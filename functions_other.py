"""
This code has been prepared for the master thesis "Extreme events and demand elasticity in energy system models with high renewable penetration and limited foresight" by Jonathan Gadfelt 

Copyright c2026 Jonathan Lybecker Gadfelt < jonathan@gadfelt.dk >
This work is licensed under a Creative Commons Attribution 4.0 International Licence (CC-BY).
"""

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib as mpl
from matplotlib.colors import Normalize, LogNorm
from matplotlib import colors as mcolors
from matplotlib import dates as mdates
import numpy as np
import os
import pypsa
import sys
import logging
import pickle
from contextlib import redirect_stdout
import tqdm
from pathlib import Path
from typing import Sequence, Any, Tuple, Optional, Dict, List, NamedTuple, Union, Callable
from pypsa import Network
import logging
from types import MethodType
from Classes import *

default_figsize = (8, 6)

np.set_printoptions(suppress=True)
FIGURES_DIR = Path.cwd() / "Figures"
FIGURES_DIR.mkdir(exist_ok=True)

region = "ESP"          # Region for hydro inflow data

# Default weather, hydro and demand years used when a single year is selected
w_year_exp = 2009
h_year_exp = 2007
d_year_exp = 2018

w_year_dispatch = 2009
h_year_dispatch = 2007
d_year_dispatch = 2018

##############################################################
"  ____________________ LOAD ALL DATA ____________________ "
##############################################################

# New function to load all data withou timezone indices
def load_all_data():
    data = {
        "solar": pd.read_csv("Data/pv_optimal_NOR_ESP.csv", sep=";", index_col=0, parse_dates=True),
        "onwind": pd.read_csv("Data/onshore_wind_1979-2017_NOR_ESP.csv", sep=";", index_col=0, parse_dates=True),
        "offwind": pd.read_csv("Data/offshore_wind_1979-2017_NOR.csv", sep=";", index_col=0, parse_dates=True),
        "demand": pd.read_csv("Data/load_data_actual_NOR_ES.csv", sep=";", index_col=0, parse_dates=True)
    }

    # Rename demand columns
    data["demand"] = data["demand"].rename(columns={
        "NO_load_actual_entsoe_transparency": "NOR",
        "ES_load_actual_entsoe_transparency": "ESP"
    }).ffill().bfill()

    # Hydro inflow conversion
    def convert_hydro_to_hourly(path, label):
        df = pd.read_csv(path)
        df['date'] = pd.to_datetime(df[['Year', 'Month', 'Day']])
        df = df[df['date'].dt.strftime('%m-%d') != '02-29']
        df['Hourly_MW'] = round(df['Inflow [GWh]'] * 1000 / 24)

        df_hourly = pd.DataFrame({
            'datetime': df['date'].repeat(24) + pd.to_timedelta(list(range(24)) * len(df), unit='h'),
            label: df['Hourly_MW'].repeat(24).values
        }).set_index('datetime')

        return df_hourly

    es_hourly = convert_hydro_to_hourly("Data/Hydro_Inflow_ES.csv", 'ESP')
    no_hourly = convert_hydro_to_hourly("Data/Hydro_Inflow_NO.csv", 'NOR')
    data["hydro_inflow"] = pd.concat([es_hourly, no_hourly], axis=1)

    # -------------------------
    # MAKE ALL INDICES TZ-NAIVE
    # -------------------------
    for key, df in data.items():
        idx = df.index
        if idx.tz is not None:
            idx = idx.tz_convert(None)
        data[key] = df.copy()
        data[key].index = idx

    return data

def load_or_build_events(path, build_func, force=False):    # Use only force=True when wanting to overwrite existing events
    if os.path.exists(path) and not force:
        with open(path, "rb") as f:
            return pickle.load(f)
    events = build_func()
    assert isinstance(events, dict), "Event builder must return a dict"
    with open(path, "wb") as f:
        pickle.dump(events, f)
    return events

def filter_networks_by_years(
    networks: Dict[int, Network],
    filtered_years: List[int],
) -> Dict[int, Network]:
    """
    Return a subset of networks restricted to filtered_years.
    """
    return {y: networks[y] for y in filtered_years}

def slice_months_cross_year(
    s: pd.Series,
    start_month: int = 9,
    end_month: int = 3,
) -> pd.Series:
    """
    Keep only months from start_month..12 and 1..end_month.
    Example: Sep–Mar.
    """
    m = s.index.month
    return s.loc[(m >= start_month) | (m <= end_month)]


##############################################################
" ____________________ COST DATA CLASS ____________________ "
##############################################################

class CostGeneration:
    def __init__(self, year: int = 2020):
        self.year = year
        self.costs, self.units = self.cost_data()

    def cost_data(self):
        url = f"https://raw.githubusercontent.com/PyPSA/technology-data/master/outputs/costs_{self.year}.csv"
        df = pd.read_csv(url, index_col=[0, 1])

        df.loc[df.unit.str.contains("/kW"), "value"] *= 1e3
        df.unit = df.unit.str.replace("/kW", "/MW")

        # Save units before dropping
        unit_df = df["unit"].copy()
        
        defaults = {
            "FOM": 0,
            "VOM": 0,
            "efficiency": 1,
            "fuel": 0,
            "investment": 0,
            "lifetime": 25,
            "CO2 intensity": 0,
            "discount rate": 0.07,
        }

        costs = df.value.unstack().fillna(defaults)

        costs.at["OCGT", "fuel"] = costs.at["gas", "fuel"]
        costs.at["CCGT", "fuel"] = costs.at["gas", "fuel"]
        costs.at["OCGT", "CO2 intensity"] = costs.at["gas", "CO2 intensity"]
        costs.at["CCGT", "CO2 intensity"] = costs.at["gas", "CO2 intensity"]


        costs["marginal_cost"] = costs["VOM"] + costs["fuel"] / costs["efficiency"]
        annuity = costs.apply(lambda x: self.annuity(x["discount rate"], x["lifetime"]), axis=1)
        costs["capital_cost"] = (annuity + costs["FOM"] / 100) * costs["investment"]


        return costs, unit_df

    @staticmethod
    def annuity(r, n):
        """ Calculate the annuity factor for an asset with lifetime n years and
        discount rate r """
        return r / (1.0 - 1.0 / (1.0 + r) ** n)
All_data = load_all_data()
Cost = CostGeneration(year=2030)
weather_years = All_data['solar'].index.year.unique()[:31]

def print_costs(network):
    # helper to ensure columns exist
    def ensure_cols(df, cols):
        for c in cols:
            if c not in df.columns:
                df[c] = np.nan
        return df

    wanted = ["carrier", "capital_cost", "marginal_cost"]

    # Generators
    gens = network.generators.copy() if hasattr(network, "generators") else pd.DataFrame()
    gens = gens.loc[:, [c for c in gens.columns if c in wanted]] if not gens.empty else pd.DataFrame(columns=wanted)
    gens = ensure_cols(gens, wanted)
    gens["type"] = "generator"

    # Stores (Store components)
    stores = pd.DataFrame(columns=wanted)
    if hasattr(network, "stores") and len(network.stores):
        stores = network.stores.copy()
        stores = stores.loc[:, [c for c in stores.columns if c in wanted]] if not stores.empty else pd.DataFrame(columns=wanted)
        stores = ensure_cols(stores, wanted)
        stores["type"] = "store"

    # StorageUnits (StorageUnit components)
    sus = pd.DataFrame(columns=wanted)
    if hasattr(network, "storage_units") and len(network.storage_units):
        sus = network.storage_units.copy()
        sus = sus.loc[:, [c for c in sus.columns if c in wanted]] if not sus.empty else pd.DataFrame(columns=wanted)
        sus = ensure_cols(sus, wanted)
        sus["type"] = "storage_unit"

    # Links
    links = pd.DataFrame(columns=wanted)
    if hasattr(network, "links") and len(network.links):
        links = network.links.copy()
        links = links.loc[:, [c for c in links.columns if c in wanted]] if not links.empty else pd.DataFrame(columns=wanted)
        links = ensure_cols(links, wanted)
        links["type"] = "link"

    # Combine (preserve original index as name)
    df = pd.concat([gens, stores, sus, links], sort=False)
    df = df.reset_index().rename(columns={"index": "name"})

    # Print nicely
    pd.set_option("display.max_rows", None)
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 120)
    pd.set_option("display.float_format", "{:,.2f}".format)

    print(df[["name", "type", "carrier", "capital_cost", "marginal_cost"]])

    return df

