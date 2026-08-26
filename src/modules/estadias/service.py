from __future__ import annotations

import json
import math
import re
from datetime import datetime, timedelta
from typing import Any, Callable

import pandas as pd

from src.modules.estadias import repository
from src.normalizers.fields import normalize_document_number, normalize_text


STOP_WORDS = {"DE", "DA", "DO", "DAS", "DOS", "E", "A", "O", "AS", "OS", "EM", "NA", "NO", "KM", "ROD", "RODOVIA", "BASE"}
PLATE_PATTERN = re.compile(r"[A-Z]{3}[0-9][A-Z0-9][0-9]{2}")
ProgressCallback = Callable[[int, int, str], None]

MOTIVOS = {
    "LCTE_SEM_PLACA": "Placa ausente ou invalida no LCTE.",
    "LCTE_SEM_NF": "Nota fiscal ausente no LCTE.",
    "LCTE_DATA_INVALIDA": "Data da carga ausente ou invalida no LCTE.",
    "LCTE_SEM_ORIGEM": "Origem ausente no LCTE.",
    "LCTE_SEM_DESTINO": "Destino ausente no LCTE.",
    "CONTROL_NAO_LOCALIZADO": "Nenhum registro correspondente encontrado no CONTROL.",
    "CONTROL_DOCUMENTO_DIVERGENTE": "CONTROL encontrado para a placa, mas com NF/CT-e diferente da viagem LCTE.",
    "CONTROL_JA_UTILIZADO": "Registro CONTROL ja vinculado a outra viagem LCTE da mesma placa.",
    "CONTROL_MULTIPLAS_CORRESPONDENCIAS": "Mais de um registro provavel encontrado no CONTROL.",
    "CONTROL_VIAGEM_EM_ANDAMENTO": "Viagem em andamento no CONTROL ou sem descarga informada.",
    "CONTROL_SEM_NF": "CONTROL sem NF; vinculo depende de placa, origem, destino e data.",
    "RASTREADOR_SEM_REGISTROS": "Nenhum registro de rastreador localizado na janela da viagem.",
    "RASTREADOR_PERMANENCIA_JA_UTILIZADA": "Bloco de permanencia do rastreador ja vinculado a outra viagem LCTE da mesma placa.",
    "RASTREADOR_DATA_INVALIDA": "Registros do rastreador sem data/hora valida.",
    "ORIGEM_SEM_COORDENADAS": "Origem sem coordenadas cadastradas.",
    "DESTINO_SEM_COORDENADAS": "Destino sem coordenadas cadastradas.",
    "ORIGEM_NAO_VISITADA": "Origem nao localizada no rastreador/CONTROL.",
    "DESTINO_NAO_VISITADO": "Destino nao localizado no rastreador/CONTROL.",
    "PERMANENCIA_INSUFICIENTE": "Permanencia inferior ao minimo configurado.",
    "PERMANENCIA_NAO_IDENTIFICADA": "Permanencia nao identificada no rastreador.",
    "VIAGEM_SOBREPOSTA": "Janela limitada pela proxima viagem da mesma placa.",
    "FRANQUIA_NAO_ULTRAPASSADA": "Tempo calculado nao ultrapassou a franquia.",
    "AGENDAMENTO_FORA_DO_LIMITE": "Agendamento fora do limite operacional configurado.",
    "VINCULO_AGUARDANDO_REVISAO": "Vinculo exige revisao manual.",
    "DIVERGENCIA_CONTROL_RASTREADOR": "Divergencia acima da tolerancia entre CONTROL e Rastreador.",
    "MULTIPLAS_PERMANENCIAS_MUNICIPIO": "Multiplas permanencias no municipio - necessita verificacao.",
    "SEM_REGISTROS_MUNICIPIO": "Sem registros no municipio dentro da janela da viagem.",
    "PROCESSAMENTO_COM_ERRO": "Erro tecnico durante o processamento.",
}

SPECIAL_OPERATIONAL_MUNICIPALITIES = {
    ("PARANAGUA", "PR"): "Paranagua",
    ("SANTOS", "SP"): "Santos",
}

CROSS_DEFAULTS: dict[str, object] = {
    "lcte_id": 0,
    "chave_viagem": "",
    "cte": "",
    "nf": "",
    "chave_nf": "",
    "placa_norm": "",
    "placas_composicao": "",
    "data_operacao": "",
    "data_hora_carga": "",
    "data_inicio_viagem_referencia": "",
    "fonte_data_inicio_viagem": "",
    "origem": "",
    "uf_origem": "",
    "destino": "",
    "uf_destino": "",
    "cliente": "",
    "motorista": "",
    "status_lcte": "",
    "status_control": "",
    "status_rastreador": "",
    "pontuacao_control": 0,
    "classificacao_control": "",
    "criterios_control_json": "{}",
    "control_id": 0,
    "encontrou_lcte": 0,
    "encontrou_control": 0,
    "encontrou_rastreador": 0,
    "encontrou_origem": 0,
    "encontrou_destino": 0,
    "calculou_estadia": 0,
    "existe_control": 0,
    "existe_rastreador": 0,
    "qtd_registros_control": 0,
    "qtd_registros_rastreador": 0,
    "fonte_janela": "",
    "inicio_janela": "",
    "fim_janela": "",
    "qtd_total_pontos_placa": 0,
    "primeira_data_control": "",
    "ultima_data_control": "",
    "primeira_data_rastreador": "",
    "ultima_data_rastreador": "",
    "chegada_origem": "",
    "saida_origem": "",
    "chegada_destino": "",
    "saida_destino": "",
    "control_chegada_origem": "",
    "control_saida_origem": "",
    "control_chegada_destino": "",
    "control_saida_destino": "",
    "diferenca_chegada_origem_min": 0,
    "diferenca_saida_origem_min": 0,
    "diferenca_chegada_destino_min": 0,
    "diferenca_saida_destino_min": 0,
    "maior_divergencia_min": 0,
    "media_divergencias_min": 0,
    "eventos_comparaveis": 0,
    "eventos_sem_control": 0,
    "eventos_sem_rastreador": 0,
    "dentro_tolerancia_control_rastreador": 0,
    "tolerancia_control_rastreador_min": 30,
    "tempo_origem_min": 0,
    "tempo_destino_min": 0,
    "regra_especial_origem": 0,
    "regra_especial_destino": 0,
    "municipio_operacional_origem": "",
    "municipio_operacional_destino": "",
    "metodo_localizacao_origem": "",
    "metodo_localizacao_destino": "",
    "qtd_blocos_municipio_origem": 0,
    "qtd_blocos_municipio_destino": 0,
    "bloco_selecionado_origem": "",
    "bloco_selecionado_destino": "",
    "referencias_visitadas_origem": "",
    "referencias_visitadas_destino": "",
    "motivo_escolha_bloco_origem": "",
    "motivo_escolha_bloco_destino": "",
    "confianca_permanencia_origem_pct": 0,
    "confianca_permanencia_destino_pct": 0,
    "motivo_confirmacao_saida_origem": "",
    "motivo_confirmacao_saida_destino": "",
    "interrupcoes_ignoradas_origem": 0,
    "interrupcoes_ignoradas_destino": 0,
    "maior_distancia_temporaria_cerca_origem_km": 0,
    "maior_distancia_temporaria_cerca_destino_km": 0,
    "tempo_oscilacao_absorvido_origem_min": 0,
    "tempo_oscilacao_absorvido_destino_min": 0,
    "tempo_operacional_min": 0,
    "tempo_transito_min": 0,
    "tempo_total_viagem_min": 0,
    "tempo_control_min": 0,
    "tempo_rastreador_min": 0,
    "diferenca_control_rastreador_min": 0,
    "km_percorrido": 0,
    "distancia_ponto_carga_km": 0,
    "distancia_ponto_descarga_km": 0,
    "pontos_origem": 0,
    "pontos_destino": 0,
    "franquia_carga_min": 0,
    "franquia_descarga_min": 0,
    "estadia_carga_min": 0,
    "estadia_descarga_min": 0,
    "horas_estadia": 0,
    "elegivel_cobranca": 0,
    "motivo_nao_elegibilidade": "",
    "horario_agendado_carga": "",
    "horario_agendado_descarga": "",
    "diferenca_agendamento_carga_min": 0,
    "diferenca_agendamento_descarga_min": 0,
    "dentro_limite_operacional": 1,
    "observacao_manual": "",
    "valor_estimado_estadia": 0,
    "status_cruzamento": "",
    "painel_atual": "",
    "status_processamento": "",
    "status_permanencia": "",
    "status_estadia": "",
    "status_verificacao": "",
    "status_tratativa": "",
    "status_retorno": "",
    "status_cte": "",
    "concluido": 0,
    "tratado": 0,
    "precisa_verificar": 0,
    "tipo_conclusao": "",
    "observacao_conclusao": "",
    "usuario_conclusao": "",
    "data_hora_conclusao": "",
    "data_limite_retorno": "",
    "dias_restantes": 0,
    "retorno_recebido": 0,
    "data_retorno": "",
    "status_prazo": "",
    "protocolo": "",
    "valor_solicitado": 0,
    "valor_aprovado": 0,
    "codigo_motivo": "",
    "descricao_motivo": "",
    "motivo_falha": "",
    "diagnostico_json": "{}",
    "log_processamento_json": "[]",
}


def _emit_progress(progress_callback: ProgressCallback | None, current: int, total: int, message: str) -> None:
    if not progress_callback:
        return
    try:
        progress_callback(int(current), max(int(total), 1), message)
    except Exception:
        pass


def _complete_row(row: dict[str, object]) -> dict[str, object]:
    return {**CROSS_DEFAULTS, **row}


def _minutes(value: float | int | None) -> float:
    return round(float(value or 0), 2)


def _format_minutes(value: Any) -> str:
    total = int(round(float(value or 0)))
    hours, minutes = divmod(total, 60)
    return f"{hours}h {minutes:02d}min"


def _to_datetime(value: Any) -> datetime | None:
    if value in [None, ""]:
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        parsed = pd.to_datetime(value, errors="coerce", dayfirst=True)
    return None if pd.isna(parsed) else parsed.to_pydatetime()


def _safe_float(value: Any) -> float | None:
    try:
        if value in [None, ""] or pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def _has_coordinates(lat: Any, lon: Any) -> bool:
    ref_lat = _safe_float(lat)
    ref_lon = _safe_float(lon)
    if ref_lat is None or ref_lon is None:
        return False
    return not (abs(ref_lat) < 0.000001 and abs(ref_lon) < 0.000001)


def _config_number(config: dict[str, str], key: str, default: float) -> float:
    value = str(config.get(key) or "").replace(",", ".").strip()
    try:
        return float(value) if value else default
    except ValueError:
        return default


def _read_config_values() -> dict[str, str]:
    df = repository.read_config()
    if df.empty:
        return {}
    return {str(row.get("chave") or ""): str(row.get("valor") or "") for row in df.to_dict(orient="records")}


def _ensure_datetime_column(df: pd.DataFrame, column: str, out_column: str) -> pd.DataFrame:
    view = df.copy()
    if column not in view.columns:
        view[out_column] = pd.NaT
        return view
    parsed = pd.to_datetime(view[column], errors="coerce")
    missing = parsed.isna()
    if missing.any():
        parsed.loc[missing] = pd.to_datetime(view.loc[missing, column], errors="coerce", dayfirst=True)
    view[out_column] = parsed
    return view


def _location_tokens(value: Any) -> set[str]:
    text = normalize_text(value)
    tokens = set(re.findall(r"[A-Z0-9]{3,}", text))
    return {token for token in tokens if token not in STOP_WORDS}


def _row_location_text(row: pd.Series, columns: list[str]) -> str:
    return normalize_text(" ".join(str(row.get(column) or "") for column in columns if column in row.index))


def _location_match_text(left: Any, right: Any) -> bool:
    left_tokens = _location_tokens(left)
    right_text = normalize_text(right)
    return bool(left_tokens and any(token in right_text for token in left_tokens))


def _location_mask(df: pd.DataFrame, location: str, columns: list[str]) -> pd.Series:
    if df.empty:
        return pd.Series(dtype=bool)
    return df.apply(lambda row: _location_match_text(location, _row_location_text(row, columns)), axis=1)


def _doc_set(value: Any) -> set[str]:
    if value in [None, ""]:
        return set()
    try:
        if pd.isna(value):
            return set()
    except Exception:
        pass
    pieces = re.split(r"[\s,;/|\\-]+", str(value).replace("\n", " "))
    docs = {normalize_document_number(piece) for piece in pieces}
    docs.discard("")
    return docs


def _normalize_plate_candidate(value: Any) -> str:
    text = re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()
    return text if PLATE_PATTERN.fullmatch(text) else ""


def _trip_plate_candidates(trip: pd.Series) -> list[str]:
    plates: list[str] = []
    principal = _normalize_plate_candidate(trip.get("placa_norm"))
    if principal:
        plates.append(principal)
    composition = str(trip.get("placas_composicao") or "").upper()
    for match in PLATE_PATTERN.findall(composition):
        plates.append(match)
    return list(dict.fromkeys(plates))


def _same_doc(row: pd.Series, trip: pd.Series) -> bool:
    trip_nfs = _doc_set(trip.get("nf"))
    row_nfs = _doc_set(row.get("nf")) if "nf" in row.index else set()
    if trip_nfs and row_nfs and trip_nfs.intersection(row_nfs):
        return True
    docs = _doc_set(trip.get("cte")) | _doc_set(trip.get("pedido")) | _doc_set(trip.get("romaneio")) | _doc_set(trip.get("numero_viagem"))
    if not docs:
        return False
    for column in ["cte", "numero_documento", "pedido", "viagem"]:
        if column in row.index and _doc_set(row.get(column)).intersection(docs):
            return True
    return False


