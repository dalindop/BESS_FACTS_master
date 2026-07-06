# -*- coding: utf-8 -*-
"""
==================================================================
  VARIABLES
------------------------------------------------------------------
Autor : Daniel Lindo -- Universidad Nacional de Colombia (UNAL)
Tesis : Maestria en Ingenieria Electrica, 2026
------------------------------------------------------------------

Define las VARIABLES de decision: lo que el solver DECIDE (a diferencia
de los parametros, que son datos fijos). Se dividen en:
  - binarias  : decisiones discretas (construir linea, instalar BESS,
                encender generador...).
  - continuas : magnitudes operativas (potencias, flujos, angulos,
                energia almacenada, dimensionamiento...).

ALCANCE DE ESTE PASO (migracion incremental):
  Bloque 1 -> OPERACION    (despacho, flujo, angulos, perdidas)
  Bloque 2 -> UNIT COMMIT.  (estado on/off, arranque, parada)
  Bloque 3 -> BESS          (carga/descarga, SOC, dimensionamiento)
  Bloque 4 -> INVERSION     (construir linea x_l, instalar BESS y_s)
  El bloque FACTS (z_f, X_f) se añade despues, cuando se decida la
  linealizacion del TCSC (la ecuacion del flujo con FACTS es bilineal
  y requiere linealizacion antes de declararse). Marcado como TODO.

NOTACION: identica a la tabla de variables del Cap. 3 de la tesis.
  Binarias : x_l, y_s, u[g,t], SU[g,t], SD[g,t], u_ch[s,t], u_dis[s,t]
  Continuas: P[g,t], P[h,t], P[r,t], Pcurt[r,t], f[ij,t], theta[i,t],
             Pch[s,t], Pdis[s,t], SoC[s,t], Psmax[s], Esmax[s]
==================================================================
"""

import pyomo.environ as pyo

