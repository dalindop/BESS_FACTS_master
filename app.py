# -*- coding: utf-8 -*-
"""
==================================================================
 INTERFAZ GRAFICA - app.py
------------------------------------------------------------------
Autor : Daniel Lindo -- Universidad Nacional de Colombia (UNAL)
Tesis : Maestria en Ingenieria Electrica, 2026
------------------------------------------------------------------

Interfaz web para el modelo DC-MILP de expansion de transmision
con BESS y TCSC. Corresponde al objetivo especifico OE3.

Uso:
    python -m streamlit run app.py

Este archivo vive en la RAIZ del repositorio, junto a main.py, para
que las rutas relativas a 01_Data/ y 03_Outputs/ coincidan con las
que usa el modelo.
==================================================================
"""

import os
from pathlib import Path

import contextlib
import io
import traceback

import openpyxl
import streamlit as st

# ------------------------------------------------------------------
# RUTAS. Se derivan de la ubicacion de este archivo, no del directorio
# desde el que se lanza el comando. Asi la app funciona igual sin
# importar donde este parada la terminal.
# ------------------------------------------------------------------
# ==================================================================
# PALETA INSTITUCIONAL UNAL
# Fuente: Guia de identidad visual, seccion B1 - Paleta de color.
# ==================================================================
VERDE_INST  = "#94B43B"   # Pantone 376 C - color institucional
ROJO_ALT    = "#A61C31"   # Pantone 187 C - color alterno
VERDE_OSC   = "#466B3F"   # Pantone 7743 C - complementario
ROJO_OSC    = "#76232F"   # Pantone 188 C  - complementario
GRIS_OSC    = "#565A5C"   # Pantone 425 C  - complementario
GRIS_CLA    = "#B1B2B0"   # Pantone 421 C  - complementario
FONDO_SUAVE = "#F2F4EC"

BASE = Path(__file__).resolve().parent
DIR_CASOS = BASE / "01_Data" / "03_Test_Cases"
DIR_SALIDAS = BASE / "03_Outputs"

# Hojas que data_loader.py exige (validacion estricta) frente a las
# que puede omitir (validacion tolerante).
HOJAS_ESENCIALES = ["Config", "Nodos", "Lineas", "Generadores", "Demanda"]
HOJAS_OPCIONALES = ["Hidraulicos", "Renovables", "Renov_Perfil",
                    "Aportes", "BESS_Cand", "FACTS_Cand"]


# ==================================================================
# CONFIGURACION DE LA PAGINA
# Debe ser la primera llamada st.* del script, sin excepcion.
# ==================================================================
st.set_page_config(
    page_title="TEP con BESS y FACTS",
    page_icon="⚡",
    layout="wide",                    # aprovecha el ancho para tablas
    initial_sidebar_state="expanded",
)


# ==================================================================
# FUNCIONES AUXILIARES
# ==================================================================
def filete():
    """Separador horizontal con el verde institucional atenuado."""
    st.markdown(
        f"<hr style='border:none; border-top:2px solid {VERDE_INST}; "
        f"opacity:0.35; margin:1.5rem 0;'>",
        unsafe_allow_html=True,
    )


def listar_casos():
    """
    Devuelve la lista ordenada de archivos .xlsx en la carpeta de casos.

    Se filtran los archivos que empiezan por '~$': son los bloqueos
    temporales que crea Excel cuando un archivo esta abierto, y no son
    casos validos.
    """
    if not DIR_CASOS.exists():
        return []
    return sorted(
        p for p in DIR_CASOS.glob("*.xlsx") if not p.name.startswith("~$")
    )


def _contar_filas(ws):
    """
    Cuenta las filas de datos de una hoja, replicando la logica de
    data_loader._leer_hoja: la fila de encabezados es la primera con dos
    o mas celdas no vacias, luego viene la fila de unidades, y los datos
    empiezan despues.
    """
    filas = list(ws.iter_rows(values_only=True))
    hdr = None
    for i, fila in enumerate(filas):
        if len([c for c in fila if c is not None]) >= 2:
            hdr = i
            break
    if hdr is None:
        return 0
    return sum(1 for f in filas[hdr + 2:] if any(c is not None for c in f))


