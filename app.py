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

import tempfile

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

# 05_GUI empieza por digitos y no es un nombre de modulo valido en
# Python, asi que se registra la carpeta en el path y se importa
# 'graficas' directamente. Mismo patron que usa main.py.
import sys
_GUI = str(BASE / "02_Model" / "05_GUI")
if _GUI not in sys.path:
    sys.path.append(_GUI)

import graficas

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
    page_title="BESS_TCSC",
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

@st.cache_data(show_spinner=False)
def guardar_temporal(nombre, contenido):
    """
    Escribe un archivo subido en una carpeta temporal y devuelve su ruta.

    Es necesario porque st.file_uploader entrega el archivo en MEMORIA,
    mientras que main.ejecutar() espera una RUTA en disco.

    El cache evita reescribir el archivo en cada re-ejecucion del script;
    se invalida solo si cambia el nombre o el contenido.
    """
    destino = Path(tempfile.gettempdir()) / "casos_tep"
    destino.mkdir(exist_ok=True)
    ruta = destino / nombre
    ruta.write_bytes(contenido)
    return ruta

def excel_en_memoria(encabezados, filas, hoja="Barrido"):
    """
    Construye un Excel en MEMORIA y devuelve sus bytes.

    No se escribe nada en disco: st.download_button recibe los bytes
    directamente y el navegador se encarga de la descarga. El archivo
    solo existe si el usuario pulsa el boton.
    """
    from io import BytesIO
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = hoja
    ws.append(list(encabezados))
    for f in filas:
        ws.append(list(f))

    buffer = BytesIO()
    wb.save(buffer)          # openpyxl acepta un objeto tipo archivo
    return buffer.getvalue()


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
    
if "corriendo" not in st.session_state:
    st.session_state.corriendo = False

# ==================================================================
# BARRA LATERAL: seleccion del caso y opciones de ejecucion
# ==================================================================
st.sidebar.title("⚡ Modelo DC-MILP con pérdidas para dimensionamiento y localización de FACTS y BESS")
st.sidebar.caption("Modelo DC-MILP con pérdidas · FACTS y BESS")
st.sidebar.divider()

st.sidebar.subheader("1. Caso de estudio")

origen = st.sidebar.radio(
    "Origen del caso",
    options=["Casos del repositorio", "Subir un archivo"],
    key="radio_origen",
    help="Los **casos del repositorio** son los archivos de "
         "`01_Data/03_Test_Cases/`, versionados junto al código y usados "
         "en los resultados de la tesis.\n\n"
         "**Subir un archivo** permite analizar un sistema propio, "
         "siempre que respete la plantilla Excel del modelo: hojas "
         "Config, Nodos, Lineas, Generadores y Demanda como mínimo.",
         disabled=st.session_state.corriendo,
)

if origen == "Casos del repositorio":
    casos = listar_casos()
    if not casos:
        st.sidebar.error(f"No hay archivos .xlsx en:\n\n`{DIR_CASOS}`")
        st.error(
            "No se encontraron casos. Verifica que la carpeta "
            "`01_Data/03_Test_Cases/` contenga archivos .xlsx, o usa la "
            "opción **Subir un archivo**."
        )
        st.stop()
    caso = st.sidebar.selectbox(
        "Archivo del caso",
        options=casos,
        format_func=lambda p: p.stem,
        key="sel_caso_repo",
        disabled=st.session_state.corriendo,
    )
else:
    subido = st.sidebar.file_uploader(
        "Archivo del caso (.xlsx)",
        type=["xlsx"],
        key="up_caso",
        help="El archivo debe seguir la plantilla del modelo. Se guarda "
             "en una carpeta temporal solo durante esta sesión; no se "
             "copia al repositorio.",
             disabled=st.session_state.corriendo,
    )
    if subido is None:
        st.info(
            "Sube un archivo Excel en la barra lateral, o cambia a "
            "**Casos del repositorio** para usar uno de los casos "
            "incluidos."
        )
        st.stop()
    caso = guardar_temporal(subido.name, subido.getvalue())



st.sidebar.subheader("2. Opciones de ejecución")

