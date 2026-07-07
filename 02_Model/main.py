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

import argparse
import pyomo.environ as pyo

import data_loader
import model_builder
import solver_runner


def ejecutar(ruta_caso, solver="highs", horas=None, exportar_lp=False,
             verbose=True):
    """
    Ejecuta el flujo completo para un caso y devuelve (modelo, salida).

    ruta_caso   : ruta al Excel del caso.
    solver      : solver a usar (ver solver_runner.SOLVERS).
    horas       : si se indica, recorta el horizonte a ese numero de h.
    exportar_lp : exporta el modelo a .lp.
    verbose     : imprime el progreso.
    """
    # 1. CARGA
    if verbose:
        print(f"\n[1/4] Cargando datos: {ruta_caso}")
    datos = data_loader.cargar_datos(ruta_caso)

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

    # 3. RESUELVE
    if verbose:
        print(f"[3/4] Resolviendo con '{solver}'...")
    salida = solver_runner.resolver(
        modelo, datos, solver=solver, exportar_lp=exportar_lp,
        ruta_lp=f"modelo_{solver}.lp", verbose=verbose)

    # 4. RESUMEN de la solucion
    if verbose and salida["resuelto"]:
        _resumen_solucion(modelo)

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
    lineas_construidas = [l for l in model.LC
                          if pyo.value(model.x_l[l]) > 0.5]
    bess_instalados = [s for s in model.S
                       if pyo.value(model.y_s[s]) > 0.5]
    facts_instalados = [f for f in model.F
                        if pyo.value(model.z_f[f]) > 0.5]

    print("\n  Decisiones de inversion (TEP):")
    if lineas_construidas:
        print(f"    Lineas construidas : {lineas_construidas}")
    else:
        print("    Lineas construidas : ninguna")
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
    perd = sum(pyo.value(model.Ploss[l, t0]) for l in model.L_ALL)
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
    args = parser.parse_args()

    ejecutar(args.caso, solver=args.solver, horas=args.horas,
             exportar_lp=args.lp)


if __name__ == "__main__":
    main()
