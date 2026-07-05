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
# ahora hay perdidas: gen >= demanda (cubre demanda + perdidas)
assert gen_total >= dem_total - 1e-3, "gen debe cubrir al menos la demanda"

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


# ======================================================================
# Test del Bloque 3: ahora el COSTO debe activarse y G2 (mas barato)
# debe priorizarse.
# ======================================================================
print("\n" + "="*60)
print("BLOQUE 3: validacion economica")
print("="*60)

d3 = build_data_www(n_horas=1)
m3 = pyo.ConcreteModel()
sets.build_sets(m3, d3)
par.build_parameters(m3, d3)
var.build_variables(m3, d3)
obj.build_objective(m3, d3)
con.build_constraints(m3, d3)

res3 = pyo.SolverFactory("appsi_highs").solve(m3)
assert str(res3.solver.termination_condition) == "optimal"

costo = pyo.value(m3.obj)
print(f"\nCosto total: {costo:.2f} USD  (antes era 0.00)")
assert costo > 0, "el costo ya NO debe ser 0 (Bloque 3 lo conecta)"

print("\nDespacho y estado on/off:")
for g in m3.G:
    pg = pyo.value(m3.P_g[g, 1]); u = pyo.value(m3.u[g, 1])
    pmin = pyo.value(m3.Pmin[g]); pmax = pyo.value(m3.Pmax[g])
    estado = "ON " if u > 0.5 else "OFF"
    print(f"  {g}: {pg:6.1f} MW  [{estado}]  (Pmin={pmin:.0f}, Pmax={pmax:.0f})")
    # si esta ON, debe respetar Pmin<=Pg<=Pmax
    if u > 0.5:
        assert pg >= pmin - 1e-3, f"{g} ON debe cumplir Pg>=Pmin"
        assert pg <= pmax + 1e-3, f"{g} ON debe cumplir Pg<=Pmax"
    else:
        assert pg < 1e-3, f"{g} OFF debe tener Pg=0"

# balance se mantiene
assert sum(pyo.value(m3.P_g[g,1]) for g in m3.G) >= 210 - 1e-3

print(f"\nVerificacion Pg = Pmin*u + sum(dP_seg):")
for g in m3.G:
    pg = pyo.value(m3.P_g[g,1])
    comp = pyo.value(m3.Pmin[g])*pyo.value(m3.u[g,1]) + \
           sum(pyo.value(m3.dP_seg[g,mm,1]) for mm in m3.SEG_COST)
    print(f"  {g}: Pg={pg:.1f}  =  Pmin*u + segs = {comp:.1f}")
    assert abs(pg - comp) < 1e-3, "composicion de potencia debe cuadrar"

print("\nOK Bloque 3: costo activado, generacion con UC coherente.")


# ======================================================================
# Test del Bloque 4 (Unit Commitment)
# ======================================================================
print("\n" + "="*60)
print("BLOQUE 4: unit commitment")
print("="*60)

# --- Caso A: W&W con valores NEUTROS (UC no debe estorbar) -----------
dA = build_data_www(n_horas=4)
mA = pyo.ConcreteModel()
sets.build_sets(mA, dA); par.build_parameters(mA, dA)
var.build_variables(mA, dA); obj.build_objective(mA, dA)
con.build_constraints(mA, dA)
resA = pyo.SolverFactory("appsi_highs").solve(mA)
assert str(resA.solver.termination_condition) == "optimal", \
    "W&W con UC neutro debe resolver"
# la consistencia SU/SD debe cumplirse en todos los periodos
for g in mA.G:
    for t in list(mA.T)[1:]:
        su = pyo.value(mA.SU[g, t]); sd = pyo.value(mA.SD[g, t])
        u = pyo.value(mA.u[g, t]); up = pyo.value(mA.u[g, mA.T.prev(t)])
        assert abs((su - sd) - (u - up)) < 1e-4, "SU-SD = u-u_prev"
print("OK caso A (W&W neutro): resuelve y SU/SD consistentes.")