solver = st.sidebar.radio(
    "Solver",
    options=["Definido en Config", "gurobi", "highs"],
    help="Gurobi es obligatorio en los casos con FACTS: la formulación "
         "Big-M agota la memoria en HiGHS.",
         disabled=st.session_state.corriendo,
)

recortar = st.sidebar.checkbox(
    "Recortar horizonte",
    value=False,
    help="Reduce el número de horas. Útil para pruebas rápidas.",
    disabled=st.session_state.corriendo,
)
horas = None
if recortar:
    horas = st.sidebar.number_input(
        "Horas a simular", min_value=1, max_value=8760, value=24, step=1,
        disabled=st.session_state.corriendo,
    )

exportar = st.sidebar.checkbox(
    "Exportar resultados a Excel", value=True,
    help="Genera el archivo en 03_Outputs/, igual que --export en consola.",
    disabled=st.session_state.corriendo,
)

if st.session_state.corriendo:
    st.sidebar.warning("Ejecución en curso...")

ejecutar_click = st.sidebar.button(
    "▶ Ejecutar modelo", type="primary", use_container_width=True,
    disabled=st.session_state.corriendo,
)

st.sidebar.divider()
_logo_side = BASE / "02_Model" / "05_GUI" / "logos" / "grupo.png"
URL_GRUPO = ("https://ingenieria.bogota.unal.edu.co/es/departamentos/"
             "departamento-ingenieria-electrica-electronica/"
             "#tab-investigacion")

if _logo_side.exists():
    # base64: el navegador no puede leer rutas del disco del servidor,
    # y st.image no acepta enlaces. Incrustar la imagen es la unica
    # forma de envolverla en un <a>.
    import base64
    _b64_side = base64.b64encode(_logo_side.read_bytes()).decode()
    st.sidebar.markdown(
        f"""<a href="{URL_GRUPO}" target="_blank"
              title="Departamento de Ingeniería Eléctrica y Electrónica — UNAL">
            <img src="data:image/png;base64,{_b64_side}" width="130">
        </a>""",
        unsafe_allow_html=True,
    )

st.sidebar.markdown(
    f"""<div style="font-size:0.78rem; color:{GRIS_OSC}; line-height:1.7;">
        <b>Daniel Lindo</b><br>
        Maestría en Ingeniería Eléctrica<br>
        <span style="opacity:0.75;">Universidad Nacional de Colombia · 2026</span><br>
        <a href="mailto:dalindop@unal.edu.co"
           style="color:{VERDE_OSC};">dalindop@unal.edu.co</a>
    </div>""",
    unsafe_allow_html=True,
)


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
            Dimensionamiento y localización de FACTS y de sistemas de almacenamiento basados en baterías con el fin de
reducir los costos de operación y las inversiones de expansión en el sistema de potencia colombiano
        </div>
        <div style="font-size:0.85rem; color:{GRIS_OSC}; opacity:0.8;
                    margin-top:0.2rem;">
            Modelo DC-MILP · Caso: <b>{caso.stem}</b>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

tab_caso, tab_resultados, tab_barrido, tab_modelo = st.tabs(
    ["📋 Caso", "📊 Resultados", "📈 Barrido de costos", "📖 Modelo"]
)

