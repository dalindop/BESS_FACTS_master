"""
==================================================================
  PARAMETROS
------------------------------------------------------------------
Autor : Daniel Lindo -- Universidad Nacional de Colombia (UNAL)
Tesis : Maestria en Ingenieria Electrica, 2026
------------------------------------------------------------------

Define los PARAMETROS (datos fijos) del modelo: los numeros que NO
cambian durante la optimizacion (e.g. el costo de cada generador, la
capacidad de cada linea, la demanda de cada nodo en cada hora).

ALCANCE DE ESTE PASO (migracion incremental):
    Bloque 0 -> Constantes del sistema
    Bloque 1 -> RED       (susceptancia, conductancia, flujo perdidas)
    Bloque 2 -> DEMANDA
    Bloque 3 -> TERMICA    (costos linealizados, limites, rampas, UC)    
    Bloque 4 -> costo de inversión
    
FILOSOFIA (acordada con la direccion de tesis):
    - Se migra la FORMULACION de Alvaro (su fisica), NO su codigo.
    - Los datos NO se leen de archivos aqui dentro. Entran ya
      preparados en el objeto `data`. Esto rompe el acoplamiento que
      causaba problemas de reproducibilidad en el codigo legacy y
      acelera la construccion del modelo (se usa initialize= con dicts
      ya armados, en vez de rule= que llama una funcion por cada indice).
==================================================================
"""

import math
import pyomo.environ as pyo


# ----------------------------------------------------------------------
# Funcion auxiliar: linealizacion del costo de generacion por tramos
# ----------------------------------------------------------------------
def linealizar_costo(c2, c1, c0, pmin, pmax, n_tramos):
    """
    Aproxima el costo cuadratico C(P)=c2*P^2 + c1*P + c0 con `n_tramos`
    rectas, entre Pmin y Pmax.

    Devuelve:
        fg_min  : costo en Pmin, C(Pmin)  (el "punto de partida").
        slopes  : lista con la pendiente de cada tramo (en $/MWh). Como
                  el costo es convexo, las pendientes crecen tramo a
                  tramo: generar mas sale progresivamente mas caro. Eso
                  es lo que mantiene correcta la aproximacion lineal.

    c2, c1, c0 : coeficientes del polinomio de costo.
    pmin, pmax : potencia minima y maxima del generador.
    n_tramos   : numero de tramos rectos (mas tramos = mas preciso).
    """
    fg_min = c2 * pmin**2 + c1 * pmin + c0 #fg_min = Cg_min
    paso = (pmax - pmin) / n_tramos
    slopes = []
    # nota-python: el indice 'm' calca la tesis (segmentos de costo,
    # conjunto M). Aqui m va de 0 a n_tramos-1 por indexacion Python;
    # al guardarlo en el dict se numera desde 1 (ver mas abajo).
    for m in range(n_tramos):
        # extremos del tramo m: [Pa, Pb]
        Pa = pmin + m * paso
        Pb = pmin + (m + 1) * paso
        Ca = c2 * Pa**2 + c1 * Pa + c0
        Cb = c2 * Pb**2 + c1 * Pb + c0
        slopes.append((Cb - Ca) / (Pb - Pa))  # pendiente del tramo
    return fg_min, slopes


