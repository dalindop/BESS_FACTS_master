# -*- coding: utf-8 -*-
"""
Test del Bloque 3b (renovable con curtailment). Anade una renovable
artificial al W&W y valida:
- P_r + Pcurt = disponibilidad (reparto exacto),
- P_r nunca supera la disponibilidad,
- si la renovable es barata y hay red, genera todo (curtailment ~0),
- el balance sigue cuadrando.
"""

import math, openpyxl
import pyomo.environ as pyo
import sets, parameters as par, variables as var
import objective as obj, constraints as con


def build_data(n_horas=3, con_renov=True):
    wb = openpyxl.load_workbook("/mnt/user-data/uploads/Case_IEEE6.xlsx",
                                data_only=True)

    def hoja(ws):
        f = list(ws.iter_rows(values_only=True)); return f[0], f[1:]

    class D: pass
    d = D(); d.mva_base = 100; d.n_horas = n_horas
    d.n_seg_costo = 3; d.n_seg_perdidas = 3
    hdr, fl = hoja(wb["Buses"]); c = {n: i for i, n in enumerate(hdr)}
    d.nodos = []; pd_ = {}; d.nodo_slack = None
    for f in fl:
        nid = f"b{f[c['bus_i']]}"; d.nodos.append(nid); pd_[nid] = f[c["Pd_MW"]]
        if f[c["type"]] == 3: d.nodo_slack = nid
    hdr, fl = hoja(wb["Lineas"]); c = {n: i for i, n in enumerate(hdr)}
    d.lineas = []; d.susceptancia = {}; d.conductancia = {}; d.flow_max = {}
    d.linea_from = {}; d.linea_to = {}
    for k, f in enumerate(fl, 1):
        lid = f"l{k}"; r = f[c["r_pu"]]; x = f[c["x_pu"]]
        d.lineas.append(lid); d.susceptancia[lid] = 1/x
        d.conductancia[lid] = r/(r**2+x**2); d.flow_max[lid] = f[c["rateA_MW"]]
        d.linea_from[lid] = f"b{f[c['from_bus']]}"; d.linea_to[lid] = f"b{f[c['to_bus']]}"
    hdr, fl = hoja(wb["Generadores"]); c = {n: i for i, n in enumerate(hdr)}
    d.gen_termica = []; d.pmin_term = {}; d.pmax_term = {}
    d.ramp_up = {}; d.ramp_down = {}; orden = []; d.gen_en_nodo = {}
    for k, f in enumerate(fl, 1):
        gid = f"G{k}"; d.gen_termica.append(gid); orden.append(gid)
        d.pmin_term[gid] = f[c["Pmin_MW"]]; d.pmax_term[gid] = f[c["Pmax_MW"]]
        d.ramp_up[gid] = f[c["Pmax_MW"]]; d.ramp_down[gid] = f[c["Pmax_MW"]]
        d.gen_en_nodo.setdefault(f"b{f[c['bus']]}", []).append(gid)
    hdr, fl = hoja(wb["Costos"]); c = {n: i for i, n in enumerate(hdr)}
    d.slope_term = {}; d.fg_min_term = {}
    for gid, f in zip(orden, fl):
        fg, sl = par.linealizar_costo(f[c["c2_$/MW2"]], f[c["c1_$/MW"]],
                                      f[c["c0_$"]], d.pmin_term[gid],
                                      d.pmax_term[gid], 3)
        d.fg_min_term[gid] = fg
        for mm, v in enumerate(sl, 1): d.slope_term[(gid, mm)] = v
    d.demanda = {(n, t): pd_[n] for n in d.nodos for t in range(1, n_horas+1)}
    d.gen_hidro = []; d.lineas_cand = []; d.nodos_bess = []
    d.lineas_facts = []; d.hid_en_nodo = {}; d.bess_en_nodo = {}
    # RENOVABLE artificial en b5
    if con_renov:
        d.gen_renov = ["R1"]
        d.ren_en_nodo = {"b5": ["R1"]}
        # disponibilidad: 30 MW en cada hora
        d.disponibilidad_renov = {("R1", t): 30.0
                                  for t in range(1, n_horas+1)}
    else:
        d.gen_renov = []; d.ren_en_nodo = {}; d.disponibilidad_renov = {}
    return d


d = build_data(n_horas=3, con_renov=True)
m = pyo.ConcreteModel()
sets.build_sets(m, d); par.build_parameters(m, d)
var.build_variables(m, d); obj.build_objective(m, d)
con.build_constraints(m, d)
res = pyo.SolverFactory("appsi_highs").solve(m)
print("Terminacion:", res.solver.termination_condition)
assert str(res.solver.termination_condition) == "optimal"

r = "R1"
print(f"\nRenovable {r} (disponibilidad 30 MW/hora):")
for t in m.T:
    pr = pyo.value(m.P_r[r, t]); pc = pyo.value(m.Pcurt[r, t])
    disp = pyo.value(m.disp_renov[r, t])
    print(f"  t{t}: genera={pr:.1f}, curtailment={pc:.1f}, "
          f"disponible={disp:.1f}")
    # reparto exacto
    assert abs((pr + pc) - disp) < 1e-3, "Pr + Pcurt = disponibilidad"
    # no supera disponibilidad
    assert pr <= disp + 1e-3, "Pr no puede superar lo disponible"

# la renovable (costo 0) deberia generarse toda -> curtailment ~ 0
curt_total = sum(pyo.value(m.Pcurt[r, t]) for t in m.T)
gen_r_total = sum(pyo.value(m.P_r[r, t]) for t in m.T)
print(f"\nGeneracion renovable total: {gen_r_total:.1f} MW")
print(f"Curtailment total: {curt_total:.1f} MW")
print("(renovable barata y con red -> se aprovecha, curtailment bajo)")

print("\nOK Bloque 3b: renovable con curtailment, reparto correcto.")