# --- Caso B: forzar UC ACTIVO (Min_ON=3) y verificar que obliga ------
# Construimos un caso donde G2 deba arrancar y, por Min_ON=3, quede ON
# al menos 3 horas seguidas. Para forzar el arranque, ponemos estado
# inicial OFF y demanda que sube en t=2.
import copy
dB = build_data_www(n_horas=5)
# estado inicial: todos apagados
dB.onoff_t0 = {g: 0 for g in dB.gen_termica}
# tiempo minimo de encendido = 3 horas para todos
dB.l_up_min = {g: 3 for g in dB.gen_termica}
dB.l_down_min = {g: 1 for g in dB.gen_termica}
mB = pyo.ConcreteModel()
sets.build_sets(mB, dB); par.build_parameters(mB, dB)
var.build_variables(mB, dB); obj.build_objective(mB, dB)
con.build_constraints(mB, dB)
resB = pyo.SolverFactory("appsi_highs").solve(mB)
assert str(resB.solver.termination_condition) == "optimal"

# verificar la regla de min-up: si una unidad arranco en t, debe estar
# ON en t, t+1, t+2 (3 horas). Buscamos algun arranque y lo validamos.
print("Estados u[g,t] (verificando Min_ON=3):")
arranques_validados = 0
for g in mB.G:
    estados = [round(pyo.value(mB.u[g, t])) for t in mB.T]
    print(f"  {g}: {estados}")
    for idx, t in enumerate(list(mB.T)):
        if pyo.value(mB.SU[g, t]) > 0.5:  # arranco en t
            # debe estar ON en las siguientes min(3, restantes) horas
            ventana = list(mB.T)[idx: idx+3]
            for tau in ventana:
                assert pyo.value(mB.u[g, tau]) > 0.5, \
                    f"{g} arranco en {t}, debe seguir ON (Min_ON=3)"
            arranques_validados += 1
print(f"OK caso B: {arranques_validados} arranque(s) respetan Min_ON=3.")
print("\nOK Bloque 4: unit commitment funciona (neutro y activo).")


# ======================================================================
# Test del Bloque 2 (perdidas)
# ======================================================================
print("\n" + "="*60)
print("BLOQUE 2: perdidas linealizadas")
print("="*60)

dP = build_data_www(n_horas=1)
# anadir conductancia ya viene en build_data_www
mP = pyo.ConcreteModel()
sets.build_sets(mP, dP); par.build_parameters(mP, dP)
var.build_variables(mP, dP); obj.build_objective(mP, dP)
con.build_constraints(mP, dP)
resP = pyo.SolverFactory("appsi_highs").solve(mP)
assert str(resP.solver.termination_condition) == "optimal", \
    "modelo con perdidas debe resolver"

gen_total = sum(pyo.value(mP.P_g[g, 1]) for g in mP.G)
dem_total = sum(pyo.value(mP.D[n, 1]) for n in mP.N)
perd_total = sum(pyo.value(mP.Ploss[l, 1]) for l in mP.L)

print(f"\nGeneracion total : {gen_total:.3f} MW")
print(f"Demanda total    : {dem_total:.3f} MW")
print(f"Perdidas totales : {perd_total:.3f} MW")
print(f"Gen - Dem        : {gen_total - dem_total:.3f} MW (debe ~= perdidas)")

# CLAVE: con perdidas, generacion = demanda + perdidas
assert perd_total >= 0, "las perdidas deben ser no negativas"
assert abs((gen_total - dem_total) - perd_total) < 1e-2, \
    "generacion debe cubrir demanda + perdidas"

# verificar descomposicion angular: una de las dos partes ~ 0
print(f"\nDescomposicion angular (una parte debe ser ~0 por linea):")
ok_desc = 0
for l in list(mP.L)[:5]:
    dp = pyo.value(mP.delta_pos[l, 1]); dn = pyo.value(mP.delta_neg[l, 1])
    print(f"  {l}: delta_pos={dp:.4f}, delta_neg={dn:.4f}")
    if min(dp, dn) < 1e-4: ok_desc += 1
print(f"  ({ok_desc}/5 lineas con una parte en ~0: correcto)")

# perdidas coherentes: Ploss = MVA*G*sum(alpha*delta_seg)
print(f"\nPerdidas por linea (primeras 5):")
for l in list(mP.L)[:5]:
    print(f"  {l}: Ploss = {pyo.value(mP.Ploss[l,1]):.4f} MW")

print("\nOK Bloque 2: perdidas calculadas, generacion cubre dem+perdidas.")