def build_parameters(model, data):
    """   
    Requiere que build_sets(model, data) se haya ejecutado antes.

    """

    # ==================================================================
    # Bloque 0 -- constantes del sistema
    # ==================================================================
    # Base de potencia del sistema, en MVA. En el W&W vale 100.
    model.MVA_base = pyo.Param(initialize=getattr(data, "mva_base", 100))

    # ==================================================================
    # Bloque 1 -- parametros de RED (lineas)
    # ==================================================================
    # Este es el bloque que FACTS/TCSC modificara mas adelante: la
    # susceptancia entra en la ecuacion de flujo DC. Punto de insercion
    # futuro de los FACTS.

    # Susceptancia de cada linea: b = 1/X.  data.susceptancia es un dict
    # {linea: valor} ya calculado en el data_loader desde la columna x.
    model.susceptance = pyo.Param(model.L_ALL, initialize=data.susceptancia)

    # Conductancia de cada linea: g = R/(R^2+X^2). Se usa en perdidas.
    model.conductance = pyo.Param(model.L_ALL, initialize=data.conductancia)

    # Capacidad (limite de flujo) de cada linea, en MW. En el W&W es la
    # columna rateA. Limita el flujo en ambos sentidos (+/-).
    model.flow_max = pyo.Param(model.L_ALL, initialize=data.flow_max)

    # alpha: coeficientes de los tramos de linealizacion de PERDIDAS.
    # Formula de Alvaro: alpha_k = delta_theta * (2*k - 1), con
    # delta_theta = 20 grados en radianes (k = indice de tramo, conj. K
    # de la tesis = SEG_PERD (=k) en el codigo). Es geometria pura (no depende
    # de datos de entrada), asi que se calcula aqui sobre SEG_PERD.
    # nota-python: SEG_PERD.ord(k) da la posicion 1,2,3... del tramo k.
    delta_theta = 20 * math.pi / 180  # 20 grados -> radianes

    def alpha_init(m, k):
        return delta_theta * (2 * m.SEG_PERD.ord(k) - 1)
    model.alpha = pyo.Param(model.SEG_PERD, initialize=alpha_init)

    # ==================================================================
    # Bloque 2 -- DEMANDA
    # ==================================================================
    # Demanda por nodo y por periodo: D[n, t]. Es de los datos mas
    # grandes (N x T). Por eso viene como dict ya armado de forma
    # vectorizada en el data_loader (no con loops), lo que reduce el
    # tiempo de construccion del modelo.
    # NOTA: en esta fase de validacion la demanda es constante en el
    # tiempo (no depende de t). Para los experimentos (Cap. 4-5) se
    # reemplazara por un perfil horario, sin tocar este modulo: solo
    # cambia el dict data.demanda que entrega el loader.
    # note-python: filas = model.N, columnas = model.T. 
    model.D = pyo.Param(model.N, model.T, initialize=data.demanda)
    
    # --- Disponibilidad renovable (tesis: Ar,t * Pr^max) --------------
    # Energia maxima que el recurso renovable r puede entregar en la hora
    # t (MW). Ya incorpora el factor de disponibilidad del recurso (sol,
    # viento) y la capacidad instalada. En el W&W R esta vacio, asi que
    # queda vacio sin error. En Colombia se puebla con perfiles de
    # generacion solar/eolica (analogo a la hoja Renewable de Alvaro).
    model.disp_renov = pyo.Param(
        model.R, model.T,
        initialize=getattr(data, "disponibilidad_renov", {}),
        default=0)

    # ==================================================================
    # Bloque 3 -- parametros de GENERACION TERMICA
    # ==================================================================
    # Se conserva la formulacion de Alvaro: el costo cuadratico se
    # linealiza por tramos (ver linealizar_costo arriba). 'slope' es la
    # pendiente del tramo y 'fg_min' el costo en Pmin.

    # Pendiente del tramo de costo, indexada por (generador, tramo).
    # data.slope_term: dict {(g, s): pendiente} ya precomputado.
    model.slope = pyo.Param(model.G, model.SEG_COST,
                            initialize=data.slope_term)

    # Costo de produccion en Pmin, por generador.
    model.fg_min = pyo.Param(model.G, initialize=data.fg_min_term)

    # Potencias minima y maxima de cada termica, en MW.
    model.Pmin = pyo.Param(model.G, initialize=data.pmin_term)
    model.Pmax = pyo.Param(model.G, initialize=data.pmax_term)

    # Rampas de subida y bajada (MW por hora). Limitan cuanto puede
    # cambiar la potencia de un generador entre horas consecutivas.
    model.ramp_up   = pyo.Param(model.G, initialize=data.ramp_up)
    model.ramp_down = pyo.Param(model.G, initialize=data.ramp_down)

    # --- Parametros de Unit Commitment (arranque/parada) --------------
    # El W&W no trae datos de UC (costos de arranque, tiempos minimos),
    # asi que se cargan con getattr y valores neutros por defecto. Cuando
    # se migre al caso colombiano, estos vendran de la hoja SM_Unit.
    # note-python: Para cada generador (g) en mi lista (model.G), 
    # asígnale un costo de 0 en el caso de que getattr no encuentre valor
    model.cost_SU = pyo.Param(model.G,
                              initialize=getattr(data, "cost_su",
                                                 {g: 0 for g in model.G}))
    model.cost_SD = pyo.Param(model.G,
                              initialize=getattr(data, "cost_sd",
                                                 {g: 0 for g in model.G}))

    # --- Parametros de tiempos minimos y estado inicial (UC) ----------
    # Necesarios para las restricciones de unit commitment (Bloque 4 de
    # constraints). Defaults NEUTROS: estado inicial apagado (0), y
    # tiempos minimos de 1 hora (no imponen restriccion real). El W&W no
    # trae estos datos; el caso colombiano los sobreescribira.
    # onoff_t0   : estado de la unidad antes del horizonte (0=off, 1=on).
    # L_up_min   : tiempo minimo de encendido (horas).
    # L_down_min : tiempo minimo de apagado (horas).
    model.onoff_t0 = pyo.Param(
        model.G, initialize=getattr(data, "onoff_t0",
                                    {g: 0 for g in model.G}))
    model.L_up_min = pyo.Param(
        model.G, initialize=getattr(data, "l_up_min",
                                    {g: 1 for g in model.G}))
    model.L_down_min = pyo.Param(
        model.G, initialize=getattr(data, "l_down_min",
                                    {g: 1 for g in model.G}))
 
    # --- Costo marginal de generacion hidraulica (tesis: Ch) ----------
    # Indexado sobre H. En el W&W H esta vacio (no hay hidro), asi que
    # C_h queda vacio sin error; la funcion objetivo lo suma sobre H y
    # da 0. Se poblara al migrar al caso colombiano (hoja de hidraulicas).
    # TODO: poblar costos hidraulicos reales en el caso Colombia.
    model.C_h = pyo.Param(model.H,
                          initialize=getattr(data, "costo_hidro", {}))
    # ==================================================================
    # Bloque 4 -- COSTOS DE INVERSION (para la funcion objetivo)
    # ==================================================================
    # Permiten comparar el costo de CONSTRUIR una linea contra el de
    # instalar BESS o FACTS. Aparecen en la funcion objetivo (Cap. 3):
    #
    #   min Z = SUM (Cg*Pg + Cg^SU·SUg,t + Cg^SD·SDg,t) + SUM Ch*Ph     (operacion)
    #         + SUM_l(Cl * x_l)                  (expansion de lineas)
    #         + SUM_s(Cs_inst*y_s + Cs_power*Pmax_s + Cs_energy*Emax_s)
    #         + SUM_f(Cf_inst*z_f + Cf_size*X_f) (FACTS)
    #
    # NOTA METODOLOGICA IMPORTANTE -- ANUALIZACION:
    #   La funcion objetivo mezcla costos de OPERACION (por hora, sobre
    #   el horizonte simulado) con costos de INVERSION (un pago unico que
    #   se recupera en varios anos). Para sumarlos en una misma funcion
    #   hay que llevarlos a la misma base temporal. Alvaro lo hace
    #   prorrateando la inversion entre los anos de recuperacion:
    #       costo_horario = costo_total / (365 * anios_recup * 24)
    #   y luego lo escala por el numero de horas del horizonte.
    #   Esta decision debe replicarse y defenderse en la tesis. Aqui se
    #   asume que los costos que entran ya vienen en la base correcta
    #   (el data_loader/loader hace la anualizacion).    

    # --- Costo de construir cada linea candidata (l in LC) ------------
    # Aparece como Cl * x_l. Solo aplica a lineas candidatas (LC).
    # El caso W&W no trae este dato (LC vacio): queda como placeholder.
    #       (p. ej. UPME, literatura de TEP, costo por km * longitud).
    model.Cl = pyo.Param(model.LC,
                         initialize=getattr(data, "costo_linea", {}))

    # --- Costos del BESS ----------------------------------------------
    # Tres componentes
    #   Cs_inst  : costo fijo por instalar BESS en el nodo (asociado y_s)
    #   Cs_power : costo por MW de potencia instalada   (asociado Pmax_s)
    #   Cs_energy: costo por MWh de energial instaada   (asociado Emax_s)
    # Valores por defecto tomados de Alvaro (hoja ESS_Unit: C_Potencia,
    # C_Energia = 45). Cs_inst no existe en Alvaro -> 0 por defecto.
    model.Cs_inst   = pyo.Param(
        initialize=getattr(data, "costo_bess_inst", 0)) # embebido en pot/ener
    model.Cs_power  = pyo.Param(
        initialize=getattr(data, "costo_bess_power", 372000)) # USD/MW (NREL 2025)
    model.Cs_energy = pyo.Param(
        initialize=getattr(data, "costo_bess_energy", 241000)) # USD/MWh (NREL 2025)

    # --- Costos del FACTS/TCSC ----------------------------------------
    # Dos componentes
    #   Cf_inst : costo fijo por instalar el dispositivo   (asociado z_f)
    #   Cf_size : costo por nivel de compensacion           (asociado X_f)
    
    model.Cf_inst = pyo.Param(
        initialize=getattr(data, "costo_facts_inst", 50000)) #USD/MVAr
    model.Cf_size = pyo.Param(
        initialize=getattr(data, "costo_facts_size", 0))

    # --- Parametros TECNICOS del BESS (para las restricciones) --------
    #   eff_ch  : eficiencia de carga (tesis: eta^ch).
    #   eff_dis : eficiencia de descarga (tesis: eta^dis).
    #   self_dis: tasa de autodescarga por periodo (tesis: eta^sd).
    #   soc_ini : estado de carga inicial, fraccion de Esmax.
    # rho: duracion nominal del BESS (horas), relacion energia/potencia.
    model.bess_rho = pyo.Param(
        initialize=getattr(data, "bess_duracion", 4))
    # eficiencias: round-trip 0.85 (NREL 2025) = 0.922 c/u.
    model.eff_ch = pyo.Param(
        initialize=getattr(data, "bess_eff_ch", 0.922))
    model.eff_dis = pyo.Param(
        initialize=getattr(data, "bess_eff_dis", 0.922))
    model.self_dis = pyo.Param(
        initialize=getattr(data, "bess_self_dis", 0.000125)) # 0.0125% por hora
    model.soc_ini_frac = pyo.Param(
        initialize=getattr(data, "bess_soc_ini", 0.5))
 
    # Limite maximo de sistemas BESS instalables (tesis: N_BESS).
    # Por defecto = numero de nodos candidatos (sin restriccion real).
    model.N_BESS = pyo.Param(
        initialize=getattr(data, "n_bess_max", len(model.S)))
 
    # --- Parametros tecnicos del TCSC (FACTS) ------------------------
    # Rango de susceptancia adicional que el TCSC puede aportar. Segun
    # la literatura (Optimal Allocation, 2018) la compensacion va de
    # -70% a +20% de la reactancia de la linea; aqui se expresa como
    # susceptancia adicional (dB) con cotas por linea. Valores por
    # defecto conservadores; se afinan con datos reales.
    #   dB_min, dB_max : cotas de la susceptancia adicional del TCSC.
    #   theta_max      : cota del angulo (para el Big-M del nivel 2).
    model.dB_min = pyo.Param(
        model.F, initialize=getattr(data, "facts_dB_min", {}),
        default=-0.7)
    model.dB_max = pyo.Param(
        model.F, initialize=getattr(data, "facts_dB_max", {}),
        default=0.2)
    # theta_max: cota de diferencia angular con TCSC.
    # 0.349 rad = pi/9 = 20°, limite de estabilidad.
    model.theta_max_f = pyo.Param(
        initialize=getattr(data, "facts_theta_max", 0.349))
    # Big-M para las restricciones de linealizacion del TCSC (fisico).
    model.M_facts = pyo.Param(
        initialize=getattr(data, "facts_big_m", 10))
    # Limite maximo de dispositivos FACTS instalables.
    model.N_FACTS = pyo.Param(
        initialize=getattr(data, "n_facts_max", len(model.F)))
    
    # --- Parametros para ANUALIZAR las inversiones (CRF) ------------
    # tasa_desc  : tasa de descuento (ej. 0.10 = 10%)
    # vida_*     : vida util de cada tecnologia (anios)
    model.tasa_desc = pyo.Param(
        initialize=getattr(data, "tasa_descuento", 0.115))
    model.vida_linea = pyo.Param(
        initialize=getattr(data, "vida_linea", 25))
    model.vida_bess = pyo.Param(
        initialize=getattr(data, "vida_bess", 15))
    model.vida_facts = pyo.Param(
        initialize=getattr(data, "vida_facts", 20))
    # Factor para llevar la operacion simulada a un anio completo.
    # Si simulo 1 dia (24h) representativo, factor = 365.
    # En general: 8760 / horas_simuladas.
    model.factor_anual = pyo.Param(
        initialize=getattr(data, "factor_anual", 365))
 
    # ==================================================================
    # TODO -- bloques para escalar al sistema colombiano de Alvaro:
    #   - HIDRO     : slope_j, fg_min_j, Q_min, Q_max
    # ==================================================================

    return model