@st.cache_data(show_spinner="Leyendo el caso...")
def inspeccionar_caso(ruta_str, mtime):
    """
    Lee el Excel de un caso y devuelve (config, conteos, hojas).

    El decorador @st.cache_data guarda el resultado en memoria: si el
    usuario vuelve a seleccionar el mismo caso, no se relee el archivo.
    Es importante porque Streamlit re-ejecuta TODO el script en cada
    interaccion, y sin cache leeriamos el Excel en cada clic.

    El argumento 'mtime' (fecha de modificacion) no se usa dentro de la
    funcion: esta ahi para invalidar el cache. Si editas el Excel, el
    mtime cambia, la firma de la llamada cambia, y Streamlit relee.
    """
    wb = openpyxl.load_workbook(ruta_str, data_only=True, read_only=True)

    # --- hoja Config: columnas parametro / valor / descripcion ---
    config = {}
    if "Config" in wb.sheetnames:
        ws = wb["Config"]
        filas = list(ws.iter_rows(values_only=True))
        hdr = None
        for i, fila in enumerate(filas):
            valores = [str(c).strip().lower() for c in fila if c is not None]
            if "parametro" in valores:
                hdr = i
                break
        if hdr is not None:
            cols = [str(c).strip().lower() if c else "" for c in filas[hdr]]
            i_par = cols.index("parametro")
            i_val = cols.index("valor") if "valor" in cols else i_par + 1
            for fila in filas[hdr + 1:]:
                if fila[i_par] is not None:
                    config[str(fila[i_par])] = fila[i_val]

    # --- conteo de filas por hoja ---
    conteos = {}
    for nombre in HOJAS_ESENCIALES + HOJAS_OPCIONALES:
        if nombre in wb.sheetnames and nombre != "Config":
            conteos[nombre] = _contar_filas(wb[nombre])

    hojas = list(wb.sheetnames)
    wb.close()
    return config, conteos, hojas

# ==================================================================
# CARGA DIFERIDA DEL MODELO
# ==================================================================
@st.cache_resource(show_spinner=False)
def cargar_main():
    """
    Importa main.py una sola vez por sesion y devuelve el modulo.

    Se usa @st.cache_resource (no cache_data) porque un modulo no es un
    dato serializable: cache_resource guarda el objeto tal cual, en
    memoria, y lo reutiliza. cache_data en cambio serializa el valor.

    La importacion es DIFERIDA a proposito: 'import main' arrastra Pyomo,
    que tarda varios segundos en cargar. Si estuviera arriba del archivo,
    la app entera tardaria eso en arrancar. Asi solo se paga al ejecutar.
    """
    import main as _main
    return _main


class _LogEnVivo(io.TextIOBase):
    """
    Sustituto de sys.stdout que escribe en un contenedor de Streamlit.

    Permite ver el progreso de main.ejecutar() mientras corre, en vez de
    esperar a que termine. Cada print() del modelo se acumula aqui y el
    contenedor se refresca al completarse cada linea.
    """

    def __init__(self, contenedor, max_lineas=18):
        self.contenedor = contenedor
        self.max_lineas = max_lineas
        self.lineas = []
        self._parcial = ""

    def write(self, texto):
        self._parcial += texto
        if "\n" in self._parcial:
            partes = self._parcial.split("\n")
            self._parcial = partes.pop()          # lo que quedo sin cerrar
            self.lineas.extend(p for p in partes)
            # se muestran solo las ultimas lineas para que no crezca
            visible = "\n".join(self.lineas[-self.max_lineas:])
            self.contenedor.code(visible, language=None)
        return len(texto)

    def flush(self):
        pass

    def texto_completo(self):
        return "\n".join(self.lineas)


