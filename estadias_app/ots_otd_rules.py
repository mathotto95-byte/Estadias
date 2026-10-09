"""Regras oficiais OTS/OTD, independentes de Streamlit, GitHub e banco."""

import re

import pandas as pd


UNKNOWN = "Sem informação"
RULES = ("OTS 2", "OTS 3", "OTD 1", "OTD 2", "OTD 3")


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


def calcular_ots2(schedule, **_):
    return _compare(schedule.get("agendamento_carga"), schedule.get("previsao_carga"))


def calcular_ots3(schedule, origem=None, **_):
    return _compare(origem, schedule.get("agendamento_carga") or schedule.get("previsao_carga"))


def calcular_otd1(schedule, emissao_nf=None, **_):
    registro, emissao = _day(schedule.get("data_hora_registro")), _day(emissao_nf)
    return ("Dentro do prazo" if registro == emissao else "Fora do prazo") if registro and emissao else UNKNOWN


def calcular_otd2(schedule, destino=None, **_):
    deadline = schedule.get("data_limite")
    status = _compare(schedule.get("agenda_gfl"), deadline)
    if status == "Fora do prazo" and _compare(destino, deadline) == "Dentro do prazo":
        status = "Dentro do prazo"
    dia_limite = _day(deadline)
    if dia_limite and dia_limite.weekday() == 6:
        return "Dentro do prazo" if _day(destino) == dia_limite else "Fora do prazo"
    return status


def calcular_otd3(schedule, destino=None, **_):
    dia_limite, dia_chegada = _day(schedule.get("data_limite")), _day(destino)
    return ("Dentro do prazo" if dia_chegada == dia_limite else "Fora do prazo") if dia_chegada and dia_limite else UNKNOWN


def avaliar_regras_viagem(schedule, origem=None, destino=None, emissao_nf=None):
    context = {"origem": origem, "destino": destino, "emissao_nf": emissao_nf}
    result = {
        "OTS 2": calcular_ots2(schedule, **context),
        "OTS 3": calcular_ots3(schedule, **context),
        "OTD 1": calcular_otd1(schedule, **context),
        "OTD 2": calcular_otd2(schedule, **context),
        "OTD 3": calcular_otd3(schedule, **context),
    }
    values = list(result.values())
    result["Dentro da Regra"] = "Não" if "Fora do prazo" in values else "Sim" if all(value == "Dentro do prazo" for value in values) else UNKNOWN
    return result