# ------------------------------------------------------------------
with tab_barrido:
    st.markdown("#### Barrido de sensibilidad de costos")
    st.caption(
        "Resuelve el modelo varias veces sobre el mismo caso, escalando "
        "el costo de inversión por una serie de factores. Responde a qué "
        "nivel de costo la tecnología empieza a resultar económicamente "
        "justificada."
    )

    b1, b2 = st.columns(2)
    with b1:
        tecnologia = st.selectbox(
            "Tecnología a barrer",
            options=["bess", "facts", "ambas"],
            format_func=lambda t: {"bess": "BESS (Li-Ion)",
                                   "facts": "FACTS (TCSC)",
                                   "ambas": "Ambas"}[t],
            key="sel_tec_barrido",
            help="**bess** escala solo el costo del almacenamiento (casos "
                 "E1). **facts** solo el del TCSC (casos E2). **ambas** "
                 "escala las dos por el mismo factor (casos E3).",
        )
    with b2:
        factores_txt = st.text_input(
            "Factores de costo",
            value="1.0, 0.75, 0.50, 0.25, 0.10, 0.05, 0.02, 0.01",
            key="txt_factores",
            help="Separados por coma. 1.0 es el costo original NREL; "
                 "0.0 sería costo nulo. Cada factor implica una "
                 "resolución completa del modelo.",
        )

    try:
        factores = [float(x.strip()) for x in factores_txt.split(",")
                    if x.strip()]
    except ValueError:
        factores = []
        st.error("Los factores deben ser números separados por coma.")

    if factores:
        st.warning(
            f"El barrido resolverá el modelo **{len(factores)} veces**. "
            "Con el sistema colombiano puede tardar varios minutos. "
            "Durante ese tiempo la interfaz queda bloqueada y no es "
            "posible ejecutar el modelo ni cambiar de caso.",
            icon="⚠️",
        )

    correr_barrido = st.button(
        "▶ Ejecutar barrido", type="primary", key="btn_barrido",
        disabled=not factores,
    )

    if correr_barrido:
        # Se importa aqui, no arriba, para no cargar Pyomo al arrancar.
        import importlib
        sys.path.insert(0, str(BASE))
        bc = importlib.import_module("barrido_costos")

        with st.status("Ejecutando el barrido...", expanded=True) as est:
            caja = st.empty()
            log_b = _LogEnVivo(caja, max_lineas=40)
            try:
                # barrido() ya imprime una tabla formateada en consola;
                # redirect_stdout la trae a la interfaz.
                with contextlib.redirect_stdout(log_b):
                    encab_b, filas_b = bc.barrido(
                        str(caso),
                        tecnologia=tecnologia,
                        factores=factores,
                        solver=solver if solver in ("gurobi", "highs")
                               else "gurobi",
                    )
                st.session_state.log_barrido = log_b.texto_completo()
                st.session_state.tabla_barrido = (encab_b, filas_b)
                est.update(label="Barrido completado", state="complete",
                           expanded=False)
            except Exception:
                est.update(label="Error durante el barrido",
                           state="error", expanded=True)
                st.error("El barrido falló. Traza completa:")
                st.code(traceback.format_exc())

    # La tabla persiste tras la corrida, igual que los resultados.
    if st.session_state.get("log_barrido"):
        filete()
        st.markdown("#### Resultado")
        st.code(st.session_state.log_barrido, language=None)

        tabla = st.session_state.get("tabla_barrido")
        if tabla:
            st.download_button(
                "⬇ Descargar tabla del barrido (Excel)",
                data=excel_en_memoria(tabla[0], tabla[1]),
                file_name=f"barrido_{tecnologia}_{caso.stem}.xlsx",
                mime=("application/vnd.openxmlformats-officedocument"
                      ".spreadsheetml.sheet"),
                key="dl_barrido",
            )
    
    # La tabla persiste tras la corrida, igual que los resultados.
    if st.session_state.get("log_barrido"):
        filete()
        st.markdown("#### Resultado")
        st.code(st.session_state.log_barrido, language=None)     

