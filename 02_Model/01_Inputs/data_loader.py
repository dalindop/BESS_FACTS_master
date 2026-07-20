# -*- coding: utf-8 -*-
"""
==================================================================
 DATA LOADER
------------------------------------------------------------------
Autor : Daniel Lindo -- Universidad Nacional de Colombia (UNAL)
Tesis : Maestria en Ingenieria Electrica, 2026
------------------------------------------------------------------

Lee un caso desde la plantilla Excel estandarizada (una hoja por tipo
de dato) y produce un objeto `data` con todos los atributos que los
modulos del modelo (sets, parameters, ...) esperan.

Filosofia de validacion:
  - ESTRICTO para lo esencial (Nodos, Lineas, Generadores): si falta
    una hoja o un dato clave, se lanza un error claro.
  - TOLERANTE para lo opcional (Lineas_Cand, BESS_Cand, FACTS_Cand,
    Hidraulicos, Renovables): si la hoja esta vacia, ese componente
    simplemente no existe (conjunto vacio en el modelo).

Un caso = un archivo Excel. La misma funcion lee el W&W, IEEE o Colombia.
==================================================================
"""
# Librería que permite leer y modificar archivos Excel
import openpyxl

class DatosModelo:
    """
    Contenedor simple de los datos del modelo (objeto `data`).
    """
    pass


def _leer_hoja(wb, nombre, obligatoria=False):
    """
    Devuelve las filas de datos de una hoja como lista de dicts
    {encabezado: valor}. La plantilla tiene: fila 1 titulo, fila 3
    encabezados, fila 4 unidades, fila 5+ datos. (En hojas creadas por
    el conversor, encabezados en fila 3 y datos en fila 5+.)

    Si la hoja no existe: error si es obligatoria, [] si es opcional.
    """
    if nombre not in wb.sheetnames:
        if obligatoria:
            raise ValueError(
                f"Falta la hoja obligatoria '{nombre}' en el Excel.")
        return []
    ws = wb[nombre]
    filas = list(ws.iter_rows(values_only=True))
    # localizar la fila de encabezados: primera fila con >1 celda no
    # vacia que no sea el titulo (el titulo esta solo en A). Buscamos la
    # fila cuyos valores sirven de nombres de columna.    
    # guardar el índice (número de fila) donde están los encabezados.
    hdr_idx = None
    for i, fila in enumerate(filas):
        no_vacias = [c for c in fila if c is not None]
        if len(no_vacias) >= 2:
            hdr_idx = i
            break
    if hdr_idx is None:
        return []
    encabezados = [c for c in filas[hdr_idx]]
    # los datos empiezan tras encabezados + fila de unidades
    datos = []
    for fila in filas[hdr_idx + 2:]:
        if all(c is None for c in fila):
            continue
        registro = {}
        for col, val in zip(encabezados, fila):
            if col is not None:
                registro[col] = val
        # omitir filas totalmente vacias de contenido util
        if any(v is not None for v in registro.values()):
            datos.append(registro)
    return datos


def _config_dict(wb):
    """Lee la hoja Config como dict {parametro: valor}."""
    filas = _leer_hoja(wb, "Config", obligatoria=True)
    cfg = {}
    for f in filas:
        # la hoja Config tiene columnas parametro/valor/descripcion
        clave = f.get("parametro")
        valor = f.get("valor")
        if clave is not None:
            cfg[clave] = valor
    return cfg


