"""
This code has been prepared for the master thesis: 
"Extreme events and demand elasticity in energy system models with high renewable penetration and limited foresight" by Jonathan Gadfelt 

Copyright c2026 Jonathan Lybecker Gadfelt < jonathan@gadfelt.dk >
This work is licensed under a Creative Commons Attribution 4.0 International Licence (CC-BY).
"""
from functions_other import *

# Global fontsize parameters
LEGEND_FONTSIZE = 8
SUBPLOT_TITLE_FONTSIZE = 11
FIGURE_TITLE_FONTSIZE = 15

default_figsize = (8, 6)

np.set_printoptions(suppress=True)
FIGURES_DIR = Path.cwd() / "Figures"
FIGURES_DIR.mkdir(exist_ok=True)

Figures_results_path = Path(r"C:\Users\jonat\Dropbox\Apps\Overleaf\Master thesis - Jonathan Gadfelt\Figures\Results")
Figures_mdl_setup_path = Path(r"C:\Users\jonat\Dropbox\Apps\Overleaf\Master thesis - Jonathan Gadfelt\Figures\Modelling_setup")
Figures_appendix_path = Path(r"C:\Users\jonat\Dropbox\Apps\Overleaf\Master thesis - Jonathan Gadfelt\Figures\Appendix")

region = "ESP"          # Region for hydro inflow data

# Making sure date formatting is english
import locale

try:
    locale.setlocale(locale.LC_TIME, "en_US.UTF-8")
except locale.Error:
    locale.setlocale(locale.LC_TIME, "C")

" _______________ DEFAULT PLOTTING STYLES ____________________ "
mpl.rcParams.update({
    "figure.figsize": default_figsize,
    "figure.dpi": 100,
    "savefig.dpi": 300,

    "font.size": 11,
    "axes.titlesize": 13,
    "axes.labelsize": 11,
    "axes.titlepad": 12,
    "xtick.labelsize": 10,
    "ytick.labelsize": 10,
    "legend.fontsize": 9,

    "lines.linewidth": 1.2,

    "axes.edgecolor": "0.4",
    "axes.linewidth": 0.8,

    "axes.spines.top": True,
    "axes.spines.right": True,
    "axes.spines.left": True,
    "axes.spines.bottom": True,
    "axes.axisbelow": True,


    "grid.color": "0.7",
    "grid.linewidth": 0.8,
    "grid.alpha": 0.5,
})



##############################################################
" ____________________ PLOTTING FUNCTIONS ____________________ "
##############################################################

def plot_electricity_mix(network, save_plot=False, plot_title='Electricity mix', min_cap=10, figure_size=default_figsize):
    # generator capacity by carrier
    gen_caps = (network.generators[["carrier","p_nom_opt"]]
                .groupby("carrier")["p_nom_opt"].sum())

    # add hydro StorageUnit power capacity (if present)
    if not network.storage_units.empty:
        hydro_cap = network.storage_units.loc[
            network.storage_units.carrier == "hydro", "p_nom_opt"
        ].sum()
        if hydro_cap > 0:
            gen_caps = gen_caps.add(pd.Series({"hydro": hydro_cap}), fill_value=0)

    # drop load shedding and tiny slices
    ls_names = {c for c in gen_caps.index if c.lower().replace("_"," ") == "load shedding"}
    gen_caps = gen_caps.drop(labels=list(ls_names), errors="ignore")
    gen_caps = gen_caps[gen_caps > min_cap]

    if gen_caps.empty:
        print("Nothing to plot.")
        return

    labels = gen_caps.index.tolist()
    sizes  = gen_caps.values.tolist()

    # use carrier colors from the network (keeps order aligned with labels)
    pie_colors = (network.carriers.reindex(labels)["color"].tolist()
                  if "color" in network.carriers else None)

    plt.figure()
    plt.pie(sizes, labels=labels, autopct='%1.1f%%',
            colors=pie_colors, wedgeprops={'linewidth': 0})
    plt.axis('equal')
    plt.title(plot_title, y=1.07)
    plt.tight_layout()
    if save_plot:
        Path("Plots").mkdir(exist_ok=True)
        plt.savefig("Plots/electricity_mix.png", dpi=300, bbox_inches="tight")
    plt.show()

def plot_capacity_mix_pie(
    opt_capa_df: pd.DataFrame,
    stat: str = "mean",
    plot_title: str | None = None,
    show: str = "values",   # "values" or "percent"
    colors: dict | None = None,
    save_plots: bool = False,
):
    """
    Pie chart of capacity mix from a summary dataframe like opt_capa_df.

    show:
        "values"  -> show absolute values on wedges [GW] (default)
        "percent" -> show percentages on wedges
    """

    # drop hydrogen storage
    opt_capa_df = opt_capa_df.drop(columns=["Hydrogen storage"], errors="ignore")

    if stat not in opt_capa_df.index:
        raise ValueError(
            f"stat='{stat}' not found. Available: {list(opt_capa_df.index)}"
        )

    # capacities in GW
    caps = (opt_capa_df.loc[stat].astype(float)) / 1000.0

    if plot_title is None:
        plot_title = f"Capacity mix ({stat})"

    labels = caps.index.tolist()
    sizes = caps.values
    total_gw = sizes.sum()

    if colors is None:
        color_list = None
    else:
        color_list = [colors.get(label, "lightgray") for label in labels]

    if show == "values":
        # explicit: pct -> GW using total
        def format_values(pct):
            value_gw = pct / 100.0 * total_gw
            return f"{value_gw:.1f}"
        autopct = format_values

    elif show == "percent":
        autopct = "%1.1f%%"

    else:
        raise ValueError("show must be 'values' or 'percent'")

    plt.figure()
    wedges, texts, autotexts = plt.pie(
        sizes,
        labels=None,
        autopct=autopct,
        startangle=90,
        colors=color_list,
    )

    plt.axis("equal")
    plt.title(plot_title, y=1.05, fontsize=FIGURE_TITLE_FONTSIZE)
    plt.tight_layout()

    plt.legend(
        wedges,
        labels,
        loc="best",
        frameon=False,
        title="Technology",
    )

    if save_plots:
        plt.savefig(
            Figures_mdl_setup_path / "exp_capacity_mix_pie_mean.pdf",
            bbox_inches="tight",
        )

    plt.show()
    return


def plot_price_duration_curve(N, descending=True, show_percentile_axis=True, title=None, figure_size=default_figsize):
    """
    Plot a price duration curve for the electricity bus in network N.
    Unweighted. Automatically picks the electricity bus.
    """

    # 1) Find electricity bus from N.buses
    if "carrier" not in N.buses.columns:
        raise ValueError("N.buses has no 'carrier' column; cannot auto-detect electricity bus.")
    cand = N.buses.index[N.buses["carrier"].astype(str).str.lower().isin(["electricity", "ac"])]
    if len(cand) == 0:
        raise ValueError("No bus with carrier 'electricity' or 'AC' found.")
    if len(cand) > 1:
        print(f"Multiple electricity-like buses detected. Using: {cand[0]}")
    bus = cand[0]

    # 2) Ensure marginal prices exist and bus is present
    if not hasattr(N, "buses_t") or "marginal_price" not in N.buses_t:
        raise ValueError("Marginal prices not available. Solve with duals (e.g., assign_all_duals=True).")
    if bus not in N.buses_t.marginal_price.columns:
        # fall back to first available priced bus
        avail = list(N.buses_t.marginal_price.columns)
        raise ValueError(f"Bus '{bus}' has no marginal prices. Available priced buses: {avail[:5]}{'...' if len(avail)>5 else ''}")

    s = N.buses_t.marginal_price[bus].dropna()

    # 3) Sort for duration curve
    s_sorted = s.sort_values(ascending=not descending).to_numpy()
    n = len(s_sorted)

    # 4) X axis
    if show_percentile_axis:
        x = np.linspace(0, 100, n, endpoint=False)
        x_label = "Percent of time [%]"
    else:
        x = np.arange(n)
        x_label = "Time steps"

    # 5) Plot
    plt.figure(figsize=figure_size)
    plt.step(x, s_sorted, where="post", label=f"Bus {bus}")
    plt.grid(True, alpha=0.3)
    plt.xlabel(x_label)
    plt.ylabel("Marginal price [EUR/MWh]")
    plt.title(title or "Price duration curve")
    plt.legend()
    plt.tight_layout()
    plt.show()

def plot_dispatch(network, colors=None, save_plots=False,
                  start_hour=0, duration_hours=7 * 24, interval=None,
                  title="Dispatch", figure_size=default_figsize):
    """
    Plot dispatch for a network.

    Parameters
    ----------
    network : pypsa.Network-like
    colors : dict or None
        mapping from component name -> matplotlib color
    save_plots : bool
    start_hour : int
        only used when `interval` is None (iloc-based slicing)
    duration_hours : int
        only used when `interval` is None (iloc-based slicing)
    interval : tuple (start, end) or None
        If provided, slices all time series with .loc[start:end] using
        the network time index. start/end can be pd.Timestamp, string, etc.
    title : str
    """
    import matplotlib.pyplot as plt

    # Determine slicing mode
    use_label_slice = interval is not None
    if use_label_slice:
        start, end = interval

    end_hour = start_hour + duration_hours

    plt.figure(figsize=figure_size)

    # Plot generator dispatch
    for generator in network.generators.index:
        # only plot sizable optimized capacities (keeps behaviour similar to your original)
        p_nom_opt = network.generators.p_nom_opt.get(generator, 0)
        if p_nom_opt <= 10:
            continue

        series = network.generators_t.p[generator]

        if use_label_slice:
            series_slice = series.loc[start:end]
        else:
            series_slice = series.iloc[start_hour:end_hour]

        # defensive: skip empty slices
        if series_slice.empty:
            continue

        plt.plot(series_slice.index, series_slice.values,
                 label=generator,
                 color=(colors.get(generator) if colors else None))

    # Plot hydro dispatch (storage_units_t.p_dispatch)
    storage_units = network.storage_units
    hydro_mask = (storage_units.carrier == "hydro") & (storage_units.bus == "electricity bus")
    if hydro_mask.any():
        for idx in storage_units[hydro_mask].index:
            # some pypsa versions: storage_units_t.p_dispatch or storage_units_t.p
            # prefer p_dispatch if available
            if "p_dispatch" in getattr(network.storage_units_t, "columns", []):
                series = network.storage_units_t.p_dispatch[idx]
            else:
                # fallback if different naming
                series = network.storage_units_t.p[idx]

            if use_label_slice:
                series_slice = series.loc[start:end]
            else:
                series_slice = series.iloc[start_hour:end_hour]

            if series_slice.empty:
                continue

            plt.plot(series_slice.index, series_slice.values,
                     label=f"{idx} (hydro dispatch)",
                     color=(colors.get("hydro") if colors else "green"),
                     linestyle="--")

    # Plot load (if present)
    # loads_t.p_set is usually a DataFrame with columns being load names; we used "load"
    try:
        load_series = network.loads_t.p_set["load"]
    except Exception:
        # try the case where loads_t.p_set has a different structure
        # pick the first column if "load" not present
        if hasattr(network.loads_t.p_set, "columns") and len(network.loads_t.p_set.columns) > 0:
            load_series = network.loads_t.p_set.iloc[:, 0]
        else:
            load_series = None

    if load_series is not None:
        if use_label_slice:
            load_slice = load_series.loc[start:end]
        else:
            load_slice = load_series.iloc[start_hour:end_hour]

        if not load_slice.empty:
            plt.plot(load_slice.index, load_slice.values,
                     label="load", color="black", linestyle=":")

    # Formatting
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.title(f'{title}', y=1.07)
    plt.ylabel('Generation in MWh')
    plt.grid(True, which='major', alpha=0.25)
    plt.legend()
    if save_plots:
        # derive a simple filename from interval or start_hour
        if use_label_slice:
            s = str(start).replace(":", "-")
            e = str(end).replace(":", "-")
            fname = f'./Plots/dispatch_{s}_to_{e}.png'
        else:
            fname = f'./Plots/dispatch_{start_hour}_{end_hour}.png'
        plt.savefig(fname, dpi=300, bbox_inches='tight')
    plt.show()

def plot_dispatch_bat(network, colors=None, save_plots=False, start_hour=0, duration_hours=7 * 24, title="Dispatch", figure_size=default_figsize):

    generators = network.generators.index
    storage_units = network.storage_units
    links = network.links

    end_hour = start_hour + duration_hours

    plt.figure(figsize=figure_size)

    # Plot generator dispatch
    for generator in generators:
        
        if getattr(network.generators, "p_nom_opt", network.generators.p_nom).get(generator, 0) > 10:
            plt.plot(
                network.generators_t.p[generator][start_hour:end_hour],
                label=generator,
                color=colors.get(generator, None) if colors else None
            )

    # Plot hydro dispatch
    hydro_mask = (storage_units.carrier == "hydro") & (storage_units.bus == "electricity bus")
    if hydro_mask.any():
        for idx in storage_units[hydro_mask].index:
            plt.plot(
                network.storage_units_t.p_dispatch[idx][start_hour:end_hour],
                label="hydro dispatch",
                color=colors.get("hydro", "green") if colors else "green",
                linestyle="--"
            )

    # Plot battery links (charge/discharge)
    if {"battery charge", "battery discharge"}.issubset(links.index):
        plt.plot(
            network.links_t.p0["battery charge"][start_hour:end_hour],
            label="battery charge (p0)",
            color=colors.get("battery charge", "blue") if colors else "blue",
            linestyle=":"
        )
        plt.plot(
            network.links_t.p1["battery discharge"][start_hour:end_hour],
            label="battery discharge (p1)",
            color=colors.get("battery discharge", "red") if colors else "red",
            linestyle=":"
        )

    # Plot load
    if "load" in network.loads.index:
        plt.plot(
            network.loads_t.p_set["load"][start_hour:end_hour],
            label="load",
            color="black",
            linestyle=":"
        )

    # X-axis formatting
    plt.xticks(rotation=45)
    plt.tight_layout()

    # Labels and title
    plt.title(f'Dispatch {title}', y=1.07)
    plt.ylabel('Generation in MWh')
    plt.grid(True, which='major', alpha=0.25)
    plt.legend()
    if save_plots:
        plt.savefig(f'./Plots/dispatch_{start_hour}.png', dpi=300, bbox_inches='tight')
    plt.show()

def plot_dispatch_elec_h2(network, save_plots=False,
                          start_hour=0, duration_hours=7*24, interval=None,
                          title="Dispatch", figure_size=default_figsize):
    """
    Plot dispatch for electricity bus including H2 conversion and load.
    Colors are automatically read from network.carriers.color.
    """

    def _slice_series(series, start_hour, duration_hours, interval):
        if interval is not None:
            s, e = interval
            return series.loc[s:e]
        else:
            return series.iloc[start_hour:start_hour + duration_hours]

    # Use carrier colors if present
    carrier_colors = (network.carriers.color
                      if hasattr(network, "carriers") and "color" in network.carriers.columns
                      else {})

    # Identify electricity bus
    elec_buses = network.buses.index[
        network.buses.carrier.astype(str).str.lower().isin(["electricity", "ac"])
    ]
    if len(elec_buses) == 0:
        raise ValueError("No electricity bus found")
    elec_bus = elec_buses[0]

    plt.figure(figsize=figure_size)
    use_label_slice = interval is not None

    # --- Generators ---
    for gen in network.generators.index[network.generators.bus == elec_bus]:
        p_nom_opt = network.generators.p_nom_opt.get(gen, 0)
        if p_nom_opt <= 10:
            continue
        series = network.generators_t.p[gen]
        series_slice = _slice_series(series, start_hour, duration_hours, interval)
        if series_slice.empty:
            continue
        color = carrier_colors.get(network.generators.loc[gen, "carrier"], None)
        plt.plot(series_slice.index, series_slice.values,
                 label=gen, color=color)

    # --- Fuel cell injections (bus1 == elec_bus) ---
    fc_mask = (network.links.carrier.str.lower() == "fuel cell") & (network.links.bus1 == elec_bus)
    for link in network.links.index[fc_mask]:
        s = network.links_t.p1[link]
        s_slice = _slice_series(s, start_hour, duration_hours, interval)
        if s_slice.empty:
            continue
        color = carrier_colors.get(network.links.loc[link, "carrier"], None)
        plt.plot(s_slice.index, -s_slice.values,
                 label=f"{link} (discharge)", color=color, linestyle="--")

    # --- Electrolyser draw (bus0 == elec_bus) ---
    ely_mask = (network.links.carrier.str.lower() == "electrolysis") & (network.links.bus0 == elec_bus)
    for link in network.links.index[ely_mask]:
        s = network.links_t.p0[link]
        s_slice = _slice_series(s, start_hour, duration_hours, interval)
        if s_slice.empty:
            continue
        color = carrier_colors.get(network.links.loc[link, "carrier"], None)
        plt.plot(s_slice.index, -s_slice.values,
                 label=f"{link} (charge)", color=color, linestyle=":")

    # --- Load ---
    load_series = None
    try:
        load_series = network.loads_t.p_set["load"]
    except Exception:
        if hasattr(network.loads_t.p_set, "columns") and len(network.loads_t.p_set.columns) > 0:
            load_series = network.loads_t.p_set.iloc[:, 0]

    if load_series is not None:
        load_slice = _slice_series(load_series, start_hour, duration_hours, interval)
        if not load_slice.empty:
            color = carrier_colors.get("load shedding", "black")
            plt.plot(load_slice.index, load_slice.values,
                     label="load", color=color, linestyle="-.")

    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.title(f"{title}", y=1.07)
    plt.ylabel("Power [MWh per snapshot]")
    plt.grid(True, alpha=0.25)
    plt.legend()
    if save_plots:
        s, e = interval if interval else (start_hour, start_hour + duration_hours)
        fname = f"./Plots/dispatch_{s}_to_{e}.png"
        plt.savefig(fname, dpi=300, bbox_inches="tight")
    
    # # --- Add vertical dashed lines for each 7-day horizon ---
    # if interval is not None:
    #     s, e = pd.to_datetime(interval[0]), pd.to_datetime(interval[1])
    #     horizon_starts = pd.date_range(start=s, end=e, freq="7D")
    # else:
    #     # use index range from one of your plotted series (e.g., load)
    #     if load_series is not None:
    #         s = load_slice.index[0]
    #         e = load_slice.index[-1]
    #         horizon_starts = pd.date_range(start=s, end=e, freq="7D")
    #     else:
    #         horizon_starts = []

    # for h in horizon_starts:
    #     plt.axvline(h, color="k", linestyle="--", linewidth=0.8, alpha=0.6)

    plt.show()