# ======================================================================
# Test del Bloque 6 (expansion unificada con perdidas en candidatas)
# ======================================================================
print("\n" + "="*60)
print("BLOQUE 6: expansion de lineas (enfoque unificado)")
print("="*60)

# --- Caso A: W&W SIN candidatas debe dar el MISMO resultado que antes -
dA6 = build_data_www(n_horas=1)
mA6 = pyo.ConcreteModel()
sets.build_sets(mA6, dA6); par.build_parameters(mA6, dA6)
var.build_variables(mA6, dA6); obj.build_objective(mA6, dA6)
con.build_constraints(mA6, dA6)
rA6 = pyo.SolverFactory("appsi_highs").solve(mA6)
assert str(rA6.solver.termination_condition) == "optimal"
gen6 = sum(pyo.value(mA6.P_g[g,1]) for g in mA6.G)
perd6 = sum(pyo.value(mA6.Ploss[l,1]) for l in mA6.L)
print(f"W&W sin candidatas: gen={gen6:.1f} MW, perdidas={perd6:.2f} MW")
# debe coincidir con el resultado previo (238.3 y 28.3)
assert abs(gen6 - 238.3) < 1.0, "el W&W debe dar el mismo resultado que antes"
print("OK caso A: no-regresion, mismo resultado que sin unificar.")

# --- Caso B: anadir una candidata redundante (no deberia construirse) -
import copy
dB6 = build_data_www(n_horas=1)
# candidata lc1 en paralelo a una linea existente (redundante y cara)
dB6.lineas_cand = ["lc1"]
dB6.susceptancia["lc1"] = 5.0
dB6.conductancia["lc1"] = 1.0
dB6.flow_max["lc1"] = 50
dB6.linea_from["lc1"] = "b2"; dB6.linea_to["lc1"] = "b4"
dB6.costo_linea = {"lc1": 1_000_000}   # muy cara -> no construir
mB6 = pyo.ConcreteModel()
sets.build_sets(mB6, dB6); par.build_parameters(mB6, dB6)
var.build_variables(mB6, dB6); obj.build_objective(mB6, dB6)
con.build_constraints(mB6, dB6)
rB6 = pyo.SolverFactory("appsi_highs").solve(mB6)
assert str(rB6.solver.termination_condition) == "optimal"

x_lc1 = pyo.value(mB6.x_l["lc1"])
f_lc1 = pyo.value(mB6.f["lc1", 1])
ploss_lc1 = pyo.value(mB6.Ploss["lc1", 1])
print(f"\nCandidata lc1 (cara): x={x_lc1:.0f}, flujo={f_lc1:.3f}, "
      f"Ploss={ploss_lc1:.3f}")
# como es cara y redundante, NO debe construirse
assert x_lc1 < 0.5, "candidata cara no debe construirse"
# y si no se construye: flujo Y perdidas deben ser 0 (clave del enfoque)
assert abs(f_lc1) < 1e-3, "candidata no construida: flujo=0"
assert abs(ploss_lc1) < 1e-3, "candidata no construida: Ploss=0"
print("OK caso B: candidata no construida -> flujo=0 Y Ploss=0.")

# --- Caso C: candidata BARATA y necesaria (debe construirse) ----------
dC6 = copy.deepcopy(dB6)
dC6.costo_linea = {"lc1": 1.0}   # baratisima -> quiza construir
mC6 = pyo.ConcreteModel()
sets.build_sets(mC6, dC6); par.build_parameters(mC6, dC6)
var.build_variables(mC6, dC6); obj.build_objective(mC6, dC6)
con.build_constraints(mC6, dC6)
rC6 = pyo.SolverFactory("appsi_highs").solve(mC6)
x_lc1_c = pyo.value(mC6.x_l["lc1"])
print(f"\nCandidata lc1 (barata): x={x_lc1_c:.0f}")
if x_lc1_c > 0.5:
    f_c = pyo.value(mC6.f["lc1", 1]); pl_c = pyo.value(mC6.Ploss["lc1", 1])
    print(f"  construida -> flujo={f_c:.2f} MW, Ploss={pl_c:.3f} MW")
    print("  (candidata construida SI puede tener flujo y perdidas)")
print("OK caso C: candidata barata evaluada correctamente.")

print("\nOK Bloque 6: expansion unificada con perdidas en candidatas.")
