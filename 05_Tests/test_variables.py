# -*- coding: utf-8 -*-
"""
Test de variables.py. Usa el mismo mini-loader del W&W (sin BESS ni
lineas candidatas) y ademas un caso con S y LC poblados, para verificar
que las variables de inversion/BESS se crean bien cuando hay datos.
"""

import openpyxl
import pyomo.environ as pyo
import sets
import parameters as par
import variables as var


def build_data_www(n_horas=4):
    XLSX = "/mnt/user-data/uploads/Case_IEEE6.xlsx"
    wb = openpyxl.load_workbook(XLSX, data_only=True)

    def hoja(ws):
        f = list(ws.iter_rows(values_only=True))
        return f[0], f[1:]

    class D: pass
    d = D()
    d.mva_base = 100; d.n_horas = n_horas
    d.n_seg_costo = 3; d.n_seg_perdidas = 3

    hdr, filas = hoja(wb["Buses"]); c = {n: i for i, n in enumerate(hdr)}
    d.nodos = []; pd_ = {}
    for f in filas:
        nid = f"b{f[c['bus_i']]}"; d.nodos.append(nid)
        pd_[nid] = f[c["Pd_MW"]]

    hdr, filas = hoja(wb["Lineas"]); c = {n: i for i, n in enumerate(hdr)}
    d.lineas = []; d.susceptancia = {}; d.conductancia = {}; d.flow_max = {}
    for k, f in enumerate(filas, 1):
        lid = f"l{k}"; r = f[c["r_pu"]]; x = f[c["x_pu"]]
        d.lineas.append(lid)
        d.susceptancia[lid] = 1/x
        d.conductancia[lid] = r/(r**2+x**2)
        d.flow_max[lid] = f[c["rateA_MW"]]

    hdr, filas = hoja(wb["Generadores"]); c = {n: i for i, n in enumerate(hdr)}
    d.gen_termica = []; d.pmin_term = {}; d.pmax_term = {}
    d.ramp_up = {}; d.ramp_down = {}; orden = []
    for k, f in enumerate(filas, 1):
        gid = f"G{k}"; d.gen_termica.append(gid); orden.append(gid)
        d.pmin_term[gid] = f[c["Pmin_MW"]]; d.pmax_term[gid] = f[c["Pmax_MW"]]
        d.ramp_up[gid] = f[c["rango_MW"]]; d.ramp_down[gid] = f[c["rango_MW"]]

    hdr, filas = hoja(wb["Costos"]); c = {n: i for i, n in enumerate(hdr)}
    d.slope_term = {}; d.fg_min_term = {}
    for gid, f in zip(orden, filas):
        fg, sl = par.linealizar_costo(f[c["c2_$/MW2"]], f[c["c1_$/MW"]],
                                      f[c["c0_$"]], d.pmin_term[gid],
                                      d.pmax_term[gid], 3)
        d.fg_min_term[gid] = fg
        for mm, v in enumerate(sl, 1): d.slope_term[(gid, mm)] = v

    d.demanda = {(n, t): pd_[n] for n in d.nodos for t in range(1, n_horas+1)}
    d.gen_hidro = []; d.gen_renov = []
    d.lineas_cand = []; d.nodos_bess = []; d.lineas_facts = []
    return d


# --- Caso 1: W&W puro (S y LC vacios) --------------------------------
d = build_data_www()
m = pyo.ConcreteModel()
sets.build_sets(m, d)
par.build_parameters(m, d)
var.build_variables(m, d)

T = 4; nG = 3; nL = 11; nN = 6
assert len(m.P_g) == nG*T,        "P_g indexada por GxT"
assert len(m.f) == nL*T,          "flujo sobre L_ALL = 11 lineas (LC vacio)"
assert len(m.theta) == nN*T,      "theta por NxT"
assert len(m.u) == nG*T,          "estado UC por GxT"
assert len(m.delta_seg) == nL*3*T, "delta_seg por L_ALL x SEG_PERD x T"
assert len(m.dP_seg) == nG*3*T,   "dP_seg por G x SEG_COST x T"
# BESS y candidatas vacias en W&W:
assert len(m.Pch) == 0,  "sin BESS -> Pch vacio"
assert len(m.Psmax) == 0
assert len(m.x_l) == 0,  "sin LC -> x_l vacio"
assert len(m.y_s) == 0
# dominios correctos:
assert m.u["G1", 1].domain is pyo.Binary
assert m.f["l1", 1].domain is pyo.Reals
assert m.P_g["G1", 1].domain is pyo.NonNegativeReals

print("OK caso W&W: variables de operacion+UC creadas; BESS/LC vacios.")
print(f"  P_g: {len(m.P_g)} | f: {len(m.f)} | theta: {len(m.theta)} | u: {len(m.u)}")
print(f"  delta_seg: {len(m.delta_seg)} | dP_seg: {len(m.dP_seg)}")
print(f"  (BESS y lineas candidatas vacios, como debe ser en W&W)")

# --- Caso 2: con BESS y linea candidata pobladas ---------------------
import copy
d2 = copy.deepcopy(d)
d2.nodos_bess = ["b3", "b5"]      # 2 nodos candidatos BESS
d2.lineas_cand = ["lc1"]          # 1 linea candidata
m2 = pyo.ConcreteModel()
sets.build_sets(m2, d2)
par.build_parameters(m2, d2)
var.build_variables(m2, d2)

assert len(m2.Pch) == 2*T,   "BESS Pch por SxT"
assert len(m2.SoC) == 2*T
assert len(m2.Psmax) == 2,   "dimensionamiento BESS por nodo"
assert len(m2.y_s) == 2,     "instalacion BESS binaria por nodo"
assert len(m2.x_l) == 1,     "1 linea candidata"
# el flujo ahora cubre 11 existentes + 1 candidata = 12
assert len(m2.f) == 12*T,    "L_ALL = L U LC = 12 lineas"
assert m2.x_l["lc1"].domain is pyo.Binary
assert m2.Psmax["b3"].domain is pyo.NonNegativeReals

print("OK caso con BESS+candidata: variables de inversion/BESS creadas.")
print(f"  Pch: {len(m2.Pch)} | Psmax: {len(m2.Psmax)} | y_s: {len(m2.y_s)} | x_l: {len(m2.x_l)}")
print(f"  flujo f sobre L_ALL = {len(m2.f)//T} lineas (11 exist + 1 cand)")

# --- FACTS aun no declarado (correcto en esta fase) ------------------
assert not hasattr(m2, "z_f"), "FACTS pendiente: no debe existir aun"
print("OK: bloque FACTS correctamente diferido (z_f, X_f no declarados).")
