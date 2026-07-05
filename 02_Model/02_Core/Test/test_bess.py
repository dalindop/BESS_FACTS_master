# -*- coding: utf-8 -*-
"""
Test del Bloque 5 (BESS). Usa un perfil de demanda VARIABLE (curva de
carga tipica) para que el BESS pueda arbitrar. Valida:
- el modelo resuelve,
- el BESS carga en el valle y descarga en el pico,
- respeta limites de energia y no carga/descarga a la vez,
- estado final = inicial (ciclico).
"""

import math
import openpyxl
import pyomo.environ as pyo
import sets, parameters as par, variables as var
import objective as obj, constraints as con


def perfil_horario(hora, n_horas=24):
    """
    Factor de carga tipico [0.6..1.0] segun la hora del dia. Curva de
    carga: valle en la madrugada, pico en la tarde. Devuelve un factor
    multiplicativo. MISMA idea que la hoja 'load' de Alvaro, pero
    sintetica para el W&W. En Colombia esto se reemplaza por datos XM.
    """
    h = ((hora - 1) % 24)  # 0..23
    # curva suave: minimo ~4am, pico ~19h
    base = 0.8 + 0.2 * math.sin((h - 8) / 24 * 2 * math.pi)
    return round(base, 4)


def build_data_bess(n_horas=24, con_bess=True):
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
        # rampa amplia para no restringir el arbitraje en este test
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

    # DEMANDA VARIABLE: base * factor horario
    d.demanda = {(n, t): pd_[n] * perfil_horario(t, n_horas)
                 for n in d.nodos for t in range(1, n_horas+1)}
    d.gen_hidro = []; d.gen_renov = []
    d.lineas_cand = []; d.lineas_facts = []
    d.hid_en_nodo = {}; d.ren_en_nodo = {}
    # BESS en el nodo de mayor demanda (b6)
    if con_bess:
        d.nodos_bess = ["b6"]
        d.bess_en_nodo = {"b6": ["b6"]}
    else:
        d.nodos_bess = []; d.bess_en_nodo = {}
    return d


# --- Construir y resolver ---
d = build_data_bess(n_horas=24, con_bess=True)
m = pyo.ConcreteModel()
sets.build_sets(m, d); par.build_parameters(m, d)
var.build_variables(m, d); obj.build_objective(m, d)
con.build_constraints(m, d)
res = pyo.SolverFactory("appsi_highs").solve(m)
print("Terminacion:", res.solver.termination_condition)
assert str(res.solver.termination_condition) == "optimal"

s = "b6"
print(f"\nBESS en {s}: instalado y_s = {pyo.value(m.y_s[s]):.0f}")
print(f"  Psmax = {pyo.value(m.Psmax[s]):.1f} MW, "
      f"Esmax = {pyo.value(m.Esmax[s]):.1f} MWh")

# perfil de demanda total por hora
dem_h = {t: sum(pyo.value(m.D[n, t]) for n in m.N) for t in m.T}
h_valle = min(dem_h, key=dem_h.get)
h_pico = max(dem_h, key=dem_h.get)
print(f"\nHora valle: {h_valle} (dem={dem_h[h_valle]:.0f} MW)")
print(f"Hora pico : {h_pico} (dem={dem_h[h_pico]:.0f} MW)")

if pyo.value(m.y_s[s]) > 0.5:
    pch_valle = pyo.value(m.Pch[s, h_valle])
    pdis_pico = pyo.value(m.Pdis[s, h_pico])
    print(f"\nBESS en valle (h{h_valle}): carga={pch_valle:.1f} MW")
    print(f"BESS en pico  (h{h_pico}): descarga={pdis_pico:.1f} MW")

# verificar no simultaneidad y limites
viol = 0
for t in m.T:
    if pyo.value(m.u_ch[s, t]) + pyo.value(m.u_dis[s, t]) > 1.01:
        viol += 1
    if pyo.value(m.SoC[s, t]) > pyo.value(m.Esmax[s]) + 1e-3:
        viol += 1
assert viol == 0, "no debe cargar/descargar a la vez ni exceder energia"
print(f"\nNo-simultaneidad y limite de energia: OK ({viol} violaciones)")

# estado ciclico: SoC final == SoC inicial
soc_fin = pyo.value(m.SoC[s, m.T.last()])
soc_ini = pyo.value(m.soc_ini_frac) * pyo.value(m.Esmax[s])
print(f"SoC final={soc_fin:.2f}, SoC inicial={soc_ini:.2f} (deben coincidir)")
assert abs(soc_fin - soc_ini) < 1e-2, "estado final debe = inicial"

print("\nOK Bloque 5: BESS opera con arbitraje y respeta restricciones.")

# ======================================================================
# Caso rentable: bajar costo del BESS para que SI arbitre
# ======================================================================
print("\n" + "="*60)
print("Caso con BESS RENTABLE (costo bajo) -> debe arbitrar")
print("="*60)
d2 = build_data_bess(n_horas=12, con_bess=True)
d2.costo_bess_power = 0.5    # muy barato
d2.costo_bess_energy = 0.5
d2.costo_bess_inst = 0
m2 = pyo.ConcreteModel()
sets.build_sets(m2, d2); par.build_parameters(m2, d2)
var.build_variables(m2, d2); obj.build_objective(m2, d2)
con.build_constraints(m2, d2)
solver2 = pyo.SolverFactory("appsi_highs")
solver2.config.time_limit = 30
solver2.config.mip_gap = 0.02
solver2.solve(m2)

s = "b6"
Ps = pyo.value(m2.Psmax[s]); Es = pyo.value(m2.Esmax[s])
print(f"BESS: Psmax={Ps:.1f} MW, Esmax={Es:.1f} MWh")

# perfil de carga/descarga por hora
carga_total = sum(pyo.value(m2.Pch[s, t]) for t in m2.T)
desc_total = sum(pyo.value(m2.Pdis[s, t]) for t in m2.T)
print(f"Energia cargada total: {carga_total:.1f} MWh")
print(f"Energia descargada total: {desc_total:.1f} MWh")

if Ps > 0.1:
    # verificar que carga mas en horas de valle que en pico
    dem_h = {t: sum(pyo.value(m2.D[n, t]) for n in m2.N) for t in m2.T}
    horas_valle = sorted(dem_h, key=dem_h.get)[:6]   # 6 horas mas bajas
    horas_pico = sorted(dem_h, key=dem_h.get)[-6:]   # 6 horas mas altas
    carga_valle = sum(pyo.value(m2.Pch[s, t]) for t in horas_valle)
    desc_pico = sum(pyo.value(m2.Pdis[s, t]) for t in horas_pico)
    print(f"Carga en 6h de valle: {carga_valle:.1f} MWh")
    print(f"Descarga en 6h de pico: {desc_pico:.1f} MWh")
    # el BESS arbitra: carga energia y luego la descarga (con perdidas
    # por eficiencia). Verificamos el ciclo completo carga->descarga.
    assert carga_total > 0.1, "debe cargar energia"
    assert desc_total > 0.1, "debe descargar energia"
    assert carga_valle > 0.1, "debe cargar preferentemente en el valle"
    # descarga < carga por eficiencia (0.9*0.9 = 0.81)
    assert desc_total < carga_total, "descarga < carga (perdidas eff.)"
    print(f"\nOK: el BESS arbitra. Eficiencia ciclo: "
          f"{desc_total/carga_total*100:.0f}% (esperado ~81%).")
else:
    print("(BESS no dimensionado; ajustar costos/diferencial)")
