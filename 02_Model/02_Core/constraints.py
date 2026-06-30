# -*- coding: utf-8 -*-
"""
==================================================================
 CONSTRAINTS
------------------------------------------------------------------
Autor : Daniel Lindo -- Universidad Nacional de Colombia (UNAL)
Tesis : Maestria en Ingenieria Electrica, 2026
------------------------------------------------------------------

Define las RESTRICCIONES: las ecuaciones e inecuaciones que el modelo
debe cumplir (las leyes fisicas y operativas del sistema).

Se construye POR BLOQUES (validables uno a uno):
  Bloque 1 -> DC-OPF basico : balance nodal, flujo DC, nodo slack,
              limites de flujo, y cota minima de generacion (para que
              el modelo ya resuelva).
  Bloque 2 -> Perdidas (Alguacil)         [TODO]
  Bloque 3 -> Generacion: limites, renovable, rampas   [TODO]
  Bloque 4 -> Unit Commitment (u, SU, SD)              [TODO]
  Bloque 5 -> BESS                                     [TODO]
  Bloque 6 -> Expansion de lineas (Big-M)              [TODO]

BUENAS PRACTICAS aplicadas:
  - lines_in / lines_out PRECOMPUTADOS: el balance nodal consulta dos
    diccionarios {nodo: [lineas]} en vez de recorrer todas las lineas
    preguntando a un DataFrame en cada nodo y hora (patron lento de
    Alvaro). Se calcula una sola vez.
  - Nombres legibles en cada Constraint (para leer el .lp exportado).
  - Sin DataFrames globales: todo entra por `data`/conjuntos.

Notacion: identica al Cap. 3 de la tesis.
==================================================================
"""

import pyomo.environ as pyo


def _incidencia(model, data):
    """
    Precomputa, para cada nodo, las lineas que ENTRAN y SALEN de el.

    Devuelve dos dicts {nodo: [lineas]}. Se calcula UNA vez (la topologia
    no cambia con el tiempo), evitando recorrer todas las lineas en cada
    nodo y periodo dentro de la restriccion de balance.

    Usa data.linea_from[l] y data.linea_to[l] (nodos extremos de cada
    linea), que el data_loader entrega. Convencion: el flujo f[l] es
    positivo de 'from' hacia 'to'.
    """
    # La comprensión de diccionarios (o dict comprehension) en Python es una
    # técnica concisa y elegante para crear, transformar y filtrar diccionarios
    # en una sola línea de código. Reemplaza los bucles for tradicionales, 
    # haciendo que el código sea más rápido, legible y fácil de mantener.
    # nuevo_diccionario = {clave: valor for elemento in iterable if condicion}
    #.append(): Este es un comando para añadir algo al final de una lista
    lines_in = {n: [] for n in model.N}   # lineas que llegan al nodo
    lines_out = {n: [] for n in model.N}  # lineas que salen del nodo
    for l in model.L_ALL:
        origen = data.linea_from[l]
        destino = data.linea_to[l]
        lines_out[origen].append(l)  # sale de 'origen'
        lines_in[destino].append(l)  # entra a 'destino'
    return lines_in, lines_out