# ------------------------------------------------------------------
with tab_caso:
    config, conteos, hojas = inspeccionar_caso(
        str(caso), os.path.getmtime(caso)
    )

    # --- ruta del archivo del caso ---
    st.markdown(
        f"""<div style="font-family: ui-monospace, monospace;
             font-size:0.78rem; color:{GRIS_OSC};
             background:{FONDO_SUAVE}; border:1px solid {GRIS_CLA};
             border-radius:4px; padding:0.5rem 0.7rem;
             word-break:break-all; margin-bottom:0.8rem;">{caso}</div>""",
        unsafe_allow_html=True,
    )
    
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
    
    st.caption(
        "El escenario se deduce de los candidatos de inversión presentes "
        "en el caso: **E0** sin candidatos, **E1** solo BESS, **E2** solo "
        "FACTS, **E3** ambos."
    )
    
    # --- validacion de hojas ---
    faltantes = [h for h in HOJAS_ESENCIALES if h not in hojas]
    if faltantes:
        st.error(f"Faltan hojas obligatorias: {', '.join(faltantes)}")
    else:
        st.success("El caso contiene todas las hojas obligatorias.")

    # --- parametros de configuracion en metricas ---
    st.markdown("#### Configuración")

    def tarjeta(col, etiqueta, valor, ayuda=None):
        """Dibuja una metrica dentro de un contenedor con borde."""
        with col:
            with st.container(border=True):
                st.metric(etiqueta, valor, help=ayuda)

    c1, c2, c3, c4 = st.columns(4)
    tarjeta(c1, "Horizonte", f"{config.get('horizonte', '?')} h",
            "Número de periodos horarios del problema. Define el tamaño "
            "del modelo: a más horas, más variables y mayor tiempo de "
            "solución.")
    tarjeta(c2, "S base", f"{config.get('S_base', '?')} MVA",
            "Potencia base del sistema por unidad. Todas las magnitudes "
            "eléctricas internas del modelo están normalizadas con este "
            "valor.")
    tarjeta(c3, "Solver (Config)", str(config.get("solver", "?")),
            "Solver definido en la hoja Config del caso. Gurobi es "
            "necesario en los casos con FACTS: la formulación Big-M del "
            "TCSC agota la memoria en HiGHS.")
    tarjeta(c4, "Pérdidas", "Sí" if config.get("incluir_perdidas") else "No",
            "Si está activo, el modelo incluye las pérdidas por efecto "
            "Joule linealizadas por tramos. Se desactiva para validar el "
            "flujo DC puro contra MATPOWER.")

    c5, c6, c7 = st.columns(3)
    tarjeta(c5, "Theta max", f"{config.get('theta_max_grados', '?')}°",
            "Cota superior de la diferencia angular entre nodos. Acota el "
            "bloque de pérdidas linealizadas y las constantes Big-M del "
            "TCSC.")
    tarjeta(c6, "Tasa descuento", f"{config.get('tasa_descuento', '?')}",
            "Tasa usada para anualizar la inversión mediante el factor de "
            "recuperación de capital (CRF), y hacerla comparable con los "
            "costos de operación del horizonte.")
    tarjeta(c7, "MIP gap", f"{config.get('mip_gap', '?')}",
            "Tolerancia de optimalidad. El solver se detiene cuando la "
            "brecha entre la mejor solución y la cota inferior baja de "
            "este valor.")

    st.markdown("#### Dimensión del sistema")

    d1, d2, d3, d4 = st.columns(4)
    tarjeta(d1, "Nodos", conteos.get("Nodos", 0),
            "Barras del sistema. Cada una impone una ecuación de balance "
            "de potencia por hora.")
    tarjeta(d2, "Líneas", conteos.get("Lineas", 0),
            "Líneas de transmisión existentes, con su reactancia y "
            "capacidad térmica.")
    tarjeta(d3, "Generadores térmicos", conteos.get("Generadores", 0),
            "Unidades declaradas en la hoja Generadores. Se modelan con "
            "costo linealizado por tramos y restricciones de compromiso "
            "de unidades.")
    tarjeta(d4, "Unidades hidráulicas", conteos.get("Hidraulicos", 0),
            "Unidades con balance de embalse: volumen, caudal turbinado, "
            "vertimiento y aportes. Cero indica que el caso no las "
            "declara en la hoja Hidraulicos.")

    d5, d6, d7 = st.columns(3)
    tarjeta(d5, "Unidades renovables", conteos.get("Renovables", 0),
            "Unidades solares y eólicas de la hoja Renovables. Su "
            "generación está acotada por el perfil de disponibilidad "
            "horaria de Renov_Perfil, y el modelo puede vertir el "
            "excedente (curtailment).")
    tarjeta(d6, "Candidatos BESS (Li-Ion)", conteos.get("BESS_Cand", 0),
            "Nodos donde el modelo puede invertir en almacenamiento. "
            "La potencia y la energía son variables continuas de decisión.")
    tarjeta(d7, "Candidatos FACTS (TCSC)", conteos.get("FACTS_Cand", 0),
            "Líneas donde se puede instalar un TCSC. La compensación es "
            "discreta, en cuatro niveles de σ.")

    

    filete()
    st.markdown("#### Perfil de demanda")
    fig_dem = graficas.fig_demanda(str(caso))
    if fig_dem is None:
        st.info("No se pudo leer la hoja Demanda de este caso.")
    else:
        st.plotly_chart(fig_dem, use_container_width=True)
        st.caption(
            "Demanda agregada de todos los nodos. El área verde es la "
            "disponibilidad renovable, no la generación efectiva: el "
            "modelo decide cuánta aprovecha y cuánta vierte."
        )
    
    
    with st.expander("Ver todas las hojas del archivo"):
        st.write(hojas)

