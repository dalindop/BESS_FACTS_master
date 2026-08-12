# -*- coding: utf-8 -*-
"""
==================================================================
 MAIN
------------------------------------------------------------------
Autor : Daniel Lindo -- Universidad Nacional de Colombia (UNAL)
Tesis : Maestria en Ingenieria Electrica, 2026
------------------------------------------------------------------

Orquesta el flujo completo de principio a fin:
    1. CARGA los datos del caso   (data_loader)
    2. CONSTRUYE el modelo        (model_builder)
    3. RESUELVE con el solver     (solver_runner)
    4. Muestra un RESUMEN de la solucion.

Uso desde la terminal:
    python main.py                          (usa caso_WW.xlsx, HiGHS)
    python main.py caso_Colombia.xlsx
    python main.py caso_WW.xlsx --solver glpk
    python main.py caso_WW.xlsx --solver gurobi --horas 24
==================================================================
"""

# Cronometro GLOBAL: primera linea ejecutable, antes de cualquier import.
import time as _time
_T_ARRANQUE = _time.perf_counter()

import argparse
import os
import sys
from datetime import datetime

# ------------------------------------------------------------------
# Registrar las subcarpetas del proyecto en el path de Python. Como
# main.py esta en la RAIZ del repositorio, las carpetas de codigo
# cuelgan de 02_Model/. _BASE es la carpeta de este archivo (la raiz).
# ------------------------------------------------------------------
_BASE = os.path.dirname(os.path.abspath(__file__))
_MODEL = os.path.join(_BASE, "02_Model")
for _sub in ["01_Inputs", "02_Core", "03_Solvers",
             "04_Postprocessing", "05_Utils"]:
    _ruta = os.path.join(_MODEL, _sub)
    if _ruta not in sys.path:
        sys.path.append(_ruta)

import pyomo.environ as pyo

import data_loader        # esta en 02_Model/01_Inputs
import model_builder      # esta en 02_Model/02_Core
import solver_runner      # esta en 02_Model/03_Solvers
import results_export     # esta en 04_Postprocessing


def ejecutar(ruta_caso, solver="highs", horas=None, exportar_lp=False,
             exportar=False, verbose=True):
    """
    Ejecuta el flujo completo para un caso y devuelve (modelo, salida).

    ruta_caso   : ruta al Excel del caso.
    solver      : solver a usar (ver solver_runner.SOLVERS).
    horas       : si se indica, recorta el horizonte a ese numero de h.
    exportar_lp : exporta el modelo a .lp.
    verbose     : imprime el progreso.
    """
    # Marca de inicio del procesamiento del caso.
    _t_ini = _time.perf_counter()

    # 1. CARGA
    if verbose:
        print(f"\n[1/4] Cargando datos: {ruta_caso}")
        print(ruta_caso)
        print(os.path.exists(ruta_caso))
    datos = data_loader.cargar_datos(ruta_caso)
    
    # (calcular una vez, cerca del inicio de ejecutar)
    nombre_caso = os.path.splitext(os.path.basename(ruta_caso))[0]
    sello = datetime.now().strftime("%Y%m%d_%H%M%S")

    # recorte opcional del horizonte (util para pruebas rapidas)
    if horas is not None:
        datos.n_horas = horas
        datos.demanda = {k: v for k, v in datos.demanda.items()
                         if k[1] <= horas}
    if verbose:
        print(f"      Nodos={len(datos.nodos)}, "
              f"Lineas={len(datos.lineas)}, "
              f"Gen={len(datos.gen_termica)}, "
              f"Horizonte={datos.n_horas}h")

    # 2. CONSTRUYE
    if verbose:
        print("[2/4] Construyendo el modelo...")
    modelo = model_builder.construir_modelo(datos)
    n_var = sum(1 for _ in modelo.component_data_objects(pyo.Var))
    n_con = sum(1 for _ in modelo.component_data_objects(pyo.Constraint))
    if verbose:
        print(f"      {n_var} variables, {n_con} restricciones")

    # 2.5 DESPACHO FIJO (modo validacion vs MATPOWER)
    # Si el caso trae despacho fijo (columna Pg_fijo), se fijan las
    # variables P_g y u a esos valores exactos, de modo que el modelo
    # calcule el flujo de potencia para ese despacho conocido en vez
    # de optimizar el suyo. Permite comparar contra rundcpf/runpf.
    pg_fijo = getattr(datos, "pg_fijo", {})
    if pg_fijo:
        if verbose:
            print(f"      [validacion] fijando despacho: {pg_fijo}")
        for g, valor in pg_fijo.items():
            for t in modelo.T:
                modelo.P_g[g, t].fix(valor)
                modelo.u[g, t].fix(1 if valor > 0 else 0)

    # 3. RESUELVE
    if verbose:
        print(f"[3/4] Resolviendo con '{solver}'...")
    # ruta del .lp en 04_Outputs con caso + fecha/hora (si se pide)
    nombre_caso = os.path.splitext(os.path.basename(ruta_caso))[0]
    sello = datetime.now().strftime("%Y%m%d_%H%M%S")
    ruta_lp = os.path.join(
        _BASE, "04_Outputs",
        f"modelo_{nombre_caso}_{solver}_{sello}.lp")
    
    if hasattr(datos, "solver") and datos.solver:
        solver = datos.solver

    salida = solver_runner.resolver(
        modelo, datos, solver=solver, exportar_lp=exportar_lp,
        ruta_lp=ruta_lp, verbose=verbose)

    # 4. RESUMEN de la solucion
    if verbose and salida["resuelto"]:
        _resumen_solucion(modelo)

    # Tiempos de pared (se calculan ANTES de exportar e imprimir).
    _t_desde_arranque = _time.perf_counter() - _T_ARRANQUE
    _t_procesamiento = _time.perf_counter() - _t_ini
    salida["tiempo_total_s"] = _t_desde_arranque
    salida["tiempo_procesamiento_s"] = _t_procesamiento

    # 5. EXPORTAR resultados a Excel (si se pidio).
    if exportar and salida["resuelto"]:
        nombre_salida = f"resultados_{nombre_caso}_{sello}.xlsx"
        ruta_salida = os.path.join(_BASE, "04_Outputs", nombre_salida)
        results_export.exportar_resultados(
            modelo, ruta_salida, salida["valor_objetivo"],
            solver=solver,
            tiempo_s=salida.get("tiempo_s", None),
            tiempo_total_s=_t_desde_arranque,
            tiempo_proc_s=_t_procesamiento)
        if verbose:
            print(f"\n  Exportado a: 04_Outputs/{nombre_salida}")

    # Reporte de tiempos en consola.
    if verbose:
        _t_solver = salida.get("tiempo_s", None)
        print("\n" + "-" * 52)
        print(f"  Tiempo desde que se lanzo el script: "
              f"{_t_desde_arranque:8.2f} s")
        print(f"  Tiempo de importar librerias       : "
              f"{_t_desde_arranque - _t_procesamiento:8.2f} s")
        print(f"  Tiempo de procesar el caso         : "
              f"{_t_procesamiento:8.2f} s")
        if _t_solver is not None:
            print(f"    - solo el solver                 : "
                  f"{_t_solver:8.2f} s")
            print(f"    - construccion + lectura + export: "
                  f"{_t_procesamiento - _t_solver:8.2f} s")
        print("-" * 52)

    return modelo, salida


