# -*- coding: utf-8 -*-
"""
results_export.py -- Exportacion de resultados del modelo TEP.

Extrae la solucion de un modelo ya resuelto y la guarda en un Excel
con hojas tematicas, listas para analisis y graficos:
    Resumen        -> costo total, inversiones, perdidas globales.
    Despacho       -> generacion por unidad y hora.
    Flujos         -> flujo de potencia por linea y hora.
    Perdidas       -> perdidas por linea y hora.
    Inversiones    -> lineas / BESS / FACTS construidos.
    BESS_operacion -> carga, descarga y SoC por hora (si hay BESS).

Separar la exportacion en su propio modulo mantiene el modelo limpio
(no mezcla optimizacion con escritura de archivos).

Autor : Daniel Lindo -- Universidad Nacional de Colombia (UNAL)
Tesis : Maestria en Ingenieria Electrica, 2026
Python: 3.12
"""

import pyomo.environ as pyo
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
import math


HDR_FILL = PatternFill("solid", start_color="1F4E78")
HDR_FONT = Font(bold=True, color="FFFFFF")
TITLE_FONT = Font(bold=True, size=13, color="1F4E78")
CENTER = Alignment(horizontal="center")


def _escribir_tabla(ws, encabezados, filas, titulo, fila_ini=1):
    """Escribe una tabla con titulo, encabezados y filas."""
    ws.cell(row=fila_ini, column=1, value=titulo).font = TITLE_FONT
    r = fila_ini + 2
    for c, h in enumerate(encabezados, 1):
        cell = ws.cell(row=r, column=c, value=h)
        cell.font = HDR_FONT; cell.fill = HDR_FILL; cell.alignment = CENTER
    for i, fila in enumerate(filas):
        for c, v in enumerate(fila, 1):
            ws.cell(row=r + 1 + i, column=c, value=v)
    for c in range(1, len(encabezados) + 1):
        ws.column_dimensions[
            ws.cell(row=r, column=c).column_letter].width = 14
    return r + 1 + len(filas)


