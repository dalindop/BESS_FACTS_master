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
  Bloque 2 -> Perdidas (Alguacil)        
  Bloque 3 -> Generacion: limites, renovable, rampas   
  Bloque 4 -> Unit Commitment (u, SU, SD)              
  Bloque 5 -> BESS                                     
  Bloque 6 -> Expansion de lineas (Big-M)              

BUENAS PRACTICAS aplicadas:
  - lines_in / lines_out PRECOMPUTADOS: el balance nodal consulta dos
    diccionarios {nodo: [lineas]} en vez de recorrer todas las lineas
    preguntando a un DataFrame en cada nodo y hora (patron lento de
    Alvaro). Se calcula una sola vez.
  - Nombres legibles en cada Constraint (para leer el .lp exportado).
  - Sin DataFrames globales: todo entra por `data`/conjuntos.

Notacion: identica al Cap. 3 de la tesis.

# NOTA: las restricciones de caudal minimo (3c.3, cota inferior),
# variacion de caudal (3c.8) y vertimiento maximo (3c.6) se
# implementan pero quedan inactivas mediante Constraint.Skip cuando
# el parametro correspondiente es cero. Ningun parametro publico del
# sistema colombiano los define (ver Cap.3, "Alcance de la
# implementacion").
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
    # Σ(fji − fij) de ahí sale esta matriz de incidencia
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
    
    # --- Construccion efectiva de cada linea -------------------------
    # Enfoque UNIFICADO: las lineas existentes se tratan como candidatas
    # ya construidas. x_eff(l) vale la variable binaria x_l si la linea
    # es candidata (l in LC), o la constante 1 si es existente (l in L).
    # Asi las restricciones de red se escriben una sola vez sobre L_ALL:
    # para existentes el Big-M nunca relaja (x_eff=1); para candidatas se
    # relaja si no se construyen (x_eff=0 -> flujo y perdidas forzados a 0).
    # ELIMINADA función en la tesis.
    # def x_eff(l):
    #     return model.x_l[l] if l in model.LC else 1
    def x_eff(l):
        return 1 # sin lineas candidatas: todas las lineas existen siempre
 
    # Big-M fisico por linea: maxima diferencia posible entre el flujo y
    # el termino B*(delta+ - delta-). Se acota por la capacidad de la
    # linea (flujo maximo). Valor FISICO, no 1e20 (evita inestabilidad).
    def big_m(l):
        return model.flow_max[l]

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
    # Mira qué generadores hay en la ciudad n. Si no hay ninguno, 
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
        # medio-perdidas de todas las lineas conectadas al nodo (la otra
        # mitad la cubre el nodo del otro extremo). Tesis: 0.5*sum Ploss.
        # incluir_perdidas es para activar/desactivar el calculo de perdidas 
        # (para comparar con el caso sin perdidas). Se multiplica por 0.5
        perdidas = m.incluir_perdidas * 0.5 * sum(
            m.Ploss[l, t] for l in (lines_in[n] + lines_out[n]))
        return (gen + hid + ren + bess + entra
                == m.D[n, t] + sale + perdidas)
    model.balance_nodal = pyo.Constraint(
        model.N, model.T, rule=balance_nodal_rule)

    # --- 1.2 Descomposicion angular + Flujo DC (unificado L_ALL) ------
    # La diferencia angular (theta_i - theta_j) se descompone en parte
    # positiva y negativa:  theta_i - theta_j = delta_pos - delta_neg.
    # Esta descomposicion se comparte con las perdidas (Bloque 2), que
    # usan el valor absoluto |theta_i - theta_j| = delta_pos + delta_neg.
    # El solver fuerza una de las dos a cero porque las perdidas tienen
    # costo implicito (mecanismo auto-consistente de Alguacil).    
    # La diferencia angular se descompone en parte positiva y negativa.
    # Para lineas CANDIDATAS, la igualdad se relaja con Big-M: solo se
    # cumple si la linea se construye (x_eff=1). Para existentes (x_eff=1
    # fijo) el termino Big-M*(1-1)=0, asi que la igualdad es exacta.
    # Se escribe como dos desigualdades (relajacion Big-M bilateral):
    #   -M(1-x) <= (theta_i - theta_j) - (delta+ - delta-) <= M(1-x)
    def desc_ang_sup_rule(m, l, t):
        i = data.linea_from[l]
        j = data.linea_to[l]
        return ((m.theta[i, t] - m.theta[j, t])
                - (m.delta_pos[l, t] - m.delta_neg[l, t])
                <= big_m(l) * (1 - x_eff(l)))
    model.desc_ang_sup = pyo.Constraint(
        model.L_ALL, model.T, rule=desc_ang_sup_rule)
    
    def desc_ang_inf_rule(m, l, t):
        i = data.linea_from[l]
        j = data.linea_to[l]
        return ((m.theta[i, t] - m.theta[j, t])
                - (m.delta_pos[l, t] - m.delta_neg[l, t])
                >= -big_m(l) * (1 - x_eff(l)))
    model.desc_ang_inf = pyo.Constraint(
        model.L_ALL, model.T, rule=desc_ang_inf_rule)

    # Flujo DC (sobre L_ALL): f = MVA * B * (delta+ - delta-)
    # Las lineas con TCSC (conjunto F) se EXCLUYEN aqui: su flujo lo
    # define facts_flujo (bloque FACTS), que anade el termino psi.
    def flujo_dc_rule(m, l, t):
        if l in m.F:
            return pyo.Constraint.Skip
        return m.f[l, t] == (m.MVA_base * m.susceptance[l]
                             * (m.delta_pos[l, t] - m.delta_neg[l, t]))
    model.flujo_dc = pyo.Constraint(
        model.L_ALL, model.T, rule=flujo_dc_rule)

    # --- 1.3 Nodo de referencia (slack) ------------------------------
    # El angulo del nodo de referencia se fija en 0 (los angulos son
    # relativos). Sin esto el flujo DC tiene infinitas soluciones.
    def slack_rule(m, t):
        return m.theta[m.nodo_ref, t] == 0
    model.ref_angular = pyo.Constraint(model.T, rule=slack_rule)

    # --- 1.4 Limites de flujo (sobre L_ALL, con medio-perdidas y x) ---
    # Tesis (Cap. 3): -Fmax <= f + 0.5*Ploss <= Fmax. Las perdidas se
    # reparten mitad en cada extremo de la linea. Ploss se define en el
    # Bloque 2; aqui ya se incluye el termino 0.5*Ploss.    
    # -Fmax*x <= f + 0.5*Ploss ... y ... -f + 0.5*Ploss <= Fmax*x
    # Si la candidata no se construye (x=0): el flujo se fuerza a 0 y,
    # como delta_seg tambien se anula (ver 2.2), Ploss=0.
    def flujo_max_rule(m, l, t):
        return (m.f[l, t] + m.incluir_perdidas * 0.5 * m.Ploss[l, t]
                <= m.flow_max[l] * x_eff(l))
    model.flujo_max = pyo.Constraint(
        model.L_ALL, model.T, rule=flujo_max_rule)
 
    def flujo_min_rule(m, l, t):
        return (-m.f[l, t] + m.incluir_perdidas * 0.5 * m.Ploss[l, t]
                <= m.flow_max[l] * x_eff(l))
    model.flujo_min = pyo.Constraint(
        model.L_ALL, model.T, rule=flujo_min_rule)

    # --- 1.5 (eliminada) ---------------------------------------------
    # La cota provisional 0<=Pg<=Pmax del Bloque 1 fue reemplazada por
    # las restricciones de generacion con UC del Bloque 3 (pot_min,
    # pot_max), que son las de la tesis.
    
    # ==================================================================
    # Bloque 2 -- PERDIDAS LINEALIZADAS (Alguacil et al., 2003)
    # ==================================================================
    # --- 2.1 Suma de bloques = valor absoluto de la dif. angular ------
    def perd_suma_bloques_rule(m, l, t):
        return (sum(m.delta_seg[l, k, t] for k in m.SEG_PERD)
                == m.delta_pos[l, t] + m.delta_neg[l, t])
    model.perd_suma_bloques = pyo.Constraint(
        model.L_ALL, model.T, rule=perd_suma_bloques_rule)

    # --- 2.2 Cota de cada bloque -------------------------------------
    # delta_seg <= delta_theta * x_eff. Para existentes (x_eff=1) es la
    # cota normal. Para candidatas NO construidas (x_eff=0) fuerza
    # delta_seg=0 -> suma de bloques=0 -> Ploss=0. Asi una linea que no
    # existe no tiene perdidas (clave del enfoque, cf. Zhang 2012).
    import math
    
    # Rango angular total permitido, leido de Config (theta_max_grados).
    # El ancho de CADA bloque es theta_max / K (K = n_seg_perdidas), no
    # theta_max completo: cada tramo cubre una fraccion igual del rango
    # total (Alguacil et al., 2003). El mismo valor alimenta los Big-M
    # del bloque FACTS, de modo que no pueden desincronizarse.
    
    #theta_max_total = 20 * math.pi / 180
    theta_max_total = data.theta_max_total
    ancho_seg_perd = theta_max_total / len(model.SEG_PERD)

    def perd_bloque_max_rule(m, l, k, t):
        return m.delta_seg[l, k, t] <= ancho_seg_perd * x_eff(l)
    model.perd_bloque_max = pyo.Constraint(
        model.L_ALL, model.SEG_PERD, model.T, rule=perd_bloque_max_rule)
    
    # --- 2.3 Calculo de las perdidas ---------------------------------
    # 
    # def perd_calculo_rule(m, l, t):
    #     return m.Ploss[l, t] == (
    #         m.MVA_base * m.conductance[l]
    #         * sum(m.alpha[k] * m.delta_seg[l, k, t] for k in m.SEG_PERD))
    # model.perd_calculo = pyo.Constraint(
    #     model.L_ALL, model.T, rule=perd_calculo_rule)
    
    # Ploss = MVA*[G*sum_k(alpha*delta) + sum_z dG*Lambda]   [ec. 3-13]
    # El segundo termino solo aplica a lineas candidatas a TCSC y captura
    # el cambio de conductancia (Luburic et al. 2020, ec. 20). Sin el, el
    # modelo subestimaria las perdidas de la linea compensada en (1-sigma)^2.
    
    # Ploss = MVA*[G*sum_k(alpha*delta) + sum_z dG*Lambda]
    # El segundo termino solo aplica a lineas candidatas a TCSC (Luburic
    # et al. 2020, ec.20). Sin el, se subestiman las perdidas de la linea
    # compensada en un factor (1-sigma)^2.
    def perd_calculo_rule(m, l, t):
        base = (m.MVA_base * m.conductance[l]
                * sum(m.alpha[k] * m.delta_seg[l, k, t] for k in m.SEG_PERD))
        if l in m.F:
            return m.Ploss[l, t] == base + m.MVA_base * sum(
                m.dG[l, z] * m.lam[l, z, t] for z in m.Z)
        return m.Ploss[l, t] == base

    model.perd_calculo = pyo.Constraint(
        model.L_ALL, model.T, rule=perd_calculo_rule)
 
    # ==================================================================
    # Bloque 3 -- GENERACION TERMICA (limites + conexion con el costo)
    # ==================================================================
    # Estas restricciones CONECTAN la potencia generada Pg con las
    # variables que cuestan (u, dP_seg). Sin ellas el costo da 0.
    # Formulacion identica a la tesis (Cap. 3) y a Avendano.
 
    # --- 3.1 Composicion de la potencia (la pieza que activa el costo)-
    # Pg,t = Pgmin*u + SUM_m dP_seg[g,m,t]
    # La generacion = minimo tecnico (si esta encendida) + aportes de
    # cada segmento de la linealizacion de costo.
    def pot_compuesta_rule(m, g, t):
        return m.P_g[g, t] == (m.Pmin[g] * m.u[g, t]
                               + sum(m.dP_seg[g, mm, t]
                                     for mm in m.SEG_COST))
    model.pot_compuesta = pyo.Constraint(
        model.G, model.T, rule=pot_compuesta_rule)
 
    # --- 3.2 Limite minimo con unit commitment -----------------------
    # Pg,t >= Pgmin * u   (si esta apagada, Pg=0; si encendida, >= Pmin)
    def pot_min_rule(m, g, t):
        return m.P_g[g, t] >= m.Pmin[g] * m.u[g, t]
    model.pot_min = pyo.Constraint(model.G, model.T, rule=pot_min_rule)
 
    # --- 3.3 Limite maximo con unit commitment -----------------------
    # Pg,t <= Pgmax * u
    def pot_max_rule(m, g, t):
        return m.P_g[g, t] <= m.Pmax[g] * m.u[g, t]
    model.pot_max = pyo.Constraint(model.G, model.T, rule=pot_max_rule)
 
    # --- 3.4 Ancho de cada segmento de costo -------------------------
    # 0 <= dP_seg[g,m,t] <= deltaP_g * u
    # Cada segmento aporta como maximo el ancho del tramo (deltaP_g), y
    # solo si la unidad esta encendida. deltaP_g = (Pmax-Pmin)/M, igual
    # que en la linealizacion de costo (tesis: ancho de segmento igual).
    n_seg = len(model.SEG_COST)
 
    def seg_max_rule(m, g, mm, t):
        delta_p = (m.Pmax[g] - m.Pmin[g]) / n_seg
        return m.dP_seg[g, mm, t] <= delta_p * m.u[g, t]
    model.seg_max = pyo.Constraint(
        model.G, model.SEG_COST, model.T, rule=seg_max_rule)
    
    # ==================================================================
    # Bloque 3c -- GENERACION HIDRAULICA (tesis Cap.3)
    # ==================================================================
    # Referencias: Soroudi (2017, pp. 80, 83); Wood & Wollenberg (2013,
    # p.18); Qiu et al. (2017, p.646).

    # --- 3c.1 Limite de generacion  Pmin <= P_h <= Pmax --------------
    def hid_lim_pot_rule(m, h, t):
        return (m.Pmin_h[h], m.P_h[h, t], m.Pmax_h[h])
    model.hid_lim_pot = pyo.Constraint(model.H, model.T,
                                       rule=hid_lim_pot_rule)

    # --- 3c.2 Relacion potencia-caudal  P = eta * q ------------------
    def hid_pot_caudal_rule(m, h, t):
        if pyo.value(m.eta_h[h]) <= 0:
            return pyo.Constraint.Skip
        return m.P_h[h, t] == m.eta_h[h] * m.q_h[h, t]
    model.hid_pot_caudal = pyo.Constraint(model.H, model.T,
                                          rule=hid_pot_caudal_rule)

    # --- 3c.3 Limite de caudal  qmin <= q <= qmax --------------------
    def hid_lim_caudal_rule(m, h, t):
        if pyo.value(m.qmax_h[h]) <= 0:      # ← si no hay dato, se salta
            return pyo.Constraint.Skip
        return (m.qmin_h[h], m.q_h[h, t], m.qmax_h[h])
    model.hid_lim_caudal = pyo.Constraint(model.H, model.T,
                                          rule=hid_lim_caudal_rule)

    # --- 3c.4 Balance del embalse -----------------------------------
    # V_t = V_{t-1} + I_t - k*(q_t + S_t).  k convierte m3/s -> hm3/h.
    def hid_balance_rule(m, h, t):
        if pyo.value(m.Vmax_h[h]) <= 0:
            return pyo.Constraint.Skip
        v_ant = m.Vinit_h[h] if t == m.T.first() else m.V_h[h, t - 1]
        return (m.V_h[h, t] == v_ant + m.I_h[h, t]
                - m.k_q2v * (m.q_h[h, t] + m.S_h[h, t]))
    model.hid_balance = pyo.Constraint(model.H, model.T,
                                       rule=hid_balance_rule)

    # --- 3c.5 Limites de volumen ------------------------------------
    def hid_lim_vol_rule(m, h, t):
        if pyo.value(m.Vmax_h[h]) <= 0:
            return pyo.Constraint.Skip
        return (m.Vmin_h[h], m.V_h[h, t], m.Vmax_h[h])
    model.hid_lim_vol = pyo.Constraint(model.H, model.T,
                                       rule=hid_lim_vol_rule)

    # --- 3c.6 Limite de vertimiento ---------------------------------
    def hid_lim_vert_rule(m, h, t):
        if pyo.value(m.Smax_h[h]) <= 0:      # ← si no hay dato, se salta
            return pyo.Constraint.Skip
        return m.S_h[h, t] <= m.Smax_h[h]
    model.hid_lim_vert = pyo.Constraint(model.H, model.T,
                                        rule=hid_lim_vert_rule)

    # --- 3c.7 Volumen final dentro de una banda del inicial ---------
    # Se relaja el cierre exacto V_T = V_init porque cuatro embalses
    # reciben aportes incompletos: XM no publica series para los rios
    # TUNJITA, RUCIO, NEGRO y BRAVO.
    def hid_vol_final_sup_rule(m, h):
        if pyo.value(m.Vmax_h[h]) <= 0:
            return pyo.Constraint.Skip
        tol = m.tol_vol * (m.Vmax_h[h] - m.Vmin_h[h])
        return m.V_h[h, m.T.last()] <= m.Vinit_h[h] + tol
    model.hid_vol_final_sup = pyo.Constraint(model.H,
                                             rule=hid_vol_final_sup_rule)

    def hid_vol_final_inf_rule(m, h):
        if pyo.value(m.Vmax_h[h]) <= 0:
            return pyo.Constraint.Skip
        tol = m.tol_vol * (m.Vmax_h[h] - m.Vmin_h[h])
        return m.V_h[h, m.T.last()] >= m.Vinit_h[h] - tol
    model.hid_vol_final_inf = pyo.Constraint(model.H,
                                             rule=hid_vol_final_inf_rule)

    # --- 3c.8 Variacion maxima de caudal (en valor absoluto) --------
    # |q_t - q_{t-1}| <= Rq  se descompone en dos desigualdades.
    def hid_rampa_sub_rule(m, h, t):
        if t == m.T.first() or pyo.value(m.Rq_h[h]) <= 0:   # ← igual
            return pyo.Constraint.Skip
        return m.q_h[h, t] - m.q_h[h, t - 1] <= m.Rq_h[h]
    model.hid_rampa_sub = pyo.Constraint(model.H, model.T,
                                         rule=hid_rampa_sub_rule)

    def hid_rampa_baj_rule(m, h, t):
        if t == m.T.first() or pyo.value(m.Rq_h[h]) <= 0:
            return pyo.Constraint.Skip
        return m.q_h[h, t - 1] - m.q_h[h, t] <= m.Rq_h[h]
    model.hid_rampa_baj = pyo.Constraint(model.H, model.T,
                                         rule=hid_rampa_baj_rule)
    
    # ==================================================================
    # Bloque 3b -- GENERACION RENOVABLE (con curtailment)
    # ==================================================================
    # Formulacion de la tesis (Forma B): la energia disponible se reparte
    # entre lo generado (P_r) y lo vertido/desperdiciado (Pcurt).
    # Permite medir cuanta energia renovable se desaprovecha.
 
    # --- 3b.1 Reparto disponibilidad = generado + vertido ------------
    # P_r[r,t] + Pcurt[r,t] = disp_renov[r,t]
    def renov_reparto_rule(m, r, t):
        return m.P_r[r, t] + m.Pcurt[r, t] == m.disp_renov[r, t]
    model.renov_reparto = pyo.Constraint(
        model.R, model.T, rule=renov_reparto_rule)
 
    # --- 3b.2 Limite de generacion renovable -------------------------
    # 0 <= P_r <= disp_renov (no puede generar mas que lo disponible).
    # El limite inferior lo da el dominio NonNegativeReals de la variable.
    def renov_max_rule(m, r, t):
        return m.P_r[r, t] <= m.disp_renov[r, t]
    model.renov_max = pyo.Constraint(
        model.R, model.T, rule=renov_max_rule)
    
     
    # ==================================================================
    # Bloque 4 -- UNIT COMMITMENT (logica de arranque/parada)
    # ==================================================================
    # Formulacion TIGHT de 3 binarias (u, SU, SD), la mas eficiente para
    # el solver (Morales-Espana et al.; misma que usa Avendano).
    # nota-python: T.first() y T.prev(t) dan el primer periodo y el
    # anterior, respetando el orden del conjunto.
 
    # --- 4.1 Consistencia arranque/parada vs cambio de estado --------
    # SU[g,t] - SD[g,t] = u[g,t] - u[g,t-1]
    # Si la unidad pasa de OFF a ON -> SU=1; de ON a OFF -> SD=1.
    # En el primer periodo se usa el estado inicial onoff_t0.
    # Esta es la restriccion que hace la formulacion "tight".
    def uc_consistencia_rule(m, g, t):
        if t == m.T.first():
            previo = m.onoff_t0[g]
        else:
            previo = m.u[g, m.T.prev(t)]
        return m.SU[g, t] - m.SD[g, t] == m.u[g, t] - previo
    model.uc_consistencia = pyo.Constraint(
        model.G, model.T, rule=uc_consistencia_rule)
 
    # --- 4.2 No arrancar y parar en el mismo periodo -----------------
    # SU[g,t] + SD[g,t] <= 1
    def uc_excluyente_rule(m, g, t):
        return m.SU[g, t] + m.SD[g, t] <= 1
    model.uc_excluyente = pyo.Constraint(
        model.G, model.T, rule=uc_excluyente_rule)
 
    # --- 4.3 Tiempo minimo de ENCENDIDO ------------------------------
    # Si la unidad arranco en algun momento de las ultimas L_up_min
    # horas, debe seguir encendida ahora:
    #   sum_{tau = t-L_up_min+1 .. t} SU[g,tau] <= u[g,t]
    def min_up_rule(m, g, t):
        lmin = m.L_up_min[g]
        ventana = [tau for tau in m.T if t - lmin + 1 <= tau <= t]
        return sum(m.SU[g, tau] for tau in ventana) <= m.u[g, t]
    model.min_up = pyo.Constraint(model.G, model.T, rule=min_up_rule)
 
    # --- 4.4 Tiempo minimo de APAGADO --------------------------------
    # Si la unidad paro en las ultimas L_down_min horas, debe seguir
    # apagada ahora:
    #   sum_{tau = t-L_down_min+1 .. t} SD[g,tau] <= 1 - u[g,t]
    def min_down_rule(m, g, t):
        lmin = m.L_down_min[g]
        ventana = [tau for tau in m.T if t - lmin + 1 <= tau <= t]
        return sum(m.SD[g, tau] for tau in ventana) <= 1 - m.u[g, t]
    model.min_down = pyo.Constraint(model.G, model.T, rule=min_down_rule)
 
    # --- 4.5 Rampa de SUBIDA (con arranque) --------------------------
    # Formulacion de la tesis (Morales-Espana et al., 2013):
    #   Pg,t - Pg,t-1 <= Rg^up + SUg,t * Pgmin
    # El termino SUg,t*Pgmin da un margen extra justo en el arranque
    # (la unidad puede saltar hasta su minimo tecnico al encender).
    def rampa_up_rule(m, g, t):
        if t == m.T.first():
            return pyo.Constraint.Skip   # no hay t-1
        tp = m.T.prev(t)
        return (m.P_g[g, t] - m.P_g[g, tp]
                <= m.ramp_up[g] + m.SU[g, t] * m.Pmin[g])
    model.rampa_up = pyo.Constraint(model.G, model.T, rule=rampa_up_rule)
 
    # --- 4.6 Rampa de BAJADA (con parada) ----------------------------
    # Formulacion de la tesis:
    #   Pg,t-1 - Pg,t <= Rg^down + SDg,t * Pgmin
    def rampa_down_rule(m, g, t):
        if t == m.T.first():
            return pyo.Constraint.Skip
        tp = m.T.prev(t)
        return (m.P_g[g, tp] - m.P_g[g, t]
                <= m.ramp_down[g] + m.SD[g, t] * m.Pmin[g])
    model.rampa_down = pyo.Constraint(
        model.G, model.T, rule=rampa_down_rule)
    
    # ==================================================================
    # Bloque 5 -- BESS (almacenamiento)
    # ==================================================================
    # Formulacion de la tesis (Cap. 3). El BESS opera solo si se instala
    # (y_s = 1). Todas las restricciones se ligan a esa decision.
 
    # --- 5.1 Balance de energia (SoC) --------------------------------
    # SoC[s,t] = SoC[s,t-1]*(1 - self_dis) + eff_ch*Pch - Pdis/eff_dis
    # En el primer periodo se parte del SoC inicial (fraccion de Esmax).
    def bess_balance_rule(m, s, t):
        carga = m.eff_ch * m.Pch[s, t]
        descarga = m.Pdis[s, t] / m.eff_dis
        if t == m.T.first():
            soc_previo = m.soc_ini_frac * m.Esmax[s]
        else:
            soc_previo = m.SoC[s, m.T.prev(t)] * (1 - m.self_dis)
        return m.SoC[s, t] == soc_previo + carga - descarga
    model.bess_balance = pyo.Constraint(
        model.S, model.T, rule=bess_balance_rule)
 
    # --- 5.2 Limite de energia almacenada ----------------------------
    # 0 <= SoC[s,t] <= Esmax[s]  (Esmax es variable de dimensionamiento)
    def bess_soc_max_rule(m, s, t):
        return m.SoC[s, t] <= m.Esmax[s]
    model.bess_soc_max = pyo.Constraint(
        model.S, model.T, rule=bess_soc_max_rule)
 
    # --- 5.3 Limites de potencia de carga/descarga -------------------
    # Pch, Pdis limitados por (a) el tamano instalado Psmax y (b) el
    # estado binario. NOTA: el producto Psmax*u_ch seria BILINEAL (dos
    # variables) y rompe el MILP. Se LINEALIZA en dos restricciones:
    #   Pch <= Psmax          (no superar la potencia instalada)
    #   Pch <= M * u_ch       (cero si no esta en modo carga; M fisico)
    # El estado binario (u_ch/u_dis) evita cargar y descargar a la vez.
    M_p = getattr(data, "bess_pot_max", 1000)   # Big-M fisico (MW)
 
    def bess_pch_size_rule(m, s, t):
        return m.Pch[s, t] <= m.Psmax[s]
    model.bess_pch_size = pyo.Constraint(
        model.S, model.T, rule=bess_pch_size_rule)
 
    def bess_pch_bin_rule(m, s, t):
        return m.Pch[s, t] <= M_p * m.u_ch[s, t]
    model.bess_pch_bin = pyo.Constraint(
        model.S, model.T, rule=bess_pch_bin_rule)
 
    def bess_pdis_size_rule(m, s, t):
        return m.Pdis[s, t] <= m.Psmax[s]
    model.bess_pdis_size = pyo.Constraint(
        model.S, model.T, rule=bess_pdis_size_rule)
 
    def bess_pdis_bin_rule(m, s, t):
        return m.Pdis[s, t] <= M_p * m.u_dis[s, t]
    model.bess_pdis_bin = pyo.Constraint(
        model.S, model.T, rule=bess_pdis_bin_rule)
 
    # --- 5.4 No cargar y descargar simultaneamente -------------------
    # u_ch + u_dis <= y_s  (ademas ligado a la instalacion: si no se
    # instala el BESS, ni carga ni descarga).
    def bess_no_simultaneo_rule(m, s, t):
        return m.u_ch[s, t] + m.u_dis[s, t] <= m.y_s[s]
    model.bess_no_simultaneo = pyo.Constraint(
        model.S, model.T, rule=bess_no_simultaneo_rule)
 
    # --- 5.5 Dimensionamiento ligado a la instalacion ----------------
    # Psmax, Esmax solo pueden ser > 0 si el BESS se instala (y_s = 1).
    # Big-M fisico: una cota superior razonable a la potencia/energia.
    M_pot = getattr(data, "bess_pot_max", 1000)   # MW, cota fisica
    M_ene = getattr(data, "bess_ene_max", 5000)   # MWh, cota fisica
 
    def bess_inst_pot_rule(m, s):
        return m.Psmax[s] <= M_pot * m.y_s[s]
    model.bess_inst_pot = pyo.Constraint(
        model.S, rule=bess_inst_pot_rule)
 
    def bess_inst_ene_rule(m, s):
        return m.Esmax[s] <= M_ene * m.y_s[s]
    model.bess_inst_ene = pyo.Constraint(
        model.S, rule=bess_inst_ene_rule)
 
    # --- 5.6 Estado final = estado inicial ---------------------------
    # SoC[s, ultimo periodo] = SoC inicial. Evita que el BESS haga
    # "trampa" vaciandose al final del horizonte. (Mejora de la tesis
    # que Alvaro no tiene.)
    def bess_ciclico_rule(m, s):
        return (m.SoC[s, m.T.last()]
                == m.soc_ini_frac * m.Esmax[s])
    model.bess_ciclico = pyo.Constraint(model.S, rule=bess_ciclico_rule)
 
    # --- 5.7 Limite del numero de BESS instalados --------------------
    # sum_s y_s <= N_BESS
    def bess_num_max_rule(m):
        if len(m.S) == 0:
            return pyo.Constraint.Skip   # sin BESS, restriccion trivial
        return sum(m.y_s[s] for s in m.S) <= m.N_BESS
    model.bess_num_max = pyo.Constraint(rule=bess_num_max_rule)
    
    # --- 5.8 Relacion potencia-energia (duracion nominal) ------------
    # Es <= rho * Ps. Relaciona la energia instalada con la potencia
    # instalada mediante la duracion nominal rho (horas). Evita
    # configuraciones irreales (mucha energia con poca potencia).
    # Tesis: Es <= rho * Ps (Alsaidan et al., 2018).
    rho = getattr(data, "bess_duracion", 4)   # duracion nominal (horas)

    def bess_pot_energia_rule(m, s):
        return m.Esmax[s] <= rho * m.Psmax[s]
    model.bess_pot_energia = pyo.Constraint(
        model.S, rule=bess_pot_energia_rule)
    
    