def build_constraints(model, data):
    """
    Crea las restricciones del modelo y se las agrega a `model`.

    Requiere build_sets, build_parameters y build_variables ejecutados.

    model: ConcreteModel con sets, parametros y variables construidos.
    data : objeto con datos; aqui se usan linea_from / linea_to para la
           incidencia nodal.
    """

    # Incidencia nodal precomputada (buena practica #2).
    lines_in, lines_out = _incidencia(model, data)
    # se guardan en el modelo por si otros bloques los necesitan.
    model._lines_in = lines_in
    model._lines_out = lines_out

    # ==================================================================
    # Bloque 1 -- DC-OPF basico
    # ==================================================================

    # --- 1.1 Balance nodal -------------------------------------------
    # En cada nodo: generacion + flujos que entran + descarga BESS
    #   = demanda + flujos que salen + carga BESS
    # (las perdidas se anaden en el Bloque 2; aqui sin perdidas).
    # Se usa data para saber que generadores/BESS estan en cada nodo.
    gen_en_nodo = getattr(data, "gen_en_nodo", {})   # {nodo: [gen termica]}
    hid_en_nodo = getattr(data, "hid_en_nodo", {})   # {nodo: [hidro]}
    ren_en_nodo = getattr(data, "ren_en_nodo", {})   # {nodo: [renovable]}
    bess_en_nodo = getattr(data, "bess_en_nodo", {}) # {nodo: [bess]}
    # get = getattr pero para diccionarios
    #Mira qué generadores hay en la ciudad n. Si no hay ninguno, 
    # la suma es cero. Si hay generadores, ve uno por uno, 
    # busca cuánta potencia está produciendo cada uno en la hora t, 
    # suma todos esos valores y guarda el total en la variable gen
    def balance_nodal_rule(m, n, t):
        gen = sum(m.P_g[g, t] for g in gen_en_nodo.get(n, []))
        hid = sum(m.P_h[h, t] for h in hid_en_nodo.get(n, []))
        ren = sum(m.P_r[r, t] for r in ren_en_nodo.get(n, []))
        bess = sum(m.Pdis[s, t] - m.Pch[s, t]
                   for s in bess_en_nodo.get(n, []))
        entra = sum(m.f[l, t] for l in lines_in[n])
        sale = sum(m.f[l, t] for l in lines_out[n])
        return (gen + hid + ren + bess + entra
                == m.D[n, t] + sale)
    model.balance_nodal = pyo.Constraint(
        model.N, model.T, rule=balance_nodal_rule)

    # --- 1.2 Flujo DC en lineas existentes ---------------------------
    # f[l,t] = MVA_base * B[l] * (theta_i - theta_j)
    # Solo lineas existentes (L). Las candidatas (LC) se rigen por el
    # Bloque 6 (expansion con Big-M).
    def flujo_dc_rule(m, l, t):
        i = data.linea_from[l]
        j = data.linea_to[l]
        return m.f[l, t] == (m.MVA_base * m.susceptance[l]
                             * (m.theta[i, t] - m.theta[j, t]))
    model.flujo_dc = pyo.Constraint(model.L, model.T, rule=flujo_dc_rule)

    # --- 1.3 Nodo de referencia (slack) ------------------------------
    # El angulo del nodo de referencia se fija en 0 (los angulos son
    # relativos). Sin esto el flujo DC tiene infinitas soluciones.
    def slack_rule(m, t):
        return m.theta[m.nodo_ref, t] == 0
    model.ref_angular = pyo.Constraint(model.T, rule=slack_rule)

    # --- 1.4 Limites de flujo de linea -------------------------------
    # -Fmax <= f <= Fmax  (sin perdidas aqui; el medio-Ploss del Cap. 3
    # se anade en el Bloque 2). Solo lineas existentes por ahora.
    def flujo_max_rule(m, l, t):
        return m.f[l, t] <= m.flow_max[l]
    model.flujo_max = pyo.Constraint(model.L, model.T, rule=flujo_max_rule)

    def flujo_min_rule(m, l, t):
        return m.f[l, t] >= -m.flow_max[l]
    model.flujo_min = pyo.Constraint(model.L, model.T, rule=flujo_min_rule)

    # --- 1.5 Cota de generacion termica (version minima) -------------
    # 0 <= P_g <= Pmax. Version simple para que el modelo CIERRE y
    # resuelva ya. El limite con Pmin y unit commitment (Pmin*u <= Pg)
    # llega en el Bloque 3/4. Por eso es "minima" y provisional.
    # TODO: reemplazar por limites con UC (Pmin*u <= Pg <= Pmax*u).
    def gen_max_rule(m, g, t):
        return m.P_g[g, t] <= m.Pmax[g]
    model.gen_max = pyo.Constraint(model.G, model.T, rule=gen_max_rule)

    # ==================================================================
    # TODO -- Bloques 2-6 (perdidas, generacion completa, UC, BESS,
    # expansion) y FACTS. Se anaden incrementalmente.
    # ==================================================================

    return model