def _control_has_document(row: pd.Series) -> bool:
    for column in ["nf", "cte", "numero_documento", "pedido", "viagem"]:
        if column in row.index and _doc_set(row.get(column)):
            return True
    return False


def _trip_reference_datetime(trip: pd.Series) -> datetime | None:
    return _to_datetime(trip.get("data_hora_carga")) or _to_datetime(trip.get("data_emissao")) or _to_datetime(trip.get("data_operacao"))


def _trip_primary_plate(trip: pd.Series | dict[str, Any]) -> str:
    if isinstance(trip, pd.Series):
        return _normalize_plate_candidate(trip.get("placa_norm"))
    return _normalize_plate_candidate(trip.get("placa_norm"))


def _date_window(trip: pd.Series, config: dict[str, str]) -> tuple[datetime | None, datetime | None, str]:
    base = _trip_reference_datetime(trip)
    if not base:
        return None, None, "LCTE_SEM_DATA_REFERENCIA"
    hours_before = _config_number(config, "janela_lcte_horas_antes", 24)
    days_after = _config_number(config, "janela_lcte_dias_depois", 7)
    start = base - timedelta(hours=max(hours_before, 0))
    end = base + timedelta(days=max(days_after, 1))
    return start, end, "LCTE_EMISSAO"


def _score_control_row(row: pd.Series, trip: pd.Series) -> tuple[float, dict[str, Any]]:
    criteria: dict[str, Any] = {}
    score = 0.0
    plate_ok = str(row.get("placa_norm") or "") in set(_trip_plate_candidates(trip))
    criteria["placa"] = 35 if plate_ok else 0
    score += criteria["placa"]

    nf_ok = bool(_doc_set(trip.get("nf")) and _doc_set(row.get("nf")) and _doc_set(trip.get("nf")).intersection(_doc_set(row.get("nf"))))
    criteria["nf"] = 35 if nf_ok else 0
    score += criteria["nf"]

    trip_dt = _to_datetime(trip.get("data_hora_carga")) or _to_datetime(trip.get("data_operacao"))
    row_dt = _to_datetime(row.get("data_hora_inicio")) or _to_datetime(row.get("data_inicio"))
    date_ok = bool(trip_dt and row_dt and abs((row_dt - trip_dt).total_seconds()) <= 48 * 3600)
    criteria["data"] = 5 if date_ok else 0
    score += criteria["data"]

    origem_ok = _location_match_text(trip.get("origem"), " ".join(str(row.get(c) or "") for c in ["local_origem", "local_evento", "observacao"]))
    destino_ok = _location_match_text(trip.get("destino"), " ".join(str(row.get(c) or "") for c in ["local_destino", "local_evento", "observacao"]))
    criteria["origem"] = 10 if origem_ok else 0
    criteria["destino"] = 10 if destino_ok else 0
    score += criteria["origem"] + criteria["destino"]

    motorista_ok = bool(normalize_text(row.get("motorista")) and normalize_text(row.get("motorista")) == normalize_text(trip.get("motorista")))
    criteria["motorista"] = 5 if motorista_ok else 0
    score += criteria["motorista"]

    doc_ok = _same_doc(row, trip)
    criteria["documento"] = 1 if doc_ok else 0
    criteria["pontuacao_total"] = min(score, 100)
    return min(score, 100), criteria


def _classify_score(score: float) -> str:
    if score >= 85:
        return "CONFIRMADO"
    if score >= 70:
        return "PROVAVEL"
    if score >= 50:
        return "REVISAO_MANUAL"
    return "NAO_RELACIONADO"


def _select_control_matches(
    control: pd.DataFrame,
    trip: pd.Series,
    log: list[str],
    used_control_ids: set[int] | None = None,
) -> tuple[pd.DataFrame, float, str, dict[str, Any], str]:
    if control.empty:
        return pd.DataFrame(), 0, "NAO_RELACIONADO", {}, "CONTROL_NAO_LOCALIZADO"
    plates = _trip_plate_candidates(trip)
    candidates = control[control["placa_norm"].fillna("").astype(str).isin(plates)].copy() if plates else pd.DataFrame()
    log.append(f"CONTROL: {len(candidates)} candidato(s) pela(s) placa(s) {', '.join(plates) or '-'}")
    if candidates.empty:
        return candidates, 0, "NAO_RELACIONADO", {}, "CONTROL_NAO_LOCALIZADO"
    if used_control_ids and "id" in candidates.columns:
        before_used_filter = len(candidates)
        control_ids = pd.to_numeric(candidates["id"], errors="coerce").fillna(0).astype(int)
        candidates = candidates[~control_ids.isin(used_control_ids)].copy()
        removed = before_used_filter - len(candidates)
        if removed:
            log.append(f"CONTROL: {removed} candidato(s) ignorado(s) por ja estarem vinculados a outra viagem.")
        if candidates.empty:
            return pd.DataFrame(), 0, "NAO_RELACIONADO", {}, "CONTROL_JA_UTILIZADO"
    documented_mask = candidates.apply(_control_has_document, axis=1)
    doc_candidates = candidates[candidates.apply(lambda row: _same_doc(row, trip), axis=1)]
    log.append(f"CONTROL: {len(doc_candidates)} candidato(s) com NF/CT-e em comum.")
    if not doc_candidates.empty:
        candidates = doc_candidates.copy()
        log.append("CONTROL: candidatos restringidos pelo documento em comum.")
    elif documented_mask.any():
        candidates_without_doc = candidates[~documented_mask].copy()
        if candidates_without_doc.empty:
            log.append("CONTROL: registros da placa existem, mas todos possuem documento diferente do LCTE.")
            return pd.DataFrame(), 0, "NAO_RELACIONADO", {}, "CONTROL_DOCUMENTO_DIVERGENTE"
        candidates = candidates_without_doc
        log.append("CONTROL: registros com documento divergente ignorados; avaliando apenas registros sem documento.")
    scored = []
    for idx, row in candidates.iterrows():
        score, criteria = _score_control_row(row, trip)
        scored.append((idx, score, criteria))
    scored.sort(key=lambda item: item[1], reverse=True)
    best_idx, best_score, best_criteria = scored[0]
    classification = _classify_score(best_score)
    probable = [item for item in scored if item[1] >= 50]
    reason = "CONTROL_MULTIPLAS_CORRESPONDENCIAS" if len(probable) > 1 and not best_criteria.get("nf") else ""
    if classification == "NAO_RELACIONADO":
        return pd.DataFrame(), best_score, classification, best_criteria, "CONTROL_NAO_LOCALIZADO"
    if classification == "REVISAO_MANUAL":
        reason = reason or "VINCULO_AGUARDANDO_REVISAO"
    selected = candidates.loc[[best_idx]].copy()
    log.append(f"CONTROL: melhor pontuacao {best_score} ({classification}).")
    return selected, best_score, classification, best_criteria, reason


def _tracker_window_bounds(
    trip: pd.Series,
    control_matches: pd.DataFrame,
    config: dict[str, str],
    log: list[str],
    previous_trip_dt: datetime | None = None,
    next_trip_dt: datetime | None = None,
) -> tuple[datetime | None, datetime | None, str]:
    lcte_start, lcte_end, source = _date_window(trip, config)
    start, end = lcte_start, lcte_end
    if control_matches.empty:
        if start and end:
            log.append("RASTREADOR: janela definida pelo LCTE porque nao houve CONTROL confirmado.")
        else:
            log.append("RASTREADOR: LCTE sem data valida para definir janela.")
    else:
        control_start = _to_datetime(control_matches.iloc[0].get("data_hora_inicio")) or _to_datetime(control_matches.iloc[0].get("data_inicio"))
        control_end = _to_datetime(control_matches.iloc[0].get("data_hora_fim")) or _to_datetime(control_matches.iloc[0].get("data_fim"))
        hours_before = _config_number(config, "janela_control_horas_antes", 12)
        hours_after = _config_number(config, "janela_control_horas_depois", 24)
        if control_start:
            start = control_start - timedelta(hours=max(hours_before, 0))
        if control_end:
            end = control_end + timedelta(hours=max(hours_after, 0))
        source = "CONTROL_OPERACIONAL"
        log.append("RASTREADOR: janela definida pelo CONTROL como referencia operacional, sem presumir chegada ou saida.")
    if start and previous_trip_dt and start < previous_trip_dt:
        start = previous_trip_dt
        log.append("RASTREADOR: inicio da janela limitado pela viagem LCTE anterior da mesma placa.")
    if end and next_trip_dt and end > next_trip_dt:
        limited_end = next_trip_dt - timedelta(minutes=1)
        if start and limited_end <= start:
            limited_end = next_trip_dt
        end = limited_end
        log.append("RASTREADOR: fim da janela limitado pela proxima viagem LCTE da mesma placa.")
    return start, end, source


def _dt_sql(value: datetime | None) -> str:
    return value.isoformat(sep=" ", timespec="seconds") if value else ""