# ==================================================================
    # Bloque FACTS (TCSC) -- bloques discretos, compensacion fija
    # ==================================================================
    # El TCSC modifica la reactancia efectiva de la linea, lo que anade
    # un flujo inducido:  f = MVA*[B*dtheta + sum_z w_{f,z,t}].
    # Al fijar la compensacion al bloque instalado (no dinamica), dB_{f,z}
    # es una CONSTANTE con signo y el unico producto no lineal es
    # binaria x continua, que se linealiza exactamente con Big-M sin
    # binarias auxiliares. Referencia de compensacion serie fija:
    # Rahmani et al. (2013).

    def _dtheta(m, f, t):
        return m.delta_pos[f, t] - m.delta_neg[f, t]

    def _sum_ad(m, f, t):
        return sum(m.alpha[k] * m.delta_seg[f, k, t] for k in m.SEG_PERD)

    # --- F.1 Un solo bloque por linea  [ec. 3-3] ---------------------
    def facts_un_bloque_rule(m, f):
        return sum(m.kappa[f, z] for z in m.Z) <= 1
    model.facts_un_bloque = pyo.Constraint(model.F, rule=facts_un_bloque_rule)

    # --- F.2 Linealizacion exacta de psi  [ecs. 3-8 a 3-10] ----------
    def f_psi_a(m, f, z, t): return m.psi[f, z, t] <=  m.MB_on[f, z] * m.kappa[f, z]
    def f_psi_b(m, f, z, t): return m.psi[f, z, t] >= -m.MB_on[f, z] * m.kappa[f, z]
    def f_psi_c(m, f, z, t):
        return m.psi[f, z, t] <= m.dB[f, z] * _dtheta(m, f, t) + m.MB_off[f, z] * (1 - m.kappa[f, z])
    def f_psi_d(m, f, z, t):
        return m.psi[f, z, t] >= m.dB[f, z] * _dtheta(m, f, t) - m.MB_off[f, z] * (1 - m.kappa[f, z])

    
    model.facts_psi_a = pyo.Constraint(model.F, model.Z, model.T, rule=f_psi_a)
    model.facts_psi_b = pyo.Constraint(model.F, model.Z, model.T, rule=f_psi_b)
    model.facts_psi_c = pyo.Constraint(model.F, model.Z, model.T, rule=f_psi_c)
    model.facts_psi_d = pyo.Constraint(model.F, model.Z, model.T, rule=f_psi_d)

    # --- F.3 Flujo de la linea con TCSC  [ec. 3-5] -------------------
    def facts_flujo_rule(m, f, t):
        return m.f[f, t] == m.MVA_base * (
            m.susceptance[f] * _dtheta(m, f, t) + sum(m.psi[f, z, t] for z in m.Z))
    model.facts_flujo = pyo.Constraint(model.F, model.T, rule=facts_flujo_rule)

    # --- F.4 Linealizacion de Lambda  [ecs. 3-15 a 3-17] -------------
    def f_lam_a(m, f, z, t): return m.lam[f, z, t] <= m.MG_on[f, z] * m.kappa[f, z]
    def f_lam_b(m, f, z, t):
        return m.lam[f, z, t] >= _sum_ad(m, f, t) - m.MG_off[f, z] * (1 - m.kappa[f, z])
    def f_lam_c(m, f, z, t):
        return m.lam[f, z, t] <= _sum_ad(m, f, t) + m.MG_off[f, z] * (1 - m.kappa[f, z])
    model.facts_lam_a = pyo.Constraint(model.F, model.Z, model.T, rule=f_lam_a)
    model.facts_lam_b = pyo.Constraint(model.F, model.Z, model.T, rule=f_lam_b)
    model.facts_lam_c = pyo.Constraint(model.F, model.Z, model.T, rule=f_lam_c)

    # --- F.5 Limite del numero de dispositivos  [ec. 3-18a] ----------
    def facts_num_max_rule(m):
        if len(m.F) == 0:
            return pyo.Constraint.Skip
        return sum(m.kappa[f, z] for f in m.F for z in m.Z) <= m.N_FACTS
    model.facts_num_max = pyo.Constraint(rule=facts_num_max_rule)    

    # ==================================================================
    # Bloque 6 -- EXPANSION: nota sobre las candidatas
    # ==================================================================
    # No se necesitan restricciones adicionales: el enfoque unificado ya
    # cubre las candidatas mediante x_eff en los bloques 1 y 2:
    #   - flujo y descomposicion relajados por Big-M si x=0,
    #   - limites de flujo y perdidas forzados a 0 si x=0.
    # El costo de construccion (Cl*x_l) ya esta en objective.py.
    # (Aqui irian restricciones extra de expansion si las hubiera, p.ej.
    #  limite al numero total de lineas nuevas.)
 
    return model
