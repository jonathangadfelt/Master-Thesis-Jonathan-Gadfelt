"""
Run script to reproduce the model simulations used in the thesis:
"Extreme events and demand elasticity in energy system models with high renewable penetration and limited foresight"

Quickstart
----------
1) Choose the region and technology setup in "USER CONFIG".
2) Choose which blocks to run in "RUN SWITCHES".
3) Run the script.
   Outputs:
   - Network_results/ contains saved PyPSA networks (.nc)
   - Results/ contains summary CSV tables

License
-------
Copyright c2026 Jonathan Lybecker Gadfelt < jonathan@gadfelt.dk >
CC-BY 4.0
"""

from functions_other import *
from Classes import *

print("Pypsa version:", pypsa.__version__)

# =============================================================================
# USER CONFIG
# =============================================================================

# Region
region = "ESP"

# Technology selection for capacity expansion runs
setup_exp = {
    f"{region}": {
        "OCGT": False,
        "CCGT": False,
        "battery storage": False,
        "onwind": True,
        "offwind": False,
        "solar": True,
        "electrolysis": True,
        "fuel cell": True,
        "Hydrogen storage": True,
        "Reservoir hydro storage": False,
        "load shedding": False,
    }
}

# Technology selection for dispatch runs
# Note: load shedding must be enabled here if you want LS results
setup_dispatch = {
    f"{region}": {
        "OCGT": False,
        "CCGT": False,
        "battery storage": False,
        "onwind": True,
        "offwind": False,
        "solar": True,
        "electrolysis": True,
        "fuel cell": True,
        "Hydrogen storage": True,
        "Reservoir hydro storage": False,
        "load shedding": True,
    }
}

# Years used for capacity expansion and dispatch runs
h_year_exp = 2007
d_year_exp = 2018

h_year_dispatch = 2007
d_year_dispatch = 2018

# Model year window (defines the June-to-May demand year if start_month=6)
start_month = 6

# =============================================================================
# PATHS AND DATA SELECTION
# =============================================================================

base_dir = os.getcwd()
N_results_path = os.path.join(base_dir, "Network_results")
Results_path = os.path.join(base_dir, "Results")
os.makedirs(N_results_path, exist_ok=True)

# Weather years included in the thesis runs
weather_years = All_data["solar"].index.year.unique()[:31]

# =============================================================================
# TEST NAMES
# =============================================================================

# These strings are appended to file names to keep different experiments separated
Test_name_exp = "base_test"
Test_name_dispatch = "base_mean_test"

# =============================================================================
# RUN SWITCHES
# =============================================================================

# Capacity expansion
capacity_exp = False                   # Run expansion model for all weather years
New_exp_results = False                # If True, build opt_capacities_df from saved expansion networks

# If New_exp_results is False, the script loads an existing capacities file
exp_result_key = "base_new_extended"

# Dispatch models (perfect foresight and rolling horizon)
dispatch_pf_rh = True                 # Run PF and RH dispatch for all weather years

# Which capacity statistic to use from opt_capacities_df when building dispatch networks
Q_capa = "mean"                        # Example: "mean", "75%", "60%", "35%"

# =============================================================================
# DEMAND ELASTICITY SETTINGS
# =============================================================================

# If True, adds piecewise-linear elastic demand segments in dispatch runs
PWL = False

# =============================================================================
# CAPACITY EXPANSION RUNS
# =============================================================================

# Multi-year expansion runs (saves one network per weather year)
if capacity_exp:
    exp_folder = f"N_EXP_d_{d_year_exp}_{Test_name_exp}"
    exp_path = os.path.join(N_results_path, exp_folder)
    os.makedirs(exp_path, exist_ok=True)

    CO2_limit = False

    for year in weather_years:
        N = Build_network_capacity_exp(
            weather_year=year,
            hydro_year=h_year_exp,
            demand_year=d_year_exp,
            data=All_data,
            cost_data=Cost,
            setup=setup_exp,
            start_month=start_month,
        ).network

        if CO2_limit:
            # CO2 budget defined as a fraction of demand-year emissions
            co2_budget = 0.01 * All_data["demand"].loc[
                All_data["demand"].index.year == d_year_exp, region
            ].sum() * (
                Cost.costs.at["gas", "CO2 intensity"] / (
                    Cost.costs.at["OCGT", "efficiency"] / 100
                    if Cost.costs.at["OCGT", "efficiency"] > 1
                    else Cost.costs.at["OCGT", "efficiency"]
                )
            )

            N.add(
                "GlobalConstraint",
                "emission_limit",
                carrier_attribute="co2_emissions",
                sense="<=",
                constant=co2_budget,
            )

        silent_optimize(N)

        network_name = f"N_w-{year}_d-{d_year_exp}_{region}_{Test_name_exp}.nc"
        N.export_to_netcdf(os.path.join(exp_path, network_name))
        print(f"Saved network for year {year} as {network_name}")

# =============================================================================
# BUILD OR LOAD opt_capacities_df
# =============================================================================

