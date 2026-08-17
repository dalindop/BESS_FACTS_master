# Tesis MSc — TEP con BESS y FACTS

Modelo DC-MILP de planeación de expansión de transmisión con
almacenamiento (BESS) y compensación serie controlada (TCSC).
Universidad Nacional de Colombia. Entrega: 30 de septiembre de 2026.

## Stack
Python 3.14, Pyomo, Gurobi 13 (licencia académica), pandas.
El solver por defecto es gurobi; HiGHS no sirve para casos con FACTS.

## Estructura
- `main.py` — punto de entrada: `python main.py <caso.xlsx> --export --solver gurobi`
- `barrido_costos.py` — análisis de sensibilidad de costos
- `02_Model/01_Inputs/data_loader.py` — carga desde Excel
- `02_Model/02_Core/` — sets, parameters, variables, constraints, objective, model_builder
- `02_Model/03_Solver/solver_runner.py`
- `02_Model/04_Postprocessing/results_export.py`
- `01_Data/01_Raw/` — datos originales de XM y PARATEC, NO MODIFICAR
- `01_Data/02_Processed/` — datos elaborados
- `01_Data/03_Test_Cases/` — casos Excel de entrada

## Convenciones críticas
- En `data_loader.py` el objeto de datos se llama `d`. En todos los demás
  módulos se llama `data`. Confundirlos causa NameError.
- Los diccionarios se declaran UNA sola vez, antes de su bucle de llenado.
  Nunca redeclarar después: vacía los datos ya cargados.
- `_leer_hoja()` devuelve un generador. Envolverlo en `list()` si se recorre
  más de una vez.
- Potencias en MW, energía en MWh, costos en USD.
- Base 100 MVA, ángulos en radianes.

## Formulación FACTS (TCSC)
- Bloques discretos de compensación: sigma en {0.15, 0.30, 0.45, 0.60}
- Solo compensación capacitiva. Sigma negativo produce costo negativo.
- Costo: 135 000 USD/MVAr overnight (de Oliveira et al. 1999, Apéndice B).
  NO usar 22 000: es una anualidad, no CAPEX.
- CRF aplicado UNA sola vez, fuera de la sumatoria.
- Big-M duales: `MB_on`/`MG_on` con bound tightening (válidos si kappa=1);
  `MB_off`/`MG_off` con rango angular completo (relajación si kappa=0).
- Las pérdidas de líneas compensadas actualizan la conductancia por bloque
  (Luburic et al. 2020, ec. 20). Omitirlo subestima pérdidas en (1-sigma)^2.

## Reglas de trabajo
- Preferir ediciones quirúrgicas sobre regenerar archivos completos.
- No crear scripts ni archivos nuevos sin autorización explícita.
- Explicar el cambio y su justificación ANTES de ejecutar.
- Reportar siempre lo que no se pudo determinar. No rellenar huecos ni
  asumir valores.
- Nunca modificar nada en `01_Data/01_Raw/`.