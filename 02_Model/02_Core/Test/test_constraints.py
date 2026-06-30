# -*- coding: utf-8 -*-
"""
Test del Bloque 1 de constraints.py: arma el W&W completo y RESUELVE
el DC-OPF por primera vez. Valida que la solucion es coherente:
- el modelo resuelve a optimo,
- la demanda total se cubre,
- el generador mas barato (G2) despacha,
- los flujos respetan limites.
"""

import openpyxl
import pyomo.environ as pyo
import sets
import parameters as par
import variables as var
import objective as obj
import constraints as con


def build_data_www(n_horas=1):
    wb = openpyxl.load_workbook("/mnt/user-data/uploads/Case_IEEE6.xlsx",
                                data_only=True)

    def hoja(ws):
        f = list(ws.iter_rows(values_only=True)); return f[0], f[1:]

    class D: pass
    d = D(); d.mva_base = 100; d.n_horas = n_horas
    d.n_seg_costo = 3; d.n_seg_perdidas = 3

    # buses + slack (type==3)
    hdr, fl = hoja(wb["Buses"]); c = {n: i for i, n in enumerate(hdr)}
    d.nodos = []; pd_ = {}; d.nodo_slack = None
    for f in fl:
        nid = f"b{f[c['bus_i']]}"; d.nodos.append(nid); pd_[nid] = f[c["Pd_MW"]]
        if f[c["type"]] == 3:
            d.nodo_slack = nid

    # lineas + from/to
    hdr, fl = hoja(wb["Lineas"]); c = {n: i for i, n in enumerate(hdr)}
    d.lineas = []; d.susceptancia = {}; d.conductancia = {}; d.flow_max = {}
    d.linea_from = {}; d.linea_to = {}
    for k, f in enumerate(fl, 1):
        lid = f"l{k}"; r = f[c["r_pu"]]; x = f[c["x_pu"]]
        d.lineas.append(lid); d.susceptancia[lid] = 1/x
        d.conductancia[lid] = r/(r**2+x**2); d.flow_max[lid] = f[c["rateA_MW"]]
        d.linea_from[lid] = f"b{f[c['from_bus']]}"
        d.linea_to[lid] = f"b{f[c['to_bus']]}"

    # generadores + en que nodo estan
    hdr, fl = hoja(wb["Generadores"]); c = {n: i for i, n in enumerate(hdr)}
    d.gen_termica = []; d.pmin_term = {}; d.pmax_term = {}
    d.ramp_up = {}; d.ramp_down = {}; orden = []; d.gen_en_nodo = {}
    for k, f in enumerate(fl, 1):
        gid = f"G{k}"; d.gen_termica.append(gid); orden.append(gid)
        d.pmin_term[gid] = f[c["Pmin_MW"]]; d.pmax_term[gid] = f[c["Pmax_MW"]]
        d.ramp_up[gid] = f[c["rango_MW"]]; d.ramp_down[gid] = f[c["rango_MW"]]
        nodo = f"b{f[c['bus']]}"
        d.gen_en_nodo.setdefault(nodo, []).append(gid)

    # costos linealizados
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
    d.hid_en_nodo = {}; d.ren_en_nodo = {}; d.bess_en_nodo = {}
    return d


# --- construir el modelo completo ---
d = build_data_www(n_horas=1)
m = pyo.ConcreteModel()
sets.build_sets(m, d)
par.build_parameters(m, d)
var.build_variables(m, d)
obj.build_objective(m, d)
con.build_constraints(m, d)

print(f"Nodo slack detectado: {m.nodo_ref}")
print(f"Restricciones creadas: balance, flujo_dc, ref_angular, "
      f"flujo_max/min, gen_max")

# --- RESOLVER (primera vez!) ---
solver = pyo.SolverFactory("appsi_highs")
res = solver.solve(m)

term = res.solver.termination_condition
print(f"\n=== RESULTADO ===")
print(f"Condicion de terminacion: {term}")
assert str(term) == "optimal", f"esperaba optimo, obtuve {term}"

# --- validaciones de coherencia fisica ---
gen_total = sum(pyo.value(m.P_g[g, 1]) for g in m.G)
dem_total = sum(pyo.value(m.D[n, 1]) for n in m.N)
print(f"Generacion total : {gen_total:.1f} MW")
print(f"Demanda total    : {dem_total:.1f} MW")
assert abs(gen_total - dem_total) < 1e-3, "gen debe igualar demanda (sin perdidas)"

print(f"\nDespacho por generador:")
for g in m.G:
    print(f"  {g}: {pyo.value(m.P_g[g,1]):.1f} MW  (Pmax={pyo.value(m.Pmax[g]):.0f})")

# G2 es el mas barato (slope inicial 11.33) -> deberia despachar
assert pyo.value(m.P_g["G2", 1]) > 0, "G2 (mas barato) deberia despachar"

print(f"\nFlujos de linea (deben respetar |f| <= Fmax):")
viol = 0
for l in m.L:
    f = pyo.value(m.f[l, 1]); fmax = pyo.value(m.flow_max[l])
    if abs(f) > fmax + 1e-3: viol += 1
    print(f"  {l}: {f:7.2f} MW  (limite +/-{fmax:.0f})")
assert viol == 0, "ningun flujo debe exceder su limite"

print(f"\nAngulo del slack {m.nodo_ref}: {pyo.value(m.theta[m.nodo_ref,1]):.4f} (debe ser 0)")
assert abs(pyo.value(m.theta[m.nodo_ref, 1])) < 1e-6

print(f"\nCosto total (objetivo): {pyo.value(m.obj):.2f} USD")
print("\nOK: el modelo RESUELVE y la solucion es fisicamente coherente.")
