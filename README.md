# Master-Thesis-Jonathan-Gadfelt

This repository contains the code used to reproduce the results presented in the master thesis  
**“Extreme events and demand elasticity in energy system models with high renewable penetration and limited foresight”**,  
authored by Jonathan Lybecker Gadfelt.

The thesis was submitted to the Department of Wind and Energy Systems at the Technical University of Denmark (DTU) in February 2026 as part of the MSc programme in Sustainable Energy Systems.

## License
Copyright © 2026 Jonathan Lybecker Gadfelt <jonathan@gadfelt.dk>  
This work is licensed under the Creative Commons Attribution 4.0 International Licence (CC-BY).

## Repository contents
The repository already contains all model outputs and results presented in the thesis.  
If you wish to reproduce the results or run new simulations, follow the instructions below.
The full acedemic report of the thesis lies in the file **'Master_thesis_Jonathan_Gadfelt_Github.pdf'**

### Running model simulations
Use the Python script **`Run_results.py`** to run new model simulations.  
The file contains inline comments explaining how to configure and execute the different modelling setups.

### Generating plots and tables
The Jupyter notebook **`Results.ipynb`** generates all figures and tables presented in the thesis, as well as additional analyses not included in the final report.
It is setup to use the results contained in the repository by default, and will automatically generate all plots and tables when executed.

To use the notebook for new model outputs:
1. Set the correct path to the model output directory in the first code cell.
2. Ensure the result names match those generated in **`Run_results.py`**.
3. Just run the notebook to with the new test name to then generate all plots and tables.

### Code structure
- **`functions_plots.py`** contains all plotting and table-generation functions.
- **`functions_other.py`** contains helper functions used to run the model simulations and process results.
- **`Classes.py`** defines the PyPSA model classes used in the study to create the capacity expansion model and economic dispatch model.

## Software versions
Model simulations were performed using **PyPSA 1.0.6**.  
All package versions are specified in the `environment.yml` file.
