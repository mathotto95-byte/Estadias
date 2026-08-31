from __future__ import annotations

import re
import zipfile
from io import BytesIO
from pathlib import Path

import pandas as pd
import streamlit as st

from src.dashboards.components import metric_grid, render_dataframe
from src.modules.estadias.imports import extrair_placa_do_nome_arquivo, import_control, import_lcte_ipiranga, import_rastreador_files
from src.modules.estadias.repository import (
    CONTROL_NORMALIZED_TABLE,
    CROSS_TABLE,
    LCTE_NORMALIZED_TABLE,
    RASTREADOR_NORMALIZED_TABLE,
    clear_estadias_imported_database,
    arquivos_rastreador_importados,
    clear_lcte_base,
    latest_logs,
    placas_disponiveis,
    read_auditoria,
    read_config,
    read_control,
    read_cross,
    read_lcte,
    read_locais,
    read_parametros,
    read_preferencia_colunas,
    read_rastreador,
    read_rastreador_period,
    reabrir_conclusao,
    sample,
    save_conclusao,
    save_config,
    save_locais,
    save_parametros,
    save_preferencia_colunas,
    select_distinct,
    table_count,
)
from src.modules.estadias.service import atualizar_cruzamento, atualizar_cruzamento_incremental, dashboard_metrics, top_indicators, validation_metrics
from src.modules.estadias.teste_lcte_rastreador import (
    CARD_DEFINITIONS,
    DEFAULT_TEST_PLATE,
    DEFAULT_VISIBLE_COLUMNS,
    active_card_labels,
    aplicar_filtros_painel_estadias,
    available_months,
    available_years,
    build_teste_lcte_rastreador,
    card_counts,
    ensure_panel_filter_columns,
    export_sheets as export_teste_lcte_rastreador_sheets,
    latest_month_with_data,
    month_label,
)
from src.reports.exporter import dataframe_to_excel
from src.utils.timezone import brasilia_now_iso


RODO_WALL_PDF_BACKGROUND_PATH = Path(__file__).resolve().parents[3] / "assets" / "rodo_wall_pdf_background.png"


def _duplicate_mode(role: str, key: str) -> str:
    if str(role or "").upper() != "ADMIN":
        return "bloquear"
    label = st.radio(
        "Arquivo duplicado",
        ["Cancelar importacao", "Reimportar substituindo lote anterior", "Importar mesmo assim como novo lote"],
        horizontal=True,
        key=key,
    )
    return {
        "Cancelar importacao": "bloquear",
        "Reimportar substituindo lote anterior": "substituir",
        "Importar mesmo assim como novo lote": "novo_lote",
    }[label]


def _import_metric_payload(result: dict[str, object]) -> dict[str, object]:
    return {
        "Linhas importadas": result.get("linhas", 0),
        "Placas validas": result.get("placas_validas", 0),
        "Datas validas": result.get("datas_validas", 0),
        "Registros com erro": result.get("registros_com_erro", 0),
        "Periodo inicial": result.get("periodo_inicial") or "-",
        "Periodo final": result.get("periodo_final") or "-",
        "Status": result.get("status") or "-",
    }


def _filter_results(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    st.subheader("Filtros")
    col_a, col_b, col_c, col_d = st.columns(4)
    plate = col_a.text_input("Placa", key="estadias_result_placa")
    status = col_b.selectbox("Status", ["", *sorted(df.get("status_cruzamento", pd.Series(dtype=str)).fillna("").astype(str).unique().tolist())], key="estadias_result_status")
    cliente = col_c.text_input("Cliente", key="estadias_result_cliente")
    motorista = col_d.text_input("Motorista", key="estadias_result_motorista")
    col_e, col_f, col_g, col_h = st.columns(4)
    origem = col_e.text_input("Origem", key="estadias_result_origem")
    destino = col_f.text_input("Destino", key="estadias_result_destino")
    special = col_g.selectbox(
        "Situacao",
        ["", "Com estadia", "Sem estadia", "Elegivel", "Nao elegivel", "Erro", "Vinculo confirmado", "Vinculo provavel", "Aguardando revisao", "Viagem em andamento", "Sem CONTROL", "Sem rastreador", "Sem coordenadas"],
        key="estadias_result_special",
    )
    periodo = col_h.text_input("Periodo contem", key="estadias_result_periodo")
    filtered = df.copy()
    for column, value in {
        "placa_norm": plate,
        "status_cruzamento": status,
        "cliente": cliente,
        "motorista": motorista,
        "origem": origem,
        "destino": destino,
        "data_operacao": periodo,
    }.items():
        if value and column in filtered:
            filtered = filtered[filtered[column].fillna("").astype(str).str.contains(str(value), case=False, na=False)]
    if special == "Com estadia":
        filtered = filtered[pd.to_numeric(filtered.get("horas_estadia", pd.Series(dtype=float)), errors="coerce").fillna(0).gt(0)]
    elif special == "Sem estadia":
        filtered = filtered[pd.to_numeric(filtered.get("horas_estadia", pd.Series(dtype=float)), errors="coerce").fillna(0).le(0)]
    elif special == "Elegivel":
        filtered = filtered[filtered.get("elegivel_cobranca", pd.Series(dtype=int)).fillna(0).astype(int).eq(1)]
    elif special == "Nao elegivel":
        filtered = filtered[
            filtered.get("calculou_estadia", pd.Series(dtype=int)).fillna(0).astype(int).eq(1)
            & filtered.get("elegivel_cobranca", pd.Series(dtype=int)).fillna(0).astype(int).ne(1)
        ]
    elif special == "Erro":
        filtered = filtered[filtered.get("status_cruzamento", pd.Series(dtype=str)).fillna("").astype(str).eq("ERRO")]
    elif special == "Vinculo confirmado":
        filtered = filtered[filtered.get("classificacao_control", pd.Series(dtype=str)).fillna("").astype(str).eq("CONFIRMADO")]
    elif special == "Vinculo provavel":
        filtered = filtered[filtered.get("classificacao_control", pd.Series(dtype=str)).fillna("").astype(str).eq("PROVAVEL")]
    elif special == "Aguardando revisao":
        filtered = filtered[filtered.get("classificacao_control", pd.Series(dtype=str)).fillna("").astype(str).eq("REVISAO_MANUAL")]
    elif special == "Viagem em andamento":
        filtered = filtered[filtered.get("motivo_falha", pd.Series(dtype=str)).fillna("").astype(str).str.contains("CONTROL_VIAGEM_EM_ANDAMENTO", na=False)]
    elif special == "Sem CONTROL":
        filtered = filtered[filtered.get("encontrou_control", pd.Series(dtype=int)).fillna(0).astype(int).ne(1)]
    elif special == "Sem rastreador":
        filtered = filtered[filtered.get("encontrou_rastreador", pd.Series(dtype=int)).fillna(0).astype(int).ne(1)]
    elif special == "Sem coordenadas":
        filtered = filtered[filtered.get("codigo_motivo", pd.Series(dtype=str)).fillna("").astype(str).str.contains("SEM_COORDENADAS", na=False)]
    return filtered


def _format_minutes_value(value: object) -> str:
    minutes = pd.to_numeric(pd.Series([value]), errors="coerce").fillna(0).iloc[0]
    total = int(round(float(minutes)))
    hours, mins = divmod(total, 60)
    return f"{hours}h {mins:02d}min"


def _permanence_rows(df: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "ID viagem",
        "CT-e",
        "NF",
        "Placa",
        "Cliente",
        "Motorista",
        "Tipo ponto",
        "Local",
        "UF",
        "Encontrou ponto",
        "Chegada",
        "Saida",
        "Tempo no ponto (min)",
        "Tempo no ponto",
        "Franquia (min)",
        "Estadia apos franquia (min)",
        "Estadia apos franquia",
        "Pontos rastreador",
    ]
    if df.empty:
        return pd.DataFrame(columns=columns)
    rows: list[dict[str, object]] = []
    for _, row in df.iterrows():
        common = {
            "ID viagem": row.get("id"),
            "CT-e": row.get("cte"),
            "NF": row.get("nf"),
            "Placa": row.get("placa_norm"),
            "Cliente": row.get("cliente"),
            "Motorista": row.get("motorista"),
        }
        for tipo, local_col, uf_col, found_col, arrival_col, departure_col, time_col, allowance_col, stay_col, points_col in [
            ("ORIGEM", "origem", "uf_origem", "encontrou_origem", "chegada_origem", "saida_origem", "tempo_origem_min", "franquia_carga_min", "estadia_carga_min", "pontos_origem"),
            ("DESTINO", "destino", "uf_destino", "encontrou_destino", "chegada_destino", "saida_destino", "tempo_destino_min", "franquia_descarga_min", "estadia_descarga_min", "pontos_destino"),
        ]:
            time_min = row.get(time_col)
            stay_min = row.get(stay_col)
            rows.append(
                {
                    **common,
                    "Tipo ponto": tipo,
                    "Local": row.get(local_col),
                    "UF": row.get(uf_col),
                    "Encontrou ponto": "SIM" if int(row.get(found_col) or 0) else "NAO",
                    "Chegada": row.get(arrival_col),
                    "Saida": row.get(departure_col),
                    "Tempo no ponto (min)": time_min,
                    "Tempo no ponto": _format_minutes_value(time_min),
                    "Franquia (min)": row.get(allowance_col),
                    "Estadia apos franquia (min)": stay_min,
                    "Estadia apos franquia": _format_minutes_value(stay_min),
                    "Pontos rastreador": row.get(points_col),
                }
            )
    return pd.DataFrame(rows, columns=columns)


def _format_export_datetime(value: object) -> str:
    if value in [None, ""]:
        return ""
    try:
        dt = pd.to_datetime(value, errors="coerce")
        if pd.isna(dt):
            return str(value or "")
        return dt.strftime("%d/%m/%Y %H:%M:%S")
    except Exception:
        return str(value or "")


def _add_minutes_to_datetime(value: object, minutes: object) -> str:
    try:
        dt = pd.to_datetime(value, errors="coerce")
        if pd.isna(dt):
            return ""
        minute_value = float(pd.to_numeric(pd.Series([minutes]), errors="coerce").fillna(0).iloc[0])
        return (dt + pd.to_timedelta(max(minute_value, 0), unit="m")).strftime("%d/%m/%Y %H:%M:%S")
    except Exception:
        return ""


def _period_query_datetime(value: object) -> str:
    try:
        dt = pd.to_datetime(value, errors="coerce")
        if pd.isna(dt):
            return ""
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


def _estadia_period_specs(df: pd.DataFrame) -> list[dict[str, object]]:
    specs: list[dict[str, object]] = []
    if df.empty:
        return specs
    for _, row in df.iterrows():
        common = {
            "lcte_id": row.get("id") or row.get("lcte_id"),
            "cte": row.get("cte"),
            "nf": row.get("nf"),
            "placa": row.get("placa_norm"),
            "cliente": row.get("cliente"),
            "motorista": row.get("motorista"),
            "origem": row.get("origem"),
            "destino": row.get("destino"),
        }
        for tipo, local_col, uf_col, arrival_col, departure_col, allowance_col, stay_col in [
            ("ORIGEM", "origem", "uf_origem", "chegada_origem", "saida_origem", "franquia_carga_min", "estadia_carga_min"),
            ("DESTINO", "destino", "uf_destino", "chegada_destino", "saida_destino", "franquia_descarga_min", "estadia_descarga_min"),
        ]:
            stay_min = float(pd.to_numeric(pd.Series([row.get(stay_col)]), errors="coerce").fillna(0).iloc[0])
            chegada = _period_query_datetime(row.get(arrival_col))
            saida = _period_query_datetime(row.get(departure_col))
            if stay_min <= 0 or not common["placa"] or not chegada or not saida:
                continue
            specs.append(
                {
                    **common,
                    "tipo": tipo,
                    "local": row.get(local_col),
                    "uf": row.get(uf_col),
                    "chegada": chegada,
                    "inicio_estadia": _add_minutes_to_datetime(row.get(arrival_col), row.get(allowance_col)),
                    "saida": saida,
                    "franquia_min": row.get(allowance_col),
                    "estadia_min": stay_min,
                }
            )
    return specs


def _estadia_pdf_option_label(spec: dict[str, object], index: int) -> str:
    return (
        f"{index}. {spec.get('tipo') or '-'} | Placa {spec.get('placa') or '-'} | "
        f"NF {spec.get('nf') or '-'} | Local {spec.get('local') or '-'}"
    )


def _estadia_pdf_options_frame(specs: list[dict[str, object]]) -> pd.DataFrame:
    rows = []
    for index, spec in enumerate(specs, start=1):
        rows.append(
            {
                "Exportar PDF": index == 1,
                "Linha": index,
                "Estadia": spec.get("tipo") or "",
                "Placa": spec.get("placa") or "",
                "Nota Fiscal": spec.get("nf") or "",
                "Local": spec.get("local") or "",
                "Origem": spec.get("origem") or "",
                "Destino": spec.get("destino") or "",
            }
        )
    return pd.DataFrame(rows)


def _sample_positions_30_minutes(positions: pd.DataFrame, limit: int = 500) -> pd.DataFrame:
    if positions.empty:
        return positions
    display = positions.copy()
    display["_data_dt"] = pd.to_datetime(display.get("data_hora"), errors="coerce")
    display = display[display["_data_dt"].notna()].sort_values("_data_dt")
    if display.empty:
        return positions.head(limit).copy()
    display["_bucket_30min"] = display["_data_dt"].dt.floor("30min")
    sampled = display.drop_duplicates("_bucket_30min", keep="first")
    last_row = display.tail(1)
    if not last_row.empty and last_row.index[0] not in sampled.index:
        sampled = pd.concat([sampled, last_row], ignore_index=False)
    return sampled.head(limit).drop(columns=["_data_dt", "_bucket_30min"], errors="ignore")


def _format_speed(value: object) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return str(value or "")
    speed = float(numeric)
    if speed.is_integer():
        return str(int(speed))
    return f"{speed:.1f}".replace(".", ",")


def _safe_pdf_filename(spec: dict[str, object], index: int) -> str:
    parts = [
        "relatorio_posicoes",
        str(index + 1),
        str(spec.get("tipo") or ""),
        str(spec.get("placa") or ""),
        f"nf_{spec.get('nf') or ''}",
    ]
    name = "_".join(part for part in parts if part).lower()
    name = re.sub(r"[^a-z0-9_-]+", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    return f"{name or f'relatorio_posicoes_{index + 1}'}.pdf"


def _tracker_positions_pdf(df: pd.DataFrame, selected_indexes: list[int] | None = None) -> bytes:
    from html import escape

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=A4, leftMargin=0.8 * cm, rightMargin=0.8 * cm, topMargin=6.0 * cm, bottomMargin=0.8 * cm)
    styles = getSampleStyleSheet()
    navy = colors.HexColor("#020d3f")
    gold = colors.HexColor("#c49a12")
    title_style = ParagraphStyle("PdfTitle", parent=styles["Title"], alignment=1, fontSize=14, leading=18, textColor=gold)
    header_cells: list[object] = [Paragraph("Relatorio de Posicoes Rastreador", title_style)]
    header = Table([header_cells], colWidths=[17.8 * cm])
    header.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), navy),
                ("TEXTCOLOR", (0, 0), (-1, -1), gold),
                ("BOX", (0, 0), (-1, -1), 0.5, gold),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    elements: list[object] = [header, Spacer(1, 0.35 * cm)]
    specs = _estadia_period_specs(df)
    if selected_indexes is not None:
        selected_set = {int(index) for index in selected_indexes if 0 <= int(index) < len(specs)}
        specs = [spec for index, spec in enumerate(specs) if index in selected_set]
    safe = lambda value, default="-": escape(str(value if value not in [None, ""] else default))
    if not specs:
        elements.append(Paragraph("Nenhum periodo de estadia localizado para exportacao.", styles["Normal"]))
    for idx, spec in enumerate(specs[:80], start=1):
        if idx > 1:
            elements.append(PageBreak())
        header = (
            f"Estadia: {safe(spec.get('tipo'))} | Placa: {safe(spec.get('placa'))} | "
            f"Nota Fiscal: {safe(spec.get('nf'))}"
        )
        elements.append(Paragraph(header, styles["Heading2"]))
        details = (
            f"Local: {safe(spec.get('local'))}<br/>"
            f"Origem/Destino viagem: {safe(spec.get('origem'))} &gt; {safe(spec.get('destino'))}"
        )
        elements.append(Paragraph(details, styles["Normal"]))
        elements.append(Spacer(1, 0.2 * cm))
        positions = read_rastreador_period(str(spec.get("placa") or ""), str(spec.get("chegada") or ""), str(spec.get("saida") or ""), 5000)
        if positions.empty:
            elements.append(Paragraph("Nenhuma posicao do rastreador encontrada para este periodo.", styles["Normal"]))
            continue
        display = _sample_positions_30_minutes(positions, 500)
        data = [["Placa", "Data e hora (intervalo 30 min)", "Municipio", "Velocidade"]]
        for _, point in display.iterrows():
            data.append(
                [
                    str(point.get("placa_norm") or spec.get("placa") or "")[:12],
                    _format_export_datetime(point.get("data_hora")),
                    str(point.get("cidade") or "")[:42],
                    _format_speed(point.get("velocidade") or point.get("velocidade_rastreador")),
                ]
            )
        table = Table(data, colWidths=[2.8 * cm, 4.8 * cm, 7.7 * cm, 2.5 * cm], repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), navy),
                    ("TEXTCOLOR", (0, 0), (-1, 0), gold),
                    ("TEXTCOLOR", (0, 1), (-1, -1), navy),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#b7b7b7")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 7),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        elements.append(table)
        if len(positions) > len(display):
            elements.append(Paragraph(f"Posicoes resumidas em intervalos de 30 minutos. Exibidas {len(display)} de {len(positions)} posicoes deste periodo.", styles["Italic"]))
    if len(specs) > 80:
        elements.append(PageBreak())
        elements.append(Paragraph(f"Relatorio limitado aos primeiros 80 periodos de estadia filtrados. Total filtrado: {len(specs)}.", styles["Normal"]))

    def draw_background(canvas, document) -> None:
        if RODO_WALL_PDF_BACKGROUND_PATH.exists():
            width, height = document.pagesize
            canvas.drawImage(str(RODO_WALL_PDF_BACKGROUND_PATH), 0, 0, width=width, height=height, preserveAspectRatio=False, mask="auto")

    doc.build(elements, onFirstPage=draw_background, onLaterPages=draw_background)
    return output.getvalue()


