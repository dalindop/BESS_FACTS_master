# -*- coding: utf-8 -*-
"""Prueba de entorno: Streamlit + Pyomo + Gurobi. Archivo desechable."""

import sys
import streamlit as st
import pandas as pd
import plotly.express as px

# 1. Configuracion de la pagina. Debe ser la PRIMERA llamada st.* del script.
#    layout="wide" aprovecha el ancho de pantalla; util para tablas y graficas.
st.set_page_config(page_title="Prueba de entorno", layout="wide")

# 2. Texto. st.title y st.write son la forma basica de escribir en la pagina.
st.title("Verificacion del entorno")
st.write("Interprete en uso:")
st.code(sys.executable)

# 3. Comprobacion de las librerias del modelo. Se hace DENTRO de la app
#    para confirmar que Streamlit corre en el mismo entorno que Pyomo.
st.subheader("Librerias del modelo")

try:
    import pyomo.environ as pyo
    st.success(f"Pyomo disponible: {pyo.__file__.split('pyomo')[0]}")
except ImportError as e:
    st.error(f"Pyomo NO disponible: {e}")

try:
    import gurobipy
    st.success(f"Gurobi disponible, version {gurobipy.gurobi.version()}")
except ImportError as e:
    st.error(f"gurobipy NO disponible: {e}")
    
try:
    import highspy
    st.success("highspy disponible")
except ImportError as e:
    st.error(f"highspy NO disponible: {e}")

# 4. Un widget. Al mover el deslizador, Streamlit RE-EJECUTA todo el script
#    y la variable 'n' toma el nuevo valor. Ese es el modelo de ejecucion.
st.subheader("Prueba de widget y grafica")
n = st.slider("Numero de horas a graficar", min_value=6, max_value=48, value=24)

# 5. Un DataFrame de mentira, con la forma que tendra tu perfil de demanda.
df = pd.DataFrame({
    "Hora": range(1, n + 1),
    "Demanda [MW]": [100 + 30 * ((h % 12) / 12) for h in range(1, n + 1)],
})

# 6. Grafica con Plotly. st.plotly_chart la inserta en la pagina.
fig = px.line(df, x="Hora", y="Demanda [MW]", markers=True,
              title="Perfil de prueba")
st.plotly_chart(fig, use_container_width=True)

# 7. Tabla. st.dataframe la muestra interactiva (ordenable, con scroll).
st.dataframe(df, use_container_width=True)