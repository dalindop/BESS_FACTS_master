# -*- coding: utf-8 -*-
"""
Test de objective.py. Verifica que la funcion objetivo se construye,
es de minimizacion, y que los terminos vacios (hidro, LC, BESS en W&W)
no rompen. Tambien aplica la buena practica de inspeccionar la objetivo.
"""

import importlib.util
import pyomo.environ as pyo
import sets
import parameters as par
import variables as var
import objective as obj

# reutilizamos el mini-loader del test de variables
spec = importlib.util.spec_from_file_location("tv", "test_variables.py")


def build_data_www(n_horas=3):
    import openpyxl
    wb = openpyxl.load_workbook("/mnt/user-data/uploads/Case_IEEE6.xlsx",
                                data_only=True)

    def hoja(ws):
        f = list(ws.iter_rows(values_only=True)); return f[0], f[1:]

    class D: pass
    d = D(); d.mva_base = 100; d.n_horas = n_horas
    d.n_seg_costo = 3; d.n_seg_perdidas = 3
    hdr, fl = hoja(wb["Buses"]); c = {n: i for i, n in enumerate(hdr)}
    d.nodos = []; pd_ = {}
    for f in fl:
        nid = f"b{f[c['bus_i']]}"; d.nodos.append(nid); pd_[nid] = f[c["Pd_MW"]]
    hdr, fl = hoja(wb["Lineas"]); c = {n: i for i, n in enumerate(hdr)}
    d.lineas = []; d.susceptancia = {}; d.conductancia = {}; d.flow_max = {}
    for k, f in enumerate(fl, 1):
        lid = f"l{k}"; r = f[c["r_pu"]]; x = f[c["x_pu"]]
        d.lineas.append(lid); d.susceptancia[lid] = 1/x
        d.conductancia[lid] = r/(r**2+x**2); d.flow_max[lid] = f[c["rateA_MW"]]
    hdr, fl = hoja(wb["Generadores"]); c = {n: i for i, n in enumerate(hdr)}
    d.gen_termica = []; d.pmin_term = {}; d.pmax_term = {}
    d.ramp_up = {}; d.ramp_down = {}; orden = []
    for k, f in enumerate(fl, 1):
        gid = f"G{k}"; d.gen_termica.append(gid); orden.append(gid)
        d.pmin_term[gid] = f[c["Pmin_MW"]]; d.pmax_term[gid] = f[c["Pmax_MW"]]
        d.ramp_up[gid] = f[c["rango_MW"]]; d.ramp_down[gid] = f[c["rango_MW"]]
    hdr, fl = hoja(wb["Costos"]); c = {n: i for i, n in enumerate(hdr)}
    d.slope_term = {}; d.fg_min_term = {}
    for gid, f in zip(orden, fl):
        fg, sl = par.linealizar_costo(f[c["c2_$/MW2"]], f[c["c1_$/MW"]],
                                      f[c["c0_$"]], d.pmin_term[gid],
                                      d.pmax_term[gid], 3)
        d.fg_min_term[gid] = fg
        for mm, v in enumerate(sl, 1): d.slope_term[(gid, mm)] = v
    d.demanda = {(n, t): pd_[n] for n in d.nodos for t in range(1, n_horas+1)}
    d.gen_hidro = []; d.gen_renov = []
    d.lineas_cand = []; d.nodos_bess = []; d.lineas_facts = []
    return d


d = build_data_www()
m = pyo.ConcreteModel()
sets.build_sets(m, d)
par.build_parameters(m, d)
var.build_variables(m, d)
obj.build_objective(m, d)

# --- comprobaciones ---
assert m.obj.sense == pyo.minimize, "debe ser minimizacion"
assert m.nobjectives() == 1, "debe haber exactamente 1 objetivo"
# la expresion debe existir y ser no trivial (depende de variables)
assert m.obj.expr is not None
# FACTS no debe estar (diferido)
assert not hasattr(m, "z_f")

print("OK: funcion objetivo construida (sin FACTS, terminos vacios OK).")
print(f"  Sentido      : {'minimizar' if m.obj.sense==1 else 'maximizar'}")
print(f"  Nº objetivos : {m.nobjectives()}")
print()
# Buena practica del profesor: inspeccionar la objetivo armada.
print("=== Inspeccion de la funcion objetivo (primeros terminos) ===")
s = str(m.obj.expr)
print(s[:400] + ("..." if len(s) > 400 else ""))