def extraer_inversiones(modelo):
    """
    Recorre el modelo resuelto y devuelve las decisiones de inversion
    como listas de diccionarios, independientes de Pyomo.

    Se extraen aqui y no se consulta el modelo mas adelante porque los
    diccionarios son ligeros y faciles de pasar a tablas y graficas.
    """
    import pyomo.environ as pyo

    bess = []
    for s in modelo.S:
        p = pyo.value(modelo.Psmax[s])
        if p > 1e-6:
            bess.append({
                "Nodo candidato": str(s),
                "Potencia [MW]": round(p, 2),
                "Energia [MWh]": round(pyo.value(modelo.Esmax[s]), 2),
            })

    facts = []
    for f in modelo.F:
        for z in modelo.Z:
            if pyo.value(modelo.kappa[f, z]) > 0.5:
                facts.append({
                    "Linea candidata": str(f),
                    "Nivel": str(z),
                    "Sigma [p.u.]": round(pyo.value(modelo.sigma[z]), 3),
                    "Q [MVAr]": round(pyo.value(modelo.Q_fz[f, z]), 2),
                })

    return bess, facts


# ------------------------------------------------------------------
# ESTADO DE LA SESION
# st.session_state es un diccionario que SOBREVIVE a las re-ejecuciones
# del script. Es imprescindible aqui: sin el, los resultados se
# perderian en cuanto el usuario tocara cualquier widget, porque el
# boton solo devuelve True en la re-ejecucion inmediata al clic.
# ------------------------------------------------------------------
if "res" not in st.session_state:
    st.session_state.res = None      # dict con el resumen de la corrida

# ==================================================================
# BARRA LATERAL: seleccion del caso y opciones de ejecucion
# ==================================================================
st.sidebar.title("⚡ Modelo TEP")
st.sidebar.caption("Expansion de transmision con BESS y TCSC")
st.sidebar.divider()

casos = listar_casos()

if not casos:
    st.sidebar.error(f"No hay archivos .xlsx en:\n\n`{DIR_CASOS}`")
    st.error(
        "No se encontraron casos de prueba. Verifica que la carpeta "
        f"`01_Data/03_Test_Cases/` exista y contenga archivos .xlsx."
    )
    st.stop()   # detiene el script aqui; no tiene sentido seguir

st.sidebar.subheader("1. Caso de estudio")

# format_func controla lo que VE el usuario; la variable conserva el
# objeto Path completo. Asi se muestra 'caso_IEEE14_E3' en vez de la
# ruta absoluta entera.
caso = st.sidebar.selectbox(
    "Archivo del caso",
    options=casos,
    format_func=lambda p: p.stem,
)

st.sidebar.subheader("2. Opciones de ejecucion")

solver = st.sidebar.radio(
    "Solver",
    options=["Definido en Config", "gurobi", "highs"],
    help="Gurobi es obligatorio en los casos con FACTS: la formulacion "
         "Big-M agota la memoria en HiGHS.",
)

recortar = st.sidebar.checkbox(
    "Recortar horizonte",
    value=False,
    help="Reduce el numero de horas. Util para pruebas rapidas.",
)
horas = None
if recortar:
    horas = st.sidebar.number_input(
        "Horas a simular", min_value=1, max_value=8760, value=24, step=1
    )

exportar = st.sidebar.checkbox(
    "Exportar resultados a Excel", value=True,
    help="Genera el archivo en 03_Outputs/, igual que --export en consola.",
)

st.sidebar.divider()
ejecutar_click = st.sidebar.button(
    "▶ Ejecutar modelo", type="primary", use_container_width=True
)

st.sidebar.divider()
st.sidebar.caption("Universidad Nacional de Colombia\nMaestria en Ing. Electrica")


# ==================================================================
# AREA PRINCIPAL
# st.tabs crea pestañas. Todo el contenido de cada pestaña se calcula
# siempre (Streamlit no ejecuta solo la pestaña visible), asi que no
# conviene poner calculos pesados dentro sin proteccion.
# ==================================================================

