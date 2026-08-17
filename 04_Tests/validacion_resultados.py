# -*- coding: utf-8 -*-
"""
validacion.py -- Verificacion y validacion del modelo MILP
==========================================================

Este modulo NO resuelve nada: toma un modelo Pyomo YA RESUELTO y
comprueba que sus resultados sean fisicamente consistentes.

Se organiza en tres capas (ver Seccion de metodologia de la tesis):

  Capa 2 -- Prueba analitica exacta
            (demanda plana -> costo debe ser 24x el de 1 hora)
  Capa 3 -- Consistencia interna
            (balance, SoC, rampas, limites, UC...)  <-- el grueso
  Capa 4 -- Comportamiento esperado
            (monotonia de costos entre escenarios)

USO TIPICO
----------
    import main
    from validacion import verificar

    modelo, salida = main.ejecutar("caso_ieee14_24h.xlsx", solver="highs")
    verificar(modelo)          # imprime el informe y devuelve un dict

DISEÑO DEFENSIVO
----------------
El script no sabe de antemano como se llaman TODOS los componentes de
tu modelo (los nombres pueden cambiar entre versiones). Por eso cada
chequeo busca el componente entre varios nombres posibles y, si no lo
encuentra, se SALTA el chequeo e informa "OMITIDO" en vez de romperse.
Asi nunca te deja sin informe por un nombre distinto.
"""

import pyomo.environ as pyo


# ---------------------------------------------------------------
# Utilidades internas
# ---------------------------------------------------------------

TOL = 1e-5          # tolerancia numerica general (MW, p.u.)
TOL_BIN = 1e-6      # tolerancia para binarias


def _buscar(modelo, *nombres):
    """
    Devuelve el primer componente del modelo cuyo nombre coincida con
    alguno de los candidatos, o None si ninguno existe.

    Ejemplo: _buscar(m, "Pmax_g", "Pmax", "pmax_term")
    """
    for n in nombres:
        if hasattr(modelo, n):
            return getattr(modelo, n)
    return None


def _val(x):
    """Lee el valor numerico de una variable/parametro Pyomo."""
    try:
        v = pyo.value(x)
        return 0.0 if v is None else float(v)
    except Exception:
        return 0.0


def _lista(conjunto):
    """Convierte un Set de Pyomo en lista (o lista vacia si no existe)."""
    return list(conjunto) if conjunto is not None else []


class _Informe:
    """Acumula el resultado de cada chequeo y lo imprime ordenado."""

    def __init__(self):
        self.filas = []      # (nombre, estado, detalle)
        self.fallos = 0

    def ok(self, nombre, detalle=""):
        self.filas.append((nombre, "OK", detalle))

    def fallo(self, nombre, detalle=""):
        self.filas.append((nombre, "FALLA", detalle))
        self.fallos += 1

    def omitido(self, nombre, motivo):
        self.filas.append((nombre, "OMITIDO", motivo))

    def registrar(self, nombre, peor, umbral=TOL, unidad=""):
        """Registra OK/FALLA comparando la peor violacion contra el umbral."""
        if peor <= umbral:
            self.ok(nombre, f"peor desviacion: {peor:.2e} {unidad}".strip())
        else:
            self.fallo(nombre, f"peor desviacion: {peor:.4f} {unidad}".strip())

    def imprimir(self):
        print()
        print("=" * 72)
        print("  INFORME DE VERIFICACION DEL MODELO")
        print("=" * 72)
        for nombre, estado, detalle in self.filas:
            marca = {"OK": "  [OK]   ", "FALLA": "  [FALLA]",
                     "OMITIDO": "  [--]   "}[estado]
            print(f"{marca} {nombre:<42} {detalle}")
        print("-" * 72)
        if self.fallos == 0:
            print("  RESULTADO: todos los chequeos ejecutados pasaron.")
        else:
            print(f"  RESULTADO: {self.fallos} chequeo(s) FALLARON. Revisar arriba.")
        print("=" * 72)
        print()


# ===============================================================
# CAPA 3 -- CONSISTENCIA INTERNA
# ===============================================================

