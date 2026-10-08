"""Consome classificações do PerformanceRW. Não calcula regras de pontualidade."""
import json
import re
from urllib.error import HTTPError, URLError

import pandas as pd

RULES = ["OTS 2", "OTS 3", "OTD 1", "OTD 2", "OTD 3"]
SCHEDULE_FIELDS = ["Previsão de Carga", "Agendamento de Carga", "Data Limite", "Agenda GFL"]
DISPLAY_FIELDS = [*SCHEDULE_FIELDS, "Dentro da Regra"]


def clean(value):
    return "" if value is None or pd.isna(value) else str(value).strip()


def _same_arrival(remote, current):
    remote, current = clean(remote), clean(current)
    if remote == current:
        return True
    a, b = pd.to_datetime(remote, errors="coerce"), pd.to_datetime(current, errors="coerce")
    return bool(pd.notna(a) and pd.notna(b) and a == b)


def receive():
    import streamlit as st
    from estadias_app.github_backup import github_settings, _download_text
    settings = github_settings()
    settings.update(repository="mathotto95-byte/Performance", branch="main")
    try:
        settings["token"] = st.secrets.get("performance_results", {}).get("token") or settings["token"]
    except FileNotFoundError:
        pass
    try:
        payload = json.loads(_download_text(settings, "backups/performance_latest.json"))
    except (HTTPError, URLError, TimeoutError, ValueError):
        raise ValueError("Não foi possível receber a análise. Publique no Performance e confira o token de leitura do repositório Performance.") from None
    validate(payload)
    return payload


def validate(payload):
    if not isinstance(payload, dict) or payload.get("schema") != "performance_results_v1" or not isinstance(payload.get("rows"), list):
        raise ValueError("Resultado PerformanceRW inválido.")
    if pd.isna(pd.to_datetime(payload.get("analyzed_at"), errors="coerce")) or not isinstance(payload.get("sources"), dict):
        raise ValueError("Resultado sem data ou identificação das bases.")
    keys = set()
    for row in payload["rows"]:
        if not isinstance(row, dict) or not {"Nota Fiscal", "Placa", "Atendeu todas as regras", "Correspondência Estadias", *RULES}.issubset(row):
            raise ValueError("Resultado incompleto.")
        key = (clean(row["Nota Fiscal"]), clean(row["Placa"]))
        if not all(key) or key in keys:
            raise ValueError("Resultado sem chave única NF + placa.")
        keys.add(key)
        if row["Atendeu todas as regras"] not in {"Sim", "Não", "Sem informação"} or any(row[r] not in {"Dentro do prazo", "Fora do prazo", "Sem informação"} for r in RULES):
            raise ValueError("Classificação PerformanceRW inválida.")