def build_variables(model, data):
    """
    Crea las variables de decision del modelo y se las agrega a `model`.

    Requiere build_sets(model, data) ejecutado antes

    model: ConcreteModel de Pyomo con los SETS ya construidos.
    data : no se usa directamente aqui, se mantiene por consistencia de
           firma con los demas modulos (sets, parameters).
    """

    # ==================================================================
    # Bloque 1 -- variables de OPERACION (continuas)
    # ==================================================================
    # Generacion por tecnologia. NonNegativeReals = no pueden ser < 0.
    # note-python: domain=pyo.NonNegativeReals obliga a que el solver no asigne valores
    # negativos a estas variables.
    model.P_g = pyo.Var(model.G, model.T, domain=pyo.NonNegativeReals)
    model.P_h = pyo.Var(model.H, model.T, domain=pyo.NonNegativeReals)
    model.P_r = pyo.Var(model.R, model.T, domain=pyo.NonNegativeReals)

    # Vertimiento renovable (curtailment): energia renovable disponible
    # que se decide NO usar. Tesis: Pr,t^curt.
    model.Pcurt = pyo.Var(model.R, model.T, domain=pyo.NonNegativeReals)

    # Flujo de potencia en cada linea. Se define sobre L_ALL = L U LC
    # (existentes + candidatas). Domain=Reals: el flujo puede ser
    # negativo (sentido contrario al de referencia de la linea).
    model.f = pyo.Var(model.L_ALL, model.T, domain=pyo.Reals)

    # Angulo de fase de cada nodo. Reals (puede ser +/-). Tesis: theta_i.
    model.theta = pyo.Var(model.N, model.T, domain=pyo.Reals)

    # Perdidas por linea (linealizadas, Alguacil). Siempre >= 0.
    # Se definen tambien sobre L_ALL para cubrir lineas candidatas.
    model.Ploss = pyo.Var(model.L_ALL, model.T,
                          domain=pyo.NonNegativeReals)

    # Auxiliares de la linealizacion de perdidas (Alguacil et al., 2003):
    #   delta+ , delta- : partes positiva y negativa de la dif. angular.
    #   delta_seg[l,k,t]: aporte del bloque k a esa diferencia.
    model.delta_pos = pyo.Var(model.L_ALL, model.T,
                              domain=pyo.NonNegativeReals)
    model.delta_neg = pyo.Var(model.L_ALL, model.T,
                              domain=pyo.NonNegativeReals)
    model.delta_seg = pyo.Var(model.L_ALL, model.SEG_PERD, model.T,
                              domain=pyo.NonNegativeReals)

    # Aporte de potencia por segmento de la linealizacion de COSTO de
    # generacion termica. Tesis: deltaP_g,m,t (conjunto M = SEG_COST).
    # Acotado en [0, deltaP] por restriccion (no aqui).
    # dP_seg = diffPg_m,t en tesis
    model.dP_seg = pyo.Var(model.G, model.SEG_COST, model.T,
                           domain=pyo.NonNegativeReals)

    # ==================================================================
    # Bloque 2 -- variables de UNIT COMMITMENT (binarias)
    # ==================================================================
    # Estado encendido/apagado, arranque y parada de cada termica.
    # Tesis: u_g,t ; SU_g,t ; SD_g,t.  Binary = {0, 1}.
    model.u  = pyo.Var(model.G, model.T, domain=pyo.Binary)  # on/off
    model.SU = pyo.Var(model.G, model.T, domain=pyo.Binary)  # arranque
    model.SD = pyo.Var(model.G, model.T, domain=pyo.Binary)  # parada

    # ==================================================================
    # Bloque 3 -- variables de BESS
    # ==================================================================
    # Operacion: potencia de carga y descarga, y estado de carga (SOC).
    # Tesis: Ps,t^ch , Ps,t^dis , SoC_s,t.
    model.Pch  = pyo.Var(model.S, model.T, domain=pyo.NonNegativeReals)
    model.Pdis = pyo.Var(model.S, model.T, domain=pyo.NonNegativeReals)
    model.SoC  = pyo.Var(model.S, model.T, domain=pyo.NonNegativeReals)

    # Estados binarios de carga/descarga (evitan cargar y descargar a la
    # vez). Tesis: u_s,t^ch , u_s,t^dis.
    model.u_ch  = pyo.Var(model.S, model.T, domain=pyo.Binary)
    model.u_dis = pyo.Var(model.S, model.T, domain=pyo.Binary)

    # Dimensionamiento (decision de inversion continua): potencia y
    # energia instaladas del BESS. Tesis: Ps^max , Es^max. Indexadas
    # solo por nodo s (no por tiempo): se decide una vez.
    model.Psmax = pyo.Var(model.S, domain=pyo.NonNegativeReals)
    model.Esmax = pyo.Var(model.S, domain=pyo.NonNegativeReals)

    # ==================================================================
    # Bloque 4 -- variables de INVERSION (binarias)
    # ==================================================================
    # Construir o no cada linea candidata. Tesis: x_l, l in LC.
    model.x_l = pyo.Var(model.LC, domain=pyo.Binary)

    # Instalar o no BESS en cada nodo candidato. Tesis: y_s, s in S.
    model.y_s = pyo.Var(model.S, domain=pyo.Binary)

    # ==================================================================
    # TODO -- bloque HIDRAULICO DE EMBALSE (diferido al caso colombiano):
    #   V[h,t]  : volumen almacenado en el embalse        (hm3).
    #   q[h,t]  : caudal turbinado de la unidad h          (m3/s).
    #   S[h,t]  : vertimiento del embalse (spillage)       (hm3).
    # P_h (generacion hidraulica) YA esta declarada arriba (operacion).
    # Estas tres variables van con su restriccion de balance hidrico
    #   V[h,t] = V[h,t-1] + I[h,t] - q[h,t] - S[h,t]
    # y solo tienen sentido con datos de embalses (conjunto H y embalses
    # vacios en el W&W). Se anaden al migrar al sistema colombiano.
    # ==================================================================

    # ==================================================================
    # Bloque FACTS (TCSC) -- formulacion 2018 (Big-M, doble nivel)
    # ==================================================================
    # z_f    : binaria, instalar TCSC en la linea f (tesis: zf).
    # dB_f   : continua, susceptancia adicional del TCSC (tesis: dBf).
    # psi_f  : continua, flujo inducido por el TCSC (tesis: psi_ij,t).
    #          El flujo de la linea con TCSC es  f = B*theta + psi.
    # v_f    : auxiliar continua = z_f * theta (2do nivel de linealiz.,
    #          resuelve el producto binaria*angulo dentro de psi).
    # y_f    : binaria, direccion del flujo (para el Big-M complementario
    #          del nivel 1, ecuaciones 9-10 del paper 2018).
    model.z_f = pyo.Var(model.F, domain=pyo.Binary)
    model.dB_f = pyo.Var(model.F, domain=pyo.Reals)
    model.psi_f = pyo.Var(model.F, model.T, domain=pyo.Reals)
    model.v_f = pyo.Var(model.F, model.T, domain=pyo.Reals)
    model.y_f = pyo.Var(model.F, model.T, domain=pyo.Binary)
    # ==================================================================

    return model
