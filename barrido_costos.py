# -*- coding: utf-8 -*-
"""
barrido_costos.py -- Analisis de sensibilidad de costos BESS / FACTS
====================================================================

Corre el modelo VARIAS veces sobre el MISMO caso, multiplicando el
costo de BESS (y/o FACTS) por una serie de factores, y registra cuanto
instala el modelo en cada caso. Responde la pregunta del director:
"si bajo 10%, 50%, o casi a cero el costo de la tecnologia, el sistema
la sigue implementando?".

NO modifica el modelo ni el Excel. Escala los costos en memoria, sobre
el objeto de datos, antes de construir cada modelo.

USO
---
    python barrido_costos.py "ruta\\al\\caso.xlsx"

o editando la variable CASO abajo y ejecutando con el boton Run.

SALIDA
------
Imprime una tabla en consola y guarda un Excel con los resultados en
la carpeta 03_Outputs.
"""

import os
import sys

_BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _BASE)

# main.py ya configura el sys.path hacia 02_Model/... al importarse.
import main
import data_loader
import model_builder
import solver_runner

# --- localizar los modulos del proyecto (misma logica que main.py) ---
# Ajusta estas rutas solo si tu estructura de carpetas cambia.
_BASE = os.path.dirname(os.path.abspath(__file__))
for sub in ["02_Model/01_Inputs", "02_Model/02_Formulation",
            "02_Model/03_Solvers", "02_Model/04_Postprocessing"]:
    ruta = os.path.join(_BASE, sub)
    if os.path.isdir(ruta) and ruta not in sys.path:
        sys.path.insert(0, ruta)
sys.path.insert(0, _BASE)

try:
    from openpyxl import Workbook
    _HAY_OPENPYXL = True
except ImportError:
    _HAY_OPENPYXL = False


# =====================================================================
# CONFIGURACION DEL BARRIDO  (edita aqui)
# =====================================================================

# Caso a analizar (puede venir por linea de comandos)
CASO = r"H:\My Drive\2. Universidad Nacional de Colombia\2. Postgraduate\1_SEMESTER\TESIS DE MAESTRIA\2nd Search\04_TESIS_DANIEL\03_CODIGO_TRABAJO_DANIEL\BESS_FACTS_master\01_Data\03_Test_Cases\caso_IEEE14_E3_24h.xlsx"
#   - "bess"  : escala solo costos de BESS  (para E1)
#   - "facts" : escala solo costos de FACTS (para E2)
#   - "ambas" : escala ambos por el mismo factor (para E3)
TECNOLOGIA = "ambas"

# Factores de costo a probar (1.0 = costo original NREL; 0.0 = gratis)
FACTORES = [1.00, 0.50, 0.25, 0.10, 0.05, 0.03, 0.02, 0.015, 0.01, 0.005]

SOLVER = "gurobi"
MIP_GAP = 0.0001        # fino para BESS; sube a 0.01 si incluyes FACTS
# =====================================================================


def _escalar_costos(datos, factor, tecnologia):
    """Multiplica en memoria los costos de la(s) tecnologia(s)."""
    if tecnologia in ("bess", "ambas"):
        if hasattr(datos, "costo_bess_power"):
            datos.costo_bess_power *= factor
        if hasattr(datos, "costo_bess_energy"):
            datos.costo_bess_energy *= factor

    if tecnologia in ("facts", "ambas"):
        # El costo del TCSC ya no es un par (inst, size): es un unico
        # costo por bloque, derivado de c_tcsc [USD/MVAr] y de la
        # potencia reactiva Q_{f,z}. Basta escalar c_tcsc y recalcular.
        if hasattr(datos, "c_tcsc"):
            datos.c_tcsc *= factor
            for k, Q in datos.facts_Q.items():
                datos.facts_capex[k] = datos.c_tcsc * Q
    return datos