# ---- Franja institucional: ancla visual de la aplicacion ----
st.markdown(
    f"""
    <div style="
        border-left: 6px solid {VERDE_INST};
        background: linear-gradient(90deg, {FONDO_SUAVE} 0%, #FFFFFF 100%);
        padding: 0.9rem 1.2rem;
        margin-bottom: 1.2rem;
        width: 100%;">
        <div style="font-size:1.45rem; font-weight:700; color:{GRIS_OSC};
                    line-height:1.2;">
            Expansión de transmisión con BESS y TCSC
        </div>
        <div style="font-size:0.85rem; color:{GRIS_OSC}; opacity:0.8;
                    margin-top:0.2rem;">
            Modelo DC-MILP · Caso: <b>{caso.stem}</b>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

tab_caso, tab_resultados, tab_barrido = st.tabs(
    ["📋 Caso", "📊 Resultados", "📈 Barrido de costos"]
)

# ------------------------------------------------------------------
with tab_caso:
    config, conteos, hojas = inspeccionar_caso(
        str(caso), os.path.getmtime(caso)
    )

    #st.subheader(caso.stem)
    st.markdown(
        f"""<div style="font-family: ui-monospace, monospace;
             font-size:0.78rem; color:{GRIS_OSC};
             background:{FONDO_SUAVE}; border:1px solid {GRIS_CLA};
             border-radius:4px; padding:0.5rem 0.7rem;
             word-break:break-all; margin-bottom:0.8rem;">{caso}</div>""",
        unsafe_allow_html=True,
    )

    # --- validacion de hojas ---
    faltantes = [h for h in HOJAS_ESENCIALES if h not in hojas]
    if faltantes:
        st.error(f"Faltan hojas obligatorias: {', '.join(faltantes)}")
    else:
        st.success("El caso contiene todas las hojas obligatorias.")

    # --- parametros de configuracion en metricas ---
    st.markdown("#### Configuracion")

    def tarjeta(col, etiqueta, valor):
        """Dibuja una metrica dentro de un contenedor con borde."""
        with col:
            with st.container(border=True):
                st.metric(etiqueta, valor)

    c1, c2, c3, c4 = st.columns(4)
    tarjeta(c1, "Horizonte", f"{config.get('horizonte', '?')} h")
    tarjeta(c2, "S base", f"{config.get('S_base', '?')} MVA")
    tarjeta(c3, "Solver (Config)", str(config.get("solver", "?")))
    tarjeta(c4, "Perdidas", "Si" if config.get("incluir_perdidas") else "No")

    c5, c6, c7, c8 = st.columns(4)
    tarjeta(c5, "Theta max", f"{config.get('theta_max_grados', '?')}°")
    tarjeta(c6, "Tasa descuento", f"{config.get('tasa_descuento', '?')}")
    tarjeta(c7, "MIP gap", f"{config.get('mip_gap', '?')}")
    tarjeta(c8, "Limite tiempo", f"{config.get('time_limit', '?')} s")

    st.markdown("#### Dimension del sistema")
    d1, d2, d3 = st.columns(3)
    tarjeta(d1, "Nodos", conteos.get("Nodos", 0))
    tarjeta(d2, "Lineas", conteos.get("Lineas", 0))
    tarjeta(d3, "Generadores termicos", conteos.get("Generadores", 0))

    d4, d5, d6 = st.columns(3)
    tarjeta(d4, "Unidades hidraulicas", conteos.get("Hidraulicos", 0))
    tarjeta(d5, "Candidatos BESS", conteos.get("BESS_Cand", 0))
    tarjeta(d6, "Candidatos FACTS", conteos.get("FACTS_Cand", 0))

    # --- escenario inferido a partir de los candidatos ---
    n_bess = conteos.get("BESS_Cand", 0)
    n_facts = conteos.get("FACTS_Cand", 0)

    COLOR_ESC = {
        "E0": (GRIS_OSC,   "Caso base, sin candidatos de inversión"),
        "E1": (VERDE_OSC,  "Solo BESS"),
        "E2": (ROJO_OSC,   "Solo FACTS (TCSC)"),
        "E3": (VERDE_INST, "Inversión conjunta BESS + FACTS"),
    }

    if n_bess and n_facts:
        esc = "E3"
    elif n_bess:
        esc = "E1"
    elif n_facts:
        esc = "E2"
    else:
        esc = "E0"

    color, texto = COLOR_ESC[esc]
    # E3 usa el verde institucional, que es claro: su texto va en negro.
    txt = "#000000" if esc == "E3" else "#FFFFFF"
    st.markdown(
        f"""<div style="margin: 0.6rem 0 1rem 0;">
        <span style="background:{color}; color:{txt}; padding:0.28rem 0.75rem;
              border-radius:4px; font-weight:700; font-size:0.9rem;">
            Escenario {esc}</span>
        <span style="margin-left:0.7rem; color:{GRIS_OSC};">{texto}</span>
        </div>""",
        unsafe_allow_html=True,
    )

    with st.expander("Ver todas las hojas del archivo"):
        st.write(hojas)