def _filter_tracker_for_trip(
    rastreador: pd.DataFrame,
    trip: pd.Series,
    control_matches: pd.DataFrame,
    config: dict[str, str],
    log: list[str],
    previous_trip_dt: datetime | None = None,
    next_trip_dt: datetime | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    plates = _trip_plate_candidates(trip)
    window_info: dict[str, Any] = {"fonte": "", "inicio": None, "fim": None, "total_pontos_placa": 0, "pontos_janela": 0}
    if not plates:
        log.append("RASTREADOR: placa LCTE ausente.")
        return pd.DataFrame(), window_info
    start, end, source = _tracker_window_bounds(trip, control_matches, config, log, previous_trip_dt, next_trip_dt)
    window_info.update({"fonte": source, "inicio": start, "fim": end})
    view = rastreador[rastreador["placa_norm"].fillna("").astype(str).isin(plates)].copy()
    window_info["total_pontos_placa"] = int(len(view))
    log.append(f"RASTREADOR: {len(view)} registro(s) encontrados para placa(s) {', '.join(plates)}.")
    if view.empty:
        return view, window_info
    view = _ensure_datetime_column(view, "data_hora", "_data_dt")
    if start and end:
        view = view[view["_data_dt"].between(start, end)].copy()
        log.append(f"RASTREADOR: {len(view)} registro(s) na janela {start} a {end}.")
    window_info["pontos_janela"] = int(len(view))
    return view.sort_values("_data_dt"), window_info


def _filter_tracker_for_trip_from_db(
    trip: pd.Series,
    control_matches: pd.DataFrame,
    config: dict[str, str],
    log: list[str],
    plate_count_cache: dict[str, int] | None = None,
    previous_trip_dt: datetime | None = None,
    next_trip_dt: datetime | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    plates = _trip_plate_candidates(trip)
    window_info: dict[str, Any] = {"fonte": "", "inicio": None, "fim": None, "total_pontos_placa": 0, "pontos_janela": 0}
    if not plates:
        log.append("RASTREADOR: placa LCTE ausente.")
        return pd.DataFrame(), window_info

    start, end, source = _tracker_window_bounds(trip, control_matches, config, log, previous_trip_dt, next_trip_dt)
    window_info.update({"fonte": source, "inicio": start, "fim": end})
    cache_key = "|".join(plates)
    if plate_count_cache is not None and cache_key in plate_count_cache:
        total_plate = plate_count_cache[cache_key]
    else:
        total_plate = repository.count_rastreador_plates(plates)
        if plate_count_cache is not None:
            plate_count_cache[cache_key] = total_plate
    window_info["total_pontos_placa"] = total_plate
    log.append(f"RASTREADOR: {total_plate} registro(s) encontrados para placa(s) {', '.join(plates)}.")
    if total_plate <= 0:
        return pd.DataFrame(), window_info

    if not start or not end:
        log.append("RASTREADOR: janela de busca nao definida.")
        return pd.DataFrame(), window_info

    view = repository.read_rastreador_period_for_plates(plates, _dt_sql(start), _dt_sql(end), 120000)
    if not view.empty:
        view = _ensure_datetime_column(view, "data_hora", "_data_dt").sort_values("_data_dt")
    window_info["pontos_janela"] = int(len(view))
    log.append(f"RASTREADOR: {len(view)} registro(s) na janela {start} a {end}.")
    return view, window_info


def _stopped_mask(df: pd.DataFrame) -> pd.Series:
    if df.empty:
        return pd.Series(dtype=bool)
    mask = pd.Series([True] * len(df), index=df.index)
    if "velocidade" in df.columns:
        speed = pd.to_numeric(df["velocidade"], errors="coerce")
        speed_mask = speed.isna() | speed.le(5)
        if speed_mask.any():
            mask &= speed_mask
    if "ignicao" in df.columns:
        ignition = df["ignicao"].fillna("").astype(str).map(normalize_text)
        ignition_mask = ignition.eq("") | ignition.str.contains("DESL|OFF|FALSE|FALSO|PARAD|0|NAO", regex=True)
        if ignition_mask.any():
            mask &= ignition_mask
    return mask


def _location_mask_with_geo(df: pd.DataFrame, location: str, lat: Any, lon: Any, config: dict[str, str]) -> pd.Series:
    if df.empty:
        return pd.Series(dtype=bool)
    text_mask = _location_mask(df, location, ["endereco", "cidade", "uf", "evento", "status"])
    ref_lat = _safe_float(lat)
    ref_lon = _safe_float(lon)
    if not _has_coordinates(lat, lon) or "latitude" not in df.columns or "longitude" not in df.columns:
        return text_mask.reindex(df.index, fill_value=False)

    radius_meters = _config_number(config, "raio_metros_local", 1000)
    extra_meters = _config_number(config, "tolerancia_raio_extra_metros", 300)
    distances = []
    for _, row in df.iterrows():
        row_lat = _safe_float(row.get("latitude"))
        row_lon = _safe_float(row.get("longitude"))
        if row_lat is None or row_lon is None:
            distances.append(float("inf"))
        else:
            distances.append(_haversine_km(ref_lat, ref_lon, row_lat, row_lon) * 1000)
    geo_mask = pd.Series(distances, index=df.index).le(radius_meters + extra_meters)
    return (text_mask | geo_mask).reindex(df.index, fill_value=False)


def _location_city_uf(location: Any, uf: Any = "") -> tuple[str, str]:
    text = normalize_text(location)
    explicit_uf = normalize_text(uf)
    for separator in ["/", "-", "|", ","]:
        text = text.replace(separator, " ")
    tokens = [token for token in re.findall(r"[A-Z0-9]+", text) if token not in STOP_WORDS]
    uf_value = explicit_uf[:2] if explicit_uf else ""
    for token in reversed(tokens):
        if len(token) == 2 and token.isalpha():
            uf_value = uf_value or token
            tokens.remove(token)
            break
    city = " ".join(tokens)
    return city, uf_value


def _special_municipality(location: Any, uf: Any = "") -> tuple[str, str, str] | None:
    city, uf_value = _location_city_uf(location, uf)
    for (special_city, special_uf), label in SPECIAL_OPERATIONAL_MUNICIPALITIES.items():
        if special_city in city and (not uf_value or uf_value == special_uf):
            return special_city, special_uf, label
    return None


def _municipality_mask(df: pd.DataFrame, city: str, uf: str) -> pd.Series:
    if df.empty:
        return pd.Series(dtype=bool)
    city_text = df.get("cidade", pd.Series("", index=df.index)).fillna("").astype(str).map(normalize_text)
    uf_text = df.get("uf", pd.Series("", index=df.index)).fillna("").astype(str).map(normalize_text)
    text = df.apply(lambda row: _row_location_text(row, ["endereco", "cidade", "uf", "evento", "status"]), axis=1)
    city_ok = city_text.str.contains(city, regex=False) | text.str.contains(city, regex=False)
    uf_ok = uf_text.eq("") | uf_text.eq(uf) | text.str.contains(f" {uf} ", regex=False) | text.str.endswith(f" {uf}")
    return (city_ok & uf_ok).reindex(df.index, fill_value=False)


def _municipality_block_rows(stay: dict[str, Any], ordered: pd.DataFrame) -> pd.DataFrame:
    arrival = pd.Timestamp(stay["arrival"])
    departure = pd.Timestamp(stay["departure"])
    return ordered[ordered["_data_dt"].between(arrival, departure)].copy()


def _municipality_references(rows: pd.DataFrame) -> str:
    if rows.empty:
        return ""
    values: list[str] = []
    for column in ["endereco", "cidade", "evento", "status"]:
        if column in rows.columns:
            for value in rows[column].fillna("").astype(str).tolist():
                clean = str(value).strip()
                if clean and clean not in values:
                    values.append(clean)
                if len(values) >= 8:
                    break
        if len(values) >= 8:
            break
    return "; ".join(values)


def _municipality_blocks(df: pd.DataFrame, city: str, uf: str, config: dict[str, str]) -> tuple[list[dict[str, Any]], pd.Series]:
    if df.empty:
        return [], pd.Series(dtype=bool)
    ordered = df.dropna(subset=["_data_dt"]).sort_values("_data_dt").copy()
    if ordered.empty:
        return [], pd.Series(dtype=bool)
    mask = _municipality_mask(ordered, city, uf)
    stays = _stays_from_mask(ordered, mask, config, split_by_reference=True)
    for index, stay in enumerate(stays, start=1):
        block_rows = _municipality_block_rows(stay, ordered)
        stay["block_index"] = index
        stay["method"] = "municipio_uf_rastreador"
        stay["references"] = _municipality_references(block_rows)
        stay["distance_km"] = _minutes(_km_percorrido(block_rows) or 0)
    return stays, mask


def _select_municipality_block(
    stays: list[dict[str, Any]],
    kind: str,
    reference_dt: datetime | None,
    after_dt: datetime | None = None,
    trip: pd.Series | None = None,
    used_tracker_stays: set[tuple[str, str, str, str]] | None = None,
) -> tuple[dict[str, Any] | None, str]:
    if not stays:
        return None, "Sem registros no municipio dentro da janela da viagem."
    candidates = list(stays)
    if kind == "DESTINO" and after_dt:
        candidates = [stay for stay in candidates if stay["arrival"] > after_dt] or [stay for stay in candidates if stay["departure"] > after_dt]
    if not candidates:
        return None, "Sem bloco compativel com a sequencia da viagem."
    if trip is not None:
        available = _available_stays(candidates, trip, kind, used_tracker_stays)
        if not available:
            return None, "Bloco de permanencia ja vinculado a outra viagem LCTE."
        candidates = available
    if len(candidates) > 1:
        reason = "Multiplas permanencias no municipio - necessita verificacao."
    else:
        reason = "Bloco unico compativel com a viagem."
    if reference_dt:
        selected = min(candidates, key=lambda stay: abs((stay["arrival"] - reference_dt).total_seconds()))
    else:
        selected = candidates[0] if kind == "ORIGEM" else min(candidates, key=lambda stay: stay["arrival"])
    return selected, reason


def _apply_special_municipality_stay(
    result: dict[str, Any],
    ordered: pd.DataFrame,
    trip: pd.Series,
    config: dict[str, str],
    log: list[str],
    kind: str,
    after_dt: datetime | None = None,
    used_tracker_stays: set[tuple[str, str, str, str]] | None = None,
) -> list[str]:
    reason_codes: list[str] = []
    if kind == "ORIGEM":
        location = trip.get("origem")
        uf = trip.get("uf_origem")
        prefix = "origem"
        label_found = "encontrou_origem"
        arrival_key = "chegada_origem"
        departure_key = "saida_origem"
        minutes_key = "tempo_origem"
        points_key = "pontos_origem"
    else:
        location = trip.get("destino")
        uf = trip.get("uf_destino")
        prefix = "destino"
        label_found = "encontrou_destino"
        arrival_key = "chegada_destino"
        departure_key = "saida_destino"
        minutes_key = "tempo_destino"
        points_key = "pontos_destino"
    special = _special_municipality(location, uf)
    if not special:
        return reason_codes
    city, city_uf, label = special
    blocks, mask = _municipality_blocks(ordered, city, city_uf, config)
    reference_dt = after_dt if kind == "DESTINO" and after_dt else _trip_reference_datetime(trip)
    selected, choice_reason = _select_municipality_block(blocks, kind, reference_dt, after_dt, trip, used_tracker_stays)
    result[f"regra_especial_{prefix}"] = 1
    result[f"municipio_operacional_{prefix}"] = f"{label}/{city_uf}"
    result[f"metodo_localizacao_{prefix}"] = "municipio_uf_rastreador"
    result[f"qtd_blocos_municipio_{prefix}"] = len(blocks)
    result[f"motivo_escolha_bloco_{prefix}"] = choice_reason
    result[points_key] = int(mask.sum()) if not mask.empty else 0
    if len(blocks) > 1:
        reason_codes.append("MULTIPLAS_PERMANENCIAS_MUNICIPIO")
    if selected is None:
        if "ja vinculado" in choice_reason:
            reason_codes.append("RASTREADOR_PERMANENCIA_JA_UTILIZADA")
        else:
            reason_codes.append("SEM_REGISTROS_MUNICIPIO")
        log.append(f"RASTREADOR: {label} nao selecionado. {choice_reason}")
        return reason_codes
    _mark_stay_used(trip, kind, selected, used_tracker_stays)
    result.update(
        {
            arrival_key: selected["arrival"],
            departure_key: selected["departure"],
            minutes_key: selected["minutes"],
            label_found: True,
            points_key: selected["points"],
            f"confianca_{prefix}_pct": selected.get("confidence_pct", 0),
            f"motivo_saida_{prefix}": selected.get("exit_reason", ""),
            f"interrupcoes_ignoradas_{prefix}": selected.get("ignored_interruptions", 0),
            f"maior_distancia_temporaria_{prefix}_km": selected.get("max_temp_distance_km", 0),
            f"tempo_oscilacao_absorvido_{prefix}": selected.get("oscillation_absorbed_min", 0),
            f"bloco_selecionado_{prefix}": f"{selected.get('block_index')} | {selected['arrival']} > {selected['departure']}",
            f"referencias_visitadas_{prefix}": selected.get("references", ""),
        }
    )
    log.append(f"RASTREADOR: {label} calculado pela permanencia no municipio ({kind.lower()}). {choice_reason}")
    if int(selected.get("ignored_interruptions") or 0):
        log.append("RASTREADOR: saida temporaria ignorada; veiculo retornou ao municipio.")
    return reason_codes


def _distance_series_meters(df: pd.DataFrame, lat: Any, lon: Any) -> pd.Series:
    if df.empty:
        return pd.Series(dtype=float)
    ref_lat = _safe_float(lat)
    ref_lon = _safe_float(lon)
    if ref_lat is None or ref_lon is None or "latitude" not in df.columns or "longitude" not in df.columns:
        return pd.Series([float("nan")] * len(df), index=df.index)
    distances: list[float] = []
    for _, row in df.iterrows():
        row_lat = _safe_float(row.get("latitude"))
        row_lon = _safe_float(row.get("longitude"))
        if row_lat is None or row_lon is None:
            distances.append(float("nan"))
        else:
            distances.append(_haversine_km(ref_lat, ref_lon, row_lat, row_lon) * 1000)
    return pd.Series(distances, index=df.index)


def _tracker_reference_signature(row: pd.Series) -> str:
    signature = normalize_text(row.get("endereco"))
    if signature:
        return signature
    return normalize_text(" ".join(str(row.get(column) or "") for column in ["cidade", "uf", "evento", "status"]))


def _new_stay(current_dt: pd.Timestamp) -> dict[str, Any]:
    return {
        "arrival": current_dt.to_pydatetime(),
        "departure": current_dt.to_pydatetime(),
        "points": 0,
        "reference_signature": "",
        "ignored_interruptions": 0,
        "oscillation_absorbed_min": 0.0,
        "max_temp_distance_m": 0.0,
        "exit_reason": "",
        "exit_criteria": [],
    }


def _outside_exit_metrics(outside_rows: pd.DataFrame, distance_meters: pd.Series, config: dict[str, str]) -> dict[str, Any]:
    if outside_rows.empty:
        return {"confirmed": False, "criteria": [], "outside_minutes": 0.0, "max_distance_m": 0.0, "avg_speed": 0.0}
    ordered = outside_rows.dropna(subset=["_data_dt"]).sort_values("_data_dt")
    if ordered.empty:
        return {"confirmed": False, "criteria": [], "outside_minutes": 0.0, "max_distance_m": 0.0, "avg_speed": 0.0}
    outside_minutes = max((ordered["_data_dt"].iloc[-1] - ordered["_data_dt"].iloc[0]).total_seconds() / 60, 0)
    distances = pd.to_numeric(distance_meters.reindex(ordered.index), errors="coerce").dropna()
    max_distance_m = float(distances.max()) if not distances.empty else 0.0
    speed = pd.to_numeric(ordered.get("velocidade", pd.Series(dtype=float)), errors="coerce").dropna()
    avg_speed = float(speed.mean()) if not speed.empty else 0.0
    required_minutes = _config_number(config, "saida_confirmacao_minutos", 20)
    required_distance_m = _config_number(config, "saida_distancia_confirmacao_km", 2) * 1000
    required_points = int(_config_number(config, "saida_posicoes_consecutivas", 3))
    required_speed = _config_number(config, "saida_velocidade_media_kmh", 15)
    criteria: list[str] = []
    if outside_minutes > required_minutes:
        criteria.append(f"fora da cerca por {round(outside_minutes, 2)} min")
    if not distances.empty and max_distance_m >= required_distance_m:
        diffs = distances.diff().dropna()
        increasing = bool(diffs.empty or diffs.ge(-50).all())
        if increasing:
            criteria.append(f"distancia crescente ate {round(max_distance_m / 1000, 3)} km")
    if len(ordered) >= required_points:
        criteria.append(f"{len(ordered)} posicoes consecutivas fora")
    if avg_speed > required_speed:
        criteria.append(f"velocidade media {round(avg_speed, 2)} km/h")
    return {
        "confirmed": len(criteria) >= 2 and len(ordered) >= 2,
        "criteria": criteria,
        "outside_minutes": outside_minutes,
        "max_distance_m": max_distance_m,
        "avg_speed": avg_speed,
    }


def _absorb_possible_exit(current: dict[str, Any], outside_rows: pd.DataFrame, distance_meters: pd.Series, return_dt: pd.Timestamp | None = None) -> None:
    if outside_rows.empty:
        return
    ordered = outside_rows.dropna(subset=["_data_dt"]).sort_values("_data_dt")
    if ordered.empty:
        return
    end_dt = return_dt or ordered["_data_dt"].iloc[-1]
    outside_minutes = max((end_dt - ordered["_data_dt"].iloc[0]).total_seconds() / 60, 0)
    distances = pd.to_numeric(distance_meters.reindex(ordered.index), errors="coerce").dropna()
    max_distance_m = float(distances.max()) if not distances.empty else 0.0
    current["ignored_interruptions"] = int(current.get("ignored_interruptions") or 0) + 1
    current["oscillation_absorbed_min"] = _minutes(float(current.get("oscillation_absorbed_min") or 0) + outside_minutes)
    current["max_temp_distance_m"] = max(float(current.get("max_temp_distance_m") or 0), max_distance_m)


def _finish_stay(stay: dict[str, Any]) -> dict[str, Any]:
    stay["minutes"] = _minutes(max((stay["departure"] - stay["arrival"]).total_seconds() / 60, 0))
    points = int(stay.get("points") or 0)
    interruptions = int(stay.get("ignored_interruptions") or 0)
    oscillation = float(stay.get("oscillation_absorbed_min") or 0)
    confidence = 100.0
    if points < 3:
        confidence -= 20
    elif points < 5:
        confidence -= 8
    confidence -= min(20, interruptions * 5)
    confidence -= min(20, oscillation / 10)
    if not stay.get("exit_reason"):
        confidence -= 5
    stay["confidence_pct"] = int(round(max(40, min(100, confidence))))
    stay["max_temp_distance_km"] = round(float(stay.get("max_temp_distance_m") or 0) / 1000, 3)
    stay["oscillation_absorbed_min"] = _minutes(stay.get("oscillation_absorbed_min") or 0)
    return stay


def _stay_usage_key(trip: pd.Series, kind: str, stay: dict[str, Any]) -> tuple[str, str, str, str]:
    plate = _trip_primary_plate(trip)
    arrival = stay.get("arrival")
    departure = stay.get("departure")
    arrival_text = arrival.isoformat(sep=" ", timespec="minutes") if hasattr(arrival, "isoformat") else str(arrival or "")
    departure_text = departure.isoformat(sep=" ", timespec="minutes") if hasattr(departure, "isoformat") else str(departure or "")
    return plate, "PERMANENCIA", arrival_text, departure_text


def _available_stays(
    stays: list[dict[str, Any]],
    trip: pd.Series,
    kind: str,
    used_tracker_stays: set[tuple[str, str, str, str]] | None,
) -> list[dict[str, Any]]:
    if not used_tracker_stays:
        return stays
    return [stay for stay in stays if _stay_usage_key(trip, kind, stay) not in used_tracker_stays]


def _mark_stay_used(
    trip: pd.Series,
    kind: str,
    stay: dict[str, Any],
    used_tracker_stays: set[tuple[str, str, str, str]] | None,
) -> None:
    if used_tracker_stays is not None:
        used_tracker_stays.add(_stay_usage_key(trip, kind, stay))


def _stays_from_mask(
    df: pd.DataFrame,
    mask: pd.Series,
    config: dict[str, str],
    split_by_reference: bool = False,
    distance_meters: pd.Series | None = None,
) -> list[dict[str, Any]]:
    if df.empty or not mask.any():
        return []
    ordered = df.dropna(subset=["_data_dt"]).sort_values("_data_dt").copy()
    if ordered.empty:
        return []
    inside = mask.reindex(ordered.index, fill_value=False)
    distances = distance_meters.reindex(ordered.index) if distance_meters is not None else pd.Series([float("nan")] * len(ordered), index=ordered.index)
    min_points = int(_config_number(config, "min_pontos_permanencia", 1))
    stays: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    possible_exit_indexes: list[Any] = []

    for idx, row in ordered.iterrows():
        current_dt = row["_data_dt"]
        is_inside = bool(inside.loc[idx])
        if pd.isna(current_dt):
            continue
        if is_inside:
            row_signature = _tracker_reference_signature(row) if split_by_reference else ""
            if current is None:
                current = _new_stay(current_dt)
                current["reference_signature"] = row_signature
            elif split_by_reference and row_signature and current.get("reference_signature") and row_signature != current.get("reference_signature"):
                if possible_exit_indexes:
                    _absorb_possible_exit(current, ordered.loc[possible_exit_indexes], distances, current_dt)
                    possible_exit_indexes = []
                if current["points"] >= min_points:
                    current["exit_reason"] = current.get("exit_reason") or "mudanca de referencia no mesmo municipio"
                    stays.append(_finish_stay(current))
                current = _new_stay(current_dt)
                current["reference_signature"] = row_signature
            elif possible_exit_indexes:
                outside_rows = ordered.loc[possible_exit_indexes]
                _absorb_possible_exit(current, outside_rows, distances, current_dt)
                possible_exit_indexes = []
            current["departure"] = current_dt.to_pydatetime()
            current["points"] = int(current["points"]) + 1
        elif current is not None:
            possible_exit_indexes.append(idx)
            outside_rows = ordered.loc[possible_exit_indexes]
            exit_metrics = _outside_exit_metrics(outside_rows, distances, config)
            if exit_metrics["confirmed"]:
                current["exit_criteria"] = exit_metrics["criteria"]
                current["exit_reason"] = "; ".join(exit_metrics["criteria"])
                if current["points"] >= min_points:
                    stays.append(_finish_stay(current))
                current = None
                possible_exit_indexes = []

    if current is not None and current["points"] >= min_points:
        if possible_exit_indexes:
            _absorb_possible_exit(current, ordered.loc[possible_exit_indexes], distances)
        stays.append(_finish_stay(current))
    return stays


def _detect_trip_events(
    df: pd.DataFrame,
    trip: pd.Series,
    config: dict[str, str],
    log: list[str],
    used_tracker_stays: set[tuple[str, str, str, str]] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "chegada_origem": None,
        "saida_origem": None,
        "tempo_origem": 0,
        "encontrou_origem": False,
        "pontos_origem": 0,
        "chegada_destino": None,
        "saida_destino": None,
        "tempo_destino": 0,
        "encontrou_destino": False,
        "pontos_destino": 0,
        "distancia_origem_min_km": None,
        "distancia_destino_min_km": None,
        "regra_especial_origem": 0,
        "regra_especial_destino": 0,
        "municipio_operacional_origem": "",
        "municipio_operacional_destino": "",
        "metodo_localizacao_origem": "",
        "metodo_localizacao_destino": "",
        "qtd_blocos_municipio_origem": 0,
        "qtd_blocos_municipio_destino": 0,
        "bloco_selecionado_origem": "",
        "bloco_selecionado_destino": "",
        "referencias_visitadas_origem": "",
        "referencias_visitadas_destino": "",
        "motivo_escolha_bloco_origem": "",
        "motivo_escolha_bloco_destino": "",
        "confianca_origem_pct": 0,
        "confianca_destino_pct": 0,
        "motivo_saida_origem": "",
        "motivo_saida_destino": "",
        "interrupcoes_ignoradas_origem": 0,
        "interrupcoes_ignoradas_destino": 0,
        "maior_distancia_temporaria_origem_km": 0,
        "maior_distancia_temporaria_destino_km": 0,
        "tempo_oscilacao_absorvido_origem": 0,
        "tempo_oscilacao_absorvido_destino": 0,
    }
    if df.empty:
        return result
    ordered = df.dropna(subset=["_data_dt"]).sort_values("_data_dt").copy()
    if ordered.empty:
        return result

    special_reasons: list[str] = []
    special_reasons.extend(_apply_special_municipality_stay(result, ordered, trip, config, log, "ORIGEM", used_tracker_stays=used_tracker_stays))
    origem_mask = _location_mask_with_geo(ordered, str(trip.get("origem") or ""), trip.get("latitude_origem"), trip.get("longitude_origem"), config)
    destino_mask = _location_mask_with_geo(ordered, str(trip.get("destino") or ""), trip.get("latitude_destino"), trip.get("longitude_destino"), config)
    origem_distances = _distance_series_meters(ordered, trip.get("latitude_origem"), trip.get("longitude_origem"))
    destino_distances = _distance_series_meters(ordered, trip.get("latitude_destino"), trip.get("longitude_destino"))
    result["pontos_origem"] = int(origem_mask.sum())
    result["pontos_destino"] = int(destino_mask.sum())
    result["distancia_origem_min_km"] = _distance_to_point(ordered, trip.get("latitude_origem"), trip.get("longitude_origem"))
    result["distancia_destino_min_km"] = _distance_to_point(ordered, trip.get("latitude_destino"), trip.get("longitude_destino"))
    stopped = _stopped_mask(ordered).reindex(ordered.index, fill_value=True)
    origem_stopped_mask = origem_mask & stopped
    destino_stopped_mask = destino_mask & stopped
    origem_stay_mask = origem_stopped_mask if origem_stopped_mask.any() else origem_mask
    destino_stay_mask = destino_stopped_mask if destino_stopped_mask.any() else destino_mask

    split_origin_by_reference = not _has_coordinates(trip.get("latitude_origem"), trip.get("longitude_origem"))
    split_destination_by_reference = not _has_coordinates(trip.get("latitude_destino"), trip.get("longitude_destino"))
    origin_stays = [] if result["regra_especial_origem"] else _stays_from_mask(ordered, origem_stay_mask, config, split_by_reference=split_origin_by_reference, distance_meters=origem_distances)
    if origin_stays and not result["regra_especial_origem"]:
        available_origin_stays = _available_stays(origin_stays, trip, "ORIGEM", used_tracker_stays)
        if not available_origin_stays:
            special_reasons.append("RASTREADOR_PERMANENCIA_JA_UTILIZADA")
            log.append("RASTREADOR: todos os blocos de origem compativeis ja foram vinculados a outra viagem LCTE.")
        origin_stays = available_origin_stays
    if origin_stays and not result["encontrou_origem"]:
        origin = origin_stays[0]
        _mark_stay_used(trip, "ORIGEM", origin, used_tracker_stays)
        result.update(
            {
                "chegada_origem": origin["arrival"],
                "saida_origem": origin["departure"],
                "tempo_origem": origin["minutes"],
                "encontrou_origem": True,
                "pontos_origem": origin["points"],
                "confianca_origem_pct": origin.get("confidence_pct", 0),
                "motivo_saida_origem": origin.get("exit_reason", ""),
                "interrupcoes_ignoradas_origem": origin.get("ignored_interruptions", 0),
                "maior_distancia_temporaria_origem_km": origin.get("max_temp_distance_km", 0),
                "tempo_oscilacao_absorvido_origem": origin.get("oscillation_absorbed_min", 0),
            }
        )
        log.append(
            f"RASTREADOR: origem identificada em bloco continuo com {origin['points']} ponto(s), "
            f"{origin.get('ignored_interruptions', 0)} oscilacao(oes) absorvida(s)."
        )

    destination_base = ordered
    destination_mask = destino_stay_mask
    destination_distances = destino_distances
    if result["saida_origem"]:
        destination_base = ordered[ordered["_data_dt"] > pd.Timestamp(result["saida_origem"])]
        destination_mask = destino_mask.reindex(destination_base.index, fill_value=False)
        destination_distances = destino_distances.reindex(destination_base.index)
    special_reasons.extend(_apply_special_municipality_stay(result, destination_base, trip, config, log, "DESTINO", result.get("saida_origem"), used_tracker_stays))
    dest_stays = [] if result["regra_especial_destino"] else _stays_from_mask(destination_base, destination_mask, config, split_by_reference=split_destination_by_reference, distance_meters=destination_distances)
    if dest_stays and not result["regra_especial_destino"]:
        available_dest_stays = _available_stays(dest_stays, trip, "DESTINO", used_tracker_stays)
        if not available_dest_stays:
            special_reasons.append("RASTREADOR_PERMANENCIA_JA_UTILIZADA")
            log.append("RASTREADOR: todos os blocos de destino compativeis ja foram vinculados a outra viagem LCTE.")
        dest_stays = available_dest_stays
    if dest_stays and not result["encontrou_destino"]:
        dest = min(dest_stays, key=lambda stay: stay["arrival"])
        _mark_stay_used(trip, "DESTINO", dest, used_tracker_stays)
        result.update(
            {
                "chegada_destino": dest["arrival"],
                "saida_destino": dest["departure"],
                "tempo_destino": dest["minutes"],
                "encontrou_destino": True,
                "pontos_destino": dest["points"],
                "confianca_destino_pct": dest.get("confidence_pct", 0),
                "motivo_saida_destino": dest.get("exit_reason", ""),
                "interrupcoes_ignoradas_destino": dest.get("ignored_interruptions", 0),
                "maior_distancia_temporaria_destino_km": dest.get("max_temp_distance_km", 0),
                "tempo_oscilacao_absorvido_destino": dest.get("oscillation_absorbed_min", 0),
            }
        )
        log.append(
            f"RASTREADOR: destino identificado depois da origem em bloco continuo com {dest['points']} ponto(s), "
            f"{dest.get('ignored_interruptions', 0)} oscilacao(oes) absorvida(s)."
        )
    elif not result["encontrou_origem"]:
        log.append("RASTREADOR: destino nao foi fechado porque a origem nao iniciou a sequencia.")
    result["codigos_motivo_especial"] = special_reasons
    return result


def _duration_from_control(df: pd.DataFrame, location: str, kind: str) -> tuple[datetime | None, datetime | None, float, bool]:
    if df.empty:
        return None, None, 0, False
    mask = _location_mask(df, location, ["local_origem", "local_destino", "local_evento", "tipo_evento", "observacao"])
    if not mask.any() and kind:
        event_text = df.get("tipo_evento", pd.Series([""] * len(df), index=df.index)).fillna("").astype(str).map(normalize_text)
        mask = event_text.str.contains(kind, regex=False)
    matched = df[mask].copy()
    if matched.empty:
        return None, None, 0, False
    if kind:
        start_label = "inicio carga" if kind == "CARGA" else "inicio descarga"
        end_label = "fim carga" if kind == "CARGA" else "fim descarga"
        interval_starts: list[datetime] = []
        interval_ends: list[datetime] = []
        for _, row in matched.iterrows():
            text = normalize_text(row.get("observacao"))
            start_match = re.search(rf"{start_label}:\s*([0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}\s+[0-9]{{2}}:[0-9]{{2}}:[0-9]{{2}})", text, flags=re.I)
            end_match = re.search(rf"{end_label}:\s*([0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}\s+[0-9]{{2}}:[0-9]{{2}}:[0-9]{{2}})", text, flags=re.I)
            start_dt = _to_datetime(start_match.group(1)) if start_match else None
            end_dt = _to_datetime(end_match.group(1)) if end_match else None
            if start_dt and end_dt:
                interval_starts.append(start_dt)
                interval_ends.append(end_dt)
        if interval_starts and interval_ends:
            arrival = min(interval_starts)
            departure = max(interval_ends)
            return arrival, departure, _minutes(max((departure - arrival).total_seconds() / 60, 0)), True
    matched = _ensure_datetime_column(matched, "data_hora_inicio", "_inicio_dt")
    matched = _ensure_datetime_column(matched, "data_hora_fim", "_fim_dt")
    starts = matched["_inicio_dt"].dropna()
    ends = matched["_fim_dt"].dropna()
    if starts.empty or ends.empty:
        return None, None, 0, True
    arrival = starts.min().to_pydatetime()
    departure = ends.max().to_pydatetime()
    return arrival, departure, _minutes(max((departure - arrival).total_seconds() / 60, 0)), True


def _control_observation_datetime(row: pd.Series, label: str) -> datetime | None:
    text = str(row.get("observacao") or "")
    match = re.search(rf"{re.escape(label)}:\s*([0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}\s+[0-9]{{2}}:[0-9]{{2}}:[0-9]{{2}})", text, flags=re.I)
    return _to_datetime(match.group(1)) if match else None


def _control_event_times(control_matches: pd.DataFrame, trip: pd.Series) -> dict[str, datetime | None]:
    result = {
        "control_chegada_origem": None,
        "control_saida_origem": None,
        "control_chegada_destino": None,
        "control_saida_destino": None,
    }
    if control_matches.empty:
        return result
    row = control_matches.iloc[0]
    result["control_chegada_origem"] = _control_observation_datetime(row, "Inicio carga") or _to_datetime(row.get("data_hora_inicio")) or _to_datetime(row.get("data_inicio"))
    result["control_saida_origem"] = _control_observation_datetime(row, "Fim carga")
    result["control_chegada_destino"] = _control_observation_datetime(row, "Inicio descarga")
    result["control_saida_destino"] = _control_observation_datetime(row, "Fim descarga") or _to_datetime(row.get("data_hora_fim")) or _to_datetime(row.get("data_fim"))
    carga_inicio, carga_fim, _, carga_found = _duration_from_control(control_matches, str(trip.get("origem") or ""), "CARGA")
    descarga_inicio, descarga_fim, _, descarga_found = _duration_from_control(control_matches, str(trip.get("destino") or ""), "DESCARGA")
    if carga_found:
        result["control_chegada_origem"] = result["control_chegada_origem"] or carga_inicio
        result["control_saida_origem"] = result["control_saida_origem"] or carga_fim
    if descarga_found:
        result["control_chegada_destino"] = result["control_chegada_destino"] or descarga_inicio
        result["control_saida_destino"] = result["control_saida_destino"] or descarga_fim
    return result


def _event_diff_minutes(left: datetime | None, right: datetime | None) -> float | None:
    if not left or not right:
        return None
    return _minutes(abs((left - right).total_seconds()) / 60)


def _compare_control_tracker_events(
    tracker_events: dict[str, Any],
    control_events: dict[str, datetime | None],
    tolerance_min: float,
) -> dict[str, Any]:
    pairs = {
        "diferenca_chegada_origem_min": (tracker_events.get("chegada_origem"), control_events.get("control_chegada_origem")),
        "diferenca_saida_origem_min": (tracker_events.get("saida_origem"), control_events.get("control_saida_origem")),
        "diferenca_chegada_destino_min": (tracker_events.get("chegada_destino"), control_events.get("control_chegada_destino")),
        "diferenca_saida_destino_min": (tracker_events.get("saida_destino"), control_events.get("control_saida_destino")),
    }
    diffs: dict[str, float | None] = {key: _event_diff_minutes(_to_datetime(tracker), _to_datetime(control)) for key, (tracker, control) in pairs.items()}
    comparable = [value for value in diffs.values() if value is not None]
    missing_control = sum(1 for _, control in pairs.values() if _to_datetime(control) is None)
    missing_tracker = sum(1 for tracker, _ in pairs.values() if _to_datetime(tracker) is None)
    max_diff = max(comparable) if comparable else 0
    avg_diff = round(sum(comparable) / len(comparable), 2) if comparable else 0
    return {
        **{key: (value if value is not None else 0) for key, value in diffs.items()},
        "maior_divergencia_min": max_diff,
        "media_divergencias_min": avg_diff,
        "eventos_comparaveis": len(comparable),
        "eventos_sem_control": missing_control,
        "eventos_sem_rastreador": missing_tracker,
        "dentro_tolerancia_control_rastreador": 1 if comparable and max_diff <= tolerance_min else 0,
        "tolerancia_control_rastreador_min": tolerance_min,
    }


def _start_reference_datetime(
    chegada_origem: datetime | None,
    saida_origem: datetime | None,
    control_events: dict[str, datetime | None],
    trip: pd.Series,
) -> tuple[datetime | None, str]:
    if saida_origem:
        return saida_origem, "RASTREADOR_SAIDA_ORIGEM"
    if chegada_origem:
        return chegada_origem, "RASTREADOR_CHEGADA_ORIGEM"
    if control_events.get("control_chegada_origem"):
        return control_events["control_chegada_origem"], "CONTROL_DT_CARGA"
    control_start = _to_datetime(trip.get("data_hora_carga")) or _to_datetime(trip.get("data_operacao"))
    if control_start:
        return control_start, "LCTE_DATA_EMISSAO"
    return _trip_reference_datetime(trip), "LCTE_DATA_EMISSAO"


def _deadline_status(conclusao_dt: datetime | None, retorno_recebido: bool, precisa_retorno: bool = True) -> tuple[str, str, int]:
    if not precisa_retorno:
        return "", "Nao necessita retorno", 0
    if not conclusao_dt:
        return "", "", 0
    limite = conclusao_dt + timedelta(days=15)
    now = datetime.now()
    dias = (limite.date() - now.date()).days
    if retorno_recebido:
        status = "Retorno recebido"
    elif dias < 0:
        status = "Prazo vencido"
    elif dias == 0:
        status = "Vence hoje"
    elif dias <= 5:
        status = "Vence em ate 5 dias"
    else:
        status = "Dentro do prazo"
    return limite.isoformat(sep=" ", timespec="seconds"), status, int(dias)


def _apply_conclusion_state(row: dict[str, object], conclusion: dict[str, Any] | None) -> dict[str, object]:
    if not conclusion:
        return row
    conclusao_dt = _to_datetime(conclusion.get("data_hora_conclusao"))
    retorno_recebido = bool(int(conclusion.get("retorno_recebido") or 0))
    precisa_retorno = bool(int(conclusion.get("necessita_retorno") or 0))
    limite, status_prazo, dias = _deadline_status(conclusao_dt, retorno_recebido, precisa_retorno)
    precisa_verificar = bool(int(conclusion.get("precisa_verificar") or 0)) or status_prazo in {"Prazo vencido", "Vence em ate 5 dias", "Vence hoje"}
    row.update(
        {
            "painel_atual": "CONCLUIDOS",
            "concluido": 1,
            "tratado": 1,
            "precisa_verificar": 1 if precisa_verificar else 0,
            "tipo_conclusao": str(conclusion.get("tipo_conclusao") or ""),
            "status_tratativa": str(conclusion.get("status_tratativa") or ""),
            "observacao_conclusao": str(conclusion.get("observacao") or ""),
            "usuario_conclusao": str(conclusion.get("usuario_responsavel") or ""),
            "data_hora_conclusao": str(conclusion.get("data_hora_conclusao") or ""),
            "data_limite_retorno": limite,
            "dias_restantes": dias,
            "retorno_recebido": 1 if retorno_recebido else 0,
            "data_retorno": str(conclusion.get("data_retorno") or ""),
            "status_retorno": str(conclusion.get("status_retorno") or ""),
            "status_prazo": status_prazo,
            "protocolo": str(conclusion.get("protocolo") or ""),
            "valor_solicitado": conclusion.get("valor_solicitado") or 0,
            "valor_aprovado": conclusion.get("valor_aprovado") or 0,
            "status_cte": "Concluido" if not precisa_verificar else "Aguardando retorno",
        }
    )
    return row


def _classify_panel(
    calculou: bool,
    elegivel: bool,
    comparison: dict[str, Any],
    reason_codes: list[str],
    control_matches: pd.DataFrame,
    tracker_matches: pd.DataFrame,
) -> dict[str, Any]:
    reason_text = " ".join(reason_codes)
    has_control = not control_matches.empty
    has_tracker = not tracker_matches.empty
    needs_verification = False
    verification_reasons: list[str] = []
    if not has_control:
        needs_verification = True
        verification_reasons.append("SEM_CONTROL")
    if not has_tracker:
        needs_verification = True
        verification_reasons.append("SEM_RASTREADOR")
    if comparison.get("eventos_sem_control", 0):
        needs_verification = True
        verification_reasons.append("CONTROL_INCOMPLETO")
    if comparison.get("eventos_sem_rastreador", 0):
        needs_verification = True
        verification_reasons.append("RASTREADOR_INCOMPLETO")
    if comparison.get("eventos_comparaveis", 0) and not int(comparison.get("dentro_tolerancia_control_rastreador") or 0):
        needs_verification = True
        verification_reasons.append("DIVERGENCIA_ACIMA_TOLERANCIA")
    if any(token in reason_text for token in ["MULTIPLAS", "REVISAO", "SEM_COORDENADAS", "SOBREPOSTA", "ERRO"]):
        needs_verification = True
        verification_reasons.append("VALIDACAO_MANUAL")
    if calculou and elegivel and not needs_verification:
        painel = "ESTADIAS"
        status_cte = "Estadia valida"
    elif calculou and needs_verification:
        painel = "VERIFICACAO"
        status_cte = "Em verificacao"
    elif not calculou and needs_verification:
        painel = "VERIFICACAO"
        status_cte = "Rastreador incompleto" if has_control else "Control incompleto"
    else:
        painel = "SOMENTE_LCTE"
        status_cte = "Sem estadia"
    return {
        "painel_atual": painel,
        "status_processamento": "PROCESSADO",
        "status_permanencia": "IDENTIFICADA" if calculou else "NAO_IDENTIFICADA",
        "status_estadia": "COM_ESTADIA" if elegivel else "SEM_ESTADIA",
        "status_verificacao": "; ".join(dict.fromkeys(verification_reasons)),
        "status_tratativa": "NAO_TRATADO",
        "status_retorno": "",
        "concluido": 0,
        "tratado": 0,
        "precisa_verificar": 1 if needs_verification else 0,
        "status_cte": status_cte,
    }


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return round(radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)), 3)


