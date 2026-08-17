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
    bess_i = [s for s in model.S if pyo.value(model.Psmax[s]) > 1e-6]
    facts_i = [(f, z) for f in model.F for z in model.Z
               if pyo.value(model.kappa[f, z]) > 0.5]
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
    
    # Costo prorrateado de BESS y FACTS (recalculado con la solucion)
    def _crf(r, n):
        return (r * (1 + r) ** n) / ((1 + r) ** n - 1)

    dias_sim = len(model.T) / 24.0
    tasa = pyo.value(model.tasa_desc)
    crf_b = _crf(tasa, pyo.value(model.vida_bess))
    crf_f = _crf(tasa, pyo.value(model.vida_facts))

    # costo_bess_val = (dias_sim / 365.0) * sum(
    #     crf_b * (pyo.value(model.Cs_power) * pyo.value(model.Psmax[s])
    #              + pyo.value(model.Cs_energy) * pyo.value(model.Esmax[s]))
    #     for s in model.S)

    # costo_facts_val = (dias_sim / 365.0) * sum(
    #     crf_f * pyo.value(model.Cf_capex[f, z])
    #     * pyo.value(model.kappa[f, z])
    #     for f in model.F for z in model.Z)
    
    delta_T = len(model.T) / 8760.0
    costo_bess_val = delta_T * crf_b * sum(
        pyo.value(model.Cs_power) * pyo.value(model.Psmax[s])
        + pyo.value(model.Cs_energy) * pyo.value(model.Esmax[s])
        for s in model.S)

    costo_facts_val = delta_T * crf_f * sum(
        pyo.value(model.Cf_capex[f, z]) * pyo.value(model.kappa[f, z])
        for f in model.F for z in model.Z)

    filas_res.append(["Costo inversion BESS (USD)", round(costo_bess_val, 2)])
    filas_res.append(["Costo inversion FACTS (USD)", round(costo_facts_val, 2)])
    
    _escribir_tabla(ws, ["Indicador", "Valor"], filas_res,
                    "Resumen de la solucion")

    # ================= Hoja DESPACHO ============================
    ws = wb.create_sheet("Despacho")
    encab = ["hora"] + [str(g) for g in model.G] + [f"u_{g}" for g in model.G]
    filas = []
    for t in horas:
        fila = ([t] + [round(pyo.value(model.P_g[g, t]), 2) for g in model.G]
                    + [round(pyo.value(model.u[g, t]), 0) for g in model.G])
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
    
    # ================= Hoja FACTS ===============================
    # Flujo inducido por el TCSC en cada linea compensada (MW/hora).
    # Es la evidencia cuantitativa de la redistribucion de flujos.
    ws = wb.create_sheet("FACTS")
    if len(facts_i) > 0:
        encab = ["hora"] + [f"{f} dP_TCSC (MW)" for (f, z) in facts_i]
        filas = []
        for t in horas:
            fila = [t]
            for (f, z) in facts_i:
                dp = pyo.value(model.MVA_base) * sum(
                    pyo.value(model.psi[f, zz, t]) for zz in model.Z)
                fila.append(round(dp, 3))
            filas.append(fila)
        _escribir_tabla(ws, encab, filas, "Flujo inducido por el TCSC (MW)")
    else:
        _escribir_tabla(ws, ["-"], [["ningun TCSC instalado"]],
                        "Flujo inducido por el TCSC (MW)")

    # ================= Hoja INVERSIONES =========================
    ws = wb.create_sheet("Inversiones")
    filas_inv = []
    # for l in lineas_c:
    #     filas_inv.append(["Linea", str(l), "construida", ""])
    for s in bess_i:
        ps = round(pyo.value(model.Psmax[s]), 1)
        es = round(pyo.value(model.Esmax[s]), 1)
        filas_inv.append(["BESS", str(s), f"{ps} MW", f"{es} MWh"])
    for (f, z) in facts_i:
        sg = pyo.value(model.sigma[z])
        Q = pyo.value(model.Q_fz[f, z])
        filas_inv.append(["TCSC", str(f), f"sigma={sg:.2f}", f"{Q:.2f} MVAr"])
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

# ================= Hoja Hidraulica ===========================
    # Operacion del embalse por unidad y hora. Permite verificar que el
    # balance V_t = V_{t-1} + I_t - k*(q_t + S_t) cierra numericamente.
    ws = wb.create_sheet("Hidraulica")
    if len(model.H) > 0:
        for h in model.H:
            encab = ["hora", "P (MW)", "q (m3/s)", "V (hm3)",
                     "S (m3/s)", "I (hm3/h)"]
            filas = []
            for t in horas:
                filas.append([
                    t,
                    round(pyo.value(model.P_h[h, t]), 3),
                    round(pyo.value(model.q_h[h, t]), 3),
                    round(pyo.value(model.V_h[h, t]), 4),
                    round(pyo.value(model.S_h[h, t]), 3),
                    round(pyo.value(model.I_h[h, t]), 4),
                ])
            _escribir_tabla(ws, encab, filas, f"Embalse {h}")
    else:
        _escribir_tabla(ws, ["-"], [["sin unidades hidraulicas"]],
                        "Operacion hidraulica")


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