def _tracker_positions_pdf_zip(df: pd.DataFrame, selected_indexes: list[int]) -> bytes:
    specs = _estadia_period_specs(df)
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for index in selected_indexes:
            if index < 0 or index >= len(specs):
                continue
            filename = _safe_pdf_filename(specs[index], index)
            archive.writestr(filename, _tracker_positions_pdf(df, [index]))
    return output.getvalue()


def _estadia_period_rows(df: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "ID viagem",
        "CT-e",
        "NF",
        "Placa",
        "Cliente",
        "Motorista",
        "Tipo estadia",
        "Local",
        "UF",
        "Chegada no ponto",
        "Inicio da estadia",
        "Saida do ponto",
        "Tempo total no ponto (min)",
        "Franquia (min)",
        "Tempo estadia (min)",
        "Tempo estadia",
        "Valor estimado",
        "Status estadia",
        "Confianca permanencia (%)",
    ]
    if df.empty:
        return pd.DataFrame(columns=columns)
    rows: list[dict[str, object]] = []
    for _, row in df.iterrows():
        common = {
            "ID viagem": row.get("id"),
            "CT-e": row.get("cte"),
            "NF": row.get("nf"),
            "Placa": row.get("placa_norm"),
            "Cliente": row.get("cliente"),
            "Motorista": row.get("motorista"),
            "Valor estimado": row.get("valor_estimado_estadia"),
            "Status estadia": row.get("status_estadia"),
        }
        for tipo, local_col, uf_col, arrival_col, departure_col, time_col, allowance_col, stay_col, confidence_col in [
            ("CARGA", "origem", "uf_origem", "chegada_origem", "saida_origem", "tempo_origem_min", "franquia_carga_min", "estadia_carga_min", "confianca_permanencia_origem_pct"),
            ("DESCARGA", "destino", "uf_destino", "chegada_destino", "saida_destino", "tempo_destino_min", "franquia_descarga_min", "estadia_descarga_min", "confianca_permanencia_destino_pct"),
        ]:
            stay_min = float(pd.to_numeric(pd.Series([row.get(stay_col)]), errors="coerce").fillna(0).iloc[0])
            if stay_min <= 0:
                continue
            arrival = row.get(arrival_col)
            rows.append(
                {
                    **common,
                    "Tipo estadia": tipo,
                    "Local": row.get(local_col),
                    "UF": row.get(uf_col),
                    "Chegada no ponto": _format_export_datetime(arrival),
                    "Inicio da estadia": _add_minutes_to_datetime(arrival, row.get(allowance_col)),
                    "Saida do ponto": _format_export_datetime(row.get(departure_col)),
                    "Tempo total no ponto (min)": row.get(time_col),
                    "Franquia (min)": row.get(allowance_col),
                    "Tempo estadia (min)": stay_min,
                    "Tempo estadia": _format_minutes_value(stay_min),
                    "Confianca permanencia (%)": row.get(confidence_col),
                }
            )
    return pd.DataFrame(rows, columns=columns)


def _with_estadia_display_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    view = df.copy()
    control_flag = view["encontrou_control"] if "encontrou_control" in view.columns else pd.Series(0, index=view.index)
    tracker_flag = view["encontrou_rastreador"] if "encontrou_rastreador" in view.columns else pd.Series(0, index=view.index)
    horas = pd.to_numeric(view["horas_estadia"] if "horas_estadia" in view.columns else pd.Series(0, index=view.index), errors="coerce").fillna(0)
    view["Estadia"] = horas.gt(0).map(lambda value: "Estadia" if value else "Sem estadia")
    view["Relatorio CONTROL"] = pd.to_numeric(control_flag, errors="coerce").fillna(0).astype(int).eq(1).map(lambda value: "OK" if value else "FALTANDO")
    view["Relatorio Rastreador"] = pd.to_numeric(tracker_flag, errors="coerce").fillna(0).astype(int).eq(1).map(lambda value: "OK" if value else "FALTANDO")
    view["Data Emissao NF"] = _safe_series(view, "data_emissao_nf").map(_format_datetime_display)
    view["Tipo ponto origem"] = "ORIGEM"
    view["Local origem estadia"] = view["origem"] if "origem" in view.columns else ""
    view["Tempo na origem (min)"] = view["tempo_origem_min"] if "tempo_origem_min" in view.columns else 0
    view["Tempo na origem"] = view["Tempo na origem (min)"].map(_format_minutes_value)
    view["Tipo ponto destino"] = "DESTINO"
    view["Local destino estadia"] = view["destino"] if "destino" in view.columns else ""
    view["Tempo no destino (min)"] = view["tempo_destino_min"] if "tempo_destino_min" in view.columns else 0
    view["Tempo no destino"] = view["Tempo no destino (min)"].map(_format_minutes_value)
    return view