def _distance_to_point(df: pd.DataFrame, lat: Any, lon: Any) -> float | None:
    ref_lat = _safe_float(lat)
    ref_lon = _safe_float(lon)
    if ref_lat is None or ref_lon is None or df.empty:
        return None
    if "latitude" not in df.columns or "longitude" not in df.columns:
        return None
    coords = df.dropna(subset=["latitude", "longitude"])
    distances = [
        _haversine_km(ref_lat, ref_lon, float(row["latitude"]), float(row["longitude"]))
        for _, row in coords.iterrows()
        if _safe_float(row.get("latitude")) is not None and _safe_float(row.get("longitude")) is not None
    ]
    return min(distances) if distances else None


def _km_percorrido(df: pd.DataFrame) -> float:
    if df.empty or "odometro" not in df.columns:
        return 0
    odo = pd.to_numeric(df["odometro"], errors="coerce").dropna()
    if len(odo) < 2:
        return 0
    diff = float(odo.max() - odo.min())
    return round(diff, 2) if diff > 0 else 0


def _params_for_trip(trip: pd.Series, parametros: pd.DataFrame, config: dict[str, str]) -> dict[str, float]:
    default_hours = _config_number(config, "franquia_padrao_horas", 24)
    result = {"franquia_carga_horas": default_hours, "franquia_descarga_horas": default_hours, "valor_hora": _config_number(config, "valor_hora_estadia", 0)}
    if parametros.empty:
        return result
    cliente = normalize_text(trip.get("cliente"))
    active = parametros[parametros.get("ativo", 1).fillna(1).astype(int).eq(1)].copy() if "ativo" in parametros else parametros.copy()
    if "cliente_norm" in active.columns:
        matched = active[active["cliente_norm"].fillna("").astype(str).eq(cliente)]
    else:
        matched = active[active["cliente"].fillna("").astype(str).map(normalize_text).eq(cliente)] if "cliente" in active else pd.DataFrame()
    if matched.empty:
        return result
    row = matched.iloc[0]
    result["franquia_carga_horas"] = _safe_float(row.get("franquia_carga_horas")) or result["franquia_carga_horas"]
    result["franquia_descarga_horas"] = _safe_float(row.get("franquia_descarga_horas")) or result["franquia_descarga_horas"]
    result["valor_hora"] = _safe_float(row.get("valor_hora")) or result["valor_hora"]
    return result