def verificar(modelo, verbose=True):
    """
    Ejecuta todos los chequeos de consistencia sobre un modelo resuelto.

    Devuelve un dict {nombre_chequeo: "OK"|"FALLA"|"OMITIDO"}.
    """
    inf = _Informe()

    T = _lista(_buscar(modelo, "T"))
    N = _lista(_buscar(modelo, "N"))
    G = _lista(_buscar(modelo, "G"))
    L = _lista(_buscar(modelo, "L_ALL", "L"))
    S = _lista(_buscar(modelo, "S"))

    if not T:
        print("ERROR: no se encontro el conjunto de tiempos 'T'.")
        return {}

    _chk_balance(modelo, inf, T)
    _chk_perdidas_positivas(modelo, inf, L, T)
    _chk_limites_flujo(modelo, inf, L, T)
    _chk_angulo_referencia(modelo, inf, T)
    _chk_limites_generacion(modelo, inf, G, T)
    _chk_rampas(modelo, inf, G, T)
    _chk_unit_commitment(modelo, inf, G, T)
    _chk_soc_continuidad(modelo, inf, S, T)
    _chk_soc_ciclico(modelo, inf, S, T)
    _chk_no_simultaneo(modelo, inf, S, T)

    if verbose:
        inf.imprimir()

    return {n: e for n, e, _ in inf.filas}


def _chk_balance(modelo, inf, T):
    """Balance global por hora: generacion = demanda + perdidas."""
    nombre = "Balance energetico por hora"
    P_g = _buscar(modelo, "P_g")
    D = _buscar(modelo, "D", "demanda", "Dem")
    Ploss = _buscar(modelo, "Ploss")
    if P_g is None or D is None:
        inf.omitido(nombre, "no se hallo P_g o la demanda")
        return

    P_h = _buscar(modelo, "P_h")
    P_r = _buscar(modelo, "P_r")
    Pch = _buscar(modelo, "Pch", "P_ch")
    Pdis = _buscar(modelo, "Pdis", "P_dis")
    Pcurt = _buscar(modelo, "Pcurt", "P_curt")

    G = _lista(_buscar(modelo, "G"))
    H = _lista(_buscar(modelo, "H"))
    R = _lista(_buscar(modelo, "R"))
    S = _lista(_buscar(modelo, "S"))
    N = _lista(_buscar(modelo, "N"))
    L = _lista(_buscar(modelo, "L_ALL", "L"))

    peor = 0.0
    for t in T:
        oferta = sum(_val(P_g[g, t]) for g in G)
        if P_h is not None:
            oferta += sum(_val(P_h[h, t]) for h in H)
        if P_r is not None:
            oferta += sum(_val(P_r[r, t]) for r in R)
        if Pdis is not None:
            oferta += sum(_val(Pdis[s, t]) for s in S)
        if Pch is not None:
            oferta -= sum(_val(Pch[s, t]) for s in S)
        if Pcurt is not None:
            # el vertimiento reduce la inyeccion renovable efectiva
            try:
                oferta -= sum(_val(Pcurt[r, t]) for r in R)
            except Exception:
                pass

        dem = sum(_val(D[n, t]) for n in N)
        perd = sum(_val(Ploss[l, t]) for l in L) if Ploss is not None else 0.0

        peor = max(peor, abs(oferta - (dem + perd)))

    inf.registrar(nombre, peor, umbral=1e-3, unidad="MW")


def _chk_perdidas_positivas(modelo, inf, L, T):
    nombre = "Perdidas no negativas"
    Ploss = _buscar(modelo, "Ploss")
    if Ploss is None:
        inf.omitido(nombre, "el modelo no incluye perdidas")
        return
    peor = 0.0
    for l in L:
        for t in T:
            peor = max(peor, -_val(Ploss[l, t]))
    inf.registrar(nombre, peor, unidad="MW")


