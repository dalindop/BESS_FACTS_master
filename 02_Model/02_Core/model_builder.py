# -*- coding: utf-8 -*-
"""
==================================================================
 MODEL BUILDER
------------------------------------------------------------------
Autor : Daniel Lindo -- Universidad Nacional de Colombia (UNAL)
Tesis : Maestria en Ingenieria Electrica, 2026
------------------------------------------------------------------

Punto unico que construye el modelo completo llamando, en orden, a los
cinco constructores de los modulos del nucleo:
    sets -> parameters -> variables -> objective -> constraints

El orden es OBLIGATORIO: cada modulo usa lo que definio el anterior
(parameters usa los conjuntos de sets, variables usa ambos, etc.).

Separar el ensamblado en su propio modulo mantiene main.py limpio y
permite construir el modelo desde cualquier script (tests, experimentos)
con una sola llamada.
==================================================================
"""

import pyomo.environ as pyo

import sets
import parameters
import variables
import objective
import constraints


def construir_modelo(data):
    """
    Construye y devuelve el modelo Pyomo completo a partir del objeto
    `data` (producido por data_loader.cargar_datos).

    data: objeto con todos los datos del caso.
    return: ConcreteModel listo para resolver.
    """
    model = pyo.ConcreteModel(name="TEP_BESS_FACTS")

    # El orden importa: cada paso usa lo construido por el anterior.
    sets.build_sets(model, data)             # conjuntos (N, L, G, ...)
    parameters.build_parameters(model, data)  # parametros (datos)
    variables.build_variables(model, data)    # variables de decision
    objective.build_objective(model, data)    # funcion objetivo
    constraints.build_constraints(model, data)  # restricciones

    return model


if __name__ == "__main__":
    import sys
    import data_loader
    ruta = sys.argv[1] if len(sys.argv) > 1 else "caso_WW.xlsx"
    datos = data_loader.cargar_datos(ruta)
    modelo = construir_modelo(datos)
    # resumen del tamano del modelo construido
    n_var = sum(1 for _ in modelo.component_data_objects(pyo.Var))
    n_con = sum(1 for _ in modelo.component_data_objects(pyo.Constraint))
    print(f"Modelo construido desde: {ruta}")
    print(f"  Variables    : {n_var}")
    print(f"  Restricciones: {n_con}")
    print(f"  Objetivo     : {'si' if modelo.nobjectives() else 'no'}")