def _main_reason(codes: list[str]) -> tuple[str, str]:
    if not codes:
        return "", ""
    code = codes[0]
    return code, MOTIVOS.get(code, code)


def _next_trip_by_plate(lcte: pd.DataFrame) -> dict[int, datetime | None]:
    lcte_dt = lcte.copy()
    lcte_dt["_trip_dt"] = pd.to_datetime(lcte_dt["data_hora_carga"].where(lcte_dt["data_hora_carga"].fillna("").astype(str).ne(""), lcte_dt["data_operacao"]), errors="coerce")
    result: dict[int, datetime | None] = {}
    for _, group in lcte_dt.sort_values("_trip_dt").groupby("placa_norm", dropna=False):
        ids = group["id"].tolist()
        dates = group["_trip_dt"].tolist()
        for idx, trip_id in enumerate(ids):
            next_dt = dates[idx + 1] if idx + 1 < len(dates) else None
            result[int(trip_id)] = None if pd.isna(next_dt) else next_dt.to_pydatetime()
    return result


def _trip_neighbors_by_plate(lcte: pd.DataFrame) -> dict[int, tuple[datetime | None, datetime | None]]:
    if lcte.empty or "id" not in lcte.columns:
        return {}
    lcte_dt = lcte.copy()
    lcte_dt["_trip_dt"] = pd.to_datetime(lcte_dt.apply(_trip_reference_datetime, axis=1), errors="coerce")
    result: dict[int, tuple[datetime | None, datetime | None]] = {}
    for _, group in lcte_dt.sort_values(["placa_norm", "_trip_dt", "id"], na_position="last").groupby("placa_norm", dropna=False):
        records = group.to_dict(orient="records")
        for index, row in enumerate(records):
            try:
                trip_id = int(row.get("id") or 0)
            except Exception:
                continue
            prev_dt = records[index - 1].get("_trip_dt") if index > 0 else None
            next_dt = records[index + 1].get("_trip_dt") if index + 1 < len(records) else None
            current_dt = row.get("_trip_dt")
            current_ts = current_dt if isinstance(current_dt, pd.Timestamp) and not pd.isna(current_dt) else None
            prev_ts = prev_dt if isinstance(prev_dt, pd.Timestamp) and not pd.isna(prev_dt) else None
            next_ts = next_dt if isinstance(next_dt, pd.Timestamp) and not pd.isna(next_dt) else None
            result[trip_id] = (
                prev_ts.to_pydatetime() if prev_ts is not None and current_ts is not None and prev_ts < current_ts else None,
                next_ts.to_pydatetime() if next_ts is not None and current_ts is not None and next_ts > current_ts else None,
            )
    return result


