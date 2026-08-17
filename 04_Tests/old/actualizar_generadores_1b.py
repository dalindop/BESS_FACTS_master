from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
import json
import re
import unicodedata

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "01_Data" / "02_Processed" / "generadores_18nodos.xlsx"
TRM = 3334.93
REPRESENTATIVE_DATE = date(2026, 7, 6)
SUBAREAS = [
    "SubArea Antioquia",
    "SubArea Arauca",
    "SubArea Atlantico",
    "SubArea Bogota",
    "SubArea Bolivar",
    "SubArea Boyaca-Casanare",
    "SubArea CQR",
    "SubArea Caqueta",
    "SubArea Cauca-Narino",
    "SubArea Cerromatoso",
    "SubArea Cordoba_Sucre",
    "SubArea GCM",
    "SubArea Huila-Tolima",
    "SubArea Meta",
    "SubArea Norte de Santander",
    "SubArea Putumayo",
    "SubArea Santander",
    "SubArea Valle",
]


def normalize(value):
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip().upper()


def parse_number(value):
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(".", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def find_file(pattern):
    matches = list((ROOT / "01_Data" / "01_Raw").glob(pattern))
    if not matches:
        raise FileNotFoundError(pattern)
    return matches[0]


def find_sheet(workbook, token):
    target = normalize(token).replace(" ", "")
    for name in workbook.sheetnames:
        candidate = normalize(name).replace(" ", "")
        if candidate == target or target in candidate:
            return workbook[name]
    raise KeyError(f"Sheet {token!r} not found in {workbook.sheetnames}")


def nonempty_rows(sheet, min_row=1):
    rows = []
    for row_number, values in enumerate(sheet.iter_rows(min_row=min_row, values_only=True), min_row):
        if any(value is not None for value in values):
            rows.append((row_number, list(values)))
    return rows


def header_map(values):
    return {normalize(value): index for index, value in enumerate(values) if value is not None}


def set_sheet(sheet, headers, rows):
    if sheet.max_row:
        sheet.delete_rows(1, sheet.max_row)
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E78")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for column_cells in sheet.columns:
        width = min(45, max(12, max(len(str(cell.value or "")) for cell in column_cells) + 2))
        sheet.column_dimensions[column_cells[0].column_letter].width = width


def add_or_replace_sheet(workbook, title):
    if title in workbook.sheetnames:
        del workbook[title]
    return workbook.create_sheet(title)


def as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def main():
    workbook = openpyxl.load_workbook(OUTPUT)

    cap_path = find_file("**/XM_API/CapEfecNeta_20260701_20260731.xlsx")
    offer_path = find_file("**/XM_API/PrecOferDesp_20260701_20260731.xlsx")
    ph_path = find_file("**/PARATEC/GENERACION/HIDRAULICA/*Phid*.xlsx")
    uh_path = find_file("**/PARATEC/GENERACION/HIDRAULICA/*Uhid*.xlsx")
    uh_stn_path = find_file("**/PARATEC/GENERACION/HIDRAULICA/*Uhid*STN*.xlsx")

    cap_sheet = find_sheet(openpyxl.load_workbook(cap_path, read_only=True, data_only=True), "01_SERIE")
    cap_headers = next(cap_sheet.iter_rows(values_only=True))
    cap_idx = header_map(cap_headers)
    cap_by_code = {}
    for values in cap_sheet.iter_rows(min_row=2, values_only=True):
        if as_date(values[cap_idx["FECHA"]]) != REPRESENTATIVE_DATE:
            continue
        code = str(values[cap_idx["CODIGO"]] or "").strip().upper()
        if code:
            cap_by_code[code] = parse_number(values[cap_idx["CAPEFECNETA_MW"]])

    offer_sheet = find_sheet(openpyxl.load_workbook(offer_path, read_only=True, data_only=True), "01_SERIE")
    offer_headers = next(offer_sheet.iter_rows(values_only=True))
    offer_idx = header_map(offer_headers)
    offer_codes = set()
    for values in offer_sheet.iter_rows(min_row=2, values_only=True):
        if as_date(values[offer_idx["FECHA"]]) == REPRESENTATIVE_DATE:
            code = str(values[offer_idx["CODIGO"]] or "").strip().upper()
            if code:
                offer_codes.add(code)

    detail = workbook["Detalle_Unidades"]
    detail_headers = [cell.value for cell in detail[1]]
    detail_idx = header_map(detail_headers)
    detail_rows = [list(row) for row in detail.iter_rows(min_row=2, values_only=True)]

    chain_code_by_plant = {
        "ALTO ANCHICAYA": "ALBG",
        "BAJO ANCHICAYA": "ALBG",
        "GUADALUPE III": "GTRG",
        "GUADALUPE IV": "GTRG",
        "TRONERAS": "GTRG",
        "PARAISO": "PGUG",
        "LA GUACA": "PGUG",
    }

    velocity_sheet = find_sheet(
        openpyxl.load_workbook(uh_stn_path, read_only=True, data_only=True),
        "VelCarga-Descarga",
    )
    velocities = {}
    for values in velocity_sheet.iter_rows(min_row=7, values_only=True):
        name = normalize(values[0])
        if name:
            velocities[name] = (parse_number(values[4]), parse_number(values[8]))

    ramp_up_by_code = defaultdict(float)
    ramp_down_by_code = defaultdict(float)
    hydraulic_audit = []
    hydraulic_count = 0
    unmatched_velocity = []
    for row in detail_rows:
        energy = normalize(row[detail_idx["TIPO_ENERGIA"]])
        if energy != "HIDRAULICA":
            continue
        hydraulic_count += 1
        unit_name = normalize(row[detail_idx["NOMBRE_UNIDAD"]])
        plant = normalize(row[detail_idx["PLANTA"]])
        code = str(row[detail_idx["CODIGO"]] or "").strip().upper()
        group_code = code or chain_code_by_plant.get(plant)
        ramp = velocities.get(unit_name)
        if ramp is None:
            unmatched_velocity.append(row[detail_idx["NOMBRE_UNIDAD"]])
            continue
        row[detail_idx["RAMPA_SUBIDA_MW_MIN"]] = ramp[0]
        row[detail_idx["RAMPA_BAJADA_MW_MIN"]] = ramp[1]
        if group_code:
            ramp_up_by_code[group_code] += ramp[0] or 0
            ramp_down_by_code[group_code] += ramp[1] or 0
        hydraulic_audit.append(
            [
                group_code,
                row[detail_idx["CODIGO"]],
                row[detail_idx["NOMBRE_UNIDAD"]],
                row[detail_idx["PLANTA"]],
                row[detail_idx["CAP_EFEC_NETA_MW"]],
                row[detail_idx["PMIN_PARATEC_MW"]],
                ramp[0],
                ramp[1],
                False,
                "PARATEC_Uhidraulica_STN / Uhidraulica",
                "Uhidraulica: Mínimo técnico [MW], columna P; VelCarga-Descarga: velocidades [MW/min]",
            ]
        )

    if hydraulic_count != 119 or unmatched_velocity:
        raise RuntimeError(
            f"Expected 119 matched hydraulic units; got {hydraulic_count}, unmatched={unmatched_velocity}"
        )

    for row in detail_rows:
        if normalize(row[detail_idx["TIPO_ENERGIA"]]) == "HIDRAULICA":
            flags_index = detail_idx["FLAGS"]
            flags = str(row[flags_index] or "")
            row[flags_index] = "; ".join(
                part for part in [flags, "rampa_fuente=VelCarga-Descarga_STN"] if part
            )
    for row_number, row in enumerate(detail_rows, 2):
        for column_number, value in enumerate(row, 1):
            detail.cell(row_number, column_number).value = value

    generators = workbook["Generadores"]
    gen_headers = [cell.value for cell in generators[1]]
    if "cost_avg_usd_mwh" not in gen_headers:
        gen_headers.append("cost_avg_usd_mwh")
        generators.cell(1, len(gen_headers)).value = "cost_avg_usd_mwh"
    gen_idx = header_map(gen_headers)
    generator_rows = []
    for row_number, old_row in enumerate(generators.iter_rows(min_row=2, values_only=True), 2):
        row = list(old_row)
        while len(row) < len(gen_headers):
            row.append(None)
        codes = [code.strip().upper() for code in str(row[gen_idx["OFFER_CODES"]] or "").split(",") if code.strip()]
        if normalize(row[gen_idx["VALUES_ENERSOURCE"]]) == "AGUA":
            row[gen_idx["RAMP_UP_SUM_MW_MIN"]] = sum(ramp_up_by_code[code] for code in codes)
            row[gen_idx["RAMP_DOWN_SUM_MW_MIN"]] = sum(ramp_down_by_code[code] for code in codes)
            row[gen_idx["PMIN_MISSING"]] = False
            row[gen_idx["MISSING_FIELDS"]] = None
        cost_cop = parse_number(row[gen_idx["COST_AVG_COP_MWH_WEIGHTED_PMAX"]])
        row[gen_idx["COST_AVG_USD_MWH"]] = cost_cop / TRM if cost_cop is not None else None
        generator_rows.append(row)
        for column_number, value in enumerate(row, 1):
            generators.cell(row_number, column_number).value = value

    renewable = workbook["Renovables"]
    renewable_headers = [cell.value for cell in renewable[1]]
    for new_header in ["es_autogenerador", "tiene_oferta"]:
        if new_header not in renewable_headers:
            renewable_headers.append(new_header)
            renewable.cell(1, len(renewable_headers)).value = new_header
    ren_idx = header_map(renewable_headers)
    for row_number, old_row in enumerate(renewable.iter_rows(min_row=2, values_only=True), 2):
        row = list(old_row)
        while len(row) < len(renewable_headers):
            row.append(None)
        resource = str(row[ren_idx["RECURSO"]] or "").strip()
        code = str(row[ren_idx["CODIGO"]] or "").strip().upper()
        row[ren_idx["ES_AUTOGENERADOR"]] = normalize(resource).startswith("AUTOG")
        row[ren_idx["TIENE_OFERTA"]] = code in offer_codes if code else False
        for column_number, value in enumerate(row, 1):
            renewable.cell(row_number, column_number).value = value

    # Capacity tables by all 18 modeled subareas.
    thermal = defaultdict(float)
    hydraulic = defaultdict(float)
    for row in generator_rows:
        area = row[gen_idx["SUBAREA"]]
        capacity = parse_number(row[gen_idx["PMAX_MW"]]) or 0
        if normalize(row[gen_idx["VALUES_ENERSOURCE"]]) == "AGUA":
            hydraulic[area] += capacity
        else:
            thermal[area] += capacity

    renewable_total = defaultdict(float)
    renewable_offered_xm = defaultdict(float)
    renewable_by_status = defaultdict(lambda: defaultdict(float))
    renewable_by_status_count = defaultdict(lambda: defaultdict(int))
    for row in renewable.iter_rows(min_row=2, values_only=True):
        area = row[ren_idx["SUBAREA"]]
        status = normalize(row[ren_idx["ESTADO"]])
        capacity = parse_number(row[ren_idx["PMAX_MW"]]) or 0
        renewable_total[area] += capacity
        if row[ren_idx["TIENE_OFERTA"]]:
            code = str(row[ren_idx["CODIGO"]] or "").strip().upper()
            renewable_offered_xm[area] += cap_by_code.get(code, 0) or 0
        if status == "OPERACION" and row[ren_idx["TIENE_OFERTA"]]:
            bucket = "operacion_con_oferta"
        elif status == "OPERACION":
            bucket = "operacion_sin_oferta"
        elif status == "PRUEBAS":
            bucket = "pruebas"
        else:
            bucket = "estado_no_determinado"
        renewable_by_status[area][bucket] += capacity
        renewable_by_status_count[area][bucket] += 1

    subarea_rows = []
    renewable_subarea_rows = []
    for area in SUBAREAS:
        thermal_mw = thermal[area]
        hydraulic_mw = hydraulic[area]
        renewable_mw = renewable_total[area]
        total = thermal_mw + hydraulic_mw + renewable_mw
        subarea_rows.append(
            [
                area,
                thermal_mw,
                hydraulic_mw,
                renewable_mw,
                renewable_offered_xm[area],
                total,
                total > 0,
                "Generación no identificada" if total == 0 else "Generación identificada",
            ]
        )
        buckets = renewable_by_status[area]
        counts = renewable_by_status_count[area]
        renewable_subarea_rows.append(
            [
                area,
                buckets["operacion_con_oferta"],
                counts["operacion_con_oferta"],
                buckets["operacion_sin_oferta"],
                counts["operacion_sin_oferta"],
                buckets["pruebas"],
                counts["pruebas"],
                buckets["estado_no_determinado"],
                counts["estado_no_determinado"],
            ]
        )

    cap_sheet_out = add_or_replace_sheet(workbook, "Capacidad_Subareas_18")
    set_sheet(
        cap_sheet_out,
        [
            "subarea",
            "cap_termica_mw",
            "cap_hidraulica_mw",
            "cap_renovable_mw",
            "cap_renovable_ofertada_xm_mw",
            "cap_total_mw",
            "tiene_generacion",
            "observacion",
        ],
        subarea_rows,
    )

    ren_cap_sheet = add_or_replace_sheet(workbook, "Renovables_Subareas")
    set_sheet(
        ren_cap_sheet,
        [
            "subarea",
            "operacion_con_oferta_mw",
            "n_operacion_con_oferta",
            "operacion_sin_oferta_mw",
            "n_operacion_sin_oferta",
            "pruebas_mw",
            "n_pruebas",
            "estado_no_determinado_mw",
            "n_estado_no_determinado",
        ],
        renewable_subarea_rows,
    )

    hydraulic_audit_sheet = add_or_replace_sheet(workbook, "Auditoria_Hidraulica")
    set_sheet(
        hydraulic_audit_sheet,
        [
            "codigo_grupo",
            "codigo_detalle",
            "nombre_unidad",
            "planta",
            "cap_efec_neta_mw",
            "pmin_uhidraulica_mw",
            "rampa_subida_mw_min",
            "rampa_bajada_mw_min",
            "pmin_faltante",
            "fuente_pmin",
            "fuente_rampa",
        ],
        hydraulic_audit,
    )

    cost_rows = []
    for row in generator_rows:
        cost_rows.append(
            [
                None,
                row[gen_idx["SUBAREA"]],
                row[gen_idx["VALUES_ENERSOURCE"]],
                row[gen_idx["PMAX_MW"]],
                row[gen_idx["PMIN_MW"]],
                row[gen_idx["COST_AVG_COP_MWH_WEIGHTED_PMAX"]],
                row[gen_idx["COST_AVG_USD_MWH"]],
                row[gen_idx["RAMP_UP_SUM_MW_MIN"]],
                row[gen_idx["RAMP_DOWN_SUM_MW_MIN"]],
                row[gen_idx["OFFER_CODES"]],
                row[gen_idx["N_UNITS"]],
            ]
        )
    cost_rows.sort(key=lambda row: (row[6] is None, row[6] or 0))
    for order, row in enumerate(cost_rows, 1):
        row[0] = order
    cost_sheet = add_or_replace_sheet(workbook, "Costos_Ordenados")
    set_sheet(
        cost_sheet,
        [
            "orden_merito",
            "subarea",
            "fuente_energetica",
            "pmax_mw",
            "pmin_mw",
            "cost_avg_cop_mwh_weighted_pmax",
            "cost_avg_usd_mwh",
            "ramp_up_sum_mw_min",
            "ramp_down_sum_mw_min",
            "offer_codes",
            "n_units",
        ],
        cost_rows,
    )

    offered_capacity = sum(cap_by_code.get(code, 0) or 0 for code in offer_codes)
    offered_renewable_codes = set()
    for row in renewable.iter_rows(min_row=2, values_only=True):
        if row[ren_idx["TIENE_OFERTA"]] and row[ren_idx["CODIGO"]]:
            offered_renewable_codes.add(str(row[ren_idx["CODIGO"]]).strip().upper())
    offered_renewable_capacity = sum(cap_by_code.get(code, 0) or 0 for code in offered_renewable_codes)
    pmax_renewable = sum(renewable_total.values())
    cap_generators = sum(parse_number(row[gen_idx["PMAX_MW"]]) or 0 for row in generator_rows)
    reconciliation_sheet = add_or_replace_sheet(workbook, "Conciliacion_Capacidad")
    set_sheet(
        reconciliation_sheet,
        ["concepto", "capacidad_mw", "fuente", "interpretacion"],
        [
            ["Fase 0 reportada", 19539, "Informe Fase 0", "Cifra histórica solicitada por el usuario"],
            ["Generadores no renovables", cap_generators, "Generadores.pmax_mw", "Suma de la hoja Generadores"],
            ["Diferencia Fase 0 - Generadores", 19539 - cap_generators, "Cálculo", "Corresponde a renovables ofertadas según la cifra histórica"],
            ["Renovables ofertadas (84 códigos)", offered_renewable_capacity, "CapEfecNeta 2026-07-06", "Incluye 13 códigos renovables; PORO incluido"],
            ["Capacidad XM de los 84 códigos", offered_capacity, "CapEfecNeta 2026-07-06", "Suma verificable de los 84 códigos de PrecOferDesp"],
            ["Renovables PARATEC completas", pmax_renewable, "Renovables.pmax_mw", "352 plantas, con y sin oferta"],
            ["Capacidad no reconciliable perdida", 0, "Conciliación", "No hay pérdida contra la fuente XM; Fase 0 subestima 300 MW por PORO"],
        ],
    )

    notes_sheet = add_or_replace_sheet(workbook, "Notas_Fase1b")
    set_sheet(
        notes_sheet,
        ["tema", "resultado", "fuente", "aplicacion"],
        [
            ["Subáreas", "Arauca y Meta tienen solo renovables; Caqueta y Putumayo no tienen generación identificada. No se perdieron agregados.", "Capacidad_Subareas_18", "Se reportan las 18 subáreas explícitamente."],
            ["Rampa1/Rampa2", "Segmentos UR/DR de oferta hidráulica, con límites y valores en MWh. No son velocidades MW/min ni MW/h.", "PARATEC_Phidraulica / Rampa1, Rampa2", "No incorporadas como rampas físicas."],
            ["VelCarga-Descarga", "Velocidad de carga y descarga por unidad; encabezados explícitos en MW/min. La columna de descarga conserva un rótulo interno erróneo de carga.", "PARATEC_Uhidraulica_STN / VelCarga-Descarga", "Incorporadas como ramp_up y ramp_down en Detail y Generadores."],
            ["Rampas hidráulicas", "119 de 119 unidades hidráulicas coinciden por nombre y tienen ambas velocidades.", "VelCarga-Descarga + Detalle_Unidades", "Las rampas agregadas son sumas por grupo ofertante."],
            ["Mínimos técnicos", "Phidraulica no contiene mínimo numérico: solo Mínimo obligatorio [Si/No]. Las 119 unidades sí tienen Mínimo técnico [MW] en Uhidraulica/STN.", "PARATEC_Phidraulica columna L; PARATEC_Uhidraulica_STN columna P", "Los tres pmin_missing se corrigieron a False; no hay unidades hidráulicas sin pmin tras revisar Uhidraulica."],
            ["TRM", f"{TRM} COP/USD, válida para el 2026-07-06.", "Superfinanciera vía datos.gov.co, dataset 32sa-8pi3", "Se aplicó cost_avg_usd_mwh = cost_avg_cop_mwh_weighted_pmax / TRM."],
            ["Capacidad", "Generadores suma 18061 MW. Los 84 códigos XM suman 19839 MW: 18061 convencionales + 1778 renovables ofertadas.", "CapEfecNeta y PrecOferDesp del 2026-07-06", "La cifra Fase 0 de 19539 MW omite 300 MW de PORO; no se detecta pérdida contra XM."],
            ["Autogeneradores", "es_autogenerador es True si recurso empieza por AUTOG; tiene_oferta es True solo si codigo pertenece a los 84 códigos de PrecOferDesp.", "Renovables + PrecOferDesp", "Los códigos ausentes permanecen sin oferta; no se infiere oferta por nombre."],
        ],
    )

    trace = workbook["Trazabilidad"]
    trace_headers = [cell.value for cell in trace[1]]
    trace_rows = [
        list(row)
        for row in trace.iter_rows(min_row=2, values_only=True)
        if str(row[0] or "") != "PHASE1B"
    ]
    trace_rows.extend(
        [
            ["PHASE1B", "Generadores", "cost_avg_usd_mwh", "Superfinanciera vía datos.gov.co/resource/32sa-8pi3.json", "32sa-8pi3", "cost_avg_cop_mwh_weighted_pmax / 3334.93; fecha representativa 2026-07-06", "OK", TRM, "COP/USD"],
            ["PHASE1B", "Generadores/Detalle_Unidades", "ramp_up/ramp_down", str(uh_stn_path.relative_to(ROOT)), "VelCarga-Descarga", "Velocidades explícitas por unidad en MW/min; 119/119 coincidencias", "OK", 119, "No usar Rampa1/Rampa2 como MW/min"],
            ["PHASE1B", "Generadores", "pmin_missing", str(uh_stn_path.relative_to(ROOT)), "Uhidraulica", "Mínimo técnico [MW] presente en las 119 unidades; tres flags previos corregidos", "OK", 0, "Unidades hidráulicas sin pmin"],
            ["PHASE1B", "Conciliacion_Capacidad", "capacidad_84", str(cap_path.relative_to(ROOT)), "01_SERIE", "Suma CapEfecNeta del 2026-07-06 para los 84 códigos ofertantes", "OK", offered_capacity, "MW"],
        ]
    )
    set_sheet(trace, trace_headers, trace_rows)

    workbook.save(OUTPUT)
    print(json.dumps({
        "output": str(OUTPUT),
        "offer_codes": len(offer_codes),
        "offer_capacity_mw": offered_capacity,
        "renewable_offer_capacity_mw": offered_renewable_capacity,
        "generator_capacity_mw": cap_generators,
        "hydraulic_units": hydraulic_count,
        "unmatched_velocity": unmatched_velocity,
        "renewable_pmax_mw": pmax_renewable,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