def plot_generator_capacity(results_df, generator, type, region, d_year_exp, h_year_exp, figure_size=default_figsize):
    """
    Plot capacity of a selected generator over years as bar and line plots.

    Parameters
    ----------
    results_df : pd.DataFrame
        MultiIndex DataFrame with (component, technology) columns, years as index.
    generator : str
        Name of the generator technology, e.g. 'onwind', 'solar'.
    region : str
        Region string for plot title.
    d_year_exp : int
        Demand year used in the experiment.
    h_year_exp : int
        Hydro year used in the experiment.
    """
    years = [int(y) for y in results_df.index]
    year_labels = [f"{y % 100:02d}/{(y + 1) % 100:02d}" for y in years]

    # Bar plot
    ax = results_df[(type, generator)].plot(
        kind='bar', figsize=(10, 5),
        title=f'{generator.capitalize()} Capacity Over Years - r: {region}, d: {d_year_exp}, h: {h_year_exp}'
    )
    plt.xlabel('Year')
    plt.ylabel('Capacity (MW)')
    ax.set_xticklabels(year_labels, rotation=45)
    plt.tight_layout()
    plt.show()

    # Line plot
    plt.figure(figsize=(10, 5))
    plt.plot(years, results_df[(type, generator)].values, marker='o')
    plt.xlabel("Year")
    plt.ylabel(f"{generator.capitalize()} Capacity (MW)")
    plt.title(f"{generator.capitalize()} Capacity Over Years - r: {region}, d: {d_year_exp}, h: {h_year_exp}")
    plt.xticks(years, year_labels, rotation=45)
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.show()

def plot_marginal_prices(network_pf, network_rh, month=None, interval=None, figure_size=default_figsize):
    # Extract marginal prices (first bus column)
    mc_pf = network_pf.buses_t['marginal_price'].iloc[:, 0]
    mc_rh = network_rh.buses_t['marginal_price'].iloc[:, 0]

    # Apply month filter
    if month is not None:
        mc_pf = mc_pf[mc_pf.index.month == month]
        mc_rh = mc_rh[mc_rh.index.month == month]

    # Apply interval filter
    if interval is not None:
        start, end = interval
        mc_pf = mc_pf.loc[start:end]
        mc_rh = mc_rh.loc[start:end]

    # Plot
    plt.figure(figsize=figure_size)
    plt.plot(mc_pf, label="Marginal prices PF", linestyle="--")
    plt.plot(mc_rh, label="Marginal prices RH", linestyle=":")
    plt.xlabel("Time")
    plt.ylabel("Marginal Price [EUR/MWh]")
    plt.title("Marginal Prices Comparison PF vs RH")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.show()

    # Cost calculations
    cost_pf = (network_pf.buses_t['marginal_price'].iloc[:, 0] * 
               network_pf.loads_t.p_set['load']).sum() / 1e6
    cost_rh = (network_rh.buses_t['marginal_price'].iloc[:, 0] * 
               network_rh.loads_t.p_set['load']).sum() / 1e6

    print(f"Sum of marginal prices (PF): {mc_pf.sum():.1f}")
    print(f"Sum of marginal prices (RH): {mc_rh.sum():.1f}")
    print(f"Total cost (PF) [MEUR]: {cost_pf:.2f}")
    print(f"Total cost (RH) [MEUR]: {cost_rh:.2f}")
    print(f"Total cost difference PF minus RH [MEUR]: {cost_rh - cost_pf:.2f}")

def plot_price_duration_curve(N, descending=True, show_percentile_axis=True, title=None, year=None, figure_size=default_figsize):
    """
    Plot a price duration curve for the electricity bus in network N.
    Unweighted. Automatically picks the electricity bus.
    """

    # 1) Find electricity bus from N.buses
    if "carrier" not in N.buses.columns:
        raise ValueError("N.buses has no 'carrier' column; cannot auto-detect electricity bus.")
    cand = N.buses.index[N.buses["carrier"].astype(str).str.lower().isin(["electricity", "ac"])]
    if len(cand) == 0:
        raise ValueError("No bus with carrier 'electricity' or 'AC' found.")
    if len(cand) > 1:
        print(f"Multiple electricity-like buses detected. Using: {cand[0]}")
    bus = cand[0]

    # 2) Ensure marginal prices exist and bus is present
    if not hasattr(N, "buses_t") or "marginal_price" not in N.buses_t:
        raise ValueError("Marginal prices not available. Solve with duals (e.g., assign_all_duals=True).")
    if bus not in N.buses_t.marginal_price.columns:
        # fall back to first available priced bus
        avail = list(N.buses_t.marginal_price.columns)
        raise ValueError(f"Bus '{bus}' has no marginal prices. Available priced buses: {avail[:5]}{'...' if len(avail)>5 else ''}")

    s = N.buses_t.marginal_price[bus].dropna()

    # 3) Sort for duration curve
    s_sorted = s.sort_values(ascending=not descending).to_numpy()
    n = len(s_sorted)

    # 4) X axis
    if show_percentile_axis:
        x = np.linspace(0, 100, n, endpoint=False)
        x_label = "Percent of time [%]"
    else:
        x = np.arange(n)
        x_label = "Time steps"

    # 5) Plot
    plt.figure(figsize=figure_size)
    plt.step(x, s_sorted, where="post", label=f"{bus}")
    plt.grid(True, alpha=0.3)
    plt.xlabel(x_label)
    plt.ylabel("Marginal price [EUR/MWh]")
    if year is not None:
        year_label = f"{int(year) % 100:02d}/{(int(year) + 1) % 100:02d}"
    else:
        year_label = ""

    plt.title(title or f"Price duration curve {year_label}")
    plt.legend()
    plt.tight_layout()
    plt.show()

# new, without year label on all graphs
def plot_price_duration_curves_all_years_new(
    networks: Dict[int, "pypsa.Network"],
    weather_years: List[int],
    title: str,
    figure_size: Tuple[float, float] = (7, 5),
    log_y: bool = False,
    clip_upper: Optional[float] = None,
    color: str = "0.4",
    alpha: float = 0.6,
    linewidth: float = 1.2,
    save: bool = False,
    save_path: Optional[Path] = None,
    save_name: Optional[str] = None,
):
    """
    Plot price duration curves for multiple weather years in one figure.
    All years are shown with the same color and no legend.
    """

    # Fixed layout to ensure identical exported PDF geometry across variants
    fig, ax = plt.subplots(figsize=figure_size, constrained_layout=False)

    for y in weather_years:
        pdc = get_price_duration(networks[y])

        if clip_upper is not None:
            pdc = pdc.clip(upper=clip_upper)

        pdc.plot(
            ax=ax,
            ylabel="Price [€/MWh]",
            xlabel="Fraction of Time [%]",
            legend=False,
            color=color,
            alpha=alpha,
            linewidth=linewidth,
        )

    ax.set_title(title)

    if log_y:
        ax.set_yscale("log")
        ax.set_ylabel("Price [€/MWh] (log scale)")

    ax.grid(True, axis="y", alpha=0.3)
    ax.grid(False, axis="x")

    # Enforce consistent margins across all saved figures
    # Adjust these if you change font sizes or have longer titles.
    fig.subplots_adjust(left=0.14, right=0.98, bottom=0.14, top=0.90)

    if save:
        if save_path is None or save_name is None:
            raise ValueError("When save=True, both save_path and save_name must be provided.")
        fig.savefig(save_path / save_name)  # no bbox_inches="tight"

    return fig, ax


def plot_price_duration_curves_all_years(
    networks: Dict[int, "pypsa.Network"],
    weather_years: List[int],
    title: str,
    figure_size: Tuple[float, float] = (7, 5),
    log_y: bool = False,
    clip_upper: Optional[float] = None,
    legend_ncol: int = 2,
    legend_fontsize: str = "x-small",
    save: bool = False,
    save_path: Optional[Path] = None,
    save_name: Optional[str] = None,
):
    """
    Plot price duration curves for multiple weather years in one figure.

    Parameters
    ----------
    networks : dict[int, pypsa.Network]
        Mapping from weather year to network.
    weather_years : list[int]
        Years to plot (order used for labels).
    title : str
        Plot title.
    figure_size : tuple
        Figure size.
    log_y : bool
        If True, y-axis is log scale.
    clip_upper : float | None
        If set, clip prices at this upper value before plotting.
    legend_ncol : int
        Number of legend columns.
    legend_fontsize : str
        Legend fontsize.
    save : bool
        If True, saves figure.
    save_path : Path | None
        Directory to save into.
    save_name : str | None
        Filename including extension.
    """
    year_labels = [f"{y % 100:02d}/{(y + 1) % 100:02d}" for y in weather_years]

    fig, ax = plt.subplots(figsize=figure_size, constrained_layout=True)

    for n, y in enumerate(weather_years):
        pdc = get_price_duration(networks[y])
        if clip_upper is not None:
            pdc = pdc.clip(upper=clip_upper)

        pdc.plot(
            ax=ax,
            ylabel="Price [€/MWh]",
            xlabel="Fraction of Time [%]",
            label=year_labels[n],
            legend=False,
        )

    ax.set_title(title)
    if log_y:
        ax.set_yscale("log")
        ax.set_ylabel("Price [€/MWh] (log scale)")

    ax.grid(True, axis="y", alpha=0.3)
    ax.grid(False, axis="x")

    ax.legend(loc="best", ncol=legend_ncol, fontsize=legend_fontsize, frameon=False)

    if save:
        fig.savefig(save_path / save_name, bbox_inches="tight")

    return fig, ax

def plot_price_duration_curves_two_models(
    networks_a: Dict[int, "pypsa.Network"],
    networks_b: Dict[int, "pypsa.Network"],
    weather_years: List[int],
    label_a: str,
    label_b: str,
    title: str,
    figure_size: Tuple[float, float] = (7, 5),
    log_y: bool = False,
    clip_upper: Optional[float] = None,
    color_a: str = "0.4",
    color_b: str = "tab:blue",
    alpha: float = 0.5,
    linewidth: float = 1.2,
    save: bool = False,
    save_path: Optional[Path] = None,
    save_name: Optional[str] = None,
):
    """
    Plot price duration curves for two model variants in the same figure.
    Each model is shown with one color across all weather years.
    """

    # Fixed layout to match other plotting functions
    fig, ax = plt.subplots(figsize=figure_size, constrained_layout=False)

    # Model A
    for y in weather_years:
        pdc = get_price_duration(networks_a[y])
        if clip_upper is not None:
            pdc = pdc.clip(upper=clip_upper)

        pdc.plot(
            ax=ax,
            legend=False,
            color=color_a,
            alpha=alpha,
            linewidth=linewidth,
        )

    # Model B
    for y in weather_years:
        pdc = get_price_duration(networks_b[y])
        if clip_upper is not None:
            pdc = pdc.clip(upper=clip_upper)

        pdc.plot(
            ax=ax,
            legend=False,
            color=color_b,
            alpha=alpha,
            linewidth=linewidth,
        )

    ax.set_title(title)
    ax.set_xlabel("Fraction of Time [%]")

    if log_y:
        ax.set_yscale("log")
        ax.set_ylabel("Price [€/MWh] (log scale)")
    else:
        ax.set_ylabel("Price [€/MWh]")

    ax.grid(True, axis="y", alpha=0.3)
    ax.grid(False, axis="x")

    # Clean legend: one handle per model, fixed placement
    handles = [
        mpl.lines.Line2D([], [], color=color_a, linewidth=2, label=label_a),
        mpl.lines.Line2D([], [], color=color_b, linewidth=2, label=label_b),
    ]
    ax.legend(
        handles=handles,
        frameon=True,
        loc="upper right",
    )

    # Same margins as your single-model function
    fig.subplots_adjust(left=0.14, right=0.98, bottom=0.14, top=0.90)

    if save:
        if save_path is None or save_name is None:
            raise ValueError("When save=True, both save_path and save_name must be provided.")
        fig.savefig(save_path / save_name)

    return fig, ax


def plot_h2(network_pf, network_rh, interval=None,
            normalized=True, show_links=True, show_soc=True, same_axes=False, figure_size=default_figsize):
    """
    Compare H2 system behavior between perfect foresight and rolling horizon.
    SOC is normalized by installed H2 storage capacity (sum of e_nom_opt or e_nom).
    """

    carrier_colors = (network_pf.carriers.color
                      if hasattr(network_pf, "carriers") and "color" in network_pf.carriers.columns
                      else {})

    def extract_h2_series_and_cap(net):
        # electricity bus
        elec_buses = net.buses.index[net.buses.carrier.astype(str).str.lower().isin(["electricity","ac"])]
        if len(elec_buses) == 0:
            raise ValueError("No electricity bus found")
        elec_bus = elec_buses[0]

        # links
        fc_mask  = (net.links.carrier.str.lower() == "fuel cell")    & (net.links.bus1 == elec_bus)
        ely_mask = (net.links.carrier.str.lower() == "electrolysis") & (net.links.bus0 == elec_bus)

        # fuel cell injects at bus1 so p1 is negative when injecting -> flip sign
        fc  = (-net.links_t.p1[net.links.index[fc_mask]].sum(axis=1)) if fc_mask.any() else None
        # electrolyser draws from bus0 -> p0 positive when withdrawing from electricity
        ely = ( net.links_t.p0[net.links.index[ely_mask]].sum(axis=1)) if ely_mask.any() else None

        # H2 store SOC and capacity
        store_mask = net.stores.carrier.str.lower().isin(["hydrogen storage","hydrogen","h2 storage"]) \
                     if hasattr(net, "stores") and len(net.stores) else []
        soc = None
        cap = 0.0
        if hasattr(net, "stores") and len(net.stores) and store_mask.any():
            ids = net.stores.index[store_mask]
            soc = net.stores_t.e[ids].sum(axis=1)
            # normalize by installed capacity: prefer e_nom_opt if available, else e_nom
            if "e_nom_opt" in net.stores.columns and net.stores["e_nom_opt"].notna().any():
                cap = float(net.stores.loc[ids, "e_nom_opt"].fillna(0).sum())
            else:
                cap = float(net.stores.loc[ids, "e_nom"].fillna(0).sum())

        # fallback if StorageUnit is used
        if soc is None and hasattr(net, "storage_units") and len(net.storage_units):
            su_mask = net.storage_units.carrier.str.lower().isin(["hydrogen storage","hydrogen","h2 storage"])
            if su_mask.any():
                ids = net.storage_units.index[su_mask]
                if hasattr(net.storage_units_t, "state_of_charge"):
                    soc = net.storage_units_t.state_of_charge[ids].sum(axis=1)
                if "p_nom_opt" in net.storage_units.columns and net.storage_units["p_nom_opt"].notna().any():
                    cap = float(net.storage_units.loc[ids, "p_nom_opt"].fillna(0).sum())
                else:
                    cap = float(net.storage_units.loc[ids, "p_nom"].fillna(0).sum())

        return fc, ely, soc, cap

    fc_pf, ely_pf, soc_pf, cap_pf = extract_h2_series_and_cap(network_pf)
    fc_rh, ely_rh, soc_rh, cap_rh = extract_h2_series_and_cap(network_rh)

    # interval slicing
    if interval:
        s, e = interval
        fc_pf, ely_pf, soc_pf = [x.loc[s:e] if x is not None else None for x in (fc_pf, ely_pf, soc_pf)]
        fc_rh, ely_rh, soc_rh = [x.loc[s:e] if x is not None else None for x in (fc_rh, ely_rh, soc_rh)]

    # normalization
    def nrm_links(s):
        if s is None or s.empty:
            return s
        m = float(np.nanmax(np.abs(s.values)))
        return s/m if m > 0 else s*0

    if normalized:
        # links normalized by their own absolute max for visual comparison
        fc_pf  = nrm_links(fc_pf)
        ely_pf = nrm_links(ely_pf)
        fc_rh  = nrm_links(fc_rh)
        ely_rh = nrm_links(ely_rh)
        # SOC normalized by installed capacity
        if soc_pf is not None and cap_pf > 0:
            soc_pf = soc_pf / cap_pf
        if soc_rh is not None and cap_rh > 0:
            soc_rh = soc_rh / cap_rh

    color_fc  = "#ff0000"
    color_ely = carrier_colors.get("electrolysis", "green")
    color_soc = carrier_colors.get("hydrogen",   "deepskyblue")

    if same_axes:
        fig, ax = plt.subplots(figsize=figure_size)
        if show_links and fc_pf  is not None: ax.plot(fc_pf,  label="Fuel cell PF", color=color_fc)
        if show_links and fc_rh  is not None: ax.plot(fc_rh,  label="Fuel cell RH", color=color_fc, linestyle="--")
        if show_links and ely_pf is not None: ax.plot(ely_pf, label="Electrolyser PF", color=color_ely)
        if show_links and ely_rh is not None: ax.plot(ely_rh, label="Electrolyser RH", color=color_ely, linestyle="--")
        if show_soc   and soc_pf is not None: ax.plot(soc_pf, label=f"H₂ SOC PF MWh", color=color_soc)
        if show_soc   and soc_rh is not None: ax.plot(soc_rh, label=f"H₂ SOC RH MWh", color=color_soc, linestyle="--")
        ax.set_title(f"{'Normalized ' if normalized else ''}Hydrogen system — PF vs RH")
        ax.set_ylabel("Normalized" if normalized else "Power or Energy")
        if normalized: ax.set_ylim(0, 1.1)
        ax.grid(True); ax.legend(loc="best")
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(mdates.AutoDateLocator()))
        plt.xticks(rotation=30); plt.tight_layout()
        return fig, ax
    else:
        fig, axes = plt.subplots(2, 1, figsize=figure_size, sharex=True)
        # RH
        if show_links and fc_rh  is not None: axes[0].plot(fc_rh,  label="Fuel cell RH", color=color_fc)
        if show_links and ely_rh is not None: axes[0].plot(ely_rh, label="Electrolyser RH", color=color_ely)
        if show_soc   and soc_rh is not None: axes[0].plot(soc_rh, label=f"H₂ SOC RH MWh", color=color_soc)
        axes[0].set_title(f"{'Normalized ' if normalized else ''}Rolling horizon")
        axes[0].grid(True); axes[0].legend(loc="best")
        # PF
        if show_links and fc_pf  is not None: axes[1].plot(fc_pf,  label="Fuel cell PF", color=color_fc)
        if show_links and ely_pf is not None: axes[1].plot(ely_pf, label="Electrolyser PF", color=color_ely)
        if show_soc   and soc_pf is not None: axes[1].plot(soc_pf, label=f"H₂ SOC PF MWh", color=color_soc)
        axes[1].set_title(f"{'Normalized ' if normalized else ''}Perfect foresight")
        axes[1].set_xlabel("Date")
        if normalized: axes[1].set_ylim(0, 1.1)
        axes[1].grid(True); axes[1].legend(loc="best")
        axes[1].xaxis.set_major_locator(mdates.AutoDateLocator())
        axes[1].xaxis.set_major_formatter(mdates.ConciseDateFormatter(mdates.AutoDateLocator()))
        plt.xticks(rotation=30); plt.tight_layout()
        return fig, axes