##############################################################
" ___________ CAPACITIES PER YEAR / OPT CAPACITIES DF ______________ "
##############################################################
# create results df for cost and objective comparison
def build_cost_objective_comparison_df(
    years,
    networks_pf,
    networks_rh,
):
    def total_cost(net):
        return (
            net.buses_t.marginal_price["electricity bus"]
            * net.loads_t.p_set["load"]
        ).sum() / 1e6

    def ls_cost(net):
        if "load shedding" in net.generators.index:
            p = net.generators_t.p["load shedding"]
            c = net.generators.at["load shedding", "marginal_cost"]
            return (p * c).sum() / 1e6
        return 0.0

    results = []
    for year in years:
        pf_net = networks_pf[year]
        rh_net = networks_rh[year]

        pf_cost = total_cost(pf_net)
        rh_cost = total_cost(rh_net)

        results.append({
            "year": year,
            "Objective PF value MEUR": round(pf_net.objective / 1e6, 2),
            "Objective RH value MEUR": round(rh_net.statistics.system_cost().sum() / 1e6, 2),
            "PF_cost_MEUR": round(pf_cost, 1),
            "RH_cost_MEUR": round(rh_cost, 1),
            "Diff cost_MEUR": round(rh_cost - pf_cost, 1),
            "PF_load_shedding_cost_MEUR": round(ls_cost(pf_net), 1),
            "RH_load_shedding_cost_MEUR": round(ls_cost(rh_net), 1),
        })

    results_df = (
        pd.DataFrame(results)
        .assign(
            Diff_obj_MEUR=lambda df: (
                df["Objective RH value MEUR"]
                - df["Objective PF value MEUR"]
            ).round(2)
        )
        .pipe(lambda df: df[sorted(df.columns)])
        .set_index("year")
    )

    return results_df


# create table with capacities per year for exp model
def capacities_exp_per_year(networks, flatten_columns=False):
    results_exp = {
        "generators": pd.DataFrame(index=weather_years),
        "links": pd.DataFrame(index=weather_years),
        "stores": pd.DataFrame(index=weather_years),
    }

    for year in weather_years:
        net = networks[year]

        # Store capacities
        gen = net.generators["p_nom_opt"].rename("p_nom_opt")
        links = net.links["p_nom_opt"].rename("p_nom_opt")
        stores = net.stores["e_nom_opt"].rename("e_nom_opt")

        results_exp["generators"].loc[year, gen.index] = gen.values
        results_exp["links"].loc[year, links.index] = links.values
        results_exp["stores"].loc[year, stores.index] = stores.values

    # Save to CSV or analyze
    results_df = pd.concat(results_exp, axis=1).round(2)
    
    if flatten_columns:
        # Flatten multi-level columns to show only tech names
        results_df.columns = results_df.columns.get_level_values(1)
    
    return results_df


# Create Stats opt_df for exp model
def stats_exp_nets(df, save_path=None, as_columns=True):
    """
    Compute descriptive statistics for a results DataFrame.

    Statistics include mean, standard deviation, selected percentiles,
    and minimum and maximum values for each component.

    Parameters
    ----------
    df : pandas.DataFrame
        Input results table with components as columns.
    save_path : str or None
        Optional file path for saving the output as a CSV file.
    as_columns : bool
        If True, statistics are returned as rows and components as columns.
        If False, components are returned as rows and statistics as columns.

    Returns
    -------
    pandas.DataFrame
        Table of descriptive statistics.
    """
    s = round(
        df.describe(
            percentiles=[.25, .45, .5, .55, .60, .65, .70, .75]
        ).loc[
            ['mean', 'std', 'min',
             '25%', '45%', '50%',
             '55%', '60%', '65%', '70%', '75%', 'max']
        ],
        1
    )

    # Use the component name as column label when a MultiIndex is present
    flat = [col[-1] if isinstance(col, tuple) else str(col) for col in s.columns]
    s.columns = flat

    # Set output orientation
    out = s if as_columns else s.T

    # Optionally save results to disk
    if save_path:
        out.to_csv(save_path)

    return out

def stats_exp_nets_extended(df, save_path=None, as_columns=True):
    """
    Compute a set of descriptive statistics for a results DataFrame.

    Statistics include mean, standard deviation, selected percentiles,
    and minimum and maximum values for each component.

    Parameters
    ----------
    df : pandas.DataFrame
        Input results table with components as columns.
    save_path : str or None
        Optional file path for saving the output as a CSV file.
    as_columns : bool
        If True, statistics are returned as rows and components as columns.
        If False, components are returned as rows and statistics as columns.

    Returns
    -------
    pandas.DataFrame
        Table of descriptive statistics.
    """
    s = round(
        df.describe(
            percentiles=[.25, .30, .35, .40, .45, .5, .55, .60, .65, .70, .75]
        ).loc[
            ['mean', 'std', 'min',
             '25%', '30%', '35%', '40%', '45%', '50%',
             '55%', '60%', '65%', '70%', '75%', 'max']
        ],
        1
    )

    # Use the component name as column label when a MultiIndex is present
    flat = [col[-1] if isinstance(col, tuple) else str(col) for col in s.columns]
    s.columns = flat

    # Set output orientation
    out = s if as_columns else s.T

    # Optionally save results to disk
    if save_path:
        out.to_csv(save_path)

    return out


##############################################################
" ____________________ ROLLING HORIZON ____________________ "
##############################################################

def rh_pf_test_yearly(test_year, horizon_days=7, overlap_days=0, 
    capacities: str = "75%", opt_capacities_df: pd.DataFrame = None):    
    d_horizon = horizon_days # days in horizon
    o_horizon = overlap_days # days of overlap in rh

    opt_df = opt_capacities_df.loc[capacities]

    N_pf_class = Build_dispatch_network(
        opt_capacities_df=opt_df,
        weather_year=test_year, hydro_year=h_year_dispatch, demand_year=d_year_dispatch,
        data=All_data, cost_data=Cost, setup=setup_dispatch
    )
    N_pf = N_pf_class.network

    silent_optimize(N_pf)

    N_rh_class = Build_dispatch_network(
        opt_capacities_df= opt_df,
        weather_year=test_year, hydro_year=h_year_dispatch, demand_year=d_year_dispatch,
        data=All_data, cost_data=Cost, setup=setup_dispatch
    )
    N_rh = N_rh_class.network

    N_rh.stores.at['Hydrogen storage', 'marginal_cost'] = 85.5
    N_rh.stores.at['Hydrogen storage', 'e_cyclic'] = False


    # Run the rolling-horizon optimization
    N_rh.optimize.optimize_with_rolling_horizon(
        snapshots=N_rh.snapshots,
        horizon= 24 * d_horizon,
        overlap= 24 * o_horizon,
        solver_name="gurobi",
        solver_options={"OutputFlag": 0},
        assign_all_duals=True,
        log_to_console=False
    )

    return N_pf, N_rh

##############################################################
" ____________________ PRINT RESULTS FUNCTION ____________________ "
##############################################################


