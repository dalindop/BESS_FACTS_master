"""
Smoke test de sets.py usando datos FALSOS del IEEE 6-bus.
Comprueba que los conjuntos se crean con el tamaño (cardinalidad) correcto.

(python) Como ahora el archivo se llama 'sets.py' (sin numero), lo
podemos importar de forma normal y limpia: 'import sets'.
"""

import sets                       # <-- import limpio, ya sin importlib
import pyomo.environ as pyo


# (python) Una "clase" aqui se usa solo como caja para agrupar datos de
# prueba. Imita lo que el data_loader real entregara mas adelante.
class FakeData:
    n_horas      = 24
    nodos        = ["b1", "b2", "b3", "b4", "b5", "b6"]   # IEEE 6-bus
    lineas       = ["l1", "l2", "l3", "l4", "l5", "l6", "l7"]
    gen_termica  = ["G1", "G2", "G3"]
    gen_hidro    = []
    gen_renov    = ["W1", "S1"]
    gen_eol      = ["W1"]
    gen_sol      = ["S1"]
    lineas_cand  = ["lc1", "lc2"]
    nodos_bess   = ["b3", "b5"]
    lineas_facts = ["l2"]
    n_seg_perdidas = 3
    n_seg_costo    = 3


data = FakeData()
model = pyo.ConcreteModel()
sets.build_sets(model, data)

assert len(model.N) == 6,  "Deben ser 6 nodos (IEEE 6-bus)"
assert len(model.L) == 7,  "Deben ser 7 lineas"
assert len(model.G) == 3,  "Deben ser 3 termicas"
assert len(model.T) == 24, "Horizonte de 24 horas"
assert len(model.R) == 2,  "2 renovables (1 eol + 1 sol)"
assert len(model.R_eol) == 1
assert len(model.R_sol) == 1
assert len(model.LC) == 2
assert len(model.S) == 2
assert len(model.F) == 1
assert len(model.SEG_PERD) == 3
assert not hasattr(model, "tt"), "NO debe migrarse el set 'tt' de Alvaro"

print("OK: todos los conjuntos se construyeron correctamente.")
print(f"  N = {list(model.N)}")
print(f"  L = {list(model.L)}")
print(f"  G = {list(model.G)}")
print(f"  R = {list(model.R)}  (eol={list(model.R_eol)}, sol={list(model.R_sol)})")
print(f"  LC={list(model.LC)} | S={list(model.S)} | F={list(model.F)}")
print(f"  T = 1..{len(model.T)}")
