# Master-Thesis-Jonathan-Gadfelt
This repository contains the code to reproduce the results presented in the master thesis and "Extreme events and demand elasticity in energy system models with high renewable penetration and limited foresight" created by me (Jonathan Lybecker Gadfelt) 

The master thesis is submitted to the Department of Wind and Energy Systems at the Technical University of Denmark (DTU) in February 2026 as part of the MSc in Sustainable Energy Systems.

Copyright c2026 Jonathan Lybecker Gadfelt < jonathan@gadfelt.dk >
This work is licensed under a Creative Commons Attribution 4.0 International Licence (CC-BY).

The repository already contains all the results presented in the thesis. However, if you want to reproduce the results yourself, please follow the instructions below.

Use the python file: "Run_results.py" to run the desired new model simulations. It contains commends internally in the code to guide you through the process of running the models.

The file Results.ipynb contains the code to generate the plots and tables presented in the thesis based on the model outputs and many additional results that did not make it into the thesis final report.
Usage: Just make sure to define the correct path to the model outputs in the first code cell. This is done by changing the names of the new test results you have generated in "Run_results.py" - Then all the plots and tables will be generated automatically when running through the notebook.

All functions to generate the plots and tables are contained in the file: "functions_plots.py".
Additional helper functions to run the model simulations are contained in the file: "functions_other.py".

Lastly, the PyPSA models used for the simulations are contained as classes in the file: Classes.py

The PyPSA version used for the model simulations was PyPSA 1.0.6. All package version are listed in the environment.yml file.
