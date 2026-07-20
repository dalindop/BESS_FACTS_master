import sys, os
_BASE = os.path.dirname(os.path.abspath(__file__))
for sub in ["01_Inputs", "02_Core", "03_Solvers"]:
    sys.path.append(os.path.join(_BASE, "02_Model", sub))

import data_loader, model_builder
import pyomo.environ as pyo

d = data_loader.cargar_datos(
    r"H:\My Drive\2. Universidad Nacional de Colombia\2. Postgraduate\1_SEMESTER\TESIS DE MAESTRIA\2nd Search\04_TESIS_DANIEL\03_CODIGO_TRABAJO_DANIEL\BESS_FACTS_master\01_Data\03_Test_Cases\caso_IEEE6_ww_A.xlsx")
m = model_builder.construir_modelo(d)

opt = pyo.SolverFactory("appsi_highs")
res = opt.solve(m, tee=True)          # tee=True muestra todo
print("=== ESTADO:", res.termination_condition)