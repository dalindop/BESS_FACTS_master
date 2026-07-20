# -*- coding: utf-8 -*-
"""
Test de integracion: carga el caso W&W con data_loader y construye +
resuelve el modelo COMPLETO. Verifica que el objeto `data` del loader
alimenta correctamente todos los modulos (sets->constraints).
"""
import pyomo.environ as pyo
import data_loader
import sets, parameters as par, variables as var
import objective as obj, constraints as con

# cargar con el loader (no con un mini-loader manual)
d = data_loader.cargar_datos("caso_WW.xlsx")
# usar horizonte corto para el test rapido
d.n_horas = 3
# reconstruir demanda a 3h
dem = {}
for (nodo, h), val in d.demanda.items():
    if h <= 3:
        dem[(nodo, h)] = val
d.demanda = dem

# construir el modelo completo
m = pyo.ConcreteModel()
sets.build_sets(m, d)
par.build_parameters(m, d)
var.build_variables(m, d)
obj.build_objective(m, d)
con.build_constraints(m, d)

# resolver
res = pyo.SolverFactory("appsi_highs").solve(m)
term = str(res.solver.termination_condition)
print(f"Terminacion: {term}")
assert term == "optimal", f"esperaba optimo, obtuve {term}"

# verificaciones basicas de coherencia
gen = sum(pyo.value(m.P_g[g, 1]) for g in m.G)
dem_t = sum(pyo.value(m.D[n, 1]) for n in m.N)
perd = sum(pyo.value(m.Ploss[l, 1]) for l in m.L)
print(f"Generacion: {gen:.1f} MW")
print(f"Demanda   : {dem_t:.1f} MW")
print(f"Perdidas  : {perd:.2f} MW")
assert gen >= dem_t - 1e-2, "generacion debe cubrir demanda"
assert abs((gen - dem_t) - perd) < 1e-1, "gen = demanda + perdidas"
print(f"Slack theta[b1]: {pyo.value(m.theta['b1',1]):.4f}")
assert abs(pyo.value(m.theta["b1", 1])) < 1e-6

print("\nOK: el data_loader alimenta el modelo completo y resuelve.")
print("    Todos los modulos (sets->constraints) funcionan con los")
print("    datos cargados desde la plantilla Excel.")
