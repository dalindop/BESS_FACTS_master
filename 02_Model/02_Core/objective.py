# -*- coding: utf-8 -*-
"""
==================================================================
  OBJECTIVE
------------------------------------------------------------------
Autor : Daniel Lindo -- Universidad Nacional de Colombia (UNAL)
Tesis : Maestria en Ingenieria Electrica, 2026
------------------------------------------------------------------

Define la FUNCION OBJETIVO: la expresion que el solver minimiza. Segun
el Cap. 3 de la tesis, minimiza el COSTO TOTAL de planificacion y
operacion del sistema:

  min Z = COSTO TERMICO + COSTO HIDRAULICO + COSTO TRANSMISION
        + COSTO BESS + COSTO FACTS

Desglose (notacion de la tesis):
  Termico    : SUM_{g,t} [ Cg(Pg,t) + Cg^SU*SU + Cg^SD*SD ]
               donde Cg(Pg,t) = fg_min*u + SUM_m slope*dP_seg  (linealiz.)
  Hidraulico : SUM_{h,t} Ch * Ph,t
  Transmision: SUM_{l in LC} Cl * x_l                 (expansion lineas)
  BESS       : SUM_{s in S} (Cs^inst*y_s + Cs^power*Psmax
                             + Cs^energy*Esmax)
  FACTS      : SUM_{f in F} (Cf^inst*z_f + Cf^size*X_f)   <-- DIFERIDO

ALCANCE DE ESTE PASO:
  Se incluyen todos los terminos MENOS FACTS. El termino FACTS es
  ADITIVO (se suma): se anade despues, cuando se declaren z_f y X_f
  (pendiente de resolver la linealizacion del TCSC). No incluirlo ahora
  permite tener un modelo EJECUTABLE y validar el DC-OPF + BESS +
  expansion de lineas como linea base (baseline) contra la cual medir,
  mas adelante, el aporte de FACTS.

  Las renovables NO entran en la objetivo: su costo marginal es ~0, su
  despacho lo fija la disponibilidad del recurso (ver tesis Cap. 3).
==================================================================
"""

import pyomo.environ as pyo


def build_objective(model, data):
    """
    Crea la funcion objetivo del modelo y se la agrega a `model`.

    Requiere build_sets, build_parameters y build_variables ejecutados
    antes (usa sus conjuntos, parametros y variables).

    model: ConcreteModel con sets, parametros y variables construidos.
    data : se mantiene por consistencia de firma (no se usa directamente).
    """

    # ------------------------------------------------------------------
    # Termino TERMICO: costo de generacion linealizado + arranque/parada
    # ------------------------------------------------------------------
    # Costo de generacion de la unidad g en t (forma linealizada):
    #   fg_min * u[g,t]  +  SUM_m slope[g,m] * dP_seg[g,m,t]
    # nota-python: una funcion interna mantiene la expresion legible.
    def costo_generacion(g, t):
        return (model.fg_min[g] * model.u[g, t]
                + sum(model.slope[g, m] * model.dP_seg[g, m, t]
                      for m in model.SEG_COST))

    costo_termico = sum(
        costo_generacion(g, t)
        + model.cost_SU[g] * model.SU[g, t]
        + model.cost_SD[g] * model.SD[g, t]
        for g in model.G for t in model.T
    )

    # ------------------------------------------------------------------
    # Termino HIDRAULICO: costo marginal * generacion hidraulica
    # ------------------------------------------------------------------
    # En el W&W H esta vacio -> esta suma da 0 (sin error). Queda listo
    # para el caso colombiano.
    costo_hidraulico = sum(
        model.C_h[h] * model.P_h[h, t]
        for h in model.H for t in model.T
    )
    
    # Factor de Recuperacion de Capital: anualiza el CAPEX.
    def _crf(i, n):
        i = float(pyo.value(i)); n = float(pyo.value(n))
        if i <= 0:
            return 1.0 / n
        return (i * (1 + i)**n) / ((1 + i)**n - 1)

    crf_linea = _crf(model.tasa_desc, model.vida_linea)
    crf_bess = _crf(model.tasa_desc, model.vida_bess)
    crf_facts = _crf(model.tasa_desc, model.vida_facts)

    # ------------------------------------------------------------------
    # Termino TRANSMISION: costo de construir lineas candidatas
    # ------------------------------------------------------------------
    # Suma sobre LC (vacio en W&W -> 0). x_l es binaria (construir o no).
    costo_transmision = crf_linea * sum(
        model.Cl[l] * model.x_l[l] for l in model.LC
    )

    # ------------------------------------------------------------------
    # Termino BESS: instalacion + dimensionamiento (potencia y energia)
    # ------------------------------------------------------------------
    # Suma sobre S (vacio en W&W -> 0).
    costo_bess = crf_bess * sum(
        model.Cs_inst * model.y_s[s]
        + model.Cs_power * model.Psmax[s]
        + model.Cs_energy * model.Esmax[s]
        for s in model.S
    )

    # ------------------------------------------------------------------
    # Termino FACTS: instalacion + compensacion del TCSC
    # ------------------------------------------------------------------
    # Suma sobre F (vacio si no hay candidatos -> 0). Cf_inst penaliza
    # instalar el TCSC. NOTA: el costo por tamano se omite aqui porque
    # dB_f puede ser negativo (compensacion capacitiva/inductiva) y
    # restaria costo erroneamente. Para penalizar la magnitud se
    # requeriria |dB_f| (variable auxiliar); se deja como afinamiento.
    costo_facts = crf_facts * sum(
        model.Cf_inst * model.z_f[f]
        + model.Cf_size * model.dB_abs[f]
        for f in model.F
    )

    # ------------------------------------------------------------------
    # Funcion objetivo total (minimizar)
    # ------------------------------------------------------------------
    model.obj = pyo.Objective(
        expr=(costo_termico + costo_hidraulico
              + costo_transmision + costo_bess + costo_facts),
        sense=pyo.minimize
    )

    return model