def df_to_latex_table(
    df: pd.DataFrame,
    caption: str,
    label: str,
    *,
    index: bool = True,
    float_fmt: Union[str, Callable[[float], str]] = "{:.2f}".format,
    int_fmt: str = "{:,}",
    na_rep: str = "",
    escape: bool = True,
    placement: str = "ht",
    centering: bool = True,
    font_size_cmd: Optional[str] = r"\small",
    column_format: Optional[str] = None,
    note: Optional[str] = None,
) -> str:
    """
    Return a complete LaTeX table environment as a multi-line string.

    Notes:
    - Works on older pandas versions: does not use to_latex(booktabs=...).
    - Converts \\hline to \\toprule/\\midrule/\\bottomrule (requires \\usepackage{booktabs}).
    - To view with line breaks in Jupyter: wrap the call in print(...).
    """

    df2 = df.copy()

    def _is_nan(x) -> bool:
        try:
            return bool(pd.isna(x))
        except Exception:
            return False

    def _format_value(x):
        if x is None or _is_nan(x):
            return na_rep

        if isinstance(x, (np.integer, int)) and not isinstance(x, bool):
            try:
                return int_fmt.format(int(x))
            except Exception:
                return str(x)

        if isinstance(x, (np.floating, float)) and not isinstance(x, bool):
            try:
                if callable(float_fmt):
                    return float_fmt(float(x))
                return float_fmt.format(float(x))
            except Exception:
                return str(x)

        return x

    # Elementwise formatting without applymap (avoids FutureWarning)
    df2 = df2.astype(object)
    df2[:] = df2.to_numpy()
    df2 = df2.apply(lambda col: col.map(_format_value), axis=0)

    tabular = df2.to_latex(
        index=index,
        escape=escape,
        na_rep=na_rep,
        column_format=column_format,
    ).strip()

    # Convert \\hline to booktabs rules
    tab_lines = tabular.splitlines()
    hline_idx = [i for i, line in enumerate(tab_lines) if r"\hline" in line]

    if len(hline_idx) >= 2:
        tab_lines[hline_idx[0]] = r"\toprule"
        for i in hline_idx[1:-1]:
            tab_lines[i] = r"\midrule"
        tab_lines[hline_idx[-1]] = r"\bottomrule"

    tabular = "\n".join(tab_lines)

    out = []
    out.append(r"\begin{table}[" + placement + r"]")
    if centering:
        out.append(r"\centering")
    if font_size_cmd:
        out.append(font_size_cmd)

    out.append(r"\caption{" + caption + r"}")
    out.append(r"\label{" + label + r"}")
    out.append(r"\begin{threeparttable}")
    out.append(tabular)

    if note:
        out.append(r"\begin{tablenotes}[flushleft]")
        out.append(r"\footnotesize \item " + note)
        out.append(r"\end{tablenotes}")

    out.append(r"\end{threeparttable}")
    out.append(r"\end{table}")


    return "\n".join(out)



def print_Results(N):
    print("\nObjective value (MEUR):", round(N.objective / 1e6))
    print("\nInstalled generator capacities (GW):")
    print(round(N.generators.p_nom_opt/1e3,1))
    print("\nInstalled store energy capacities (GWh):")
    print(round(N.stores.e_nom_opt/1e3, 4))
    print("\nInstalled battery power capacity (GW):")
    print(round(N.storage_units.p_nom_opt/1e3, 1))
    print("\nInstalled battery energy capacity (GWh):")
    print(round(N.storage_units.p_nom_opt*N.storage_units.max_hours/1e3, 4))
    print("\nInstalled link power capacities (GW):")
    print(round(N.links.p_nom_opt/1e3, 3))

    return

def extract_total_dispatch_profiles(network_pf, network_rh):    # Energy Dipatch pr carrier 
    records = []

    for model_label, network in zip(["Perfect Foresight", "Rolling Horizon"], [network_pf, network_rh]):
        # Generators
        for gen in network.generators.index:
            total_dispatch = round(network.generators_t.p[gen].sum() / 1e3, 1)  # Convert MWh to GWh
            records.append({
                "Model": model_label,
                "Component": gen,
                "Carrier": network.generators.at[gen, "carrier"],
                "Type": "generator",
                "Total Dispatch [GWh]": total_dispatch
            })

        # Hydro StorageUnits
        for hydro in network.storage_units.index:
            if network.storage_units.at[hydro, "carrier"] == "hydro":
                total_dispatch = round(network.storage_units_t.p_dispatch[hydro].sum() / 1e3, 1)  # Convert MWh to GWh
                records.append({
                    "Model": model_label,
                    "Component": hydro,
                    "Carrier": "hydro",
                    "Type": "hydro storage dispatch",
                    "Total Dispatch [GWh]": total_dispatch
                })

        # Battery Links: charge (p0), discharge (p1)
        if {"battery charge", "battery discharge"}.issubset(network.links.index):
            total_charge = round(network.links_t.p1["battery charge"].sum() / 1e3, 1)
            total_discharge = round(network.links_t.p0["battery discharge"].sum() / 1e3, 1)

            records.append({
                "Model": model_label,
                "Component": "battery charge",
                "Carrier": "battery",
                "Type": "charge",
                "Total Dispatch [GWh]": total_charge
            })
            records.append({
                "Model": model_label,
                "Component": "battery discharge",
                "Carrier": "battery",
                "Type": "discharge",
                "Total Dispatch [GWh]": total_discharge
            })

    dispatch_df = pd.DataFrame(records)
    # Add total sum for each model
    total_rows = []
    for model in dispatch_df["Model"].unique():
        total = dispatch_df[dispatch_df["Model"] == model]["Total Dispatch [GWh]"].sum()
        total_rows.append({
            "Model": model,
            "Component": "Total",
            "Carrier": "",
            "Type": "",
            "Total Dispatch [GWh]": round(total, 1)
        })
    dispatch_df = pd.concat([dispatch_df, pd.DataFrame(total_rows)], ignore_index=True)
    return dispatch_df.sort_values(by=["Component", "Carrier"])

def make_dispatch_diff_table(dispatch_df):         # Energi difference between PF and RH from above function
    """
    Create PF vs RH comparison from extract_total_dispatch_profiles output.
    Keeps each Component separate; no premature rounding.
    """
    # Remove any total rows if present
    df = dispatch_df[dispatch_df["Component"] != "Total"].copy()
    df = dispatch_df[dispatch_df["Component"] != "Total"].copy()

    # Pivot so PF and RH are side by side per Component
    pivot = df.pivot_table(index=["Component", "Carrier", "Type"],
                           columns="Model",
                           values="Total Dispatch [GWh]",
                           aggfunc="sum").reset_index()

    # Ensure both PF and RH columns exist
    if "Perfect Foresight" not in pivot.columns:
        pivot["Perfect Foresight"] = 0.0
    if "Rolling Horizon" not in pivot.columns:
        pivot["Rolling Horizon"] = 0.0

    # Rename
    pivot = pivot.rename(columns={
        "Perfect Foresight": "PF [GWh]",
        "Rolling Horizon": "RH [GWh]"
    })

    # Differences
    pivot["Diff [GWh]"] = pivot["RH [GWh]"] - pivot["PF [GWh]"]
    pivot["Percentage Difference [%]"] = pivot.apply(
        lambda r: 0.0 if r["PF [GWh]"] == 0 and r["RH [GWh]"] == 0
        else float("inf") if r["PF [GWh]"] == 0
        else 100 * (r["RH [GWh]"] - r["PF [GWh]"]) / r["PF [GWh]"],
        axis=1
    )

    # Round for display
    for col in ["PF [GWh]", "RH [GWh]", "Diff [GWh]"]:
        pivot[col] = pivot[col].round(1)
    pivot["Percentage Difference [%]"] = pivot["Percentage Difference [%]"].round(1)

    return pivot.sort_values(["Component", "Carrier"]).reset_index(drop=True)

def tot_cost_N(N):
    return (N.buses_t['marginal_price'].iloc[:, 0] * 
               N.loads_t.p_set['load']).sum() 

##############################################################
" ____________________ SILENT OPTIMIZE ____________________ "
##############################################################