def _leer_instalado(modelo):
    """Suma la capacidad instalada de BESS y FACTS de un modelo resuelto."""
    import pyomo.environ as pyo

    ps_tot = es_tot = 0.0
    n_bess = 0
    if hasattr(modelo, "S"):
        for s in modelo.S:
            ps = pyo.value(modelo.Psmax[s]) if hasattr(modelo, "Psmax") else 0
            es = pyo.value(modelo.Esmax[s]) if hasattr(modelo, "Esmax") else 0
            ps = ps or 0
            es = es or 0
            if ps > 1e-3:
                n_bess += 1
            ps_tot += max(ps, 0)
            es_tot += max(es, 0)

    n_facts = 0
    mvar_tot = 0.0
    sigma_sum = 0.0
    if hasattr(modelo, "F") and hasattr(modelo, "kappa"):
        for f in modelo.F:
            for z in modelo.Z:
                k = pyo.value(modelo.kappa[f, z]) or 0
                if k > 0.5:
                    n_facts += 1
                    mvar_tot += pyo.value(modelo.Q_fz[f, z]) or 0
                    sigma_sum += pyo.value(modelo.sigma[z]) or 0
    sigma_med = sigma_sum / n_facts if n_facts else 0.0

    return {
        "n_bess": n_bess, "ps_tot": ps_tot, "es_tot": es_tot,
        "n_facts": n_facts, "mvar_tot": mvar_tot, "sigma_med": sigma_med,
    }


def barrido(caso, tecnologia=TECNOLOGIA, factores=FACTORES,
            solver=SOLVER, mip_gap=MIP_GAP):
    filas = []
    print("\n" + "=" * 78)
    print(f"  BARRIDO DE SENSIBILIDAD DE COSTOS -- tecnologia: {tecnologia}")
    print(f"  Caso: {os.path.basename(caso)}")
    print("=" * 78)
    print(f"{'factor':>7} {'costo%':>7} | {'BESS n':>6} {'P(MW)':>8} "
          f"{'E(MWh)':>8} | {'FACTS n':>7} {'MVAr':>7} {'sigma':>6} | "
          f"{'costo obj':>14}")
    print("-" * 78)

    for factor in factores:
        # Recargar datos LIMPIOS en cada iteracion (evita acumular escalados)
        datos = data_loader.cargar_datos(caso)
        datos = _escalar_costos(datos, factor, tecnologia)

        modelo = model_builder.construir_modelo(datos)
        salida = solver_runner.resolver(modelo, datos, solver=solver,
                                        mip_gap=mip_gap, verbose=False)

        if not salida.get("resuelto"):
            print(f"{factor:7.2f} {factor*100:6.0f}% | "
                  f"{'INFACTIBLE o no resuelto':>50}")
            filas.append([factor, "infactible", "", "", "", "", "", "", ""])
            continue

        inst = _leer_instalado(modelo)
        costo = salida.get("valor_objetivo", 0) or 0
        print(f"{factor:7.2f} {factor*100:6.0f}% | "
              f"{inst['n_bess']:6d} {inst['ps_tot']:8.2f} "
              f"{inst['es_tot']:8.2f} | "
              f"{inst['n_facts']:7d} {inst['mvar_tot']:7.2f} "
              f"{inst['sigma_med']:6.2f} | {costo:14,.2f}")
        filas.append([factor, "ok", inst["n_bess"], round(inst["ps_tot"], 3),
                      round(inst["es_tot"], 3), inst["n_facts"],
                      round(inst["mvar_tot"], 3), round(inst["sigma_med"], 3),
                      round(costo, 2)])

    print("=" * 78)
    
    ruta_out = None

    # Guardar a Excel
    # No se escribe ningun archivo. La funcion devuelve los encabezados y
    # las filas; quien llame decide que hacer con ellos. Desde consola se
    # ignoran (la tabla ya se imprimio); la interfaz grafica construye el
    # Excel en memoria solo si el usuario pide descargarlo.
    encabezados = ["factor_costo", "estado", "n_BESS", "P_BESS_MW",
                   "E_BESS_MWh", "n_FACTS", "dB_FACTS_total",
                   "costo_obj_USD"]

    return encabezados, filas


if __name__ == "__main__":
    caso = sys.argv[1] if len(sys.argv) > 1 else CASO
    barrido(caso)