def _chk_limites_flujo(modelo, inf, L, T):
    nombre = "Limites de flujo por linea"
    f = _buscar(modelo, "f", "flujo")
    cap = _buscar(modelo, "cap_l", "cap", "Fmax", "F_max")
    if f is None or cap is None:
        inf.omitido(nombre, "no se hallo el flujo o la capacidad")
        return
    peor = 0.0
    for l in L:
        for t in T:
            try:
                lim = _val(cap[l])
            except Exception:
                continue
            exceso = abs(_val(f[l, t])) - lim
            peor = max(peor, exceso)
    inf.registrar(nombre, peor, umbral=1e-4, unidad="MW")


def _chk_angulo_referencia(modelo, inf, T):
    nombre = "Angulo de referencia = 0"
    theta = _buscar(modelo, "theta", "th")
    if theta is None:
        inf.omitido(nombre, "no se hallo la variable theta")
        return
    ref = _buscar(modelo, "nodo_ref", "slack", "ref")
    peor = 0.0
    encontrado = False
    for t in T:
        for idx in theta:
            # idx puede ser (n, t) -- buscamos el nodo de referencia
            if not isinstance(idx, tuple) or idx[1] != t:
                continue
            n = idx[0]
            es_ref = False
            if ref is not None:
                try:
                    es_ref = (n == _val(ref)) or (n == ref.value)
                except Exception:
                    es_ref = False
            if es_ref:
                encontrado = True
                peor = max(peor, abs(_val(theta[idx])))
    if not encontrado:
        # fallback: al menos un nodo debe tener theta=0 en toda hora
        for t in T:
            ceros = [abs(_val(theta[idx])) < TOL
                     for idx in theta
                     if isinstance(idx, tuple) and idx[1] == t]
            if not any(ceros):
                inf.fallo(nombre, f"ningun nodo con theta=0 en t={t}")
                return
        inf.ok(nombre, "hay un nodo con theta=0 en todas las horas")
        return
    inf.registrar(nombre, peor, unidad="rad")


def _chk_limites_generacion(modelo, inf, G, T):
    nombre = "Pmin*u <= P_g <= Pmax*u"
    P_g = _buscar(modelo, "P_g")
    u = _buscar(modelo, "u")
    pmin = _buscar(modelo, "Pmin_g", "Pmin", "pmin_term")
    pmax = _buscar(modelo, "Pmax_g", "Pmax", "pmax_term")
    if P_g is None or pmin is None or pmax is None:
        inf.omitido(nombre, "no se hallo P_g / Pmin / Pmax")
        return
    peor = 0.0
    for g in G:
        for t in T:
            p = _val(P_g[g, t])
            uu = _val(u[g, t]) if u is not None else 1.0
            lo = _val(pmin[g]) * uu
            hi = _val(pmax[g]) * uu
            peor = max(peor, lo - p, p - hi)
    inf.registrar(nombre, peor, umbral=1e-4, unidad="MW")


def _chk_rampas(modelo, inf, G, T):
    nombre = "Rampas de subida / bajada"
    P_g = _buscar(modelo, "P_g")
    r_up = _buscar(modelo, "R_up", "rampa_up", "Rup", "ramp_up")
    r_dn = _buscar(modelo, "R_down", "rampa_down", "Rdn", "ramp_down")
    if P_g is None or (r_up is None and r_dn is None):
        inf.omitido(nombre, "el modelo no define rampas")
        return
    # margen extra: al arrancar/parar se permite saltar hasta Pmin
    pmin = _buscar(modelo, "Pmin_g", "Pmin", "pmin_term")
    peor = 0.0
    Tl = list(T)
    for g in G:
        for i in range(1, len(Tl)):
            t, tprev = Tl[i], Tl[i - 1]
            delta = _val(P_g[g, t]) - _val(P_g[g, tprev])
            margen = _val(pmin[g]) if pmin is not None else 0.0
            if delta > 0 and r_up is not None:
                peor = max(peor, delta - _val(r_up[g]) - margen)
            elif delta < 0 and r_dn is not None:
                peor = max(peor, -delta - _val(r_dn[g]) - margen)
    inf.registrar(nombre, peor, umbral=1e-4, unidad="MW")