def silent_optimize(network, solver_name="gurobi", solver_options=None):
    """
    Optimize a PyPSA network silently: suppress logs, progress bars, and Gurobi messages.
    
    Parameters:
    - network: PyPSA Network object
    - solver_name: Solver name (default: "gurobi")
    - solver_options: Dictionary of solver options (default: {"OutputFlag": 0})
    """
    if solver_options is None:
        solver_options = {"OutputFlag": 0}

    # Suppress PyPSA, Linopy, Gurobi logging output
    for name in ["pypsa", "linopy", "gurobipy"]:
        logging.getLogger(name).setLevel(logging.CRITICAL)

    # Suppress tqdm progress output during optimization
    tqdm.tqdm = lambda *args, **kwargs: iter(args[0]) if args else iter([])

    # Redirect stdout to suppress Gurobi messages
    with open(os.devnull, 'w') as fnull:
        with redirect_stdout(fnull):
            network.optimize(solver_name=solver_name, assign_all_duals=True, solver_options=solver_options)



##############################################################
" ____________________ Unique prices ____________________ "
##############################################################
def unique_prices(network):
    prices = network.buses_t.marginal_price["electricity bus"].round(2).unique()
    return sorted(float(p) for p in prices)

def count_unique_prices(network):
    prices = network.buses_t['marginal_price']['electricity bus'].round(2)
    counts = prices.value_counts().sort_index()
    return counts

##############################################################
" ____________________ LOAD SAVED NETWORKS ____________________ "
##############################################################

def load_networks(folder_name: str, weather_years: list[int], region: str = "ESP", ext: str = ".nc"):
    """
    Load PyPSA networks for given weather_years from Network_results/<folder_name>.
    Keys in the dict are the years (int). Returns dict {year: Network}.
    """
    path = Path.cwd() / "Network_results" / folder_name
    if not path.exists():
        raise FileNotFoundError(f"Folder not found: {path}")

    files = sorted(path.glob(f"*{ext}"))
    if not files:
        print(f"No {ext} files found in {path}")
        return {}

    if len(files) != len(weather_years):
        print(f"Warning: {len(files)} files but {len(weather_years)} years — check alignment")

    networks = {}
    for year, f in zip(weather_years, files):
        n = pypsa.Network(str(f))
        n.name = f.stem       # file name without .nc
        networks[year] = n
        print(f"Loaded N_{year} from {f.name}")

    return networks

##############################################################
" ____________________ COST RECOVERY ____________________ "
##############################################################
def calculate_cost_recovery(network, model_label: str = "exp") -> pd.DataFrame:
    def _safe_div(num: float, den: float) -> float:
        return np.nan if den == 0 else num / den

    rows = []

    # Generators
    for gen in network.generators.index:
        carrier = network.generators.at[gen, "carrier"]
        bus = network.generators.at[gen, "bus"]

        p_nom = network.generators.p_nom_opt[gen] if "p_nom_opt" in network.generators else network.generators.at[gen, "p_nom"]
        mc = float(network.generators.at[gen, "marginal_cost"]) if "marginal_cost" in network.generators.columns else 0.0
        capex_unit = float(network.generators.at[gen, "capital_cost"]) if "capital_cost" in network.generators.columns else 0.0

        dispatch = network.generators_t.p[gen]
        price = network.buses_t.marginal_price[bus]

        revenue = float((dispatch * price).sum())
        var_cost = float((dispatch * mc).sum())
        capex = float(p_nom * capex_unit)

        total_cost = var_cost + capex
        profit = revenue - total_cost

        rows.append({
            "Model": model_label,
            "name": gen,
            "carrier": carrier,
            "revenue [MEUR]": round(revenue / 1e6, 3),
            "variable cost [MEUR]": round(var_cost / 1e6, 3),
            "capital cost [MEUR]": round(capex / 1e6, 3),
            "total cost [MEUR]": round(total_cost / 1e6, 3),
            "profit [MEUR]": round(profit / 1e6, 3),
            "cost recovery [-]": round(_safe_div(revenue, total_cost), 3),
        })

    # StorageUnits
    for su in network.storage_units.index:
        carrier = network.storage_units.at[su, "carrier"]
        bus = network.storage_units.at[su, "bus"]

        p_nom = float(network.storage_units.at[su, "p_nom"])
        mc = float(network.storage_units.at[su, "marginal_cost"]) if "marginal_cost" in network.storage_units.columns else 0.0
        capex_unit = float(network.storage_units.at[su, "capital_cost"]) if "capital_cost" in network.storage_units.columns else 0.0

        dispatch = network.storage_units_t.p_dispatch[su]
        price = network.buses_t.marginal_price[bus]

        revenue = float((dispatch * price).sum())
        var_cost = float((dispatch * mc).sum())
        capex = float(p_nom * capex_unit)

        total_cost = var_cost + capex
        profit = revenue - total_cost

        rows.append({
            "Model": model_label,
            "name": su,
            "carrier": carrier,
            "revenue [MEUR]": round(revenue / 1e6, 3),
            "variable cost [MEUR]": round(var_cost / 1e6, 3),
            "capital cost [MEUR]": round(capex / 1e6, 3),
            "total cost [MEUR]": round(total_cost / 1e6, 3),
            "profit [MEUR]": round(profit / 1e6, 3),
            "cost recovery [-]": round(_safe_div(revenue, total_cost), 3),
        })

    # Links: variable cost = input market cost + link marginal cost on input
    # Sign convention: delivered output to bus1 is (-p1)
    for ln in network.links.index:
        carrier = network.links.at[ln, "carrier"]
        bus0 = network.links.at[ln, "bus0"]
        bus1 = network.links.at[ln, "bus1"]

        p_nom = network.links.p_nom_opt[ln] if "p_nom_opt" in network.links else network.links.at[ln, "p_nom"]
        mc = float(network.links.at[ln, "marginal_cost"]) if "marginal_cost" in network.links.columns else 0.0
        capex_unit = float(network.links.at[ln, "capital_cost"]) if "capital_cost" in network.links.columns else 0.0

        p0 = network.links_t.p0[ln]
        p1 = network.links_t.p1[ln]

        price_in = network.buses_t.marginal_price[bus0]
        price_out = network.buses_t.marginal_price[bus1]

        input_energy = p0.clip(lower=0.0)
        output_energy = (-p1).clip(lower=0.0)

        revenue = float((output_energy * price_out).sum())

        input_market_cost = float((input_energy * price_in).sum())
        link_var_cost = float((input_energy * mc).sum())
        var_cost = input_market_cost + link_var_cost

        capex = float(p_nom * capex_unit)

        total_cost = var_cost + capex
        profit = revenue - total_cost

        rows.append({
            "Model": model_label,
            "name": ln,
            "carrier": carrier,
            "revenue [MEUR]": round(revenue / 1e6, 3),
            "variable cost [MEUR]": round(var_cost / 1e6, 3),
            "capital cost [MEUR]": round(capex / 1e6, 3),
            "total cost [MEUR]": round(total_cost / 1e6, 3),
            "profit [MEUR]": round(profit / 1e6, 3),
            "cost recovery [-]": round(_safe_div(revenue, total_cost), 3),
        })

    # Stores: variable cost = charging market cost + store marginal cost on discharge
    for st in network.stores.index:
        carrier = network.stores.at[st, "carrier"]
        bus = network.stores.at[st, "bus"]

        if hasattr(network.stores, "e_nom_opt") and st in network.stores.e_nom_opt.index:
            e_nom = float(network.stores.e_nom_opt[st])
        else:
            e_nom = float(network.stores.at[st, "e_nom"]) if "e_nom" in network.stores.columns else 0.0

        capex_unit = float(network.stores.at[st, "capital_cost"]) if "capital_cost" in network.stores.columns else 0.0
        mc = float(network.stores.at[st, "marginal_cost"]) if "marginal_cost" in network.stores.columns and pd.notna(network.stores.at[st, "marginal_cost"]) else 0.0

        p = network.stores_t.p[st]
        price = network.buses_t.marginal_price[bus]

        discharge = p.clip(lower=0.0)
        charge = (-p).clip(lower=0.0)

        revenue = float((discharge * price).sum())

        charging_cost = float((charge * price).sum())
        store_var_cost = float((discharge * mc).sum())
        var_cost = charging_cost + store_var_cost

        capex = float(e_nom * capex_unit)

        total_cost = var_cost + capex
        profit = revenue - total_cost

        rows.append({
            "Model": model_label,
            "name": st,
            "carrier": carrier,
            "revenue [MEUR]": round(revenue / 1e6, 3),
            "variable cost [MEUR]": round(var_cost / 1e6, 3),
            "capital cost [MEUR]": round(capex / 1e6, 3),
            "total cost [MEUR]": round(total_cost / 1e6, 3),
            "profit [MEUR]": round(profit / 1e6, 3),
            "cost recovery [-]": round(_safe_div(revenue, total_cost), 3),
        })

    return pd.DataFrame(rows).reset_index(drop=True)

