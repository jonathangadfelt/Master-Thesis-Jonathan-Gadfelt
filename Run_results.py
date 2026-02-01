"""
This code has been prepared for the master thesis: 
"Extreme events and demand elasticity in energy system models with high renewable penetration and limited foresight" by Jonathan Gadfelt 

Copyright c2026 Jonathan Lybecker Gadfelt < jonathan@gadfelt.dk >
This work is licensed under a Creative Commons Attribution 4.0 International Licence (CC-BY).
"""

from functions_other import *
from Classes import *
print("Pypsa version:", pypsa.__version__)

#%%       INITIALIZATION AND SETTINGS
# Define the use technologies and regions(s)
region = 'ESP'  
setup_exp = {
    f'{region}': {
        'OCGT': False,
        'CCGT': False,
        'battery storage': False,
        'onwind': True,
        'offwind': False,
        'solar': True,
        'electrolysis': True,
        'fuel cell': True,
        'Hydrogen storage': True,
        'Reservoir hydro storage': False,
        'load shedding': False
    }
}

setup_dispatch = {
    f'{region}': {
        'OCGT': False,
        'CCGT': False,
        'battery storage': False,
        'onwind': True,
        'offwind': False,
        'solar': True,
        'electrolysis': True,
        'fuel cell': True,
        'Hydrogen storage': True,
        'Reservoir hydro storage': False,
        'load shedding': True
    }
}

# Default weather, hydro and demand years
w_year_exp = 2009
h_year_exp = 2007
d_year_exp = 2018

# Dispatch and rolling horizon settings
w_year_dispatch = 2009
h_year_dispatch = 2007
d_year_dispatch = 2018

base_dir = os.getcwd()  # Gets the current working directory (where notebook is running)
N_results_path = os.path.join(base_dir, "Network_results")
Results_path = os.path.join(base_dir, "Results")
os.makedirs(N_results_path, exist_ok=True)
weather_years = All_data['solar'].index.year.unique()[:31]


########################################################################
# __________________________ MODEL RUN NAMES ___________________________
########################################################################
Test_name_exp = "base_new"  # Name to append to files for identification
#Test_name_dispatch = "base_lin_flex_eps_5p_Pnom_10p"  # Name to append to files for identification
Test_name_dispatch = "base_q35"  # Name to append to files for identification


########################################################################
# __________________________ MODEL SETTINGS _________________________
########################################################################
"Which test to run"
capacity_exp = False
one_capacity_exp_test = False
New_exp_results = False # Set to False to load existing results file
exp_result_key = "base_new_extended"  # Key to identify existing results file USED when New_exp_results = false
dispatch_pf_rh = True # CHECK LS in SETUP DISPATCH
one_rh_pf_test = False

start_month = 6
# Which capacities to use for dispatch model from expansion results   
Q_capa = "35%" # either mean or 75% 60% etc.

# _______________________ DEMAND ELASTICITY SETTINGS _____________________
PWL = False
lin_DE_flex = False

if lin_DE_flex:
    b_gen_lin_de = 0.3404
    a_gen_lin_de = 0


"_____________ RUN EXPANSION MODEL __________________"  
#%%-------TEST EXPANSION MODEL FOR ONE YEAR----------------
if one_capacity_exp_test:
    N_class = Build_network_capacity_exp(weather_year=w_year_exp, hydro_year=h_year_exp, demand_year=d_year_exp,
        data=All_data, cost_data=Cost, setup=setup_exp, start_month=start_month)
    N = N_class.network

    silent_optimize(N)

    print_Results(N)
    N.statistics.energy_balance.plot.area(linewidth=0, bus_carrier="electricity")

