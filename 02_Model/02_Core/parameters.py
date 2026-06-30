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
    Hidro, embalses, renovable y BESS se anaden en pasos posteriores,
    cuando se escale del IEEE 6-bus (Wood & Wollenberg) al sistema
    colombiano de Alvaro. Marcados como TODO al final.

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
    model.susceptance = pyo.Param(model.L, initialize=data.susceptancia)

    # Conductancia de cada linea: g = R/(R^2+X^2). Se usa en perdidas.
    model.conductance = pyo.Param(model.L, initialize=data.conductancia)

    # Capacidad (limite de flujo) de cada linea, en MW. En el W&W es la
    # columna rateA. Limita el flujo en ambos sentidos (+/-).
    model.flow_max = pyo.Param(model.L, initialize=data.flow_max)

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
    # TODO: poblar UC real (CSU, Min_ON, Min_OFF...) en el caso Colombia.
    model.cost_SU = pyo.Param(model.G,
                              initialize=getattr(data, "cost_su",
                                                 {g: 0 for g in model.G}))
    model.cost_SD = pyo.Param(model.G,
                              initialize=getattr(data, "cost_sd",
                                                 {g: 0 for g in model.G}))

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
    # TODO: fijar y documentar el horizonte de recuperacion (anios_recup).

    # --- Costo de construir cada linea candidata (l in LC) ------------
    # Aparece como Cl * x_l. Solo aplica a lineas candidatas (LC).
    # El caso W&W no trae este dato (LC vacio): queda como placeholder.
    # TODO: valor de referencia de costo de linea [CITA - verificar]
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
        initialize=getattr(data, "costo_bess_inst", 0))
    model.Cs_power  = pyo.Param(
        initialize=getattr(data, "costo_bess_power", 45))
    model.Cs_energy = pyo.Param(
        initialize=getattr(data, "costo_bess_energy", 45))

    # --- Costos del FACTS/TCSC ----------------------------------------
    # Dos componentes
    #   Cf_inst : costo fijo por instalar el dispositivo   (asociado z_f)
    #   Cf_size : costo por nivel de compensacion           (asociado X_f)
    # placeholder hasta respaldarlos con fuentes.
    # TODO: valores de referencia de costo FACTS/TCSC [CITA - verificar]
    #       (p. ej. fabricantes, literatura de compensacion serie).
    model.Cf_inst = pyo.Param(
        initialize=getattr(data, "costo_facts_inst", 0))
    model.Cf_size = pyo.Param(
        initialize=getattr(data, "costo_facts_size", 0))

    # ==================================================================
    # TODO -- bloques para escalar al sistema colombiano de Alvaro:
    #   - HIDRO     : slope_j, fg_min_j, Q_min, Q_max
    #   - EMBALSES  : Vmin, Vmax, aportes, vertimiento (spillage)
    #   - RENOVABLE : perfiles de generacion eolica/solar
    #   - BESS      : C_potencia, C_energia, eficiencias, SOC_min/ini
    # ==================================================================

    return model