def _resumen_solucion(model):
    """Imprime un resumen legible de la solucion (despacho, inversiones)."""
    print("\n[4/4] Resumen de la solucion")
    print("-" * 52)

    # --- despacho termico (primer periodo, como muestra) ---
    t0 = model.T.first()
    print(f"  Despacho termico (t={t0}):")
    for g in model.G:
        pg = pyo.value(model.P_g[g, t0])
        u = pyo.value(model.u[g, t0])
        estado = "ON" if u > 0.5 else "off"
        print(f"    {g}: {pg:7.1f} MW [{estado}]")

    # --- decisiones de INVERSION (lo relevante para TEP) ---
    # ELIMINADA función de la tesis
    # lineas_construidas = [l for l in model.LC
    #                       if pyo.value(model.x_l[l]) > 0.5]
    bess_instalados = [s for s in model.S
                       if pyo.value(model.y_s[s]) > 0.5]
    facts_instalados = [f for f in model.F
                        if pyo.value(model.z_f[f]) > 0.5]

    print("\n  Decisiones de inversion (TEP):")
    # if lineas_construidas:
    #     print(f"    Lineas construidas : {lineas_construidas}")
    # else:
    #     print("    Lineas construidas : ninguna")
    if bess_instalados:
        for s in bess_instalados:
            ps = pyo.value(model.Psmax[s]); es = pyo.value(model.Esmax[s])
            print(f"    BESS en {s}: {ps:.1f} MW / {es:.1f} MWh")
    else:
        print("    BESS instalados    : ninguno")
    if facts_instalados:
        print(f"    FACTS instalados   : {facts_instalados}")
    else:
        print("    FACTS instalados   : ninguno")

    # --- perdidas totales (primer periodo) ---
    # Si incluir_perdidas=0 (validacion DC), Ploss no es significativa
    # (ver nota en results_export.py); se reporta como 0.
    incl_perd = pyo.value(model.incluir_perdidas)
    if incl_perd:
        perd = sum(pyo.value(model.Ploss[l, t0]) for l in model.L_ALL)
    else:
        perd = 0.0
    print(f"\n  Perdidas totales (t={t0}): {perd:.2f} MW")
    print("-" * 52)


def main():
    parser = argparse.ArgumentParser(
        description="Modelo TEP con BESS y FACTS.")
    parser.add_argument("caso", nargs="?", default="caso_WW.xlsx",
                        help="Ruta al Excel del caso (default caso_WW).")
    parser.add_argument("--solver", default="highs",
                        help="Solver: highs, gurobi, glpk, cbc, "
                             "cplex_neos.")
    parser.add_argument("--horas", type=int, default=None,
                        help="Recorta el horizonte a N horas (pruebas).")
    parser.add_argument("--lp", action="store_true",
                        help="Exporta el modelo a .lp.")
    parser.add_argument("--export", action="store_true",
                        help="Exporta los resultados a 04_Outputs.")
    args = parser.parse_args()

    ejecutar(args.caso, solver=args.solver, horas=args.horas,
             exportar_lp=args.lp, exportar=args.export)


if __name__ == "__main__":
    main()
