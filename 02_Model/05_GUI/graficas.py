# -*- coding: utf-8 -*-
"""
==================================================================
 GRAFICAS DE LA INTERFAZ
------------------------------------------------------------------
Autor : Daniel Lindo -- Universidad Nacional de Colombia (UNAL)
Tesis : Maestria en Ingenieria Electrica, 2026
------------------------------------------------------------------

Construye las figuras Plotly de la interfaz a partir del Excel de
resultados que genera results_export.py.

Separacion de responsabilidades: este modulo NO ejecuta el modelo ni
conoce Pyomo. Solo lee el Excel de salida y devuelve figuras. Eso
permite graficar resultados de corridas anteriores sin volver a
resolver.

Estructura del Excel de resultados (ver results_export._escribir_tabla):
    fila 1 -> titulo de la tabla
    fila 2 -> vacia
    fila 3 -> encabezados
    fila 4+ -> datos
Por eso todas las lecturas usan header=2 (indice base cero).
==================================================================
"""

import pandas as pd
import plotly.graph_objects as go

# ------------------------------------------------------------------
# PALETA DE LAS SERIES
# Los colores de la interfaz viven en app.py; aqui solo los de las
# series graficadas, derivados de la paleta institucional UNAL.
# ------------------------------------------------------------------
COLOR_SERIE = {
    "Hidraulica":    "#1F77B4",   # azul, convencion para hidro
    "Gas":           "#565A5C",   # Pantone 425 C
    "Carbon":        "#2F3234",   # gris muy oscuro
    "Liquidos":      "#76232F",   # Pantone 188 C
    "Biomasa":       "#94B43B",   # Pantone 376 C, institucional
    "Renovable":     "#94B43B",   # Pantone 376 C
    "BESS descarga": "#466B3F",   # Pantone 7743 C
    "BESS carga":    "#B1B2B0",   # Pantone 421 C
    "Demanda":       "#000000",
    "Perdidas":      "#B1B2B0",
    "Congestion":    "#A61C31",   # Pantone 187 C, color alterno
}

# Clasificacion de generadores por sufijo del identificador.
# Criterio de PRESENTACION, no de modelado: agrupa los recursos como
# los publica XM. Ver nota en el Capitulo 5.
SUFIJO_TECNOLOGIA = {
    "HID": "Hidraulica",
    "GAS": "Gas",
    "GLP": "Gas",
    "CAR": "Carbon",
    "ACP": "Liquidos",
    "FUE": "Liquidos",
    "JET": "Liquidos",
    "BIO": "Biomasa",
}

# Fondo blanco forzado: la app puede tener fondo tintado, pero las
# figuras exportadas al documento de la tesis deben ir en blanco puro.
LAYOUT_BASE = dict(
    paper_bgcolor="white",
    plot_bgcolor="white",
    font=dict(family="sans-serif", size=12, color="#565A5C"),
    margin=dict(l=60, r=30, t=50, b=50),
    hovermode="x unified",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
)


# ==================================================================
# LECTURA
# ==================================================================
def hojas_disponibles(ruta):
    """Devuelve la lista de hojas del Excel de resultados."""
    return pd.ExcelFile(ruta).sheet_names


def leer(ruta, hoja):
    """
    Lee una hoja del Excel de resultados como DataFrame.

    header=2 salta el titulo (fila 1) y la fila vacia (fila 2), de modo
    que los encabezados reales queden como nombres de columna.
    Devuelve None si la hoja no existe.
    """
    if hoja not in hojas_disponibles(ruta):
        return None
    df = pd.read_excel(ruta, sheet_name=hoja, header=2)
    return df.dropna(how="all")


# ==================================================================
# LECTURA DEL EXCEL DE ENTRADA
# Ojo: estas funciones leen el archivo del CASO, no el de resultados.
# La plantilla de entrada tiene otra estructura: titulo, encabezados,
# fila de unidades, y luego los datos. La fila de encabezados no esta
# en una posicion fija, asi que se detecta igual que en data_loader.
# ==================================================================
def leer_hoja_entrada(ruta_caso, hoja):
    """
    Lee una hoja del Excel de entrada y devuelve un DataFrame.

    Replica la deteccion de data_loader._leer_hoja: la fila de
    encabezados es la primera con dos o mas celdas no vacias, la
    siguiente es la de unidades, y los datos empiezan despues.

    Devuelve None si la hoja no existe o esta vacia.
    """
    try:
        crudo = pd.read_excel(ruta_caso, sheet_name=hoja, header=None)
    except ValueError:          # la hoja no existe
        return None

    hdr = None
    for i in range(len(crudo)):
        if crudo.iloc[i].notna().sum() >= 2:
            hdr = i
            break
    if hdr is None:
        return None

    columnas = [str(c).strip() if pd.notna(c) else ""
                for c in crudo.iloc[hdr]]
    df = crudo.iloc[hdr + 2:].copy()      # +2 salta la fila de unidades
    df.columns = columnas
    df = df.loc[:, [c for c in df.columns if c]]   # descarta columnas sin nombre
    df = df.dropna(how="all")
    return df if len(df) else None


