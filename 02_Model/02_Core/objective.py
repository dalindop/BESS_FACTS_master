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
    
    # ================================================================
    # Prorrateo de la inversion (metodo Kim et al0. 218): 
    # el CAPEX se divide entre los dias de vida util,
    # dando un costo por dia. Se multiplica por los dias simulados
    # para ser coherente con el horizonte de operacion.
    # Con interés (recuperacion lineal simple).
    # ================================================================
    def _crf(r, n):
        # Factor de Recuperacion de Capital (Qiu et al. 2017;
        # Zakeri & Syri, 2015). r=tasa, n=vida util en anios.
        return (r * (1 + r)**n) / ((1 + r)**n - 1)

    crf_bess = _crf(model.tasa_desc, model.vida_bess)
    crf_facts = _crf(model.tasa_desc, model.vida_facts)

    dias_simulados = len(model.T) / 24.0

    # Costo anual equivalente (EAC) prorrateado a los dias simulados
    costo_bess = (dias_simulados / 365.0) * sum(
        crf_bess * (model.Cs_power * model.Psmax[s]
                     + model.Cs_energy * model.Esmax[s])
        for s in model.S
    )

    costo_facts = (dias_simulados / 365.0) * sum(
        crf_facts * (model.Cf_inst * model.z_f[f]
                      + model.Cf_size * model.dB_abs[f])
        for f in model.F
    )

    model.obj = pyo.Objective(
        expr=(costo_termico + costo_hidraulico
              + costo_bess + costo_facts),
        sense=pyo.minimize
    )

    return model