def _chk_unit_commitment(modelo, inf, G, T):
    nombre = "Coherencia UC (u, SU, SD)"
    u = _buscar(modelo, "u")
    SU = _buscar(modelo, "SU")
    SD = _buscar(modelo, "SD")
    if u is None or SU is None or SD is None:
        inf.omitido(nombre, "el modelo no define u / SU / SD")
        return
    peor = 0.0
    Tl = list(T)
    for g in G:
        for i in range(1, len(Tl)):
            t, tprev = Tl[i], Tl[i - 1]
            izq = _val(u[g, t]) - _val(u[g, tprev])
            der = _val(SU[g, t]) - _val(SD[g, t])
            peor = max(peor, abs(izq - der))
            # no se puede arrancar y parar en la misma hora
            peor = max(peor, _val(SU[g, t]) + _val(SD[g, t]) - 1.0)
    inf.registrar(nombre, peor, umbral=1e-4)


def _chk_soc_continuidad(modelo, inf, S, T):
    nombre = "Continuidad del SoC"
    SoC = _buscar(modelo, "SoC", "soc", "E_s")
    Pch = _buscar(modelo, "Pch", "P_ch")
    Pdis = _buscar(modelo, "Pdis", "P_dis")
    if SoC is None or Pch is None or Pdis is None:
        inf.omitido(nombre, "el modelo no incluye BESS")
        return
    if not S:
        inf.omitido(nombre, "no hay candidatos BESS en este caso")
        return
    eta_c = _buscar(modelo, "eta_ch", "eficiencia_carga")
    eta_d = _buscar(modelo, "eta_dis", "eficiencia_descarga")
    peor = 0.0
    Tl = list(T)
    for s in S:
        for i in range(1, len(Tl)):
            t, tprev = Tl[i], Tl[i - 1]
            ec = _val(eta_c[s]) if eta_c is not None else 1.0
            ed = _val(eta_d[s]) if eta_d is not None else 1.0
            ed = ed if ed != 0 else 1.0
            esperado = (_val(SoC[s, tprev])
                        + ec * _val(Pch[s, t])
                        - _val(Pdis[s, t]) / ed)
            peor = max(peor, abs(_val(SoC[s, t]) - esperado))
    inf.registrar(nombre, peor, umbral=1e-3, unidad="MWh")


def _chk_soc_ciclico(modelo, inf, S, T):
    nombre = "SoC final = SoC inicial"
    SoC = _buscar(modelo, "SoC", "soc", "E_s")
    if SoC is None or not S:
        inf.omitido(nombre, "el modelo no incluye BESS")
        return
    Tl = list(T)
    peor = 0.0
    for s in S:
        peor = max(peor, abs(_val(SoC[s, Tl[-1]]) - _val(SoC[s, Tl[0]])))
    inf.registrar(nombre, peor, umbral=1e-2, unidad="MWh")


def _chk_no_simultaneo(modelo, inf, S, T):
    nombre = "No carga y descarga simultanea"
    Pch = _buscar(modelo, "Pch", "P_ch")
    Pdis = _buscar(modelo, "Pdis", "P_dis")
    if Pch is None or Pdis is None or not S:
        inf.omitido(nombre, "el modelo no incluye BESS")
        return
    peor = 0.0
    for s in S:
        for t in T:
            c, d = _val(Pch[s, t]), _val(Pdis[s, t])
            if c > TOL and d > TOL:
                peor = max(peor, min(c, d))
    inf.registrar(nombre, peor, umbral=1e-4, unidad="MW")


# ===============================================================
# CAPA 2 -- PRUEBA ANALITICA EXACTA (demanda plana -> 24x)
# ===============================================================