# ------------------------------------------------------------------
with tab_resultados:

    # --- 1. EJECUCION (solo cuando se presiona el boton) ---
    if ejecutar_click:
        st.session_state.res = None          # descarta la corrida previa
        modulo_main = cargar_main()

        with st.status("Ejecutando el modelo...", expanded=True) as estado:
            caja_log = st.empty()
            log = _LogEnVivo(caja_log)
            try:
                # redirect_stdout captura los print() de main.ejecutar()
                # y los envia al contenedor de Streamlit.
                with contextlib.redirect_stdout(log):
                    modelo, salida = modulo_main.ejecutar(
                        str(caso),
                        solver=None if solver == "Definido en Config" else solver,
                        horas=int(horas) if horas else None,
                        exportar=exportar,
                        verbose=True,
                    )

                if salida["resuelto"]:
                    bess, facts = extraer_inversiones(modelo)
                    st.session_state.res = {
                        "caso": caso.stem,
                        "status": salida["status"],
                        "solver": salida["solver"],
                        "costo": salida["valor_objetivo"],
                        "t_solver": salida.get("tiempo_s"),
                        "t_proceso": salida.get("tiempo_procesamiento_s"),
                        "ruta_excel": salida.get("ruta_resultados"),
                        "bess": bess,
                        "facts": facts,
                        "log": log.texto_completo(),
                    }
                    estado.update(label="Modelo resuelto", state="complete",
                                  expanded=False)
                else:
                    estado.update(
                        label=f"Sin solucion: {salida['status']}",
                        state="error", expanded=True)
                    st.error(
                        f"El solver termino con estado **{salida['status']}**. "
                        "Si es `infeasible`, revisa los limites de generacion "
                        "y la demanda del caso."
                    )

            except Exception:
                estado.update(label="Error durante la ejecucion",
                              state="error", expanded=True)
                st.error("La ejecucion fallo. Traza completa:")
                st.code(traceback.format_exc())

    # --- 2. PRESENTACION (se dibuja en toda re-ejecucion posterior) ---
    res = st.session_state.res

    if res is None:
        st.info("Selecciona un caso y presiona **Ejecutar modelo** "
                "en la barra lateral.")
    else:
        st.subheader(f"Resultados: {res['caso']}")

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Costo total", f"{res['costo']:,.0f} USD")
        m2.metric("Terminacion", res["status"])
        m3.metric("Solver", res["solver"])
        m4.metric("Tiempo solver",
                  f"{res['t_solver']:.1f} s" if res["t_solver"] else "n/d")

        filete()
        st.markdown("#### Decisiones de inversion")

        col_b, col_f = st.columns(2)
        with col_b:
            st.markdown("**BESS**")
            if res["bess"]:
                st.dataframe(res["bess"], use_container_width=True,
                             hide_index=True)
            else:
                st.caption("Ninguno instalado.")
        with col_f:
            st.markdown("**TCSC**")
            if res["facts"]:
                st.dataframe(res["facts"], use_container_width=True,
                             hide_index=True)
            else:
                st.caption("Ninguno instalado.")

        # --- descarga del Excel de resultados ---
        if res["ruta_excel"] and os.path.exists(res["ruta_excel"]):
            filete()
            with open(res["ruta_excel"], "rb") as fh:
                st.download_button(
                    "⬇ Descargar Excel de resultados",
                    data=fh.read(),
                    file_name=os.path.basename(res["ruta_excel"]),
                    mime=("application/vnd.openxmlformats-officedocument"
                          ".spreadsheetml.sheet"),
                )

        with st.expander("Ver registro de la ejecucion"):
            st.code(res["log"], language=None)