##############################################################
" ____________________ DEMAND FLEXIBILITY ____________________ "
##############################################################
  
def add_elastic_demand(N, marginal_cost: float, marginal_cost_quadratic: float, p_nom: float= None, segment_name: str = "elastic demand"):
    N.add("Generator", f"elastic load shedding - {segment_name}",
        bus="electricity bus",
        carrier=f"elastic load shedding",
        p_nom=p_nom if p_nom is not None else float(np.mean(N.loads_t.p_set)),
        marginal_cost=marginal_cost,
        marginal_cost_quadratic=marginal_cost_quadratic
    )

##############################################################
" ____________________ SOC analysis ____________________ "
##############################################################

def collect_h2_soc(networks: dict, carrier="hydrogen storage") -> pd.DataFrame:
    """
    Return long dataframe with normalized SOC for all networks.
    Columns: soc, year, doy
    """
    rows = []

    for year, net in sorted(networks.items()):
        mask = net.stores.carrier.str.lower() == carrier.lower()
        if not mask.any():
            continue

        ids = net.stores.index[mask]
        soc = net.stores_t.e[ids].sum(axis=1)

        # normalize by capacity
        if "e_nom_opt" in net.stores.columns and net.stores["e_nom_opt"].notna().any():
            cap = net.stores.loc[ids, "e_nom_opt"].sum()
        else:
            cap = net.stores.loc[ids, "e_nom"].sum()
        soc = soc / cap

        df = soc.to_frame("soc")
        df["year"] = year
        df["doy"] = df.index.dayofyear
        rows.append(df)

    return pd.concat(rows)
#df_SOC = collect_h2_soc(networks_exp_1, carrier="hydrogen storage")

def h2_SOC_on_date(networks: dict,
                        date: str,
                        carrier="hydrogen storage",
                        threshold_full=0.9):
    """
    Compute SOC fullness statistics for a specific calendar date (e.g. '06-01').

    Statistics returned:
        - mean SOC
        - median SOC
        - percentiles P10, P50, P90
        - min and max SOC
        - share of years with SOC > threshold_full
        - number of years included
    """

    # parse input date
    try:
        month, day = map(int, date.split("-"))
    except Exception:
        raise ValueError("Date must be a string in MM-DD format, e.g. '06-01'.")

    # get long-format SOC for all years
    soc_long = collect_h2_soc(networks, carrier=carrier)

    # convert DOY back to a dummy date (year 2000)
    dummy_year = 2000
    soc_long["dummy_date"] = soc_long["doy"].apply(
        lambda doy: pd.Timestamp(dummy_year, 1, 1) + pd.Timedelta(days=doy - 1)
    )

    # select the requested month/day
    mask = (
        (soc_long["dummy_date"].dt.month == month) &
        (soc_long["dummy_date"].dt.day == day)
    )
    subset = soc_long.loc[mask]

    if subset.empty:
        print(f"No data found for date {date}.")
        return None

    years = subset["year"].nunique()

    # compute statistics
    mean_val   = subset["soc"].mean()
    median_val = subset["soc"].median()
    p25        = subset["soc"].quantile(0.25)
    p50        = subset["soc"].quantile(0.50)
    p90        = subset["soc"].quantile(0.90)
    min_val    = subset["soc"].min()
    max_val    = subset["soc"].max()
    share_full = (subset["soc"] > threshold_full).mean()

    # print summary
    print(f"\nHydrogen SOC statistics for {date}:")
    print(f"Years included:                 {years}")
    print(f"Mean SOC:                     {mean_val:.3f}")
    print(f"Median SOC:                   {median_val:.3f}")
    print(f"P25 SOC:                      {p25:.3f}")
    print(f"P50 SOC:                      {p50:.3f}")
    print(f"P90 SOC:                      {p90:.3f}")
    print(f"Min SOC:                      {min_val:.3f}")
    print(f"Max SOC:                      {max_val:.3f}")
    print(f"Share SOC > {threshold_full}:        {share_full:.3f}")

    return {
        "date": date,
        "mean_soc": mean_val,
        "median_soc": median_val,
        "p25": p25,
        "p50": p50,
        "p90": p90,
        "min_soc": min_val,
        "max_soc": max_val,
        "share_soc_above_threshold": share_full,
        "years_count": years
    }

##############################################################
" ____________________ EXTREME SP PERIODS ____________________ "
##############################################################

" EXTREME PERIODS code from aleks (slightly modified) "
# _________________________________________________________
class extreme_period(NamedTuple):
    period: pd.Interval
    peak_hour: pd.Timestamp
def get_peak_hour_from_period(
    n: pypsa.Network,
    p: pd.Interval,
) -> list:
    """Find the hour with the highest system cost (load * nodal_price) for a given interval.

    Parameters
    ----------
    n : pypsa.Network
        The network for which to find difficult periods.
    p: pd.Interval
        Period of interest, represented as pd.Interval.

    Returns
    -------
    peak_hours: list[pd.Timestamp]
        A list of the most extreme timestamp for the list of periods of interest."""

    return (
        (
            n.buses_t["marginal_price"].loc[p.left : p.right]
            * n.loads_t.p.loc[p.left : p.right]
        )
        .sum(axis=1)
        .idxmax()
    )