# ------------------------------------------------------------------
with tab_resultados:

    # --- 1. EJECUCION (solo cuando se presiona el boton) ---
        
    # El clic solo REGISTRA la orden y fuerza una re-ejecucion. Es necesario
    # porque la barra lateral se dibuja ANTES de este bloque: si aqui mismo
    # se levantara la bandera, los widgets ya estarian renderizados como
    # habilitados. En la pasada siguiente la bandera ya vale True, la barra
    # lateral se dibuja bloqueada, y es entonces cuando corre el modelo.  
    
    
    import time as _t
    
    if ejecutar_click:
        st.session_state.res = None
        st.session_state.corriendo = True
        st.rerun()
              
    if st.session_state.corriendo:
        _t_app = _t.perf_counter()
        modulo_main = cargar_main()
        _t_import = _t.perf_counter() - _t_app
            
        st.warning(
            "⏳ **Ejecución en curso.** El modelo está resolviendo. "
            "No cierrar esta pestaña ni modificar los parámetros hasta "
            "que termine.",
            icon="⚠️",
        )
        
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
                        reiniciar_cronometro=True,
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
                        "t_total": salida.get("tiempo_total_s"),
                        "t_import": _t_import,
                        "t_app": _t.perf_counter() - _t_app,
                        "ruta_excel": salida.get("ruta_resultados"),
                        "bess": bess,
                        "facts": facts,
                        "log": log.texto_completo(),
                    }
                    estado.update(label="Modelo resuelto", state="complete",
                                  expanded=False)
                else:
                    estado.update(
                        label=f"Sin solución: {salida['status']}",
                        state="error", expanded=True)
                    st.error(
                        f"El solver terminó con estado **{salida['status']}**. "
                        "Si es `infeasible`, revisa los límites de generación "
                        "y la demanda del caso."
                    )

            except Exception:
                estado.update(label="Error durante la ejecución",
                              state="error", expanded=True)
                st.error("La ejecución fallo. Traza completa:")
                st.code(traceback.format_exc())

        # Se libera el bloqueo de la barra lateral y se fuerza una
        # re-ejecucion para que los widgets vuelvan a habilitarse.
        st.session_state.corriendo = False
        st.rerun()

    # --- 2. PRESENTACION (se dibuja en toda re-ejecucion posterior) ---
    res = st.session_state.res

    if res is None:
        st.info("Selecciona un caso y presiona **Ejecutar modelo** "
                "en la barra lateral.")
    else:
        st.subheader(f"Resultados: {res['caso']}")

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Costo total", f"{res['costo']:,.0f} USD")
        m2.metric("Terminación", res["status"])
        m3.metric("Solver", res["solver"])
        m4.metric(
            "Tiempo de proceso",
            f"{res['t_proceso']:.1f} s" if res["t_proceso"] else "n/d",
            help=(
                f"Carga del caso, construcción del modelo, solución y "
                f"exportación. De ese total, el solver empleó "
                f"{res['t_solver']:.1f} s."
                if res["t_solver"] and res["t_proceso"] else
                "Tiempo de procesamiento del caso."
            ),
        )
        
        st.caption(
            f"DEBUG · import: {res['t_import']:.2f} s · "
            f"total app: {res['t_app']:.2f} s · "
            f"modelo: {res['t_proceso']:.2f} s"
        )

        filete()
        st.markdown("#### Decisiones de inversión")

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

        with st.expander("Ver registro de la ejecución"):
            st.code(res["log"], language=None)
            filete()
        st.markdown("#### Gráficas")

        if res["ruta_excel"] and os.path.exists(res["ruta_excel"]):
            for titulo, funcion in [
                ("Cobertura de la demanda por tecnología",
                 graficas.fig_cobertura),
                ("Operación del BESS", graficas.fig_bess),
                ("Flujo en las líneas más cargadas", graficas.fig_flujos),
            ]:
                st.markdown(f"**{titulo}**")
                fig = funcion(res["ruta_excel"])
                if fig is None:
                    st.info("Gráfica pendiente de implementar.")
                else:
                    st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning(
                "Las gráficas requieren el Excel de resultados. Activa "
                "**Exportar resultados a Excel** antes de ejecutar."
            )

