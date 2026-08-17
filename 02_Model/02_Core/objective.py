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
  BESS  : delta_T * SUM_s (Cs^P_anual*Psmax + Cs^E_anual*Esmax)
  FACTS : delta_T * SUM_f SUM_z Cf^anual_{f,z} * kappa_{f,z}
  con delta_T = |T|/8760

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
    
    
    # ================================================================
    # Inversion. Los costos anuales equivalentes (FRC ya aplicado) se
    # definen como parametros en parameters.py / data_loader.py. Aqui
    # solo se escala al horizonte simulado.
    #   delta_T = |T| / 8760  ->  horizonte expresado en anios
    # ================================================================
    def _crf(r, n):
        # Factor de Recuperacion de Capital (Qiu et al. 2017;
        # Zakeri & Syri, 2015). r=tasa, n=vida util en anios.
        return (r * (1 + r)**n) / ((1 + r)**n - 1)

    crf_bess  = _crf(model.tasa_desc, model.vida_bess)    # 15 anios
    crf_facts = _crf(model.tasa_desc, model.vida_facts)   # 20 anios

    # Horizonte simulado expresado en anios. Lleva el costo anual
    # equivalente a la misma base temporal que los costos de operacion.
    # Se adapta a cualquier horizonte: 1 h, 24 h, 1 mes, 1 anio.
    delta_T = len(model.T) / 8760.0

    costo_bess = delta_T * crf_bess * sum(
        model.Cs_power * model.Psmax[s] + model.Cs_energy * model.Esmax[s]
        for s in model.S
    )

    costo_facts = delta_T * crf_facts * sum(
        model.Cf_capex[f, z] * model.kappa[f, z]
        for f in model.F for z in model.Z
    )

    dias_simulados = len(model.T) / 24.0

    # Costo anual equivalente (EAC) prorrateado a los dias simulados
    costo_bess = (dias_simulados / 365.0) * sum(
        crf_bess * (model.Cs_power * model.Psmax[s]
                     + model.Cs_energy * model.Esmax[s])
        for s in model.S
    )

    # Costo FACTS: un unico costo por par (linea, bloque de compensacion),
    # que ya embebe instalacion y dimensionamiento. No se separa en
    # C_inst*z + C_size*X porque ninguna de las referencias revisadas
    # (Ziaee 2018, Luburic 2020, Esmaili 2020, Wu 2023) usa esa
    # separacion.
    costo_facts = (dias_simulados / 365.0) * sum(
        crf_facts * model.Cf_capex[f, z] * model.kappa[f, z]
        for f in model.F for z in model.Z
    )

    # ------------------------------------------------------------------
    # Penalizacion del vertimiento. No representa un costo real: es un
    # termino de regularizacion que rompe la degeneracion entre turbinar
    # y verter. Sin el, el solver reparte arbitrariamente entre q_h y S_h
    # porque ambos son indiferentes para la funcion objetivo.
    # ------------------------------------------------------------------
    costo_vert = model.c_vert * sum(model.S_h[h, t]
                                    for h in model.H for t in model.T)

    model.obj = pyo.Objective(
        expr=(costo_termico + costo_hidraulico
              + costo_bess + costo_facts + costo_vert),
        sense=pyo.minimize
    )

    return model
