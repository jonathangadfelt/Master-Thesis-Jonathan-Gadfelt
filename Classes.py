"""
This code has been prepared for the master thesis: 
"Extreme events and demand elasticity in energy system models with high renewable penetration and limited foresight" by Jonathan Gadfelt 

Copyright c2026 Jonathan Lybecker Gadfelt < jonathan@gadfelt.dk >
This work is licensed under a Creative Commons Attribution 4.0 International Licence (CC-BY).
"""

from functions_other import *
np.random.seed(1) 

class Build_network_capacity_exp:
    def __init__(
        self,
        weather_year: int = 2011,
        hydro_year: int = 2011,
        demand_year: int = 2018,
        data: dict = None,
        cost_data: tuple = None,
        setup: dict = None,
        start_month: int = 10
    ):
        # Default technology setup
        if setup is None:
            setup = {
                'ESP': {
                    'OCGT': True,
                    'CCGT': False,
                    'battery storage': True,
                    'onwind': True,
                    'offwind': False,
                    'solar': True,
                    'electrolysis': True,
                    'fuel cell': True,
                    'Hydrogen storage': True,
                    'Reservoir hydro storage': True,
                    'load shedding': True
                }
            }

        self.weather_year = weather_year
        self.hydro_year = hydro_year
        self.demand_year = demand_year
        self.start_month = start_month
        self.setup = setup
        self.region = list(setup.keys())[0]

        self.costs = cost_data.costs
        self.cost_units = cost_data.units

        self.all_data = data if data is not None else load_all_data()

        # Extract year slices for this run
        self.data_dict = {
            self.region: self.extract_data(
                self.region,
                self.weather_year,
                self.hydro_year,
                self.demand_year,
                self.start_month
            )
        }

        # -------------------
        # BUILD NETWORK
        # -------------------
        self.network = pypsa.Network()

        # Snapshots (always tz-naive)
        start = pd.Timestamp(f"{weather_year}-{start_month:02d}-01 00:00")
        end = start + pd.DateOffset(years=1)

        snapshots = pd.date_range(start, end - pd.Timedelta(hours=1), freq="h")


        # Remove Feb 29 if present
        snapshots = snapshots[snapshots.strftime("%m-%d") != "02-29"]

        self.network.set_snapshots(snapshots)

        # -----------------------------
        # ADD CARRIERS, BUSES, LOAD
        # -----------------------------
        # Carriers
        self.carriers = [
            "electricity", "Hydrogen storage",
            "gas", "onwind", "offwind", "solar",
            "battery charge", "battery discharge", "battery storage",
            "hydro", "electrolysis", "fuel cell",
            "hydrogen", "load shedding", "demand"
        ]

        self.colors = {
            'electricity': 'orange', 'Hydrogen storage': 'purple',
            'gas': 'black', 'onwind': 'deepskyblue',
            'offwind': 'dodgerblue', 'solar': 'yellow',
            'battery charge': 'gold', 'battery discharge': 'darkorange', 'battery storage': 'goldenrod',
            'electrolysis': 'limegreen', 'fuel cell': 'darkgreen',
            'hydrogen': 'blue', 'hydro': 'slateblue',
            'load shedding': 'red', 'demand': 'gray'
        }

        self.network.add(
            "Carrier",
            self.carriers,
            color=[self.colors[c] for c in self.carriers],
            co2_emissions=[
                self.costs.at[c, "CO2 intensity"] if c in self.costs.index else 0.0
                for c in self.carriers
            ]
        )

        # Buses
        self.network.add("Bus", "electricity bus", carrier ="electricity")
        self.network.add("Bus", "hydrogen bus", carrier ="hydrogen")

        # Demand
        self.network.add(
            "Load",
            name = "load",
            carrier = "demand",
            bus="electricity bus",
            p_set=self.data_dict[self.region]["demand"].values.flatten()
        )

        # -------------------
        # ADD TECHNOLOGIES
        # -------------------
        technologies = self.setup[self.region].keys()

        for tech in technologies:
            if not self.setup[self.region][tech]:
                continue

            # OCGT, CCGT
            if tech in ["OCGT", "CCGT"]:
                self.network.add(
                    "Generator",
                    tech,
                    bus="electricity bus",
                    p_nom_extendable=True,
                    carrier="gas",
                    capital_cost=self.costs.at[tech, "capital_cost"],
                    marginal_cost=self.costs.at[tech, "marginal_cost"]
                )

            # Load Shedding
            elif tech == "load shedding":
                self.network.add(
                    "Generator",
                    tech,
                    bus="electricity bus",
                    p_nom_extendable=True,
                    marginal_cost=2000,
                    capital_cost=0,
                    carrier="load shedding"
                )

            # Solar / Onwind / Offwind
            elif tech in ["solar", "onwind", "offwind"]:
                self.network.add(
                    "Generator",
                    tech,
                    bus="electricity bus",
                    p_nom_extendable=True,
                    carrier=tech,
                    capital_cost=self.costs.at[tech, "capital_cost"],
                    marginal_cost=self.costs.at[tech, "marginal_cost"],
                    p_max_pu=self.data_dict[self.region][tech].values.flatten()
                )

            # Battery
            elif tech == "battery storage":
                self.network.add("Bus", "battery bus")

                self.network.add(
                    "Link",
                    "battery charge",
                    bus0="electricity bus",
                    bus1="battery bus",
                    carrier="battery charge",
                    p_nom_extendable=True,
                    marginal_cost=0.1,
                    capital_cost=self.costs.at["battery inverter", "capital_cost"] / 2,
                    efficiency=self.costs.at["battery inverter", "efficiency"]
                )

                self.network.add(
                    "Link",
                    "battery discharge",
                    bus0="battery bus",
                    bus1="electricity bus",
                    carrier="battery discharge",
                    p_nom_extendable=True,
                    capital_cost=self.costs.at["battery inverter", "capital_cost"] / 2,
                    efficiency=self.costs.at["battery inverter", "efficiency"]
                )

                self.network.add(
                    "Store",
                    tech,
                    bus="battery bus",
                    e_nom_extendable=True,
                    e_cyclic=True,
                    capital_cost=self.costs.at[tech, "capital_cost"]
                )

            # Electrolyzer
            elif tech == "electrolysis":
                self.network.add(
                    "Link",
                    tech,
                    bus0="electricity bus",
                    bus1="hydrogen bus",
                    carrier="electrolysis",
                    p_nom_extendable=True,
                    capital_cost=self.costs.at[tech, "capital_cost"],
                    efficiency=self.costs.at[tech, "efficiency"]
                )

            # Fuel cell
            elif tech == "fuel cell":
                self.network.add(
                    "Link",
                    tech,
                    bus0="hydrogen bus",
                    bus1="electricity bus",
                    carrier="fuel cell",
                    p_nom_extendable=True,
                    capital_cost=self.costs.at[tech, "capital_cost"] * self.costs.at[tech, "efficiency"],
                    efficiency=self.costs.at[tech, "efficiency"]
                )

            # Hydrogen storage
            elif tech == "Hydrogen storage":
                self.network.add(
                    "Store",
                    name= tech,
                    bus="hydrogen bus",
                    e_nom_extendable=True,
                    e_cyclic=True,
                    capital_cost=self.costs.at["hydrogen storage underground", "capital_cost"],
                    carrier="Hydrogen storage"
                )

            # Reservoir Hydro
            elif tech == "Reservoir hydro storage":
                self.network.add(
                    "StorageUnit",
                    tech,
                    bus="electricity bus",
                    carrier="hydro",
                    p_nom=12700,
                    p_nom_extendable=False,
                    max_hours=1300,
                    efficiency_store=0,
                    efficiency_dispatch=self.costs.at["Pumped-Storage-Hydro-bicharger", "efficiency"],
                    cyclic_state_of_charge=False,
                    state_of_charge_initial=(12700 * 1300) * 0.3,
                    inflow=self.data_dict[self.region]["hydro"].values.flatten(),
                    marginal_cost=self.costs.at["onwind", "marginal_cost"] * 1.2,
                    capital_cost=0
                )
    # HELPER METHOD TO REMOVE FEB 29
    def remove_feb29(self, series):
        return series[series.index.strftime("%m-%d") != "02-29"]

    # ------------------------
    # DATA EXTRACTION METHOD
    # ------------------------
    def extract_data(
        self,
        region: str,
        weather_year: int,
        hydro_year: int,
        demand_year: int,
        start_month: int
    ):
        extracted = {}

        # tz-naive boundaries (same is everything else)
        start_d = pd.Timestamp(f"{demand_year}-{start_month:02d}-01 00:00")
        end_d = start_d + pd.DateOffset(years=1)

        start_w = pd.Timestamp(f"{weather_year}-{start_month:02d}-01 00:00")
        end_w = start_w + pd.DateOffset(years=1)

        start_h = pd.Timestamp(f"{hydro_year}-{start_month:02d}-01 00:00")
        end_h = start_h + pd.DateOffset(years=1)

        # Demand
        extracted["demand"] = self.all_data["demand"][region].loc[
            start_d : end_d - pd.Timedelta(hours=1)
        ]

        # Solar / Wind
        for tech in ["solar", "onwind", "offwind"]:
            if region in self.all_data[tech].columns:
                extracted[tech] = self.all_data[tech][region].loc[
                    start_w : end_w - pd.Timedelta(hours=1)
                ]
                

        # Hydro inflow
        extracted["hydro"] = self.all_data["hydro_inflow"][region].loc[
            start_h : end_h - pd.Timedelta(hours=1)
        ]

        # Remove Feb 29 if present
        extracted["demand"] = self.remove_feb29(extracted["demand"])
        for tech in ["solar", "onwind", "offwind"]:
            if tech in extracted:
                extracted[tech] = self.remove_feb29(extracted[tech])
        extracted["hydro"] = self.remove_feb29(extracted["hydro"])


        return extracted