def plot_h2_new(
    Year,
    network_pf,
    network_rh,
    interval=None,
    normalized=True,
    show_links=True,
    show_soc=True,
    same_axes=False,
    colors: Optional[Dict[str, str]] = None,
    title_prefix: Optional[str] = None,
    figure_size: Tuple[float, float] = (12, 8),
):
    """
    Compare H2 system behavior between perfect foresight and rolling horizon.
    SOC is normalized by installed H2 storage capacity (sum of e_nom_opt or e_nom).
    Colors default to network carrier colors, but can be overridden by `colors`.
    """

    carrier_colors = (
        network_pf.carriers["color"].to_dict()
        if hasattr(network_pf, "carriers") and "color" in network_pf.carriers.columns
        else {}
    )

    def get_color(key: str, fallback: str) -> str:
        if colors is not None and key in colors:
            return colors[key]
        if key in carrier_colors:
            return carrier_colors[key]
        return fallback

    def extract_h2_series_and_cap(net):
        elec_buses = net.buses.index[
            net.buses.carrier.astype(str).str.lower().isin(["electricity", "ac"])
        ]
        if len(elec_buses) == 0:
            raise ValueError("No electricity bus found")
        elec_bus = elec_buses[0]

        fc_mask = (net.links.carrier.str.lower() == "fuel cell") & (net.links.bus1 == elec_bus)
        ely_mask = (net.links.carrier.str.lower() == "electrolysis") & (net.links.bus0 == elec_bus)

        fc = (-net.links_t.p1[net.links.index[fc_mask]].sum(axis=1)) if fc_mask.any() else None
        ely = (net.links_t.p0[net.links.index[ely_mask]].sum(axis=1)) if ely_mask.any() else None

        soc = None
        cap = 0.0

        if hasattr(net, "stores") and len(net.stores):
            store_mask = net.stores.carrier.str.lower().isin(
                ["hydrogen storage", "hydrogen", "h2 storage"]
            )
            if store_mask.any():
                ids = net.stores.index[store_mask]
                soc = net.stores_t.e[ids].sum(axis=1)
                if "e_nom_opt" in net.stores.columns and net.stores["e_nom_opt"].notna().any():
                    cap = float(net.stores.loc[ids, "e_nom_opt"].fillna(0).sum())
                else:
                    cap = float(net.stores.loc[ids, "e_nom"].fillna(0).sum())

        if soc is None and hasattr(net, "storage_units") and len(net.storage_units):
            su_mask = net.storage_units.carrier.str.lower().isin(
                ["hydrogen storage", "hydrogen", "h2 storage"]
            )
            if su_mask.any():
                ids = net.storage_units.index[su_mask]
                if hasattr(net.storage_units_t, "state_of_charge"):
                    soc = net.storage_units_t.state_of_charge[ids].sum(axis=1)
                if "p_nom_opt" in net.storage_units.columns and net.storage_units["p_nom_opt"].notna().any():
                    cap = float(net.storage_units.loc[ids, "p_nom_opt"].fillna(0).sum())
                else:
                    cap = float(net.storage_units.loc[ids, "p_nom"].fillna(0).sum())

        return fc, ely, soc, cap

    fc_pf, ely_pf, soc_pf, cap_pf = extract_h2_series_and_cap(network_pf)
    fc_rh, ely_rh, soc_rh, cap_rh = extract_h2_series_and_cap(network_rh)

    if interval:
        s, e = interval
        fc_pf, ely_pf, soc_pf = [x.loc[s:e] if x is not None else None for x in (fc_pf, ely_pf, soc_pf)]
        fc_rh, ely_rh, soc_rh = [x.loc[s:e] if x is not None else None for x in (fc_rh, ely_rh, soc_rh)]

    def nrm_links(s):
        if s is None or s.empty:
            return s
        m = float(np.nanmax(np.abs(s.values)))
        return s / m if m > 0 else s * 0

    if normalized:
        fc_pf = nrm_links(fc_pf)
        ely_pf = nrm_links(ely_pf)
        fc_rh = nrm_links(fc_rh)
        ely_rh = nrm_links(ely_rh)

        if soc_pf is not None and cap_pf > 0:
            soc_pf = soc_pf / cap_pf
        if soc_rh is not None and cap_rh > 0:
            soc_rh = soc_rh / cap_rh

    color_fc = get_color("fuel cell", "#d62728")
    color_ely = get_color("electrolysis", "#2ca02c")
    color_soc = get_color("hydrogen", "#1f77b4")

    lw_links = 0.9
    lw_soc = 1.6
    alpha_links = 0.55
    alpha_soc = 0.95

    month_locator = mdates.MonthLocator()
    month_formatter = mdates.DateFormatter("%b")

    yy = f"{str(Year)[-2:]}/{str(Year + 1)[-2:]}"
    base = f"{title_prefix} " if title_prefix is not None else ""
    norm_txt = "(normalized)" if normalized else ""

    if same_axes:
        fig, ax = plt.subplots(figsize=figure_size, constrained_layout=True)

        if show_links and fc_pf is not None:
            ax.plot(fc_pf, label="Fuel cell PF", color=color_fc, linewidth=lw_links, alpha=alpha_links)
        if show_links and fc_rh is not None:
            ax.plot(fc_rh, label="Fuel cell RH", color=color_fc, linestyle="--", linewidth=lw_links, alpha=alpha_links)

        if show_links and ely_pf is not None:
            ax.plot(ely_pf, label="Electrolyser PF", color=color_ely, linewidth=lw_links, alpha=alpha_links)
        if show_links and ely_rh is not None:
            ax.plot(ely_rh, label="Electrolyser RH", color=color_ely, linestyle="--", linewidth=lw_links, alpha=alpha_links)

        if show_soc and soc_pf is not None:
            ax.plot(soc_pf, label="H2 SOC PF", color=color_soc, linewidth=lw_soc, alpha=alpha_soc)
        if show_soc and soc_rh is not None:
            ax.plot(soc_rh, label="H2 SOC RH", color=color_soc, linestyle="--", linewidth=lw_soc, alpha=alpha_soc)

        ax.set_title(f"{base}Hydrogen system PF vs RH {yy} {norm_txt}".strip())
        ax.set_ylabel("SOC p.u." if normalized else "Power / Energy [MW / MWh]")

        ax.xaxis.set_major_locator(month_locator)
        ax.xaxis.set_major_formatter(month_formatter)

        ax.grid(True, axis="y", alpha=0.3)
        ax.grid(False, axis="x")

        ax.legend(
            bbox_to_anchor=(1.02, 1),
            loc="upper left",
            frameon=False,
            fontsize=LEGEND_FONTSIZE,
            handlelength=1.2,
            columnspacing=0.8,
            labelspacing=0.3,
            borderaxespad=0.3,
        )

        return fig, ax

    fig, axes = plt.subplots(2, 1, figsize=figure_size, sharex=True, constrained_layout=True)

    axes[0].set_title(f"{base}Rolling horizon {yy} {norm_txt}".strip())
    axes[1].set_title(f"{base}Perfect foresight {yy} {norm_txt}".strip())

    for ax, fc, ely, soc in zip(axes, (fc_rh, fc_pf), (ely_rh, ely_pf), (soc_rh, soc_pf)):
        if show_links and fc is not None:
            ax.plot(fc, color=color_fc, linewidth=lw_links, alpha=alpha_links)
        if show_links and ely is not None:
            ax.plot(ely, color=color_ely, linewidth=lw_links, alpha=alpha_links)
        if show_soc and soc is not None:
            ax.plot(soc, color=color_soc, linewidth=lw_soc, alpha=alpha_soc)

        ax.grid(True, axis="y", alpha=0.3)
        ax.grid(False, axis="x")
        if normalized:
            ax.set_ylim(0, 1.1)

    axes[0].set_ylabel("SOC p.u." if normalized else "Power / Energy [MW / MWh]")
    axes[1].set_ylabel("SOC p.u." if normalized else "Power / Energy [MW / MWh]")
    axes[1].set_xlabel("Date")

    axes[1].xaxis.set_major_locator(month_locator)
    axes[1].xaxis.set_major_formatter(month_formatter)

    return fig, axes


def plot_h2_multi(
    Year,
    models: List[Dict[str, Any]],
    interval=None,
    normalized=True,
    show_links=True,
    show_soc=True,
    same_axes=False,
    colors: Optional[Dict[str, str]] = None,
    title_prefix: Optional[str] = None,
    figure_size: Tuple[float, float] = (12, 8),
):
    """
    Compare H2 system behavior across multiple models (up to 5).

    Parameters
    ----------
    Year : int
        Used only for title formatting (YY/YY+1).
    models : list of dict
        Each dict:
            {
              "network": pypsa.Network,
              "title": str,
              "ls": str (optional, default "-")  # line style for this model
            }
        Example:
            models = [
                {"network": networks_pf[Year], "title": "Perfect foresight", "ls": "-"},
                {"network": networks_rh[Year], "title": "Rolling horizon", "ls": "--"},
            ]
    interval : (start, end) tuple or None
        Optional time slicing.
    normalized : bool
        If True, link series normalized by their max abs; SOC normalized by installed storage cap.
    show_links, show_soc : bool
        Toggle plotting of fuel cell/electrolyser and SOC.
    same_axes : bool
        If True: all models in ONE axis (overlay).
        If False: one subplot per model (stacked).
    colors : dict or None
        Override colors. Keys expected:
            "fuel cell", "electrolysis", "hydrogen"
        (same behavior as before)
    title_prefix : str or None
        Prepended to titles.
    figure_size : (w, h)
        Figure size.

    Returns
    -------
    fig, ax_or_axes
    """

    if len(models) == 0:
        raise ValueError("models must contain at least one entry.")
    if len(models) > 5:
        raise ValueError("models can contain at most 5 entries.")

    # carrier color lookup from first model (fallback)
    first_net = models[0]["networks"]
    carrier_colors = (
        first_net.carriers["color"].to_dict()
        if hasattr(first_net, "carriers") and "color" in first_net.carriers.columns
        else {}
    )

    def get_color(key: str, fallback: str) -> str:
        if colors is not None and key in colors:
            return colors[key]
        if key in carrier_colors:
            return carrier_colors[key]
        return fallback

    def extract_h2_series_and_cap(net):
        elec_buses = net.buses.index[
            net.buses.carrier.astype(str).str.lower().isin(["electricity", "ac"])
        ]
        if len(elec_buses) == 0:
            raise ValueError("No electricity bus found")
        elec_bus = elec_buses[0]

        fc_mask = (net.links.carrier.str.lower() == "fuel cell") & (net.links.bus1 == elec_bus)
        ely_mask = (net.links.carrier.str.lower() == "electrolysis") & (net.links.bus0 == elec_bus)

        fc = (-net.links_t.p1[net.links.index[fc_mask]].sum(axis=1)) if fc_mask.any() else None
        ely = (net.links_t.p0[net.links.index[ely_mask]].sum(axis=1)) if ely_mask.any() else None

        soc = None
        cap = 0.0

        if hasattr(net, "stores") and len(net.stores):
            store_mask = net.stores.carrier.str.lower().isin(["hydrogen storage", "hydrogen", "h2 storage"])
            if store_mask.any():
                ids = net.stores.index[store_mask]
                soc = net.stores_t.e[ids].sum(axis=1)
                if "e_nom_opt" in net.stores.columns and net.stores["e_nom_opt"].notna().any():
                    cap = float(net.stores.loc[ids, "e_nom_opt"].fillna(0).sum())
                else:
                    cap = float(net.stores.loc[ids, "e_nom"].fillna(0).sum())

        if soc is None and hasattr(net, "storage_units") and len(net.storage_units):
            su_mask = net.storage_units.carrier.str.lower().isin(["hydrogen storage", "hydrogen", "h2 storage"])
            if su_mask.any():
                ids = net.storage_units.index[su_mask]
                if hasattr(net.storage_units_t, "state_of_charge"):
                    soc = net.storage_units_t.state_of_charge[ids].sum(axis=1)
                if "p_nom_opt" in net.storage_units.columns and net.storage_units["p_nom_opt"].notna().any():
                    cap = float(net.storage_units.loc[ids, "p_nom_opt"].fillna(0).sum())
                else:
                    cap = float(net.storage_units.loc[ids, "p_nom"].fillna(0).sum())

        return fc, ely, soc, cap

    def nrm_links(s):
        if s is None or s.empty:
            return s
        m = float(np.nanmax(np.abs(s.values)))
        return s / m if m > 0 else s * 0

    # style
    color_fc = get_color("fuel cell", "#d62728")
    color_ely = get_color("electrolysis", "#2ca02c")
    color_soc = get_color("hydrogen", "#1f77b4")

    lw_links = 0.9
    lw_soc = 1.6
    alpha_links = 0.55
    alpha_soc = 0.95

    month_locator = mdates.MonthLocator()
    month_formatter = mdates.DateFormatter("%b")

    yy = f"{str(Year)[-2:]}/{str(Year + 1)[-2:]}"
    base = f"{title_prefix} " if title_prefix is not None else ""
    norm_txt = "(normalized)" if normalized else ""

    # helper to prep one model
    def prep_one(net):
        fc, ely, soc, cap = extract_h2_series_and_cap(net)

        if interval:
            s, e = interval
            fc, ely, soc = [x.loc[s:e] if x is not None else None for x in (fc, ely, soc)]

        if normalized:
            fc = nrm_links(fc)
            ely = nrm_links(ely)
            if soc is not None and cap > 0:
                soc = soc / cap

        return fc, ely, soc

    # precompute series
    series = []
    for m in models:
        net = m["networks"]
        title = m.get("title", "")
        ls = m.get("ls", "-")
        fc, ely, soc = prep_one(net)
        series.append({"title": title, "ls": ls, "fc": fc, "ely": ely, "soc": soc})

    if same_axes:
        fig, ax = plt.subplots(figsize=figure_size, constrained_layout=True)

        for s in series:
            title = s["title"]
            ls = s["ls"]

            if show_links and s["fc"] is not None:
                ax.plot(s["fc"], label=f"{title} Fuel cell", color=color_fc, linestyle=ls,
                        linewidth=lw_links, alpha=alpha_links)
            if show_links and s["ely"] is not None:
                ax.plot(s["ely"], label=f"{title} Electrolyser", color=color_ely, linestyle=ls,
                        linewidth=lw_links, alpha=alpha_links)
            if show_soc and s["soc"] is not None:
                ax.plot(s["soc"], label=f"{title} H2 SOC", color=color_soc, linestyle=ls,
                        linewidth=lw_soc, alpha=alpha_soc)

        ax.set_title(f"{base}Hydrogen system {yy} {norm_txt}".strip())
        ax.set_ylabel("SOC p.u." if normalized else "Power / Energy [MW / MWh]")

        ax.xaxis.set_major_locator(month_locator)
        ax.xaxis.set_major_formatter(month_formatter)

        ax.grid(True, axis="y", alpha=0.3)
        ax.grid(False, axis="x")
        if normalized:
            ax.set_ylim(0, 1.1)

        ax.legend(
            bbox_to_anchor=(1.02, 1),
            loc="upper left",
            frameon=False,
            fontsize=LEGEND_FONTSIZE,
            handlelength=1.2,
            columnspacing=0.8,
            labelspacing=0.3,
            borderaxespad=0.3,
        )

        return fig, ax

    # stacked mode: one subplot per model
    n = len(series)
    fig, axes = plt.subplots(n, 1, figsize=figure_size, sharex=True, constrained_layout=True)
    if n == 1:
        axes = [axes]

    for ax, s in zip(axes, series):
        if show_links and s["fc"] is not None:
            ax.plot(s["fc"], color=color_fc, linestyle=s["ls"], linewidth=lw_links, alpha=alpha_links)
        if show_links and s["ely"] is not None:
            ax.plot(s["ely"], color=color_ely, linestyle=s["ls"], linewidth=lw_links, alpha=alpha_links)
        if show_soc and s["soc"] is not None:
            ax.plot(s["soc"], color=color_soc, linestyle=s["ls"], linewidth=lw_soc, alpha=alpha_soc)

        ax.set_title(f"{s['title']} {yy} {norm_txt}".strip())
        ax.grid(True, axis="y", alpha=0.3)
        ax.grid(False, axis="x")
        if normalized:
            ax.set_ylim(0, 1.1)
        ax.set_ylabel("SOC p.u." if normalized else "Power / Energy [MW / MWh]")

    axes[-1].set_xlabel("Date")
    axes[-1].xaxis.set_major_locator(month_locator)
    axes[-1].xaxis.set_major_formatter(month_formatter)

    return fig, axes


def get_price_duration(n: pypsa.Network, bus: str = "electricity bus", figure_size=default_figsize) -> pd.Series:
    s = (
        n.buses_t.marginal_price[bus]
        .sort_values(ascending=False)
        .reset_index(drop=True)
    )
    s.index = np.arange(0, 100, 100 / len(s.index))
    return s