def fig_demanda(ruta_caso):
    """
    Perfil horario de demanda agregada del sistema, con la
    disponibilidad renovable superpuesta.

    Se lee del Excel de ENTRADA, sin resolver el modelo: sirve para
    validar que el caso es verosimil antes de invertir tiempo de solver.

    La disponibilidad renovable se calcula multiplicando las fracciones
    de Renov_Perfil por la capacidad instalada de cada recurso
    (hoja Renovables), igual que hace data_loader.

    Devuelve None si el caso no tiene hoja Demanda utilizable.
    """
    dem = leer_hoja_entrada(ruta_caso, "Demanda")
    if dem is None or "hora" not in dem.columns:
        return None

    dem["hora"] = pd.to_numeric(dem["hora"], errors="coerce")
    dem = dem.dropna(subset=["hora"])

    cols_nodo = [c for c in dem.columns if c != "hora"]
    dem[cols_nodo] = dem[cols_nodo].apply(pd.to_numeric, errors="coerce")
    total = dem[cols_nodo].sum(axis=1)

    fig = go.Figure()

    # --- disponibilidad renovable (area, al fondo) ---
    renov = leer_hoja_entrada(ruta_caso, "Renovables")
    perfil = leer_hoja_entrada(ruta_caso, "Renov_Perfil")
    if renov is not None and perfil is not None and "hora" in perfil.columns:
        caps = {}
        if "id" in renov.columns and "capacidad" in renov.columns:
            for _, f in renov.iterrows():
                caps[str(f["id"]).strip()] = float(f["capacidad"] or 0)
        disp = pd.Series(0.0, index=perfil.index)
        for rid, cap in caps.items():
            if rid in perfil.columns:
                disp += pd.to_numeric(perfil[rid],
                                      errors="coerce").fillna(0) * cap
        if disp.sum() > 0:
            fig.add_trace(go.Scatter(
                x=pd.to_numeric(perfil["hora"], errors="coerce"),
                y=disp,
                name="Disponibilidad renovable",
                mode="lines",
                line=dict(width=0),
                fill="tozeroy",
                fillcolor="rgba(148, 180, 59, 0.35)",   # verde 376 C
                hovertemplate="%{y:.0f} MW<extra></extra>",
            ))

    # --- demanda (linea negra encima) ---
    fig.add_trace(go.Scatter(
        x=dem["hora"], y=total,
        name="Demanda del sistema",
        mode="lines+markers",
        line=dict(color=COLOR_SERIE["Demanda"], width=2.5),
        marker=dict(size=5),
        hovertemplate="%{y:,.0f} MW<extra></extra>",
    ))

    # --- marcas de pico y valle ---
    if len(total):
        i_max, i_min = total.idxmax(), total.idxmin()
        for idx, etiqueta, pos in [(i_max, "Pico", "top"),
                                   (i_min, "Valle", "bottom")]:
            fig.add_annotation(
                x=dem.loc[idx, "hora"], y=total.loc[idx],
                text=f"{etiqueta}: {total.loc[idx]:,.0f} MW",
                showarrow=True, arrowhead=0, arrowwidth=1,
                arrowcolor=COLOR_SERIE["Congestion"],
                ax=0, ay=-25 if pos == "top" else 25,
                font=dict(size=10, color=COLOR_SERIE["Congestion"]),
            )

    fig.update_layout(
        **LAYOUT_BASE,
        xaxis_title="Hora",
        yaxis_title="Potencia [MW]",
        height=340,
    )
    return fig

def clasificar_despacho(df_despacho):
    """
    PENDIENTE.

    Agrupa las columnas de la hoja Despacho por tecnologia usando
    SUFIJO_TECNOLOGIA, e ignora las columnas de estado (prefijo 'u_').
    Devuelve un DataFrame con una columna por tecnologia y la hora
    como indice.
    """
    return None


# ==================================================================
# FIGURAS
# ==================================================================
def fig_cobertura(ruta):
    """
    PENDIENTE. Requisito 4.a de la tesis.

    Area apilada de generacion por tecnologia, con la demanda como
    linea negra superpuesta. Responde de un vistazo si el sistema
    cubre la carga y con que recursos.

    Fuentes: hoja Despacho (agrupada por tecnologia) y hoja Balance
    (columnas Demanda y Perdidas).
    """
    return None


def fig_bess(ruta):
    """
    PENDIENTE. Requisito 4.b de la tesis.

    Operacion del BESS con doble eje: carga y descarga en MW a la
    izquierda, estado de carga en MWh a la derecha. El doble eje es
    necesario porque MW y MWh son magnitudes distintas y compartir eje
    aplasta una de las dos.

    Fuente: hoja BESS_operacion. Devuelve None si el caso no instalo
    ningun BESS.
    """
    return None


def fig_flujos(ruta, n_lineas=5):
    """
    PENDIENTE. Requisito 4.c de la tesis.

    Flujo horario de las n_lineas mas cargadas, ordenadas por flujo
    maximo absoluto. Solo un subconjunto: graficar las 26 lineas del
    sistema colombiano produce una figura ilegible.

    Fuente: hoja Flujos.
    """
    return None


def fig_barrido(ruta_barrido):
    """
    PENDIENTE. Requisito 5 de la tesis.

    Resultado del barrido de costos: capacidad instalada y costo total
    frente al factor de costo de inversion. Es la contribucion
    analitica principal del trabajo.

    Fuente: salida de barrido_costos.py.
    """
    return None