# Finding extreme periods based on total system cost. 
# This function were developed by 2023 Koen van Greevenbroek & Aleksander Grochowicz, and only includes slight modifications removing the nodal aspect. 
def global_difficult_periods(
    n: pypsa.Network,
    min_length: int,
    max_length: int,
    T: float,
    month_bounds: Optional[tuple[int, int]] = None,
) -> pd.DataFrame:
    """Find intervals with high global system cost.

    The intervals will have a length between `min_length` and
    `max_length`, over which the total system costs adds up to a value
    greater than `T`.

    Parameters
    ----------
    n : pypsa.Network
        The network for which to find difficult periods.
    min_length : int
        The minimum length of the intervals to consider, in hours.
    max_length : int
        The maximum length of the intervals to consider, in hours.
    T : float
        The threshold for the total system costs to be exceeded, in EUR.
    month_bounds : Optional[tuple[int, int]] = None
        Optionally, specify in which months to search for difficult
        periods. In this argument is not None, only periods in given
        month interval are returned. The interval is inclusive and
        cyclic. For example, if `month_bounds == (11, 2)`, only
        periods contained entirely within the November-February range
        (inclusive) are returned.

    Returns
    -------
    namedtuple consisting of
        list[pd.Interval]
            A list of the periods of interest, represented as pd.Interval.
        list[pd.Timestamp]
            A list of the most extreme timestamp for the list of periods of interest.
    """
    # Modified here to fit the model used in this thesis. 
    nodal_costs = n.buses_t["marginal_price"]["electricity bus"] * n.loads_t["p_set"]["load"]
    total_costs = nodal_costs

    if month_bounds is not None:
        total_costs = total_costs.loc[
            (total_costs.index.month >= month_bounds[0])
            & (total_costs.index.month <= month_bounds[1])
        ]

    # Create an empty series, but specifying the type of index it's
    # going to have: an datetime interval index.
    C = pd.Series(
        index=pd.IntervalIndex.from_tuples(
            [], closed="both", dtype="interval[datetime64[ns], both]"
        ),
        dtype="float64",
    )

    for w in range(min_length - 1, max_length - 1):
        # Create array of intervals of width w+1
        intervals = pd.IntervalIndex.from_arrays(
            left=total_costs.index[:-w], right=total_costs.index[w:], closed="both"
        )
        # Find total costs for all intervals of width w+1
        costs = total_costs.rolling(w + 1).sum().iloc[w:]
        costs.index = intervals
        # In case we are only looking at intervals within some given
        # months, the index of `costs` might actually consist of two
        # disjoint seasons (e.g. July-October and April-June), leading
        # to some intervals that span the "gap" between these seasons.
        # Filter those out by only keeping intervals with an actual
        # duration of w+1 hours
 
        
        costs = costs.loc[costs.index.length <= pd.Timedelta(hours=w + 1)]

        # Filter out the intervals costing less than T
        costs = costs.loc[costs > T]

        # Filter out the intervals that overlap with existing intervals
        if len(C) > 0:
            costs = costs.loc[
                ~np.array([costs.index.overlaps(I) for I in C.index]).any(axis=0)
            ]

        # Also filter out intervals in `non_overlapping_I` that
        # overlap with each other. Sort the intervals by cost (from
        # highest to lowest) and take each interval in turn as long as
        # it doesn't overlap any of the previously taken intervals.
        costs = costs.sort_values(ascending=False)
        # (Again, we need to specify the type of index explicitly when
        # initialising it empty.)
        non_overlapping_I = pd.IntervalIndex.from_tuples(
            [], closed="both", dtype="interval[datetime64[ns], both]"
        )
        for I in costs.index:
            if not any(non_overlapping_I.overlaps(I)):
                # Now that we have committed to selecting the interval
                # I, we can see if it's actually natural to "expand" I
                # in either direction. We only want to expand I by
                # times at which the cost is greater than the average
                # cost of I. First, find the average cost of I.
                avg_cost = total_costs.loc[I.left : I.right].mean()
                # Now, expand I in both directions as long as the cost
                # is greater than the average cost of I
                while (
                    I.left > total_costs.index[0]
                    and total_costs.iloc[total_costs.index.searchsorted(I.left) - 1]
                    > avg_cost
                ):
                    I = pd.Interval(
                        left=total_costs.index[
                            total_costs.index.searchsorted(I.left) - 1
                        ],
                        right=I.right,
                        closed="both",
                    )
                while (
                    I.right < total_costs.index[-1]
                    and total_costs.iloc[total_costs.index.searchsorted(I.right) + 1]
                    > avg_cost
                ):
                    I = pd.Interval(
                        left=I.left,
                        right=total_costs.index[
                            total_costs.index.searchsorted(I.right) + 1
                        ],
                        closed="both",
                    )

                # Insert in sorted order
                i = non_overlapping_I.searchsorted(I)
                non_overlapping_I = non_overlapping_I.insert(i, I)

        # Add the intervals we found one by one. However, since the
        # intervals may be been extended, they may now still overlap
        # with some of the intervals in the index of C.
        # NOTE: this code path is not taken for the periods of our paper!
        for I in non_overlapping_I:
            if len(C) == 0:
                C.loc[I] = total_costs.loc[I.left : I.right].sum()
            else:
                # Find intervals in C that overlap with I
                overlapping_I = C.index[C.index.overlaps(I)]
                # Remove them from C
                C = C.drop(overlapping_I)
                # Create the union of I and all the intervals it overlaps with.
                left = min([I.left, *overlapping_I.left])
                right = max([I.right, *overlapping_I.right])
                I = pd.Interval(left=left, right=right, closed="both")
                # Add the union to C
                C.loc[I] = total_costs.loc[I.left : I.right].sum()

        C = C.sort_index()

    return [extreme_period(p, get_peak_hour_from_period(n, p)) for p in C.index]
# _________________________________________________________

###############################################################
" ____________________ IDENTIFY EVENTS ____________________ "
###############################################################

# FUNCTION TO LOAD OR BUILD EVENTS - USING THE DIFFERENT METHODS DEFINED BELOW AND ABOVE
def get_events(
    model_type: str,
    test_name: str,
    event_type: str,
    networks: Dict[int, "pypsa.Network"],
    years: List[int],
    event_dir_root: Path = Path("Event_results"),
    force: bool = False,
    **kwargs
) -> Dict[int, list]:
    """
    Unified event loader/builder.
    event_type: "SP", "NL", "LS", "FLEX"

    kwargs per event_type:
      SP: threshold (float), length (tuple/list [min_days, max_days])
      NL/LS/FLEX: method ("calendar"|"dynamic"),
                  window_days (int) OR window_hours (int)
    """
    event_dir = event_dir_root / model_type
    event_dir.mkdir(parents=True, exist_ok=True)

    et = event_type.upper()

    if et == "SP":
        threshold = float(kwargs["threshold"])
        length = kwargs["length"]
        min_d, max_d = int(length[0]), int(length[1])

        fname = f"{model_type}_events_{test_name}_SP_T{int(threshold*100)}_L{min_d}_{max_d}days"
        path = event_dir / fname

        return load_or_build_events(
            path=path,
            build_func=lambda: extreme_periods_identification(
                networks, years, threshold=threshold, length=(min_d, max_d)
            ),
            force=force,
        )

    if et in ("NL", "LS", "FLEX", "DE_FLEX", "DE"):
        method = kwargs.get("method", "dynamic")
        if method not in ("calendar", "dynamic"):
            raise ValueError("method must be 'calendar' or 'dynamic'")

        window_hours = kwargs.get("window_hours", None)
        if window_hours is None:
            window_days = kwargs.get("window_days", None)
            if window_days is None:
                window_hours = 24 * 7
            else:
                window_hours = int(window_days) * 24
        window_hours = int(window_hours)

        if et == "NL":
            fname = f"{model_type}_events_{test_name}_NL_{method}_{int(window_hours/24)}days"
            path = event_dir / fname
            builder = lambda: find_netload_events_from_networks(
                networks, years, method=method, window_hours=window_hours
            )

        elif et == "LS":
            fname = f"{model_type}_events_{test_name}_LS_{method}_{int(window_hours/24)}days_T{int(T_LS*10000)}"
            path = event_dir / fname
            builder = lambda: find_ls_events_by_year(
                networks, years, method=method, window_hours=window_hours, alpha=T_LS
            )

        else:  # FLEX
            fname = f"{model_type}_events_{test_name}_FLEX_{method}_{int(window_hours/24)}days"
            path = event_dir / fname
            builder = lambda: find_flex_activated_events_by_year(
                networks, years, method=method, window_hours=window_hours
            )

        return load_or_build_events(path=path, build_func=builder, force=force)

    raise ValueError("event_type must be one of: 'SP', 'NL', 'LS', 'FLEX'")