#%%-------RUN EXPANSION MODEL FOR ALL YEARS----------------
if capacity_exp:
    exp_folder = f"N_EXP_d_{d_year_exp}_{Test_name_exp}"
    exp_path = os.path.join(N_results_path, exp_folder)
    os.makedirs(exp_path, exist_ok=True)

    CO2_limit = False
    
    for year in weather_years:
        N = Build_network_capacity_exp(weather_year=year, hydro_year=h_year_exp, demand_year=d_year_exp,
            data=All_data, cost_data=Cost, setup=setup_exp, start_month=start_month).network

        if CO2_limit:
            # Calculate CO2 budget as 1% of total demand emissions in demand year
            co2_budget = 0.01 * All_data['demand'].loc[All_data['demand'].index.year == d_year_exp, region].sum() * (Cost.costs.at["gas","CO2 intensity"] / (Cost.costs.at["OCGT","efficiency"]/100 if Cost.costs.at["OCGT","efficiency"] > 1 else Cost.costs.at["OCGT","efficiency"]))

            N.add(  "GlobalConstraint",
                    "emission_limit",
                    carrier_attribute="co2_emissions",
                    sense="<=",
                    constant=co2_budget)
        
        silent_optimize(N)
    
        network_name = f"N_w-{year}_d-{d_year_exp}_{region}_{Test_name_exp}.nc"
        N.export_to_netcdf(os.path.join(exp_path, network_name))
        
        print(f"Saved network for year {year} as {network_name}")

#%%-------Load or create new opt_capacities_df----------------

if New_exp_results:
    # Initialize
    networks_exp = {}
    folder_name = f"N_EXP_d_{d_year_exp}_{Test_name_exp}"
    
    # Load network files
    networks_exp = load_networks(folder_name = folder_name, weather_years = weather_years)
    
    # create table with capacities per year
    yearly_exp_caps_df = capacities_exp_per_year(networks_exp)
    print(yearly_exp_caps_df.head(7))
    
    # Save final result
    file_name = f"Results\\opt_cap_exp_model_d{d_year_exp}_{Test_name_exp}.csv"
    
    # Create stats dict with optimized capacities and save to csv
    opt_capacities_df = stats_exp_nets(yearly_exp_caps_df, as_columns= True, save_path=file_name)

else:   
    # Load existing results file
    name = f"opt_cap_exp_model_d{d_year_exp}_{exp_result_key}.csv"
    opt_capacities_df = pd.read_csv(os.path.join(Results_path, name), index_col=0)



#%%-------RUN DISPATCH MODELS---------------------------------
" Running for all weather years "

d_horizon = 7 # days in horizon
o_horizon = 0 # days of overlap in rh


