# -*- coding: utf-8 -*-
"""
==================================================================
 SOLVER
------------------------------------------------------------------
Autor : Daniel Lindo -- Universidad Nacional de Colombia (UNAL)
Tesis : Maestria en Ingenieria Electrica, 2026
------------------------------------------------------------------

Configura el solver, resuelve el modelo y verifica el resultado,
aplicando las BUENAS PRACTICAS de resolucion:
  - Configurar mip_gap y time_limit (evita corridas infinitas).
  - VERIFICAR el status del solver explicitamente (optimo, limite de
    tiempo, infactible) en vez de asumir que todo salio bien.
  - Exportar el modelo a .lp con nombres legibles (symbolic labels)
    para inspeccion y anexos de la tesis.
  - Reportar el gap final y el tiempo de solucion.

Soporta HiGHS (libre, por defecto) y Gurobi (academico, produccion).
El cambio de solver es un parametro; el resto del flujo es identico.

SOLVERS SOPORTADOS (seleccionables):
  - 'highs'      : HiGHS, libre, local, moderno (por defecto).
  - 'gurobi'     : Gurobi, comercial, local (licencia academica).
  - 'glpk'       : GLPK, libre, local (el que usaba Avendano).
  - 'cbc'        : CBC, libre, local (baseline historico).
  - 'cplex_neos' : CPLEX via servidor NEOS (remoto; requiere internet
                   y un email en NEOS_EMAIL). Como en Avendano.
==================================================================
"""

import os
import time
import pyomo.environ as pyo
 
 
SOLVERS = {
    "highs": "HiGHS (libre, local)",
    "gurobi": "Gurobi (comercial, local)",
    "glpk": "GLPK (libre, local)",
    "cbc": "CBC (libre, local)",
    "cplex_neos": "CPLEX via NEOS (remoto, requiere internet)",
}
 
 
def _configurar_solver(solver, mip_gap, time_limit):
    """Devuelve (opt, manager, kwargs) segun el solver elegido."""
    s = solver.lower()
 
    if s == "gurobi":
        opt = pyo.SolverFactory("gurobi")
        opt.options["MIPGap"] = mip_gap
        opt.options["TimeLimit"] = time_limit
        return opt, None, {}
 
    if s == "glpk":
        opt = pyo.SolverFactory("glpk")
        opt.options["mipgap"] = mip_gap
        opt.options["tmlim"] = int(time_limit)
        return opt, None, {}
 
    if s == "cbc":
        opt = pyo.SolverFactory("cbc")
        opt.options["ratioGap"] = mip_gap
        opt.options["seconds"] = int(time_limit)
        return opt, None, {}
 
    if s == "cplex_neos":
        if not os.environ.get("NEOS_EMAIL"):
            raise ValueError(
                "CPLEX-NEOS requiere la variable de entorno NEOS_EMAIL "
                "con un correo valido (export NEOS_EMAIL=tu@mail).")
        manager = pyo.SolverManagerFactory("neos")
        return None, manager, {"opt": "cplex"}
 
    # HiGHS por defecto (appsi)
    opt = pyo.SolverFactory("appsi_highs")
    opt.config.mip_gap = mip_gap
    opt.config.time_limit = time_limit
    return opt, None, {}
 
 
def resolver(model, data=None, solver="highs", mip_gap=None,
             time_limit=None, exportar_lp=False, ruta_lp="modelo.lp",
             verbose=True):
    """Resuelve el modelo y devuelve un dict con el resultado."""
    if solver.lower() not in SOLVERS:
        raise ValueError(
            f"Solver '{solver}' no soportado. Opciones: "
            f"{', '.join(SOLVERS)}")
 
    if mip_gap is None:
        mip_gap = getattr(data, "mip_gap", 0.01) if data else 0.01
    if time_limit is None:
        time_limit = getattr(data, "time_limit", 1800) if data else 1800
 
    if exportar_lp:
        model.write(ruta_lp,
                    io_options={"symbolic_solver_labels": True})
        if verbose:
            print(f"Modelo exportado a: {ruta_lp}")
 
    opt, manager, kwargs = _configurar_solver(solver, mip_gap,
                                              time_limit)
 
    t0 = time.time()
    if manager is not None:
        resultados = manager.solve(model, **kwargs)
    else:
        try:
            resultados = opt.solve(model)
        except RuntimeError as e:
            if "feasible solution was not found" in str(e).lower():
                return {
                    "status": "infactible",
                    "valor_objetivo": None,
                    "resuelto": False,
                }
            raise
    tiempo = time.time() - t0
 
    term = str(resultados.solver.termination_condition)
    status_ok = term in ("optimal", "maxTimeLimit", "feasible")
 
    valor_obj = None
    if status_ok:
        try:
            valor_obj = pyo.value(model.obj)
        except Exception:
            valor_obj = None
 
    salida = {
        "status": term,
        "resuelto": status_ok,
        "valor_objetivo": valor_obj,
        "tiempo_s": tiempo,
        "solver": solver,
        "resultados": resultados,
    }
 
    if verbose:
        print("=" * 52)
        print("RESULTADO DE LA OPTIMIZACION")
        print("=" * 52)
        print(f"  Solver          : {SOLVERS[solver.lower()]}")
        print(f"  Terminacion     : {term}")
        print(f"  Tiempo          : {tiempo:.2f} s")
        if valor_obj is not None:
            print(f"  Costo optimo    : {valor_obj:,.2f} USD")
        if term == "infeasible":
            print("  *** MODELO INFACTIBLE: revise datos/restricciones.")
        elif term == "maxTimeLimit":
            print("  *** Limite de tiempo: solucion factible no optima.")
        elif term == "optimal":
            print(f"  Optimo alcanzado (gap <= {mip_gap*100:.1f}%).")
        print("=" * 52)
 
    return salida
 
 
if __name__ == "__main__":
    import sys
    import data_loader
    import model_builder
 
    ruta = sys.argv[1] if len(sys.argv) > 1 else "caso_WW.xlsx"
    sol = sys.argv[2] if len(sys.argv) > 2 else "highs"
    datos = data_loader.cargar_datos(ruta)
    datos.n_horas = 3
    datos.demanda = {k: v for k, v in datos.demanda.items() if k[1] <= 3}
 
    modelo = model_builder.construir_modelo(datos)
    salida = resolver(modelo, datos, solver=sol, exportar_lp=True,
                      ruta_lp="/tmp/modelo_ww.lp")