# opt_capacities_df is used by the dispatch models to set fixed capacities
if New_exp_results:
    folder_name = f"N_EXP_d_{d_year_exp}_{Test_name_exp}"

    # Load all saved expansion networks into a dict: {weather_year: network}
    networks_exp = load_networks(folder_name=folder_name, weather_years=weather_years)

    # Create a per-year capacity table and then compute summary statistics across years
    yearly_exp_caps_df = capacities_exp_per_year(networks_exp)
    print(yearly_exp_caps_df.head(7))

    file_name = f"Results\\opt_cap_exp_model_d{d_year_exp}_{Test_name_exp}.csv"
    opt_capacities_df = stats_exp_nets(yearly_exp_caps_df, as_columns=True, save_path=file_name)

else:
    # Load an existing capacities table created by an earlier run
    name = f"opt_cap_exp_model_d{d_year_exp}_{exp_result_key}.csv"
    opt_capacities_df = pd.read_csv(os.path.join(Results_path, name), index_col=0)

# =============================================================================
# DISPATCH RUNS (PERFECT FORESIGHT AND ROLLING HORIZON)
# =============================================================================

# Rolling horizon settings
d_horizon = 7      # days per optimization horizon
o_horizon = 0      # days of overlap between horizons

if dispatch_pf_rh:
    pf_folder = f"N_PF_d_{d_year_dispatch}_{Test_name_dispatch}"
    rh_folder = f"N_RH_d_{d_year_dispatch}_{Test_name_dispatch}"

    pf_path = os.path.join(N_results_path, pf_folder)
    rh_path = os.path.join(N_results_path, rh_folder)

    os.makedirs(pf_path, exist_ok=True)
    os.makedirs(rh_path, exist_ok=True)

    for year in weather_years:
        network_name_pf = f"N_PF_w-{year}_d-{d_year_dispatch}_{region}_{Test_name_dispatch}.nc"
        network_name_rh = f"N_RH_w-{year}_d-{d_year_dispatch}_{region}_{Test_name_dispatch}.nc"

        # Skip years that already have saved results in the PF folder
        if network_name_pf in os.listdir(pf_path):
            print(f"Networks for {year} already exists, skipping.")
            continue

        # Build PF network with fixed capacities
        N_pf_class = Build_dispatch_network(
            opt_capacities_df=opt_capacities_df.loc[Q_capa],
            weather_year=year,
            hydro_year=h_year_dispatch,
            demand_year=d_year_dispatch,
            data=All_data,
            cost_data=Cost,
            setup=setup_dispatch,
            start_month=start_month,
        )
        N_pf = N_pf_class.network

        # Build RH network with the same fixed capacities
        N_rh_class = Build_dispatch_network(
            opt_capacities_df=opt_capacities_df.loc[Q_capa],
            weather_year=year,
            hydro_year=h_year_dispatch,
            demand_year=d_year_dispatch,
            data=All_data,
            cost_data=Cost,
            setup=setup_dispatch,
            start_month=start_month,
        )
        N_rh = N_rh_class.network

        # Initial conditions and storage settings for RH
        N_rh.stores.at["Hydrogen storage", "e_cyclic"] = False
        N_rh.stores.at["Hydrogen storage", "e_initial"] = 0.65 * N_rh.stores.at["Hydrogen storage", "e_nom"]
        N_rh.stores.at["Hydrogen storage", "marginal_cost"] = 85.50

        # Optional: piecewise-linear demand response (adds multiple flexible-demand segments)
        if PWL:
            D_base = N_pf.loads_t.p_set.mean().iloc[0]

            de_shares = [0.115, 0.1, 0.1]
            a_gen_list = [1479.6, 1079.0, 98.0]
            b_gen_list = [1.2847, 0.0694, 0.1702]

            for i in range(len(de_shares)):
                p_Q = D_base * de_shares[i]
                calc_marginal_cost_quadratic = b_gen_list[i]
                calc_marginal_cost = a_gen_list[i]

                add_elastic_demand(
                    N_pf,
                    p_nom=p_Q,
                    marginal_cost=calc_marginal_cost,
                    marginal_cost_quadratic=calc_marginal_cost_quadratic,
                    segment_name=f"segment_{i+1}",
                )

                add_elastic_demand(
                    N_rh,
                    p_nom=p_Q,
                    marginal_cost=calc_marginal_cost,
                    marginal_cost_quadratic=calc_marginal_cost_quadratic,
                    segment_name=f"segment_{i+1}",
                )

        # Solve PF dispatch
        silent_optimize(N_pf)

        # Solve RH dispatch
        N_rh.optimize.optimize_with_rolling_horizon(
            snapshots=N_rh.snapshots,
            horizon=24 * d_horizon,
            overlap=24 * o_horizon,
            solver_name="gurobi",
            solver_options={"OutputFlag": 0},
            assign_all_duals=True,
        )

        # Save solved networks
        N_pf.export_to_netcdf(os.path.join(pf_path, network_name_pf))
        N_rh.export_to_netcdf(os.path.join(rh_path, network_name_rh))

        print(f"Saved PF network for {year} as {network_name_pf} in {pf_folder}")
        print(f"Saved RH network for {year} as {network_name_rh} in {rh_folder}")
