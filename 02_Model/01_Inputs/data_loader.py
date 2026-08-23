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
import math

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
    d.n_seg_perdidas = int(cfg.get("n_seg_perdidas", 3))
    # Cota angular unica del modelo. La usan el bloque de perdidas y los
    # Big-M del TCSC. Definida en un solo lugar para que no puedan
    # desincronizarse.
    d.theta_max_total = float(cfg.get("theta_max_grados", 20.0)) * math.pi / 180.0
    d.tasa_descuento = float(cfg.get("tasa_descuento", 0.115))
    d.incluir_perdidas = int(cfg.get("incluir_perdidas", 1))   # <-- NUEVO
    d.mip_gap = cfg.get("mip_gap", 0.01)
    d.solver = str(cfg.get("solver", "highs")).lower()
    # Costo base por p.u. de reactancia (para costo de lineas
    # proporcional a reactancia, Alguacil). Configurable.
    # d.costo_base_reactancia = float(
    #     cfg.get("costo_base_reactancia", 5.0e7))
    d.n_seg_perdidas = int(cfg.get("n_seg_perdidas", 3))
    d.time_limit = cfg.get("time_limit", 1800)
    # Banda admitida para el cierre de volumen del embalse:
    # |V_T - V_init| <= tol_volumen_final * (Vmax - Vmin).
    d.tol_volumen_final = float(cfg.get("tol_volumen_final", 0.05))
    # Banda asimetrica opcional:
    #   Vinit - tol_inf*(Vmax-Vmin) <= V_T <= Vinit + tol_sup*(Vmax-Vmin).
    # El problema fisico es que el embalse no alcanza a recuperar volumen
    # con el aporte del horizonte, no que lo supere; por eso conviene
    # relajar el limite inferior mas que el superior. Si las claves no
    # estan en Config, ambas toman tol_volumen_final y la banda vuelve a
    # ser simetrica: los casos anteriores no cambian.
    d.tol_volumen_inf = float(cfg.get("tol_volumen_inf",
                                      d.tol_volumen_final))
    d.tol_volumen_sup = float(cfg.get("tol_volumen_sup",
                                      d.tol_volumen_final))
    # Penalizacion del vertimiento [USD por m3/s y hora]. Termino de
    # regularizacion, no un costo real.
    d.costo_vertimiento = float(cfg.get("costo_vertimiento", 0.01))

    # ================= Nodos (obligatoria) =======================
    nodos = _leer_hoja(wb, "Nodos", obligatoria=True)
    if not nodos:
        raise ValueError("La hoja 'Nodos' esta vacia.")
    d.nodos = []
    # demanda_base = {}
    d.nodo_slack = None
    for n in nodos:
        nid = str(n["id"])
        d.nodos.append(nid)
        # demanda_base[nid] = n.get("demanda_base", 0) or 0
        if str(n.get("tipo", "")).lower() == "slack":
            d.nodo_slack = nid
    if d.nodo_slack is None:
        d.nodo_slack = d.nodos[0]  # por defecto, el primero
        
    d.susceptancia = {}; 
    d.conductancia = {}; 
    d.flow_max = {}; 
    d.resistencia = {}

    # ================= Lineas (obligatoria) ======================
    lineas = _leer_hoja(wb, "Lineas", obligatoria=True)
    if not lineas:
        raise ValueError("La hoja 'Lineas' esta vacia.")
    d.lineas = []
    d.linea_from = {}; d.linea_to = {}
    for ln in lineas:
        lid = str(ln["id"])
        r = float(ln["R"]); x = float(ln["X"])
        d.lineas.append(lid)
        d.susceptancia[lid] = 1.0 / x          # susceptancia SERIE = 1/X
        d.conductancia[lid] = r / (r**2 + x**2)  # conductancia de linea
        d.resistencia[lid]  = r                  # R [p.u.] -> Luburic ec.(20)
        d.flow_max[lid] = float(ln["capacidad"])
        d.linea_from[lid] = str(ln["desde"])
        d.linea_to[lid] = str(ln["hasta"])

    # ============== Lineas_Cand (opcional) =======================
    cand = list(_leer_hoja(wb, "Lineas_Cand", obligatoria=False))
    d.lineas_cand = []
    d.costo_linea = {}
    
    for c in cand:
        lid = str(c["id"])
        r = float(c["R"]); x = float(c["X"])
        d.lineas_cand.append(lid)
        d.susceptancia[lid] = 1.0 / x          # susceptancia SERIE = 1/X
        d.conductancia[lid] = r / (r**2 + x**2)  # conductancia de linea
        d.resistencia[lid]  = r                  # R [p.u.] -> Luburic ec.(20)
        # 'c' es la candidata; usar 'ln' aqui heredaba la capacidad de la
        # ultima fila de 'Lineas' a TODAS las candidatas.
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
    d.pg_fijo = {}   # despacho fijo opcional (validacion vs MATPOWER)
    # se importa aqui para linealizar los costos cuadraticos
    import parameters as par
    for g in gens:
        gid = str(g["id"])
        d.gen_termica.append(gid)
        pmin = float(g["Pmin"]); pmax = float(g["Pmax"])
        d.pmin_term[gid] = pmin; d.pmax_term[gid] = pmax
        # rampa = float(g.get("rampa", pmax) or pmax)
        # d.ramp_up[gid] = rampa; d.ramp_down[gid] = rampa
        
        # Rampas de subida y bajada en MW/h. PARATEC las publica por
        # separado en MW/min (hoja VelCarga-Descarga) y pueden diferir.
        # Las columnas 'rampa_sub_min' y 'rampa_baj_min' del Excel son
        # documentales: NO se leen aqui. Se admite la columna unica
        # 'rampa' por compatibilidad con los casos del IEEE 14.
        r_up = g.get("rampa_sub")
        r_dn = g.get("rampa_baj")
        if r_up is None or r_dn is None:
            rampa = float(g.get("rampa", pmax) or pmax)
            r_up = rampa if r_up is None else r_up
            r_dn = rampa if r_dn is None else r_dn
        d.ramp_up[gid] = min(float(r_up), pmax)
        d.ramp_down[gid] = min(float(r_dn), pmax)        
        
        
        d.gen_en_nodo.setdefault(str(g["nodo"]), []).append(gid)
        d.l_up_min[gid] = int(g.get("min_on", 1) or 1)
        d.l_down_min[gid] = int(g.get("min_off", 1) or 1)
        d.cost_su[gid] = float(g.get("cost_su", 0) or 0)
        d.cost_sd[gid] = float(g.get("cost_sd", 0) or 0)
        if g.get("Pg_fijo") not in (None, ""):
            valor_fijo = float(g["Pg_fijo"])
            d.pg_fijo[gid] = valor_fijo
            # Modo validacion (despacho fijo): el estado inicial se
            # deduce del despacho impuesto.
            d.onoff_t0[gid] = 1 if valor_fijo > 0 else 0
        else:
            # Modo normal: leer el estado inicial u_init de la hoja
            # (ecuacion u_g,0 = u_g^init de la formulacion). Si la
            # columna no existe, por defecto apagado (0).
            u_ini = g.get("u_init")
            d.onoff_t0[gid] = int(u_ini) if u_ini not in (None, "") else 0
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
    # Tesis Cap.3, modelado detallado de generacion hidraulica:
    #   Pmin <= P_h,t <= Pmax                    (Soroudi 2017, p.83)
    #   Vmin <= V_h,t <= Vmax                    (Soroudi 2017, p.80)
    #   qmin <= q_h,t <= qmax                    (Soroudi 2017, p.80)
    #   P_h,t = eta_h * q_h,t                    (Wood & Wollenberg, p.18)
    #   V_h,t = V_h,t-1 + I_h,t - q_h,t - S_h,t  (Soroudi 2017, p.80)
    #   V_h,0 = V_h,T = Vinit                    (Soroudi 2017, p.80)
    #   q_h,t - q_h,t-1 <= Rq                    (Qiu et al. 2017, p.646)
    hidro = list(_leer_hoja(wb, "Hidraulicos", obligatoria=False))
    d.gen_hidro = []; d.hid_en_nodo = {}; d.costo_hidro = {}
    d.pmin_hid = {}; d.pmax_hid = {}
    d.qmin_hid = {}; d.qmax_hid = {}; d.eta_hid = {}
    d.vmin_hid = {}; d.vmax_hid = {}; d.vinit_hid = {}
    d.smax_hid = {}; d.rq_hid = {}
    for h in hidro:
        hid = str(h["id"])
        d.gen_hidro.append(hid)
        d.hid_en_nodo.setdefault(str(h["nodo"]), []).append(hid)
        d.costo_hidro[hid] = float(h.get("costo", 0) or 0)
        d.pmin_hid[hid] = float(h.get("Pmin", 0) or 0)
        d.pmax_hid[hid] = float(h.get("Pmax", 0) or 0)
        d.qmin_hid[hid] = float(h.get("qmin", 0) or 0)
        d.qmax_hid[hid] = float(h.get("qmax", 0) or 0)
        d.eta_hid[hid] = float(h.get("eta", 0) or 0)
        d.vmin_hid[hid] = float(h.get("Vmin", 0) or 0)
        d.vmax_hid[hid] = float(h.get("Vmax", 0) or 0)
        d.vinit_hid[hid] = float(h.get("Vinit", 0) or 0)
        d.smax_hid[hid] = float(h.get("Smax", 0) or 0)
        d.rq_hid[hid] = float(h.get("Rq", 0) or 0)

    # ------------- Aportes hidrologicos I_{h,t} -------------------
    # Hoja {hora x embalse} en m3/s, dato directo de AporCaudal. La
    # conversion a Mm3 la hace el modelo con k_q2v en el balance, igual
    # que para el turbinado y el vertimiento. Si el dato de origen es
    # diario, el reparto uniforme entre horas es un supuesto propio.
    ap = list(_leer_hoja(wb, "Aportes", obligatoria=False))
    d.aportes_hid = {}
    if ap:
        for fila in ap:
            hora_val = fila.get("hora")
            if hora_val in (None, ""):
                continue
            hora = int(hora_val)
            if hora > d.n_horas:
                continue
            for hid in d.gen_hidro:
                v = fila.get(hid)
                d.aportes_hid[(hid, hora)] = float(v) if v is not None else 0.0
    elif d.gen_hidro:
        print("  AVISO: hoja 'Aportes' ausente. I_h,t = 0: los embalses "
              "solo se vacian.")

    # ================= Renovables (opcional) =====================
    # Tesis Cap.3: la disponibilidad renovable es A_{r,t} * Pr^max, donde
    # A_{r,t} es el factor de disponibilidad horario (p.u.) y Pr^max la
    # capacidad instalada (MW). El producto se almacena ya en MW.
    renov = list(_leer_hoja(wb, "Renovables", obligatoria=False))
    d.gen_renov = []; d.ren_en_nodo = {}; d.cap_renov = {}
    for r in renov:
        rid = str(r["id"])
        d.gen_renov.append(rid)
        d.ren_en_nodo.setdefault(str(r["nodo"]), []).append(rid)
        d.cap_renov[rid] = float(r.get("capacidad", 0) or 0)

    # ------------- Renov_Perfil (factor de disponibilidad) --------
    # Hoja {hora x recurso} con fracciones 0-1. Si no existe, la
    # disponibilidad queda en cero y se emite advertencia: dejarla en 1.0
    # haria que las plantas solares generaran de noche.
    perf = list(_leer_hoja(wb, "Renov_Perfil", obligatoria=False))
    d.disponibilidad_renov = {}
    if perf:
        for fila in perf:
            hora_val = fila.get("hora")
            if hora_val in (None, ""):
                continue
            hora = int(hora_val)
            if hora > d.n_horas:
                continue
            for rid in d.gen_renov:
                frac = fila.get(rid)
                if frac is None:
                    continue
                d.disponibilidad_renov[(rid, hora)] = (
                    float(frac) * d.cap_renov[rid])
        faltan = [rid for rid in d.gen_renov
                  if (rid, 1) not in d.disponibilidad_renov]
        if faltan:
            print(f"  AVISO: sin perfil en Renov_Perfil -> {faltan}")
    elif d.gen_renov:
        print("  AVISO: hoja 'Renov_Perfil' ausente. La disponibilidad "
              "renovable queda en 0 y esos recursos no generaran.")

    # ================= BESS_Cand (opcional) ======================
    bess = list(_leer_hoja(wb, "BESS_Cand", obligatoria=False))
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
    # Formulacion por BLOQUES DISCRETOS de compensacion.
    #   Estructura : Luburic et al. (2020) ec.(3); Esmaili et al. (2020) ec.(17)
    #   Susceptancia: Luburic et al. (2020) ec.(21) con R=0 (modelo DC)
    #   Conductancia: Luburic et al. (2020) ec.(20), con R
    #   Costo      : de Oliveira et al. (1999) ecs.(A4)-(A5), Apendice B
    facts = list(_leer_hoja(wb, "FACTS_Cand", obligatoria=False))

    sig_txt = cfg.get("sigma_niveles", "0.15,0.30,0.45,0.60")
    d.sigma_niveles = [float(s) for s in str(sig_txt).split(",")]
    d.z_bloques = list(range(1, len(d.sigma_niveles) + 1))
    d.sigma = {z: s for z, s in zip(d.z_bloques, d.sigma_niveles)}
    # La funcion de costo (de Oliveira et al. 1999, ec. A4) esta formulada
    # para compensacion CAPACITIVA. Un sigma negativo produciria una
    # potencia reactiva negativa y, por tanto, un costo de inversion
    # negativo: el modelo cobraria por instalar el dispositivo.
    for z, sg in d.sigma.items():
        if not (0.0 < sg < 1.0):
            raise ValueError(
                f"sigma_niveles: el nivel {sg} esta fuera de (0,1). "
                f"Solo se admite compensacion capacitiva.")

    d.c_tcsc = float(cfg.get("c_tcsc", 135000.0))      # USD/MVAr (overnight)
    d.vida_facts = int(cfg.get("vida_facts", 20))      # anios

    def _crf(r, n):
        return (r * (1 + r) ** n) / ((1 + r) ** n - 1)

    crf_f = _crf(d.tasa_descuento, d.vida_facts)

    th = d.theta_max_total
    d.lineas_facts = []
    d.facts_dB = {}          # (f,z) -> susceptancia adicional   [p.u.]
    d.facts_dG = {}          # (f,z) -> conductancia adicional   [p.u.]
    d.facts_MB_on = {}       # (f,z) -> Big-M del flujo (cuando kappa=1) [p.u.]
    d.facts_MB_off = {}      # (f,z) -> Big-M del flujo (cuando kappa=0) [p.u.]
    d.facts_MG_on = {}       # (f,z) -> Big-M de perdidas (cuando kappa=1) [rad^2]
    d.facts_MG_off = {}      # (f,z) -> Big-M de perdidas (cuando kappa=0) [rad^2]
    d.facts_Q = {}           # (f,z) -> potencia reactiva        [MVAr]
    d.facts_capex = {}       # (f,z) -> inversion overnight      [USD]
    d.facts_anual = {}       # (f,z) -> costo anual equivalente  [USD/anio]

    for f in facts:
        lid = str(f["linea"])
        if f.get("habilitada") is not None and not int(f["habilitada"]):
            continue
        if lid not in d.lineas:
            raise ValueError(f"FACTS_Cand: la linea '{lid}' no existe en 'Lineas'.")
        d.lineas_facts.append(lid)

        B_l = d.susceptancia[lid]          # 1/X   [p.u.]
        x_l = 1.0 / B_l                    # X     [p.u.]
        r_l = d.resistencia[lid]           # R     [p.u.]
        S_l = d.flow_max[lid]              # Fmax  [MVA]
        G_l = d.conductancia[lid]          # R/(R^2+X^2) [p.u.]

        for z, sg in d.sigma.items():
            x_new = x_l * (1.0 - sg)

            # Susceptancia adicional  [ec. 3-4]
            dB = B_l * sg / (1.0 - sg)
            d.facts_dB[(lid, z)] = dB

            # Bound tightening (Wu et al. 2023, p.5, ec.23). Con el bloque
            # instalado, el limite de flujo acota el angulo, de donde
            # |psi| <= sigma*Fmax/Sbase. Dos cotas: _on vale solo si
            # kappa=1; _off vale siempre (relajacion cuando kappa=0).
            th_on = min(th, (S_l / d.mva_base) / (B_l + dB))
            d.facts_MB_on[(lid, z)] = abs(dB) * th_on
            d.facts_MB_off[(lid, z)] = abs(dB) * th

            # Conductancia adicional  [ec. 3-12; Luburic et al. 2020 ec.20]
            G_new = r_l / (r_l ** 2 + x_new ** 2) if r_l > 0 else 0.0
            d.facts_dG[(lid, z)] = G_new - G_l
            d.facts_MG_on[(lid, z)] = th_on ** 2
            d.facts_MG_off[(lid, z)] = th ** 2

            # Potencia reactiva y costo  [ecs. 3-17, 3-18]
            Q = sg * x_l * (S_l ** 2) / d.mva_base
            d.facts_Q[(lid, z)] = Q
            d.facts_capex[(lid, z)] = d.c_tcsc * Q
            d.facts_anual[(lid, z)] = crf_f * d.c_tcsc * Q

    # print(f"  [dbg] lineas_facts = {d.lineas_facts}")
    # print(f"  [dbg] z_bloques    = {d.z_bloques}   sigma = {d.sigma}")
    # print(f"  [dbg] capex: {len(d.facts_capex)} claves -> {sorted(d.facts_capex.keys())[:5]}")    
    # print(f"  [dbg] dB:{len(d.facts_dB)} MBon:{len(d.facts_MB_on)} "
    #       f"dG:{len(d.facts_dG)} Q:{len(d.facts_Q)} capex:{len(d.facts_capex)}")
    
    # ================= Demanda (obligatoria) =====================
    # Estructura {hora x nodo}. Si un nodo no aparece, su demanda es 0.
    dem_filas = _leer_hoja(wb, "Demanda", obligatoria=True)
    d.demanda = {}
    if dem_filas:
        for fila in dem_filas:
            hora_val = fila.get("hora")
            # Saltar filas vacias (Excel deja filas fantasma al final).
            if hora_val is None or hora_val == "":
                continue
            hora = int(hora_val)
            if hora > d.n_horas:
                continue
            for nodo in d.nodos:
                val = fila.get(nodo)
                d.demanda[(nodo, hora)] = float(val) if val else 0.0
    # else:
    #     # sin hoja de demanda: usar la demanda base constante
    #     for nodo in d.nodos:
    #         for t in range(1, d.n_horas + 1):
    #             d.demanda[(nodo, t)] = float(demanda_base.get(nodo, 0))
    else:
        # La hoja 'Demanda' es ahora obligatoria: se elimino el respaldo
        # 'demanda_base' de la hoja Nodos. Un caso sin demanda produciria
        # un despacho nulo y un costo cero, sin error visible.
        raise ValueError(
            "La hoja 'Demanda' esta vacia o ausente. Es obligatoria: "
            "el respaldo 'demanda_base' de la hoja 'Nodos' fue eliminado.")

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
    print(f"  FACTS cand : {len(datos.lineas_facts)} lineas x "
          f"{len(datos.z_bloques)} bloques")
    print(f"  Horizonte  : {datos.n_horas} h")