def _export_sheets(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    if df.empty:
        return {"resultado_completo": df}
    result = _with_estadia_display_columns(df)
    permanencias = _permanence_rows(df)
    series = lambda column, default="": df[column] if column in df.columns else pd.Series(default, index=df.index)
    horas = pd.to_numeric(series("horas_estadia", 0), errors="coerce").fillna(0)
    calculadas = series("calculou_estadia", 0).fillna(0).astype(int).eq(1)
    com_rastreador = series("encontrou_rastreador", 0).fillna(0).astype(int).eq(1)
    elegiveis = series("elegivel_cobranca", 0).fillna(0).astype(int).eq(1)
    status = series("status_cruzamento").fillna("").astype(str)
    classificacao = series("classificacao_control").fillna("").astype(str)
    codigo_motivo = series("codigo_motivo").fillna("").astype(str)
    motivo_falha = series("motivo_falha").fillna("").astype(str)
    motivos = codigo_motivo + " " + motivo_falha
    return {
        "resultado_completo": result,
        "periodos_estadia": _estadia_period_rows(df),
        "permanencia_origem_destino": permanencias,
        "com_estadia": result[horas.gt(0)],
        "elegiveis": result[elegiveis],
        "nao_elegiveis": result[calculadas & elegiveis.ne(True)],
        "nao_calculadas": result[com_rastreador & calculadas.ne(True)],
        "inconsistencias": result[status.eq("ERRO") | motivos.str.contains("MULTIPLAS|CONFLITO|INVALIDA|ERRO", regex=True, na=False)],
        "sem_control": result[series("encontrou_control", 0).fillna(0).astype(int).ne(1)],
        "sem_rastreador": result[com_rastreador.ne(True)],
        "vinculos_provaveis": result[classificacao.isin(["PROVAVEL", "REVISAO_MANUAL"])],
        "sem_coordenadas": result[codigo_motivo.str.contains("SEM_COORDENADAS", na=False)],
        "diagnostico": result,
        "auditoria": read_auditoria(5000),
    }


def render_dashboard_page() -> None:
    st.title("Dashboard Estadias")
    metric_grid(dashboard_metrics(), columns=4)
    with st.expander("Limpeza do banco de Estadias", expanded=False):
        st.warning("Esta acao limpa LCTE, CONTROL, Rastreador, cruzamentos, diagnosticos e logs de importacao de Estadias. Configuracoes, locais e parametros serao mantidos.")
        confirmar = st.text_input("Digite LIMPAR ESTADIAS para confirmar", key="estadias_confirmar_limpeza_total")
        if st.button("Limpar banco de Estadias", type="primary", use_container_width=True, disabled=confirmar.strip().upper() != "LIMPAR ESTADIAS"):
            deleted = clear_estadias_imported_database()
            for key in list(st.session_state):
                if str(key).startswith("estadias_") and key != "estadias_confirmar_limpeza_total":
                    del st.session_state[key]
            st.success(f"Banco de Estadias limpo. Registros removidos: {sum(deleted.values())}.")
            st.rerun()

    tops = top_indicators()
    if tops:
        col_a, col_b = st.columns(2)
        with col_a:
            st.subheader("Top clientes")
            render_dataframe(tops.get("Top clientes"), height=260, max_rows=10)
            st.subheader("Top motoristas")
            render_dataframe(tops.get("Top motoristas"), height=260, max_rows=10)
        with col_b:
            st.subheader("Top bases")
            render_dataframe(tops.get("Top bases"), height=260, max_rows=10)
            st.subheader("Top placas")
            render_dataframe(tops.get("Top placas"), height=260, max_rows=10)

    st.subheader("Ultimas importacoes")
    render_dataframe(latest_logs(20), height=280, max_rows=20)

    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Arquivos rastreador importados")
        render_dataframe(arquivos_rastreador_importados(100), height=320, max_rows=100)
    with col_b:
        st.subheader("Placas disponiveis")
        render_dataframe(placas_disponiveis(), height=320, max_rows=200)

    st.subheader("Amostra LCTE Ipiranga")
    render_dataframe(sample(LCTE_NORMALIZED_TABLE, 50), height=260, max_rows=50)
    st.subheader("Amostra CONTROL")
    render_dataframe(sample(CONTROL_NORMALIZED_TABLE, 50), height=260, max_rows=50)
    st.subheader("Amostra Rastreador")
    render_dataframe(sample(RASTREADOR_NORMALIZED_TABLE, 50), height=260, max_rows=50)


def render_imports_page(usuario: str, role: str) -> None:
    st.title("Importacoes Estadias")
    st.caption("Importacoes proprias do modulo Estadias. O LCTE Ipiranga e a base mestre das viagens.")
    if str(role or "").upper() not in {"ADMIN", "OPERACIONAL"}:
        st.error("Seu perfil nao possui permissao para importar arquivos de Estadias.")
        return

    with st.expander("IMPORTAR LCTE IPIRANGA", expanded=True):
        col_clear_a, col_clear_b = st.columns([2, 1])
        confirmar_limpeza_lcte = col_clear_a.checkbox("Confirmo limpar LCTE importado e diagnosticos vinculados", key="estadias_confirmar_limpar_lcte")
        if col_clear_b.button("Limpar LCTE", use_container_width=True, disabled=not confirmar_limpeza_lcte):
            deleted = clear_lcte_base()
            st.session_state.estadias_lcte_upload_version = int(st.session_state.get("estadias_lcte_upload_version", 0)) + 1
            st.success(f"LCTE limpo. Registros removidos: {sum(deleted.values())}.")
            st.rerun()
        upload_key = f"estadias_lcte_upload_{int(st.session_state.get('estadias_lcte_upload_version', 0))}"
        lcte_file = st.file_uploader("Arquivo LCTE Ipiranga", type=["xlsx", "xls", "csv"], key=upload_key)
        lcte_mode = _duplicate_mode(role, "estadias_lcte_duplicate_mode")
        if st.button("Importar LCTE Ipiranga", type="primary", use_container_width=True, disabled=lcte_file is None):
            with st.spinner("Importando LCTE Ipiranga..."):
                result = import_lcte_ipiranga(lcte_file, usuario, lcte_mode)
            if result.get("status") == "SUCESSO":
                st.success(f"LCTE importado. Lote: {result.get('lote')} | Viagens: {result.get('viagens')}")
                metric_grid(
                    {"Arquivo": result.get("arquivo", "-"), "Viagens lidas": result.get("viagens", 0), **_import_metric_payload(result)},
                    columns=4,
                )
                inconsistencias = result.get("inconsistencias")
                if isinstance(inconsistencias, pd.DataFrame) and not inconsistencias.empty:
                    st.warning(f"{len(inconsistencias)} inconsistencia(s) encontrada(s) no LCTE.")
                    render_dataframe(inconsistencias, height=300, max_rows=200)
                st.json(result.get("colunas_encontradas") or {})
                amostra = result.get("amostra")
                if isinstance(amostra, pd.DataFrame):
                    render_dataframe(amostra, height=260, max_rows=20)
            elif result.get("status") == "DUPLICADO":
                st.warning(result.get("mensagem"))
            else:
                st.error(result.get("mensagem") or "Erro ao importar LCTE Ipiranga.")

    with st.expander("Importar CONTROL - Estadias", expanded=True):
        control_file = st.file_uploader("Arquivo CONTROL", type=["xlsx", "xls", "csv"], key="estadias_control_upload")
        mode = _duplicate_mode(role, "estadias_control_duplicate_mode")
        if st.button("Importar CONTROL", type="primary", use_container_width=True, disabled=control_file is None):
            with st.spinner("Importando CONTROL..."):
                result = import_control(control_file, usuario, mode)
            if result.get("status") == "SUCESSO":
                st.success(f"CONTROL importado. Lote: {result.get('lote')} | Linhas: {result.get('linhas')}")
                metric_grid({"Arquivo": result.get("arquivo", "-"), **_import_metric_payload(result)}, columns=4)
                st.json(result.get("colunas_encontradas") or {})
                amostra = result.get("amostra")
                if isinstance(amostra, pd.DataFrame):
                    render_dataframe(amostra, height=260, max_rows=20)
            elif result.get("status") == "DUPLICADO":
                st.warning(result.get("mensagem"))
            else:
                st.error(result.get("mensagem") or "Erro ao importar CONTROL.")

    with st.expander("Importar Relatorios Rastreador por Placa", expanded=True):
        st.session_state.setdefault("estadias_rastreador_upload_version", 0)
        tracker_files = st.file_uploader(
            "Relatorios do rastreador",
            type=["xlsx", "xls", "csv"],
            accept_multiple_files=True,
            key=f"estadias_rastreador_upload_{int(st.session_state.get('estadias_rastreador_upload_version', 0))}",
        )
        if tracker_files:
            preview = pd.DataFrame(
                [
                    {
                        "arquivo": getattr(file, "name", ""),
                        "placa_identificada": extrair_placa_do_nome_arquivo(getattr(file, "name", "")),
                    }
                    for file in tracker_files
                ]
            )
            st.caption(f"{len(tracker_files)} arquivo(s) selecionado(s).")
            if len(tracker_files) > 20:
                st.warning("Para evitar queda por memoria/tempo, o sistema vai processar em lotes e liberar os arquivos da tela ao terminar.")
            render_dataframe(preview, height=260, max_rows=120)
        tracker_mode = _duplicate_mode(role, "estadias_rastreador_duplicate_mode")
        if st.button("Importar relatorios do rastreador", type="primary", use_container_width=True, disabled=not tracker_files):
            progress = st.progress(0)
            status_text = st.empty()

            def update_progress(current: int, total: int, file_name: str) -> None:
                progress.progress(current / max(total, 1))
                status_text.info(f"Importando {current}/{total}: {file_name}")

            result = import_rastreador_files(list(tracker_files or []), usuario, tracker_mode, update_progress)
            progress.empty()
            status_text.empty()
            if int(result.get("total_linhas") or 0) >= 20000 or len(tracker_files or []) > 5:
                st.session_state["skip_next_auto_backup"] = True
            st.session_state["estadias_last_tracker_import_result"] = result
            st.session_state["estadias_rastreador_upload_version"] = int(st.session_state.get("estadias_rastreador_upload_version", 0)) + 1
            st.rerun()
        last_tracker_result = st.session_state.get("estadias_last_tracker_import_result")
        if isinstance(last_tracker_result, dict):
            st.success(
                f"Lote {last_tracker_result.get('lote')}: {last_tracker_result.get('arquivos_sucesso')} sucesso, "
                f"{last_tracker_result.get('arquivos_erro')} erro(s), {last_tracker_result.get('arquivos_duplicados')} duplicado(s), "
                f"{last_tracker_result.get('total_linhas')} linha(s)."
            )
            render_dataframe(last_tracker_result.get("resultado"), height=360, max_rows=200)


def _multiselect_filter(table: str, column: str, label: str) -> list[str]:
    options = select_distinct(table, column, 500)
    return st.multiselect(label, options, key=f"estadias_filter_{table}_{column}")


def render_control_page() -> None:
    st.title("Base CONTROL")
    col_a, col_b, col_c, col_d = st.columns(4)
    filters = {
        "lote_importacao": col_a.selectbox("Lote", ["", *select_distinct(CONTROL_NORMALIZED_TABLE, "lote_importacao", 200)]),
        "arquivo_origem": col_b.selectbox("Arquivo", ["", *select_distinct(CONTROL_NORMALIZED_TABLE, "arquivo_origem", 500)]),
        "placa_norm": col_c.text_input("Placa"),
        "data_inicio": col_d.text_input("Data"),
        "motorista": _multiselect_filter(CONTROL_NORMALIZED_TABLE, "motorista", "Motorista"),
        "cliente": _multiselect_filter(CONTROL_NORMALIZED_TABLE, "cliente", "Cliente"),
        "status": _multiselect_filter(CONTROL_NORMALIZED_TABLE, "status", "Status"),
        "tipo_evento": _multiselect_filter(CONTROL_NORMALIZED_TABLE, "tipo_evento", "Tipo evento"),
    }
    df = read_control(filters, 5000)
    st.download_button(
        "Exportar Excel",
        dataframe_to_excel({"control": df}),
        "estadias_control.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
        disabled=df.empty,
    )
    render_dataframe(df, height=560, max_rows=1000)


def render_rastreador_page() -> None:
    st.title("Relatorios Rastreador por Placa")
    col_a, col_b, col_c, col_d, col_e = st.columns(5)
    filters = {
        "lote_importacao": col_a.selectbox("Lote", ["", *select_distinct(RASTREADOR_NORMALIZED_TABLE, "lote_importacao", 200)]),
        "arquivo_origem": col_b.selectbox("Arquivo", ["", *select_distinct(RASTREADOR_NORMALIZED_TABLE, "arquivo_origem", 500)]),
        "placa_norm": col_c.text_input("Placa"),
        "data": col_d.text_input("Data"),
        "velocidade": col_e.text_input("Velocidade"),
        "cidade": _multiselect_filter(RASTREADOR_NORMALIZED_TABLE, "cidade", "Cidade"),
        "uf": _multiselect_filter(RASTREADOR_NORMALIZED_TABLE, "uf", "UF"),
        "ignicao": _multiselect_filter(RASTREADOR_NORMALIZED_TABLE, "ignicao", "Ignicao"),
        "evento": _multiselect_filter(RASTREADOR_NORMALIZED_TABLE, "evento", "Evento"),
    }
    df = read_rastreador(filters, 5000)
    st.download_button(
        "Exportar Excel",
        dataframe_to_excel({"rastreador": df}),
        "estadias_rastreador.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
        disabled=df.empty,
    )
    render_dataframe(df, height=560, max_rows=1000)


def render_lcte_panel() -> None:
    st.subheader("Base mestre LCTE Ipiranga")
    col_a, col_b, col_c, col_d = st.columns(4)
    filters = {
        "lote_importacao": col_a.selectbox("Lote LCTE", ["", *select_distinct(LCTE_NORMALIZED_TABLE, "lote_importacao", 200)]),
        "arquivo_origem": col_b.selectbox("Arquivo LCTE", ["", *select_distinct(LCTE_NORMALIZED_TABLE, "arquivo_origem", 500)]),
        "placa_norm": col_c.text_input("Placa LCTE"),
        "data_operacao": col_d.text_input("Data LCTE"),
    }
    df = read_lcte(filters, 5000)
    render_dataframe(df, height=360, max_rows=500)


DATE_DISPLAY_COLUMNS = [
    "data_emissao_nf",
    "data_operacao",
    "data_hora_carga",
    "data_inicio_viagem_referencia",
    "inicio_janela",
    "fim_janela",
    "primeira_data_control",
    "ultima_data_control",
    "primeira_data_rastreador",
    "ultima_data_rastreador",
    "chegada_origem",
    "saida_origem",
    "chegada_destino",
    "saida_destino",
    "control_chegada_origem",
    "control_saida_origem",
    "control_chegada_destino",
    "control_saida_destino",
    "data_hora_conclusao",
    "data_limite_retorno",
    "data_retorno",
]


PANEL_DEFAULT_COLUMNS = {
    "RESUMO": [
        "Status",
        "Estadia",
        "Relatorio CONTROL",
        "Relatorio Rastreador",
        "Notas",
        "Data Emissao NF",
        "Placa",
        "Origem",
        "Destino",
        "Tipo",
        "Chegada Rastreador",
        "Saida Rastreador",
        "Tempo Rastreador",
        "Chegada Control",
        "Saida Control",
        "Tempo Control",
        "Status Estadia",
        "Diferenca",
        "Motivo",
        "Concluir",
    ],
    "ESTADIAS": [
        "id",
        "cte",
        "nf",
        "placa_norm",
        "data_emissao_nf",
        "data_inicio_viagem_referencia",
        "origem",
        "destino",
        "cliente",
        "motorista",
        "tempo_origem_min",
        "tempo_destino_min",
        "estadia_carga_min",
        "estadia_descarga_min",
        "horas_estadia",
        "valor_estimado_estadia",
        "maior_divergencia_min",
        "status_cte",
    ],
    "VERIFICACAO": [
        "id",
        "cte",
        "nf",
        "placa_norm",
        "data_emissao_nf",
        "data_inicio_viagem_referencia",
        "origem",
        "destino",
        "status_verificacao",
        "motivo_falha",
        "encontrou_control",
        "encontrou_rastreador",
        "encontrou_origem",
        "encontrou_destino",
        "maior_divergencia_min",
        "eventos_sem_control",
        "eventos_sem_rastreador",
    ],
    "CONCLUIDOS": [
        "id",
        "cte",
        "nf",
        "placa_norm",
        "data_emissao_nf",
        "data_inicio_viagem_referencia",
        "cliente",
        "tipo_conclusao",
        "status_tratativa",
        "usuario_conclusao",
        "data_hora_conclusao",
        "data_limite_retorno",
        "dias_restantes",
        "status_prazo",
        "precisa_verificar",
        "protocolo",
        "valor_solicitado",
        "valor_aprovado",
    ],
    "LCTE": [
        "id",
        "lcte_id",
        "cte",
        "nf",
        "placa_norm",
        "data_emissao_nf",
        "data_operacao",
        "data_hora_carga",
        "origem",
        "destino",
        "cliente",
        "motorista",
        "painel_atual",
        "status_cte",
        "status_cruzamento",
        "codigo_motivo",
        "motivo_falha",
    ],
}


def _safe_series(df: pd.DataFrame, column: str, default: object = "") -> pd.Series:
    if column in df.columns:
        return df[column]
    return pd.Series(default, index=df.index)


def _num_series(df: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(_safe_series(df, column, 0), errors="coerce").fillna(0)


def _bool_series(df: pd.DataFrame, column: str) -> pd.Series:
    return _num_series(df, column).astype(int).eq(1)


def _safe_int_value(value: object, default: int = 0) -> int:
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, str):
        text = value.strip().upper()
        if text in {"", "NAN", "NONE", "NULL", "NA"}:
            return default
        if text in {"SIM", "S", "TRUE", "VERDADEIRO", "YES", "Y"}:
            return 1
        if text in {"NAO", "NÃO", "N", "FALSE", "FALSO", "NO"}:
            return 0
        text = text.replace(",", ".")
    else:
        text = value
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return default


def _safe_bool_value(value: object) -> bool:
    return _safe_int_value(value, 0) != 0


def _format_datetime_display(value: object) -> str:
    if value is None or str(value).strip() == "":
        return ""
    parsed = pd.to_datetime(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(parsed):
        return str(value)
    return parsed.strftime("%d/%m/%Y %H:%M")


def _format_cross_dates(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    view = df.copy()
    for column in DATE_DISPLAY_COLUMNS:
        if column in view.columns:
            view[column] = view[column].map(_format_datetime_display)
    return view


def _panel_base(df: pd.DataFrame, panel: str) -> pd.DataFrame:
    if df.empty:
        return df
    painel = _safe_series(df, "painel_atual").fillna("").astype(str).str.upper()
    concluido = _bool_series(df, "concluido")
    if panel == "ESTADIAS":
        base = df[painel.eq("ESTADIAS") & ~concluido]
        if base.empty:
            base = df[_bool_series(df, "calculou_estadia") & _bool_series(df, "elegivel_cobranca") & ~_bool_series(df, "precisa_verificar") & ~concluido]
        return base
    if panel == "VERIFICACAO":
        base = df[painel.eq("VERIFICACAO") & ~concluido]
        if base.empty:
            base = df[_bool_series(df, "precisa_verificar") & ~concluido]
        return base
    if panel == "CONCLUIDOS":
        return df[painel.eq("CONCLUIDOS") | concluido]
    return df


def _cross_card_defs(panel: str) -> list[dict[str, str]]:
    common = [
        {"key": "sem_control", "label": "Sem CONTROL", "group": "control"},
        {"key": "sem_rastreador", "label": "Sem Rastreador", "group": "rastreador"},
        {"key": "divergencia_tolerancia", "label": "Fora da tolerancia", "group": "tolerancia"},
        {"key": "origem_destino_falha", "label": "Origem/destino pendente", "group": "permanencia"},
    ]
    if panel == "ESTADIAS":
        return [
            {"key": "estadia_carga", "label": "Estadia na carga", "group": "tipo_estadia"},
            {"key": "estadia_descarga", "label": "Estadia na descarga", "group": "tipo_estadia"},
            {"key": "valor_estimado", "label": "Com valor estimado", "group": "valor"},
            {"key": "match_valido", "label": "Dentro da tolerancia", "group": "tolerancia"},
        ]
    if panel == "CONCLUIDOS":
        return [
            {"key": "retorno_pendente", "label": "Retorno pendente", "group": "retorno"},
            {"key": "prazo_vencido", "label": "Prazo vencido", "group": "retorno"},
            {"key": "precisa_verificar", "label": "Precisa verificar", "group": "retorno"},
            {"key": "retorno_recebido", "label": "Retorno recebido", "group": "retorno"},
        ]
    if panel == "LCTE":
        return [
            {"key": "painel_estadias", "label": "Em Estadias", "group": "painel"},
            {"key": "painel_verificacao", "label": "Em Verificacao", "group": "painel"},
            {"key": "painel_concluidos", "label": "Concluidos", "group": "painel"},
            {"key": "somente_lcte", "label": "Somente LCTE", "group": "painel"},
        ]
    return common + [{"key": "precisa_verificar", "label": "Precisa verificar", "group": "verificacao"}]


def _cross_card_mask(df: pd.DataFrame, key: str) -> pd.Series:
    status_prazo = _safe_series(df, "status_prazo").fillna("").astype(str)
    painel = _safe_series(df, "painel_atual").fillna("").astype(str).str.upper()
    if key == "sem_control":
        return ~_bool_series(df, "encontrou_control")
    if key == "sem_rastreador":
        return ~_bool_series(df, "encontrou_rastreador")
    if key == "divergencia_tolerancia":
        return _num_series(df, "eventos_comparaveis").gt(0) & ~_bool_series(df, "dentro_tolerancia_control_rastreador")
    if key == "origem_destino_falha":
        return ~_bool_series(df, "encontrou_origem") | ~_bool_series(df, "encontrou_destino")
    if key == "estadia_carga":
        return _num_series(df, "estadia_carga_min").gt(0)
    if key == "estadia_descarga":
        return _num_series(df, "estadia_descarga_min").gt(0)
    if key == "valor_estimado":
        return _num_series(df, "valor_estimado_estadia").gt(0)
    if key == "match_valido":
        return _num_series(df, "eventos_comparaveis").gt(0) & _bool_series(df, "dentro_tolerancia_control_rastreador")
    if key == "retorno_pendente":
        return _safe_series(df, "status_cte").fillna("").astype(str).str.contains("Aguardando retorno", case=False, na=False)
    if key == "prazo_vencido":
        return status_prazo.str.contains("vencido", case=False, na=False)
    if key == "precisa_verificar":
        return _bool_series(df, "precisa_verificar")
    if key == "retorno_recebido":
        return _bool_series(df, "retorno_recebido")
    if key == "painel_estadias":
        return painel.eq("ESTADIAS")
    if key == "painel_verificacao":
        return painel.eq("VERIFICACAO")
    if key == "painel_concluidos":
        return painel.eq("CONCLUIDOS")
    if key == "somente_lcte":
        return painel.eq("SOMENTE_LCTE") | painel.eq("")
    return pd.Series(True, index=df.index)


def _toggle_cross_card(panel: str, card_key: str, group: str) -> None:
    state_key = f"estadias_cross_cards_{panel}"
    cards = dict(st.session_state.get(state_key, {}))
    if cards.get(group) == card_key:
        cards.pop(group, None)
    else:
        cards[group] = card_key
    st.session_state[state_key] = cards


def _clear_cross_cards(panel: str) -> None:
    st.session_state[f"estadias_cross_cards_{panel}"] = {}


def _apply_cross_cards(df: pd.DataFrame, cards: dict[str, str], exclude_group: str = "") -> pd.DataFrame:
    filtered = df
    for group, key in cards.items():
        if group == exclude_group:
            continue
        filtered = filtered[_cross_card_mask(filtered, key)]
    return filtered


def _render_cross_cards(panel: str, df: pd.DataFrame) -> dict[str, str]:
    state_key = f"estadias_cross_cards_{panel}"
    active = dict(st.session_state.get(state_key, {}))
    defs = _cross_card_defs(panel)
    cols = st.columns(min(4, max(1, len(defs))))
    for index, definition in enumerate(defs):
        base = _apply_cross_cards(df, active, definition["group"])
        count = int(_cross_card_mask(base, definition["key"]).sum()) if not base.empty else 0
        selected = active.get(definition["group"]) == definition["key"]
        label = f"{definition['label']}\n{count}"
        cols[index % len(cols)].button(
            label,
            key=f"estadias_cross_card_{panel}_{definition['key']}",
            type="primary" if selected else "secondary",
            use_container_width=True,
            on_click=_toggle_cross_card,
            args=(panel, definition["key"], definition["group"]),
        )
    if active:
        st.button("Limpar cards deste painel", key=f"estadias_cross_clear_cards_{panel}", on_click=_clear_cross_cards, args=(panel,))
    return active


def _cross_date_basis(df: pd.DataFrame) -> pd.Series:
    dates = pd.to_datetime(_safe_series(df, "data_inicio_viagem_referencia"), errors="coerce")
    if dates.notna().any():
        return dates
    dates = pd.to_datetime(_safe_series(df, "data_hora_carga"), errors="coerce")
    if dates.notna().any():
        return dates
    return pd.to_datetime(_safe_series(df, "data_operacao"), errors="coerce")


def _render_cross_filters(panel: str, df: pd.DataFrame) -> dict[str, object]:
    with st.expander("Filtros", expanded=True):
        dates = _cross_date_basis(df)
        years = sorted([int(value) for value in dates.dt.year.dropna().unique().tolist()])
        months = sorted([int(value) for value in dates.dt.month.dropna().unique().tolist()])
        col_a, col_b, col_c, col_d = st.columns(4)
        filters = {
            "anos": col_a.multiselect("Ano", years, key=f"estadias_cross_{panel}_anos"),
            "meses": col_b.multiselect("Mes", months, format_func=lambda value: f"{int(value):02d}", key=f"estadias_cross_{panel}_meses"),
            "placa": col_c.text_input("Placa", key=f"estadias_cross_{panel}_placa"),
            "cte": col_d.text_input("CT-e", key=f"estadias_cross_{panel}_cte"),
        }
        col_e, col_f, col_g, col_h = st.columns(4)
        filters.update(
            {
                "nf": col_e.text_input("NF", key=f"estadias_cross_{panel}_nf"),
                "origem": col_f.text_input("Origem", key=f"estadias_cross_{panel}_origem"),
                "destino": col_g.text_input("Destino", key=f"estadias_cross_{panel}_destino"),
                "cliente": col_h.text_input("Cliente", key=f"estadias_cross_{panel}_cliente"),
            }
        )
        col_i, col_j = st.columns(2)
        filters["motorista"] = col_i.text_input("Motorista", key=f"estadias_cross_{panel}_motorista")
        status_values = sorted(_safe_series(df, "status_cte").fillna("").astype(str).replace("", pd.NA).dropna().unique().tolist())
        filters["status_cte"] = col_j.selectbox("Status CT-e", ["", *status_values], key=f"estadias_cross_{panel}_status_cte")
    return filters


def _apply_cross_filters(df: pd.DataFrame, filters: dict[str, object]) -> pd.DataFrame:
    filtered = df.copy()
    if filtered.empty:
        return filtered
    dates = _cross_date_basis(filtered)
    anos = filters.get("anos") or []
    meses = filters.get("meses") or []
    if anos:
        filtered = filtered[dates.dt.year.isin(anos)]
        dates = dates.loc[filtered.index]
    if meses:
        filtered = filtered[dates.dt.month.isin(meses)]
    for column, key in [
        ("placa_norm", "placa"),
        ("cte", "cte"),
        ("nf", "nf"),
        ("origem", "origem"),
        ("destino", "destino"),
        ("cliente", "cliente"),
        ("motorista", "motorista"),
        ("status_cte", "status_cte"),
    ]:
        value = str(filters.get(key) or "").strip()
        if value and column in filtered.columns:
            filtered = filtered[filtered[column].fillna("").astype(str).str.contains(value, case=False, na=False)]
    return filtered


def _set_column_selection(key: str, values: list[str]) -> None:
    st.session_state[key] = values


def _insert_column_after(columns: list[str], column: str, after_column: str, options: list[str]) -> list[str]:
    visible = [item for item in columns if item in options]
    if column not in options or column in visible:
        return visible
    if after_column in visible:
        index = visible.index(after_column) + 1
        return [*visible[:index], column, *visible[index:]]
    return [*visible, column]


def _configured_columns(panel: str, df: pd.DataFrame, usuario: str) -> list[str]:
    options = [str(column) for column in df.columns]
    defaults = [column for column in PANEL_DEFAULT_COLUMNS.get(panel, options[:18]) if column in options]
    if not defaults:
        defaults = options[:18]
    widget_key = f"estadias_cross_columns_{panel}"
    if widget_key not in st.session_state:
        saved = [column for column in read_preferencia_colunas(usuario, panel) if column in options]
        st.session_state[widget_key] = saved or defaults
    if panel == "RESUMO":
        st.session_state[widget_key] = _insert_column_after(
            list(st.session_state.get(widget_key, defaults)),
            "Status Estadia",
            "Tempo Control",
            options,
        )
    with st.expander("Configurar colunas", expanded=False):
        col_a, col_b, col_c = st.columns(3)
        col_a.button("Modelo padrao", key=f"{widget_key}_default", on_click=_set_column_selection, args=(widget_key, defaults))
        col_b.button("Todas", key=f"{widget_key}_all", on_click=_set_column_selection, args=(widget_key, options))
        selected = st.multiselect("Colunas visiveis", options, key=widget_key)
        if col_c.button("Salvar preferencia", key=f"{widget_key}_save"):
            save_preferencia_colunas(usuario, panel, selected)
            st.success("Preferencia de colunas salva para este usuario.")
    return [column for column in st.session_state.get(widget_key, defaults) if column in options] or defaults


def _render_conclusion_form(panel: str, df: pd.DataFrame, usuario: str) -> None:
    if df.empty or panel not in {"ESTADIAS", "VERIFICACAO"}:
        return
    with st.expander("Concluir e mover para Banco de Dados - Concluidos", expanded=False):
        options = []
        row_by_lcte: dict[int, pd.Series] = {}
        for _, row in df.iterrows():
            lcte_id = int(row.get("lcte_id") or row.get("id") or 0)
            if not lcte_id:
                continue
            row_by_lcte[lcte_id] = row
            options.append(f"{lcte_id} | CT-e {row.get('cte') or '-'} | NF {row.get('nf') or '-'} | {row.get('placa_norm') or '-'}")
        if not options:
            st.info("Nenhuma viagem disponivel para conclusao neste filtro.")
            return
        with st.form(f"estadias_concluir_{panel}"):
            selected = st.selectbox("Viagem", options)
            lcte_id = int(str(selected).split("|", 1)[0].strip())
            col_a, col_b, col_c = st.columns(3)
            tipo = col_a.selectbox("Tipo de conclusao", ["Cobrar estadia", "Nao cobrar", "Ajuste operacional", "Duplicidade", "Outro"])
            status = col_b.selectbox("Status da tratativa", ["Concluido", "Enviado para cobranca", "Aguardando cliente", "Resolvido internamente"])
            protocolo = col_c.text_input("Protocolo")
            col_d, col_e, col_f, col_g = st.columns(4)
            valor_solicitado = col_d.number_input("Valor solicitado", min_value=0.0, value=0.0, step=10.0)
            valor_aprovado = col_e.number_input("Valor aprovado", min_value=0.0, value=0.0, step=10.0)
            necessita_retorno = col_f.checkbox("Necessita retorno", value=True)
            retorno_recebido = col_g.checkbox("Retorno recebido", value=False)
            col_h, col_i = st.columns(2)
            status_retorno = col_h.text_input("Status do retorno")
            data_retorno = col_i.text_input("Data do retorno")
            precisa_verificar = st.checkbox("Marcar para verificacao no prazo/retorno", value=False)
            observacao = st.text_area("Observacao")
            submitted = st.form_submit_button("Salvar conclusao", type="primary")
        if submitted:
            payload = {
                "tipo_conclusao": tipo,
                "status_tratativa": status,
                "observacao": observacao,
                "protocolo": protocolo,
                "valor_solicitado": valor_solicitado,
                "valor_aprovado": valor_aprovado,
                "necessita_retorno": necessita_retorno,
                "retorno_recebido": retorno_recebido,
                "data_retorno": data_retorno,
                "precisa_verificar": precisa_verificar,
                "status_retorno": status_retorno,
            }
            save_conclusao(lcte_id, payload, usuario, painel)
            st.success("Conclusao salva. A viagem foi movida para o Banco de Dados - Concluidos.")
            st.rerun()


def _render_reopen_form(df: pd.DataFrame, usuario: str) -> None:
    if df.empty:
        return
    with st.expander("Reabertura", expanded=False):
        options = []
        for _, row in df.iterrows():
            lcte_id = int(row.get("lcte_id") or row.get("id") or 0)
            if lcte_id:
                options.append(f"{lcte_id} | CT-e {row.get('cte') or '-'} | NF {row.get('nf') or '-'} | {row.get('placa_norm') or '-'}")
        if not options:
            return
        with st.form("estadias_reabertura"):
            selected = st.selectbox("Registro concluido", options)
            destino = st.selectbox("Retornar para", ["VERIFICACAO", "ESTADIAS"])
            motivo = st.text_area("Motivo da reabertura")
            submitted = st.form_submit_button("Registrar reabertura")
        if submitted:
            lcte_id = int(str(selected).split("|", 1)[0].strip())
            reabrir_conclusao(lcte_id, usuario, destino, motivo)
            st.success("Reabertura registrada e registro movido para o painel escolhido.")
            st.rerun()


def _render_cross_diagnostic(cross: pd.DataFrame) -> None:
    st.subheader("Diagnostico da Viagem")
    options = [
        f"{row.get('id')} | {row.get('placa_norm') or '-'} | {row.get('chave_viagem') or '-'} | CT-e {row.get('cte') or '-'} | NF {row.get('nf') or '-'}"
        for _, row in cross.iterrows()
    ]
    selected = st.selectbox("Viagem", options, key="estadias_diagnostico_viagem")
    selected_id = int(str(selected).split("|", 1)[0].strip()) if selected else 0
    detail = cross[cross["id"].astype(int).eq(selected_id)].head(1)
    if detail.empty:
        return
    row = detail.iloc[0]
    metric_grid(
        {
            "Encontrou no LCTE": "SIM" if int(row.get("encontrou_lcte") or 0) else "NAO",
            "Encontrou no CONTROL": "SIM" if int(row.get("encontrou_control") or 0) else "NAO",
            "Encontrou no Rastreador": "SIM" if int(row.get("encontrou_rastreador") or 0) else "NAO",
            "Encontrou origem": "SIM" if int(row.get("encontrou_origem") or 0) else "NAO",
            "Encontrou destino": "SIM" if int(row.get("encontrou_destino") or 0) else "NAO",
            "Calculou estadia": "SIM" if int(row.get("calculou_estadia") or 0) else "NAO",
            "Maior divergencia": row.get("maior_divergencia_min") or 0,
            "Painel atual": row.get("painel_atual") or "-",
        },
        columns=4,
    )
    if str(row.get("motivo_falha") or "").strip():
        st.error(row.get("motivo_falha"))
    st.write(
        {
            "Origem": row.get("origem"),
            "Tempo na origem": _format_minutes_value(row.get("tempo_origem_min")),
            "Destino": row.get("destino"),
            "Tempo no destino": _format_minutes_value(row.get("tempo_destino_min")),
            "CONTROL chegada origem": _format_datetime_display(row.get("control_chegada_origem")),
            "Rastreador chegada origem": _format_datetime_display(row.get("chegada_origem")),
            "CONTROL saida origem": _format_datetime_display(row.get("control_saida_origem")),
            "Rastreador saida origem": _format_datetime_display(row.get("saida_origem")),
            "CONTROL chegada destino": _format_datetime_display(row.get("control_chegada_destino")),
            "Rastreador chegada destino": _format_datetime_display(row.get("chegada_destino")),
            "CONTROL saida destino": _format_datetime_display(row.get("control_saida_destino")),
            "Rastreador saida destino": _format_datetime_display(row.get("saida_destino")),
            "Eventos comparaveis": row.get("eventos_comparaveis"),
            "Eventos sem CONTROL": row.get("eventos_sem_control"),
            "Eventos sem Rastreador": row.get("eventos_sem_rastreador"),
        }
    )
    render_dataframe(_permanence_rows(detail), height=220, max_rows=2)
    with st.expander("Log detalhado de processamento", expanded=False):
        st.json(row.get("diagnostico_json") or "{}")
        st.json(row.get("log_processamento_json") or "[]")


def _render_cross_panel(panel: str, title: str, cross: pd.DataFrame, usuario: str) -> None:
    st.subheader(title)
    base = _panel_base(cross, panel)
    cards = _render_cross_cards(panel, base)
    filters = _render_cross_filters(panel, base)
    filtered = _apply_cross_filters(_apply_cross_cards(base, cards), filters)
    metric_grid(
        {
            "Registros": len(filtered),
            "Com estadia": int(_num_series(filtered, "horas_estadia").gt(0).sum()),
            "Valor estimado": round(float(_num_series(filtered, "valor_estimado_estadia").sum()), 2),
            "Maior divergencia": round(float(_num_series(filtered, "maior_divergencia_min").max() if not filtered.empty else 0), 2),
        },
        columns=4,
    )
    _render_conclusion_form(panel, filtered, usuario)
    if panel == "CONCLUIDOS":
        _render_reopen_form(filtered, usuario)
    visible_columns = _configured_columns(panel, filtered if not filtered.empty else base, usuario)
    table = _format_cross_dates(_with_estadia_display_columns(filtered))
    visible_columns = [column for column in visible_columns if column in table.columns]
    export_df = table[visible_columns] if visible_columns else table
    periodos_estadia = _estadia_period_rows(filtered)
    st.download_button(
        "Exportar painel Excel",
        dataframe_to_excel({"painel": export_df, "resultado_completo": _with_estadia_display_columns(filtered), "periodos_estadia": periodos_estadia}),
        f"estadias_{panel.lower()}.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
        disabled=filtered.empty,
    )
    st.download_button(
        "Exportar periodos de estadia",
        dataframe_to_excel({"periodos_estadia": periodos_estadia}),
        f"periodos_estadia_{panel.lower()}.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
        disabled=filtered.empty or periodos_estadia.empty,
    )
    render_dataframe(export_df, height=560, max_rows=1000)


def _duration_to_minutes(value: object) -> float | None:
    if value in [None, ""]:
        return None
    if isinstance(value, pd.Timedelta):
        return max(float(value.total_seconds() / 60), 0)
    try:
        if hasattr(value, "total_seconds"):
            return max(float(value.total_seconds() / 60), 0)
    except Exception:
        pass
    if isinstance(value, (int, float)) and not pd.isna(value):
        return max(float(value), 0)
    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none", "sem informacao", "sem informação"}:
        return None
    numeric = pd.to_numeric(pd.Series([text.replace(",", ".")]), errors="coerce").iloc[0]
    if not pd.isna(numeric):
        return max(float(numeric), 0)
    day_match = re.match(r"^\s*(\d+)\s+days?\s+(\d{1,3}):(\d{2})(?::(\d{2}))?\s*$", text, flags=re.I)
    if day_match:
        days = int(day_match.group(1))
        hours = int(day_match.group(2))
        minutes = int(day_match.group(3))
        seconds = int(day_match.group(4) or 0)
        return max(days * 1440 + hours * 60 + minutes + seconds / 60, 0)
    hhmm_match = re.match(r"^\s*(\d{1,5}):(\d{2})(?::(\d{2}))?\s*$", text)
    if hhmm_match:
        hours = int(hhmm_match.group(1))
        minutes = int(hhmm_match.group(2))
        seconds = int(hhmm_match.group(3) or 0)
        return max(hours * 60 + minutes + seconds / 60, 0)
    return None


def _format_hhmm(value: object) -> str:
    minutes_value = _duration_to_minutes(value)
    if minutes_value is None:
        return ""
    total = max(int(round(float(minutes_value))), 0)
    hours, mins = divmod(total, 60)
    return f"{hours:02d}:{mins:02d}"


def _status_estadia_from_minutes(tracker_minutes: float | None, estadia_minutes: object = None) -> tuple[str, str]:
    tracker_has = tracker_minutes is not None
    estadia_value = pd.to_numeric(pd.Series([estadia_minutes]), errors="coerce").fillna(0).iloc[0]
    if tracker_has and float(estadia_value) > 0:
        return "ESTADIA", "RASTREADOR"
    if tracker_has:
        return "SEM ESTADIA", "RASTREADOR"
    return "PENDENTE", "SEM DADOS"


def _line_diff_value(row: pd.Series, tipo: str) -> float | None:
    if tipo == "ORIGEM":
        values = [row.get("diferenca_chegada_origem_min"), row.get("diferenca_saida_origem_min")]
    else:
        values = [row.get("diferenca_chegada_destino_min"), row.get("diferenca_saida_destino_min")]
    numeric = [float(value) for value in pd.to_numeric(pd.Series(values), errors="coerce").dropna().tolist()]
    return max(numeric) if numeric else None


def _line_control_minutes(row: pd.Series, tipo: str) -> float | None:
    if tipo == "ORIGEM":
        start = pd.to_datetime(row.get("control_chegada_origem"), errors="coerce")
        end = pd.to_datetime(row.get("control_saida_origem"), errors="coerce")
    else:
        start = pd.to_datetime(row.get("control_chegada_destino"), errors="coerce")
        end = pd.to_datetime(row.get("control_saida_destino"), errors="coerce")
    if pd.isna(start) or pd.isna(end) or end < start:
        return None
    return round(float((end - start).total_seconds() / 60), 2)


def _line_tracker_minutes(row: pd.Series, tipo: str) -> float | None:
    found_col = "encontrou_origem" if tipo == "ORIGEM" else "encontrou_destino"
    time_col = "tempo_origem_min" if tipo == "ORIGEM" else "tempo_destino_min"
    if not _safe_bool_value(row.get(found_col)):
        return None
    return _duration_to_minutes(row.get(time_col))


def _line_status(row: pd.Series, tipo: str) -> str:
    if _safe_bool_value(row.get("concluido")):
        return "CONCLUIDO"
    found_col = "encontrou_origem" if tipo == "ORIGEM" else "encontrou_destino"
    stay_col = "estadia_carga_min" if tipo == "ORIGEM" else "estadia_descarga_min"
    if not _safe_bool_value(row.get(found_col)):
        return "PENDENTE"
    if float(pd.to_numeric(pd.Series([row.get(stay_col)]), errors="coerce").fillna(0).iloc[0]) > 0:
        return "ESTADIA"
    if str(row.get("painel_atual") or "").upper() == "VERIFICACAO" or _safe_bool_value(row.get("precisa_verificar")):
        return "PENDENTE"
    return "SEM ESTADIA"


def _line_reason(row: pd.Series, tipo: str, status: str, diff_value: float | None) -> str:
    if status == "CONCLUIDO":
        return "Concluido"
    found_col = "encontrou_origem" if tipo == "ORIGEM" else "encontrou_destino"
    tracker_start = row.get("chegada_origem") if tipo == "ORIGEM" else row.get("chegada_destino")
    tracker_end = row.get("saida_origem") if tipo == "ORIGEM" else row.get("saida_destino")
    failure = str(row.get("motivo_falha") or "")
    if "SEM_REGISTROS_MUNICIPIO" in failure:
        return "Sem registros no municipio"
    if not _safe_bool_value(row.get(found_col)):
        return "Origem nao localizada" if tipo == "ORIGEM" else "Destino nao localizado"
    if not str(tracker_start or "").strip():
        return "Rastreador sem chegada"
    if not str(tracker_end or "").strip():
        return "Rastreador sem saida"
    if "MULTIPLAS_PERMANENCIAS_MUNICIPIO" in failure:
        return "Multiplas permanencias"
    special_col = "regra_especial_origem" if tipo == "ORIGEM" else "regra_especial_destino"
    city_col = "municipio_operacional_origem" if tipo == "ORIGEM" else "municipio_operacional_destino"
    if _safe_bool_value(row.get(special_col)):
        city = str(row.get(city_col) or "Municipio").split("/", 1)[0]
        return f"{city} pelo municipio"
    if status == "ESTADIA":
        return "Estadia pelo rastreador"
    if "FRANQUIA_NAO_ULTRAPASSADA" in failure:
        return "Permanencia inferior a franquia"
    if "GPS" in failure.upper():
        return "GPS instavel"
    return "Sem estadia"


def _build_cross_summary_table(cross: pd.DataFrame) -> pd.DataFrame:
    columns = PANEL_DEFAULT_COLUMNS["RESUMO"] + [
        "Regra especial aplicada?",
        "Municipio operacional",
        "Metodo de localizacao",
        "Quantidade de blocos",
        "Bloco selecionado",
        "Primeiro ponto do bloco",
        "Ultimo ponto do bloco",
        "Quantidade de posicoes",
        "Referencias visitadas",
        "Saidas temporarias ignoradas",
        "Confianca do bloco",
        "Motivo da escolha",
        "Fonte Status Estadia",
        "Tempo Rastreador em minutos",
        "Tempo Control em minutos",
        "lcte_id",
        "cte",
        "nf",
        "cliente",
        "motorista",
        "data_emissao_nf",
        "data_inicio_viagem_referencia",
        "data_hora_carga",
        "painel_atual",
        "encontrou_control",
        "encontrou_rastreador",
        "concluido",
        "motivo_falha",
    ]
    if cross.empty:
        return pd.DataFrame(columns=columns)
    rows: list[dict[str, object]] = []
    for _, row in cross.iterrows():
        for (
            tipo,
            chegada_tracker,
            saida_tracker,
            tempo_tracker,
            chegada_control,
            saida_control,
            special_col,
            city_col,
            method_col,
            block_count_col,
            selected_block_col,
            references_col,
            interruptions_col,
            confidence_col,
            choice_reason_col,
            points_col,
        ) in [
            (
                "ORIGEM",
                "chegada_origem",
                "saida_origem",
                "tempo_origem_min",
                "control_chegada_origem",
                "control_saida_origem",
                "regra_especial_origem",
                "municipio_operacional_origem",
                "metodo_localizacao_origem",
                "qtd_blocos_municipio_origem",
                "bloco_selecionado_origem",
                "referencias_visitadas_origem",
                "interrupcoes_ignoradas_origem",
                "confianca_permanencia_origem_pct",
                "motivo_escolha_bloco_origem",
                "pontos_origem",
            ),
            (
                "DESTINO",
                "chegada_destino",
                "saida_destino",
                "tempo_destino_min",
                "control_chegada_destino",
                "control_saida_destino",
                "regra_especial_destino",
                "municipio_operacional_destino",
                "metodo_localizacao_destino",
                "qtd_blocos_municipio_destino",
                "bloco_selecionado_destino",
                "referencias_visitadas_destino",
                "interrupcoes_ignoradas_destino",
                "confianca_permanencia_destino_pct",
                "motivo_escolha_bloco_destino",
                "pontos_destino",
            ),
        ]:
            diff_value = _line_diff_value(row, tipo)
            status = _line_status(row, tipo)
            tracker_minutes = _line_tracker_minutes(row, tipo)
            control_minutes = _line_control_minutes(row, tipo)
            stay_minutes = row.get("estadia_carga_min") if tipo == "ORIGEM" else row.get("estadia_descarga_min")
            status_estadia, fonte_status_estadia = _status_estadia_from_minutes(tracker_minutes, stay_minutes)
            encontrou_control = _safe_int_value(row.get("encontrou_control"))
            encontrou_rastreador = _safe_int_value(row.get("encontrou_rastreador"))
            rows.append(
                {
                    "Status": status,
                    "Estadia": "Estadia" if status_estadia == "ESTADIA" else ("Sem estadia" if status_estadia == "SEM ESTADIA" else "Pendente"),
                    "Relatorio CONTROL": "OK" if encontrou_control else "FALTANDO",
                    "Relatorio Rastreador": "OK" if encontrou_rastreador else "FALTANDO",
                    "Notas": row.get("nf") or row.get("cte") or "",
                    "Data Emissao NF": _format_datetime_display(row.get("data_emissao_nf")),
                    "Placa": row.get("placa_norm") or "",
                    "Origem": row.get("origem") or "",
                    "Destino": row.get("destino") or "",
                    "Tipo": tipo,
                    "Chegada Rastreador": _format_datetime_display(row.get(chegada_tracker)),
                    "Saida Rastreador": _format_datetime_display(row.get(saida_tracker)),
                    "Tempo Rastreador": _format_hhmm(tracker_minutes),
                    "Chegada Control": _format_datetime_display(row.get(chegada_control)),
                    "Saida Control": _format_datetime_display(row.get(saida_control)),
                    "Tempo Control": _format_hhmm(control_minutes),
                    "Status Estadia": status_estadia,
                    "Diferenca": f"{int(round(diff_value))} min" if diff_value is not None else "",
                    "Motivo": _line_reason(row, tipo, status, diff_value),
                    "Concluir": "Concluir" if status in {"ESTADIA", "PENDENTE"} else "",
                    "Regra especial aplicada?": "SIM" if _safe_bool_value(row.get(special_col)) else "NAO",
                    "Municipio operacional": row.get(city_col) or "",
                    "Metodo de localizacao": row.get(method_col) or "",
                    "Quantidade de blocos": row.get(block_count_col) or 0,
                    "Bloco selecionado": row.get(selected_block_col) or "",
                    "Primeiro ponto do bloco": _format_datetime_display(row.get(chegada_tracker)),
                    "Ultimo ponto do bloco": _format_datetime_display(row.get(saida_tracker)),
                    "Quantidade de posicoes": row.get(points_col) or 0,
                    "Referencias visitadas": row.get(references_col) or "",
                    "Saidas temporarias ignoradas": row.get(interruptions_col) or 0,
                    "Confianca do bloco": row.get(confidence_col) or 0,
                    "Motivo da escolha": row.get(choice_reason_col) or "",
                    "Fonte Status Estadia": fonte_status_estadia,
                    "Tempo Rastreador em minutos": tracker_minutes,
                    "Tempo Control em minutos": control_minutes,
                    "lcte_id": _safe_int_value(row.get("lcte_id") or row.get("id")),
                    "cte": row.get("cte") or "",
                    "nf": row.get("nf") or "",
                    "cliente": row.get("cliente") or "",
                    "motorista": row.get("motorista") or "",
                    "data_emissao_nf": row.get("data_emissao_nf") or "",
                    "data_inicio_viagem_referencia": row.get("data_inicio_viagem_referencia") or row.get("data_hora_carga") or row.get("data_operacao") or "",
                    "data_hora_carga": row.get("data_hora_carga") or "",
                    "painel_atual": row.get("painel_atual") or "",
                    "encontrou_control": encontrou_control,
                    "encontrou_rastreador": encontrou_rastreador,
                    "concluido": _safe_int_value(row.get("concluido")),
                    "motivo_falha": row.get("motivo_falha") or "",
                }
            )
    return pd.DataFrame(rows, columns=columns)


def _toggle_simple_card(state_key: str, value: str) -> None:
    st.session_state[state_key] = "" if st.session_state.get(state_key) == value else value


def _clear_cross_summary_filters() -> None:
    for key in list(st.session_state):
        if str(key).startswith("estadias_resumo_") or str(key) in {"estadias_validation_card", "estadias_situation_card"}:
            del st.session_state[key]


def _apply_summary_filters(df: pd.DataFrame, filters: dict[str, object]) -> pd.DataFrame:
    filtered = df.copy()
    if filtered.empty:
        return filtered
    dates = pd.to_datetime(filtered["data_inicio_viagem_referencia"], errors="coerce")
    anos = filters.get("anos") or []
    meses = filters.get("meses") or []
    if anos:
        filtered = filtered[dates.dt.year.isin(anos)]
        dates = dates.loc[filtered.index]
    if meses:
        filtered = filtered[dates.dt.month.isin(meses)]
    text_filters = [
        ("Placa", "placa"),
        ("Notas", "nota"),
        ("Origem", "origem"),
        ("Destino", "destino"),
    ]
    exact_filters = [
        ("Tipo", "tipo"),
        ("Status", "status"),
        ("Status Estadia", "status_estadia"),
    ]
    for column, key in text_filters:
        value = str(filters.get(key) or "").strip()
        if value.upper() == "TODOS":
            value = ""
        if value:
            filtered = filtered[filtered[column].fillna("").astype(str).str.contains(value, case=False, na=False)]
    for column, key in exact_filters:
        value = str(filters.get(key) or "").strip()
        if value.upper() == "TODOS":
            value = ""
        if value:
            filtered = filtered[filtered[column].fillna("").astype(str).str.upper().eq(value.upper())]
    return filtered


def _apply_validation_card(df: pd.DataFrame, card: str) -> pd.DataFrame:
    if card == "CONTROL":
        return df[df["encontrou_control"].fillna(0).astype(int).eq(1)]
    if card == "RASTREADOR":
        return df[df["encontrou_rastreador"].fillna(0).astype(int).eq(1)]
    return df


def _apply_situation_card(df: pd.DataFrame, card: str) -> pd.DataFrame:
    if card == "ESTADIA":
        return df[df["Status Estadia"].fillna("").astype(str).eq("ESTADIA")]
    if card in {"PENDENTE", "CONCLUIDO"}:
        return df[df["Status"].fillna("").astype(str).eq(card)]
    return df


def _render_summary_filters(df: pd.DataFrame) -> dict[str, object]:
    dates = pd.to_datetime(df.get("data_inicio_viagem_referencia", pd.Series(dtype=str)), errors="coerce")
    years = sorted([int(value) for value in dates.dt.year.dropna().unique().tolist()])
    months = sorted([int(value) for value in dates.dt.month.dropna().unique().tolist()])
    col_a, col_b, col_c, col_d = st.columns(4)
    filters = {
        "meses": col_a.multiselect("Mes inicio", months, format_func=lambda value: f"{int(value):02d}", key="estadias_resumo_meses"),
        "anos": col_b.multiselect("Ano", years, key="estadias_resumo_anos"),
        "placa": col_c.text_input("Placa", key="estadias_resumo_placa"),
        "nota": col_d.text_input("Nota fiscal", key="estadias_resumo_nota"),
    }
    col_e, col_f, col_g, col_h, col_i = st.columns(5)
    filters.update(
        {
            "origem": col_e.text_input("Origem", key="estadias_resumo_origem"),
            "destino": col_f.text_input("Destino", key="estadias_resumo_destino"),
            "tipo": col_g.selectbox("Tipo", ["", "ORIGEM", "DESTINO"], key="estadias_resumo_tipo"),
            "status": col_h.selectbox("Status", ["", "ESTADIA", "PENDENTE", "CONCLUIDO", "SEM ESTADIA"], key="estadias_resumo_status"),
            "status_estadia": col_i.selectbox("Status Estadia", ["Todos", "ESTADIA", "SEM ESTADIA", "PENDENTE"], key="estadias_resumo_status_estadia"),
        }
    )
    return filters


def _render_validation_cards(df: pd.DataFrame) -> str:
    active = str(st.session_state.get("estadias_validation_card") or "")
    unique = df.drop_duplicates("lcte_id") if "lcte_id" in df.columns else df
    cards = [
        ("LCTE", "Viagens no LCTE", len(unique)),
        ("CONTROL", "Relacionadas ao Control", int(unique["encontrou_control"].fillna(0).astype(int).eq(1).sum()) if not unique.empty else 0),
        ("RASTREADOR", "Com registro no Rastreador", int(unique["encontrou_rastreador"].fillna(0).astype(int).eq(1).sum()) if not unique.empty else 0),
    ]
    cols = st.columns(3)
    for idx, (key, label, count) in enumerate(cards):
        cols[idx].button(
            f"{label}\n{count}",
            key=f"estadias_validation_{key}",
            type="primary" if active == key else "secondary",
            use_container_width=True,
            on_click=_toggle_simple_card,
            args=("estadias_validation_card", key),
        )
    return active


def _render_situation_cards(df: pd.DataFrame) -> str:
    active = str(st.session_state.get("estadias_situation_card") or "")
    cards = [
        ("ESTADIA", "ESTADIAS", int(df["Status Estadia"].fillna("").astype(str).eq("ESTADIA").sum()) if not df.empty else 0),
        ("PENDENTE", "PENDENTES", int(df["Status"].fillna("").astype(str).eq("PENDENTE").sum()) if not df.empty else 0),
        ("CONCLUIDO", "CONCLUIDOS", int(df["Status"].fillna("").astype(str).eq("CONCLUIDO").sum()) if not df.empty else 0),
    ]
    cols = st.columns(3)
    for idx, (key, label, count) in enumerate(cards):
        cols[idx].button(
            f"{label}\n{count}",
            key=f"estadias_situation_{key}",
            type="primary" if active == key else "secondary",
            use_container_width=True,
            on_click=_toggle_simple_card,
            args=("estadias_situation_card", key),
        )
    return active


def _render_quick_conclusion(summary: pd.DataFrame, usuario: str) -> None:
    pending = summary[summary["Concluir"].fillna("").astype(str).ne("")].drop_duplicates("lcte_id") if not summary.empty else summary
    if pending.empty:
        return
    with st.expander("Concluir registro", expanded=False):
        options = [
            f"{int(row.get('lcte_id') or 0)} | Nota {row.get('Notas') or '-'} | {row.get('Placa') or '-'} | {row.get('Origem') or '-'} > {row.get('Destino') or '-'}"
            for _, row in pending.iterrows()
        ]
        with st.form("estadias_resumo_concluir"):
            selected = st.selectbox("Registro", options)
            tipo = st.selectbox("Tipo de conclusao", ["Cobrar estadia", "Nao cobrar", "Ajuste operacional", "Duplicidade", "Outro"])
            observacao = st.text_area("Observacao")
            col_a, col_b = st.columns(2)
            precisa_retorno = col_a.checkbox("Precisa de retorno?", value=True)
            protocolo = col_b.text_input("Protocolo")
            submitted = st.form_submit_button("Concluir", type="primary")
        if submitted:
            lcte_id = int(str(selected).split("|", 1)[0].strip())
            save_conclusao(
                lcte_id,
                {
                    "tipo_conclusao": tipo,
                    "status_tratativa": "Concluido",
                    "observacao": observacao,
                    "protocolo": protocolo,
                    "necessita_retorno": precisa_retorno,
                    "retorno_recebido": False,
                },
                usuario,
                "CRUZAMENTO_RESUMIDO",
            )
            st.success("Registro concluido e movido para Concluidos.")
            st.rerun()


def _render_summary_detail(summary: pd.DataFrame, cross: pd.DataFrame) -> None:
    if summary.empty:
        return
    with st.expander("Detalhamento da linha", expanded=False):
        options = [
            f"{int(row.get('lcte_id') or 0)} | {row.get('Tipo') or '-'} | Nota {row.get('Notas') or '-'} | {row.get('Placa') or '-'}"
            for _, row in summary.head(1000).iterrows()
        ]
        selected = st.selectbox("Linha", options, key="estadias_resumo_detalhe")
        lcte_id = int(str(selected).split("|", 1)[0].strip()) if selected else 0
        detail = cross[cross["lcte_id"].fillna(0).astype(int).eq(lcte_id)].head(1) if "lcte_id" in cross.columns else pd.DataFrame()
        if detail.empty:
            st.info("Detalhe nao localizado para esta linha.")
            return
        row = detail.iloc[0]
        st.write(
            {
                "CT-e": row.get("cte"),
                "NF": row.get("nf"),
                "Motorista": row.get("motorista"),
                "Cliente": row.get("cliente"),
                "Data emissao LCTE": _format_datetime_display(row.get("data_hora_carga") or row.get("data_operacao")),
                "Origem": row.get("origem"),
                "Destino": row.get("destino"),
                "Pontos GPS origem": row.get("pontos_origem"),
                "Pontos GPS destino": row.get("pontos_destino"),
                "Raio/tolerancia": row.get("tolerancia_control_rastreador_min"),
                "Conclusao": row.get("tipo_conclusao"),
                "Observacao": row.get("observacao_conclusao"),
            }
        )
        st.json(row.get("diagnostico_json") or "{}")
        st.json(row.get("log_processamento_json") or "[]")


def render_cross_page(usuario: str) -> None:
    col_title, col_plate, col_update = st.columns([2.2, 1.2, 1])
    col_title.title("CRUZAMENTO LCTE x CONTROL x RASTREADOR")
    lcte_count = table_count(LCTE_NORMALIZED_TABLE)
    rastreador_count = table_count(RASTREADOR_NORMALIZED_TABLE)
    cross_count = table_count(CROSS_TABLE)
    plate_options = ["TODAS", *select_distinct(LCTE_NORMALIZED_TABLE, "placa_norm", 3000)]
    plate_update = col_plate.selectbox("Atualizar placa", plate_options, key="estadias_cross_update_placa")
    selected_plate = "" if plate_update == "TODAS" else str(plate_update or "").strip()
    button_label = "RECALCULAR PLACA" if selected_plate else "RECALCULAR REGRAS"
    can_recalculate = bool(lcte_count and rastreador_count)
    if not can_recalculate and cross_count:
        missing = []
        if not lcte_count:
            missing.append("LCTE")
        if not rastreador_count:
            missing.append("RASTREADOR")
        st.warning(
            "Existe resultado importado por JSON, mas nao ha base suficiente para recalcular com as regras atuais. "
            f"Reimporte {' e '.join(missing)} para liberar o botao de recalculo."
        )
    if col_update.button(
        button_label,
        type="primary",
        use_container_width=True,
        disabled=not can_recalculate,
        help="Reprocessa o cruzamento usando LCTE como base e rastreador como permanencia. O JSON de resultado sozinho nao contem as posicoes do rastreador.",
    ):
        progress_bar = st.progress(0)
        progress_text = st.empty()

        def update_progress(current: int, total: int, message: str) -> None:
            pct = max(0, min(100, int(round((current / max(total, 1)) * 100))))
            progress_bar.progress(pct)
            progress_text.caption(f"{pct}% - {message}")

        update_progress(0, 100, "Iniciando atualizacao...")
        cross_updated, resumo = atualizar_cruzamento_incremental(usuario, update_progress, selected_plate)
        progress_bar.progress(100)
        progress_text.caption("100% - Atualizacao concluida.")
        scope = f"Placa {selected_plate}: " if selected_plate else ""
        st.success(
            f"{scope}Atualizacao concluida: "
            f"{resumo['registros_novos']} registros novos, "
            f"{resumo['estadias_identificadas']} estadias, "
            f"{resumo['pendencias']} pendencias, "
            f"{resumo['registros_atualizados']} registros atualizados, "
            f"{resumo['concluidos_preservados']} concluidos preservados e "
            f"{resumo['erros']} erros."
        )
        cross = cross_updated
    else:
        cross = read_cross(200000)

    summary = _build_cross_summary_table(cross)
    session_filters = {
        "meses": st.session_state.get("estadias_resumo_meses", []),
        "anos": st.session_state.get("estadias_resumo_anos", []),
        "placa": st.session_state.get("estadias_resumo_placa", ""),
        "nota": st.session_state.get("estadias_resumo_nota", ""),
        "origem": st.session_state.get("estadias_resumo_origem", ""),
        "destino": st.session_state.get("estadias_resumo_destino", ""),
        "tipo": st.session_state.get("estadias_resumo_tipo", ""),
        "status": st.session_state.get("estadias_resumo_status", ""),
        "status_estadia": st.session_state.get("estadias_resumo_status_estadia", ""),
    }
    filtered_by_fields = _apply_summary_filters(summary, session_filters)

    validation_card = _render_validation_cards(filtered_by_fields)
    filtered_by_validation = _apply_validation_card(filtered_by_fields, validation_card)
    situation_card = _render_situation_cards(filtered_by_validation)

    filters = _render_summary_filters(summary)
    filtered = _apply_summary_filters(summary, filters)
    filtered = _apply_validation_card(filtered, validation_card)
    filtered = _apply_situation_card(filtered, situation_card)

    col_a, col_b, col_c, col_d = st.columns([2, 1, 1, 1])
    with col_a:
        visible_columns = _configured_columns("RESUMO", filtered if not filtered.empty else summary, usuario)
    table = filtered[[column for column in visible_columns if column in filtered.columns]] if not filtered.empty else filtered
    col_b.download_button(
        "Exportar visualizacao",
        dataframe_to_excel({"visualizacao": table}),
        "cruzamento_estadias_visualizacao.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
        disabled=table.empty,
    )
    col_c.download_button(
        "Exportar completo",
        dataframe_to_excel({"visualizacao": table, "completo": filtered, "detalhamento_viagem": _with_estadia_display_columns(cross)}),
        "cruzamento_estadias_completo.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
        disabled=filtered.empty,
    )
    col_d.button("Limpar filtros", use_container_width=True, on_click=_clear_cross_summary_filters)

    filtered_ids = set(pd.to_numeric(filtered.get("lcte_id", pd.Series(dtype=int)), errors="coerce").dropna().astype(int).tolist()) if not filtered.empty else set()
    pdf_base = cross[pd.to_numeric(cross.get("lcte_id", pd.Series(dtype=int)), errors="coerce").fillna(0).astype(int).isin(filtered_ids)].copy() if filtered_ids and "lcte_id" in cross.columns else pd.DataFrame()
    pdf_specs = _estadia_period_specs(pdf_base)
    if pdf_specs:
        with st.expander("PDF de posicoes do rastreador", expanded=True):
            pdf_options = _estadia_pdf_options_frame(pdf_specs)
            edited_pdf_options = st.data_editor(
                pdf_options,
                hide_index=True,
                use_container_width=True,
                height=min(420, 70 + (len(pdf_options) + 1) * 36),
                num_rows="fixed",
                column_config={
                    "Exportar PDF": st.column_config.CheckboxColumn("Exportar PDF", default=False),
                    "Linha": st.column_config.NumberColumn("Linha", disabled=True),
                },
                disabled=[column for column in pdf_options.columns if column != "Exportar PDF"],
                key="estadias_pdf_periodos_flags",
            )
            pdf_selected = (
                edited_pdf_options.loc[edited_pdf_options["Exportar PDF"].fillna(False), "Linha"]
                .astype(int)
                .sub(1)
                .tolist()
            )
            multiple_pdfs = len(pdf_selected) > 1
            download_stamp = re.sub(r"\D+", "", brasilia_now_iso())[:14] or "atual"
            if multiple_pdfs:
                download_bytes = _tracker_positions_pdf_zip(pdf_base, pdf_selected)
                download_name = f"relatorios_posicoes_rastreador_{download_stamp}.zip"
                mime_type = "application/zip"
                button_label = "Baixar PDFs selecionados"
            else:
                download_bytes = _tracker_positions_pdf(pdf_base, pdf_selected) if pdf_selected else b""
                download_name = f"relatorio_posicoes_rastreador_{download_stamp}.pdf"
                mime_type = "application/pdf"
                button_label = "Baixar PDF selecionado"
            st.download_button(
                button_label,
                download_bytes,
                download_name,
                mime_type,
                use_container_width=True,
                disabled=not pdf_selected,
            )
    else:
        st.info("Nenhuma estadia filtrada possui periodo valido para gerar PDF de posicoes.")

    render_dataframe(table, height=620, max_rows=2000)
    _render_quick_conclusion(filtered, usuario)
    _render_summary_detail(filtered, cross)
    return

    metric_grid(
        {
            "Viagens processadas": len(cross),
            "Com estadia": int(pd.to_numeric(cross.get("horas_estadia", pd.Series(dtype=float)), errors="coerce").fillna(0).gt(0).sum()),
            "Sem estadia": int(pd.to_numeric(cross.get("horas_estadia", pd.Series(dtype=float)), errors="coerce").fillna(0).le(0).sum()),
            "Sem CONTROL": int(cross["encontrou_control"].fillna(0).astype(int).ne(1).sum()),
            "Sem Rastreador": int(cross["encontrou_rastreador"].fillna(0).astype(int).ne(1).sum()),
            "Falha origem/destino": int((cross["encontrou_origem"].fillna(0).astype(int).ne(1) | cross["encontrou_destino"].fillna(0).astype(int).ne(1)).sum()),
        },
        columns=6,
    )

    st.subheader("Diagnostico da Viagem")
    options = [
        f"{row.get('id')} | {row.get('placa_norm') or '-'} | {row.get('chave_viagem') or '-'} | CT-e {row.get('cte') or '-'} | NF {row.get('nf') or '-'}"
        for _, row in cross.iterrows()
    ]
    selected = st.selectbox("Viagem", options, key="estadias_diagnostico_viagem")
    selected_id = int(str(selected).split("|", 1)[0].strip()) if selected else 0
    detail = cross[cross["id"].astype(int).eq(selected_id)].head(1)
    if not detail.empty:
        row = detail.iloc[0]
        metric_grid(
            {
                "Encontrou no LCTE": "SIM" if int(row.get("encontrou_lcte") or 0) else "NAO",
                "Encontrou no CONTROL": "SIM" if int(row.get("encontrou_control") or 0) else "NAO",
                "Encontrou no Rastreador": "SIM" if int(row.get("encontrou_rastreador") or 0) else "NAO",
                "Encontrou origem": "SIM" if int(row.get("encontrou_origem") or 0) else "NAO",
                "Encontrou destino": "SIM" if int(row.get("encontrou_destino") or 0) else "NAO",
                "Calculou estadia": "SIM" if int(row.get("calculou_estadia") or 0) else "NAO",
                "Pontuacao CONTROL": row.get("pontuacao_control") or 0,
                "Elegivel": "SIM" if int(row.get("elegivel_cobranca") or 0) else "NAO",
            },
            columns=4,
        )
        if str(row.get("motivo_falha") or "").strip():
            st.error(row.get("motivo_falha"))
        st.write(
            {
                "Tipo ponto origem": "ORIGEM",
                "Local origem": row.get("origem"),
                "Tempo na origem (min)": row.get("tempo_origem_min"),
                "Tempo na origem": _format_minutes_value(row.get("tempo_origem_min")),
                "Tipo ponto destino": "DESTINO",
                "Local destino": row.get("destino"),
                "Tempo no destino (min)": row.get("tempo_destino_min"),
                "Tempo no destino": _format_minutes_value(row.get("tempo_destino_min")),
                "Franquia carga (min)": row.get("franquia_carga_min"),
                "Franquia descarga (min)": row.get("franquia_descarga_min"),
                "Estadia carga apos franquia (min)": row.get("estadia_carga_min"),
                "Estadia descarga apos franquia (min)": row.get("estadia_descarga_min"),
                "Horas de estadia": row.get("horas_estadia"),
                "Valor estimado": row.get("valor_estimado_estadia"),
                "Tempo Operacional (min)": row.get("tempo_operacional_min"),
                "Tempo em Transito (min)": row.get("tempo_transito_min"),
                "Tempo Total da Viagem (min)": row.get("tempo_total_viagem_min"),
                "Tempo CONTROL (min)": row.get("tempo_control_min"),
                "Tempo Rastreador (min)": row.get("tempo_rastreador_min"),
                "Diferenca CONTROL x Rastreador (min)": row.get("diferenca_control_rastreador_min"),
                "Km percorrido": row.get("km_percorrido"),
                "Distancia ponto carga km": row.get("distancia_ponto_carga_km"),
                "Distancia ponto descarga km": row.get("distancia_ponto_descarga_km"),
            }
        )
        st.subheader("Permanencia por origem/destino")
        render_dataframe(_permanence_rows(detail), height=220, max_rows=2)
        with st.expander("Log detalhado de processamento", expanded=False):
            st.json(row.get("diagnostico_json") or "{}")
            st.json(row.get("log_processamento_json") or "[]")

    filtered = _filter_results(cross)
    st.download_button(
        "Exportar resultado Excel",
        dataframe_to_excel(_export_sheets(filtered)),
        "diagnostico_estadias.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
        disabled=filtered.empty,
    )
    render_dataframe(_with_estadia_display_columns(filtered), height=560, max_rows=1000)


def _toggle_estadias_teste_card(card_key: str) -> None:
    cards = dict(st.session_state.get("estadias_teste_cards_ativos", {}))
    definition = CARD_DEFINITIONS.get(card_key, {})
    group = str(definition.get("group") or card_key)
    if cards.get(group) == card_key:
        cards.pop(group, None)
    else:
        cards[group] = card_key
    st.session_state.estadias_teste_cards_ativos = cards


def _clear_estadias_teste_cards() -> None:
    st.session_state.estadias_teste_cards_ativos = {}


def _clear_estadias_teste_all_filters() -> None:
    st.session_state.estadias_teste_cards_ativos = {}
    for key, value in {
        "estadias_teste_lcte_rastreador_placa": DEFAULT_TEST_PLATE,
        "estadias_teste_cte": "",
        "estadias_teste_nf": "",
        "estadias_teste_origem": "",
        "estadias_teste_destino": "",
        "estadias_teste_cliente": "",
        "estadias_teste_motorista": "",
        "estadias_teste_status": "",
        "estadias_teste_possivel_estadia": "",
        "estadias_teste_tipo_data": "Por mes",
        "estadias_teste_periodo_inicio": "",
        "estadias_teste_periodo_fim": "",
    }.items():
        st.session_state[key] = value
    st.session_state.pop("estadias_teste_anos", None)
    st.session_state.pop("estadias_teste_meses", None)
    st.session_state.pop("estadias_teste_lcte_rastreador_result", None)


def _select_all_estadias_teste_months(month_options: list[str]) -> None:
    st.session_state.estadias_teste_meses = list(month_options)


def _clear_estadias_teste_months() -> None:
    st.session_state.estadias_teste_meses = []


def _remove_estadias_teste_filter(kind: str, value: str = "") -> None:
    if kind == "card":
        cards = dict(st.session_state.get("estadias_teste_cards_ativos", {}))
        cards.pop(value, None)
        st.session_state.estadias_teste_cards_ativos = cards
    elif kind == "field":
        st.session_state[value] = ""
    elif kind == "date":
        st.session_state.estadias_teste_tipo_data = "Por mes"
        st.session_state.estadias_teste_meses = []
        st.session_state.estadias_teste_periodo_inicio = ""
        st.session_state.estadias_teste_periodo_fim = ""
    elif kind == "all_cards":
        _clear_estadias_teste_cards()


def _render_teste_active_filters(filters: dict[str, object]) -> None:
    active: list[tuple[str, str, str]] = []
    if filters.get("tipo_data") == "Periodo personalizado":
        active.append(("Periodo", f"{filters.get('periodo_inicio') or '-'} ate {filters.get('periodo_fim') or '-'}", "date"))
    elif filters.get("meses"):
        labels = ", ".join(month_label(str(month)) for month in filters.get("meses", []))
        active.append(("Mes", labels, "date"))
    if filters.get("placa"):
        active.append(("Placa", str(filters.get("placa")), "field:estadias_teste_lcte_rastreador_placa"))
    for label, key in [
        ("CT-e", "estadias_teste_cte"),
        ("NF", "estadias_teste_nf"),
        ("Origem", "estadias_teste_origem"),
        ("Destino", "estadias_teste_destino"),
        ("Cliente", "estadias_teste_cliente"),
        ("Motorista", "estadias_teste_motorista"),
        ("Status", "estadias_teste_status"),
        ("Possivel estadia", "estadias_teste_possivel_estadia"),
    ]:
        value = st.session_state.get(key)
        if value:
            active.append((label, str(value), f"field:{key}"))
    for group, card_key in (filters.get("cards") or {}).items():
        definition = CARD_DEFINITIONS.get(str(card_key))
        if definition:
            active.append(("Card", definition["label"], f"card:{group}"))
    st.subheader("FILTROS ATIVOS")
    if not active:
        st.caption("Nenhum filtro ativo alem do contexto inicial.")
        return
    cols = st.columns(min(len(active), 4))
    for index, (label, value, token) in enumerate(active):
        with cols[index % len(cols)]:
            st.caption(f"{label}: {value}")
            kind, _, payload = token.partition(":")
            st.button("Remover", key=f"estadias_teste_remove_{index}_{kind}_{payload}", on_click=_remove_estadias_teste_filter, args=(kind, payload), use_container_width=True)


def _render_teste_cards(counts: dict[str, int], active_cards: dict[str, str]) -> None:
    st.subheader("Cards interativos")
    rows = [
        ["viagens_lcte", "com_rastreador", "sem_rastreador", "control_completo"],
        ["control_incompleto", "sem_control", "origem_identificada", "destino_identificada"],
        ["permanencia_gps", "possivel_estadia", "nao_calculadas", "inconsistencias"],
    ]
    for row in rows:
        cols = st.columns(len(row))
        for col, card_key in zip(cols, row):
            definition = CARD_DEFINITIONS[card_key]
            active = active_cards.get(definition["group"]) == card_key
            border = "#2563eb" if active else "#d1d5db"
            background = "#eff6ff" if active else "#ffffff"
            badge = "FILTRO ATIVO" if active else "Clique para filtrar"
            col.markdown(
                f"""
                <div style="border:2px solid {border};background:{background};border-radius:8px;padding:10px 12px;margin-bottom:6px;min-height:86px;">
                    <div style="font-size:12px;color:#475569;font-weight:700;">{badge}</div>
                    <div style="font-size:14px;color:#111827;font-weight:700;">{definition['label']}</div>
                    <div style="font-size:26px;color:#111827;font-weight:800;line-height:1.2;">{counts.get(card_key, 0)}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            label = f"{'[ATIVO] ' if active else ''}{definition['label']}\n{counts.get(card_key, 0)}"
            help_text = "Filtro ativo - clique novamente para remover" if active else "Clique para filtrar"
            col.button(label, key=f"estadias_teste_card_{card_key}", on_click=_toggle_estadias_teste_card, args=(card_key,), help=help_text, use_container_width=True)


def _filters_export_df(usuario: str, filters: dict[str, object], total_rows: int) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Filtro": "data_hora_exportacao", "Valor": brasilia_now_iso()},
            {"Filtro": "usuario", "Valor": usuario},
            {"Filtro": "tipo_data", "Valor": filters.get("tipo_data") or ""},
            {"Filtro": "anos", "Valor": ", ".join(map(str, filters.get("anos") or []))},
            {"Filtro": "meses", "Valor": ", ".join(month_label(str(month)) for month in filters.get("meses", []))},
            {"Filtro": "periodo_inicio", "Valor": filters.get("periodo_inicio") or ""},
            {"Filtro": "periodo_fim", "Valor": filters.get("periodo_fim") or ""},
            {"Filtro": "placa", "Valor": filters.get("placa") or ""},
            {"Filtro": "cards", "Valor": ", ".join(active_card_labels(filters.get("cards") or {}))},
            {"Filtro": "cte", "Valor": filters.get("cte") or ""},
            {"Filtro": "nf", "Valor": filters.get("nf") or ""},
            {"Filtro": "origem", "Valor": filters.get("origem") or ""},
            {"Filtro": "destino", "Valor": filters.get("destino") or ""},
            {"Filtro": "cliente", "Valor": filters.get("cliente") or ""},
            {"Filtro": "motorista", "Valor": filters.get("motorista") or ""},
            {"Filtro": "status", "Valor": filters.get("status") or ""},
            {"Filtro": "possivel_estadia", "Valor": filters.get("possivel_estadia") or ""},
            {"Filtro": "quantidade_registros", "Valor": total_rows},
        ]
    )


def render_teste_lcte_rastreador_page(usuario: str = "sistema") -> None:
    st.title("TESTE LCTE x RASTREADOR")
    st.caption("Painel de teste isolado: LCTE define a viagem, Rastreador calcula permanencias por GPS e CONTROL aparece apenas para auditoria.")
    st.session_state.setdefault("estadias_teste_lcte_rastreador_placa", DEFAULT_TEST_PLATE)
    st.session_state.setdefault("estadias_teste_cards_ativos", {})
    st.session_state.setdefault("estadias_teste_tipo_data", "Por mes")

    with st.expander("Parametros do teste", expanded=True):
        col_a, col_b, col_c, col_d = st.columns(4)
        placa = col_a.text_input("Placa", key="estadias_teste_lcte_rastreador_placa")
        limite_viagens = int(col_d.number_input("Limite de viagens", min_value=1, max_value=50000, value=5000, step=100, key="estadias_teste_limite"))
        col_e, col_f, col_g, col_h = st.columns(4)
        janela_antes = float(col_e.number_input("Inicio janela: horas antes LCTE", min_value=0.0, max_value=240.0, value=24.0, step=1.0, key="estadias_teste_janela_antes"))
        janela_depois = float(col_f.number_input("Fim janela: dias apos LCTE", min_value=1.0, max_value=30.0, value=7.0, step=1.0, key="estadias_teste_janela_depois"))
        raio_metros = float(col_g.number_input("Raio ponto GPS (m)", min_value=50.0, max_value=10000.0, value=1000.0, step=50.0, key="estadias_teste_raio"))
        extra_metros = float(col_h.number_input("Margem raio (m)", min_value=0.0, max_value=5000.0, value=300.0, step=50.0, key="estadias_teste_extra_raio"))
        col_i, col_j, col_k, col_l = st.columns(4)
        tolerancia_sinal = float(col_i.number_input("Tolerancia sem sinal (min)", min_value=1.0, max_value=1440.0, value=30.0, step=5.0, key="estadias_teste_tolerancia_sinal"))
        tolerancia_saida = float(col_j.number_input("Tolerancia fora do ponto (min)", min_value=0.0, max_value=1440.0, value=15.0, step=5.0, key="estadias_teste_tolerancia_saida"))
        min_pontos = int(col_k.number_input("Minimo pontos permanencia", min_value=1, max_value=20, value=1, step=1, key="estadias_teste_min_pontos"))
        tempo_minimo = float(col_l.number_input("Tempo minimo parado (min)", min_value=0.0, max_value=1440.0, value=30.0, step=5.0, key="estadias_teste_tempo_minimo"))
        col_m, col_n = st.columns(2)
        franquia_horas = float(col_m.number_input("Franquia para possivel estadia (h)", min_value=0.0, max_value=240.0, value=24.0, step=1.0, key="estadias_teste_franquia"))
        limitar_proxima = col_n.checkbox("Limitar janela pela proxima viagem LCTE da mesma placa", value=True, key="estadias_teste_limitar_proxima")

    process_signature = {
        "placa": placa,
        "limite_viagens": limite_viagens,
        "janela_antes": janela_antes,
        "janela_depois": janela_depois,
        "raio_metros": raio_metros,
        "extra_metros": extra_metros,
        "tolerancia_sinal": tolerancia_sinal,
        "tolerancia_saida": tolerancia_saida,
        "min_pontos": min_pontos,
        "tempo_minimo": tempo_minimo,
        "franquia_horas": franquia_horas,
        "limitar_proxima": limitar_proxima,
    }
    processar = st.button("Processar teste LCTE x Rastreador", type="primary", use_container_width=True)
    if processar or "estadias_teste_lcte_rastreador_result" not in st.session_state or st.session_state.get("estadias_teste_process_signature") != process_signature:
        with st.spinner("Processando teste com LCTE como base mestre e Rastreador como fonte de permanencia..."):
            result, summary, diagnostic, timeline = build_teste_lcte_rastreador(
                placa=placa,
                janela_antes_horas=janela_antes,
                janela_depois_dias=janela_depois,
                raio_metros=raio_metros,
                tolerancia_raio_extra_metros=extra_metros,
                tolerancia_sem_sinal_minutos=tolerancia_sinal,
                tolerancia_fora_cerca_minutos=tolerancia_saida,
                min_pontos_permanencia=min_pontos,
                tempo_minimo_parado_minutos=tempo_minimo,
                franquia_horas=franquia_horas,
                limitar_proxima_viagem=limitar_proxima,
                limite_viagens=limite_viagens,
            )
        st.session_state.estadias_teste_lcte_rastreador_result = result
        st.session_state.estadias_teste_lcte_rastreador_summary = summary
        st.session_state.estadias_teste_lcte_rastreador_diagnostic = diagnostic
        st.session_state.estadias_teste_lcte_rastreador_timeline = timeline
        st.session_state.estadias_teste_process_signature = process_signature

    result = ensure_panel_filter_columns(st.session_state.get("estadias_teste_lcte_rastreador_result", pd.DataFrame()))
    diagnostic = st.session_state.get("estadias_teste_lcte_rastreador_diagnostic", pd.DataFrame())
    timeline = st.session_state.get("estadias_teste_lcte_rastreador_timeline", pd.DataFrame())
    if not isinstance(result, pd.DataFrame) or result.empty:
        st.info("Informe a placa e processe o teste. O padrao inicial e AIW8A04.")
        return

    years = available_years(result)
    latest_month = latest_month_with_data(result)
    latest_year = int(latest_month[:4]) if latest_month else (years[-1] if years else 0)
    if "estadias_teste_anos" not in st.session_state:
        st.session_state.estadias_teste_anos = [latest_year] if latest_year else years
    if "estadias_teste_meses" not in st.session_state:
        st.session_state.estadias_teste_meses = [latest_month] if latest_month else []

    st.subheader("Filtro de data pelo inicio da viagem")
    col_data_a, col_data_b, col_data_c, col_data_d = st.columns(4)
    tipo_data = col_data_a.selectbox("TIPO DE FILTRO DE DATA", ["Por mes", "Periodo personalizado"], key="estadias_teste_tipo_data")
    anos = col_data_b.multiselect("ANO DE INICIO DA VIAGEM", years, key="estadias_teste_anos")
    month_options = available_months(result, anos)
    month_label_map = {month: month_label(month) for month in month_options}
    if tipo_data == "Por mes":
        st.session_state.estadias_teste_meses = [month for month in st.session_state.get("estadias_teste_meses", []) if month in month_options]
        btn_month_a, btn_month_b = st.columns(2)
        btn_month_a.button("Selecionar todos os meses", key="estadias_teste_select_all_months", on_click=_select_all_estadias_teste_months, args=(month_options,), use_container_width=True)
        btn_month_b.button("Limpar meses", key="estadias_teste_clear_months", on_click=_clear_estadias_teste_months, use_container_width=True)
        meses = col_data_c.multiselect(
            "MES DE INICIO DA VIAGEM",
            month_options,
            format_func=lambda value: month_label_map.get(value, value),
            key="estadias_teste_meses",
        )
        col_data_d.caption(f"Mes ativo: {', '.join(month_label(month) for month in meses) if meses else 'Todos'}")
        periodo_inicio = ""
        periodo_fim = ""
    else:
        meses = []
        periodo_inicio = col_data_c.text_input("Data inicial", key="estadias_teste_periodo_inicio", placeholder="dd/mm/aaaa")
        periodo_fim = col_data_d.text_input("Data final", key="estadias_teste_periodo_fim", placeholder="dd/mm/aaaa")
        st.info("Periodo personalizado ativo: o filtro mensal fica substituido por data inicial/final.")

    st.subheader("Filtros de texto")
    col_a, col_b, col_c, col_d = st.columns(4)
    status_options = ["", *sorted(result.get("Status", pd.Series(dtype=str)).fillna("").astype(str).unique().tolist())]
    status = col_a.selectbox("Status", status_options, key="estadias_teste_status")
    origem = col_b.text_input("Origem contem", key="estadias_teste_origem")
    destino = col_c.text_input("Destino contem", key="estadias_teste_destino")
    possivel_estadia = col_d.selectbox("Possivel estadia", ["", "SIM", "NAO"], key="estadias_teste_possivel_estadia")
    col_e, col_f, col_g, col_h = st.columns(4)
    cliente = col_e.text_input("Cliente contem", key="estadias_teste_cliente")
    motorista = col_f.text_input("Motorista contem", key="estadias_teste_motorista")
    cte = col_g.text_input("CT-e contem", key="estadias_teste_cte")
    nf = col_h.text_input("NF contem", key="estadias_teste_nf")

    filters = {
        "tipo_data": tipo_data,
        "anos": anos,
        "meses": meses,
        "periodo_inicio": periodo_inicio,
        "periodo_fim": periodo_fim,
        "placa": placa,
        "cte": cte,
        "nf": nf,
        "origem": origem,
        "destino": destino,
        "cliente": cliente,
        "motorista": motorista,
        "status": status,
        "possivel_estadia": possivel_estadia,
        "cards": dict(st.session_state.get("estadias_teste_cards_ativos", {})),
    }

    base_sem_cards = aplicar_filtros_painel_estadias(result, filters, include_card_filters=False)
    counts = card_counts(result, filters)
    _render_teste_cards(counts, filters["cards"])
    col_clear_a, col_clear_b = st.columns(2)
    col_clear_a.button("LIMPAR FILTROS DOS CARDS", on_click=_clear_estadias_teste_cards, use_container_width=True)
    col_clear_b.button("LIMPAR TODOS OS FILTROS", on_click=_clear_estadias_teste_all_filters, use_container_width=True)
    _render_teste_active_filters(filters)
    filtered = aplicar_filtros_painel_estadias(result, filters, include_card_filters=True)

    all_columns = filtered.columns.tolist()
    default_columns = [column for column in DEFAULT_VISIBLE_COLUMNS if column in all_columns]
    if "estadias_teste_colunas_visiveis" in st.session_state:
        st.session_state.estadias_teste_colunas_visiveis = [column for column in st.session_state.estadias_teste_colunas_visiveis if column in all_columns]
    selected_columns = st.multiselect(
        "Colunas visiveis",
        all_columns,
        default=st.session_state.get("estadias_teste_colunas_visiveis", default_columns),
        key="estadias_teste_colunas_visiveis",
    )
    if not selected_columns:
        selected_columns = default_columns

    filtered_diagnostic = diagnostic[diagnostic["lcte_id"].isin(filtered["lcte_id"])] if isinstance(diagnostic, pd.DataFrame) and not diagnostic.empty and not filtered.empty else diagnostic
    filtered_timeline = timeline[timeline["lcte_id"].isin(filtered["lcte_id"])] if isinstance(timeline, pd.DataFrame) and not timeline.empty and not filtered.empty else timeline
    export_filters = _filters_export_df(usuario, filters, len(filtered))
    col_a, col_b = st.columns(2)
    col_a.download_button(
        "Exportar visao atual",
        dataframe_to_excel({"visao_atual": filtered[selected_columns], "FILTROS APLICADOS": export_filters}),
        "teste_lcte_rastreador_visao.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
        disabled=filtered.empty,
    )
    col_b.download_button(
        "Exportar diagnostico completo",
        dataframe_to_excel({**export_teste_lcte_rastreador_sheets(filtered, filtered_diagnostic, filtered_timeline), "FILTROS APLICADOS": export_filters}),
        "teste_lcte_rastreador_diagnostico.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
        disabled=filtered.empty,
    )

    st.write(f"REGISTROS EXIBIDOS: {len(filtered)} DE {len(base_sem_cards)}")
    render_dataframe(filtered[selected_columns], height=540, max_rows=1000)
    if filtered.empty:
        st.warning("Nenhuma viagem encontrada para a combinacao atual de filtros.")
        return

    st.subheader("Diagnostico da viagem")
    options = [
        f"{row.get('lcte_id')} | {row.get('Placa') or '-'} | CT-e {row.get('CT-e') or '-'} | NF {row.get('NF') or '-'} | {row.get('Status') or '-'}"
        for _, row in filtered.iterrows()
    ]
    selected = st.selectbox("Viagem", options, key="estadias_teste_viagem_detalhe")
    selected_id = int(str(selected).split("|", 1)[0].strip()) if selected else 0
    detail = filtered[filtered["lcte_id"].astype(int).eq(selected_id)].head(1)
    if not detail.empty:
        row = detail.iloc[0]
        metric_grid(
            {
                "Encontrou no LCTE": "SIM",
                "Encontrou no CONTROL": row.get("CONTROL localizado?") or "NAO",
                "Encontrou no Rastreador": "SIM" if int(row.get("Pontos rastreador janela") or 0) > 0 else "NAO",
                "Encontrou origem GPS": "SIM" if str(row.get("Chegada origem GPS") or "") else "NAO",
                "Encontrou destino GPS": "SIM" if str(row.get("Chegada destino GPS") or "") else "NAO",
                "Calculou permanencia GPS": "SIM" if row.get("Status") in ["GPS CALCULADO", "GPS PARCIAL"] else "NAO",
                "Control bloqueou calculo": "NAO",
                "Possivel estadia": row.get("Possivel estadia?") or "NAO",
            },
            columns=4,
        )
        st.write(
            {
                "Motivo": row.get("Motivo"),
                "Diagnostico": row.get("Diagnostico"),
                "Tempo origem GPS": row.get("Tempo origem GPS"),
                "Tempo destino GPS": row.get("Tempo destino GPS"),
                "Tempo operacional GPS": row.get("Tempo operacional GPS"),
                "Confiança da Permanência (%)": row.get("Confiança da Permanência (%)"),
                "Motivo confirmação saída": row.get("Motivo confirmação saída"),
                "Interrupções ignoradas": row.get("Interrupções ignoradas"),
                "Maior distância temporária da cerca origem (km)": row.get("Maior distância temporária da cerca origem (km)"),
                "Maior distância temporária da cerca destino (km)": row.get("Maior distância temporária da cerca destino (km)"),
                "Tempo oscilação absorvido origem (min)": row.get("Tempo oscilação absorvido origem (min)"),
                "Tempo oscilação absorvido destino (min)": row.get("Tempo oscilação absorvido destino (min)"),
                "Data inicio viagem": row.get("Data inicio viagem"),
                "Fonte data inicio viagem": row.get("Fonte inicio viagem"),
                "Km percorrido": row.get("Km percorrido"),
                "Distancia ponto carga km": row.get("Distancia ponto carga km"),
                "Distancia ponto descarga km": row.get("Distancia ponto descarga km"),
            }
        )
        with st.expander("Timeline LCTE / GPS / CONTROL", expanded=True):
            render_dataframe(timeline[timeline["lcte_id"].astype(int).eq(selected_id)] if isinstance(timeline, pd.DataFrame) and not timeline.empty else pd.DataFrame(), height=260, max_rows=50)
        with st.expander("Log detalhado", expanded=False):
            st.json(row.get("diagnostico_json") or "{}")
            st.json(row.get("log_processamento_json") or "[]")


def render_logs_page() -> None:
    st.title("Logs de Importacao - Estadias")
    render_dataframe(latest_logs(200), height=560, max_rows=200)


def render_config_page(usuario: str) -> None:
    st.title("Configuracoes Estadias")
    st.caption("Parametros aplicados no cruzamento LCTE x CONTROL x Rastreador.")
    tab_config, tab_locais, tab_parametros, tab_auditoria = st.tabs(["Gerais", "Locais operacionais", "Parametros por cliente", "Auditoria"])
    with tab_config:
        df = read_config()
        if df.empty:
            st.info("Nenhuma configuracao cadastrada.")
        else:
            edited = st.data_editor(
                df[["chave", "valor", "descricao", "updated_at", "updated_by"]],
                use_container_width=True,
                hide_index=True,
                disabled=["chave", "updated_at", "updated_by"],
                key="estadias_config_editor",
            )
            if st.button("Salvar configuracoes", type="primary", use_container_width=True):
                saved = save_config(edited, usuario)
                st.success(f"{saved} configuracao(oes) salva(s).")
                st.rerun()
    with tab_locais:
        locais = read_locais(2000)
        base = locais if not locais.empty else pd.DataFrame(
            columns=[
                "nome_padrao",
                "nome_norm",
                "municipio",
                "uf",
                "razao_social",
                "latitude",
                "longitude",
                "raio_metros",
                "tipo_local",
                "aliases",
                "origem_cadastro",
                "ativo",
            ]
        )
        edited_locais = st.data_editor(base, use_container_width=True, hide_index=True, num_rows="dynamic", key="estadias_locais_editor")
        if st.button("Salvar locais operacionais", type="primary", use_container_width=True):
            saved = save_locais(edited_locais, usuario)
            st.success(f"{saved} local(is) salvo(s).")
            st.rerun()
    with tab_parametros:
        parametros = read_parametros(2000)
        base = parametros if not parametros.empty else pd.DataFrame(
            [
                {
                    "cliente": "IPIRANGA",
                    "cliente_norm": "IPIRANGA",
                    "tipo_operacao": "",
                    "franquia_carga_horas": 24,
                    "franquia_descarga_horas": 24,
                    "inicio_contagem": "CHEGADA_REAL",
                    "regra_agendamento": "",
                    "valor_hora": 0,
                    "vigencia_inicial": "",
                    "vigencia_final": "",
                    "observacoes": "",
                    "ativo": 1,
                }
            ]
        )
        edited_parametros = st.data_editor(base, use_container_width=True, hide_index=True, num_rows="dynamic", key="estadias_parametros_editor")
        if st.button("Salvar parametros por cliente", type="primary", use_container_width=True):
            saved = save_parametros(edited_parametros, usuario)
            st.success(f"{saved} parametro(s) salvo(s).")
            st.rerun()
    with tab_auditoria:
        render_dataframe(read_auditoria(1000), height=520, max_rows=1000)