class Build_network_capacity_exp_calendar_year:
    def __init__(
        self,
        weather_year: int = 2011,
        hydro_year: int = 2011,
        demand_year: int = 2018,
        data: dict = None,
        cost_data: tuple = None,
        setup: dict = None
    ):
        if setup is None:
            setup = {
                'NOR': {
                    'OCGT': True,
                    'CCGT': False,
                    'battery storage': True,
                    'onwind': True,
                    'offwind': False,
                    'solar': True,
                    'electrolysis': True,
                    'fuel cell': True,
                    'Hydrogen storage': True,
                    'Reservoir hydro storage': True,
                    'load shedding': True
                }
            }

        self.weather_year = weather_year
        self.hydro_year = hydro_year
        self.demand_year = demand_year
        self.setup = setup
        self.region = list(setup.keys())[0]  # Single region expected

        self.costs = cost_data.costs
        self.cost_units = cost_data.units

        self.all_data = data if data is not None else load_all_data()
        self.data_dict = {self.region: self.extract_data(self.region, self.weather_year, self.hydro_year, self.demand_year)}
        
        self.network = pypsa.Network()
        
        self.hours_in_year = pd.date_range(f'{weather_year}-01-01 00:00', f'{weather_year}-12-31 23:00', freq='h')
        if len(self.hours_in_year) > 8760:
            self.hours_in_year = self.hours_in_year[self.hours_in_year.strftime('%m-%d') != '02-29']
        self.network.set_snapshots(self.hours_in_year.values)

        # Carriers
        self.carriers = [
            "electricity", "Hydrogen storage",
            "gas", "onwind", "offwind", "solar",
            "battery charge", "battery discharge", "battery storage",
            "hydro", "electrolysis", "fuel cell",
            "hydrogen", "load shedding", "demand"
        ]

        self.colors = {
            'electricity': 'orange', 'Hydrogen storage': 'purple',
            'gas': 'black', 'onwind': 'deepskyblue',
            'offwind': 'dodgerblue', 'solar': 'yellow',
            'battery charge': 'gold', 'battery discharge': 'darkorange', 'battery storage': 'goldenrod',
            'electrolysis': 'limegreen', 'fuel cell': 'darkgreen',
            'hydrogen': 'blue', 'hydro': 'slateblue',
            'load shedding': 'red', 'demand': 'gray'
        }

        self.network.add("Carrier",
            self.carriers,
            color=[self.colors[c] for c in self.carriers],
            co2_emissions=[self.costs.at[c, "CO2 intensity"] if c in self.costs.index else 0.0 for c in self.carriers]
        )


        self.network.add("Bus", 'electricity bus')
        self.network.add("Bus", 'hydrogen bus')
        self.network.add("Load", 'load',
                         bus='electricity bus',
                         p_set=self.data_dict[self.region]['demand'].values.flatten()
                         )


        technologies = self.setup[self.region].keys()
        for tech in technologies:
            if not self.setup[self.region][tech]:
                continue

            if tech in ['OCGT', 'CCGT']:
                self.network.add("Generator", tech,
                    bus='electricity bus',
                    p_nom_extendable=True,
                    carrier='gas',
                    capital_cost=self.costs.at[tech, "capital_cost"],
                    marginal_cost=self.costs.at[tech, "marginal_cost"]  # + 1.6 * np.random.uniform(1, 10) # Adding small random cost to break symmetry
                    )

            elif tech == 'load shedding':
                self.network.add("Generator", tech,
                    bus="electricity bus",
                    p_nom_extendable=True,
                    marginal_cost=10000,   # €/MWh, can adjust based on VoLL
                    capital_cost=0,
                    carrier="load shedding"
                    )
                
            elif tech == 'solar':
                self.network.add("Generator", tech,
                    bus='electricity bus',
                    p_nom_extendable=True,
                    carrier='solar',
                    capital_cost=self.costs.at[tech, "capital_cost"],
                    marginal_cost=self.costs.at[tech, "marginal_cost"],
                    p_max_pu=self.data_dict[self.region]['solar'].values.flatten()
                    )

            elif tech == 'onwind':
                self.network.add("Generator", tech,
                    bus='electricity bus',
                    p_nom_extendable=True,
                    carrier='onwind',
                    capital_cost=self.costs.at[tech, "capital_cost"],
                    marginal_cost=self.costs.at[tech, "marginal_cost"],
                    p_max_pu=self.data_dict[self.region]['onwind'].values.flatten()
                    )

            elif tech == 'offwind':
                self.network.add("Generator", tech,
                    bus='electricity bus',
                    p_nom_extendable=True,
                    carrier='offwind',
                    capital_cost=self.costs.at[tech, "capital_cost"],
                    marginal_cost=self.costs.at[tech, "marginal_cost"],
                    p_max_pu=self.data_dict[self.region]['offwind'].values.flatten()
                    )

            elif tech == 'battery storage':
                self.network.add("Bus", 'battery bus')

                self.network.add("Link", 'battery charge',
                    bus0='electricity bus',
                    bus1='battery bus',
                    carrier='battery charge',
                    p_nom_extendable=True,
                    marginal_cost=0.1, 
                    capital_cost=self.costs.at["battery inverter", "capital_cost"]/2,    # Divide by two as only one inverter will be baught in reality
                    efficiency=self.costs.at["battery inverter", "efficiency"]
                    )

                self.network.add("Link", 'battery discharge',
                    bus0='battery bus',
                    bus1='electricity bus',
                    carrier='battery discharge',
                    p_nom_extendable=True,
                    capital_cost=self.costs.at["battery inverter", "capital_cost"]/2,     # Divide by two as only one inverter will be baught in reality
                    efficiency=self.costs.at["battery inverter", "efficiency"]
                    )        

                self.network.add("Store", tech,
                    bus='battery bus',
                    e_nom_extendable=True,
                    e_cyclic=True,
                    capital_cost=self.costs.at[tech, "capital_cost"]
                    )

            # elif tech == 'battery storage':
            #     max_h = 6  # Max hours of storage
            #     self.network.add("StorageUnit", "battery",
            #         bus='electricity bus', carrier='battery',
            #         p_nom_extendable=True, 
            #         max_hours=max_h,
            #         efficiency_store=self.costs.at["battery inverter", "efficiency"],
            #         efficiency_dispatch=self.costs.at["battery inverter", "efficiency"],
            #         capital_cost=self.costs.at["battery inverter", "capital_cost"] + self.costs.at["battery storage", "capital_cost"] * max_h,
            #         #capital_cost= max_h * self.costs.at["battery storage", "capital_cost"],
            #         cyclic_state_of_charge=False
            #         )

            elif tech == 'electrolysis':
                self.network.add("Link", tech,
                    bus0='electricity bus',
                    bus1='hydrogen bus',
                    carrier='electrolysis',
                    p_nom_extendable=True,
                    capital_cost=self.costs.at[tech, "capital_cost"],
                    efficiency=self.costs.at[tech, "efficiency"]
                    )

            elif tech == 'fuel cell':
                self.network.add("Link", tech,
                    bus0='hydrogen bus',
                    bus1='electricity bus',
                    carrier='fuel cell',
                    p_nom_extendable=True,
                    capital_cost=self.costs.at[tech, "capital_cost"] * self.costs.at[tech, "efficiency"],
                    efficiency=self.costs.at[tech, "efficiency"]
                    )

            elif tech == 'Hydrogen storage':
                self.network.add("Store", tech,
                    bus='hydrogen bus',
                    e_nom_extendable=True,
                    e_cyclic=True,
                    #capital_cost=self.costs.at["H2 (l) storage tank", "capital_cost"],
                    capital_cost=self.costs.at["hydrogen storage underground", "capital_cost"],                  
                    carrier='hydrogen storage'
                    )
                
            elif tech == 'Reservoir hydro storage':
                self.network.add("StorageUnit", tech,
                    bus='electricity bus',
                    carrier='hydro',
                    p_nom_extendable=False,
                    p_nom = 12700,  # 12 GW
                    max_hours=1300,
                    efficiency_store=0,
                    efficiency_dispatch=self.costs.at["Pumped-Storage-Hydro-bicharger", "efficiency"],
                    cyclic_state_of_charge=False,
                    state_of_charge_initial= (12700 * 1300)*0.3 ,  # Initial storage capacity in MWh
                    inflow=self.data_dict[self.region]['hydro'].values.flatten(),
                    marginal_cost=self.costs.at["onwind", "marginal_cost"]*1.2,  # higher than wind to prioritize wind usage
                    capital_cost=0
                    )

    def extract_data(self, region: str, weather_year: int, hydro_year: int, demand_year: int):
        extracted = {}
        if demand_year not in self.all_data["demand"].index.year:
            print(f"Demand year {demand_year} not in data. Using 2017 instead.")
            demand_year = 2017
        if weather_year not in self.all_data["solar"].index.year:
            print(f"Weather year {weather_year} not in data. Using 2012 instead.")
            weather_year = 2012
        if hydro_year not in self.all_data["hydro_inflow"].index.year:
            print(f"Hydro year {hydro_year} not in data. Using 2011 instead.")
            hydro_year = 2011

        if region in self.all_data["demand"].columns:
            demand_series = self.all_data["demand"].loc[self.all_data["demand"].index.year == demand_year, region]
            extracted["demand"] = demand_series[demand_series.index.strftime('%m-%d') != '02-29'][:8760]

        for carrier in ["solar", "onwind", "offwind"]:
            if region in self.all_data[carrier].columns:
                weather_series = self.all_data[carrier].loc[self.all_data[carrier].index.year == weather_year, region]
                extracted[carrier] = weather_series[weather_series.index.strftime('%m-%d') != '02-29'][:8760]

        if region in self.all_data["hydro_inflow"].columns:
            hydro_series = self.all_data["hydro_inflow"].loc[self.all_data["hydro_inflow"].index.year == hydro_year, region]
            extracted["hydro"] = hydro_series[hydro_series.index.strftime('%m-%d') != '02-29'][:8760]

        return extracted  

