# BESS_FACTS_master

Repositorio principal de trabajo para la tesis de maestría enfocada en la integración de **BESS (Battery Energy Storage Systems)** y **FACTS (Flexible AC Transmission Systems)** en modelos de expansión/operación del sistema eléctrico colombiano mediante optimización matemática en **Pyomo**.

---

# Objetivo del proyecto

Este repositorio tiene como propósito:

1. **Reproducir y validar** el modelo base desarrollado por Álvaro.
2. **Migrar el modelo a una arquitectura limpia y modular** usando Python moderno y Pyomo actualizado.
3. **Incorporar dispositivos FACTS** dentro del problema de localización, dimensionamiento y operación del BESS.
4. Evaluar escenarios comparativos para analizar impactos técnicos y económicos.

---

# Arquitectura del proyecto

La estructura del proyecto está organizada para mantener una separación clara entre:

* Datos
* Modelo matemático
* Solver
* Postprocesamiento
* Experimentos
* Validación
* Documentación

```txt
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
├── .gitignore
├── README.md
└── BESS_FACTS_master.code-workspace
```

---

# Estructura detallada

## 01_Data/

Contiene todos los datos del proyecto.

```txt
01_Data/
│
├── 01_Raw/
├── 02_Processed/
└── 03_Test_Cases/
```

### 01_Raw/

Datos originales sin modificar.

Ejemplos:

* Archivos de Álvaro
* Datos XM
* Casos IEEE
* Excel originales
* CSV crudos

**Regla:** nunca modificar archivos aquí.

---

### 02_Processed/

Datos ya limpios y transformados para el modelo.

Ejemplos:

* Matrices organizadas
* Datos normalizados
* Parámetros preprocesados

---

### 03_Test_Cases/

Casos pequeños para pruebas rápidas.

Ejemplos:

* IEEE 9 buses
* IEEE 14 buses
* Casos reducidos de Colombia

Se usarán para validar FACTS antes de escalar.

---

# 02_Model/

Corazón del modelo matemático.

Aquí vive toda la formulación de optimización.

```txt
02_Model/
│
├── main.py
│
├── 01_Inputs/
├── 02_Core/
├── 03_Solvers/
├── 04_Postprocessing/
└── 05_Utils/
```

---

## main.py

Archivo principal.

Coordina el flujo completo:

```txt
leer datos
↓
validar datos
↓
crear modelo
↓
resolver
↓
guardar resultados
```

**No debe contener matemáticas del modelo.**

Solo coordinación.

---

## 01_Inputs/

Lectura y validación de datos.

```txt
01_Inputs/
│
├── 01_data_loader.py
└── 02_data_validation.py
```

### 01_data_loader.py

Carga archivos:

* Excel
* CSV
* JSON
* Casos de prueba

Ejemplo:

* demanda
* líneas
* buses
* generadores
* parámetros BESS

---

### 02_data_validation.py

Verifica consistencia de datos.

Ejemplos:

* valores faltantes
* buses inexistentes
* reactancias vacías
* errores dimensionales

---

## 02_Core/

Núcleo matemático del modelo Pyomo.

```txt
02_Core/
│
├── 01_sets.py
├── 02_parameters.py
├── 03_variables.py
├── 04_objective.py
├── 05_constraints.py
└── 06_model_builder.py
```

---

### 01_sets.py

Define conjuntos del modelo.

Ejemplos:

* buses
* líneas
* generadores
* tiempo
* tecnologías

---

### 02_parameters.py

Parámetros del sistema.

Ejemplos:

* demanda
* reactancias
* costos
* límites de generación
* eficiencia BESS

---

### 03_variables.py

Variables de decisión.

Ejemplos:

* generación
* flujo
* ángulos
* SOC batería
* potencia carga/descarga

---

### 04_objective.py

Función objetivo.

Ejemplos:

Minimizar:

* costo operacional
* costo inversión
* penalizaciones
* costos FACTS

---

### 05_constraints.py

Restricciones matemáticas.

