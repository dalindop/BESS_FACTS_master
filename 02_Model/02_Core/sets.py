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

    # ------------------------------------------------------------------
    # Conjuntos de generacion
    # ------------------------------------------------------------------
    model.G = pyo.Set(initialize=data.gen_termica, ordered=True)  # termica
    model.H = pyo.Set(initialize=data.gen_hidro,   ordered=True)  # hidro
    model.R = pyo.Set(initialize=data.gen_renov,   ordered=True)  # renovable

    # Subconjuntos de R por tecnologia: eolica y solar
    # nota-python: within=model.R obliga a que los elementos pertenezcan
    # a R.
    # nota-python: getattr(data,"gen_eol",[]) toma data.gen_eol; si ese
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
    # TODO: poblar LC con las lineas candidatas reales (data_loader).
    # TODO: poblar S con los nodos candidatos a BESS (data_loader).
    # TODO: poblar F con las lineas candidatas a FACTS/TCSC (data_loader).
    model.LC = pyo.Set(initialize=getattr(data, "lineas_cand", []),
                       ordered=True)   # lineas candidatas (expansion)
    model.S = pyo.Set(initialize=getattr(data, "nodos_bess", []),
                      ordered=True)    # nodos candidatos para BESS
    model.F = pyo.Set(initialize=getattr(data, "lineas_facts", []),
                      ordered=True)    # lineas candidatas para FACTS

    # ------------------------------------------------------------------
    # Conjuntos auxiliares de linealizacion
    # ------------------------------------------------------------------
    # El numero de tramos se deja como dato de entrada (no fijo en el codigo)
    # para poder estudiar su efecto en la precision y el tiempo de solucion.
    # n_cost = costo de generación térmica, n_perd = perdidas en las lineas.
    n_perd = getattr(data, "n_seg_perdidas", 3)  # por defecto 3 tramos
    n_cost = getattr(data, "n_seg_costo", 3)
    model.SEG_PERD = pyo.RangeSet(1, n_perd)  # tramos de perdidas
    model.SEG_COST = pyo.RangeSet(1, n_cost)  # tramos de costo de gen.

    return model