def plot_h2_soc_all_years(
    networks: dict,
    carrier: str = "hydrogen storage",
    normalized: bool = True,
    mode: str = "standard",
    save_name: str | None = None,
    save_path: str | Path | None = None,
    show: bool = True,
    title : str | None = None,
    figure_size: Tuple[float, float] = default_figsize,
):
    """
    Plot SOC of hydrogen store for all networks/years in one figure.

    mode:
        "standard" : original time resolution
        "weekly"   : 7 day average
        "monthly"  : monthly average
    """

    mode = mode.lower()
    if mode not in {"standard", "weekly", "monthly"}:
        raise ValueError("mode must be 'standard', 'weekly' or 'monthly'")

    fig, ax = plt.subplots(figsize=figure_size, constrained_layout=True)
    dummy_year = 2000

    for year, net in sorted(networks.items()):
        mask = net.stores.carrier.str.lower() == carrier.lower()
        if not mask.any():
            continue

        ids = net.stores.index[mask]
        soc = net.stores_t.e[ids].sum(axis=1)

        if normalized:
            if "e_nom_opt" in net.stores.columns and net.stores["e_nom_opt"].notna().any():
                cap = net.stores.loc[ids, "e_nom_opt"].sum()
            else:
                cap = net.stores.loc[ids, "e_nom"].sum()

            if cap > 0:
                soc = soc / cap
            else:
                continue

        if mode == "weekly":
            soc = soc.resample("7D").mean()
        elif mode == "monthly":
            soc = soc.resample("ME").mean()

        idx = soc.index

        if mode == "monthly":
            dummy_idx = pd.DatetimeIndex(
                [pd.Timestamp(dummy_year, ts.month, 1) for ts in idx]
            )
        else:
            dummy_idx = pd.DatetimeIndex(
                [pd.Timestamp(dummy_year, ts.month, ts.day, ts.hour, ts.minute)
                 for ts in idx]
            )

        ax.plot(
            dummy_idx,
            soc.values,
            label=str(year),
            linewidth=1.0,
            alpha=0.8,  
        )

    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
    ax.set_xlim(pd.Timestamp(dummy_year, 1, 1), pd.Timestamp(dummy_year, 12, 31))

    ax.grid(True, axis="y", alpha=0.3)
    ax.grid(False, axis="x")

    if normalized:
        ax.set_ylim(0, 1)

    if mode == "standard":
        title_part = ""
    elif mode == "weekly":
        title_part = " weekly average"
    else:
        title_part = " monthly average"
        
    if title is None:
        ax.set_title(
            "Hydrogen SOC" + title_part + " for all years" +
            (" (normalized)" if normalized else "")
        )
    else:
        ax.set_title(title)

    ax.set_ylabel("SOC [p.u.]" if normalized else "SOC [MWh]")
    ax.set_xlabel("Months")

    ax.legend(
        title="Year",
        bbox_to_anchor=(1.02, 1.02),
        loc="upper left",
        ncol=2,
        frameon=True,
    )

    #fig.tight_layout()

    if save_name is not None:
        plt.savefig(
            Figures_mdl_setup_path / save_name,
            bbox_inches="tight",
        )

    if show:
        plt.show()

    return fig, ax

def plot_with_horizons(series, horizon_days=4, color="C0", title: str = None, figure_size=default_figsize):
    snaps = series.index
    start = snaps[0]
    h = pd.Timedelta(days=horizon_days)

    # compute horizon boundaries
    horizon_times = [start + i*h for i in range(1, int((snaps[-1]-start)/h)+1)]
    horizon_times = snaps.get_indexer(horizon_times, method="nearest")
    horizon_times = snaps[horizon_times]

    # plot
    fig, ax = plt.subplots(figsize=(12,6))
    series.plot(ax=ax, color=color)

    for t in horizon_times:
        plt.figure(figsize=figure_size)
        ax.axvline(t, color="C1", ls="--", lw=1)

    ax.set_xlabel("")
    ax.set_ylabel("")
    plt.title(title)
    plt.tight_layout()
    return ax

def plot_stacked_generator_capacities(
    results_df: pd.DataFrame,
    tech_list: List[str],
    colors: Optional[Dict[str, str]] = None,
    figsize: Tuple[float, float] = (10, 5),
    title: Optional[str] = None,
    save_plots: bool = False,
):
    """
    Stacked bar plot of selected capacities over years.

    Expects MultiIndex columns like (component, technology), years as index.
    Selects all columns whose technology (level 1) is in tech_list.
    """

    if not isinstance(results_df.columns, pd.MultiIndex) or results_df.columns.nlevels < 2:
        raise ValueError("results_df must have MultiIndex columns with at least 2 levels: (component, technology)")

    tech_level = results_df.columns.get_level_values(1)

    selected_cols = [col for col in results_df.columns if col[1] in tech_list]
    missing = [t for t in tech_list if t not in set(tech_level)]

    if missing:
        raise KeyError(f"Missing technologies in results_df columns level 1: {missing}")

    plot_df = results_df.loc[:, selected_cols].copy()

    # If a technology appears under multiple components, sum them
    plot_df.columns = [c[1] for c in plot_df.columns]
    plot_df = plot_df.groupby(level=0, axis=1).sum()

    # Keep the requested order
    plot_df = plot_df.loc[:, tech_list]

    color_list = None
    if colors is not None:
        color_list = [colors.get(t, None) for t in plot_df.columns]

    ax = plot_df.plot(
        kind="bar",
        stacked=True,
        figsize=figsize,
        color=color_list,
        width=0.85,
        edgecolor="none",
    )

    ax.set_title(title if title is not None else "Stacked capacities over years", pad=28)
    ax.set_xlabel("Year")
    ax.set_ylabel("Capacity [MW]")

    ax.legend(frameon=False, ncol=4, loc="upper center", bbox_to_anchor=(0.5, 1.1))

    plt.xticks(rotation=45, ha="right")
    ax.set_xticklabels([f"{y%100:02d}/{(y+1)%100:02d}" for y in results_df.index])
    plt.tight_layout()
    

    if save_plots:
        plt.savefig(
            Figures_mdl_setup_path / "exp_stacked_generator_capacities.pdf",
            bbox_inches="tight",
        )
    
    plt.show()
    return ax

def plot_stacked_generator_capacities_w_demand(
    results_df: pd.DataFrame,
    tech_list: List[str],
    stats: pd.Series,
    colors: Optional[Dict[str, str]] = None,
    figsize: Tuple[float, float] = (10, 5),
    title: Optional[str] = None,
    save_plots: bool = False,
):
    """
    Stacked bar plot of selected capacities over years with mean/max demand overlay.
    Values shown in GW.
    """

    if not isinstance(results_df.columns, pd.MultiIndex) or results_df.columns.nlevels < 2:
        raise ValueError("results_df must have MultiIndex columns with at least 2 levels: (component, technology)")

    tech_level = results_df.columns.get_level_values(1)

    selected_cols = [col for col in results_df.columns if col[1] in tech_list]
    missing = [t for t in tech_list if t not in set(tech_level)]

    if missing:
        raise KeyError(f"Missing technologies in results_df columns level 1: {missing}")

    plot_df = results_df.loc[:, selected_cols].copy()

    plot_df.columns = [c[1] for c in plot_df.columns]
    plot_df = plot_df.groupby(level=0, axis=1).sum()
    plot_df = plot_df.loc[:, tech_list]

    plot_df /= 1e3

    color_list = None
    if colors is not None:
        color_list = [colors.get(t, None) for t in plot_df.columns]

    ax = plot_df.plot(
        kind="bar",
        stacked=True,
        figsize=figsize,
        color=color_list,
        width=0.85,
        edgecolor="none",
    )

    ax.set_title(title if title is not None else "Stacked capacities over years", pad=28)
    ax.set_xlabel("Year")
    ax.set_ylabel("Capacity [GW]")

    mean_demand = float(stats["mean"]) / 1e3
    max_demand = float(stats["max"]) / 1e3

    ax.axhline(mean_demand, linestyle="--", linewidth=1.2, alpha=0.9, label="Mean demand")
    ax.axhline(max_demand, linestyle="-.", linewidth=1.2, alpha=0.9, label="Max demand")

    ax.legend(frameon=False, ncol=6, loc="upper center", bbox_to_anchor=(0.5, 1.1))

    plt.xticks(rotation=45, ha="right")
    ax.set_xticklabels([f"{y%100:02d}/{(y+1)%100:02d}" for y in results_df.index])
    plt.tight_layout()

    if save_plots:
        plt.savefig(
            Figures_mdl_setup_path / "exp_stacked_generator_capacities.pdf",
            bbox_inches="tight",
        )

    plt.show()
    return ax


def plot_store_operation(
    networks_top: Dict[Any, Any],
    networks_bottom: Dict[Any, Any],
    title_top: str,
    title_bottom: str,
    interval: Optional[Tuple[pd.Timestamp, pd.Timestamp]] = None,
    carrier: str = "hydrogen storage",
    normalized: bool = True,
    same_axes: bool = True,
    colors: Optional[Dict[str, str]] = None,
    figure_size: Tuple[float, float] = (12, 6.5),
    alpha: float = 0.85,
    linewidth: float = 1.4,
    start_month: Optional[int] = None,
    plot_mean: bool = False,
):
    """
    Plot store SOC for two groups of networks (top and bottom).

    Respects operational year (e.g. Jun–May) by mapping months < start_month
    to the next dummy year.
    """

    dummy_year = 2000

    def fmt_label(lbl: Any) -> str:
        if isinstance(lbl, (int, np.integer)):
            y = int(lbl)
            return f"{str(y)[-2:]}/{str(y + 1)[-2:]}"
        return str(lbl)

    def extract_soc_and_cap(net):
        mask = net.stores.carrier.astype(str).str.lower() == carrier.lower()
        ids = net.stores.index[mask]
        soc = net.stores_t.e[ids].sum(axis=1)

        if "e_nom_opt" in net.stores.columns and net.stores["e_nom_opt"].notna().any():
            cap = float(net.stores.loc[ids, "e_nom_opt"].sum())
        else:
            cap = float(net.stores.loc[ids, "e_nom"].sum())

        return soc, cap

    def get_color(label_str: str, net) -> str:
        if colors is not None and label_str in colors:
            return colors[label_str]

        if colors is not None and carrier.lower() in colors:
            return colors[carrier.lower()]

        if "hydrogen" in net.carriers.index and "color" in net.carriers.columns:
            return net.carriers.loc["hydrogen", "color"]

        return "deepskyblue"

    def to_operational_dummy_index(idx: pd.DatetimeIndex, start_month: int) -> pd.DatetimeIndex:
        return pd.DatetimeIndex(
            [
                pd.Timestamp(
                    dummy_year + (ts.month < start_month),
                    ts.month,
                    ts.day,
                    ts.hour,
                    ts.minute,
                )
                for ts in idx
            ]
        )

    def prep_soc(net, soc, cap, start_month: int):
        if interval is not None:
            s, e = interval
            soc = soc.loc[s:e]

        if normalized:
            soc = soc / cap

        soc = soc.sort_index()
        soc.index = to_operational_dummy_index(soc.index, start_month)
        return soc

    if start_month is None:
        first_net = next(iter(networks_top.values()))
        first_soc, _ = extract_soc_and_cap(first_net)
        start_month = int(first_soc.index[0].month)

    month_locator = mdates.MonthLocator()
    month_formatter = mdates.DateFormatter("%b")

    x_start = pd.Timestamp(dummy_year, start_month, 1)
    x_end = pd.Timestamp(dummy_year + 1, start_month, 1) - pd.Timedelta(hours=1)

    def mean_series(series_list: List[pd.Series]) -> pd.Series:
        df = pd.concat(series_list, axis=1)
        return df.mean(axis=1)

    mean_color = "#0033A0"  # hardcoded deep blue

    if same_axes:
        fig, ax = plt.subplots(figsize=figure_size, constrained_layout=True)

        top_series = []
        bottom_series = []

        for lbl, net in networks_top.items():
            soc, cap = extract_soc_and_cap(net)
            soc = prep_soc(net, soc, cap, start_month)
            top_series.append(soc)

            label_str = fmt_label(lbl)
            ax.plot(
                soc.index,
                soc.values,
                color=get_color(label_str, net),
                linewidth=linewidth,
                alpha=alpha,
                linestyle="-",
                label=f"{title_top} {label_str}",
            )

        for lbl, net in networks_bottom.items():
            soc, cap = extract_soc_and_cap(net)
            soc = prep_soc(net, soc, cap, start_month)
            bottom_series.append(soc)

            label_str = fmt_label(lbl)
            ax.plot(
                soc.index,
                soc.values,
                color=get_color(label_str, net),
                linewidth=linewidth,
                alpha=alpha,
                linestyle="--",
                label=f"{title_bottom} {label_str}",
            )

        if plot_mean and len(top_series) > 0:
            m = mean_series(top_series)
            ax.plot(
                m.index,
                m.values,
                color=mean_color,
                linewidth=2.2,
                alpha=1.0,
                linestyle="-",
                label=f"{title_top} mean",
                zorder=5,
            )

        if plot_mean and len(bottom_series) > 0:
            m = mean_series(bottom_series)
            ax.plot(
                m.index,
                m.values,
                color=mean_color,
                linewidth=2.2,
                alpha=1.0,
                linestyle="--",
                label=f"{title_bottom} mean",
                zorder=5,
            )

        ax.set_xlim(x_start, x_end)
        ax.xaxis.set_major_locator(month_locator)
        ax.xaxis.set_major_formatter(month_formatter)

        ax.set_ylabel("SOC [p.u.]" if normalized else "SOC [MWh]")
        ax.set_xlabel("Month")

        if normalized:
            ax.set_ylim(0, 1.05)

        ax.grid(True, axis="y", alpha=0.3)
        ax.grid(False, axis="x")

        ax.set_title(f"Store SOC operation ({carrier})")

        ax.legend(
            bbox_to_anchor=(1.02, 1),
            loc="upper left",
            frameon=False,
            fontsize=LEGEND_FONTSIZE,
            ncol=2,
            handlelength=1.2,
            columnspacing=0.8,
            labelspacing=0.3,
            borderaxespad=0.3,
        )

        return fig, ax

    fig, axes = plt.subplots(2, 1, figsize=figure_size, sharex=True, constrained_layout=True)

    top_series = []
    bottom_series = []

    for lbl, net in networks_top.items():
        soc, cap = extract_soc_and_cap(net)
        soc = prep_soc(net, soc, cap, start_month)
        top_series.append(soc)

        label_str = fmt_label(lbl)
        axes[0].plot(
            soc.index,
            soc.values,
            color=get_color(label_str, net),
            linewidth=linewidth,
            alpha=alpha,
            label=label_str,
        )

    for lbl, net in networks_bottom.items():
        soc, cap = extract_soc_and_cap(net)
        soc = prep_soc(net, soc, cap, start_month)
        bottom_series.append(soc)

        label_str = fmt_label(lbl)
        axes[1].plot(
            soc.index,
            soc.values,
            color=get_color(label_str, net),
            linewidth=linewidth,
            alpha=alpha,
            label=label_str,
        )

    if plot_mean and len(top_series) > 0:
        m = mean_series(top_series)
        axes[0].plot(
            m.index,
            m.values,
            color=mean_color,
            linewidth=2.2,
            alpha=1.0,
            linestyle="-",
            label="mean",
            zorder=5,
        )

    if plot_mean and len(bottom_series) > 0:
        m = mean_series(bottom_series)
        axes[1].plot(
            m.index,
            m.values,
            color=mean_color,
            linewidth=2.2,
            alpha=1.0,
            linestyle="-",
            label="mean",
            zorder=5,
        )

    for ax in axes:
        ax.set_xlim(x_start, x_end)
        ax.xaxis.set_major_locator(month_locator)
        ax.xaxis.set_major_formatter(month_formatter)
        ax.grid(True, axis="y", alpha=0.3)
        ax.grid(False, axis="x")
        if normalized:
            ax.set_ylim(0, 1.05)
        ax.set_ylabel("SOC [p.u.]" if normalized else "SOC [MWh]")

    axes[0].set_title(title_top)
    axes[1].set_title(title_bottom)
    axes[1].set_xlabel("Month")

    axes[0].legend(
        bbox_to_anchor=(1.02, 1),
        loc="upper left",
        frameon=False,
        fontsize=LEGEND_FONTSIZE,
        ncol=2,
        title="Networks",
        title_fontsize=LEGEND_FONTSIZE,
        handlelength=1.2,
        columnspacing=0.8,
        labelspacing=0.3,
        borderaxespad=0.3,
    )
    axes[1].legend(
        bbox_to_anchor=(1.02, 1),
        loc="upper left",
        frameon=False,
        fontsize=LEGEND_FONTSIZE,
        ncol=2,
        title="Networks",
        title_fontsize=LEGEND_FONTSIZE,
        handlelength=1.2,
        columnspacing=0.8,
        labelspacing=0.3,
        borderaxespad=0.3,
    )

    plt.tight_layout()
    return fig, axes