if dispatch_pf_rh:
    # create subfolders for PF and RH
    pf_folder = f"N_PF_d_{d_year_dispatch}_{Test_name_dispatch}"
    rh_folder = f"N_RH_d_{d_year_dispatch}_{Test_name_dispatch}"

    pf_path = os.path.join(N_results_path, pf_folder)
    rh_path = os.path.join(N_results_path, rh_folder)
    
    os.makedirs(pf_path, exist_ok=True)
    os.makedirs(rh_path, exist_ok=True)
    
    for year in weather_years:
        
        network_name_pf = f"N_PF_w-{year}_d-{d_year_dispatch}_{region}_{Test_name_dispatch}.nc"
        network_name_rh = f"N_RH_w-{year}_d-{d_year_dispatch}_{region}_{Test_name_dispatch}.nc"

        # Enable skipping if results already exist
        if network_name_pf in os.listdir(pf_path):
            print(f"Networks for {year} already exists, skipping...")
            continue

        N_pf_class = Build_dispatch_network(
            opt_capacities_df=opt_capacities_df.loc[Q_capa],
            weather_year=year, hydro_year=h_year_dispatch, demand_year=d_year_dispatch,
            data=All_data, cost_data=Cost, setup=setup_dispatch, start_month=start_month)

        N_pf = N_pf_class.network

        N_rh_class = Build_dispatch_network(
            opt_capacities_df=opt_capacities_df.loc[Q_capa],
            weather_year=year, hydro_year=h_year_dispatch, demand_year=d_year_dispatch,
            data=All_data, cost_data=Cost, setup=setup_dispatch, start_month=start_month)

        N_rh = N_rh_class.network

        N_rh.stores.at['Hydrogen storage', 'e_cyclic'] = False
        N_rh.stores.at['Hydrogen storage', 'e_initial'] = 0.65 * N_rh.stores.at['Hydrogen storage', 'e_nom']
        N_rh.stores.at['Hydrogen storage', 'marginal_cost'] = 85.50


        if PWL:
            D_base = N_pf.loads_t.p_set.mean().iloc[0]    # reference demand (MW)

            de_shares =  [0.115, 0.1, 0.1]
            # eps = np.array([-0.025, -0.3, -0.01])
            a_gen_list = [1479.6, 1079.0, 98.0]
            b_gen_list = [1.2847, 0.0694, 0.1702]

            #p_Q = [D_base*de_shares[0], D_base*de_shares[1], D_base*de_shares[2]]  # quantities at different linear segments
            
            for i in range(len(de_shares)):

                    p_Q = D_base * de_shares[i]

                    calc_marginal_cost_quadratic = b_gen_list[i]        # b_gen to pass to PyPSA
                    calc_marginal_cost = a_gen_list[i]                  # a_gen (marginal price at d_ref when D_baseline = d_ref)

                    add_elastic_demand(
                        N_pf,
                        p_nom = p_Q, 
                        marginal_cost = calc_marginal_cost,
                        marginal_cost_quadratic = calc_marginal_cost_quadratic, 
                        segment_name = f"segment_{i+1}"
                    )

                    add_elastic_demand(
                        N_rh,
                        p_nom = p_Q, 
                        marginal_cost = calc_marginal_cost,
                        marginal_cost_quadratic = calc_marginal_cost_quadratic, 
                        segment_name = f"segment_{i+1}"
                    )


        if lin_DE_flex:
            D_base = N_pf.loads_t.p_set.mean().iloc[0]    # reference demand (MW)
            
            p_Q = D_base * 0.10  # 10% of mean flexible demand quantity
                        
            calc_marginal_cost_quadratic = b_gen_lin_de             # b_gen to pass to PyPSA
            calc_marginal_cost = a_gen_lin_de                             # a_gen (marginal price at d_ref when D_baseline = d_ref)


            add_elastic_demand(N_pf,
                p_nom = p_Q, #float(np.max(N_exp.loads_t.p_set)),
                marginal_cost = calc_marginal_cost,
                marginal_cost_quadratic = calc_marginal_cost_quadratic #(10/240)*0.5
                )

            add_elastic_demand(N_rh,
                p_nom = p_Q,
                marginal_cost = calc_marginal_cost,
                marginal_cost_quadratic = calc_marginal_cost_quadratic #(10/240)*0.5
                )
        
        
        silent_optimize(N_pf)

        # Run the rolling-horizon optimization
        N_rh.optimize.optimize_with_rolling_horizon(
            snapshots=N_rh.snapshots,
            horizon= 24 * d_horizon,
            overlap= 24 * o_horizon,
            solver_name="gurobi",
            solver_options={"OutputFlag": 0},
            assign_all_duals=True)
        

        # save to their respective folders
        N_pf.export_to_netcdf(os.path.join(pf_path, network_name_pf))
        N_rh.export_to_netcdf(os.path.join(rh_path, network_name_rh))

        print(f"Saved PF network for {year} as {network_name_pf} in {pf_folder}")
        print(f"Saved RH network for {year} as {network_name_rh} in {rh_folder}")

#%%       TEST PERFECT AND ROLLING HORIZON FOR ONE YEAR

test_year = 1997

if one_rh_pf_test:
    N_pf, N_rh = rh_pf_test_yearly(
        test_year, 
        horizon_days=7, 
        overlap_days=0,
        capacities="75%", 
        opt_capacities_df=opt_capacities_df)

    # Calculate and print basic results
    pf_obj = float(N_pf.objective) / 1e6
    rh_obj = float(N_rh.statistics.system_cost().sum()) / 1e6
    diff_obj = rh_obj - pf_obj

    pf_tot_meur = tot_cost_N(N_pf) / 1e6
    rh_tot_meur = tot_cost_N(N_rh) / 1e6
    diff_tot_meur = rh_tot_meur - pf_tot_meur

    print(f"Results for year {test_year}")
    print(f"\nObjective PF [MEUR]: {pf_obj:.2f}")
    print(f"Objective RH [MEUR]: {rh_obj:.2f}")
    print(f"Difference RH - PF [MEUR]: {diff_obj:.2f}")
    print(f"\nIs RH objective higher than PF objective? {rh_obj > pf_obj}")

    print(f"PF total cost [MEUR]: {pf_tot_meur:.2f}")
    print(f"RH total cost [MEUR]: {rh_tot_meur:.2f}")
    print(f"Difference RH - PF total cost [MEUR]: {diff_tot_meur:.2f}")