def attach(cross, payload):
    validate(payload)
    records = {(r["Nota Fiscal"], r["Placa"]): r for r in payload["rows"]}
    rows = []
    for row in cross.to_dict("records"):
        plate = re.sub(r"[^A-Z0-9]", "", clean(row.get("placa_norm")).upper())
        for nf in {n.removesuffix(".0").lstrip("0") or "0" for n in re.split(r"[;,/|\s]+", clean(row.get("nf"))) if n}:
            rows.append({"Nota Fiscal": nf, "Placa": plate, "Origem": clean(row.get("origem")), "Destino": clean(row.get("destino")),
                         "_arrival_origin": clean(row.get("chegada_origem")), "_arrival_destination": clean(row.get("chegada_destino")),
                         "_trip_key": clean(row.get("chave_viagem")), "_id": clean(row.get("lcte_id")) or clean(row.get("id"))})
    result = []
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    for key, group in frame.drop_duplicates().groupby(["Nota Fiscal", "Placa"], sort=False):
        source = records.get(key, {})
        status = source.get("Correspondência Estadias")
        compatible = status in {"Exata", "NF + placa exata; viagem duplicada compatível"}
        same_trip = bool(group["_trip_key"].iloc[0]) and group["_trip_key"].nunique() == 1
        linked = bool(source) and compatible and (len(group) == 1 or same_trip)
        for local in group.to_dict("records"):
            origin_current = linked and _same_arrival(source.get("Chegada na Origem"), local["_arrival_origin"])
            destination_current = linked and _same_arrival(source.get("Chegada no Destino"), local["_arrival_destination"])
            matching = origin_current and destination_current
            reason = ("NF + placa ausentes no resultado publicado" if not source else
                      "NF + placa identificam viagens diferentes; vínculo ambíguo" if not linked else
                      "Chegada GPS alterada desde a publicação: reimporte o backup atual no PerformanceRW, analise e publique novamente")
            item = {k: v for k, v in local.items() if not k.startswith("_")}
            item["lcte_id"] = local["_id"]
            item.update({field: clean(source.get(field)) if linked else "" for field in SCHEDULE_FIELDS})
            item["Dentro da Regra"] = source["Atendeu todas as regras"] if matching else "Sem informação"
            item.update({r: source[r] if linked and (r in {"OTS 2", "OTD 1", "OTD 2"} or (r == "OTS 3" and origin_current) or (r == "OTD 3" and destination_current)) else "Sem informação" for r in RULES})
            item["Atendeu todas as regras"] = source["Atendeu todas as regras"] if matching else "Sem informação"
            item["Correspondência"] = "Exata" if matching else ("Parcial" if linked else "Sem correspondência")
            item["Motivo do vínculo"] = "" if matching else reason
            item["Data/Hora da última análise"] = payload["analyzed_at"] if matching else ""
            item["Motivo da classificação"] = source.get("Motivo da classificação", "") if matching else reason
            result.append(item)
    return pd.DataFrame(result)


def enrich_summary(summary, cross, payload):
    """Exibe resultados publicados, sem recalcular regras nem alterar viagens."""
    result = summary.copy()
    for field in [*DISPLAY_FIELDS, *RULES, "Correspondência PerformanceRW", "Motivo vínculo PerformanceRW"]:
        result[field] = "Sem informação" if field == "Dentro da Regra" else ""
    if result.empty or not payload:
        return result
    received = attach(cross, payload)
    lookup = {(r["Nota Fiscal"], r["Placa"], r["lcte_id"]): r for r in received.to_dict("records")}
    fallback_lookup = {(r["Nota Fiscal"], r["Placa"]): r for r in received.to_dict("records")}
    for index, row in result.iterrows():
        plate = re.sub(r"[^A-Z0-9]", "", clean(row.get("Placa")).upper())
        notes = sorted({n.removesuffix(".0").lstrip("0") or "0" for n in re.split(r"[;,/|\s]+", clean(row.get("Notas"))) if n})
        trip_id = clean(row.get("lcte_id"))
        matches = [lookup.get((nf, plate, trip_id), fallback_lookup.get((nf, plate), {}) if not trip_id else {}) for nf in notes]
        result.at[index, "Correspondência PerformanceRW"] = ("Exata" if matches and all(m.get("Correspondência") == "Exata" for m in matches) else
                                                               "Parcial" if matches and all(m.get("Correspondência") in {"Exata", "Parcial"} for m in matches) else "Sem correspondência")
        result.at[index, "Motivo vínculo PerformanceRW"] = "; ".join(dict.fromkeys(m.get("Motivo do vínculo") or "NF + placa não localizadas no LCTE atual" for m in matches)) if matches else "NF ausente"
        for field in [*DISPLAY_FIELDS, *RULES]:
            fallback = "Sem informação" if field == "Dentro da Regra" else ""
            values = [(nf, match.get(field, fallback)) for nf, match in zip(notes, matches)]
            unique = {value for _, value in values}
            if len(unique) == 1:
                result.at[index, field] = next(iter(unique))
            elif values:
                result.at[index, field] = "; ".join(f"NF {nf}: {value or 'Sem informação'}" for nf, value in values)
    return result