def exportar_resultados(model, ruta_salida, valor_objetivo=None,
                         solver=None, tiempo_s=None,
                         tiempo_total_s=None, tiempo_proc_s=None):
    """
    Exporta la solucion del modelo `model` (ya resuelto) a un Excel.

    model          : ConcreteModel resuelto.
    ruta_salida    : ruta del .xlsx de salida.
    valor_objetivo : costo optimo (si None, se lee de model.obj).
    """
    if valor_objetivo is None:
        valor_objetivo = pyo.value(model.obj)

    horas = list(model.T)
    wb = Workbook()

    # ================= Hoja RESUMEN =============================
    ws = wb.active; ws.title = "Resumen"
    # lineas_c = [l for l in model.L_ALL if pyo.value(model.x_l[l]) > 0.5]
    bess_i = [s for s in model.S if pyo.value(model.y_s[s]) > 0.5]
    facts_i = [f for f in model.F if pyo.value(model.z_f[f]) > 0.5]
    # Si incluir_perdidas=0 (modo validacion DC), las variables Ploss
    # no participan en el balance ni en los limites de flujo; su valor
    # calculado (ligado solo a la diferencia angular real) no es
    # significativo y se reporta como 0 para evitar confusion.
    incl_perd = pyo.value(model.incluir_perdidas)
    if incl_perd:
        perd_tot = sum(pyo.value(model.Ploss[l, t])
                       for l in model.L_ALL for t in horas)
    else:
        perd_tot = 0.0
    gen_tot = sum(pyo.value(model.P_g[g, t])
                  for g in model.G for t in horas)
    filas_res = [
        ["Costo total optimo (USD)", round(valor_objetivo, 2)],
        ["Generacion termica total (MWh)", round(gen_tot, 1)],
        ["Perdidas totales (MWh)", round(perd_tot, 2)],
        # ["Lineas construidas", len(lineas_c)],
        ["BESS instalados", len(bess_i)],
        ["FACTS instalados", len(facts_i)],
        ["Horizonte (h)", len(horas)],
        ["Solver utilizado", solver if solver else "N/D"],
        ["Tiempo total simulacion (s)",
         round(tiempo_total_s, 2) if tiempo_total_s is not None else "N/D"],
    ]
    _escribir_tabla(ws, ["Indicador", "Valor"], filas_res,
                    "Resumen de la solucion")

    # ================= Hoja DESPACHO ============================
    ws = wb.create_sheet("Despacho")
    encab = ["hora"] + [str(g) for g in model.G]
    filas = []
    for t in horas:
        fila = [t] + [round(pyo.value(model.P_g[g, t]), 2)
                      for g in model.G]
        filas.append(fila)
    _escribir_tabla(ws, encab, filas, "Despacho termico (MW)")

    # ================= Hoja FLUJOS ==============================
    ws = wb.create_sheet("Flujos")
    encab = ["hora"] + [str(l) for l in model.L_ALL]
    filas = []
    for t in horas:
        fila = [t] + [round(pyo.value(model.f[l, t]), 2)
                      for l in model.L_ALL]
        filas.append(fila)
    _escribir_tabla(ws, encab, filas, "Flujos de potencia (MW)")

    # ================= Hoja PERDIDAS ============================
    ws = wb.create_sheet("Perdidas")
    encab = ["hora"] + [str(l) for l in model.L_ALL]
    filas = []
    for t in horas:
        if incl_perd:
            fila = [t] + [round(pyo.value(model.Ploss[l, t]), 3)
                          for l in model.L_ALL]
        else:
            fila = [t] + [0.0 for l in model.L_ALL]
        filas.append(fila)
    titulo_perd = ("Perdidas por linea (MW)" if incl_perd
                   else "Perdidas por linea (MW) -- No incluidas "
                        "en el modelo (incluir_perdidas=0)")
    _escribir_tabla(ws, encab, filas, titulo_perd)
    
    # ================= Hoja ANGULOS ============================
    ws = wb.create_sheet("Angulos")
    encab = ["hora"] + [str(n) for n in model.N]
    filas = []
    for t in horas:
        fila = [t] + [round(math.degrees(pyo.value(model.theta[n, t])), 4)
                    for n in model.N]
        filas.append(fila)
    _escribir_tabla(ws, encab, filas, "Angulos nodales (grados)")

    # ================= Hoja INVERSIONES =========================
    ws = wb.create_sheet("Inversiones")
    filas_inv = []
    # for l in lineas_c:
    #     filas_inv.append(["Linea", str(l), "construida", ""])
    for s in bess_i:
        ps = round(pyo.value(model.Psmax[s]), 1)
        es = round(pyo.value(model.Esmax[s]), 1)
        filas_inv.append(["BESS", str(s), f"{ps} MW", f"{es} MWh"])
    for f in facts_i:
        db = round(pyo.value(model.dB_f[f]), 3)
        filas_inv.append(["FACTS", str(f), f"dB={db}", ""])
    if not filas_inv:
        filas_inv.append(["-", "ninguna inversion", "", ""])
    _escribir_tabla(ws, ["Tipo", "Ubicacion", "Detalle_1", "Detalle_2"],
                    filas_inv, "Decisiones de inversion (TEP)")

    # ================= Hoja BESS_operacion (si hay) =============
    if len(bess_i) > 0:
        ws = wb.create_sheet("BESS_operacion")
        fila_actual = 1
        for s in bess_i:
            encab = ["hora", "carga (MW)", "descarga (MW)", "SoC (MWh)"]
            filas = []
            for t in horas:
                filas.append([
                    t,
                    round(pyo.value(model.Pch[s, t]), 2),
                    round(pyo.value(model.Pdis[s, t]), 2),
                    round(pyo.value(model.SoC[s, t]), 2),
                ])
            fila_actual = _escribir_tabla(
                ws, encab, filas, f"BESS en {s}", fila_ini=fila_actual)
            fila_actual += 2

    wb.save(ruta_salida)
    return ruta_salida


if __name__ == "__main__":
    import sys
    import data_loader, model_builder, solver_runner

    ruta = sys.argv[1] if len(sys.argv) > 1 else "caso_WW.xlsx"
    datos = data_loader.cargar_datos(ruta)
    datos.n_horas = 3
    datos.demanda = {k: v for k, v in datos.demanda.items() if k[1] <= 3}

    modelo = model_builder.construir_modelo(datos)
    salida = solver_runner.resolver(modelo, datos, verbose=False)

    if salida["resuelto"]:
        out = exportar_resultados(modelo, "resultados.xlsx",
                                  salida["valor_objetivo"])
        print(f"Resultados exportados a: {out}")
    else:
        print(f"No se pudo resolver: {salida['status']}")