def dashboard_metrics() -> dict[str, int | str]:
    logs = repository.latest_logs(10)
    cross = repository.read_cross(200000)
    latest_lcte = latest_control = latest_rastreador = ""
    if not logs.empty:
        latest_lcte_df = logs[logs["tipo_importacao"].astype(str).eq("LCTE_IPIRANGA")]
        latest_control_df = logs[logs["tipo_importacao"].astype(str).eq("CONTROL")]
        latest_rastreador_df = logs[logs["tipo_importacao"].astype(str).eq("RASTREADOR_PLACA")]
        latest_lcte = str(latest_lcte_df.iloc[0]["data_hora"]) if not latest_lcte_df.empty else ""
        latest_control = str(latest_control_df.iloc[0]["data_hora"]) if not latest_control_df.empty else ""
        latest_rastreador = str(latest_rastreador_df.iloc[0]["data_hora"]) if not latest_rastreador_df.empty else ""

    if cross.empty:
        return {
            "Ultima importacao LCTE": latest_lcte or "-",
            "Ultima importacao CONTROL": latest_control or "-",
            "Ultima importacao Rastreador": latest_rastreador or "-",
            **repository.counts(),
        }

    viagens = int(len(cross))
    com_estadia = int(pd.to_numeric(cross.get("horas_estadia", pd.Series(dtype=float)), errors="coerce").fillna(0).gt(0).sum())
    tempo_carga = pd.to_numeric(cross.get("tempo_origem_min", pd.Series(dtype=float)), errors="coerce").fillna(0)
    tempo_descarga = pd.to_numeric(cross.get("tempo_destino_min", pd.Series(dtype=float)), errors="coerce").fillna(0)
    maior = max(float(tempo_carga.max() if not tempo_carga.empty else 0), float(tempo_descarga.max() if not tempo_descarga.empty else 0))
    valor_estimado = pd.to_numeric(cross.get("valor_estimado_estadia", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()
    return {
        "Total de viagens": viagens,
        "Viagens com estadia": com_estadia,
        "Viagens sem estadia": viagens - com_estadia,
        "Tempo medio de carga": _format_minutes(tempo_carga.mean() if not tempo_carga.empty else 0),
        "Tempo medio de descarga": _format_minutes(tempo_descarga.mean() if not tempo_descarga.empty else 0),
        "Maior estadia": _format_minutes(maior),
        "Valor estimado de estadias": f"R$ {valor_estimado:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
        "Ultima importacao LCTE": latest_lcte or "-",
    }


def validation_metrics(cross: pd.DataFrame | None = None) -> dict[str, int]:
    cross = repository.read_cross(200000) if cross is None else cross
    if cross.empty:
        return {
            "Viagens encontradas no LCTE": repository.table_count(repository.LCTE_NORMALIZED_TABLE),
            "Viagens relacionadas ao CONTROL": 0,
            "Viagens nao relacionadas ao CONTROL": 0,
            "Vinculos confirmados": 0,
            "Vinculos provaveis": 0,
            "Vinculos aguardando revisao": 0,
            "Viagens com registros no rastreador": 0,
            "Viagens sem registros no rastreador": 0,
            "Origens reconhecidas": 0,
            "Destinos reconhecidos": 0,
            "Locais sem coordenadas": 0,
            "Viagens processadas": 0,
            "Viagens com possivel estadia": 0,
            "Viagens com erro": 0,
            "Viagens em andamento": 0,
            "Aguardando validacao manual": 0,
        }
    classification = cross["classificacao_control"].fillna("").astype(str)
    motives = cross["codigo_motivo"].fillna("").astype(str) + " " + cross["motivo_falha"].fillna("").astype(str)
    return {
        "Viagens encontradas no LCTE": int(len(cross)),
        "Viagens relacionadas ao CONTROL": int(cross["encontrou_control"].fillna(0).astype(int).eq(1).sum()),
        "Viagens nao relacionadas ao CONTROL": int(cross["encontrou_control"].fillna(0).astype(int).ne(1).sum()),
        "Vinculos confirmados": int(classification.eq("CONFIRMADO").sum()),
        "Vinculos provaveis": int(classification.eq("PROVAVEL").sum()),
        "Vinculos aguardando revisao": int(classification.eq("REVISAO_MANUAL").sum()),
        "Viagens com registros no rastreador": int(cross["encontrou_rastreador"].fillna(0).astype(int).eq(1).sum()),
        "Viagens sem registros no rastreador": int(cross["encontrou_rastreador"].fillna(0).astype(int).ne(1).sum()),
        "Origens reconhecidas": int(cross["encontrou_origem"].fillna(0).astype(int).eq(1).sum()),
        "Destinos reconhecidos": int(cross["encontrou_destino"].fillna(0).astype(int).eq(1).sum()),
        "Locais sem coordenadas": int(cross["codigo_motivo"].fillna("").astype(str).str.contains("SEM_COORDENADAS").sum()),
        "Viagens processadas": int(len(cross)),
        "Viagens em andamento": int(motives.str.contains("CONTROL_VIAGEM_EM_ANDAMENTO", na=False).sum()),
        "Viagens com possivel estadia": int(pd.to_numeric(cross.get("horas_estadia", pd.Series(dtype=float)), errors="coerce").fillna(0).gt(0).sum()),
        "Viagens com erro": int(cross["status_cruzamento"].fillna("").astype(str).eq("ERRO").sum()),
        "Aguardando validacao manual": int(classification.isin(["PROVAVEL", "REVISAO_MANUAL"]).sum()),
    }


def top_indicators(limit: int = 10) -> dict[str, pd.DataFrame]:
    cross = repository.read_cross(200000)
    if cross.empty:
        return {}
    result: dict[str, pd.DataFrame] = {}
    for label, column in {"Top clientes": "cliente", "Top bases": "origem", "Top motoristas": "motorista", "Top placas": "placa_norm"}.items():
        if column not in cross.columns:
            continue
        result[label] = (
            cross[cross[column].fillna("").astype(str).ne("")]
            .groupby(column, dropna=False)
            .agg(
                viagens=(column, "size"),
                viagens_com_estadia=("horas_estadia", lambda s: int(pd.to_numeric(s, errors="coerce").fillna(0).gt(0).sum())),
                tempo_total_min=("tempo_operacional_min", "sum"),
                valor_estimado=("valor_estimado_estadia", "sum"),
            )
            .sort_values(["viagens_com_estadia", "tempo_total_min", "viagens"], ascending=False)
            .head(limit)
            .reset_index()
        )
    return result


def _filter_lcte_by_plate(lcte: pd.DataFrame, placa_filtro: str | None) -> tuple[pd.DataFrame, str]:
    plate = _normalize_plate_candidate(placa_filtro)
    if lcte.empty or not plate:
        return lcte, plate
    principal = lcte.get("placa_norm", pd.Series(dtype=str)).fillna("").astype(str).eq(plate)
    composicao = pd.Series(False, index=lcte.index)
    if "placas_composicao" in lcte.columns:
        composicao = lcte["placas_composicao"].fillna("").astype(str).str.upper().str.contains(plate, regex=False)
    return lcte[principal | composicao].copy(), plate


def _plates_from_lcte(lcte: pd.DataFrame) -> list[str]:
    plates: list[str] = []
    for _, trip in lcte.iterrows():
        for plate in _trip_plate_candidates(trip):
            if plate and plate not in plates:
                plates.append(plate)
    return plates


def build_cross_rows(progress_callback: ProgressCallback | None = None, placa_filtro: str | None = None) -> list[dict[str, object]]:
    _emit_progress(progress_callback, 1, 100, "Carregando viagens LCTE...")
    lcte_base = repository.read_lcte({}, 200000)
    lcte, plate_filter = _filter_lcte_by_plate(lcte_base, placa_filtro)
    if plate_filter:
        _emit_progress(progress_callback, 3, 100, f"Filtro de placa aplicado: {plate_filter}.")
    _emit_progress(progress_callback, 4, 100, "Carregando registros CONTROL...")
    control_filters: dict[str, Any] = {}
    if plate_filter:
        control_plates = _plates_from_lcte(lcte) or [plate_filter]
        control_filters["placa_norm"] = control_plates
    control = repository.read_control(control_filters, 300000)
    _emit_progress(progress_callback, 7, 100, "Carregando parametros e configuracoes...")
    parametros = repository.read_parametros(10000)
    config = _read_config_values()
    min_stop = _config_number(config, "tempo_minimo_parado", 30)
    tolerance_control_tracker = _config_number(config, "tolerancia_control_rastreador_min", 30)
    try:
        conclusoes = repository.read_conclusoes_map()
    except Exception:
        conclusoes = {}
    rows: list[dict[str, object]] = []
    if lcte.empty:
        _emit_progress(progress_callback, 100, 100, "Nenhuma viagem LCTE encontrada.")
        return rows
    _emit_progress(progress_callback, 10, 100, f"Preparando cruzamento de {len(lcte)} viagem(ns)...")
    control_by_plate: dict[str, pd.DataFrame] = {}
    if not control.empty and "placa_norm" in control.columns:
        for plate_key, group in control.groupby(control["placa_norm"].fillna("").astype(str), dropna=False):
            control_by_plate[str(plate_key)] = group.copy()
    empty_control = control.iloc[0:0].copy() if not control.empty else pd.DataFrame()
    tracker_plate_counts: dict[str, int] = {}
    used_control_ids: set[int] = set()
    used_tracker_stays: set[tuple[str, str, str, str]] = set()
    trip_neighbors_base = lcte if not plate_filter else _filter_lcte_by_plate(lcte_base, plate_filter)[0]
    trip_neighbors = _trip_neighbors_by_plate(trip_neighbors_base)
    processing_lcte = lcte.copy()
    processing_lcte["_trip_dt"] = pd.to_datetime(processing_lcte.apply(_trip_reference_datetime, axis=1), errors="coerce")
    processing_lcte = processing_lcte.sort_values(["placa_norm", "_trip_dt", "id"], na_position="last")

    total_trips = max(len(lcte), 1)
    last_progress = -1
    for trip_index, (_, trip) in enumerate(processing_lcte.iterrows(), start=1):
        log: list[str] = ["LCTE: viagem mestre encontrada."]
        reason_codes: list[str] = []
        plate = str(trip.get("placa_norm") or "")
        trip_id = int(trip.get("id") or 0)
        previous_trip_dt, next_trip_dt = trip_neighbors.get(trip_id, (None, None))
        if not plate:
            reason_codes.append("LCTE_SEM_PLACA")
        if not _doc_set(trip.get("nf")):
            reason_codes.append("LCTE_SEM_NF")
        if not str(trip.get("data_operacao") or ""):
            reason_codes.append("LCTE_DATA_INVALIDA")
        if not str(trip.get("origem_norm") or ""):
            reason_codes.append("LCTE_SEM_ORIGEM")
        if not str(trip.get("destino_norm") or ""):
            reason_codes.append("LCTE_SEM_DESTINO")

        try:
            control_frames = [control_by_plate.get(candidate) for candidate in _trip_plate_candidates(trip)]
            control_frames = [frame for frame in control_frames if frame is not None and not frame.empty]
            if control_frames:
                control_candidates = pd.concat(control_frames, ignore_index=False)
                control_candidates = (
                    control_candidates.drop_duplicates(subset=["id"])
                    if "id" in control_candidates.columns
                    else control_candidates.loc[~control_candidates.index.duplicated()]
                )
            else:
                control_candidates = empty_control
            control_matches, control_score, control_class, control_criteria, control_reason = _select_control_matches(control_candidates, trip, log, used_control_ids)
            if control_reason:
                reason_codes.append(control_reason)
            if not control_matches.empty:
                selected_control_id = int(control_matches.iloc[0].get("id") or 0)
                if selected_control_id:
                    used_control_ids.add(selected_control_id)
                control_row = control_matches.iloc[0]
                if not _doc_set(control_row.get("nf")):
                    reason_codes.append("CONTROL_SEM_NF")
                control_status = normalize_text(control_row.get("status"))
                if "VIAJ" in control_status or (not str(control_row.get("data_hora_fim") or "") and not str(control_row.get("data_fim") or "")):
                    reason_codes.append("CONTROL_VIAGEM_EM_ANDAMENTO")
            tracker_matches, window_info = _filter_tracker_for_trip_from_db(trip, control_matches, config, log, tracker_plate_counts, previous_trip_dt, next_trip_dt)
            if tracker_matches.empty:
                reason_codes.append("RASTREADOR_SEM_REGISTROS")
            elif tracker_matches.get("_data_dt", pd.Series(dtype=object)).isna().all():
                reason_codes.append("RASTREADOR_DATA_INVALIDA")

            tracker_events = _detect_trip_events(tracker_matches, trip, config, log, used_tracker_stays)
            for special_reason in tracker_events.get("codigos_motivo_especial", []):
                if special_reason:
                    reason_codes.append(str(special_reason))
            chegada_origem = tracker_events["chegada_origem"]
            saida_origem = tracker_events["saida_origem"]
            tempo_origem = tracker_events["tempo_origem"]
            encontrou_origem = tracker_events["encontrou_origem"]
            pontos_origem = tracker_events["pontos_origem"]
            if not encontrou_origem:
                chegada_origem, saida_origem, tempo_origem, encontrou_origem = _duration_from_control(control_matches, str(trip.get("origem") or ""), "CARGA")
                pontos_origem = 0
                if encontrou_origem:
                    log.append("Origem calculada por CONTROL por ausencia de ponto rastreador compativel.")

            chegada_destino = tracker_events["chegada_destino"]
            saida_destino = tracker_events["saida_destino"]
            tempo_destino = tracker_events["tempo_destino"]
            encontrou_destino = tracker_events["encontrou_destino"]
            pontos_destino = tracker_events["pontos_destino"]
            if not encontrou_destino:
                chegada_destino, saida_destino, tempo_destino, encontrou_destino = _duration_from_control(control_matches, str(trip.get("destino") or ""), "DESCARGA")
                pontos_destino = 0
                if encontrou_destino:
                    log.append("Destino calculado por CONTROL por ausencia de ponto rastreador compativel.")

            if not encontrou_origem:
                reason_codes.append("ORIGEM_NAO_VISITADA")
            if not encontrou_destino:
                reason_codes.append("DESTINO_NAO_VISITADO")

            control_events = _control_event_times(control_matches, trip)
            comparison = _compare_control_tracker_events(
                {
                    "chegada_origem": chegada_origem,
                    "saida_origem": saida_origem,
                    "chegada_destino": chegada_destino,
                    "saida_destino": saida_destino,
                },
                control_events,
                tolerance_control_tracker,
            )
            if comparison.get("eventos_comparaveis", 0) and not int(comparison.get("dentro_tolerancia_control_rastreador") or 0):
                reason_codes.append("DIVERGENCIA_CONTROL_RASTREADOR")

            tempo_operacional = _minutes(tempo_origem + tempo_destino)
            data_inicio_ref, fonte_inicio_ref = _start_reference_datetime(chegada_origem, saida_origem, control_events, trip)
            first_dt = data_inicio_ref or chegada_origem or _to_datetime(trip.get("data_hora_carga")) or _to_datetime(trip.get("data_operacao"))
            last_dt = saida_destino or (tracker_matches["_data_dt"].max().to_pydatetime() if not tracker_matches.empty and tracker_matches["_data_dt"].notna().any() else None)
            tempo_total = _minutes((last_dt - first_dt).total_seconds() / 60) if first_dt and last_dt and last_dt >= first_dt else 0
            tempo_transito = _minutes(max(tempo_total - tempo_operacional, 0))
            tempo_control = _minutes(pd.to_numeric(control_matches.get("tempo_total", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()) if not control_matches.empty else 0
            tempo_rastreador = tempo_operacional
            diff_control_tracker = _minutes(tempo_control - tempo_rastreador) if tempo_control else 0

            origin_tracker = tracker_matches[_location_mask(tracker_matches, str(trip.get("origem") or ""), ["endereco", "cidade", "uf"])] if not tracker_matches.empty else tracker_matches
            dest_tracker = tracker_matches[_location_mask(tracker_matches, str(trip.get("destino") or ""), ["endereco", "cidade", "uf"])] if not tracker_matches.empty else tracker_matches
            dist_carga = tracker_events.get("distancia_origem_min_km")
            if dist_carga is None:
                dist_carga = _distance_to_point(origin_tracker, trip.get("latitude_origem"), trip.get("longitude_origem"))
            dist_descarga = tracker_events.get("distancia_destino_min_km")
            if dist_descarga is None:
                dist_descarga = _distance_to_point(dest_tracker, trip.get("latitude_destino"), trip.get("longitude_destino"))
            if (trip.get("latitude_origem") or trip.get("longitude_origem")) and dist_carga is None:
                reason_codes.append("ORIGEM_SEM_COORDENADAS")
            if (trip.get("latitude_destino") or trip.get("longitude_destino")) and dist_descarga is None:
                reason_codes.append("DESTINO_SEM_COORDENADAS")

            params = _params_for_trip(trip, parametros, config)
            franquia_carga_min = _minutes(params["franquia_carga_horas"] * 60)
            franquia_descarga_min = _minutes(params["franquia_descarga_horas"] * 60)
            estadia_carga_min = _minutes(max(tempo_origem - franquia_carga_min, 0))
            estadia_descarga_min = _minutes(max(tempo_destino - franquia_descarga_min, 0))
            horas_estadia = round((estadia_carga_min + estadia_descarga_min) / 60, 2)
            valor_estimado = round(horas_estadia * params["valor_hora"], 2)
            calculou = encontrou_origem and encontrou_destino and tempo_operacional >= min_stop
            if encontrou_origem and encontrou_destino and tempo_operacional < min_stop:
                reason_codes.append("PERMANENCIA_INSUFICIENTE")
            if not calculou:
                reason_codes.append("PERMANENCIA_NAO_IDENTIFICADA")
            if tempo_operacional >= min_stop and horas_estadia <= 0:
                reason_codes.append("FRANQUIA_NAO_ULTRAPASSADA")

            elegivel = calculou and horas_estadia > 0
            status = "ESTADIA_CALCULADA" if calculou else "NAO_CALCULADA"
            status_control = control_class if not control_matches.empty else "NAO_LOCALIZADO"
            status_rastreador = "LOCALIZADO" if not tracker_matches.empty else "NAO_LOCALIZADO"
            code, description = _main_reason(list(dict.fromkeys(reason_codes)))
            motivo_nao_elegibilidade = "" if elegivel else description
            workflow = _classify_panel(calculou, elegivel, comparison, list(dict.fromkeys(reason_codes)), control_matches, tracker_matches)

            diagnostic = {
                "Viagem criada pelo LCTE": True,
                "Placa validada": bool(plate),
                "Data emissao tratada": str(_trip_reference_datetime(trip) or ""),
                "Fonte da janela": window_info.get("fonte") or "",
                "Inicio da janela": str(window_info.get("inicio") or ""),
                "Fim da janela": str(window_info.get("fim") or ""),
                "Total de pontos da placa": int(window_info.get("total_pontos_placa") or 0),
                "Pontos dentro da janela": int(window_info.get("pontos_janela") or 0),
                "Primeiro ponto analisado": str(tracker_matches["_data_dt"].min() if not tracker_matches.empty and "_data_dt" in tracker_matches else ""),
                "Ultimo ponto analisado": str(tracker_matches["_data_dt"].max() if not tracker_matches.empty and "_data_dt" in tracker_matches else ""),
                "Relacionamento com CONTROL": status_control,
                "Pontuacao CONTROL": control_score,
                "Criterios CONTROL": control_criteria,
                "Registros CONTROL por placa": int(len(control_candidates)) if plate else 0,
                "Registros do rastreador localizados": not tracker_matches.empty,
                "Origem localizada": encontrou_origem,
                "Destino localizado": encontrou_destino,
                "Distancia minima origem km": tracker_events.get("distancia_origem_min_km"),
                "Distancia minima destino km": tracker_events.get("distancia_destino_min_km"),
                "Pontos dentro da origem": pontos_origem,
                "Pontos dentro do destino": pontos_destino,
                "Regra especial origem": bool(tracker_events.get("regra_especial_origem")),
                "Regra especial destino": bool(tracker_events.get("regra_especial_destino")),
                "Municipio operacional origem": tracker_events.get("municipio_operacional_origem"),
                "Municipio operacional destino": tracker_events.get("municipio_operacional_destino"),
                "Blocos municipio origem": tracker_events.get("qtd_blocos_municipio_origem"),
                "Blocos municipio destino": tracker_events.get("qtd_blocos_municipio_destino"),
                "Bloco selecionado origem": tracker_events.get("bloco_selecionado_origem"),
                "Bloco selecionado destino": tracker_events.get("bloco_selecionado_destino"),
                "Eventos Control": {key: str(value or "") for key, value in control_events.items()},
                "Comparacao Control x Rastreador": comparison,
                "Tolerancia Control x Rastreador min": tolerance_control_tracker,
                "Confianca permanencia origem pct": tracker_events.get("confianca_origem_pct"),
                "Confianca permanencia destino pct": tracker_events.get("confianca_destino_pct"),
                "Motivo confirmacao saida origem": tracker_events.get("motivo_saida_origem"),
                "Motivo confirmacao saida destino": tracker_events.get("motivo_saida_destino"),
                "Interrupcoes ignoradas origem": tracker_events.get("interrupcoes_ignoradas_origem"),
                "Interrupcoes ignoradas destino": tracker_events.get("interrupcoes_ignoradas_destino"),
                "Maior distancia temporaria origem km": tracker_events.get("maior_distancia_temporaria_origem_km"),
                "Maior distancia temporaria destino km": tracker_events.get("maior_distancia_temporaria_destino_km"),
                "Tempo oscilacao absorvido origem min": tracker_events.get("tempo_oscilacao_absorvido_origem"),
                "Tempo oscilacao absorvido destino min": tracker_events.get("tempo_oscilacao_absorvido_destino"),
                "Permanencia calculada": calculou,
                "Regra de franquia aplicada": True,
                "Elegivel para cobranca": elegivel,
                "Painel atual": workflow.get("painel_atual"),
                "Status CT-e": workflow.get("status_cte"),
                "Motivos": [{"codigo": c, "descricao": MOTIVOS.get(c, c)} for c in dict.fromkeys(reason_codes)],
            }
            row_payload = _complete_row(
                {
                    "lcte_id": int(trip.get("id") or 0),
                    "chave_viagem": str(trip.get("chave_viagem") or ""),
                    "cte": str(trip.get("cte") or ""),
                    "nf": str(trip.get("nf") or ""),
                    "chave_nf": str(trip.get("chave_nf") or ""),
                    "placa_norm": plate,
                    "placas_composicao": str(trip.get("placas_composicao") or ""),
                    "data_operacao": str(trip.get("data_operacao") or ""),
                    "data_hora_carga": str(trip.get("data_hora_carga") or ""),
                    "data_inicio_viagem_referencia": data_inicio_ref.isoformat(sep=" ", timespec="seconds") if data_inicio_ref else "",
                    "fonte_data_inicio_viagem": fonte_inicio_ref,
                    "origem": str(trip.get("origem") or ""),
                    "uf_origem": str(trip.get("uf_origem") or ""),
                    "destino": str(trip.get("destino") or ""),
                    "uf_destino": str(trip.get("uf_destino") or ""),
                    "cliente": str(trip.get("cliente") or ""),
                    "motorista": str(trip.get("motorista") or ""),
                    "status_lcte": "OK",
                    "status_control": status_control,
                    "status_rastreador": status_rastreador,
                    "pontuacao_control": control_score,
                    "classificacao_control": control_class,
                    "criterios_control_json": json.dumps(control_criteria, ensure_ascii=False, default=str),
                    "control_id": int(control_matches.iloc[0].get("id") or 0) if not control_matches.empty else 0,
                    "encontrou_lcte": 1,
                    "encontrou_control": 1 if not control_matches.empty else 0,
                    "encontrou_rastreador": 1 if not tracker_matches.empty else 0,
                    "encontrou_origem": 1 if encontrou_origem else 0,
                    "encontrou_destino": 1 if encontrou_destino else 0,
                    "calculou_estadia": 1 if calculou else 0,
                    "existe_control": 1 if not control_matches.empty else 0,
                    "existe_rastreador": 1 if not tracker_matches.empty else 0,
                    "qtd_registros_control": int(len(control_matches)),
                    "qtd_registros_rastreador": int(len(tracker_matches)),
                    "fonte_janela": str(window_info.get("fonte") or ""),
                    "inicio_janela": window_info.get("inicio").isoformat(sep=" ", timespec="seconds") if window_info.get("inicio") else "",
                    "fim_janela": window_info.get("fim").isoformat(sep=" ", timespec="seconds") if window_info.get("fim") else "",
                    "qtd_total_pontos_placa": int(window_info.get("total_pontos_placa") or 0),
                    "primeira_data_control": str(control_matches["data_hora_inicio"].min() if not control_matches.empty and "data_hora_inicio" in control_matches else ""),
                    "ultima_data_control": str(control_matches["data_hora_fim"].max() if not control_matches.empty and "data_hora_fim" in control_matches else ""),
                    "primeira_data_rastreador": str(tracker_matches["data_hora"].min() if not tracker_matches.empty and "data_hora" in tracker_matches else ""),
                    "ultima_data_rastreador": str(tracker_matches["data_hora"].max() if not tracker_matches.empty and "data_hora" in tracker_matches else ""),
                    "chegada_origem": chegada_origem.isoformat(sep=" ", timespec="seconds") if chegada_origem else "",
                    "saida_origem": saida_origem.isoformat(sep=" ", timespec="seconds") if saida_origem else "",
                    "chegada_destino": chegada_destino.isoformat(sep=" ", timespec="seconds") if chegada_destino else "",
                    "saida_destino": saida_destino.isoformat(sep=" ", timespec="seconds") if saida_destino else "",
                    "control_chegada_origem": control_events["control_chegada_origem"].isoformat(sep=" ", timespec="seconds") if control_events.get("control_chegada_origem") else "",
                    "control_saida_origem": control_events["control_saida_origem"].isoformat(sep=" ", timespec="seconds") if control_events.get("control_saida_origem") else "",
                    "control_chegada_destino": control_events["control_chegada_destino"].isoformat(sep=" ", timespec="seconds") if control_events.get("control_chegada_destino") else "",
                    "control_saida_destino": control_events["control_saida_destino"].isoformat(sep=" ", timespec="seconds") if control_events.get("control_saida_destino") else "",
                    **comparison,
                    "tempo_origem_min": tempo_origem,
                    "tempo_destino_min": tempo_destino,
                    "regra_especial_origem": tracker_events.get("regra_especial_origem") or 0,
                    "regra_especial_destino": tracker_events.get("regra_especial_destino") or 0,
                    "municipio_operacional_origem": tracker_events.get("municipio_operacional_origem") or "",
                    "municipio_operacional_destino": tracker_events.get("municipio_operacional_destino") or "",
                    "metodo_localizacao_origem": tracker_events.get("metodo_localizacao_origem") or "",
                    "metodo_localizacao_destino": tracker_events.get("metodo_localizacao_destino") or "",
                    "qtd_blocos_municipio_origem": tracker_events.get("qtd_blocos_municipio_origem") or 0,
                    "qtd_blocos_municipio_destino": tracker_events.get("qtd_blocos_municipio_destino") or 0,
                    "bloco_selecionado_origem": tracker_events.get("bloco_selecionado_origem") or "",
                    "bloco_selecionado_destino": tracker_events.get("bloco_selecionado_destino") or "",
                    "referencias_visitadas_origem": tracker_events.get("referencias_visitadas_origem") or "",
                    "referencias_visitadas_destino": tracker_events.get("referencias_visitadas_destino") or "",
                    "motivo_escolha_bloco_origem": tracker_events.get("motivo_escolha_bloco_origem") or "",
                    "motivo_escolha_bloco_destino": tracker_events.get("motivo_escolha_bloco_destino") or "",
                    "confianca_permanencia_origem_pct": tracker_events.get("confianca_origem_pct") or 0,
                    "confianca_permanencia_destino_pct": tracker_events.get("confianca_destino_pct") or 0,
                    "motivo_confirmacao_saida_origem": tracker_events.get("motivo_saida_origem") or "",
                    "motivo_confirmacao_saida_destino": tracker_events.get("motivo_saida_destino") or "",
                    "interrupcoes_ignoradas_origem": tracker_events.get("interrupcoes_ignoradas_origem") or 0,
                    "interrupcoes_ignoradas_destino": tracker_events.get("interrupcoes_ignoradas_destino") or 0,
                    "maior_distancia_temporaria_cerca_origem_km": tracker_events.get("maior_distancia_temporaria_origem_km") or 0,
                    "maior_distancia_temporaria_cerca_destino_km": tracker_events.get("maior_distancia_temporaria_destino_km") or 0,
                    "tempo_oscilacao_absorvido_origem_min": tracker_events.get("tempo_oscilacao_absorvido_origem") or 0,
                    "tempo_oscilacao_absorvido_destino_min": tracker_events.get("tempo_oscilacao_absorvido_destino") or 0,
                    "tempo_operacional_min": tempo_operacional,
                    "tempo_transito_min": tempo_transito,
                    "tempo_total_viagem_min": tempo_total,
                    "tempo_control_min": tempo_control,
                    "tempo_rastreador_min": tempo_rastreador,
                    "diferenca_control_rastreador_min": diff_control_tracker,
                    "km_percorrido": round(float(_km_percorrido(tracker_matches) or _safe_float(trip.get("km_rota")) or 0), 2),
                    "distancia_ponto_carga_km": dist_carga if dist_carga is not None else 0,
                    "distancia_ponto_descarga_km": dist_descarga if dist_descarga is not None else 0,
                    "pontos_origem": pontos_origem,
                    "pontos_destino": pontos_destino,
                    "franquia_carga_min": franquia_carga_min,
                    "franquia_descarga_min": franquia_descarga_min,
                    "estadia_carga_min": estadia_carga_min,
                    "estadia_descarga_min": estadia_descarga_min,
                    "horas_estadia": horas_estadia,
                    "elegivel_cobranca": 1 if elegivel else 0,
                    "motivo_nao_elegibilidade": motivo_nao_elegibilidade,
                    "dentro_limite_operacional": 1,
                    "valor_estimado_estadia": valor_estimado,
                    "status_cruzamento": status,
                    **workflow,
                    "codigo_motivo": code,
                    "descricao_motivo": description,
                    "motivo_falha": "; ".join(f"{c}: {MOTIVOS.get(c, c)}" for c in dict.fromkeys(reason_codes)),
                    "diagnostico_json": json.dumps(diagnostic, ensure_ascii=False, default=str),
                    "log_processamento_json": json.dumps(log, ensure_ascii=False, default=str),
                }
            )
            rows.append(_apply_conclusion_state(row_payload, conclusoes.get(int(trip.get("id") or 0))))
        except Exception as exc:
            code, description = "PROCESSAMENTO_COM_ERRO", MOTIVOS["PROCESSAMENTO_COM_ERRO"]
            rows.append(
                _complete_row(
                    {
                    "lcte_id": int(trip.get("id") or 0),
                    "chave_viagem": str(trip.get("chave_viagem") or ""),
                    "cte": str(trip.get("cte") or ""),
                    "nf": str(trip.get("nf") or ""),
                    "placa_norm": plate,
                    "data_operacao": str(trip.get("data_operacao") or ""),
                    "origem": str(trip.get("origem") or ""),
                    "destino": str(trip.get("destino") or ""),
                    "cliente": str(trip.get("cliente") or ""),
                    "motorista": str(trip.get("motorista") or ""),
                    "encontrou_lcte": 1,
                    "status_lcte": "OK",
                    "painel_atual": "VERIFICACAO",
                    "status_processamento": "ERRO",
                    "status_permanencia": "NAO_IDENTIFICADA",
                    "status_estadia": "SEM_ESTADIA",
                    "status_verificacao": "PROCESSAMENTO_COM_ERRO",
                    "status_tratativa": "NAO_TRATADO",
                    "status_cte": "Erro no processamento",
                    "precisa_verificar": 1,
                    "status_cruzamento": "ERRO",
                    "codigo_motivo": code,
                    "descricao_motivo": description,
                    "motivo_falha": f"{code}: {description} {exc}",
                    "diagnostico_json": json.dumps({"erro": str(exc)}, ensure_ascii=False),
                    "log_processamento_json": json.dumps(log, ensure_ascii=False, default=str),
                    }
                )
            )
        current_progress = 10 + int((trip_index / total_trips) * 80)
        if current_progress != last_progress or trip_index == total_trips:
            last_progress = current_progress
            nf_label = str(trip.get("nf") or trip.get("cte") or "").strip() or "-"
            _emit_progress(progress_callback, current_progress, 100, f"Processando viagem {trip_index}/{total_trips} - NF/CT-e {nf_label}")
    _emit_progress(progress_callback, 90, 100, "Cruzamento calculado. Preparando gravacao...")
    return rows


def atualizar_cruzamento(usuario: str, progress_callback: ProgressCallback | None = None, placa_filtro: str | None = None) -> pd.DataFrame:
    rows = build_cross_rows(progress_callback, placa_filtro)
    _emit_progress(progress_callback, 95, 100, "Salvando resultado do cruzamento...")
    repository.replace_cross(rows, usuario)
    repository.registrar_auditoria(usuario, "PROCESSAR_ESTADIAS", valor_novo_json=json.dumps({"viagens": len(rows), "placa_filtro": _normalize_plate_candidate(placa_filtro)}, ensure_ascii=False))
    _emit_progress(progress_callback, 100, 100, "Atualizacao concluida.")
    return pd.DataFrame(rows)


def _row_signature(row: dict[str, Any]) -> str:
    ignored = {"id", "atualizado_em", "atualizado_por"}
    payload = {key: value for key, value in row.items() if key not in ignored}
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def atualizar_cruzamento_incremental(usuario: str, progress_callback: ProgressCallback | None = None, placa_filtro: str | None = None) -> tuple[pd.DataFrame, dict[str, int]]:
    plate_filter = _normalize_plate_candidate(placa_filtro)
    _emit_progress(progress_callback, 1, 100, "Lendo resultado anterior...")
    existing = repository.read_cross(300000)
    existing_by_lcte: dict[int, dict[str, Any]] = {}
    if not existing.empty and "lcte_id" in existing.columns:
        for row in existing.to_dict(orient="records"):
            try:
                existing_by_lcte[int(row.get("lcte_id") or 0)] = row
            except Exception:
                continue

    def build_progress(current: int, total: int, message: str) -> None:
        mapped = 2 + int((current / max(total, 1)) * 86)
        _emit_progress(progress_callback, mapped, 100, message)

    recalculated_rows = build_cross_rows(build_progress, plate_filter)
    _emit_progress(progress_callback, 89, 100, "Comparando registros novos e alterados...")
    rows: list[dict[str, Any]] = []
    new_count = 0
    changed_count = 0
    preserved_count = 0
    recalculated_ids: set[int] = set()
    for row in recalculated_rows:
        try:
            recalculated_ids.add(int(row.get("lcte_id") or 0))
        except Exception:
            continue
    if plate_filter and not recalculated_ids:
        summary = {
            "registros_novos": 0,
            "registros_atualizados": 0,
            "viagens_control": 0,
            "viagens_rastreador": 0,
            "estadias_identificadas": 0,
            "pendencias": 0,
            "concluidos_preservados": 0,
            "erros": 0,
        }
        _emit_progress(progress_callback, 100, 100, f"Nenhuma viagem LCTE encontrada para a placa {plate_filter}.")
        return existing, summary
    if plate_filter and not existing.empty and "lcte_id" in existing.columns:
        existing_rows = existing.to_dict(orient="records")
        for old in existing_rows:
            try:
                old_lcte_id = int(old.get("lcte_id") or 0)
            except Exception:
                old_lcte_id = 0
            if old_lcte_id not in recalculated_ids:
                rows.append(old)
    for row in recalculated_rows:
        lcte_id = int(row.get("lcte_id") or 0)
        old = existing_by_lcte.get(lcte_id)
        if old and int(old.get("concluido") or 0) == 1 and str(old.get("painel_atual") or "").upper() == "CONCLUIDOS":
            rows.append(old)
            preserved_count += 1
            continue
        if not old:
            new_count += 1
        elif _row_signature(row) != _row_signature(old):
            changed_count += 1
        rows.append(row)

    _emit_progress(progress_callback, 95, 100, "Salvando resultado atualizado...")
    repository.replace_cross(rows, usuario)
    result = pd.DataFrame(rows)
    summary_base = pd.DataFrame(recalculated_rows) if plate_filter else result
    summary = {
        "registros_novos": int(new_count),
        "registros_atualizados": int(changed_count),
        "viagens_control": int(summary_base.get("encontrou_control", pd.Series(dtype=int)).fillna(0).astype(int).eq(1).sum()) if not summary_base.empty else 0,
        "viagens_rastreador": int(summary_base.get("encontrou_rastreador", pd.Series(dtype=int)).fillna(0).astype(int).eq(1).sum()) if not summary_base.empty else 0,
        "estadias_identificadas": int(summary_base.get("painel_atual", pd.Series(dtype=str)).fillna("").astype(str).str.upper().eq("ESTADIAS").sum()) if not summary_base.empty else 0,
        "pendencias": int(summary_base.get("painel_atual", pd.Series(dtype=str)).fillna("").astype(str).str.upper().eq("VERIFICACAO").sum()) if not summary_base.empty else 0,
        "concluidos_preservados": int(preserved_count),
        "erros": int(summary_base.get("status_cruzamento", pd.Series(dtype=str)).fillna("").astype(str).str.upper().eq("ERRO").sum()) if not summary_base.empty else 0,
    }
    _emit_progress(progress_callback, 98, 100, "Registrando auditoria...")
    repository.registrar_auditoria(usuario, "ATUALIZAR_ESTADIAS_INCREMENTAL", valor_novo_json=json.dumps(summary | {"placa_filtro": plate_filter}, ensure_ascii=False))
    _emit_progress(progress_callback, 100, 100, "Atualizacao concluida.")
    return result, summary