# LS EVENTS 
def find_ls_events_by_year(
    networks_pf: Dict[int, "pypsa.Network"],
    years: List[int],
    method: str = "dynamic",
    window_hours: int = 24 * 7,
    alpha: float = 0.001
) -> Dict[int, list]:
    """
    Find yearly load-shedding events based on 'load shedding' generator output.
    Returns dict {year: [extreme_period]} or 0 if no load shedding that year.
    """
    out = {y: 0 for y in years}

    for y in years:
        net = networks_pf.get(y)
        if net is None:
            continue

        ls = net.generators_t.p["load shedding"]

        if ls.sum() <= 0.1:
            continue

        ls = ls.sort_index()

        if method == "calendar":
            weekly = ls.resample("W").sum()
            if weekly.max() <= 0:
                continue
            w_end = weekly.idxmax()
            w_start = w_end - pd.Timedelta(days=6)
            p = pd.Interval(w_start, w_end, closed="both")
            peak = ls.loc[w_start:w_end].idxmax()
            out[y] = [extreme_period(p, peak)]

        elif method == "dynamic":
            roll = ls.rolling(window_hours, min_periods=window_hours).sum()
            if roll.max() <= 0:
                continue
            end = roll.idxmax()
            if pd.isna(end):
                continue
            start = end - pd.Timedelta(hours=window_hours - 1)

            ls_energy = ls.loc[start:end].sum()
            load_energy = net.loads_t.p_set["load"].loc[start:end].sum()
            if (ls_energy / load_energy) < alpha:
                continue

            p = pd.Interval(start, end, closed="both")
            peak = ls.loc[start:end].idxmax()
            out[y] = [extreme_period(p, peak)]

        else:
            raise ValueError("method must be 'calendar' or 'dynamic'")

    return out

def find_flex_activated_events_by_year(
    networks_pf: Dict[int, "pypsa.Network"],
    years: List[int],
    method: str = "dynamic",
    window_hours: int = 24 * 7,
    alpha: float = 0.001
) -> Dict[int, list]:

    seg_names = [
        "elastic load shedding - segment_1",
        "elastic load shedding - segment_2",
        "elastic load shedding - segment_3",
    ]

    out = {y: 0 for y in years}

    for y in years:
        net = networks_pf.get(y)
        if net is None:
            continue

        flex = net.generators_t.p[seg_names].sum(axis=1).sort_index()

        if flex.sum() <= 0.1:
            continue

        if method == "calendar":
            weekly = flex.resample("W").sum()
            if weekly.max() <= 0:
                continue

            w_end = weekly.idxmax()
            w_start = w_end - pd.Timedelta(days=6)

            flex_energy = flex.loc[w_start:w_end].sum()
            load_energy = net.loads_t.p_set["load"].loc[w_start:w_end].sum()
            if (flex_energy / load_energy) < alpha:
                continue

            p = pd.Interval(w_start, w_end, closed="both")
            peak = flex.loc[w_start:w_end].idxmax()
            out[y] = [extreme_period(p, peak)]
            continue

        elif method == "dynamic":
            roll = flex.rolling(window_hours, min_periods=window_hours).sum()
            if roll.max() <= 0:
                continue

            end = roll.idxmax()
            start = end - pd.Timedelta(hours=window_hours - 1)

            flex_energy = flex.loc[start:end].sum()
            load_energy = net.loads_t.p_set["load"].loc[start:end].sum()
            if (flex_energy / load_energy) < alpha:
                continue

            p = pd.Interval(start, end, closed="both")
            peak = flex.loc[start:end].idxmax()
            out[y] = [extreme_period(p, peak)]

        else:
            raise ValueError("method must be, 'calendar', or 'dynamic'")

    return out

# function to calculate net load for a given network 
def calculate_net_load_potential(network: pypsa.Network,
                                 weather_year: int
) -> pd.Series:
    """
    Net load = demand - (CF * p_nom) for wind + solar.
    Uses global All_data and region.
    Always potential, never dispatch.
    """

    # demand
    demand = network.loads_t.p_set["load"]
    demand = demand[demand.index.strftime("%m-%d") != "02-29"]

    # helper
    def remove_feb29(s):
        return s[s.index.strftime("%m-%d") != "02-29"]

    # snapshot period (June → June)
    start = demand.index[0]
    end   = demand.index[-1]

    # capacity-factor time series from All_data
    cf_wind  = All_data["onwind"][region].loc[start:end]
    cf_solar = All_data["solar"][region].loc[start:end]

    cf_wind  = remove_feb29(cf_wind)
    cf_solar = remove_feb29(cf_solar)

    # align indices
    cf_wind  = cf_wind.reindex(demand.index)
    cf_solar = cf_solar.reindex(demand.index)

    # p_nom from network
    p_nom_wind  = network.generators.p_nom_opt.get("onwind", 0.0)
    p_nom_solar = network.generators.p_nom_opt.get("solar", 0.0)

    # potential production
    wind_pot  = cf_wind  * p_nom_wind
    solar_pot = cf_solar * p_nom_solar

    return demand - (wind_pot + solar_pot)

# NETLOAD EVENTS
def find_netload_events_from_networks(
    networks: Dict[int, "pypsa.Network"],
    weather_years: List[int],
    method: str = "dynamic",
    window_hours: int = 24 * 7
) -> Dict[int, List[extreme_period]]:
    out = {y: [] for y in weather_years}

    for y in weather_years:
        net = networks.get(y)
        if net is None:
            continue

        s = calculate_net_load_potential(net, weather_year=y).sort_index()
        if s.empty:
            continue

        if method == "calendar":
            weekly = s.resample("W").sum()
            if weekly.dropna().empty:
                continue
            e = weekly.idxmax()
            b = e - pd.Timedelta(days=6)
            p = pd.Interval(b, e, closed="both")
            peak = s.loc[b:e].idxmax()

        elif method == "dynamic":
            roll = s.rolling(window_hours, min_periods=window_hours).sum()
            if roll.dropna().empty:
                continue
            e = roll.idxmax()
            if pd.isna(e):
                continue
            b = e - pd.Timedelta(hours=window_hours - 1)
            p = pd.Interval(b, e, closed="both")
            peak = s.loc[b:e].idxmax()

        else:
            raise ValueError("method must be 'calendar' or 'dynamic'")

        out[y].append(extreme_period(p, peak))

    return out

# Only returns a dict  - can go instead of calc_yearly_extreme_periods
# SP EVENTS - THE ONE CURRENTLY IN USE
def extreme_periods_identification(
    networks: dict,
    weather_years: list,
    threshold: float = 0.15,
    length: tuple = (1, 14)
):
    """
    Run global_difficult_periods for each year and return periods_by_year dict.
    - networks_pf: {year: pypsa.Network}
    - weather_years: list of years to process
    - threshold, length: passed to detection
    """
    periods_by_year = {}

    for year in weather_years:
        net = networks[year]
        net_name = getattr(net, "name", year)

        if not hasattr(net, "objective") or net.objective == 0:
            print(f"Warning: {net_name} has no valid objective. Skipping.")
            continue

        mp = net.buses_t["marginal_price"]["electricity bus"].squeeze()
        load = net.loads_t["p_set"]["load"].squeeze()
        nodal = mp.mul(load)
        T = threshold * nodal.sum()

        periods = global_difficult_periods(
            net,
            min_length=24 * length[0],
            max_length=24 * length[1],
            T=T
        )
        periods_by_year[year] = periods

        print(f"\nYear {year} - {len(periods)} extreme periods found:")
        for p in periods:
            print(f"  Period: {p.period}, Peak hour: {p.peak_hour}")

    return periods_by_year

def filter_events_by_years(events_dict: dict, years: list[int]) -> dict:
    return {y: events_dict[y] for y in years if y in events_dict}

