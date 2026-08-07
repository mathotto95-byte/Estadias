from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from src.modules.estadias import repository
from src.modules.estadias.normalizers import normalizar_placa
from src.modules.estadias.service import (
    _detect_trip_events,
    _distance_to_point,
    _doc_set,
    _ensure_datetime_column,
    _km_percorrido,
    _minutes,
    _select_control_matches,
    _to_datetime,
)


DEFAULT_TEST_PLATE = "AIW8A04"

DEFAULT_VISIBLE_COLUMNS = [
    "Status",
    "Placa",
    "CT-e",
    "NF",
    "Data emissao LCTE",
    "Origem LCTE",
    "Destino LCTE",
    "Chegada origem GPS",
    "Saida origem GPS",
    "Tempo origem GPS",
    "Chegada destino GPS",
    "Saida destino GPS",
    "Tempo destino GPS",
    "Confiança da Permanência (%)",
    "Motivo confirmação saída",
    "Interrupções ignoradas",
    "CONTROL localizado?",
    "Dt carga CONTROL",
    "Dt descarga CONTROL",
    "Tempo CONTROL",
    "Possivel estadia?",
    "Motivo",
    "Diagnostico",
]

MONTH_NAMES = {
    1: "Janeiro",
    2: "Fevereiro",
    3: "Março",
    4: "Abril",
    5: "Maio",
    6: "Junho",
    7: "Julho",
    8: "Agosto",
    9: "Setembro",
    10: "Outubro",
    11: "Novembro",
    12: "Dezembro",
}

CARD_DEFINITIONS: dict[str, dict[str, str]] = {
    "viagens_lcte": {"label": "Viagens no LCTE", "group": "lcte"},
    "com_rastreador": {"label": "Com Rastreador", "group": "rastreador"},
    "sem_rastreador": {"label": "Sem Rastreador", "group": "rastreador"},
    "control_completo": {"label": "Control Completo", "group": "control"},
    "control_incompleto": {"label": "Control Incompleto", "group": "control"},
    "sem_control": {"label": "Sem Control", "group": "control"},
    "origem_identificada": {"label": "Origem Identificada", "group": "gps_origem"},
    "destino_identificada": {"label": "Destino Identificado", "group": "gps_destino"},
    "permanencia_gps": {"label": "Permanencia GPS", "group": "gps_permanencia"},
    "possivel_estadia": {"label": "Possivel Estadia", "group": "estadia"},
    "nao_calculadas": {"label": "Nao Calculadas", "group": "calculo"},
    "inconsistencias": {"label": "Inconsistencias", "group": "qualidade"},
}


def _format_datetime_br(value: Any) -> str:
    parsed = _to_datetime(value)
    return parsed.strftime("%d/%m/%Y %H:%M") if parsed else ""


def _format_minutes_value(value: Any) -> str:
    total = int(round(float(value or 0)))
    hours, minutes = divmod(total, 60)
    return f"{hours}h {minutes:02d}min"


def _parse_optional_datetime(value: Any, end_of_day: bool = False) -> datetime | None:
    parsed = _to_datetime(value)
    if not parsed:
        return None
    if end_of_day and parsed.hour == 0 and parsed.minute == 0 and parsed.second == 0:
        return parsed.replace(hour=23, minute=59, second=59)
    return parsed


def _trip_reference_datetime(trip: pd.Series) -> datetime | None:
    return _to_datetime(trip.get("data_emissao")) or _to_datetime(trip.get("data_hora_carga")) or _to_datetime(trip.get("data_operacao"))


def _control_is_complete(control_matches: pd.DataFrame) -> bool:
    if control_matches.empty:
        return False
    row = control_matches.iloc[0]
    missing = _control_missing_fields(control_matches)
    return not missing


def _control_observation_value(row: pd.Series, label: str) -> str:
    text = str(row.get("observacao") or "")
    match = re.search(rf"{re.escape(label)}\s*:\s*([^|]+)", text, flags=re.I)
    return str(match.group(1)).strip() if match else ""


def _has_explicit_control_label(row: pd.Series, label: str) -> bool:
    return bool(re.search(rf"{re.escape(label)}\s*:", str(row.get("observacao") or ""), flags=re.I))


def _control_datetime_value(row: pd.Series, label: str, fallback_columns: list[str]) -> datetime | None:
    parsed = _to_datetime(_control_observation_value(row, label))
    if parsed:
        return parsed
    for column in fallback_columns:
        parsed = _to_datetime(row.get(column))
        if parsed:
            return parsed
    return None