def plot_store_operation_groups(
    groups: List[Dict[str, Any]],
    carrier: str = "hydrogen storage",
    interval: Optional[Tuple[pd.Timestamp, pd.Timestamp]] = None,
    normalized: bool = True,
    mode: str = "stacked",  # "stacked" or "overlay"
    figure_size: Tuple[float, float] = (12, 7),
    alpha: float = 0.25,
    linewidth: float = 1.1,
    plot_mean: bool = True,
    mean_alpha: float = 0.95,
    mean_linewidth: float = 2.2,
    start_month: Optional[int] = None,
    legend_yearly_label: str = "Yearly SOC (1979–2010)",
    legend_mean_label: str = "Mean",
    color_yearly_soc: str = "0.7",
    color_mean: str = "darkblue",
    plot_quantiles: bool = False,
    q_low: float = 0.35,
    q_high: float = 0.65,
    quantile_alpha: float = 0.9,
    quantile_linewidth: float = 1.8,
    color_quantiles: str = "blue",
    figure_title: Optional[str] = None,
    legend_loc: str = "upper",  # "upper" or "lower"
    legend_ncol: int = 3,
):
    """
    groups: list of dicts, each like:
        {"networks": {year: net, ...}, "title": "Rolling horizon"}
    """

    mode = mode.lower()
    if mode not in {"stacked", "overlay"}:
        raise ValueError("mode must be 'stacked' or 'overlay'")

    dummy_year = 2000

    def extract_soc_and_cap(net):
        mask = net.stores.carrier.astype(str).str.lower() == carrier.lower()
        ids = net.stores.index[mask]
        soc = net.stores_t.e[ids].sum(axis=1)
        if "e_nom_opt" in net.stores.columns and net.stores["e_nom_opt"].notna().any():
            cap = float(net.stores.loc[ids, "e_nom_opt"].sum())
        else:
            cap = float(net.stores.loc[ids, "e_nom"].sum())
        return soc, cap

    def to_operational_dummy_index(idx: pd.DatetimeIndex, start_month: int) -> pd.DatetimeIndex:
        return pd.DatetimeIndex(
            [
                pd.Timestamp(
                    dummy_year + (ts.month < start_month),
                    ts.month,
                    ts.day,
                    ts.hour,
                    ts.minute,
                )
                for ts in idx
            ]
        )

    def prep_soc(soc, cap, start_month: int):
        if interval is not None:
            s, e = interval
            soc = soc.loc[s:e]

        if normalized:
            soc = soc / cap

        soc = soc.sort_index()
        soc.index = to_operational_dummy_index(soc.index, start_month)
        return soc

    if start_month is None:
        first_net = next(iter(groups[0]["networks"].values()))
        first_soc, _ = extract_soc_and_cap(first_net)
        start_month = int(first_soc.index[0].month)

    month_locator = mdates.MonthLocator()
    month_formatter = mdates.DateFormatter("%b")
    x_start = pd.Timestamp(dummy_year, start_month, 1)
    x_end = pd.Timestamp(dummy_year + 1, start_month, 1) - pd.Timedelta(hours=1)

    def mean_and_quantiles(series_list: List[pd.Series]):
        df = pd.concat(series_list, axis=1)
        return df.mean(axis=1), df.quantile(q_low, axis=1), df.quantile(q_high, axis=1)

    if mode == "overlay":
        fig, ax = plt.subplots(figsize=figure_size, constrained_layout=True)

        for g in groups:
            nets = g["networks"]
            title = g.get("title", "")
            ls = g.get("ls", "-")
            a = g.get("panel_alpha", alpha)

            group_series = []

            for _, net in nets.items():
                soc, cap = extract_soc_and_cap(net)
                soc = prep_soc(soc, cap, start_month)
                group_series.append(soc)

                ax.plot(
                    soc.index,
                    soc.values,
                    color=color_yearly_soc,
                    linewidth=linewidth,
                    alpha=a,
                    linestyle=ls,
                )

            if (plot_mean or plot_quantiles) and len(group_series) > 0:
                m, ql, qh = mean_and_quantiles(group_series)

                if plot_quantiles:
                    ax.plot(
                        ql.index,
                        ql.values,
                        color=color_quantiles,
                        linewidth=quantile_linewidth,
                        alpha=quantile_alpha,
                        linestyle=ls,
                        zorder=4,
                    )
                    ax.plot(
                        qh.index,
                        qh.values,
                        color=color_quantiles,
                        linewidth=quantile_linewidth,
                        alpha=quantile_alpha,
                        linestyle=ls,
                        zorder=4,
                    )

                if plot_mean:
                    ax.plot(
                        m.index,
                        m.values,
                        color=color_mean,
                        linewidth=mean_linewidth,
                        alpha=mean_alpha,
                        linestyle=ls,
                        label=f"{title} {legend_mean_label}".strip(),
                        zorder=5,
                    )

        ax.set_xlim(x_start, x_end)
        ax.xaxis.set_major_locator(month_locator)
        ax.xaxis.set_major_formatter(month_formatter)

        ax.set_ylabel("SOC [p.u.]" if normalized else "SOC [MWh]")
        ax.set_xlabel("Month")
        if normalized:
            ax.set_ylim(0, 1.05)

        ax.grid(True, axis="y", alpha=0.3)
        ax.grid(False, axis="x")

        ax.set_title("Store SOC operation (overlay)")

        if plot_mean:
            ax.legend(
                bbox_to_anchor=(1.02, 1),
                loc="upper left",
                frameon=False,
                fontsize=LEGEND_FONTSIZE,
            )

        return fig, ax

    # stacked mode
    n = len(groups)
    fig, axes = plt.subplots(n, 1, figsize=figure_size, sharex=True, constrained_layout=True)
    if n == 1:
        axes = [axes]

    for ax, g in zip(axes, groups):
        nets = g["networks"]
        title = g.get("title", "")
        a = g.get("panel_alpha", alpha)

        panel_series = []

        for _, net in nets.items():
            soc, cap = extract_soc_and_cap(net)
            soc = prep_soc(soc, cap, start_month)
            panel_series.append(soc)

            ax.plot(
                soc.index,
                soc.values,
                color=color_yearly_soc,
                linewidth=linewidth,
                alpha=a,
                linestyle="-",
            )

        if (plot_mean or plot_quantiles) and len(panel_series) > 0:
            m, ql, qh = mean_and_quantiles(panel_series)

            if plot_quantiles:
                ax.plot(
                    ql.index,
                    ql.values,
                    color=color_quantiles,
                    linewidth=quantile_linewidth,
                    alpha=quantile_alpha,
                    linestyle="-",
                    zorder=4,
                )
                ax.plot(
                    qh.index,
                    qh.values,
                    color=color_quantiles,
                    linewidth=quantile_linewidth,
                    alpha=quantile_alpha,
                    linestyle="-",
                    zorder=4,
                )

            if plot_mean:
                ax.plot(
                    m.index,
                    m.values,
                    color=color_mean,
                    linewidth=mean_linewidth,
                    alpha=mean_alpha,
                    linestyle="-",
                    zorder=5,
                )

        ax.set_title(title, fontsize=SUBPLOT_TITLE_FONTSIZE)
        ax.grid(True, axis="y", alpha=0.3)
        ax.grid(False, axis="x")

        if normalized:
            ax.set_ylim(0, 1.05)

        ax.set_ylabel("SOC [p.u.]" if normalized else "SOC [MWh]")

    axes[-1].set_xlim(x_start, x_end)
    axes[-1].xaxis.set_major_locator(month_locator)
    axes[-1].xaxis.set_major_formatter(month_formatter)
    axes[-1].set_xlabel("Month")

    # One compact legend: yearly + quantiles + mean
    legend_handles = [
        mpl.lines.Line2D([], [], color=color_yearly_soc, linewidth=1.8, alpha=min(1.0, alpha + 0.2)),
    ]
    legend_labels = [legend_yearly_label]

    if plot_quantiles:
        legend_handles.append(
            mpl.lines.Line2D([], [], color=color_quantiles, linewidth=quantile_linewidth, alpha=quantile_alpha)
        )
        legend_labels.append(f"Quantiles {q_low*100:.0f} and {q_high*100:.0f}%")

    if plot_mean:
        legend_handles.append(
            mpl.lines.Line2D([], [], color=color_mean, linewidth=mean_linewidth, alpha=mean_alpha)
        )
        legend_labels.append(legend_mean_label)

    # Figure title
    if figure_title is not None:
        fig.suptitle(figure_title, fontsize=FIGURE_TITLE_FONTSIZE, y=0.96)
        fig.subplots_adjust(top=0.93)

    fig.legend(
        legend_handles,
        legend_labels,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.93),
        ncol=legend_ncol,
        frameon=False,
        fontsize=LEGEND_FONTSIZE,
        handlelength=1.8,
        columnspacing=1.2,
        labelspacing=0.6,
    )

    fig.tight_layout(rect=(0, 0, 1, 0.93))

    return fig, axes

############################################################
" ____________________ PLOT EVENTS ____________________ "
############################################################

# Plot all events across years. for multiple model setups
def plot_all_events(event_dicts: list,
                       labels: list,
                       colors: list,
                       standard_year: int = 2018,
                       start_month: int = 6,
                       figsize=(10,6),
                       title="Comparison of extreme event types",
                       offset_step: float = 0.25,
                       alpha: float = 0.8,
                       linewidth: float = 4, figure_size=default_figsize):
    """
    Plot multiple event types on a shifted model-year axis.
    Example: start_month=6 gives June→May.
    Events are mapped into this shifted year so cross-year events
    appear as single continuous bars.
    """
    fig, ax = plt.subplots(figsize=figure_size, constrained_layout=True)

    offsets = {lab: (i - (len(labels)-1)/2) * offset_step for i, lab in enumerate(labels)}

    all_years = sorted({y for events in event_dicts for y in events.keys()})

    # Build ordered month list for model-year axis
    # Example: start_month=6 → [6,7,8,9,10,11,12,1,2,3,4,5]
    month_order = [(start_month + i - 1) % 12 + 1 for i in range(12)]

    # Helper converts timestamp → model-year timestamp
    def map_to_model_year(ts):
        # Keep same day and hour but rearrange month position
        m = ts.month
        idx = month_order.index(m)        # new month index 0..11
        new_month = idx + 1               # mapped month 1..12
        return ts.replace(year=standard_year, month=new_month)

    for events, label, color in zip(event_dicts, labels, colors):
        dy = offsets[label]
        first_label = label

        for y, ev_list in sorted(events.items()):
            if not ev_list or isinstance(ev_list, int):
                continue

            y_pos = y + dy

            for ev in ev_list:
                s = ev.period.left
                e = ev.period.right

                # Map both timestamps into model-year
                s_m = map_to_model_year(s)
                e_m = map_to_model_year(e)

                ax.plot([s_m, e_m],
                        [y_pos, y_pos],
                        color=color,
                        linewidth=linewidth,
                        alpha=alpha,
                        solid_capstyle="butt",
                        label=first_label)
                first_label = None

    # Build x-axis limits based on mapped months
    x_start = pd.Timestamp(year=standard_year, month=1, day=1)
    x_end = pd.Timestamp(year=standard_year, month=12, day=31, hour=23)
    ax.set_xlim([x_start, x_end])

    year_labels = [f"{y % 100:02d}/{(y + 1) % 100:02d}" for y in all_years]

    # Set custom month ticks in model-year order
    xticks = [pd.Timestamp(standard_year, i+1, 1) for i in range(12)]
    ax.set_xticks(xticks)
    ax.set_xticklabels([pd.Timestamp(standard_year, m, 1).strftime("%b") for m in month_order])

    ax.set_xlabel(f"Demand year {standard_year}/{standard_year+1}")
    ax.set_ylabel("Weather year")
    ax.set_title(title)
    ax.set_yticks(all_years)
    ax.set_yticklabels(year_labels)
    ax.grid(alpha=0.3)
    ax.legend(loc="best")

    return fig, ax

# Need input from the function: calculate_net_load_potential
def plot_single_netload_extreme_event(
    netload: pd.Series,
    window_hours: int = 24 * 7,
    method: str = "rolling",   # "rolling" or "calendar"
    figsize: Tuple[int, int] = (14, 5),
    color_year: str = "lightgrey",
    color_worst: str = "red",
    title: Optional[str] = None,
    figure_size=default_figsize):
    """
    Find the worst window and plot the year with that window highlighted.

    Parameters
    - netload: hourly pd.Series indexed by pd.DatetimeIndex.
    - window_hours: length of moving window in hours (default 168).
    - method: "rolling" for moving window, "calendar" for calendar week (W).
    - figsize: figure size tuple.
    - color_year, color_worst: plot colors.
    - title: optional custom title.

    Returns (fig, ax, start_ts, end_ts, label).
    """
    netload = netload.sort_index()

    if method == "calendar":
        weekly = netload.resample("W").sum()
        end_ts = weekly.idxmax()
        start_ts = end_ts - pd.Timedelta(days=6)
        label = f"calendar week {end_ts.isocalendar().week} {end_ts.isocalendar().year}"
    else:
        rolling_sum = netload.rolling(window=window_hours, min_periods=window_hours).sum()
        end_ts = rolling_sum.idxmax()
        start_ts = end_ts - pd.Timedelta(hours=window_hours - 1)
        label = f"rolling {window_hours//24}-day event"

    worst = netload.loc[start_ts:end_ts]

    fig, ax = plt.subplots(figsize=figure_size, constrained_layout=True)

    # Plot full year first (use ax.plot to avoid pandas tick/locator side effects)
    ax.plot(netload.index, netload.values, color=color_year, label="Year net load", linewidth=0.8)

    # Plot worst window on top
    ax.plot(worst.index, worst.values, color=color_worst, label=f"Highest {label}", linewidth=1.5)

    ax.set_title(title or f"Net load - {label}")
    ax.set_ylabel("Net load [MW]")

    ax.legend(frameon=False)

    # Month ticks for full-year axis
    ax.set_xlim(netload.index.min(), netload.index.max())
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))

    ax.grid(True, axis="y", alpha=0.3)
    ax.grid(False, axis="x")

    fig.autofmt_xdate()

    return fig, ax, start_ts, end_ts, label

def plot_avg_event_duration_vs_threshold(
    df: pd.DataFrame,
    title: str = None,
    file_name: str = None,
    labels = None,
    figure_size=default_figsize):
    """
    Plot average event duration (days) vs threshold T for CE, PF, RH.
    """
    dfp = df.copy().sort_values("Threshold T")

    x = dfp["Threshold T"].to_numpy()

    fig, ax = plt.subplots(figsize=figure_size, constrained_layout=True)

    # cycle markers, linestyles and colors per iteration
    markers = ["o", "s", "^", "D", "v", "*", "x", "P"]
    #linestyles = ["-", "--", "-.", ":"]
    colors = plt.rcParams["axes.prop_cycle"].by_key().get("color", ["C0", "C1", "C2", "C3"])

    for i, col in enumerate(labels):
        if col in dfp.columns:
            m = markers[i % len(markers)]
            #ls = linestyles[i % len(linestyles)]
            #c = colors[i % len(colors)]
            ax.plot(
                x,
                dfp[col].to_numpy(),
                marker=m,
                #linestyle=ls,
                #color=c,
                linewidth=1.8,
                markersize=5,
                label=col,
            )

    ax.set_xlabel("Threshold T")
    ax.set_ylabel("Average event duration [days]")

    # Add padding on x-axis
    dx = 0.02
    ax.set_xlim(float(np.min(x) - dx), float(np.max(x) + dx))

    ax.set_ylim(bottom=0.0)

    ax.grid(True, which="major", linewidth=0.6, alpha=0.4)

    if title is not None:
        ax.set_title(title)

    ax.legend(frameon=False)

    if file_name is not None:
        plt.savefig(
            Figures_results_path / file_name,
            bbox_inches="tight",
        )

    return fig, ax

def plot_avg_yearly_events_vs_threshold(
    df: pd.DataFrame,
    title: str = None,
    file_name: str = None,
    labels = None,
    figure_size=default_figsize
):
    """
    Plot average yearly number of SP events vs threshold T for CE, PF, RH.
    """
    dfp = df.copy().sort_values("Threshold T")

    x = dfp["Threshold T"].to_numpy()

    fig, ax = plt.subplots(figsize=figure_size, constrained_layout=True)
    
    # cycle markers, linestyles and colors per iteration
    markers = ["o", "s", "^", "D", "v", "*", "x", "P"]
    #linestyles = ["-", "--", "-.", ":"]
    colors = plt.rcParams["axes.prop_cycle"].by_key().get("color", ["C0", "C1", "C2", "C3"])

    for i, col in enumerate(labels):
        if col in dfp.columns:
            m = markers[i % len(markers)]
            #ls = linestyles[i % len(linestyles)]
            #c = colors[i % len(colors)]
            ax.plot(
                x,
                dfp[col].to_numpy(),
                marker=m,
                #linestyle=ls,
                #color=c,
                linewidth=1.8,
                markersize=5,
                label=col,
            )
    ax.set_xlabel("Threshold T")
    ax.set_ylabel("Events per year")

    # Add padding on x-axis
    dx = 0.02
    ax.set_xlim(float(np.min(x) - dx), float(np.max(x) + dx))

    ax.set_ylim(bottom=0.0)

    ax.grid(True, which="major", linewidth=0.6, alpha=0.4)

    if title is not None:
        ax.set_title(title)

    ax.legend(frameon=False)

    if file_name is not None:
        plt.savefig(
        Figures_results_path / file_name,
        bbox_inches="tight",
    )


    return fig, ax


def plot_overview_heatmap_old(
    selected_networks: dict,
    plot_type: str,
    event_dicts: list,
    event_labels: list,
    event_colors: list,
    standard_year: int = 2018,
    start_month: int = 6,
    agg: str = "daily",                 # "hourly" or "daily"
    cmap: str = "Purples",
    vmin: float = 0.01,                 # for "0 -> white" via set_under
    vmax: float | None = None,
    title: str | None = None,
    show_heatmap: bool = True,
    heatmap_alpha: float = 0.7,
    event_linewidth: float = 3.0,
    event_alpha: float = 0.9,
    offset_step: float = 0.2,
    rowline_color: str = "0.75",
    rowline_width: float = 0.6,
    figure_size=default_figsize
):
    """
    Overview plot (June->May) for:
      plot_type="LS": load shedding from generators_t.p["load shedding"] [MW]
      plot_type="SP": marginal price from buses_t.marginal_price["electricity bus"] [€/MWh]
      plot_type="NL": residual load = calculate_net_load_potential(network, year).clip(lower=0) [MW]

    agg:
      "hourly": plot hourly values
      "daily": aggregate by day
        - LS: daily sum
        - SP: daily mean
        - NL: daily sum (residual load)

    show_heatmap:
      True  -> heatmap + colorbar + event overlays
      False -> event overlays only (same layout and styling)
    """
    plot_type = plot_type.upper()
    years = sorted(int(y) for y in selected_networks.keys())
    anchor = pd.Timestamp(standard_year, start_month, 1)

    # Y label to 98/99 instead of just 1998
    year_labels = [f"{y % 100:02d}/{(y + 1) % 100:02d}" for y in years]

    def to_model_day(ts: pd.Timestamp) -> int:
        same_year = pd.Timestamp(standard_year, ts.month, ts.day)
        if ts.month < start_month:
            same_year = same_year + pd.DateOffset(years=1)
        return int((same_year - anchor).days)

    def to_model_hour(ts: pd.Timestamp) -> int:
        return int(to_model_day(ts) * 24 + ts.hour)

    # -------------------------
    # Extract series by year
    # -------------------------
    series_by_year = {}

    for y in years:
        n = selected_networks[y]

        if plot_type == "LS":
            s = pd.Series(n.generators_t.p["load shedding"]).sort_index()
            series_by_year[y] = s

        elif plot_type == "SP":
            s = pd.Series(n.buses_t.marginal_price["electricity bus"]).sort_index()
            series_by_year[y] = s

        else:  # "NL"
            s = calculate_net_load_potential(n, weather_year=y)
            s = pd.Series(s).sort_index().clip(lower=0.0)
            series_by_year[y] = s

    # -------------------------
    # Aggregation rules
    # -------------------------
    if plot_type == "SP":
        daily_method = "mean"
        default_cbar = "Daily mean shadow price [€/MWh]"
        default_title = "Electricity price overview"
    elif plot_type == "LS":
        daily_method = "sum"
        default_cbar = "Load shedding [MW·h/day]" if agg == "daily" else "Load shedding [MW]"
        default_title = "Load shedding overview"
    else:  # "NL"
        daily_method = "sum"
        default_cbar = "Residual load [MW·h/day]" if agg == "daily" else "Residual load [MW]"
        default_title = "Residual load overview"

    if title is None:
        title = default_title

    # -------------------------
    # Build time grid
    # -------------------------
    if agg == "daily":
        n_bins = 366
        x_edges = np.arange(n_bins + 1)
        xticks, xlabels = [], []

        for k in range(12):
            m = (start_month + k - 1) % 12 + 1
            year_offset = 0 if m >= start_month else 1
            dt = pd.Timestamp(standard_year + year_offset, m, 1)
            xticks.append((dt - anchor).days)
            xlabels.append(dt.strftime("%b"))
    else:
        n_bins = 366 * 24
        x_edges = np.arange(n_bins + 1)
        xticks, xlabels = [], []

        for k in range(12):
            m = (start_month + k - 1) % 12 + 1
            year_offset = 0 if m >= start_month else 1
            dt = pd.Timestamp(standard_year + year_offset, m, 1)
            xticks.append(int((dt - anchor).days * 24))
            xlabels.append(dt.strftime("%b"))

    Z = np.full((len(years), n_bins), np.nan)

    if show_heatmap:
        for i, y in enumerate(years):
            s = series_by_year[y]

            if agg == "daily":
                if daily_method == "sum":
                    d = s.groupby(s.index.normalize()).sum()
                else:
                    d = s.groupby(s.index.normalize()).mean()

                m = pd.Series({to_model_day(t): v for t, v in d.items()})
                m = m[(m.index >= 0) & (m.index <= n_bins - 1)]
                Z[i, m.index.values] = m.values
            else:
                m = pd.Series({to_model_hour(t): v for t, v in s.items()})
                m = m[(m.index >= 0) & (m.index <= n_bins - 1)]
                Z[i, m.index.values] = m.values

        if vmax is None:
            vmax = float(np.nanmax(Z))

        norm = Normalize(vmin=vmin, vmax=vmax)
        cm = plt.get_cmap(cmap).copy()
        cm.set_under("white")

    # -------------------------
    # Plot
    # -------------------------
    fig, ax = plt.subplots(figsize=figure_size, constrained_layout=True)
    fig.subplots_adjust(right=0.82)

    if show_heatmap:
        mesh = ax.pcolormesh(
            x_edges,
            np.arange(len(years) + 1),
            Z,
            shading="auto",
            cmap=cm,
            norm=norm,
            alpha=heatmap_alpha,
        )

        cax = fig.add_axes([0.86, 0.07, 0.02, 0.45])
        cbar = fig.colorbar(mesh, cax=cax, extend="min")
        cbar.set_label(default_cbar)

    ax.set_yticks(np.arange(len(years)) + 0.5)
    ax.set_yticklabels(year_labels)
    ax.set_ylabel("Weather year")

    for yline in range(1, len(years)):
        ax.hlines(
            yline,
            xmin=x_edges[0],
            xmax=x_edges[-1],
            colors=rowline_color,
            linewidth=rowline_width,
            zorder=3,
        )

    ax.set_xticks(xticks)
    ax.set_xticklabels(xlabels)
    ax.set_xlabel(f"Demand year {standard_year}/{standard_year+1}")
    ax.set_title(title)

    offsets = {lab: (i - (len(event_labels) - 1) / 2) * offset_step
               for i, lab in enumerate(event_labels)}

    for events, lab, col in zip(event_dicts, event_labels, event_colors):
        first_label = lab
        dy = offsets[lab]

        for y, ev_list in sorted(events.items()):
            if not ev_list or isinstance(ev_list, int):
                continue

            row = years.index(int(y))
            y_pos = row + 0.5 + dy

            for ev in ev_list:
                if agg == "daily":
                    s0 = to_model_day(ev.period.left)
                    e0 = to_model_day(ev.period.right)
                else:
                    s0 = to_model_hour(ev.period.left)
                    e0 = to_model_hour(ev.period.right)

                ax.plot(
                    [s0, e0],
                    [y_pos, y_pos],
                    color=col,
                    linewidth=event_linewidth,
                    alpha=event_alpha,
                    solid_capstyle="butt",
                    label=first_label,
                    zorder=4,
                )
                first_label = None

    ax.legend(
        loc="upper left",
        bbox_to_anchor=(1.02, 1.0),
        borderaxespad=0.0,
        frameon=True,
    )

    return fig, ax