# ____________________ EVENT OVERLAP MATRIX ____________________ "
def compute_event_overlap_matrix(
    event_dicts: list,
    labels: list
) -> pd.DataFrame:
    """
    Asymmetric overlap matrix M where M[i,j] = (# row-events that overlap any col-event) / (total row-events).

    Inputs
    - event_dicts: list of {year: [extreme_period, ...]} (your fixed structure; years with no events can be 0)
    - labels: list of label strings, same length/order as event_dicts

    Output
    - pd.DataFrame with index=labels, columns=labels, values in [0, 1]
    """

    def intervals_overlap(a: pd.Interval, b: pd.Interval) -> bool:
        return not (a.right < b.left or b.right < a.left)

    n = len(labels)
    M = pd.DataFrame(index=labels, columns=labels, dtype=float)

    for i in range(n):
        row_label = labels[i]
        row_dict = event_dicts[i]

        for j in range(n):
            col_label = labels[j]
            col_dict = event_dicts[j]

            overlap_count = 0
            total_count = 0

            all_years = sorted(set(row_dict.keys()) | set(col_dict.keys()))

            for y in all_years:
                row_events = row_dict[y]
                col_events = col_dict[y]

                row_events = row_events if isinstance(row_events, list) else []
                col_events = col_events if isinstance(col_events, list) else []

                total_count += len(row_events)

                if len(row_events) == 0 or len(col_events) == 0:
                    continue

                col_intervals = [ev.period for ev in col_events]

                for ev in row_events:
                    if any(intervals_overlap(ev.period, ci) for ci in col_intervals):
                        overlap_count += 1

            if total_count == 0:
                M.loc[row_label, col_label] = 0.0
            else:
                M.loc[row_label, col_label] = round(overlap_count / total_count, 3)

    return M



## for problem years
def build_event_count_table(
    labels: list[str],
    events_dict_list: list[dict],
) -> pd.DataFrame:
    years = sorted({int(y) for d in events_dict_list for y in d.keys()})

    df = pd.DataFrame(index=years, columns=labels, dtype=float)

    for lab, d in zip(labels, events_dict_list):
        for y in years:
            ev_list = d.get(y, [])
            df.loc[y, lab] = 0 if (not ev_list or isinstance(ev_list, int)) else len(ev_list)

    total_label = f"Total of {len(labels)}"
    df.insert(0, total_label, df.sum(axis=1))

    df.index = [f"{y % 100:02d}/{(y + 1) % 100:02d}" for y in df.index]
    df.index.name = "Year"

    return df


def build_ls_aggregation_table(
    labels: list[str],
    years: list[int],   
    networks_by_model: dict[str, dict],
) -> pd.DataFrame:
    df = pd.DataFrame(index=years, columns=labels, dtype=float)

    for lab in labels:
        model = lab.split("_", 1)[0]
        nets = networks_by_model[model]

        for y in years:
            n = nets[y]
            ls_mw = pd.Series(n.generators_t.p["load shedding"]).sort_index()
            df.loc[y, lab] = float(ls_mw.sum())

    # Add percentage-of-max column per model/event label
    for lab in labels:
        max_ls = df[lab].max()
        pct_col = f"LS % of max {lab}"
        df[pct_col] = (df[lab] / max_ls * 100).round(2)

    df = df.round(2)

    df.index = [f"{y % 100:02d}/{(y + 1) % 100:02d}" for y in df.index]
    df.index.name = "Season"

    return df


# Helper functions event length detection: 

def avg_event_duration_hours(events_dict):
    durations_h = []

    for events in events_dict.values():
        for ev in events:
            interval = ev.period
            duration = interval.right - interval.left + pd.Timedelta(hours=1)
            durations_h.append(duration / pd.Timedelta(hours=1))

    return float(sum(durations_h) / len(durations_h)) if durations_h else 0.0


def build_event_tables_for_beta_list(
    beta_list: List[float],
    Test_name_exp: str,
    Test_name_dispatch: str,
    Test_name_dispatch_PWL: str,
    selected_networks_exp,
    selected_networks_pf,
    selected_networks_pf_PWL,
    selected_networks_rh,
    selected_networks_rh_PWL,
    years: List[int],
    length: Tuple[int, int],
    new_events: bool,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Build event count, avg yearly count, and avg duration tables for SP events
    for capacity expansion, perfect foresight, and limited foresight variants
    across a list of beta thresholds.
    """

    def avg_event_duration_hours(events_dict):
        durations_h = []
        for events in events_dict.values():
            for ev in events:
                interval = ev.period
                duration = interval.right - interval.left + pd.Timedelta(hours=1)
                durations_h.append(duration / pd.Timedelta(hours=1))
        return float(sum(durations_h) / len(durations_h)) if durations_h else 0.0

    event_number_rows = []
    avg_yearly_event_number_rows = []
    avg_event_duration_rows = []

    for beta in beta_list:
        ce_events_SP = get_events(
            model_type="EXP",
            test_name=Test_name_exp,
            event_type="SP",
            networks=selected_networks_exp,
            years=years,
            threshold=beta,
            length=length,
            force=False,
        )

        pf_events_SP = get_events(
            model_type="PF",
            test_name=Test_name_dispatch,
            event_type="SP",
            networks=selected_networks_pf,
            years=years,
            threshold=beta,
            length=length,
            force=new_events,
        )

        pf_events_SP_PWL = get_events(
            model_type="PF",
            test_name=Test_name_dispatch_PWL,
            event_type="SP",
            networks=selected_networks_pf_PWL,
            years=years,
            threshold=beta,
            length=length,
            force=new_events,
        )

        rh_events_SP = get_events(
            model_type="RH",
            test_name=Test_name_dispatch,
            event_type="SP",
            networks=selected_networks_rh,
            years=years,
            threshold=beta,
            length=length,
            force=new_events,
        )

        rh_events_SP_PWL = get_events(
            model_type="RH",
            test_name=Test_name_dispatch_PWL,
            event_type="SP",
            networks=selected_networks_rh_PWL,
            years=years,
            threshold=beta,
            length=length,
            force=new_events,
        )

        total_events_ce = sum(len(events) for events in ce_events_SP.values())
        total_events_pf = sum(len(events) for events in pf_events_SP.values())
        total_events_pf_pwl = sum(len(events) for events in pf_events_SP_PWL.values())
        total_events_rh = sum(len(events) for events in rh_events_SP.values())
        total_events_rh_pwl = sum(len(events) for events in rh_events_SP_PWL.values())

        event_number_rows.append(
            {
                "Threshold beta": round(beta, 2),
                "Capacity expansion": round(total_events_ce, 2),
                "Perfect foresight": round(total_events_pf, 2),
                "Perfect foresight PWL": round(total_events_pf_pwl, 2),
                "Limited foresight": round(total_events_rh, 2),
                "Limited foresight PWL": round(total_events_rh_pwl, 2),
            }
        )

        avg_yearly_event_number_rows.append(
            {
                "Threshold beta": round(beta, 2),
                "Capacity expansion": round(total_events_ce / len(years), 2),
                "Perfect foresight": round(total_events_pf / len(years), 2),
                "Perfect foresight PWL": round(total_events_pf_pwl / len(years), 2),
                "Limited foresight": round(total_events_rh / len(years), 2),
                "Limited foresight PWL": round(total_events_rh_pwl / len(years), 2),
            }
        )

        avg_event_duration_rows.append(
            {
                "Threshold beta": round(beta, 2),
                "Capacity expansion": round(avg_event_duration_hours(ce_events_SP) / 24, 2),
                "Perfect foresight": round(avg_event_duration_hours(pf_events_SP) / 24, 2),
                "Perfect foresight PWL": round(avg_event_duration_hours(pf_events_SP_PWL) / 24, 2),
                "Limited foresight": round(avg_event_duration_hours(rh_events_SP) / 24, 2),
                "Limited foresight PWL": round(avg_event_duration_hours(rh_events_SP_PWL) / 24, 2),
            }
        )

    df_columns = [
        "Threshold beta",
        "Capacity expansion",
        "Perfect foresight",
        "Perfect foresight PWL",
        "Limited foresight",
        "Limited foresight PWL",
    ]

    df_table_event_pr_model = pd.DataFrame(event_number_rows, columns=df_columns)
    df_table_avg_yearly_event_pr_model = pd.DataFrame(avg_yearly_event_number_rows, columns=df_columns)
    df_table_avg_event_duration_pr_model = pd.DataFrame(avg_event_duration_rows, columns=df_columns)

    return (
        df_table_event_pr_model,
        df_table_avg_yearly_event_pr_model,
        df_table_avg_event_duration_pr_model,
    )