Ejemplos:

* balance nodal
* flujo DC
* límites de línea
* SOC del BESS
* restricciones FACTS

---

### 06_model_builder.py

Construye el modelo completo.

Se encarga de ensamblar:

```txt
sets
↓
parameters
↓
variables
↓
objective
↓
constraints
```

---

## 03_Solvers/

Configuración y ejecución del solver.

```txt
03_Solvers/
│
├── 01_solvers_config.py
└── 02_solvers_runner.py
```

### 01_solvers_config.py

Configura solver.

Ejemplos:

* CBC
* Gurobi
* HiGHS
* CPLEX

Parámetros:

* mip gap
* threads
* time limit

---

### 02_solvers_runner.py

Ejecuta la optimización.

Ejemplo:

```python
results = solver.solve(model)
```

---

## 04_Postprocessing/

Resultados y visualización.

```txt
04_Postprocessing/
│
├── 01_results_export.py
├── 02_plots.py
└── 03_kpi_analysis.py
```

### 01_results_export.py

Exporta resultados.

Ejemplos:

* Excel
* CSV
* DataFrames

---

### 02_plots.py

Gráficas.

Ejemplos:

* despacho
* SOC batería
* utilización FACTS
* costos

---

### 03_kpi_analysis.py

Indicadores del sistema.

Ejemplos:

* costos totales
* congestión
* reducción pérdidas
* utilización BESS

---

## 05_Utils/

Funciones auxiliares reutilizables.

```txt
05_Utils/
│
├── 01_paths.py
├── 02_helpers.py
└── 03_loggers.py
```

### 01_paths.py

Centraliza rutas del proyecto.

Evita hardcoding.

---

### 02_helpers.py

Funciones pequeñas reutilizables.

Ejemplos:

* conversiones
* limpieza
* validaciones rápidas

---

### 03_loggers.py

Mensajes organizados del sistema.

Ejemplos:

```txt
Modelo construido
Solver iniciado
Resultados exportados
```

---

# 03_Experiments/

Escenarios de simulación.

Ejemplos:

* 24h
* 168h
* 720h

Escenarios:

* baseline
* solo BESS
* solo FACTS
* BESS + FACTS

---

# 04_Outputs/

Resultados generados automáticamente.

Ejemplos:

* Excel
* figuras
* reportes
* logs

---

# 05_Tests/

Pruebas unitarias y validaciones.

Ejemplos:

* validación de restricciones
* consistencia de datos
* comparación con Álvaro

---

# 06_Docs/

Documentación de tesis.

Ejemplos:

* papers
* notas técnicas
* decisiones de modelado
* formulaciones matemáticas

---

# 07_Notebooks/

Análisis exploratorio.

Jupyter notebooks para:

* visualización rápida
* pruebas
* debugging

---

# Convención de trabajo

## GitFlow

Se trabajará con:

```txt
main
develop
feature/*
```

Ejemplos:

```txt
feature/core-model
feature/facts-model
feature/validation
```

---

## Regla del proyecto

Antes de agregar FACTS:

**el modelo base de Álvaro debe estar completamente reproducido y validado en esta nueva arquitectura.**

Luego:

1. Validación baseline
2. Integración FACTS
3. Comparación de escenarios
4. Resultados de tesis

## Environment Setup

This repository uses an isolated Python environment (`.venv`) for reproducibility.

### Recommended Python version

```txt
Python 3.11.x
```

### Create environment

```bash
python -m venv .venv
```

### Activate environment

**Git Bash**

```bash
source .venv/Scripts/activate
```

**PowerShell**

```powershell
.venv\Scripts\activate
```

### Install dependencies

```bash
pip install -r requirements-lock.txt
```

### Main scientific stack

* Pyomo
* Pandas
* NumPy
* Matplotlib
* SciPy
* OpenPyXL
* Jupyter Notebook

### Solver strategy

Current development uses open-source solvers during prototyping.

Planned production solver:

* Gurobi (academic license)

Fallback solver:

* CBC