def plot_overview_heatmap(
    selected_networks: dict,
    plot_type: str,
    event_dicts: list,
    event_labels: list,
    event_colors: list,
    standard_year: int = 2018,
    start_month: int = 6,
    agg: str = "daily",
    cmap: str | None = None,
    vmin: float = 0.01,
    vmax: float | None = None,
    title: str | None = None,
    show_heatmap: bool = True,
    log_scale: bool = False,
    heatmap_alpha: float = 0.6,
    event_linewidth: float = 2.8,
    event_alpha: float = 0.9,
    offset_step: float = 0.2,
    rowline_color: str = "0.75",
    rowline_width: float = 0.6,
    event_edge: bool = True,
    event_edge_color: str = "black",
    event_edge_width: float = 0.7,
    figure_size=default_figsize,
    ax: plt.Axes | None = None,
    cax: plt.Axes | None = None,
    draw_legend: bool = True,
    draw_title: bool = True,
    end_month: int | None = None,   
):
    plot_type = plot_type.upper()
    years = sorted(int(y) for y in selected_networks.keys())
    year_labels = [f"{y % 100:02d}/{(y + 1) % 100:02d}" for y in years]

    if end_month is None:
        end_month = start_month - 1 if start_month != 1 else 12

    anchor, end_dt = _window_anchor_and_end(standard_year, start_month, end_month)

    if agg == "daily":
        n_bins = int((end_dt - anchor).days)
        x_edges = np.arange(n_bins + 1)
    else:
        n_bins = int((end_dt - anchor).days) * 24
        x_edges = np.arange(n_bins + 1)

    months = _months_in_window(start_month, end_month)
    xticks, xlabels = [], []
    for m in months:
        y_off = 0 if m >= start_month else 1
        dt = pd.Timestamp(standard_year + y_off, m, 1)
        if agg == "daily":
            xticks.append(int((dt - anchor).days))
        else:
            xticks.append(int((dt - anchor).days * 24))
        xlabels.append(dt.strftime("%b"))

    def to_model_day(ts: pd.Timestamp) -> int:
        same = pd.Timestamp(standard_year, ts.month, ts.day)
        if ts.month < start_month:
            same = same + pd.DateOffset(years=1)
        return int((same - anchor).days)

    def to_model_hour(ts: pd.Timestamp) -> int:
        return int(to_model_day(ts) * 24 + ts.hour)

    series_by_year = {}

    for y in years:
        n = selected_networks[y]

        if plot_type == "LS":
            s = pd.Series(n.generators_t.p["load shedding"]).sort_index()
        elif plot_type == "SP":
            s = pd.Series(n.buses_t.marginal_price["electricity bus"]).sort_index()
        else:
            s = calculate_net_load_potential(n, weather_year=y)
            s = pd.Series(s).sort_index().clip(lower=0.0)

        # FIX 1: filter per year and store back
        mask = _month_window_mask(s.index, start_month, end_month)
        s = s.loc[mask]
        series_by_year[y] = s

    if plot_type == "SP":
        daily_method = "mean"
        default_cbar = "Daily mean shadow price [€/MWh]"
        default_title = "Electricity price overview"
    elif plot_type == "LS":
        daily_method = "sum"
        default_cbar = "Load shedding [GWh/day]" if agg == "daily" else "Load shedding [MW]"
        default_title = "Load shedding overview"
    else:
        daily_method = "sum"
        default_cbar = "Net load [GWh/day]" if agg == "daily" else "Net load [MW]"
        default_title = "Net load overview"

    if draw_title and title is None:
        title = default_title

    Z = np.full((len(years), n_bins), np.nan)

    if show_heatmap:
        for i, y in enumerate(years):
            s = series_by_year[y]
            if s.empty:
                continue

            if agg == "daily":
                if daily_method == "sum":
                    d = s.groupby(s.index.normalize()).sum()
                    if plot_type in {"LS", "NL"}:
                        d = d / 1000.0
                else:
                    d = s.groupby(s.index.normalize()).mean()

                m = pd.Series({to_model_day(t): v for t, v in d.items()})
            else:
                m = pd.Series({to_model_hour(t): v for t, v in s.items()})

            m = m[(m.index >= 0) & (m.index <= n_bins - 1)]
            Z[i, m.index.values] = m.values

        if vmax is None and np.isfinite(Z).any():
            vmax = float(np.nanmax(Z))
        if cmap is None:
            cmaps={"NL": "Blues", "LS": "Greens", "SP": "Oranges"}
            cm = plt.get_cmap(cmaps[plot_type]).copy()
            cm.set_under("white")
        else:
            cm = plt.get_cmap(cmap).copy()
            cm.set_under("white")
        norm = LogNorm(vmin=vmin, vmax=vmax) if log_scale else Normalize(vmin=vmin, vmax=vmax)

    if ax is None:
        fig, ax = plt.subplots(figsize=figure_size, constrained_layout=False)
        fig.subplots_adjust(right=0.82)
    else:
        fig = ax.figure

    if show_heatmap:
        mesh = ax.pcolormesh(
            x_edges,
            np.arange(len(years) + 1),
            Z,
            shading="auto",
            cmap=cm,
            norm=norm,
            alpha=heatmap_alpha,
        )

        if cax is None:
            cbar_width = 0.65
            cbar_height = 0.018
            cbar_y_pad = 0.07

            pos = ax.get_position()
            cax = fig.add_axes([
                pos.x0 + (1 - cbar_width) * pos.width / 2,
                pos.y0 - cbar_y_pad,
                pos.width * cbar_width,
                cbar_height,
            ])
        else:
            cbar = fig.colorbar(mesh, cax=cax, orientation="horizontal")

        cbar = fig.colorbar(mesh, cax=cax, orientation="horizontal")
        cbar.set_label(default_cbar, fontsize=10)
        cbar.ax.tick_params(labelsize=9)

    ax.set_yticks(np.arange(len(years)) + 0.5)
    ax.set_yticklabels(year_labels)
    ax.set_ylabel("Weather year")
    # FIX: enforce identical top/bottom spacing whether heatmap is on or off
    ax.set_ylim(0, len(years))
    ax.margins(y=0)

    for yline in range(1, len(years)):
        ax.hlines(
            yline,
            xmin=x_edges[0],
            xmax=x_edges[-1],
            colors=rowline_color,
            linewidth=rowline_width,
            zorder=3,
        )

    ax.set_xticks(xticks)
    ax.set_xticklabels(xlabels)

    ax.set_xlim(x_edges[0], x_edges[-1])

    #ax.set_xlabel(f"Demand year {standard_year}/{standard_year+1}")
    ax.set_xlabel("Months")

    if draw_title:
        ax.set_title(title)

    clean_labels = [lab.replace("Events", "").replace("events", "").strip() for lab in event_labels]
    offsets = {lab: ((len(clean_labels) - 1) / 2 - i) * offset_step for i, lab in enumerate(clean_labels)}

    legend_handles_by_label = {}

    for events, lab_raw, lab_clean, col in zip(event_dicts, event_labels, clean_labels, event_colors):
        dy = offsets[lab_clean]

        for y, ev_list in sorted(events.items()):
            if not ev_list or isinstance(ev_list, int):
                continue
            if int(y) not in years:
                continue

            row = years.index(int(y))
            y_pos = row + 0.5 + dy

            for ev in ev_list:
                if agg == "daily":
                    s0 = to_model_day(ev.period.left)
                    e0 = to_model_day(ev.period.right)
                else:
                    s0 = to_model_hour(ev.period.left)
                    e0 = to_model_hour(ev.period.right)

                # FIX 2: clip event lines to window
                if e0 < 0 or s0 > n_bins - 1:
                    continue
                s0 = max(0, s0)
                e0 = min(n_bins - 1, e0)

                if event_edge:
                    ax.plot(
                        [s0, e0],
                        [y_pos, y_pos],
                        color=event_edge_color,
                        linewidth=event_linewidth + event_edge_width,
                        alpha=1.0,
                        solid_capstyle="butt",
                        zorder=4,
                    )

                h = ax.plot(
                    [s0, e0],
                    [y_pos, y_pos],
                    color=col,
                    linewidth=event_linewidth,
                    alpha=event_alpha,
                    solid_capstyle="butt",
                    zorder=5,
                )[0]

                if lab_clean not in legend_handles_by_label:
                    legend_handles_by_label[lab_clean] = h

    if draw_legend:
        labels_sorted = sorted(legend_handles_by_label.keys(), key=lambda s: offsets[s], reverse=True)
        handles_sorted = [legend_handles_by_label[s] for s in labels_sorted]

        ax.legend(
            handles_sorted,
            labels_sorted,
            title="Model + Event types",
            loc="upper left",
            bbox_to_anchor=(1.02, 1.0),
            borderaxespad=0.0,
            frameon=True,
        )

    return fig, ax

def plot_overview_heatmap_combined(
    selected_networks: dict,
    event_dicts: list,
    event_labels: list,
    event_colors: list,
    standard_year: int = 2018,
    start_month: int = 6,
    agg: str = "daily",
    figure_size: tuple = (14, 10),
    hspace: float = 0.25,
    cbar_height: float = 0.08,
    cmaps: dict | None = None,
    cbar_width_ratios: tuple = (0.2, 0.6, 0.2),
    suptitle: str | None = None,
    suptitle_y: float = 0.98,
    legend_y: float = 0.94,
    end_month: int | None = None,
):
    from matplotlib.gridspec import GridSpec

    if cmaps is None:
        cmaps = {"NL": "Purples", "LS": "Oranges", "SP": "Greens"}

    fig = plt.figure(figsize=figure_size, constrained_layout=False)

    if suptitle is not None:
        fig.suptitle(suptitle, fontsize=14, y=suptitle_y)

    fig.subplots_adjust(top=0.90)

    gs = GridSpec(
        nrows=4,
        ncols=3,
        height_ratios=[1.0, 1.0, 1.0, cbar_height],
        hspace=hspace,
        wspace=0.37,
        figure=fig,
    )

    ax_sp = fig.add_subplot(gs[0, :])
    ax_ls = fig.add_subplot(gs[1, :])
    ax_nl = fig.add_subplot(gs[2, :])

    cax_sp = fig.add_subplot(gs[3, 0])
    cax_ls = fig.add_subplot(gs[3, 1])
    cax_nl = fig.add_subplot(gs[3, 2])

    
    plot_overview_heatmap(
        selected_networks=selected_networks,
        plot_type="SP",
        event_dicts=event_dicts,
        event_labels=event_labels,
        event_colors=event_colors,
        standard_year=standard_year,
        start_month=start_month,
        end_month=end_month,
        heatmap_alpha=0.55,
        agg=agg,
        cmap=cmaps["SP"],
        ax=ax_sp,
        cax=cax_sp,
        draw_legend=True,
        draw_title=False,
    )

    plot_overview_heatmap(
        selected_networks=selected_networks,
        plot_type="NL",
        event_dicts=event_dicts,
        event_labels=event_labels,
        event_colors=event_colors,
        standard_year=standard_year,
        start_month=start_month,
        end_month=end_month,
        heatmap_alpha=0.7,
        agg=agg,
        cmap=cmaps["NL"],
        ax=ax_nl,
        cax=cax_nl,
        draw_legend=False,
        draw_title=False,
    )

    plot_overview_heatmap(
        selected_networks=selected_networks,
        plot_type="LS",
        event_dicts=event_dicts,
        event_labels=event_labels,
        event_colors=event_colors,
        standard_year=standard_year,
        start_month=start_month,
        end_month=end_month,
        heatmap_alpha=1,
        agg=agg,
        cmap=cmaps["LS"],
        ax=ax_ls,
        cax=cax_ls,
        draw_legend=False,
        draw_title=False,
    )

    # keep xlabel only on bottom axis
    ax_sp.set_xlabel("")
    ax_ls.set_xlabel("")

    leg = ax_sp.get_legend()
    handles = leg.legend_handles
    labels = [t.get_text() for t in leg.get_texts()]
    leg.remove()

    if end_month is not None:
        # tighten space between title and plots
        fig.subplots_adjust(top=0.94)

        fig.legend(
            handles,
            labels,
            loc="upper left",
            bbox_to_anchor=(0.93, 0.945),
            ncol=1,
            frameon=True,
            # title_fontsize=9,
            # fontsize=8,
            title="Model & Event types",
            borderaxespad=0.0,
        )
    else:
        fig.legend(
            handles,
            labels,
            loc="upper center",
            bbox_to_anchor=(0.5, legend_y),
            ncol=3,
            frameon=True,
            title_fontsize=9,
            fontsize=8,
            title="Model & Event types",
        )

    return fig, (ax_sp, ax_ls, ax_nl)