def _control_duration_ok(row: pd.Series, label: str) -> bool:
    value = _control_observation_value(row, label)
    if value:
        text = value.strip().upper()
        return text not in {"0", "0:00", "00:00", "00:00:00", "0H", "0H00", "0H 00MIN"}
    if _has_explicit_control_label(row, label):
        return False
    return float(pd.to_numeric(pd.Series([row.get("tempo_total")]), errors="coerce").fillna(0).iloc[0]) > 0


def _control_missing_fields(control_matches: pd.DataFrame) -> list[str]:
    if control_matches.empty:
        return []
    row = control_matches.iloc[0]
    missing: list[str] = []
    has_start = bool(_control_datetime_value(row, "Inicio carga", ["data_hora_inicio", "data_inicio"]))
    has_end = bool(_control_datetime_value(row, "Fim descarga", ["data_hora_fim", "data_fim"]))
    has_load_duration = _control_duration_ok(row, "Tempo carga")
    has_unload_duration = _control_duration_ok(row, "Tempo descarga")
    has_nf = bool(_doc_set(row.get("nf")))
    has_origin = bool(str(row.get("local_origem") or "").strip())
    has_destination = bool(str(row.get("local_destino") or "").strip())
    if not has_start:
        missing.append("data/horario de carga")
    if not has_end:
        missing.append("data/horario de descarga")
    if not has_load_duration:
        missing.append("tempo de carga")
    if not has_unload_duration:
        missing.append("tempo de descarga")
    if not _doc_set(row.get("nf")):
        missing.append("NF")
    if not str(row.get("local_origem") or "").strip():
        missing.append("origem")
    if not str(row.get("local_destino") or "").strip():
        missing.append("destino")
    return missing


def _inicio_viagem_reference(events: dict[str, Any], control_matches: pd.DataFrame, trip: pd.Series) -> tuple[datetime | None, str]:
    for value, source in [
        (events.get("saida_origem"), "RASTREADOR_SAIDA_ORIGEM"),
        (events.get("chegada_origem"), "RASTREADOR_CHEGADA_ORIGEM"),
    ]:
        parsed = _to_datetime(value)
        if parsed:
            return parsed, source
    if not control_matches.empty:
        row = control_matches.iloc[0]
        parsed = _to_datetime(row.get("data_hora_inicio"))
        if parsed:
            return parsed, "CONTROL_DT_CARGA"
        parsed = _to_datetime(row.get("data_inicio"))
        if parsed:
            return parsed, "CONTROL_DATA_INICIO"
    return _trip_reference_datetime(trip), "LCTE_DATA_EMISSAO"


def _filter_lcte(
    lcte: pd.DataFrame,
    placa_norm: str,
    periodo_inicio: Any = "",
    periodo_fim: Any = "",
) -> pd.DataFrame:
    if lcte.empty:
        return lcte
    view = lcte.copy()
    if placa_norm:
        view = view[view.get("placa_norm", pd.Series(dtype=str)).fillna("").astype(str).eq(placa_norm)].copy()
    view = _ensure_datetime_column(view, "data_emissao", "_ref_dt")
    if view["_ref_dt"].isna().any():
        carga_dt = pd.to_datetime(view.get("data_hora_carga", pd.Series(dtype=str)), errors="coerce")
        operacao_dt = pd.to_datetime(view.get("data_operacao", pd.Series(dtype=str)), errors="coerce")
        view["_ref_dt"] = view["_ref_dt"].fillna(carga_dt).fillna(operacao_dt)
    start = _parse_optional_datetime(periodo_inicio)
    end = _parse_optional_datetime(periodo_fim, end_of_day=True)
    if start:
        view = view[view["_ref_dt"].ge(pd.Timestamp(start)) | view["_ref_dt"].isna()].copy()
    if end:
        view = view[view["_ref_dt"].le(pd.Timestamp(end)) | view["_ref_dt"].isna()].copy()
    return view.sort_values(["placa_norm", "_ref_dt", "id"], na_position="last")


