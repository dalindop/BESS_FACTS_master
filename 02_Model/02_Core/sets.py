"""
==================================================================
  SETS (CONJUNTOS)
------------------------------------------------------------------
Autor : Daniel Lindo -- Universidad Nacional de Colombia (UNAL)
Tesis : Maestria en Ingenieria Electrica, 2026
------------------------------------------------------------------

CONJUNTO = lista de "etiquetas" que sirven de indices (e.g N = {b1, b2, ...})

FINALIDAD DEL CÓDIGO: recibir datos ya cargados
(objeto `data`) y crear los conjuntos en el modelo de Pyomo. No lee
archivos, no valida datos y no imprime.

Equivalencia con el codigo legacy de Alvaro:
    Tesis | Alvaro | Significado
     N    |  b     | Nodos del sistema (indices i, j)
     L    |  l     | Lineas de transmision existentes
     LC   |  --    | Lineas candidatas para expansion (nuevo)
     G    |  i     | Generacion termica
     H    |  j     | Generacion hidraulica
     R    |  w,s   | Generacion renovable (eolica + solar)
     S    |  --    | Nodos candidatos para BESS (nuevo)
     F    |  --    | Lineas candidatas para FACTS/TCSC (nuevo)
     T    |  t     | Periodos de tiempo del horizonte
     K    |  L     | Segmentos de linealizacion de perdidas
     M    |  k     | Segmentos de linealizacion de costo de gen

==================================================================

"""

import pyomo.environ as pyo

def build_sets(model, data):
    """
    Construye los conjuntos del modelo y se los agrega a `model`.

    model: Modelo de Pyomo al que se agregaran los conjuntos.
    data : Objeto con los datos ya preparados. 
    """

    # ------------------------------------------------------------------
    # Conjunto temporal
    # ------------------------------------------------------------------
    # T son los periodos del horizonte: 1, 2, ..., n_horas.
    # RangeSet(1, n) crea el rango de enteros {1,...,n}.
    model.T = pyo.RangeSet(1, data.n_horas)

    # ------------------------------------------------------------------
    # Conjuntos estructurales (topologia fisica de la red)
    # ------------------------------------------------------------------
    # ordered=True fija el orden de los elementos. 
    # pyo.Set(initialize=lista) crea el conjunto desde una lista
    model.N = pyo.Set(initialize=data.nodos,  ordered=True)  # nodos
    model.L = pyo.Set(initialize=data.lineas, ordered=True)  # lineas
    # nodo de referencia (slack) para el balance nodal
    model.nodo_ref = getattr(data, "nodo_slack", data.nodos[0])

    # ------------------------------------------------------------------
    # Conjuntos de generacion
    # ------------------------------------------------------------------
    model.G = pyo.Set(initialize=data.gen_termica, ordered=True)  # termica
    model.H = pyo.Set(initialize=data.gen_hidro,   ordered=True)  # hidro
    model.R = pyo.Set(initialize=data.gen_renov,   ordered=True)  # renovable

    # Subconjuntos de R por tecnologia: eolica y solar
    # nota-python: within=model.R obliga a que los elementos pertenezcan
    # a R.
    # getattr(data,"gen_eol",[]) toma/busca data.gen_eol; si ese
    # atributo no existe, usa lista vacia [].
    model.R_eol = pyo.Set(within=model.R,
                          initialize=getattr(data, "gen_eol", []), 
                          ordered=True)
    model.R_sol = pyo.Set(within=model.R,
                          initialize=getattr(data, "gen_sol", []),
                          ordered=True)

    # ------------------------------------------------------------------
    # Conjuntos TEP / BESS / FACTS
    # ------------------------------------------------------------------
    # ELIMINADA función en la tesis.
    # model.LC = pyo.Set(initialize=getattr(data, "lineas_cand", []),
    #                    ordered=True)   # lineas candidatas (expansion)
    model.S = pyo.Set(initialize=getattr(data, "nodos_bess", []),
                      ordered=True)    # nodos candidatos para BESS
    model.F = pyo.Set(initialize=getattr(data, "lineas_facts", []),
                      ordered=True)    # lineas candidatas para FACTS
    
    # Union de lineas existentes y candidatas: L_ALL = L U LC.
    # El flujo, los limites de flujo y el balance nodal se definen sobre
    # TODAS las lineas (existentes + candidatas). Una linea candidata
    # existe en el modelo, pero su flujo se forzara a 0 mediante una
    # restriccion Big-M si no se construye (x_l = 0). Definir la union
    # aqui, una sola vez, evita repetir el concepto en variables.py y
    # constraints.py.
    # Operador | = union de conjuntos (L U LC)
    # model.L_ALL = model.L | model.LC 
    # L_ALL = lineas existentes (sin candidatas). Se crea como conjunto
    # nuevo inicializado con los mismos elementos de L.
    model.L_ALL = pyo.Set(initialize=list(model.L))

    # ------------------------------------------------------------------
    # Conjuntos auxiliares de linealizacion
    # ------------------------------------------------------------------
    # El numero de tramos se deja como dato de entrada (no fijo en el codigo)
    # para poder estudiar su efecto en la precision y el tiempo de solucion.
    # n_cost = costo de generación térmica, n_perd = perdidas en las lineas.
    n_perd = getattr(data, "n_seg_perdidas", 3)  # por defecto 3 tramos
    n_cost = getattr(data, "n_seg_costo", 3)
    model.SEG_PERD = pyo.RangeSet(1, n_perd)  # tramos de perdidas (K)
    model.SEG_COST = pyo.RangeSet(1, n_cost)  # tramos de costo de gen (M)

    return model
