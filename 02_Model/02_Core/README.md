## Decisiones de Arquitectura

### Convención de nombres para módulos de Python

El proyecto evita intencionalmente utilizar nombres de archivos Python iniciando por números, por ejemplo:

```txt
01_sets.py
02_parameters.py
03_variables.py
04_objective.py
05_constraints.py
06_model_builder.py
```

Aunque visualmente parecen organizados, Python no permite importar módulos cuyos nombres comienzan con números. Por ejemplo:

```python
import 01_sets
```

produce un error de sintaxis.

Para garantizar una arquitectura limpia, modular y fácil de mantener, el proyecto adopta nombres descriptivos compatibles con las convenciones estándar de Python.

Convención actual:

```txt
sets.py
parameters.py
variables.py
objective.py
constraints.py
builder.py
```

Esto permite realizar importaciones limpias y mantenibles, por ejemplo:

```python
from sets import build_sets
from parameters import build_parameters
from variables import build_variables
```

### ¿Por qué se tomó esta decisión?

Esta tesis evolucionará progresivamente desde un modelo base de expansión de transmisión con BESS hacia la integración de dispositivos FACTS. A medida que aumente la complejidad del modelo, será necesario mantener un código:

* Modular
* Escalable
* Fácil de depurar
* Fácil de extender
* Compatible con buenas prácticas de Python

Usar nombres descriptivos evita dependencias innecesarias, hacks de importación y problemas futuros de mantenimiento.

Además, esta arquitectura facilitará incorporar nuevos módulos como:

```txt
facts_constraints.py
facts_variables.py
bess_constraints.py
solver_runner.py
results_export.py
```