def cargar_datos(ruta_excel):
    """
    Carga un caso desde la plantilla Excel y devuelve el objeto `data`.

    ruta_excel: ruta al archivo .xlsx del caso.
    """
    wb = openpyxl.load_workbook(ruta_excel, data_only=True)
    d = DatosModelo()

    # ================= Config (obligatoria) ======================
    cfg = _config_dict(wb)
    d.mva_base = cfg.get("S_base", 100)
    d.n_horas = int(cfg.get("horizonte", 24))
    d.n_seg_costo = int(cfg.get("n_seg_costo", 3))
    # Costo base por p.u. de reactancia (para costo de lineas
    # proporcional a reactancia, Alguacil). Configurable.
    d.costo_base_reactancia = float(
        cfg.get("costo_base_reactancia", 5.0e7))
    d.n_seg_perdidas = int(cfg.get("n_seg_perdidas", 3))
    d.mip_gap = cfg.get("mip_gap", 0.01)
    d.time_limit = cfg.get("time_limit", 1800)

    # ================= Nodos (obligatoria) =======================
    nodos = _leer_hoja(wb, "Nodos", obligatoria=True)
    if not nodos:
        raise ValueError("La hoja 'Nodos' esta vacia.")
    d.nodos = []
    demanda_base = {}
    d.nodo_slack = None
    for n in nodos:
        nid = str(n["id"])
        d.nodos.append(nid)
        demanda_base[nid] = n.get("demanda_base", 0) or 0
        if str(n.get("tipo", "")).lower() == "slack":
            d.nodo_slack = nid
    if d.nodo_slack is None:
        d.nodo_slack = d.nodos[0]  # por defecto, el primero

    # ================= Lineas (obligatoria) ======================
    lineas = _leer_hoja(wb, "Lineas", obligatoria=True)
    if not lineas:
        raise ValueError("La hoja 'Lineas' esta vacia.")
    d.lineas = []
    d.susceptancia = {}; d.conductancia = {}; d.flow_max = {}
    d.linea_from = {}; d.linea_to = {}
    for ln in lineas:
        lid = str(ln["id"])
        r = float(ln["R"]); x = float(ln["X"])
        d.lineas.append(lid)
        d.susceptancia[lid] = 1.0 / x          # susceptancia SERIE = 1/X
        d.conductancia[lid] = r / (r**2 + x**2)  # conductancia de linea
        d.flow_max[lid] = float(ln["capacidad"])
        d.linea_from[lid] = str(ln["desde"])
        d.linea_to[lid] = str(ln["hasta"])

    # ============== Lineas_Cand (opcional) =======================
    cand = _leer_hoja(wb, "Lineas_Cand", obligatoria=False)
    d.lineas_cand = []
    d.costo_linea = {}
    for c in cand:
        lid = str(c["id"])
        r = float(c["R"]); x = float(c["X"])
        d.lineas_cand.append(lid)
        d.susceptancia[lid] = 1.0 / x
        d.conductancia[lid] = r / (r**2 + x**2)
        d.flow_max[lid] = float(c["capacidad"])
        d.linea_from[lid] = str(c["desde"])
        d.linea_to[lid] = str(c["hasta"])
        # Costo de la linea candidata. Dos modos:
        #  1) Si el Excel trae un costo explicito, se usa ese.
        #  2) Si no (vacio o 0), se calcula proporcional a la
        #     reactancia (Alguacil et al. 2003): lineas con mas
        #     reactancia (mas largas) cuestan mas. Evita necesitar
        #     distancias geograficas en sistemas de prueba.
        costo_expl = c.get("costo")
        if costo_expl is not None and float(costo_expl) > 0:
            d.costo_linea[lid] = float(costo_expl)
        else:
            # costo_base_reactancia: USD por p.u. de reactancia.
            # se lee de Config; por defecto un valor representativo.
            cb = getattr(d, "costo_base_reactancia", 5.0e7)
            d.costo_linea[lid] = cb * x

    # ================= Generadores (obligatoria) =================
    gens = _leer_hoja(wb, "Generadores", obligatoria=True)
    if not gens:
        raise ValueError("La hoja 'Generadores' esta vacia.")
    d.gen_termica = []; d.pmin_term = {}; d.pmax_term = {}
    d.ramp_up = {}; d.ramp_down = {}; d.gen_en_nodo = {}
    d.onoff_t0 = {}; d.l_up_min = {}; d.l_down_min = {}
    d.cost_su = {}; d.cost_sd = {}
    d.slope_term = {}; d.fg_min_term = {}
    # se importa aqui para linealizar los costos cuadraticos
    import parameters as par
    for g in gens:
        gid = str(g["id"])
        d.gen_termica.append(gid)
        pmin = float(g["Pmin"]); pmax = float(g["Pmax"])
        d.pmin_term[gid] = pmin; d.pmax_term[gid] = pmax
        rampa = float(g.get("rampa", pmax) or pmax)
        d.ramp_up[gid] = rampa; d.ramp_down[gid] = rampa
        d.gen_en_nodo.setdefault(str(g["nodo"]), []).append(gid)
        d.l_up_min[gid] = int(g.get("min_on", 1) or 1)
        d.l_down_min[gid] = int(g.get("min_off", 1) or 1)
        d.onoff_t0[gid] = 0
        d.cost_su[gid] = float(g.get("cost_su", 0) or 0)
        d.cost_sd[gid] = float(g.get("cost_sd", 0) or 0)
        # linealizar el costo cuadratico c2*P^2+c1*P+c0
        c2 = float(g.get("c2", 0) or 0)
        c1 = float(g.get("c1", 0) or 0)
        c0 = float(g.get("c0", 0) or 0)
        fg, sl = par.linealizar_costo(c2, c1, c0, pmin, pmax,
                                      d.n_seg_costo)
        d.fg_min_term[gid] = fg
        for mm, v in enumerate(sl, 1):
            d.slope_term[(gid, mm)] = v

    # ================= Hidraulicos (opcional) ====================
    hidro = _leer_hoja(wb, "Hidraulicos", obligatoria=False)
    d.gen_hidro = []; d.hid_en_nodo = {}; d.costo_hidro = {}
    for h in hidro:
        hid = str(h["id"])
        d.gen_hidro.append(hid)
        d.hid_en_nodo.setdefault(str(h["nodo"]), []).append(hid)
        d.costo_hidro[hid] = float(h.get("costo", 0) or 0)

    # ================= Renovables (opcional) =====================
    renov = _leer_hoja(wb, "Renovables", obligatoria=False)
    d.gen_renov = []; d.ren_en_nodo = {}
    for r in renov:
        rid = str(r["id"])
        d.gen_renov.append(rid)
        d.ren_en_nodo.setdefault(str(r["nodo"]), []).append(rid)
    d.disponibilidad_renov = {}  # se completa con perfil si aplica

    # ================= BESS_Cand (opcional) ======================
    bess = _leer_hoja(wb, "BESS_Cand", obligatoria=False)
    d.nodos_bess = []; d.bess_en_nodo = {}
    for b in bess:
        nodo = str(b["nodo"])
        d.nodos_bess.append(nodo)
        d.bess_en_nodo.setdefault(nodo, []).append(nodo)
        # parametros tecnicos (si vienen; si no, defaults del modelo)
        if b.get("eff_ch") is not None:
            d.bess_eff_ch = float(b["eff_ch"])
        if b.get("eff_dis") is not None:
            d.bess_eff_dis = float(b["eff_dis"])
        if b.get("self_dis") is not None:
            d.bess_self_dis = float(b["self_dis"])
        if b.get("soc_ini") is not None:
            d.bess_soc_ini = float(b["soc_ini"])
        if b.get("duracion") is not None:
            d.bess_duracion = float(b["duracion"])
        if b.get("costo_inst") is not None:
            d.costo_bess_inst = float(b["costo_inst"])
        if b.get("costo_pot") is not None:
            d.costo_bess_power = float(b["costo_pot"])
        if b.get("costo_ene") is not None:
            d.costo_bess_energy = float(b["costo_ene"])

    # ================= FACTS_Cand (opcional) =====================
    facts = _leer_hoja(wb, "FACTS_Cand", obligatoria=False)
    d.lineas_facts = []; d.facts_dB_min = {}; d.facts_dB_max = {}
    for f in facts:
        lid = str(f["linea"])
        d.lineas_facts.append(lid)
        d.facts_dB_min[lid] = float(f.get("dB_min", -0.5) or -0.5)
        d.facts_dB_max[lid] = float(f.get("dB_max", 0.5) or 0.5)
        if f.get("costo_inst") is not None:
            d.costo_facts_inst = float(f["costo_inst"])

    # ================= Demanda (obligatoria) =====================
    # Estructura {hora x nodo}. Si un nodo no aparece, su demanda es 0.
    dem_filas = _leer_hoja(wb, "Demanda", obligatoria=True)
    d.demanda = {}
    if dem_filas:
        for fila in dem_filas:
            hora = int(fila.get("hora"))
            if hora > d.n_horas:
                continue
            for nodo in d.nodos:
                val = fila.get(nodo)
                d.demanda[(nodo, hora)] = float(val) if val else 0.0
    else:
        # sin hoja de demanda: usar la demanda base constante
        for nodo in d.nodos:
            for t in range(1, d.n_horas + 1):
                d.demanda[(nodo, t)] = float(demanda_base.get(nodo, 0))

    return d


if __name__ == "__main__":
    import sys
    ruta = sys.argv[1] if len(sys.argv) > 1 else "caso_WW.xlsx"
    datos = cargar_datos(ruta)
    print(f"Caso cargado: {ruta}")
    print(f"  Nodos      : {len(datos.nodos)} (slack: {datos.nodo_slack})")
    print(f"  Lineas     : {len(datos.lineas)}")
    print(f"  Candidatas : {len(datos.lineas_cand)}")
    print(f"  Termicos   : {len(datos.gen_termica)}")
    print(f"  Hidro      : {len(datos.gen_hidro)}")
    print(f"  Renovables : {len(datos.gen_renov)}")
    print(f"  BESS cand  : {len(datos.nodos_bess)}")
    print(f"  FACTS cand : {len(datos.lineas_facts)}")
    print(f"  Horizonte  : {datos.n_horas} h")