class Build_dispatch_network:
    def __init__(
        self,
        opt_capacities_df: pd.DataFrame,
        weather_year: int = 2011,
        hydro_year: int = 2011,
        demand_year: int = 2018,
        data: dict = None,
        cost_data: tuple = None,
        setup: dict = None,
        start_month: int = 6   # add start_month for consistency
    ):
        if setup is None:
            setup = {
                'ESP': {
                    'OCGT': True,
                    'CCGT': False,
                    'battery storage': True,
                    'onwind': True,
                    'offwind': False,
                    'solar': True,
                    'electrolysis': False,
                    'fuel cell': False,
                    'Hydrogen storage': False,
                    'Reservoir hydro storage': True,
                    'load shedding': True
                }
            }

        self.weather_year = weather_year
        self.hydro_year = hydro_year
        self.demand_year = demand_year
        self.start_month = start_month
        self.setup = setup
        self.region = list(setup.keys())[0]

        self.costs = cost_data.costs
        self.cost_units = cost_data.units
        self.opt_caps = opt_capacities_df

        # Load data (already tz-naive)
        self.all_data = data if data is not None else load_all_data()

        # Updated extraction logic
        self.data_dict = {
            self.region: self.extract_data(
                self.region,
                self.weather_year,
                self.hydro_year,
                self.demand_year,
                self.start_month
            )
        }

        # -----------------------------
        # SNAPSHOTS: remove Feb 29
        # -----------------------------
        self.network = pypsa.Network()

        start = pd.Timestamp(f"{weather_year}-{start_month:02d}-01 00:00")
        end = start + pd.DateOffset(years=1)

        snapshots = pd.date_range(start, end - pd.Timedelta(hours=1), freq="h")

        # drop leap day if present
        snapshots = snapshots[snapshots.strftime("%m-%d") != "02-29"]

        self.network.set_snapshots(snapshots)

        # -----------------------------
        # ADD CARRIERS, BUSES, LOAD
        # -----------------------------
        # Carriers
        self.carriers = [
            "electricity", "Hydrogen storage",
            "gas", "onwind", "offwind", "solar",
            "battery charge", "battery discharge", "battery storage",
            "hydro", "electrolysis", "fuel cell",
            "hydrogen", "load shedding", "demand"
        ]

        self.colors = {
            'electricity': 'orange', 'Hydrogen storage': 'purple',
            'gas': 'black', 'onwind': 'deepskyblue',
            'offwind': 'dodgerblue', 'solar': 'yellow',
            'battery charge': 'gold', 'battery discharge': 'darkorange', 'battery storage': 'goldenrod',
            'electrolysis': 'limegreen', 'fuel cell': 'darkgreen',
            'hydrogen': 'blue', 'hydro': 'slateblue',
            'load shedding': 'red', 'demand': 'gray'
        }

        self.network.add(
            "Carrier",
            self.carriers,
            color=[self.colors[c] for c in self.carriers],
            co2_emissions=[
                self.costs.at[c, "CO2 intensity"] if c in self.costs.index else 0.0
                for c in self.carriers
            ]
        )

        self.network.add("Bus", 'electricity bus', carrier ="electricity")
        self.network.add("Bus", 'hydrogen bus', carrier ="hydrogen")

        # Load
        self.network.add(
            "Load",
            name = "load",
            carrier = "demand",
            bus="electricity bus",
            p_set=self.data_dict[self.region]["demand"].values.flatten()
        )

        # -------------------------------------
        # ADD TECHNOLOGIES (CAPACITIES FIXED)
        # -------------------------------------
        for tech, active in self.setup[self.region].items():
            if not active:
                continue

            if tech in ['OCGT', 'CCGT', 'onwind', 'offwind', 'solar']:
                self.network.add(
                    "Generator",
                    tech,
                    bus='electricity bus',
                    p_nom=self.opt_caps.at[tech],
                    p_nom_extendable=False,
                    carrier=tech if tech in ['solar', 'onwind', 'offwind'] else 'gas',
                    capital_cost=0,
                    marginal_cost=self.costs.at[tech, "marginal_cost"],
                    p_max_pu=(
                        self.data_dict[self.region][tech].values.flatten()
                        if tech in ['solar', 'onwind', 'offwind']
                        else None
                    )
                )

            elif tech == "load shedding":
                self.network.add(
                    "Generator",
                    tech,
                    bus="electricity bus",
                    p_nom_extendable=True,
                    marginal_cost=10000,
                    capital_cost=0,
                    carrier="load shedding"
                )

            elif tech == "battery storage":
                self.network.add("Bus", 'battery bus')

                self.network.add(
                    "Link",
                    "battery charge",
                    bus0="electricity bus",
                    bus1="battery bus",
                    carrier="battery charge",
                    p_nom=self.opt_caps.at["battery charge"],
                    p_nom_extendable=False,
                    capital_cost=0,
                    efficiency=self.costs.at["battery inverter", "efficiency"]
                )

                self.network.add(
                    "Link",
                    "battery discharge",
                    bus0="battery bus",
                    bus1="electricity bus",
                    carrier="battery discharge",
                    p_nom=self.opt_caps.at["battery discharge"],
                    p_nom_extendable=False,
                    capital_cost=0,
                    efficiency=self.costs.at["battery inverter", "efficiency"]
                )

                self.network.add(
                    "Store",
                    tech,
                    bus="battery bus",
                    carrier = "battery storage",
                    e_nom=self.opt_caps.at[tech],
                    e_nom_extendable=False,
                    e_cyclic=False,
                    capital_cost=0
                )

            elif tech == "electrolysis":
                self.network.add(
                    "Link",
                    tech,
                    bus0="electricity bus",
                    bus1="hydrogen bus",
                    carrier="electrolysis",
                    p_nom=self.opt_caps.at[tech],
                    p_nom_extendable=False,
                    capital_cost=0,
                    efficiency=self.costs.at[tech, 'efficiency']
                )

            elif tech == "fuel cell":
                self.network.add(
                    "Link",
                    tech,
                    bus0="hydrogen bus",
                    bus1="electricity bus",
                    carrier="fuel cell",
                    p_nom=self.opt_caps.at[tech],
                    p_nom_extendable=False,
                    capital_cost=0,
                    efficiency=self.costs.at[tech, 'efficiency']
                )

            elif tech == "Hydrogen storage":
                self.network.add(
                    "Store",
                    tech,
                    bus="hydrogen bus",
                    e_nom=self.opt_caps.at[tech],
                    e_nom_extendable=False,
                    e_cyclic=True,
                    capital_cost=0,
                    marginal_cost=0,
                    carrier="Hydrogen storage"
                )

            elif tech == "Reservoir hydro storage":
                self.network.add(
                    "StorageUnit",
                    tech,
                    bus="electricity bus",
                    carrier="hydro",
                    p_nom=12700,
                    p_nom_extendable=False,
                    max_hours=1300,
                    efficiency_store=0,
                    efficiency_dispatch=self.costs.at["Pumped-Storage-Hydro-bicharger", "efficiency"],
                    cyclic_state_of_charge=False,
                    inflow=self.data_dict[self.region]["hydro"].values.flatten(),
                    state_of_charge_initial=(12700 * 1300) * 0.3,
                    marginal_cost=self.costs.at["OCGT", "marginal_cost"] * 0.5,
                    spill_cost=100,
                    capital_cost=0
                )
    

    # HELPER METHOD TO REMOVE FEB 29
    def remove_feb29(self, series):
        return series[series.index.strftime("%m-%d") != "02-29"]

    # ------------------------
    # DATA EXTRACTION METHOD
    # ------------------------
    def extract_data(
        self,
        region: str,
        weather_year: int,
        hydro_year: int,
        demand_year: int,
        start_month: int
    ):
        extracted = {}

        # tz-naive boundaries (same is everything else)
        start_d = pd.Timestamp(f"{demand_year}-{start_month:02d}-01 00:00")
        end_d = start_d + pd.DateOffset(years=1)

        start_w = pd.Timestamp(f"{weather_year}-{start_month:02d}-01 00:00")
        end_w = start_w + pd.DateOffset(years=1)

        start_h = pd.Timestamp(f"{hydro_year}-{start_month:02d}-01 00:00")
        end_h = start_h + pd.DateOffset(years=1)

        # Demand
        extracted["demand"] = self.all_data["demand"][region].loc[
            start_d : end_d - pd.Timedelta(hours=1)
        ]

        # Solar / Wind
        for tech in ["solar", "onwind", "offwind"]:
            if region in self.all_data[tech].columns:
                extracted[tech] = self.all_data[tech][region].loc[
                    start_w : end_w - pd.Timedelta(hours=1)
                ]
                

        # Hydro inflow
        extracted["hydro"] = self.all_data["hydro_inflow"][region].loc[
            start_h : end_h - pd.Timedelta(hours=1)
        ]

        # Remove Feb 29 if present
        extracted["demand"] = self.remove_feb29(extracted["demand"])
        for tech in ["solar", "onwind", "offwind"]:
            if tech in extracted:
                extracted[tech] = self.remove_feb29(extracted[tech])
        extracted["hydro"] = self.remove_feb29(extracted["hydro"])


        return extracted

