"""Consulta o backup OTS/OTD e cruza seus prazos com as viagens GPS atuais."""

import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd

from estadias_app.ots_otd_rules import RULES, UNKNOWN, _date, _text, avaliar_regras_viagem


FIELDS = ("Previsão de Carga", "Agendamento de Carga", "Data Limite", "Agenda GFL")
REQUIRED = {"id", "previsao_carga", "data_limite", "agendamento_carga", "agenda_gfl", "codigo_monitoramento", "data_hora_registro"}


def _registro_local(row):
    value = _date(row.get("data_hora_registro"))
    return value.tz_convert("America/Sao_Paulo").tz_localize(None) if pd.notna(value) and value.tzinfo else value


def receive():
    from estadias_app.github_backup import github_settings

    token = github_settings()["token"]
    url = "https://api.github.com/repos/mathotto95-byte/OTSeOTD/contents/backups/ots_otd_latest.json?ref=main"
    headers = {"Accept": "application/vnd.github.raw+json", "User-Agent": "Estadias"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with urlopen(Request(url, headers=headers), timeout=10) as response:
            payload = json.load(response)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ValueError(f"Backup OTS/OTD indisponível ({getattr(exc, 'code', 'conexão')}). O GITHUB_TOKEN do Estadias também precisa ter leitura no repositório OTSeOTD.") from None
    if not isinstance(payload, dict) or payload.get("schema") != "ots_otd_backup_v1":
        raise ValueError("Backup OTS/OTD inválido; dados atuais preservados.")
    rows = payload.get("rows")
    if not isinstance(rows, list) or payload.get("records") != len(rows) or any(not isinstance(row, dict) or not REQUIRED.issubset(row) for row in rows):
        raise ValueError("Backup OTS/OTD incompleto; dados atuais preservados.")
    if len({row["id"] for row in rows}) != len(rows):
        raise ValueError("Backup OTS/OTD com IDs duplicados; dados atuais preservados.")
    return payload


def enrich_summary(summary, payload):
    result = summary.copy()
    for field in (*FIELDS, *RULES, "Dentro da Regra", "Correspondência OTS/OTD", "Motivo vínculo OTS/OTD"):
        result[field] = UNKNOWN if field in (*RULES, "Dentro da Regra") else ""
    if result.empty or not payload:
        return result
    arrivals = {}
    if "Tipo" in result.columns and "lcte_id" in result.columns:
        for _, stay in result.iterrows():
            arrivals.setdefault(stay.get("lcte_id"), {})[stay.get("Tipo")] = _text(stay.get("Chegada Rastreador"))
    rows = payload["rows"]
    schedules = {}
    for row in rows:
        code = _text(row.get("codigo_monitoramento"))
        if re.fullmatch(r"\d{7}", code):
            schedules.setdefault(code, []).append(row)
    schedules = {code: max(group, key=lambda row: (_registro_local(row), int(row.get("id") or 0)))
                 for code, group in schedules.items() if all(pd.notna(_registro_local(row)) for row in group)}
    identities = {}
    for _, row in result.iterrows():
        plate = re.sub(r"[^A-Z0-9]", "", _text(row.get("Placa")).upper())
        for nf in re.split(r"[;,/|\s]+", _text(row.get("Notas"))):
            if nf:
                identities.setdefault((nf.removesuffix(".0").lstrip("0") or "0", plate), set()).add((_text(row.get("monitoramento")), _text(row.get("lcte_id"))))
    for index, row in result.iterrows():
        code = _text(row.get("monitoramento"))
        plate = re.sub(r"[^A-Z0-9]", "", _text(row.get("Placa")).upper())
        notes = [nf.removesuffix(".0").lstrip("0") or "0" for nf in re.split(r"[;,/|\s]+", _text(row.get("Notas"))) if nf]
        reason = ""
        if not re.fullmatch(r"\d{7}", code):
            reason = "Monitoramento de 7 dígitos ausente no LCTE"
        elif not plate or not notes:
            reason = "NF ou placa ausente no LCTE"
        elif any(identities.get((nf, plate)) != {(code, _text(row.get("lcte_id")))} for nf in notes):
            reason = "NF + placa vinculadas a mais de uma viagem ou monitoramento"
        elif code not in schedules:
            reason = "Monitoramento não localizado no backup OTS/OTD ou histórico inválido"
        if reason:
            result.at[index, "Motivo vínculo OTS/OTD"] = reason
            continue
        schedule = schedules[code]
        for target, source in zip(FIELDS, ("previsao_carga", "agendamento_carga", "data_limite", "agenda_gfl")):
            result.at[index, target] = _text(schedule.get(source))
        trip_arrivals = arrivals.get(row.get("lcte_id"), {})
        origin = trip_arrivals.get("ORIGEM") or _text(row.get("Chegada Rastreador Carga"))
        destination = trip_arrivals.get("DESTINO") or _text(row.get("Chegada Rastreador Descarga"))
        issued = row.get("Data Emissao NF") or row.get("data_emissao_nf")
        for field, value in avaliar_regras_viagem(schedule, origin, destination, issued).items():
            result.at[index, field] = value
        result.at[index, "Correspondência OTS/OTD"] = "Exata"
    return result