def prueba_escalado_temporal(ruta_caso_1h, ruta_caso_plano, ejecutar_fn,
                             n_horas=24, tolerancia_pct=0.01, **kwargs):
    """
    Compara el costo de un caso de 1 hora contra el mismo caso con
    demanda PLANA de n_horas. Si la dimension temporal esta bien
    implementada, el costo debe ser exactamente n_horas veces mayor.

    IMPORTANTE: ambos casos deben estar SIN BESS, SIN FACTS y con
    rampas holgadas (o desactivadas). Si hay acoplamiento temporal,
    la relacion exacta de n_horas ya no aplica.

    ejecutar_fn : normalmente main.ejecutar
    """
    m1, _ = ejecutar_fn(ruta_caso_1h, **kwargs)
    mN, _ = ejecutar_fn(ruta_caso_plano, **kwargs)

    c1 = _val(m1.obj) if hasattr(m1, "obj") else _costo_objetivo(m1)
    cN = _val(mN.obj) if hasattr(mN, "obj") else _costo_objetivo(mN)

    esperado = c1 * n_horas
    error_pct = abs(cN - esperado) / esperado * 100 if esperado else float("inf")

    print()
    print("=" * 72)
    print("  CAPA 2 -- PRUEBA DE ESCALADO TEMPORAL")
    print("=" * 72)
    print(f"  Costo con 1 hora           : {c1:14,.2f}")
    print(f"  Costo esperado ({n_horas}h = {n_horas}x): {esperado:14,.2f}")
    print(f"  Costo obtenido ({n_horas}h)      : {cN:14,.2f}")
    print(f"  Error                      : {error_pct:14.4f} %")
    print("-" * 72)
    if error_pct <= tolerancia_pct:
        print("  RESULTADO: OK -- la dimension temporal escala correctamente.")
    else:
        print("  RESULTADO: FALLA -- revisar indices 't', doble conteo o")
        print("             acoplamientos temporales no esperados.")
    print("=" * 72)
    print()
    return {"costo_1h": c1, "costo_Nh": cN, "error_pct": error_pct}


def _costo_objetivo(modelo):
    """Busca el objetivo activo del modelo y devuelve su valor."""
    for obj in modelo.component_objects(pyo.Objective, active=True):
        return _val(obj)
    return 0.0


# ===============================================================
# CAPA 4 -- COMPORTAMIENTO ESPERADO (monotonia entre escenarios)
# ===============================================================

def prueba_monotonia(costos):
    """
    Verifica que agregar opciones de flexibilidad nunca empeore el optimo.

    costos : dict con las claves "E0", "E1", "E2", "E3"
             E0 = base, E1 = solo BESS, E2 = solo FACTS, E3 = ambos

    Como BESS y FACTS son OPCIONALES (el modelo puede no instalarlos),
    el costo nunca puede subir al habilitarlos. Si sube, hay un error
    de formulacion garantizado.
    """
    reglas = [
        ("E1 <= E0", "E1", "E0"),
        ("E2 <= E0", "E2", "E0"),
        ("E3 <= E1", "E3", "E1"),
        ("E3 <= E2", "E3", "E2"),
    ]
    print()
    print("=" * 72)
    print("  CAPA 4 -- MONOTONIA DE COSTOS ENTRE ESCENARIOS")
    print("=" * 72)
    fallos = 0
    for etiqueta, a, b in reglas:
        if a not in costos or b not in costos:
            print(f"  [--]    {etiqueta:<12} (falta {a} o {b})")
            continue
        ca, cb = costos[a], costos[b]
        if ca <= cb + 1e-6:
            ahorro = (cb - ca) / cb * 100 if cb else 0.0
            print(f"  [OK]    {etiqueta:<12} {ca:12,.2f} <= {cb:12,.2f}"
                  f"   (ahorro {ahorro:5.2f} %)")
        else:
            fallos += 1
            print(f"  [FALLA] {etiqueta:<12} {ca:12,.2f} >  {cb:12,.2f}"
                  f"   <-- IMPOSIBLE, revisar formulacion")
    print("-" * 72)
    print("  RESULTADO: OK." if fallos == 0
          else f"  RESULTADO: {fallos} violacion(es) de monotonia.")
    print("=" * 72)
    print()
    return fallos == 0


# ===============================================================
# CLI
# ===============================================================

if __name__ == "__main__":
    import argparse
    import main   # tu modulo principal

    ap = argparse.ArgumentParser(
        description="Verifica la consistencia de un caso ya resuelto.")
    ap.add_argument("caso", help="ruta al Excel del caso")
    ap.add_argument("--solver", default="highs")
    args = ap.parse_args()

    modelo, salida = main.ejecutar(args.caso, solver=args.solver,
                                   verbose=False)
    verificar(modelo)