class Build_dispatch_network_calendar_year:
    def __init__(
        self,
        opt_capacities_df: pd.DataFrame,
        weather_year: int = 2011,
        hydro_year: int = 2011,
        demand_year: int = 2018,
        data: dict = None,
        cost_data: tuple = None,
        setup: dict = None
    ):
        if setup is None:
            setup = {
                'ESP': {
                    'OCGT': True,
                    'CCGT': False,
                    'battery storage': True,
                    'onwind': True,
                    'offwind': False,
                    'solar': True,
                    'electrolysis': False,
                    'fuel cell': False,
                    'Hydrogen storage': False,
                    'Reservoir hydro storage': True,
                    'load shedding': True
                }
            }

        self.weather_year = weather_year
        self.hydro_year = hydro_year
        self.demand_year = demand_year
        self.setup = setup
        self.region = list(setup.keys())[0]

        self.costs = cost_data.costs
        self.cost_units = cost_data.units

        self.opt_caps = opt_capacities_df

        self.all_data = data if data is not None else load_all_data()
        self.data_dict = {self.region: self.extract_data(self.region, self.weather_year, self.hydro_year, self.demand_year)}

        self.network = pypsa.Network()
        self.hours_in_year = pd.date_range(f'{weather_year}-01-01 00:00', f'{weather_year}-12-31 23:00', freq='h')
        if len(self.hours_in_year) > 8760:
            self.hours_in_year = self.hours_in_year[self.hours_in_year.strftime('%m-%d') != '02-29']
        self.network.set_snapshots(self.hours_in_year.values)

        self.carriers = ['gas', 'onwind', 'offwind', 'solar', 'battery charge', 'battery discharge', 'electrolysis', 'fuel cell', 'hydrogen', 'hydro', 'load shedding']

        self.colors = {
            'gas': 'gray', 'onwind': 'lightblue', 'offwind': 'dodgerblue', 'solar': 'orange',
            'battery charge': 'gold', 'battery discharge': 'darkorange', 'electrolysis': 'green',
            'fuel cell': 'limegreen', 'hydrogen': 'deepskyblue', 'hydro': 'slateblue', 'load shedding': 'red'
        }

        self.network.add("Carrier", self.carriers, color=[self.colors[c] for c in self.carriers],
                         co2_emissions=[self.costs.at[c, "CO2 intensity"] if c in self.costs.index else 0.0 for c in self.carriers])

        self.network.add("Bus", 'electricity bus')
        self.network.add("Bus", 'hydrogen bus')
        self.network.add("Load", 'load', bus='electricity bus', p_set=self.data_dict[self.region]['demand'].values.flatten())


        for tech, active in self.setup[self.region].items():
            if not active:
                continue

            if tech in ['OCGT', 'CCGT', 'onwind', 'offwind', 'solar']:
                self.network.add("Generator", tech,
                    bus='electricity bus',
                    p_nom=self.opt_caps.at[tech],
                    p_nom_extendable=False,
                    carrier=tech if tech in ['solar', 'onwind', 'offwind'] else 'gas',
                    capital_cost=0,
                    marginal_cost=self.costs.at[tech, "marginal_cost"],
                    p_max_pu=self.data_dict[self.region][tech].values.flatten() if tech != 'OCGT' and tech != 'CCGT' else None)

            elif tech == 'load shedding':
                # Add load shedding generator
                self.network.add("Generator", tech,
                    bus="electricity bus",
                    p_nom_extendable=True,
                    marginal_cost= 10000, # 10k this is default in many european countries
                    capital_cost=0,
                    carrier="load shedding")

            elif tech == 'battery storage':
                self.network.add("Bus", 'battery bus')
                self.network.add("Link", 'battery charge',
                    bus0='electricity bus', bus1='battery bus',
                    carrier='battery charge',
                    p_nom=self.opt_caps.at['battery charge'],
                    p_nom_extendable=False,
                    capital_cost=0,
                    efficiency=self.costs.at['battery inverter', 'efficiency'])
                
                self.network.add("Link", 'battery discharge',
                    bus0='battery bus', bus1='electricity bus',
                    carrier='battery discharge',
                    p_nom=self.opt_caps.at['battery discharge'],
                    p_nom_extendable=False,
                    capital_cost=0,
                    efficiency=self.costs.at['battery inverter', 'efficiency'])
                
                self.network.add("Store", tech,
                    bus='battery bus',
                    e_nom=self.opt_caps.at[tech],
                    e_nom_extendable=False,
                    e_cyclic=False,
                    capital_cost=0)

            elif tech == 'electrolysis':
                self.network.add("Link", tech,
                    bus0='electricity bus', bus1='hydrogen bus',
                    carrier='electrolysis',
                    p_nom=self.opt_caps.at[tech],
                    p_nom_extendable=False,
                    capital_cost=0,
                    efficiency=self.costs.at[tech, 'efficiency'])

            elif tech == 'fuel cell':
                self.network.add("Link", tech,
                    bus0='hydrogen bus', bus1='electricity bus',
                    carrier='fuel cell',
                    p_nom=self.opt_caps.at[tech],
                    p_nom_extendable=False,
                    capital_cost=0,
                    efficiency=self.costs.at[tech, 'efficiency'])

            elif tech == 'Hydrogen storage':
                self.network.add("Store", tech,
                    bus='hydrogen bus',
                    e_nom=self.opt_caps.at[tech],
                    e_nom_extendable=False,
                    e_cyclic=True,
                    #e_initial=0.2*self.opt_caps.at[tech],
                    marginal_cost=0,
                    capital_cost=0,
                    carrier='hydrogen storage')

            elif tech == 'Reservoir hydro storage':
                self.network.add("StorageUnit", tech,
                    bus='electricity bus',
                    carrier='hydro',
                    p_nom=12700,
                    p_nom_extendable=False,
                    max_hours=1300,
                    efficiency_store=0,
                    efficiency_dispatch=self.costs.at['Pumped-Storage-Hydro-bicharger', 'efficiency'],
                    cyclic_state_of_charge=False,
                    inflow=self.data_dict[self.region]['hydro'].values.flatten(),
                    state_of_charge_initial= (12700 * 1300)*0.3 ,  # Initial storage capacity in MWh
                    marginal_cost=self.costs.at["OCGT", "marginal_cost"]*0.5,  
                    spill_cost = 100,
                    capital_cost=0)
    
    def extract_data(self, region: str, weather_year: int, hydro_year: int, demand_year: int):
        extracted = {}
        if demand_year not in self.all_data["demand"].index.year:
            print(f"Demand year {demand_year} not in data. Using 2017 instead.")
            demand_year = 2017
        if weather_year not in self.all_data["solar"].index.year:
            print(f"Weather year {weather_year} not in data. Using 2012 instead.")
            weather_year = 2012
        if hydro_year not in self.all_data["hydro_inflow"].index.year:
            print(f"Hydro year {hydro_year} not in data. Using 2011 instead.")
            hydro_year = 2011

        if region in self.all_data["demand"].columns:
            demand_series = self.all_data["demand"].loc[self.all_data["demand"].index.year == demand_year, region]
            extracted["demand"] = demand_series[demand_series.index.strftime('%m-%d') != '02-29'][:8760]

        for carrier in ["solar", "onwind", "offwind"]:
            if region in self.all_data[carrier].columns:
                weather_series = self.all_data[carrier].loc[self.all_data[carrier].index.year == weather_year, region]
                extracted[carrier] = weather_series[weather_series.index.strftime('%m-%d') != '02-29'][:8760]

        if region in self.all_data["hydro_inflow"].columns:
            hydro_series = self.all_data["hydro_inflow"].loc[self.all_data["hydro_inflow"].index.year == hydro_year, region]
            extracted["hydro"] = hydro_series[hydro_series.index.strftime('%m-%d') != '02-29'][:8760]

        return extracted    

