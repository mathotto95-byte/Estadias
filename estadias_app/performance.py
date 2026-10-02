"""Consome classificações do PerformanceRW. Não calcula regras de pontualidade."""
import json
import re
from urllib.error import HTTPError, URLError

import pandas as pd

RULES = ["OTS 2", "OTS 3", "OTD 1", "OTD 2", "OTD 3"]


def clean(value):
    return "" if value is None or pd.isna(value) else str(value).strip()


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
                         "_id": clean(row.get("lcte_id")) or clean(row.get("id"))})
    result = []
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    for key, group in frame.drop_duplicates().groupby(["Nota Fiscal", "Placa"], sort=False):
        local = group.iloc[0].to_dict()
        source = records.get(key, {})
        matching = len(group) == 1 and source.get("Correspondência Estadias") == "Exata"
        reason = "Sem correspondência exata e única na análise publicada"
        if matching:
            for remote_col, local_col in [("Chegada na Origem", "_arrival_origin"), ("Chegada no Destino", "_arrival_destination")]:
                remote, current = clean(source.get(remote_col)), local[local_col]
                if remote == current:
                    continue
                a, b = pd.to_datetime(remote, errors="coerce"), pd.to_datetime(current, errors="coerce")
                if pd.isna(a) or pd.isna(b) or a != b:
                    matching = False
                    reason = "Dados do Estadias mudaram após a análise; sincronize e publique novamente"
                    break
        item = {k: v for k, v in local.items() if not k.startswith("_")}
        item.update({r: source[r] if matching else "Sem informação" for r in RULES})
        item["Atendeu todas as regras"] = source["Atendeu todas as regras"] if matching else "Sem informação"
        item["Correspondência"] = "Exata" if matching else "Sem correspondência"
        item["Data/Hora da última análise"] = payload["analyzed_at"] if matching else ""
        item["Motivo da classificação"] = source.get("Motivo da classificação", "") if matching else reason
        result.append(item)
    return pd.DataFrame(result)
