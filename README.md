# BESS_FACTS_master

Repositorio principal para el desarrollo de la tesis de maestría enfocada en la integración de **BESS (Battery Energy Storage Systems)** y **FACTS (Flexible AC Transmission Systems)** en modelos de expansión y operación del sistema eléctrico utilizando **Pyomo**.

---

# Objetivo del proyecto

Este repositorio tiene como propósito:

1. Reproducir el modelo baseline desarrollado originalmente en **HEPISA (modelo de Álvaro)**.
2. Modernizar el entorno computacional.
3. Construir una arquitectura modular, limpia y mantenible.
4. Integrar dispositivos **FACTS** como aporte principal de tesis.
5. Evaluar escenarios comparativos de flexibilidad del sistema eléctrico.

---

# Estructura del repositorio

```text
BESS_FACTS_master/
│
├── 01_Data/
├── 02_Model/
├── 03_Experiments/
├── 04_Outputs/
├── 05_Tests/
├── 06_Docs/
├── 07_Notebooks/
│
├── README.md
├── .gitignore
└── BESS_FACTS_master.code-workspace
```

---

# Descripción de carpetas

## `01_Data/`

Contiene todos los **datos de entrada del modelo**.

Aquí se almacenan:

- Topología de red
- Demandas
- Generación
- Parámetros eléctricos
- Tecnologías BESS
- Casos de estudio
- Archivos Excel/CSV

Ejemplo esperado:

```text
01_Data/
│
├── Raw/
├── Processed/
└── Test_Cases/
```

### `Raw/`

Datos originales.

**Nunca modificarlos directamente.**

Ejemplo:

```text
Tech.csv
system_data.xlsx
```

---

### `Processed/`

Datos ya procesados o transformados para el modelo.

Ejemplo:

- normalización
- limpieza de datos
- formatos intermedios

---

### `Test_Cases/`

Casos de prueba del modelo.

Ejemplos:

```text
24h/
168h/
720h/
IEEE_9/
IEEE_14/
```

---

## `02_Model/`

Es el **núcleo matemático del proyecto**.

Aquí vive el modelo de optimización construido en Pyomo.

Arquitectura esperada:

```text
02_Model/
│
├── Core/
├── BESS/
├── FACTS/
├── Solvers/
└── Utils/
```

---

### `Core/`

Modelo baseline de optimización.

Contendrá:

```text
sets.py
parameters.py
variables.py
constraints.py
objective.py
model_builder.py
```

#### `sets.py`

Define los conjuntos del problema.

Ejemplo:

```python
model.b = Set()
model.t = Set()
```

---

#### `parameters.py`

Carga los parámetros del sistema.

Ejemplos:

- demanda
- reactancias
- costos
- límites de transmisión

---

#### `variables.py`

Define las variables de decisión.

Ejemplos:

- generación
- potencia BESS
- energía almacenada
- flujo de potencia
- ángulos nodales

---

#### `constraints.py`

Define todas las restricciones.

Ejemplos:

- balance nodal
- flujo DC
- SOC de baterías
- límites de líneas
- binarias de carga/descarga

---

#### `objective.py`

Función objetivo del modelo.

Ejemplo:

Minimización de:

- costos operativos
- inversión
- penalizaciones

---

### `BESS/`

Restricciones específicas del sistema de almacenamiento.

Ejemplos:

- carga/descarga
- SOC
- degradación
- límites energéticos

---

### `FACTS/`

Aquí irá el aporte principal de tesis.

Incluye:

- formulación matemática
- variables FACTS
- restricciones adicionales
- linealizaciones

Ejemplos futuros:

```text
tcsc.py
svc.py
facts_constraints.py
```

---

### `Solvers/`

Configuraciones de solucionadores.

Ejemplos:

```text
cbc_solver.py
gurobi_solver.py
highs_solver.py
```

Aquí se definirán:

- mip gap
- límites de tiempo
- tolerancias
- threads

---

### `Utils/`

Funciones auxiliares.

Ejemplo:

- lectura de archivos
- exportación
- procesamiento de resultados

---

## `03_Experiments/`

Scripts para correr distintos escenarios.

Ejemplos:

```text
run_24h.py
run_168h.py
run_720h.py
run_facts_case.py
```

Objetivo:

Separar experimentos del modelo base.

---

## `04_Outputs/`

Resultados generados automáticamente.

Ejemplos:

```text
Excel/
Figures/
Logs/
```

Aquí irán:

- resultados Excel
- gráficas
- logs del solver
- reportes

### Importante

Esta carpeta **NO debe versionarse en GitHub**.

Solo contiene archivos generados.

---

## `05_Tests/`

Pruebas del modelo.

Objetivo:

Validar que el código no se rompa.

Ejemplos:

- consistencia dimensional
- validación baseline
- comparación contra HEPISA

---

## `06_Docs/`

Documentación técnica del proyecto.

Ejemplo esperado:

```text
06_Docs/
│
├── bitacora.md
├── ecuaciones.md
└── architecture.md
```

---

### `bitacora.md`

Registro técnico de decisiones.

Ejemplos:

- cambios de solver
- mejoras numéricas
- bugs encontrados
- validaciones

---

### `ecuaciones.md`

Formulación matemática del modelo.

Incluye:

- baseline HEPISA
- ecuaciones BESS
- formulación FACTS
- linealizaciones

---

### `architecture.md`

Mapa conceptual del software.

Incluye:

- flujo de datos
- dependencias
- arquitectura modular

---

## `07_Notebooks/`

Exploración rápida y análisis.

Uso esperado:

- pruebas pequeñas
- visualización
- depuración matemática

**No usar para el modelo final.**

---

# Flujo Git recomendado

Nunca trabajar directamente sobre `main`.

Estructura:

```text
main
↑
develop
↑
feature/*
```

Ejemplos:

```text
feature/project-skeleton
feature/core-model
feature/bess-module
feature/facts-formulation
feature/solver-config
feature/validation-baseline
```

---

# Principios de desarrollo

1. **Reproducir antes de extender**
2. **Validar antes de optimizar**
3. **Una feature = un propósito**
4. **Cambios pequeños y trazables**
5. **No modificar múltiples componentes críticos simultáneamente**

---

# Roadmap de tesis

## Fase 1 — Reproducción baseline

- [ ] Reproducir modelo de Álvaro
- [ ] Validar 24h
- [ ] Validar 168h
- [ ] Validar 720h

---

## Fase 2 — Reimplementación limpia

- [ ] Modularización
- [ ] Migración Pyomo moderno
- [ ] Solver robusto
- [ ] Validación cruzada

---

## Fase 3 — Integración FACTS

- [ ] Formulación matemática
- [ ] Linealización
- [ ] Integración Pyomo

---

## Fase 4 — Experimentos de tesis

- [ ] Escenarios comparativos
- [ ] Sensibilidades
- [ ] Resultados finales

---

# Nota importante

Si en algún momento el proyecto se vuelve caótico:

> **Volver al baseline validado antes de continuar.**

No introducir múltiples cambios críticos al mismo tiempo.