def plot_overview_heatmap_dual(
    selected_networks: dict,
    plot_type_top: str,
    plot_type_bottom: str,
    event_dicts: list,
    event_labels: list,
    event_colors: list,
    standard_year: int = 2018,
    start_month: int = 6,
    agg: str = "daily",
    cmap_top: str = "Purples",
    cmap_bottom: str = "Blues",
    vmin_top: float = 0.01,
    vmax_top: float | None = None,
    vmin_bottom: float = 0.01,
    vmax_bottom: float | None = None,
    title: str | None = None,
    show_heatmap: bool = True,
    log_scale_top: bool = False,
    log_scale_bottom: bool = False,
    heatmap_alpha_top: float = 0.7,
    heatmap_alpha_bottom: float = 0.7,
    event_linewidth: float = 3.0,
    event_alpha: float = 0.9,
    offset_step: float = 0.2,
    rowline_color: str = "0.75",
    rowline_width: float = 0.6,
    subrow_line_color: str = "0.88",
    subrow_line_width: float = 0.5,
    event_edge: bool = True,
    event_edge_color: str = "black",
    event_edge_width: float = 1.2,
    figure_size=default_figsize,
    cbar_top_label: str | None = None,
    cbar_bottom_label: str | None = None,
):
    plot_type_top = plot_type_top.upper()
    plot_type_bottom = plot_type_bottom.upper()

    years = sorted(int(y) for y in selected_networks.keys())
    anchor = pd.Timestamp(standard_year, start_month, 1)

    year_labels = [f"{y % 100:02d}/{(y + 1) % 100:02d}" for y in years]

    def to_model_day(ts: pd.Timestamp) -> int:
        same_year = pd.Timestamp(standard_year, ts.month, ts.day)
        if ts.month < start_month:
            same_year = same_year + pd.DateOffset(years=1)
        return int((same_year - anchor).days)

    def to_model_hour(ts: pd.Timestamp) -> int:
        return int(to_model_day(ts) * 24 + ts.hour)

    def extract_series(plot_type: str) -> dict[int, pd.Series]:
        out = {}
        for y in years:
            n = selected_networks[y]
            if plot_type == "LS":
                out[y] = pd.Series(n.generators_t.p["load shedding"]).sort_index()
            elif plot_type == "SP":
                out[y] = pd.Series(n.buses_t.marginal_price["electricity bus"]).sort_index()
            else:  # "NL"
                s = calculate_net_load_potential(n, weather_year=y)
                out[y] = pd.Series(s).sort_index().clip(lower=0.0)
        return out

    def label_and_daily_method(plot_type: str) -> tuple[str, str]:
        if plot_type == "SP":
            return "mean", "Electricity price [€/MWh]" if agg == "daily" else "Electricity price [€/MWh]"
        if plot_type == "LS":
            return "sum", "Load shedding [GWh/day]" if agg == "daily" else "Load shedding [MW]"
        return "sum", "Net load [GWh/day]" if agg == "daily" else "Net load [MW]"

    daily_method_top, default_top_label = label_and_daily_method(plot_type_top)
    daily_method_bottom, default_bottom_label = label_and_daily_method(plot_type_bottom)

    if cbar_top_label is None:
        cbar_top_label = default_top_label
    if cbar_bottom_label is None:
        cbar_bottom_label = default_bottom_label

    if title is None:
        title = f"{plot_type_top} (top) + {plot_type_bottom} (bottom) overview"

    if agg == "daily":
        n_bins = 366
        x_edges = np.arange(n_bins + 1)
        xticks, xlabels = [], []
        for k in range(12):
            m = (start_month + k - 1) % 12 + 1
            year_offset = 0 if m >= start_month else 1
            dt = pd.Timestamp(standard_year + year_offset, m, 1)
            xticks.append((dt - anchor).days)
            xlabels.append(dt.strftime("%b"))
    else:
        n_bins = 366 * 24
        x_edges = np.arange(n_bins + 1)
        xticks, xlabels = [], []
        for k in range(12):
            m = (start_month + k - 1) % 12 + 1
            year_offset = 0 if m >= start_month else 1
            dt = pd.Timestamp(standard_year + year_offset, m, 1)
            xticks.append(int((dt - anchor).days * 24))
            xlabels.append(dt.strftime("%b"))

    series_top = extract_series(plot_type_top)
    series_bottom = extract_series(plot_type_bottom)

    ny = 2 * len(years)
    y_edges = np.arange(ny + 1)

    Z_top = np.full((ny, n_bins), np.nan)
    Z_bottom = np.full((ny, n_bins), np.nan)

    if show_heatmap:
        for i, y in enumerate(years):
            # bottom half-row -> index 2*i
            # top half-row    -> index 2*i + 1
            row_bottom = 2 * i
            row_top = 2 * i + 1

            s = series_top[y]
            if agg == "daily":
                if daily_method_top == "sum":
                    d = s.groupby(s.index.normalize()).sum()
                    if plot_type_top in {"LS", "NL"}:
                        d = d / 1000.0
                else:
                    d = s.groupby(s.index.normalize()).mean()
                m = pd.Series({to_model_day(t): v for t, v in d.items()})
                m = m[(m.index >= 0) & (m.index <= n_bins - 1)]
                Z_top[row_top, m.index.values] = m.values
            else:
                m = pd.Series({to_model_hour(t): v for t, v in s.items()})
                m = m[(m.index >= 0) & (m.index <= n_bins - 1)]
                Z_top[row_top, m.index.values] = m.values

            s = series_bottom[y]
            if agg == "daily":
                if daily_method_bottom == "sum":
                    d = s.groupby(s.index.normalize()).sum()
                    if plot_type_bottom in {"LS", "NL"}:
                        d = d / 1000.0
                else:
                    d = s.groupby(s.index.normalize()).mean()
                m = pd.Series({to_model_day(t): v for t, v in d.items()})
                m = m[(m.index >= 0) & (m.index <= n_bins - 1)]
                Z_bottom[row_bottom, m.index.values] = m.values
            else:
                m = pd.Series({to_model_hour(t): v for t, v in s.items()})
                m = m[(m.index >= 0) & (m.index <= n_bins - 1)]
                Z_bottom[row_bottom, m.index.values] = m.values

        if vmax_top is None:
            vmax_top = float(np.nanmax(Z_top))
        if vmax_bottom is None:
            vmax_bottom = float(np.nanmax(Z_bottom))

        cm_top = plt.get_cmap(cmap_top).copy()
        cm_bottom = plt.get_cmap(cmap_bottom).copy()

        cm_top.set_under("white")
        cm_bottom.set_under("white")

        cm_top.set_bad("white")
        cm_bottom.set_bad("white")

        if log_scale_top:
            norm_top = LogNorm(vmin=vmin_top, vmax=vmax_top)
        else:
            norm_top = Normalize(vmin=vmin_top, vmax=vmax_top)

        if log_scale_bottom:
            norm_bottom = LogNorm(vmin=vmin_bottom, vmax=vmax_bottom)
        else:
            norm_bottom = Normalize(vmin=vmin_bottom, vmax=vmax_bottom)

    fig, ax = plt.subplots(figsize=figure_size, constrained_layout=False)
    fig.subplots_adjust(right=0.82, bottom=0.20)

    mesh_top = None
    mesh_bottom = None

    if show_heatmap:
        mesh_bottom = ax.pcolormesh(
            x_edges,
            y_edges,
            Z_bottom,
            shading="auto",
            cmap=cm_bottom,
            norm=norm_bottom,
            alpha=heatmap_alpha_bottom,
            zorder=1,
        )

        mesh_top = ax.pcolormesh(
            x_edges,
            y_edges,
            Z_top,
            shading="auto",
            cmap=cm_top,
            norm=norm_top,
            alpha=heatmap_alpha_top,
            zorder=2,
        )

        # two stacked horizontal colorbars (bottom)
        cax_bottom = fig.add_axes([0.26, 0.065, 0.42, 0.015])
        cbar_bottom = fig.colorbar(mesh_bottom, cax=cax_bottom, orientation="horizontal")
        cbar_bottom.set_label(cbar_bottom_label, fontsize=9)
        cbar_bottom.ax.tick_params(labelsize=8)

        cax_top = fig.add_axes([0.26, 0.13, 0.42, 0.015])
        cbar_top = fig.colorbar(mesh_top, cax=cax_top, orientation="horizontal")
        cbar_top.set_label(cbar_top_label, fontsize=9)
        cbar_top.ax.tick_params(labelsize=8)

    # y ticks centered between the two half-rows
    ytick_pos = [2 * i + 1 for i in range(len(years))]
    ax.set_yticks(ytick_pos)
    ax.set_yticklabels(year_labels)
    ax.set_ylabel("Weather year")

    # separators between years (between pairs)
    for i in range(1, len(years)):
        ax.hlines(
            2 * i,
            xmin=x_edges[0],
            xmax=x_edges[-1],
            colors=rowline_color,
            linewidth=rowline_width,
            zorder=3,
        )

    # optional separator within each year (between bottom and top sub-row)
    for i in range(len(years)):
        ax.hlines(
            2 * i + 1,
            xmin=x_edges[0],
            xmax=x_edges[-1],
            colors=subrow_line_color,
            linewidth=subrow_line_width,
            zorder=3,
        )

    ax.set_xticks(xticks)
    ax.set_xticklabels(xlabels)
    ax.set_xlabel(f"Demand year {standard_year}/{standard_year+1}")
    ax.set_title(title)

    clean_labels = [lab.replace("Events", "").replace("events", "").strip() for lab in event_labels]

    offsets = {lab: (i - (len(clean_labels) - 1) / 2) * offset_step
               for i, lab in enumerate(clean_labels)}

    legend_handles_by_label = {}

    for events, lab_clean, col in zip(event_dicts, clean_labels, event_colors):
        dy = offsets[lab_clean]

        for y, ev_list in sorted(events.items()):
            if not ev_list or isinstance(ev_list, int):
                continue

            row = years.index(int(y))
            y_center = 2 * row + 1
            y_pos = y_center + dy

            for ev in ev_list:
                if agg == "daily":
                    s0 = to_model_day(ev.period.left)
                    e0 = to_model_day(ev.period.right)
                else:
                    s0 = to_model_hour(ev.period.left)
                    e0 = to_model_hour(ev.period.right)

                if event_edge:
                    ax.plot(
                        [s0, e0],
                        [y_pos, y_pos],
                        color=event_edge_color,
                        linewidth=event_linewidth + event_edge_width,
                        alpha=1.0,
                        solid_capstyle="butt",
                        zorder=8,
                    )

                h = ax.plot(
                    [s0, e0],
                    [y_pos, y_pos],
                    color=col,
                    linewidth=event_linewidth,
                    alpha=event_alpha,
                    solid_capstyle="butt",
                    zorder=9,
                )[0]

                if lab_clean not in legend_handles_by_label:
                    legend_handles_by_label[lab_clean] = h

    labels_for_legend = list(legend_handles_by_label.keys())
    labels_for_legend_sorted = sorted(
        labels_for_legend,
        key=lambda s: offsets[s],
        reverse=True,
    )
    handles_sorted = [legend_handles_by_label[s] for s in labels_for_legend_sorted]

    ax.legend(
        handles_sorted,
        labels_for_legend_sorted,
        title="Model + Event types",
        loc="upper left",
        bbox_to_anchor=(1.02, 1.0),
        borderaxespad=0.0,
        frameon=True,
    )

    return fig, ax


def plot_overlap_matrix_heatmap(
    M: pd.DataFrame,
    title: str,
    figure_size: Tuple[float, float] = (10, 8),
    cmap: str = "Oranges",
    highlight_from: float = 0.6,
    annotation_fmt: str = ".2f",
    rotate_xticks: int = 45,
    savepath: Optional[str] = None
) -> Tuple[plt.Figure, plt.Axes]:
    """
    Heatmap for asymmetric event overlap matrix.
    Diagonal (self-overlap) is removed (white, no annotation).
    """

    A = M.to_numpy().copy()

    diag_mask = np.eye(A.shape[0], dtype=bool)
    low_mask = A < highlight_from

    A_plot = A.copy()
    A_plot[low_mask] = np.nan
    A_plot[diag_mask] = np.nan

    fig, ax = plt.subplots(figsize=figure_size)

    cm = mpl.colormaps.get_cmap(cmap).copy()
    cm.set_bad("white")

    norm = Normalize(vmin=0.0, vmax=1.0, clip=False)

    im = ax.imshow(
        A_plot,
        cmap=cm,
        norm=norm,
        interpolation="nearest",
        aspect="auto"
    )

    ax.set_title(title, fontsize=FIGURE_TITLE_FONTSIZE)
    ax.set_xticks(np.arange(M.shape[1]))
    ax.set_yticks(np.arange(M.shape[0]))
    ax.set_xticklabels(M.columns)
    ax.set_yticklabels(M.index)

    ax.tick_params(top=True, bottom=False, labeltop=True, labelbottom=False)
    plt.setp(
        ax.get_xticklabels(),
        rotation=rotate_xticks,
        ha="left",
        rotation_mode="anchor"
    )

    cbar = fig.colorbar(im, ax=ax, fraction=0.036, pad=0.037)
    cbar.set_label("Probability share", labelpad=15)
    cbar.set_ticks([0, 0.2, 0.4, 0.6, 0.8, 1.0])
    cbar.ax.set_yticklabels(['0', '0.2', '0.4', '0.6', '0.8', '1.0'])

    # annotate only non-diagonal, non-masked values
    for i in range(M.shape[0]):
        for j in range(M.shape[1]):
            if diag_mask[i, j]:
                continue
            v = M.iat[i, j]
            if v >= highlight_from:
                ax.text(j, i, format(v, annotation_fmt), ha="center", va="center")

    # grid between cells
    ax.set_xticks(np.arange(M.shape[1] + 1) - 0.5, minor=True)
    ax.set_yticks(np.arange(M.shape[0] + 1) - 0.5, minor=True)
    ax.grid(which="minor", linestyle="-", linewidth=0.5)
    ax.tick_params(which="minor", bottom=False, left=False)

    # KEEP outer frame
    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_linewidth(0.8)

    fig.tight_layout()

    if savepath is not None:
        fig.savefig(savepath, bbox_inches="tight")

    return fig, ax


def plot_overlap_matrix_heatmap_old(
    M: pd.DataFrame,
    title: str,
    figure_size: Tuple[float, float] = (10, 8),
    cmap: str = "Oranges",
    highlight_from: float = 0.6,
    annotation_fmt: str = ".2f",
    rotate_xticks: int = 45,
    savepath: Optional[str] = None
) -> Tuple[plt.Figure, plt.Axes]:
    """
    Heatmap for asymmetric event overlap matrix.
    Diagonal (self-overlap) is removed (white, no annotation).
    """

    A = M.to_numpy().copy()

    diag_mask = np.eye(A.shape[0], dtype=bool)
    low_mask = A < highlight_from

    A_plot = A.copy()
    A_plot[low_mask] = np.nan
    A_plot[diag_mask] = np.nan

    fig, ax = plt.subplots(figsize=figure_size)

    cm = mpl.colormaps.get_cmap(cmap).copy()
    cm.set_bad("white")

    norm = Normalize(vmin=highlight_from, vmax=1.0, clip=False)

    im = ax.imshow(
        A_plot,
        cmap=cm,
        norm=norm,
        interpolation="nearest",
        aspect="auto"
    )

    ax.set_title(title)
    ax.set_xticks(np.arange(M.shape[1]))
    ax.set_yticks(np.arange(M.shape[0]))
    ax.set_xticklabels(M.columns)
    ax.set_yticklabels(M.index)

    ax.tick_params(top=True, bottom=False, labeltop=True, labelbottom=False)
    plt.setp(
        ax.get_xticklabels(),
        rotation=rotate_xticks,
        ha="left",
        rotation_mode="anchor"
    )

    cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cbar.set_label("Probability share")

    # annotate only non-diagonal, non-masked values
    for i in range(M.shape[0]):
        for j in range(M.shape[1]):
            if diag_mask[i, j]:
                continue
            v = M.iat[i, j]
            if v >= highlight_from:
                ax.text(j, i, format(v, annotation_fmt), ha="center", va="center")

    # grid between cells
    ax.set_xticks(np.arange(M.shape[1] + 1) - 0.5, minor=True)
    ax.set_yticks(np.arange(M.shape[0] + 1) - 0.5, minor=True)
    ax.grid(which="minor", linestyle="-", linewidth=0.5)
    ax.tick_params(which="minor", bottom=False, left=False)

    # KEEP outer frame
    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_linewidth(0.8)

    fig.tight_layout()

    if savepath is not None:
        fig.savefig(savepath, bbox_inches="tight")

    return fig, ax


# helper plot functions: 
def _month_window_mask(idx: pd.DatetimeIndex, start_month: int, end_month: int) -> np.ndarray:
    m = idx.month
    if start_month <= end_month:
        return (m >= start_month) & (m <= end_month)
    return (m >= start_month) | (m <= end_month)