def _tracker_window_for_trip(
    rastreador: pd.DataFrame,
    trip: pd.Series,
    all_lcte: pd.DataFrame,
    config: dict[str, str],
    limitar_proxima_viagem: bool,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    plate = str(trip.get("placa_norm") or "")
    plate_points = rastreador[rastreador.get("placa_norm", pd.Series(dtype=str)).fillna("").astype(str).eq(plate)].copy() if plate else pd.DataFrame()
    info: dict[str, Any] = {
        "fonte_janela": "LCTE",
        "total_pontos_placa": int(len(plate_points)),
        "pontos_janela": 0,
        "inicio": None,
        "fim": None,
        "proxima_viagem_lcte": None,
    }
    base = _trip_reference_datetime(trip)
    if plate_points.empty or not base:
        return plate_points, info
    hours_before = float(config.get("janela_lcte_horas_antes") or 24)
    days_after = float(config.get("janela_lcte_dias_depois") or 7)
    start = base - timedelta(hours=max(hours_before, 0))
    end = base + timedelta(days=max(days_after, 1))
    if limitar_proxima_viagem and not all_lcte.empty:
        plate_lcte = all_lcte[all_lcte.get("placa_norm", pd.Series(dtype=str)).fillna("").astype(str).eq(plate)].copy()
        plate_lcte = _ensure_datetime_column(plate_lcte, "data_emissao", "_next_ref_dt")
        if plate_lcte["_next_ref_dt"].isna().any():
            carga_dt = pd.to_datetime(plate_lcte.get("data_hora_carga", pd.Series(dtype=str)), errors="coerce")
            operacao_dt = pd.to_datetime(plate_lcte.get("data_operacao", pd.Series(dtype=str)), errors="coerce")
            plate_lcte["_next_ref_dt"] = plate_lcte["_next_ref_dt"].fillna(carga_dt).fillna(operacao_dt)
        next_rows = plate_lcte[plate_lcte["_next_ref_dt"].gt(pd.Timestamp(base))].sort_values("_next_ref_dt")
        if not next_rows.empty:
            next_dt = next_rows.iloc[0]["_next_ref_dt"].to_pydatetime()
            info["proxima_viagem_lcte"] = next_dt
            end = min(end, next_dt - timedelta(minutes=1))
            info["fonte_janela"] = "LCTE_ATE_PROXIMA_VIAGEM"
    plate_points = _ensure_datetime_column(plate_points, "data_hora", "_data_dt")
    window = plate_points[plate_points["_data_dt"].between(pd.Timestamp(start), pd.Timestamp(end))].sort_values("_data_dt").copy()
    info.update({"inicio": start, "fim": end, "pontos_janela": int(len(window))})
    return window, info


def _status_and_reasons(
    tracker_window: pd.DataFrame,
    events: dict[str, Any],
    control_matches: pd.DataFrame,
    control_complete: bool,
    min_stop_minutes: float,
    trip: pd.Series,
    total_plate_points: int,
) -> tuple[str, list[str], bool, bool]:
    reasons: list[str] = []
    if not str(trip.get("placa_norm") or ""):
        reasons.append("LCTE_SEM_PLACA")
    if total_plate_points == 0:
        reasons.append("PLACA_INEXISTENTE_RASTREADOR")
    elif tracker_window.empty:
        reasons.append("RASTREADOR_SEM_REGISTROS_JANELA")
    if not bool(events.get("encontrou_origem")):
        reasons.append("ORIGEM_NAO_LOCALIZADA_GPS")
    if not bool(events.get("encontrou_destino")):
        reasons.append("DESTINO_NAO_LOCALIZADO_GPS")
    tempo_operacional = float(events.get("tempo_origem") or 0) + float(events.get("tempo_destino") or 0)
    if tempo_operacional and tempo_operacional < min_stop_minutes:
        reasons.append("PERMANENCIA_INSUFICIENTE")
    if control_matches.empty:
        reasons.append("CONTROL_NAO_LOCALIZADO_AUDITORIA")
    elif not control_complete:
        reasons.append("CONTROL_INCOMPLETO_AUDITORIA")
    if not trip.get("latitude_origem") or not trip.get("longitude_origem"):
        reasons.append("COORDENADAS_ORIGEM_AUSENTES")
    if not trip.get("latitude_destino") or not trip.get("longitude_destino"):
        reasons.append("COORDENADAS_DESTINO_AUSENTES")
    calculou_gps = bool(events.get("encontrou_origem")) or bool(events.get("encontrou_destino"))
    if not calculou_gps:
        reasons.append("PERMANENCIA_NAO_IDENTIFICADA_GPS")
    if bool(events.get("encontrou_origem")) and bool(events.get("encontrou_destino")) and tempo_operacional >= min_stop_minutes:
        status = "GPS CALCULADO"
    elif calculou_gps:
        status = "GPS PARCIAL"
    elif tracker_window.empty:
        status = "SEM RASTREADOR"
    else:
        status = "NAO CALCULADO"
    inconsistent = bool(set(reasons) & {"LCTE_SEM_PLACA", "PLACA_INEXISTENTE_RASTREADOR", "RASTREADOR_SEM_REGISTROS_JANELA", "PERMANENCIA_NAO_IDENTIFICADA_GPS"})
    return status, list(dict.fromkeys(reasons)), calculou_gps, inconsistent


def _timeline_rows(row: dict[str, Any]) -> list[dict[str, Any]]:
    base = {"lcte_id": row.get("lcte_id"), "Placa": row.get("Placa"), "CT-e": row.get("CT-e"), "NF": row.get("NF")}
    events = [
        ("LCTE", "Emissao/Carga", row.get("Data emissao LCTE"), row.get("Origem LCTE"), ""),
        ("GPS", "Chegada origem", row.get("Chegada origem GPS"), row.get("Origem LCTE"), row.get("Tempo origem GPS")),
        ("GPS", "Saida origem", row.get("Saida origem GPS"), row.get("Origem LCTE"), row.get("Tempo origem GPS")),
        ("GPS", "Chegada destino", row.get("Chegada destino GPS"), row.get("Destino LCTE"), row.get("Tempo destino GPS")),
        ("GPS", "Saida destino", row.get("Saida destino GPS"), row.get("Destino LCTE"), row.get("Tempo destino GPS")),
        ("CONTROL", "Inicio", row.get("Dt carga CONTROL"), row.get("Origem LCTE"), row.get("Tempo CONTROL")),
        ("CONTROL", "Fim", row.get("Dt descarga CONTROL"), row.get("Destino LCTE"), row.get("Tempo CONTROL")),
    ]
    return [{**base, "Fonte": source, "Evento": event, "Data/hora": when, "Local": location, "Tempo": duration} for source, event, when, location, duration in events if when]


def build_teste_lcte_rastreador(
    placa: str = DEFAULT_TEST_PLATE,
    periodo_inicio: Any = "",
    periodo_fim: Any = "",
    janela_antes_horas: float = 24,
    janela_depois_dias: float = 7,
    raio_metros: float = 1000,
    tolerancia_raio_extra_metros: float = 300,
    tolerancia_sem_sinal_minutos: float = 30,
    tolerancia_fora_cerca_minutos: float = 15,
    min_pontos_permanencia: int = 1,
    tempo_minimo_parado_minutos: float = 30,
    franquia_horas: float = 24,
    limitar_proxima_viagem: bool = True,
    limite_viagens: int = 5000,
) -> tuple[pd.DataFrame, dict[str, Any], pd.DataFrame, pd.DataFrame]:
    placa_norm = normalizar_placa(placa)
    lcte_base = repository.read_lcte({}, 200000)
    lcte = _filter_lcte(lcte_base, placa_norm, periodo_inicio, periodo_fim).head(limite_viagens)
    control = repository.read_control({"placa_norm": placa_norm}, 300000) if placa_norm else repository.read_control({}, 300000)
    rastreador = repository.read_rastreador({"placa_norm": placa_norm}, 700000) if placa_norm else repository.read_rastreador({}, 700000)
    config = {
        "janela_lcte_horas_antes": str(janela_antes_horas),
        "janela_lcte_dias_depois": str(janela_depois_dias),
        "raio_metros_local": str(raio_metros),
        "tolerancia_raio_extra_metros": str(tolerancia_raio_extra_metros),
        "tolerancia_sem_sinal_minutos": str(tolerancia_sem_sinal_minutos),
        "tolerancia_fora_cerca_minutos": str(tolerancia_fora_cerca_minutos),
        "min_pontos_permanencia": str(max(int(min_pontos_permanencia or 1), 1)),
    }
    rows: list[dict[str, Any]] = []
    timeline: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []

    for _, trip in lcte.iterrows():
        log = ["LCTE: viagem mestre encontrada no painel de teste LCTE x RASTREADOR."]
        control_matches, control_score, control_class, control_criteria, control_reason = _select_control_matches(control, trip, log)
        control_complete = _control_is_complete(control_matches)
        tracker_window, window_info = _tracker_window_for_trip(rastreador, trip, lcte_base, config, limitar_proxima_viagem)
        events = _detect_trip_events(tracker_window, trip, config, log)
        status, reasons, calculou_gps, inconsistent = _status_and_reasons(
            tracker_window,
            events,
            control_matches,
            control_complete,
            tempo_minimo_parado_minutos,
            trip,
            int(window_info.get("total_pontos_placa") or 0),
        )
        tempo_origem = _minutes(events.get("tempo_origem") or 0)
        tempo_destino = _minutes(events.get("tempo_destino") or 0)
        tempo_operacional = _minutes(tempo_origem + tempo_destino)
        chegada_origem = events.get("chegada_origem")
        saida_destino = events.get("saida_destino")
        first_dt = chegada_origem or _trip_reference_datetime(trip)
        last_dt = saida_destino or (tracker_window["_data_dt"].max().to_pydatetime() if not tracker_window.empty and "_data_dt" in tracker_window and tracker_window["_data_dt"].notna().any() else None)
        tempo_total = _minutes((last_dt - first_dt).total_seconds() / 60) if first_dt and last_dt and last_dt >= first_dt else 0
        estadia_carga_min = _minutes(max(tempo_origem - franquia_horas * 60, 0))
        estadia_descarga_min = _minutes(max(tempo_destino - franquia_horas * 60, 0))
        possivel_estadia = estadia_carga_min > 0 or estadia_descarga_min > 0
        control_row = control_matches.iloc[0] if not control_matches.empty else pd.Series(dtype=object)
        control_missing = _control_missing_fields(control_matches)
        tempo_control = _minutes(pd.to_numeric(control_matches.get("tempo_total", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()) if not control_matches.empty else 0
        inicio_viagem, fonte_inicio_viagem = _inicio_viagem_reference(events, control_matches, trip)
        diagnostic = {
            "lcte_id": int(trip.get("id") or 0),
            "Encontrou no LCTE": True,
            "Encontrou no CONTROL": not control_matches.empty,
            "CONTROL completo": control_complete,
            "CONTROL campos ausentes": control_missing,
            "CONTROL classificacao": control_class,
            "CONTROL pontuacao": control_score,
            "CONTROL criterio": control_criteria,
            "CONTROL motivo auditoria": control_reason,
            "Encontrou no Rastreador": not tracker_window.empty,
            "Encontrou origem GPS": bool(events.get("encontrou_origem")),
            "Encontrou destino GPS": bool(events.get("encontrou_destino")),
            "Calculou permanencia GPS": calculou_gps,
            "Control bloqueou calculo GPS": False,
            "Data inicio viagem referencia": inicio_viagem,
            "Fonte data inicio viagem": fonte_inicio_viagem,
            "Inicio janela": window_info.get("inicio"),
            "Fim janela": window_info.get("fim"),
            "Fonte janela": window_info.get("fonte_janela"),
            "Proxima viagem LCTE": window_info.get("proxima_viagem_lcte"),
            "Total pontos placa": int(window_info.get("total_pontos_placa") or 0),
            "Pontos na janela": int(window_info.get("pontos_janela") or 0),
            "Pontos origem": int(events.get("pontos_origem") or 0),
            "Pontos destino": int(events.get("pontos_destino") or 0),
            "Distancia origem km": events.get("distancia_origem_min_km"),
            "Distancia destino km": events.get("distancia_destino_min_km"),
            "Confianca origem pct": events.get("confianca_origem_pct"),
            "Confianca destino pct": events.get("confianca_destino_pct"),
            "Motivo saida origem": events.get("motivo_saida_origem"),
            "Motivo saida destino": events.get("motivo_saida_destino"),
            "Interrupcoes ignoradas origem": events.get("interrupcoes_ignoradas_origem"),
            "Interrupcoes ignoradas destino": events.get("interrupcoes_ignoradas_destino"),
            "Maior distancia temporaria origem km": events.get("maior_distancia_temporaria_origem_km"),
            "Maior distancia temporaria destino km": events.get("maior_distancia_temporaria_destino_km"),
            "Tempo oscilacao absorvido origem min": events.get("tempo_oscilacao_absorvido_origem"),
            "Tempo oscilacao absorvido destino min": events.get("tempo_oscilacao_absorvido_destino"),
            "Motivos": reasons,
            "Log": log,
        }
        confidence_values = [
            float(value)
            for value in [events.get("confianca_origem_pct"), events.get("confianca_destino_pct")]
            if float(value or 0) > 0
        ]
        confidence = int(round(sum(confidence_values) / len(confidence_values))) if confidence_values else 0
        exit_reasons = [str(value) for value in [events.get("motivo_saida_origem"), events.get("motivo_saida_destino")] if str(value or "").strip()]
        ignored_interruptions = int(events.get("interrupcoes_ignoradas_origem") or 0) + int(events.get("interrupcoes_ignoradas_destino") or 0)
        row = {
            "lcte_id": int(trip.get("id") or 0),
            "Status": status,
            "Placa": str(trip.get("placa_norm") or ""),
            "CT-e": str(trip.get("cte") or ""),
            "NF": str(trip.get("nf") or ""),
            "Data emissao LCTE": _format_datetime_br(trip.get("data_emissao") or trip.get("data_hora_carga") or trip.get("data_operacao")),
            "data_inicio_viagem_referencia": inicio_viagem,
            "Data inicio viagem": _format_datetime_br(inicio_viagem),
            "fonte_data_inicio_viagem": fonte_inicio_viagem,
            "Fonte inicio viagem": fonte_inicio_viagem,
            "Origem LCTE": str(trip.get("origem") or ""),
            "Destino LCTE": str(trip.get("destino") or ""),
            "Cliente": str(trip.get("cliente") or ""),
            "Motorista": str(trip.get("motorista") or ""),
            "Chegada origem GPS": _format_datetime_br(events.get("chegada_origem")),
            "Saida origem GPS": _format_datetime_br(events.get("saida_origem")),
            "Tempo origem GPS": _format_minutes_value(tempo_origem),
            "Tempo origem GPS (min)": tempo_origem,
            "Chegada destino GPS": _format_datetime_br(events.get("chegada_destino")),
            "Saida destino GPS": _format_datetime_br(events.get("saida_destino")),
            "Tempo destino GPS": _format_minutes_value(tempo_destino),
            "Tempo destino GPS (min)": tempo_destino,
            "Confiança da Permanência (%)": confidence,
            "Confiança origem (%)": events.get("confianca_origem_pct") or 0,
            "Confiança destino (%)": events.get("confianca_destino_pct") or 0,
            "Motivo confirmação saída": "; ".join(exit_reasons),
            "Motivo confirmação saída origem": events.get("motivo_saida_origem") or "",
            "Motivo confirmação saída destino": events.get("motivo_saida_destino") or "",
            "Interrupções ignoradas": ignored_interruptions,
            "Interrupções ignoradas origem": events.get("interrupcoes_ignoradas_origem") or 0,
            "Interrupções ignoradas destino": events.get("interrupcoes_ignoradas_destino") or 0,
            "Maior distância temporária da cerca origem (km)": events.get("maior_distancia_temporaria_origem_km") or 0,
            "Maior distância temporária da cerca destino (km)": events.get("maior_distancia_temporaria_destino_km") or 0,
            "Tempo oscilação absorvido origem (min)": events.get("tempo_oscilacao_absorvido_origem") or 0,
            "Tempo oscilação absorvido destino (min)": events.get("tempo_oscilacao_absorvido_destino") or 0,
            "CONTROL localizado?": "SIM" if not control_matches.empty else "NAO",
            "CONTROL completo?": "SIM" if control_complete else "NAO",
            "CONTROL campos ausentes": "; ".join(control_missing),
            "Dt carga CONTROL": _format_datetime_br(control_row.get("data_hora_inicio") if not control_matches.empty else ""),
            "Dt descarga CONTROL": _format_datetime_br(control_row.get("data_hora_fim") if not control_matches.empty else ""),
            "Tempo CONTROL": _format_minutes_value(tempo_control),
            "Tempo CONTROL (min)": tempo_control,
            "Possivel estadia?": "SIM" if possivel_estadia else "NAO",
            "Estadia carga GPS (min)": estadia_carga_min,
            "Estadia descarga GPS (min)": estadia_descarga_min,
            "Tempo operacional GPS": _format_minutes_value(tempo_operacional),
            "Tempo operacional GPS (min)": tempo_operacional,
            "Tempo transito GPS (min)": _minutes(max(tempo_total - tempo_operacional, 0)),
            "Tempo total viagem GPS (min)": tempo_total,
            "Km percorrido": round(float(_km_percorrido(tracker_window) or trip.get("km_rota") or 0), 2),
            "Distancia ponto carga km": events.get("distancia_origem_min_km") or _distance_to_point(tracker_window, trip.get("latitude_origem"), trip.get("longitude_origem")) or 0,
            "Distancia ponto descarga km": events.get("distancia_destino_min_km") or _distance_to_point(tracker_window, trip.get("latitude_destino"), trip.get("longitude_destino")) or 0,
            "Pontos rastreador janela": int(window_info.get("pontos_janela") or 0),
            "Pontos origem GPS": int(events.get("pontos_origem") or 0),
            "Pontos destino GPS": int(events.get("pontos_destino") or 0),
            "tem_rastreador_janela": int(not tracker_window.empty),
            "tem_rastreador_placa": int((window_info.get("total_pontos_placa") or 0) > 0),
            "control_completo": int(control_complete),
            "control_incompleto": int(not control_matches.empty and not control_complete),
            "sem_control": int(control_matches.empty),
            "origem_identificada": int(bool(events.get("encontrou_origem"))),
            "destino_identificada": int(bool(events.get("encontrou_destino"))),
            "permanencia_gps": int(calculou_gps),
            "possivel_estadia": int(possivel_estadia),
            "nao_calculada": int(status in ["SEM RASTREADOR", "NAO CALCULADO"]),
            "inconsistencia": int(inconsistent),
            "Motivo": "; ".join(reasons) if reasons else "GPS calculado sem bloqueios.",
            "Diagnostico": "Control usado apenas para auditoria; calculo GPS independente do CONTROL.",
            "diagnostico_json": json.dumps(diagnostic, ensure_ascii=False, default=str),
            "log_processamento_json": json.dumps(log, ensure_ascii=False, default=str),
            "Inconsistencia?": "SIM" if inconsistent else "NAO",
        }
        rows.append(row)
        timeline.extend(_timeline_rows(row))
        diagnostics.append(
            {
                **{key: value for key, value in row.items() if key not in {"diagnostico_json", "log_processamento_json"}},
                "Inicio janela": _format_datetime_br(window_info.get("inicio")),
                "Fim janela": _format_datetime_br(window_info.get("fim")),
                "Proxima viagem LCTE": _format_datetime_br(window_info.get("proxima_viagem_lcte")),
                "Criterios CONTROL": json.dumps(control_criteria, ensure_ascii=False, default=str),
                "Log detalhado": " | ".join(log),
            }
        )

    result = pd.DataFrame(rows)
    diagnostic_df = pd.DataFrame(diagnostics)
    timeline_df = pd.DataFrame(timeline)
    summary = {
        "Viagens LCTE": int(len(lcte)),
        "Registros Rastreador": int(len(rastreador)),
        "CONTROL encontrado": int(result["CONTROL localizado?"].eq("SIM").sum()) if not result.empty else 0,
        "CONTROL completo": int(result["CONTROL completo?"].eq("SIM").sum()) if not result.empty else 0,
        "CONTROL incompleto": int((result["CONTROL localizado?"].eq("SIM") & result["CONTROL completo?"].ne("SIM")).sum()) if not result.empty else 0,
        "CONTROL ausente": int(result["CONTROL localizado?"].eq("NAO").sum()) if not result.empty else 0,
        "GPS origem identificado": int(result["Chegada origem GPS"].astype(str).ne("").sum()) if not result.empty else 0,
        "GPS destino identificado": int(result["Chegada destino GPS"].astype(str).ne("").sum()) if not result.empty else 0,
        "Permanencia GPS": int(result["Status"].isin(["GPS CALCULADO", "GPS PARCIAL"]).sum()) if not result.empty else 0,
        "Possivel estadia": int(result["Possivel estadia?"].eq("SIM").sum()) if not result.empty else 0,
        "Nao calculado": int(result["Status"].isin(["SEM RASTREADOR", "NAO CALCULADO"]).sum()) if not result.empty else 0,
        "Inconsistencias": int(result["Inconsistencia?"].eq("SIM").sum()) if not result.empty else 0,
    }
    return result, summary, diagnostic_df, timeline_df


def ensure_panel_filter_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    view = df.copy()
    parsed = pd.to_datetime(view.get("data_inicio_viagem_referencia", pd.Series(dtype=object)), errors="coerce")
    if parsed.isna().any() and "Data inicio viagem" in view:
        parsed = parsed.fillna(pd.to_datetime(view["Data inicio viagem"], errors="coerce", dayfirst=True))
    view["data_inicio_viagem_referencia"] = parsed
    view["ano_inicio_viagem"] = parsed.dt.year.astype("Int64")
    view["mes_inicio_viagem"] = parsed.dt.strftime("%Y-%m")
    view["mes_inicio_viagem_label"] = parsed.map(month_label_from_datetime)
    for column, default in {
        "tem_rastreador_janela": 0,
        "control_completo": 0,
        "control_incompleto": 0,
        "sem_control": 0,
        "origem_identificada": 0,
        "destino_identificada": 0,
        "permanencia_gps": 0,
        "possivel_estadia": 0,
        "nao_calculada": 0,
        "inconsistencia": 0,
    }.items():
        if column not in view:
            view[column] = default
    return view


def month_label(month_key: str) -> str:
    try:
        year, month = str(month_key).split("-", 1)
        return f"{MONTH_NAMES[int(month)]}/{year}"
    except Exception:
        return str(month_key or "")


def month_label_from_datetime(value: Any) -> str:
    parsed = _to_datetime(value)
    if not parsed:
        return ""
    return f"{MONTH_NAMES.get(parsed.month, str(parsed.month))}/{parsed.year}"


def available_years(df: pd.DataFrame) -> list[int]:
    view = ensure_panel_filter_columns(df)
    if view.empty:
        return []
    years = pd.to_numeric(view["ano_inicio_viagem"], errors="coerce").dropna().astype(int).unique().tolist()
    return sorted(years)


def available_months(df: pd.DataFrame, years: list[int] | None = None) -> list[str]:
    view = ensure_panel_filter_columns(df)
    if view.empty:
        return []
    if years:
        view = view[view["ano_inicio_viagem"].isin(years)]
    months = view["mes_inicio_viagem"].fillna("").astype(str)
    return sorted(month for month in months.unique().tolist() if month)


def latest_month_with_data(df: pd.DataFrame) -> str:
    months = available_months(df)
    return months[-1] if months else ""


def _contains_filter(series: pd.Series, value: Any) -> pd.Series:
    if value in [None, ""]:
        return pd.Series(True, index=series.index)
    return series.fillna("").astype(str).str.contains(str(value), case=False, na=False)


def _card_mask(df: pd.DataFrame, card_key: str) -> pd.Series:
    if df.empty:
        return pd.Series(dtype=bool)
    if card_key == "viagens_lcte":
        return pd.Series(True, index=df.index)
    if card_key == "com_rastreador":
        return df["tem_rastreador_janela"].fillna(0).astype(int).eq(1)
    if card_key == "sem_rastreador":
        return df["tem_rastreador_janela"].fillna(0).astype(int).ne(1)
    if card_key == "control_completo":
        return df["control_completo"].fillna(0).astype(int).eq(1)
    if card_key == "control_incompleto":
        return df["control_incompleto"].fillna(0).astype(int).eq(1)
    if card_key == "sem_control":
        return df["sem_control"].fillna(0).astype(int).eq(1)
    if card_key == "origem_identificada":
        return df["origem_identificada"].fillna(0).astype(int).eq(1)
    if card_key == "destino_identificada":
        return df["destino_identificada"].fillna(0).astype(int).eq(1)
    if card_key == "permanencia_gps":
        return df["permanencia_gps"].fillna(0).astype(int).eq(1)
    if card_key == "possivel_estadia":
        return df["possivel_estadia"].fillna(0).astype(int).eq(1)
    if card_key == "nao_calculadas":
        return df["nao_calculada"].fillna(0).astype(int).eq(1)
    if card_key == "inconsistencias":
        return df["inconsistencia"].fillna(0).astype(int).eq(1)
    return pd.Series(True, index=df.index)


def aplicar_filtros_painel_estadias(
    df: pd.DataFrame,
    filters: dict[str, Any],
    include_card_filters: bool = True,
    exclude_card_group: str | None = None,
) -> pd.DataFrame:
    view = ensure_panel_filter_columns(df)
    if view.empty:
        return view
    date_type = str(filters.get("tipo_data") or "Por mes")
    if date_type == "Periodo personalizado":
        start = _parse_optional_datetime(filters.get("periodo_inicio"))
        end = _parse_optional_datetime(filters.get("periodo_fim"), end_of_day=True)
        if start:
            view = view[view["data_inicio_viagem_referencia"].ge(pd.Timestamp(start))].copy()
        if end:
            view = view[view["data_inicio_viagem_referencia"].le(pd.Timestamp(end))].copy()
    else:
        years = [int(year) for year in filters.get("anos", []) if str(year).strip()]
        months = [str(month) for month in filters.get("meses", []) if str(month).strip()]
        if years:
            view = view[view["ano_inicio_viagem"].isin(years)].copy()
        if months:
            view = view[view["mes_inicio_viagem"].isin(months)].copy()

    for column, value in {
        "Placa": filters.get("placa"),
        "CT-e": filters.get("cte"),
        "NF": filters.get("nf"),
        "Origem LCTE": filters.get("origem"),
        "Destino LCTE": filters.get("destino"),
        "Cliente": filters.get("cliente"),
        "Motorista": filters.get("motorista"),
    }.items():
        if value and column in view:
            view = view[_contains_filter(view[column], value)].copy()
    if filters.get("status") and "Status" in view:
        view = view[view["Status"].fillna("").astype(str).eq(str(filters["status"]))].copy()
    if filters.get("possivel_estadia") in ["SIM", "NAO"] and "Possivel estadia?" in view:
        view = view[view["Possivel estadia?"].fillna("").astype(str).eq(str(filters["possivel_estadia"]))].copy()

    if include_card_filters:
        active_cards = filters.get("cards") or {}
        for group, card_key in active_cards.items():
            if exclude_card_group and group == exclude_card_group:
                continue
            if card_key:
                view = view[_card_mask(view, str(card_key))].copy()
    return view


def card_counts(base_df: pd.DataFrame, filters: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for key, definition in CARD_DEFINITIONS.items():
        group = definition["group"]
        compatible = aplicar_filtros_painel_estadias(base_df, filters, include_card_filters=True, exclude_card_group=group)
        counts[key] = int(_card_mask(compatible, key).sum()) if not compatible.empty else 0
    return counts


def active_card_labels(active_cards: dict[str, str] | None) -> list[str]:
    labels: list[str] = []
    for card_key in (active_cards or {}).values():
        definition = CARD_DEFINITIONS.get(str(card_key))
        if definition:
            labels.append(definition["label"])
    return labels


def export_sheets(result: pd.DataFrame, diagnostic: pd.DataFrame, timeline: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {
        "teste_lcte_rastreador": result,
        "diagnostico_completo": diagnostic,
        "timeline": timeline,
    }
