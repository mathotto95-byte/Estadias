"""Consulta o backup OTS/OTD e cruza seus prazos com as viagens GPS atuais."""

import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd


RULES = ("OTS 2", "OTS 3", "OTD 1", "OTD 2", "OTD 3")
FIELDS = ("Previsão de Carga", "Agendamento de Carga", "Data Limite", "Agenda GFL")
UNKNOWN = "Sem informação"
REQUIRED = {"id", "previsao_carga", "data_limite", "agendamento_carga", "agenda_gfl", "codigo_monitoramento", "data_hora_registro"}


def _text(value):
    return "" if value is None or pd.isna(value) else str(value).strip()


def _date(value):
    value = _text(value)
    return pd.to_datetime(value, dayfirst=not bool(re.match(r"^\d{4}-\d\d-\d\d", value)), errors="coerce") if value else pd.NaT


def _day(value):
    parsed = _date(value)
    if pd.isna(parsed):
        return None
    return (parsed.tz_convert("America/Sao_Paulo") if parsed.tzinfo else parsed).date()


def _compare(actual, deadline):
    a, b = _date(actual), _date(deadline)
    if pd.isna(a) or pd.isna(b):
        return UNKNOWN
    if a.tzinfo:
        a = a.tz_convert("America/Sao_Paulo").tz_localize(None)
    if b.tzinfo:
        b = b.tz_convert("America/Sao_Paulo").tz_localize(None)
    if not re.search(r"\d{1,2}:\d{2}", _text(deadline)):
        return "Dentro do prazo" if a.date() <= b.date() else "Fora do prazo"
    if not re.search(r"\d{1,2}:\d{2}", _text(actual)) and a.date() == b.date():
        return UNKNOWN
    return "Dentro do prazo" if a <= b else "Fora do prazo"


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
    schedules = {code: max(group, key=lambda row: (_date(row.get("data_hora_registro")) if pd.notna(_date(row.get("data_hora_registro"))) else pd.Timestamp.min, int(row.get("id") or 0)))
                 for code, group in schedules.items() if all(pd.notna(_date(row.get("data_hora_registro"))) for row in group)}
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
        result.at[index, "OTS 2"] = _compare(schedule.get("agendamento_carga"), schedule.get("previsao_carga"))
        result.at[index, "OTS 3"] = _compare(origin, schedule.get("agendamento_carga") or schedule.get("previsao_carga"))
        result.at[index, "OTD 2"] = _compare(schedule.get("agenda_gfl"), schedule.get("data_limite"))
        if result.at[index, "OTD 2"] == "Fora do prazo" and _compare(destination, schedule.get("data_limite")) == "Dentro do prazo":
            result.at[index, "OTD 2"] = "Dentro do prazo"
        if _day(schedule.get("data_limite")) and _day(schedule.get("data_limite")).weekday() == 6:
            sunday = _day(destination) == _day(schedule.get("data_limite"))
            result.at[index, "OTD 2"] = "Dentro do prazo" if sunday else "Fora do prazo"
            result.at[index, "OTD 3"] = "Dentro do prazo" if sunday else "Fora do prazo"
        else:
            result.at[index, "OTD 3"] = ("Dentro do prazo" if _day(destination) == _day(schedule.get("data_limite")) else "Fora do prazo") if _day(destination) and _day(schedule.get("data_limite")) else UNKNOWN
        registered = _day(schedule.get("data_hora_registro"))
        emitted = _day(issued)
        result.at[index, "OTD 1"] = ("Dentro do prazo" if registered == emitted else "Fora do prazo") if registered and emitted else UNKNOWN
        values = [result.at[index, rule] for rule in RULES]
        result.at[index, "Dentro da Regra"] = "Não" if "Fora do prazo" in values else "Sim" if all(value == "Dentro do prazo" for value in values) else UNKNOWN
        result.at[index, "Correspondência OTS/OTD"] = "Exata"
    return result