# ------------------------------------------------------------------
with tab_modelo:
    st.markdown("#### Documentación del modelo")
    st.markdown(
        "Esta herramienta resuelve un modelo de planeación de expansión "
        "de la transmisión (TEP) formulado como programación lineal "
        "entera mixta (MILP) con flujo DC y pérdidas linealizadas. El modelo co-optimiza la inversión "
        "en sistemas de almacenamiento (BESS) de Li-Ion y compensación serie "
        "controlada por tiristores (TCSC) junto con la operación del "
        "sistema, permitiendo evaluar en qué medida estas tecnologías "
        "pueden diferir o evitar la construcción de nueva infraestructura "
        "de transmisión."
    )
    st.caption(
        "Resumen de la formulación implementada. El desarrollo completo "
        "está en el Capítulo 3 del documento de tesis."
    )

    with st.expander("Formulación matemática"):
        st.info("Pendiente: función objetivo y restricciones principales.")

    with st.expander("Almacenamiento (BESS)"):
        st.info("Pendiente: parámetros técnicos y económicos, leídos "
                "de la hoja BESS_Cand del caso.")

    with st.expander("Compensación serie (TCSC)"):
        st.info("Pendiente: niveles discretos de compensación y "
                "formulación Big-M.")

    with st.expander("Supuestos y limitaciones"):
        st.info("Pendiente: limitaciones metodológicas declaradas.")

    filete() 
    
    st.markdown(
        f"""
        <div style="font-size:0.8rem; color:{GRIS_OSC}; line-height:1.6;">
            <b>Autor:</b> Daniel Lindo<br>
            Trabajo final de Maestría en Ingeniería Eléctrica<br>
            Universidad Nacional de Colombia — Sede Bogotá, 2026<br>
            <span style="opacity:0.8;">
            Dimensionamiento y localización de FACTS y de sistemas de almacenamiento basados en baterías con el fin de
reducir los costos de operación y las inversiones de expansión en el sistema de potencia colombiano.
            </span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    filete()   

    st.markdown(
        f"<div style='font-size:0.95rem; font-weight:700; color:{GRIS_OSC}; "
        f"margin:0 0 -0.5rem 0;'>Grupo de investigación</div>",
        unsafe_allow_html=True,
    )

    _logo = BASE / "02_Model" / "05_GUI" / "logos" / "grupo.png"
    URL_GRUPO = "https://ingenieria.bogota.unal.edu.co/es/departamentos/departamento-ingenieria-electrica-electronica/#tab-investigacion"  

    if _logo.exists():
        # La imagen se incrusta en base64 porque el navegador no puede
        # leer rutas del disco del servidor. Es la unica forma de
        # envolverla en un enlace: st.image no acepta href.
        import base64
        b64 = base64.b64encode(_logo.read_bytes()).decode()
        st.markdown(
            f"""<a href="{URL_GRUPO}" target="_blank"
                  title="Grupo de investigación EMC — Universidad Nacional de Colombia">
                <img src="data:image/png;base64,{b64}" width="180"
                     style="margin-top:0.6rem;">
            </a>""",
            unsafe_allow_html=True,
        )
    else:
        st.caption(f"No se encontró el logo en `{_logo}`")
    