def _window_anchor_and_end(standard_year: int, start_month: int, end_month: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    """
    Anchor is standard_year-start_month-01.
    End is first day of month after end_month in the shifted model-year.
    """
    anchor = pd.Timestamp(standard_year, start_month, 1)
    end_year = standard_year if end_month >= start_month else standard_year + 1
    end_dt = pd.Timestamp(end_year, end_month, 1) + pd.offsets.MonthBegin(1)
    return anchor, end_dt


def _months_in_window(start_month: int, end_month: int) -> List[int]:
    if start_month <= end_month:
        return list(range(start_month, end_month + 1))
    return list(range(start_month, 13)) + list(range(1, end_month + 1))


def _last_day_of_month(year: int, month: int) -> int:
    first = pd.Timestamp(year, month, 1)
    nxt = first + pd.offsets.MonthBegin(1)
    return (nxt - pd.Timedelta(days=1)).day


def plot_dispatch_elec_h2_w_PWL(
    network,
    save_plots=False,
    start_hour=0,
    duration_hours=7*24,
    interval=None,
    title="Dispatch",
    figure_size=default_figsize,
    legend_outside: bool = False,
):
    """
    Plot dispatch for electricity bus including H2 conversion and load.
    Colors are automatically read from network.carriers.color.
    """

    def _slice_series(series, start_hour, duration_hours, interval):
        if interval is not None:
            s, e = interval
            return series.loc[s:e]
        else:
            return series.iloc[start_hour:start_hour + duration_hours]

    carrier_colors = network.carriers.color

    elec_buses = network.buses.index[
        network.buses.carrier.astype(str).str.lower().isin(["electricity", "ac"])
    ]
    if len(elec_buses) == 0:
        raise ValueError("No electricity bus found")
    elec_bus = elec_buses[0]

    fig, ax = plt.subplots(figsize=figure_size)

    # --- Generators ---
    for gen in network.generators.index[network.generators.bus == elec_bus]:
        p_nom_opt = network.generators.p_nom_opt[gen]
        if p_nom_opt <= 10:
            continue
        series = network.generators_t.p[gen]
        series_slice = _slice_series(series, start_hour, duration_hours, interval)
        color = carrier_colors[network.generators.loc[gen, "carrier"]]
        ax.plot(series_slice.index, series_slice.values, label=gen, color=color)

    # --- Fuel cell injections ---
    fc_mask = (network.links.carrier.str.lower() == "fuel cell") & (network.links.bus1 == elec_bus)
    for link in network.links.index[fc_mask]:
        s = network.links_t.p1[link]
        s_slice = _slice_series(s, start_hour, duration_hours, interval)
        color = carrier_colors[network.links.loc[link, "carrier"]]
        ax.plot(s_slice.index, -s_slice.values,
                label=f"{link} (discharge)", color=color, linestyle="--")

    # --- Electrolysis draw ---
    ely_mask = (network.links.carrier.str.lower() == "electrolysis") & (network.links.bus0 == elec_bus)
    for link in network.links.index[ely_mask]:
        s = network.links_t.p0[link]
        s_slice = _slice_series(s, start_hour, duration_hours, interval)
        color = carrier_colors[network.links.loc[link, "carrier"]]
        ax.plot(s_slice.index, -s_slice.values,
                label=f"{link} (charge)", color=color, linestyle=":")

    # --- Load ---
    load_series = network.loads_t.p_set["load"]
    load_slice = _slice_series(load_series, start_hour, duration_hours, interval)
    color = carrier_colors["load shedding"]
    ax.plot(load_slice.index, load_slice.values, label="load", color=color, linestyle="-.")

    ax.set_title(title, y=1.07)
    ax.set_ylabel("Power [MWh per snapshot]")
    ax.grid(True, alpha=0.25)
    ax.tick_params(axis="x", rotation=45)

    if legend_outside:
        ax.legend(
            loc="upper left",
            bbox_to_anchor=(1.02, 0.97),
            frameon=True,
        )
        fig.subplots_adjust(right=0.8)
    else:
        ax.legend()

    if save_plots:
        s, e = interval if interval else (start_hour, start_hour + duration_hours)
        fname = f"./Plots/dispatch_{s}_to_{e}.png"
        fig.savefig(fname, dpi=300, bbox_inches="tight")

    plt.show()

def plot_soc_and_events_single_year(
    year: int,
    networks: Dict[str, Any],
    event_dicts: List[Dict[int, Any]],
    event_labels: List[str],
    event_colors: List[str],
    carrier: str = "hydrogen storage",
    normalized: bool = True,
    start_month: int = 6,
    interval: Optional[Tuple[pd.Timestamp, pd.Timestamp]] = None,
    figure_size: Tuple[float, float] = (12, 6.5),
    soc_alpha: float = 0.95,
    soc_linewidth: float = 1.6,
    soc_colors: Optional[Dict[str, str]] = None,
    event_alpha: float = 0.85,
    event_linewidth: float = 6.0,
    title: Optional[str] = None,
    soc_ylabel: Optional[str] = None,
    event_ylabel: str = "Events",
):
    """
    Single-year plot:
      - Top: SOC overlay for multiple model networks
      - Bottom: Event bars for multiple event types
    """

    dummy_year = 2000

    def fmt_yy(y: int) -> str:
        return f"{str(y)[-2:]}/{str(y + 1)[-2:]}"

    def to_operational_dummy_index(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
        return pd.DatetimeIndex(
            [
                pd.Timestamp(
                    dummy_year + (ts.month < start_month),
                    ts.month,
                    ts.day,
                    ts.hour,
                    ts.minute,
                )
                for ts in idx
            ]
        )

    def extract_soc_and_cap(net):
        mask = net.stores.carrier.astype(str).str.lower() == carrier.lower()
        if not mask.any():
            raise ValueError(f"No stores found with carrier='{carrier}'")

        ids = net.stores.index[mask]
        soc = net.stores_t.e[ids].sum(axis=1)

        if "e_nom_opt" in net.stores.columns and net.stores["e_nom_opt"].notna().any():
            cap = float(net.stores.loc[ids, "e_nom_opt"].fillna(0).sum())
        else:
            cap = float(net.stores.loc[ids, "e_nom"].fillna(0).sum())

        return soc, cap

    def prep_soc_for_year(net):
        soc, cap = extract_soc_and_cap(net)

        if interval is not None:
            s, e = interval
            soc = soc.loc[s:e]

        soc = soc.sort_index()
        soc = soc.loc[str(year):str(year + 1)]

        if normalized:
            if cap <= 0:
                raise ValueError("Storage capacity is <= 0")
            soc = soc / cap

        soc.index = to_operational_dummy_index(soc.index)
        return soc

    def get_event_list_for_year(ed, y):
        ev_list = ed.get(y, [])
        if ev_list is None or isinstance(ev_list, int):
            return []
        return ev_list

    x_start = pd.Timestamp(dummy_year, start_month, 1)
    x_end = pd.Timestamp(dummy_year + 1, start_month, 1) - pd.Timedelta(hours=1)

    month_order = [(start_month + i - 1) % 12 + 1 for i in range(12)]
    xticks = []
    xticklabels = []
    for m in month_order:
        y_ = dummy_year if m >= start_month else dummy_year + 1
        xticks.append(pd.Timestamp(y_, m, 1))
        xticklabels.append(pd.Timestamp(dummy_year, m, 1).strftime("%b"))

    fig = plt.figure(figsize=figure_size)
    gs = fig.add_gridspec(2, 1, height_ratios=[3.2, 1.0], hspace=0.08)
    ax_soc = fig.add_subplot(gs[0])
    ax_evt = fig.add_subplot(gs[1], sharex=ax_soc)

    # ---- SOC plot
    for name, net in networks.items():
        soc = prep_soc_for_year(net)

        color = None
        if soc_colors is not None and name in soc_colors:
            color = soc_colors[name]

        ax_soc.plot(
            soc.index,
            soc.values,
            label=name,
            color=color,
            linewidth=soc_linewidth,
            alpha=soc_alpha,
        )

    ax_soc.set_xlim(x_start, x_end)
    ax_soc.set_ylabel(soc_ylabel or ("SOC [p.u.]" if normalized else "SOC [MWh]"))
    if normalized:
        ax_soc.set_ylim(0, 1.05)

    ax_soc.grid(True, axis="y", alpha=0.3)
    ax_soc.grid(False, axis="x")

    ax_soc.legend(
        loc="lower right",
        frameon=True,
        fontsize=9,
        borderaxespad=0.8,
    )

    # ---- Event bars
    y_pos = np.arange(len(event_dicts))[::-1]
    ax_evt.set_yticks(y_pos)
    ax_evt.set_yticklabels(event_labels)

    for i, (ed, col) in enumerate(zip(event_dicts, event_colors)):
        for ev in get_event_list_for_year(ed, year):
            s = ev.period.left
            e = ev.period.right

            if interval is not None:
                s_int, e_int = interval
                if e < s_int or s > e_int:
                    continue
                s = max(s, s_int)
                e = min(e, e_int)

            s_m = pd.Timestamp(dummy_year + (s.month < start_month), s.month, s.day, s.hour, s.minute)
            e_m = pd.Timestamp(dummy_year + (e.month < start_month), e.month, e.day, e.hour, e.minute)

            ax_evt.plot(
                [s_m, e_m],
                [y_pos[i], y_pos[i]],
                color=col,
                linewidth=event_linewidth,
                alpha=event_alpha,
                solid_capstyle="butt",
            )

    ax_evt.set_xlim(x_start, x_end)
    ax_evt.set_xlabel("Months")
    #ax_evt.set_ylabel(event_ylabel)
    ax_evt.set_xticks(xticks)
    ax_evt.set_xticklabels(xticklabels)

    ax_evt.grid(True, axis="y", alpha=0.15)
    ax_evt.grid(False, axis="x")

    plt.setp(ax_soc.get_xticklabels(), visible=False)

    yy = fmt_yy(year)
    ax_soc.set_title(title or f"SOC and extreme events — {yy}", fontsize=FIGURE_TITLE_FONTSIZE)

    return fig, (ax_soc, ax_evt)


def build_aggregate_pwl_with_ls(
    D_base,
    shares,
    p_ref_init,
    eps,
    p_ls=10000.0,
    p_terminal=98.0,
    price_step=1.0,
    max_iter=20,
    tol=1e-4,
    n_plot=300,
    ylim=(0, 12000),
    save_plot=False,
    file_name="pwl_demand_curve_with_ls"
):
    """
    Build aggregate PWL demand curve (3 segments) with an LS cap segment (seg0).
    Returns:
      segments: list of dicts for seg0..seg3 (includes a_d, b_d, a_gen, b_gen, interval bounds)
      p_ref: updated reference prices after continuity adjustment
      shares_pct: demand quantity per segment in % of D_base (seg1..seg3)
    """

    shares = np.array(shares, dtype=float)
    eps = np.array(eps, dtype=float)
    p_ref = np.array(p_ref_init, dtype=float).copy()

    # ---- Step 1: aggregate reference quantities ----
    p_nom = shares * D_base
    d_agg = np.cumsum(p_nom)  # [D1, D2, D3]

    p_ref[2] = p_terminal

    a_d = np.zeros(3)
    b_d = np.zeros(3)
    for i in range(3):
        a_d[i], b_d[i] = demand_params_from_aggregate_ref(d_ref=d_agg[i], p_ref=p_ref[i], eps=eps[i])

    print("Step 1: initial a_d, b_d")
    for i in range(3):
        print(f"seg{i+1}: d_ref={d_agg[i]:.2f}, p_ref={p_ref[i]:.2f}, eps={eps[i]:.4f}  ->  a={a_d[i]:.2f}, b={b_d[i]:.6f}")

    # ---- Step 2: enforce continuity (no overlapping prices) ----
    for _ in range(max_iter):
        p1_new = (a_d[1] - b_d[1] * d_agg[0]) + price_step
        p2_new = (a_d[2] - b_d[2] * d_agg[1]) + price_step

        p_ref_new = p_ref.copy()
        p_ref_new[0] = p1_new
        p_ref_new[1] = p2_new
        p_ref_new[2] = p_terminal

        a_new = np.zeros(3)
        b_new = np.zeros(3)
        for i in range(3):
            a_new[i], b_new[i] = demand_params_from_aggregate_ref(d_ref=d_agg[i], p_ref=p_ref_new[i], eps=eps[i])

        if np.max(np.abs(p_ref_new - p_ref)) < tol:
            p_ref = p_ref_new
            a_d, b_d = a_new, b_new
            break

        p_ref = p_ref_new
        a_d, b_d = a_new, b_new

    print("\nStep 2: continuity-enforced p_ref and updated a_d, b_d")
    for i in range(3):
        print(f"seg{i+1}: D_end={d_agg[i]:.2f}, p_ref={p_ref[i]:.2f}, eps={eps[i]:.4f}  ->  a={a_d[i]:.2f}, b={b_d[i]:.6f}")

    print("\nSegment price ranges:")
    p_seg1_start = a_d[0] - b_d[0] * 0.0
    p_seg1_end   = a_d[0] - b_d[0] * d_agg[0]
    print(f"seg1: D ∈ [0, {d_agg[0]:.2f}] MW, price ∈ [{p_seg1_start:.1f}, {p_seg1_end:.1f}]")

    p_seg2_start = a_d[1] - b_d[1] * d_agg[0]
    p_seg2_end   = a_d[1] - b_d[1] * d_agg[1]
    print(f"seg2: D ∈ [{d_agg[0]:.2f}, {d_agg[1]:.2f}] MW, price ∈ [{p_seg2_start:.1f}, {p_seg2_end:.1f}]")
    p_seg3_start = a_d[2] - b_d[2] * d_agg[1]
    p_seg3_end   = a_d[2] - b_d[2] * d_agg[2]
    print(f"seg3: D ∈ [{d_agg[1]:.2f}, {d_agg[2]:.2f}] MW, price ∈ [{p_seg3_start:.1f}, {p_seg3_end:.1f}]")

    # ---- Step 3: LS intersection ----
    D_ls = demand_at_price(a_d[0], b_d[0], p_ls)

    if D_ls < 0:
        raise ValueError("LS cap is above seg1 intercept, no intersection (D_ls < 0).")
    if D_ls > d_agg[0]:
        raise ValueError("LS cap intersects after seg1 end; check p_ls or seg1 parameters.")

    print(f"\nStep 3: LS intersection for seg0 at p={p_ls}: D_ls = {D_ls:.2f} MW")

    # ---- Step 4: build segments + print + plot ----
    segments = []

    segments.append({
        "i": -1,
        "name": "Load shedding",
        "D_left": 0.0,
        "D_right": float(D_ls),
        "a_d": float(p_ls),
        "b_d": 0.0,
        "a_gen": float(p_ls),
        "b_gen": 0.0,
        "p_ref": round(float(p_ls), 2),
        "eps": None,
        "D_ref": float(D_ls),
        "width": float(D_ls)
    })

    D_lefts = np.array([D_ls, d_agg[0], d_agg[1]])
    D_rights = np.array([d_agg[0], d_agg[1], d_agg[2]])

    for i in range(3):
        width = float(D_rights[i] - D_lefts[i])

        a_gen_i, b_gen_i = ls_generator_params(a_d[i], b_d[i], D_base=d_agg[i])

        segments.append({
            "i": i,
            "name": f"Segment_{i+1}",
            "D_left": float(D_lefts[i]),
            "D_right": float(D_rights[i]),
            "a_d": float(a_d[i]),
            "b_d": float(b_d[i]),
            "a_gen": float(a_gen_i),
            "b_gen": float(b_gen_i),
            "p_ref": round(float(p_ref[i]), 2),
            "eps": float(eps[i]),
            "D_ref": float(d_agg[i]),
            "width": width
        })

    print("\nStep 4: final segment parameters (demand and LS generator)")
    for s in segments:
        print(f"\n{s['name']}")
        print(f"  interval D: [{s['D_left']:.2f}, {s['D_right']:.2f}]  width={s['width']:.2f}")
        print(f"  a_d={s['a_d']:.2f}, b_d={s['b_d']:.6f}")
        print(f"  a_gen={s['a_gen']:.2f}, b_gen={s['b_gen']:.6f}")

    #colors = ['red', 'blue', 'cyan', 'limegreen']
    colors = [
        "#D62728",  # Load shedding (red)
        "#1F77B4",  # segment_1 (muted blue)
        "#17BECF",  # segment_2 (teal)
        "#2CA02C",  # segment_3 (green)
    ]

    
    plt.figure(figsize=(7, 4.5))

    for idx, s in enumerate(segments):
        D_vals = np.linspace(s["D_left"], s["D_right"], n_plot)
        if s["b_d"] == 0.0:
            P_vals = np.full_like(D_vals, s["a_d"])
        else:
            P_vals = s["a_d"] - s["b_d"] * D_vals
        plt.plot(D_vals, P_vals, lw=3, label=s["name"], color=colors[idx % len(colors)])

    plt.axvline(D_base, color="gray", linestyle="--", label="mean demand")
    plt.xlabel("Aggregate demand (MW)")
    plt.ylabel("Price (€/MWh)")
    plt.title("Aggregate PWL demand curve")
    plt.ylim(*ylim)
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()

    if save_plots and save_plot:
        plt.savefig(
            Figures_mdl_setup_path / f"{file_name}.pdf",
            bbox_inches="tight",
        )

    plt.show()

    # ---- Updated shares (fractions, not percent) to match the plotted widths ----
    seg0 = round(D_ls / D_base,2)
    seg1 = round((d_agg[0] - D_ls) / D_base,3)
    seg2 = round((d_agg[1] - d_agg[0]) / D_base,2)
    seg3 = round((d_agg[2] - d_agg[1]) / D_base,2)

    shares_pct = [seg0, seg1, seg2, seg3]

    print("\nShares (width on x-axis, % of D_base):")
    print(f"seg0 (LS cap): {shares_pct[0]:.2f}%")
    print(f"seg1:          {shares_pct[1]:.2f}%")
    print(f"seg2:          {shares_pct[2]:.2f}%")
    print(f"seg3:          {shares_pct[3]:.2f}%")

    return segments, p_ref, shares_pct

def demand_params_from_aggregate_ref(d_ref, p_ref, eps):
    """
    Compute a_d and b_d for linear inverse demand:
        p(D) = a_d - b_d * D
    calibrated at (d_ref, p_ref) with point elasticity eps.
    """
    b_d = -p_ref / (eps * d_ref)
    a_d = p_ref + b_d * d_ref
    return a_d, b_d

def demand_at_price(a_d, b_d, price):
    """
    Invert p(D) = a_d - b_d D to find D at given price.
    """
    return (a_d - price) / b_d
def ls_generator_params(a_d, b_d, D_base):
    """
    Convert demand curve parameters to LS generator cost parameters.
    """
    a_gen = a_d - b_d * D_base
    b_gen = 0.5 * b_d
    return a_gen, b_gen



def plot_avg_yearly_events_vs_threshold(
    df: pd.DataFrame,
    title: str = None,
    file_name: str = None,
    labels: List[str] = None,
    figure_size=default_figsize,
):
    """
    Plot average yearly number of SP events vs threshold beta.
    """
    dfp = df.copy().sort_values("Threshold beta")

    x = dfp["Threshold beta"].to_numpy()

    fig, ax = plt.subplots(figsize=figure_size, constrained_layout=True)

    markers = ["o", "s", "^", "D", "v", "*", "x", "P"]

    for i, col in enumerate(labels):
        m = markers[i % len(markers)]
        ax.plot(
            x,
            dfp[col].to_numpy(),
            marker=m,
            linewidth=1.8,
            markersize=5,
            label=col,
        )

    ax.set_xlabel("Threshold beta")
    ax.set_ylabel("Events per year")

    dx = 0.02
    ax.set_xlim(float(np.min(x) - dx), float(np.max(x) + dx))

    ax.set_ylim(bottom=0.0)
    ax.grid(True, which="major", linewidth=0.6, alpha=0.35, axis="y")
    ax.grid(False, axis="x")

    if title is not None:
        ax.set_title(title)

    ax.legend(frameon=True)

    if file_name is not None:
        plt.savefig(Figures_results_path / file_name, bbox_inches="tight")

    return fig, ax

def plot_avg_event_duration_vs_threshold(
    df: pd.DataFrame,
    title: str = None,
    file_name: str = None,
    labels: List[str] = None,
    figure_size=default_figsize,
):
    """
    Plot average event duration (days) vs threshold beta.
    """
    dfp = df.copy().sort_values("Threshold beta")

    x = dfp["Threshold beta"].to_numpy()

    fig, ax = plt.subplots(figsize=figure_size, constrained_layout=True)

    markers = ["o", "s", "^", "D", "v", "*", "x", "P"]

    for i, col in enumerate(labels):
        m = markers[i % len(markers)]
        ax.plot(
            x,
            dfp[col].to_numpy(),
            marker=m,
            linewidth=1.8,
            markersize=5,
            label=col,
        )

    ax.set_xlabel("Threshold beta")
    ax.set_ylabel("Average event duration [days]")

    dx = 0.02
    ax.set_xlim(float(np.min(x) - dx), float(np.max(x) + dx))

    ax.set_ylim(bottom=0.0)
    ax.grid(True, which="major", linewidth=0.6, alpha=0.35, axis="y")
    ax.grid(False, axis="x")

    if title is not None:
        ax.set_title(title)

    ax.legend(frameon=True)

    if file_name is not None:
        plt.savefig(Figures_results_path / file_name, bbox_inches="tight")

    return fig, ax

def rows_at_threshold_beta(
    tables_by_cap: Dict[str, pd.DataFrame],
    beta_star: float,
    model_cols: List[str],
) -> pd.DataFrame:
    rows = []
    for cap, df in tables_by_cap.items():
        r = df.loc[df["Threshold beta"] == round(beta_star, 2), ["Threshold beta"] + model_cols].iloc[0]
        out = {"Capacity": cap}
        for c in model_cols:
            out[c] = float(r[c])
        rows.append(out)
    return pd.DataFrame(rows)


def plot_capacity_sensitivity_bars(
    df_bars: pd.DataFrame,
    model_cols: List[str],
    ylabel: str,
    title: str,
    figsize: Tuple[float, float] = (8.0, 4.2),
    file_name: str | None = None,
):
    caps = df_bars["Capacity"].to_list()
    x = np.arange(len(caps), dtype=float)

    n = len(model_cols)
    width = 0.80 / n
    offsets = (np.arange(n) - (n - 1) / 2) * width

    fig, ax = plt.subplots(figsize=figsize)

    for i, m in enumerate(model_cols):
        ax.bar(x + offsets[i], df_bars[m].to_numpy(), width=width, label=m)

    ax.set_xticks(x)
    ax.set_xticklabels(caps)
    ax.set_xlabel("Capacity assumption", labelpad=10)
    ax.set_ylabel(ylabel)
    ax.set_title(title)

    ax.set_ylim(bottom=0.0)
    ax.set_axisbelow(True)
    ax.grid(True, axis="y", linewidth=0.6, alpha=0.4)

    ax.legend(frameon=True, loc="upper left", bbox_to_anchor=(1.0, 1.02), ncol=1, title="Model")
    fig.tight_layout()

    if file_name is not None:
        plt.savefig(Figures_results_path / file_name, bbox_inches="tight")

    return fig, ax

