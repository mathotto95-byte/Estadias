from __future__ import annotations

import hashlib
import gc
import json
import re
from io import BytesIO
from pathlib import Path
from typing import Any, BinaryIO, Callable

import pandas as pd

from src.modules.estadias.logs import registrar_log_importacao
from src.modules.estadias.normalizers import (
    extrair_placa_do_nome_arquivo,
    identificar_coluna_flexivel,
    normalizar_data,
    normalizar_data_hora,
    normalizar_hora,
    normalizar_placa,
    normalizar_texto,
    normalizar_valor_monetario,
    row_value,
)
from src.modules.estadias.repository import (
    CONTROL_NORMALIZED_TABLE,
    CONTROL_ORIGINAL_TABLE,
    LCTE_NORMALIZED_TABLE,
    LCTE_ORIGINAL_TABLE,
    RASTREADOR_NORMALIZED_TABLE,
    RASTREADOR_ORIGINAL_TABLE,
    delete_by_hash,
    hash_already_imported,
    insert_rows,
)
from src.utils.timezone import brasilia_now, brasilia_now_iso


CONTROL_ALIASES = {
    "placa": ["placa", "veiculo", "veículo", "cavalo", "frota"],
    "motorista": ["motorista", "condutor"],
    "cliente": ["cliente", "tomador"],
    "razao_social": ["razao social", "razão social", "razao social cobranca", "razão social cobrança"],
    "local_origem": ["origem", "local origem", "local da coleta"],
    "local_destino": ["destino", "local destino", "local da entrega"],
    "local_evento": ["local evento", "local", "endereco", "endereço"],
    "data_inicio": ["data inicio", "data início", "dt inicio", "data entrada", "inicio"],
    "hora_inicio": ["hora inicio", "hora início", "hr inicio", "hora entrada"],
    "data_fim": ["data fim", "dt fim", "data saida", "data saída", "fim"],
    "hora_fim": ["hora fim", "hr fim", "hora saida", "hora saída"],
    "data_hora_inicio": ["data hora inicio", "data/hora inicio", "data hora entrada", "chegada"],
    "data_hora_fim": ["data hora fim", "data/hora fim", "data hora saida", "saida"],
    "tipo_evento": ["tipo evento", "evento", "ocorrencia", "ocorrência"],
    "status": ["status", "situacao", "situação"],
    "observacao": ["observacao", "observação", "obs"],
    "valor_estadia": ["valor estadia", "valor", "vl estadia"],
    "tempo_total": ["tempo total", "tempo", "duracao", "duração", "permanencia", "permanência"],
    "data_hora_inicio_carga": ["data inicio carga", "data início carga", "inicio carga", "início carga", "dt inicio carga", "dt início carga"],
    "data_hora_fim_carga": ["data termino carga", "data término carga", "termino carga", "término carga", "fim carga", "dt termino carga", "dt término carga"],
    "tempo_carga": ["tempo carga", "tempo de carga"],
    "data_hora_inicio_descarga": ["data inicio descarga", "data início descarga", "inicio descarga", "início descarga", "dt inicio descarga", "dt início descarga"],
    "data_hora_fim_descarga": ["data termino descarga", "data término descarga", "termino descarga", "término descarga", "fim descarga", "dt termino descarga", "dt término descarga"],
    "tempo_descarga": ["tempo descarga", "tempo de descarga"],
    "remetente": ["remetente"],
    "destinatario": ["destinatario", "destinatário"],
    "operacao": ["operacao", "operação"],
    "mercadoria": ["mercadoria", "produto"],
    "romaneio": ["romaneio", "numero romaneio", "n romaneio"],
    "numero_documento": ["numero documento", "n documento", "documento"],
    "cte": ["cte", "ct-e", "conhecimento"],
    "nf": ["nf", "nota fiscal", "nota"],
    "pedido": ["pedido"],
    "viagem": ["viagem"],
}

LCTE_ALIASES = {
    "cte": ["cte", "ct-e", "conhecimento", "numero cte", "numero ct-e", "n cte"],
    "nf": ["nf", "nota fiscal", "nota", "numero nf", "n nf", "notas fiscais"],
    "chave_nf": ["chave nf", "chave nfe", "chave da nf", "chave nota fiscal"],
    "placa": ["placa", "placa tracao", "placa tração", "frota tracao", "frota tração", "veiculo", "veiculo tracao", "cavalo", "frota"],
    "placas_composicao": ["placas composicao", "placas composição", "composicao", "composição", "carretas", "placa carreta", "placas"],
    "motorista": ["motorista", "condutor"],
    "cliente": ["cliente", "tomador", "razao social", "razao social cobranca", "destinatario"],
    "razao_social_cobranca": ["razao social cobranca", "razão social cobrança", "cobranca", "cobrança", "tomador"],
    "remetente": ["remetente", "embarcador"],
    "destinatario": ["destinatario", "destinatário", "recebedor"],
    "data_emissao": ["data emissao", "data emissão", "emissao cte", "emissão cte", "data cte"],
    "data_carga": [
        "data carga",
        "dt carga",
        "data da carga",
        "data coleta",
        "dt coleta",
        "data operacao",
        "data emissao",
        "data emissão",
        "data da emissao",
        "data da emissão",
        "dt emissao",
        "dt emissão",
        "emissao",
        "emissão",
        "emissao cte",
        "emissão cte",
        "data cte",
    ],
    "hora_carga": ["hora carga", "hr carga", "hora coleta", "hr coleta", "horario carga", "horario da carga"],
    "data_hora_carga": ["data hora carga", "data/hora carga", "data hora coleta", "data/hora coleta", "inicio carga"],
    "origem": [
        "origem",
        "cidade origem",
        "local origem",
        "base origem",
        "ponto carga",
        "local da carga",
        "local coleta",
        "coleta",
        "municipio remetente",
        "município remetente",
        "municipio do remetente",
        "município do remetente",
        "municipio do remetente origem",
        "município do remetente origem",
        "cidade remetente",
        "cidade do remetente",
    ],
    "uf_origem": ["uf origem", "estado origem", "uf coleta", "uf remetente", "uf do remetente", "estado remetente", "estado do remetente"],
    "destino": [
        "destino",
        "cidade destino",
        "local destino",
        "base destino",
        "ponto descarga",
        "local da descarga",
        "local entrega",
        "entrega",
        "municipio destinatario",
        "município destinatário",
        "municipio do destinatario",
        "município do destinatário",
        "municipio do destinatario destino",
        "município do destinatário destino",
        "cidade destinatario",
        "cidade destinatário",
        "cidade do destinatario",
        "cidade do destinatário",
    ],
    "uf_destino": ["uf destino", "estado destino", "uf entrega", "uf destinatario", "uf destinatário", "uf do destinatario", "uf do destinatário", "estado destinatario", "estado destinatário", "estado do destinatario", "estado do destinatário"],
    "volume": ["volume", "quantidade", "qtd", "peso", "litros", "m3"],
    "produto": ["produto", "mercadoria"],
    "tabela_frete": ["tabela frete", "tabela de frete", "tarifa", "nome tabela"],
    "pedido": ["pedido", "numero pedido", "n pedido"],
    "romaneio": ["romaneio", "numero romaneio", "n romaneio"],
    "numero_viagem": ["viagem", "numero viagem", "n viagem", "id viagem"],
    "km_rota": ["km", "km rota", "distancia", "distancia rota"],
    "valor_frete": ["valor frete", "valor", "total conhecimento", "valor cte"],
    "latitude_origem": ["latitude origem", "lat origem", "lat carga"],
    "longitude_origem": ["longitude origem", "lng origem", "long origem", "lon origem", "lng carga"],
    "latitude_destino": ["latitude destino", "lat destino", "lat descarga"],
    "longitude_destino": ["longitude destino", "lng destino", "long destino", "lon destino", "lng descarga"],
    "observacao": ["observacao", "obs", "comentario"],
}

RASTREADOR_ALIASES = {
    "placa": ["placa", "veiculo", "veículo"],
    "data": ["data", "dt evento"],
    "hora": ["hora", "hr evento"],
    "data_hora": ["data hora", "data/hora", "data evento", "data gps", "data posição", "data posicao"],
    "latitude": ["latitude", "lat"],
    "longitude": ["longitude", "lng", "lon", "long"],
    "endereco": ["endereco", "endereço", "localizacao", "localização", "posicao", "posição"],
    "cidade": ["cidade", "municipio", "município"],
    "uf": ["uf", "estado"],
    "velocidade": ["velocidade", "vel"],
    "ignicao": ["ignicao", "ignição", "ignition"],
    "evento": ["evento", "ocorrencia", "ocorrência"],
    "status": ["status", "situacao", "situação"],
    "odometro": ["odometro", "odômetro", "km", "hodometro", "hodômetro"],
    "motorista": ["motorista", "condutor"],
}

CONTROL_ALIASES["placa"].extend(["frota tracao", "frota traÃ§Ã£o", "placa tracao", "placa traÃ§Ã£o"])
CONTROL_ALIASES["local_origem"].extend(["carregamento", "local carregamento"])
CONTROL_ALIASES["local_destino"].extend(["descarga", "entrega", "destino"])
CONTROL_ALIASES["data_hora_inicio"].extend(["dt carga i", "dt carga (i)", "data carga i", "data carga inicio", "dt prev c", "dt prev (c)", "data inicio"])
CONTROL_ALIASES["data_hora_fim"].extend(["dt descarga i", "dt descarga (i)", "data descarga i", "data descarga inicio"])
CONTROL_ALIASES["data_hora_inicio"].extend(["dt carga t", "dt carga (t)", "data carga t", "previsao carga", "previsão carga"])
CONTROL_ALIASES["data_hora_fim"].extend(["dt descarga t", "dt descarga (t)", "data descarga t"])
CONTROL_ALIASES["status"].extend(["situacao romaneio", "situaÃ§Ã£o romaneio", "conferencia romaneio", "conferÃªncia romaneio"])
CONTROL_ALIASES["observacao"].extend(["alterado em", "alterado por"])
CONTROL_ALIASES["tempo_total"].extend(["tempo carga", "tempo descarga"])
CONTROL_ALIASES["numero_documento"].extend(["nÂº conhec", "n conhec"])
CONTROL_ALIASES["cte"].extend(["documento"])
CONTROL_ALIASES["nf"].extend(["notas fiscais"])
CONTROL_ALIASES["numero_documento"].extend(["romaneio"])
CONTROL_ALIASES["viagem"].extend(["romaneio"])
CONTROL_ALIASES["numero_documento"].extend(["no conhec"])
CONTROL_ALIASES["viagem"].extend(["no viagem"])
CONTROL_ALIASES["viagem"].extend(["n viagem", "nÂº viagem", "numero viagem", "nÃºmero viagem"])

LCTE_ALIASES["cte"].extend(["nÂº conhec", "n conhec", "nÃºmero conhec"])
LCTE_ALIASES["nf"].extend(["notas fiscais"])
LCTE_ALIASES["data_emissao"].extend(["data emissao nf", "data emissÃ£o nf"])
LCTE_ALIASES["data_carga"].extend(["data emissao nf", "data emissão nf"])
LCTE_ALIASES["origem"].extend(["local da coleta"])
LCTE_ALIASES["destino"].extend(["local da entrega"])
LCTE_ALIASES["cte"].extend(["no conhec", "numero conhec"])
LCTE_ALIASES["numero_viagem"].extend(["no viagem"])

RASTREADOR_ALIASES["placa"].insert(0, "frota")
RASTREADOR_ALIASES["data_hora"].extend(["data"])
RASTREADOR_ALIASES["ignicao"].extend(["ignicao ligada", "ignição ligada"])
RASTREADOR_ALIASES["cidade"].extend(["municipio da referencia", "município da referência"])
RASTREADOR_ALIASES["endereco"].extend(["referencia", "referÃªncia", "cliente referencia", "cliente referÃªncia", "descricao referencia", "descriÃ§Ã£o referÃªncia"])
RASTREADOR_ALIASES["cidade"].extend(["municipio referencia", "municÃ­pio referÃªncia"])

LCTE_REQUIRED_FIELDS = {
    "placa": "Placa",
    "data_carga": "Data da carga",
    "origem": "Origem",
    "destino": "Destino",
}

RASTREADOR_INSERT_CHUNK_SIZE = 1000


def _file_bytes(file: BinaryIO) -> bytes:
    if hasattr(file, "getvalue"):
        return bytes(file.getvalue())
    file.seek(0)
    content = file.read()
    file.seek(0)
    return content


def hash_file_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def make_lote(tipo: str) -> str:
    return f"ESTADIAS_{tipo}_{brasilia_now().strftime('%Y%m%d_%H%M%S')}"


def read_tabular_file(file_name: str, content: bytes) -> tuple[pd.DataFrame, str]:
    suffix = Path(file_name).suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(BytesIO(content), dtype=object).dropna(how="all").reset_index(drop=True), "CSV"
    with pd.ExcelFile(BytesIO(content)) as excel:
        sheet_name = excel.sheet_names[0]
    df = pd.read_excel(BytesIO(content), sheet_name=sheet_name, dtype=object)
    return df.dropna(how="all").reset_index(drop=True), sheet_name


def _clean_value(value: Any) -> Any:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def row_json(row: dict[str, Any]) -> str:
    return json.dumps({str(key): _clean_value(value) for key, value in row.items()}, ensure_ascii=False, default=str)


def normalizar_duracao_minutos(value: Any) -> float:
    if value in [None, ""]:
        return 0.0
    text = str(value).strip()
    match = re.match(r"^(\d{1,3}):(\d{2})(?::(\d{2}))?$", text)
    if match:
        hours, minutes, seconds = match.groups()
        return round(int(hours) * 60 + int(minutes) + int(seconds or 0) / 60, 2)
    return normalizar_valor_monetario(value)


def column_map(df: pd.DataFrame, aliases: dict[str, list[str]]) -> dict[str, str]:
    return {field: identificar_coluna_flexivel(df.columns, candidates) for field, candidates in aliases.items()}


def _alias_score(columns: list[Any], aliases: dict[str, list[str]]) -> int:
    probe = pd.DataFrame(columns=[str(column or "") for column in columns])
    mapped = column_map(probe, aliases)
    return sum(1 for value in mapped.values() if value)


def _unique_columns(columns: list[Any]) -> list[str]:
    seen: dict[str, int] = {}
    result: list[str] = []
    for column in columns:
        name = str(_clean_value(column) or "").strip() or "coluna"
        seen[name] = seen.get(name, 0) + 1
        result.append(name if seen[name] == 1 else f"{name}_{seen[name]}")
    return result


def promote_header_row(df: pd.DataFrame, aliases: dict[str, list[str]], min_score: int = 3) -> tuple[pd.DataFrame, int]:
    if df.empty:
        return df, -1
    current_score = _alias_score(list(df.columns), aliases)
    best_index = -1
    best_score = current_score
    scan_limit = min(len(df), 12)
    for index in range(scan_limit):
        values = list(df.iloc[index].fillna("").astype(str))
        score = _alias_score(values, aliases)
        if score > best_score:
            best_score = score
            best_index = index
    if best_index < 0 or best_score < min_score:
        return df, -1
    promoted = df.iloc[best_index + 1 :].copy()
    promoted.columns = _unique_columns(list(df.iloc[best_index]))
    return promoted.dropna(how="all").reset_index(drop=True), best_index


def _document_number(value: Any) -> str:
    if value in [None, ""]:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = re.sub(r"\.0$", "", str(value).strip())
    digits = re.sub(r"\D", "", text)
    return digits.lstrip("0") or digits or text


def _document_list(value: Any) -> list[str]:
    if value in [None, ""]:
        return []
    try:
        if pd.isna(value):
            return []
    except Exception:
        pass
    text = str(int(value)) if isinstance(value, float) and value.is_integer() else str(value)
    pieces = re.split(r"[\s,;/|\\-]+", text.replace("\n", " "))
    docs: set[str] = set()
    for piece in pieces:
        doc = _document_number(piece)
        if doc:
            docs.add(doc)
    return sorted(docs, key=lambda item: (len(item), item))


def _document_list_text(value: Any) -> str:
    return "/".join(_document_list(value))


def _compact_location(value: Any, uf: Any = "") -> str:
    location = normalizar_texto(value)
    state = normalizar_texto(uf)
    if state and state not in location.split():
        location = f"{location}-{state}"
    return re.sub(r"[^A-Z0-9]+", "-", location).strip("-")


def _extract_uf(value: Any) -> str:
    text = normalizar_texto(value)
    match = re.search(r"(?:^|[^A-Z])([A-Z]{2})(?:$|[^A-Z])", text)
    return match.group(1) if match else ""


def _make_trip_key(row: dict[str, Any], sequence: int = 0) -> str:
    date_key = str(row.get("data_operacao") or "").replace("-", "")
    origem = _compact_location(row.get("origem"), row.get("uf_origem"))
    destino = _compact_location(row.get("destino"), row.get("uf_destino"))
    doc = row.get("cte") or row.get("nf") or row.get("pedido") or row.get("romaneio") or row.get("numero_viagem")
    parts = [row.get("placa_norm") or "SEMPLACA", date_key or "SEMDATA", origem or "SEMORIGEM", destino or "SEMDESTINO"]
    parts.append(f"CTE{doc}" if doc else f"SEQ{sequence:03d}")
    return "|".join(map(str, parts))


def validate_lcte_layout(columns: dict[str, str]) -> list[str]:
    missing = [label for field, label in LCTE_REQUIRED_FIELDS.items() if not columns.get(field)]
    return missing


def lcte_inconsistencies(normalized_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in normalized_rows:
        linha = row.get("numero_linha")
        validations = [
            ("placa", "Placa ausente ou invalida", row.get("placa")),
            ("data_operacao", "Data da carga ausente ou invalida", row.get("data_carga") or row.get("data_hora_carga")),
            ("origem_norm", "Origem ausente", row.get("origem")),
            ("destino_norm", "Destino ausente", row.get("destino")),
        ]
        for field, message, value in validations:
            if not row.get(field):
                rows.append({"linha": linha, "campo": field, "valor": value or "", "mensagem": message})
        if not row.get("cte") and not row.get("nf"):
            rows.append({"linha": linha, "campo": "cte_nf", "valor": "", "mensagem": "CT-e e NF ausentes; associacao com multiplas viagens fica fragil."})
    return rows


def import_stats(rows: list[dict[str, Any]], date_column: str) -> dict[str, Any]:
    dates = [str(row.get(date_column) or "") for row in rows if str(row.get(date_column) or "")]
    return {
        "placas_validas": sum(1 for row in rows if row.get("placa_norm")),
        "datas_validas": len(dates),
        "registros_com_erro": sum(1 for row in rows if not row.get("placa_norm") or not row.get(date_column)),
        "periodo_inicial": min(dates) if dates else "",
        "periodo_final": max(dates) if dates else "",
    }


def _empty_import_stats() -> dict[str, Any]:
    return {
        "placas_validas": 0,
        "datas_validas": 0,
        "registros_com_erro": 0,
        "periodo_inicial": "",
        "periodo_final": "",
    }


def _update_import_stats(stats: dict[str, Any], row: dict[str, Any], date_column: str) -> None:
    if row.get("placa_norm"):
        stats["placas_validas"] += 1
    date_value = str(row.get(date_column) or "")
    if date_value:
        stats["datas_validas"] += 1
        if not stats["periodo_inicial"] or date_value < stats["periodo_inicial"]:
            stats["periodo_inicial"] = date_value
        if not stats["periodo_final"] or date_value > stats["periodo_final"]:
            stats["periodo_final"] = date_value
    if not row.get("placa_norm") or not row.get(date_column):
        stats["registros_com_erro"] += 1


def _base_original_row(
    row: dict[str, Any],
    lote: str,
    file_name: str,
    usuario: str,
    imported_at: str,
    file_hash: str,
    index: int,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "lote_importacao": lote,
        "arquivo_origem": file_name,
        "usuario_importacao": usuario,
        "data_hora_importacao": imported_at,
        "hash_arquivo": file_hash,
        "numero_linha": index + 2,
        "dados_json": row_json(row),
        "created_at": imported_at,
        "updated_at": imported_at,
    }
    if extra:
        payload.update(extra)
    return payload


def normalize_control_row(row: dict[str, Any], columns: dict[str, str], base: dict[str, Any]) -> dict[str, Any]:
    data_hora_inicio_carga = row_value(row, columns.get("data_hora_inicio_carga", ""))
    data_hora_fim_carga = row_value(row, columns.get("data_hora_fim_carga", ""))
    data_hora_inicio_descarga = row_value(row, columns.get("data_hora_inicio_descarga", ""))
    data_hora_fim_descarga = row_value(row, columns.get("data_hora_fim_descarga", ""))
    data_hora_inicio_raw = row_value(row, columns.get("data_hora_inicio", "")) or data_hora_inicio_carga
    data_hora_fim_raw = row_value(row, columns.get("data_hora_fim", "")) or data_hora_fim_descarga or data_hora_fim_carga
    data_inicio = row_value(row, columns.get("data_inicio", ""))
    hora_inicio = row_value(row, columns.get("hora_inicio", ""))
    data_fim = row_value(row, columns.get("data_fim", ""))
    hora_fim = row_value(row, columns.get("hora_fim", ""))
    placa = row_value(row, columns.get("placa", ""))
    tempo_carga = row_value(row, columns.get("tempo_carga", ""))
    tempo_descarga = row_value(row, columns.get("tempo_descarga", ""))
    romaneio = str(row_value(row, columns.get("romaneio", "")) or "")
    operacao = normalizar_texto(row_value(row, columns.get("operacao", "")))
    mercadoria = normalizar_texto(row_value(row, columns.get("mercadoria", "")))
    remetente = normalizar_texto(row_value(row, columns.get("remetente", "")))
    destinatario = normalizar_texto(row_value(row, columns.get("destinatario", "")))
    observation_parts = [
        f"Remetente: {remetente}" if remetente else "",
        f"Destinatario: {destinatario}" if destinatario else "",
        f"Operacao: {operacao}" if operacao else "",
        f"Mercadoria: {mercadoria}" if mercadoria else "",
        f"Inicio carga: {normalizar_data_hora('', '', data_hora_inicio_carga)}" if data_hora_inicio_carga not in [None, ""] else "",
        f"Fim carga: {normalizar_data_hora('', '', data_hora_fim_carga)}" if data_hora_fim_carga not in [None, ""] else "",
        f"Inicio descarga: {normalizar_data_hora('', '', data_hora_inicio_descarga)}" if data_hora_inicio_descarga not in [None, ""] else "",
        f"Fim descarga: {normalizar_data_hora('', '', data_hora_fim_descarga)}" if data_hora_fim_descarga not in [None, ""] else "",
        f"Tempo carga: {tempo_carga}" if tempo_carga not in [None, ""] else "",
        f"Tempo descarga: {tempo_descarga}" if tempo_descarga not in [None, ""] else "",
    ]
    source_observation = str(row_value(row, columns.get("observacao", "")) or "")
    observation = " | ".join(part for part in [source_observation, *observation_parts] if part)
    total_time = normalizar_duracao_minutos(row_value(row, columns.get("tempo_total", "")))
    if not total_time:
        total_time = normalizar_duracao_minutos(tempo_carga) + normalizar_duracao_minutos(tempo_descarga)
    payload = {
        **base,
        "placa": "" if placa in [None, ""] else str(placa),
        "placa_norm": normalizar_placa(placa),
        "motorista": normalizar_texto(row_value(row, columns.get("motorista", ""))),
        "cliente": normalizar_texto(row_value(row, columns.get("cliente", ""))) or operacao or destinatario,
        "razao_social": normalizar_texto(row_value(row, columns.get("razao_social", ""))) or remetente or destinatario,
        "local_origem": normalizar_texto(row_value(row, columns.get("local_origem", ""))),
        "local_destino": normalizar_texto(row_value(row, columns.get("local_destino", ""))),
        "local_evento": normalizar_texto(row_value(row, columns.get("local_evento", ""))),
        "data_inicio": normalizar_data(data_inicio),
        "hora_inicio": normalizar_hora(hora_inicio),
        "data_fim": normalizar_data(data_fim),
        "hora_fim": normalizar_hora(hora_fim),
        "data_hora_inicio": normalizar_data_hora(data_inicio, hora_inicio, data_hora_inicio_raw),
        "data_hora_fim": normalizar_data_hora(data_fim, hora_fim, data_hora_fim_raw),
        "tipo_evento": normalizar_texto(row_value(row, columns.get("tipo_evento", ""))) or "CARGA/DESCARGA",
        "status": normalizar_texto(row_value(row, columns.get("status", ""))),
        "observacao": observation,
        "valor_estadia": normalizar_valor_monetario(row_value(row, columns.get("valor_estadia", ""))),
        "tempo_total": total_time,
        "numero_documento": str(row_value(row, columns.get("numero_documento", "")) or romaneio),
        "cte": str(row_value(row, columns.get("cte", "")) or ""),
        "nf": _document_list_text(row_value(row, columns.get("nf", ""))),
        "pedido": str(row_value(row, columns.get("pedido", "")) or ""),
        "viagem": str(row_value(row, columns.get("viagem", "")) or romaneio),
    }
    return payload


def normalize_lcte_row(row: dict[str, Any], columns: dict[str, str], base: dict[str, Any], sequence: int = 0) -> dict[str, Any]:
    data_hora_carga_raw = row_value(row, columns.get("data_hora_carga", ""))
    data_carga = row_value(row, columns.get("data_carga", ""))
    hora_carga = row_value(row, columns.get("hora_carga", ""))
    data_emissao = row_value(row, columns.get("data_emissao", ""))
    data_hora_carga_ref = data_hora_carga_raw or (data_carga if not hora_carga else "")
    data_hora_carga = normalizar_data_hora(data_carga, hora_carga, data_hora_carga_ref)
    data_hora_emissao = normalizar_data_hora(data_emissao, "", data_emissao)
    placa = row_value(row, columns.get("placa", ""))
    cliente = row_value(row, columns.get("cliente", ""))
    origem = row_value(row, columns.get("origem", ""))
    destino = row_value(row, columns.get("destino", ""))
    uf_origem = normalizar_texto(row_value(row, columns.get("uf_origem", ""))) or _extract_uf(origem)
    uf_destino = normalizar_texto(row_value(row, columns.get("uf_destino", ""))) or _extract_uf(destino)
    payload = {
        **base,
        "cte": _document_number(row_value(row, columns.get("cte", ""))),
        "nf": _document_list_text(row_value(row, columns.get("nf", ""))),
        "chave_nf": _document_number(row_value(row, columns.get("chave_nf", ""))),
        "placa": "" if placa in [None, ""] else str(placa),
        "placa_norm": normalizar_placa(placa),
        "placas_composicao": normalizar_texto(row_value(row, columns.get("placas_composicao", ""))),
        "motorista": normalizar_texto(row_value(row, columns.get("motorista", ""))),
        "cliente": normalizar_texto(cliente),
        "cliente_norm": normalizar_texto(cliente),
        "razao_social_cobranca": normalizar_texto(row_value(row, columns.get("razao_social_cobranca", ""))),
        "remetente": normalizar_texto(row_value(row, columns.get("remetente", ""))),
        "destinatario": normalizar_texto(row_value(row, columns.get("destinatario", ""))),
        "data_emissao": data_hora_emissao or normalizar_data(data_emissao),
        "data_carga": normalizar_data(data_carga) or data_hora_carga[:10],
        "hora_carga": normalizar_hora(hora_carga) or (data_hora_carga[11:19] if data_hora_carga else ""),
        "data_hora_carga": data_hora_carga,
        "data_operacao": (normalizar_data(data_carga) or data_hora_carga[:10]),
        "origem": normalizar_texto(origem),
        "origem_norm": normalizar_texto(origem),
        "uf_origem": uf_origem,
        "destino": normalizar_texto(destino),
        "destino_norm": normalizar_texto(destino),
        "uf_destino": uf_destino,
        "volume": normalizar_valor_monetario(row_value(row, columns.get("volume", ""))),
        "produto": normalizar_texto(row_value(row, columns.get("produto", ""))),
        "tabela_frete": normalizar_texto(row_value(row, columns.get("tabela_frete", ""))),
        "pedido": _document_number(row_value(row, columns.get("pedido", ""))),
        "romaneio": _document_number(row_value(row, columns.get("romaneio", ""))),
        "numero_viagem": _document_number(row_value(row, columns.get("numero_viagem", ""))),
        "km_rota": normalizar_valor_monetario(row_value(row, columns.get("km_rota", ""))),
        "valor_frete": normalizar_valor_monetario(row_value(row, columns.get("valor_frete", ""))),
        "latitude_origem": normalizar_valor_monetario(row_value(row, columns.get("latitude_origem", ""))),
        "longitude_origem": normalizar_valor_monetario(row_value(row, columns.get("longitude_origem", ""))),
        "latitude_destino": normalizar_valor_monetario(row_value(row, columns.get("latitude_destino", ""))),
        "longitude_destino": normalizar_valor_monetario(row_value(row, columns.get("longitude_destino", ""))),
        "observacao": str(row_value(row, columns.get("observacao", "")) or ""),
    }
    payload["chave_viagem"] = _make_trip_key(payload, sequence)
    return payload


def normalize_rastreador_row(row: dict[str, Any], columns: dict[str, str], base: dict[str, Any], placa_arquivo: str) -> dict[str, Any]:
    placa = row_value(row, columns.get("placa", "")) or placa_arquivo
    data_value = row_value(row, columns.get("data", ""))
    hora_value = row_value(row, columns.get("hora", ""))
    data_hora_value = row_value(row, columns.get("data_hora", ""))
    return {
        **base,
        "placa": str(placa or ""),
        "placa_norm": normalizar_placa(placa),
        "data": normalizar_data(data_value),
        "hora": normalizar_hora(hora_value),
        "data_hora": normalizar_data_hora(data_value, hora_value, data_hora_value),
        "latitude": normalizar_valor_monetario(row_value(row, columns.get("latitude", ""))),
        "longitude": normalizar_valor_monetario(row_value(row, columns.get("longitude", ""))),
        "endereco": str(row_value(row, columns.get("endereco", "")) or ""),
        "cidade": normalizar_texto(row_value(row, columns.get("cidade", ""))),
        "uf": normalizar_texto(row_value(row, columns.get("uf", ""))),
        "velocidade": normalizar_valor_monetario(row_value(row, columns.get("velocidade", ""))),
        "ignicao": normalizar_texto(row_value(row, columns.get("ignicao", ""))),
        "evento": normalizar_texto(row_value(row, columns.get("evento", ""))),
        "status": normalizar_texto(row_value(row, columns.get("status", ""))),
        "odometro": normalizar_valor_monetario(row_value(row, columns.get("odometro", ""))),
        "motorista": normalizar_texto(row_value(row, columns.get("motorista", ""))),
    }


def import_control(file: BinaryIO, usuario: str, duplicate_mode: str = "bloquear") -> dict[str, Any]:
    file_name = getattr(file, "name", "control.xlsx")
    content = _file_bytes(file)
    file_hash = hash_file_bytes(content)
    if hash_already_imported(file_hash, "CONTROL"):
        if duplicate_mode == "bloquear":
            return {"status": "DUPLICADO", "arquivo": file_name, "mensagem": "Este arquivo já foi importado anteriormente.", "linhas": 0}
        if duplicate_mode == "substituir":
            delete_by_hash(file_hash, "CONTROL")
    lote = make_lote("CONTROL")
    imported_at = brasilia_now_iso()
    try:
        df, sheet_name = read_tabular_file(file_name, content)
        df, promoted_header_row = promote_header_row(df, CONTROL_ALIASES)
        columns = column_map(df, CONTROL_ALIASES)
        original_rows = []
        normalized_rows = []
        for index, raw in enumerate(df.to_dict(orient="records")):
            base = _base_original_row(raw, lote, file_name, usuario, imported_at, file_hash, index)
            original_rows.append(base)
            normalized_rows.append(normalize_control_row(raw, columns, base))
        stats = import_stats(normalized_rows, "data_hora_inicio")
        inserted = insert_rows(CONTROL_ORIGINAL_TABLE, original_rows)
        insert_rows(CONTROL_NORMALIZED_TABLE, normalized_rows)
        registrar_log_importacao(
            usuario=usuario,
            tipo_importacao="CONTROL",
            arquivo_origem=file_name,
            hash_arquivo=file_hash,
            lote_importacao=lote,
            quantidade_linhas=len(df),
            quantidade_registros_inseridos=inserted,
            quantidade_registros_ignorados=stats["registros_com_erro"],
            status="SUCESSO",
            mensagem="Arquivo CONTROL importado.",
            detalhes={"aba": sheet_name, "linha_cabecalho_promovida": promoted_header_row, "colunas_encontradas": columns, "colunas_arquivo": list(map(str, df.columns)), **stats},
        )
        return {
            "status": "SUCESSO",
            "arquivo": file_name,
            "lote": lote,
            "linhas": len(df),
            **stats,
            "linha_cabecalho_promovida": promoted_header_row,
            "colunas_encontradas": columns,
            "amostra": df.head(20),
        }
    except Exception as exc:
        registrar_log_importacao(
            usuario=usuario,
            tipo_importacao="CONTROL",
            arquivo_origem=file_name,
            hash_arquivo=file_hash,
            lote_importacao=lote,
            status="ERRO",
            mensagem=str(exc),
        )
        return {"status": "ERRO", "arquivo": file_name, "mensagem": str(exc), "linhas": 0}


def import_lcte_ipiranga(file: BinaryIO, usuario: str, duplicate_mode: str = "bloquear") -> dict[str, Any]:
    file_name = getattr(file, "name", "lcte_ipiranga.xlsx")
    content = _file_bytes(file)
    file_hash = hash_file_bytes(content)
    if hash_already_imported(file_hash, "LCTE_IPIRANGA"):
        if duplicate_mode == "bloquear":
            return {"status": "DUPLICADO", "arquivo": file_name, "mensagem": "Este arquivo ja foi importado anteriormente.", "linhas": 0}
        if duplicate_mode == "substituir":
            delete_by_hash(file_hash, "LCTE_IPIRANGA")
    lote = make_lote("LCTE")
    imported_at = brasilia_now_iso()
    try:
        df, sheet_name = read_tabular_file(file_name, content)
        df, promoted_header_row = promote_header_row(df, LCTE_ALIASES)
        columns = column_map(df, LCTE_ALIASES)
        missing_layout = validate_lcte_layout(columns)
        if missing_layout:
            message = "Layout LCTE invalido. Colunas obrigatorias nao encontradas: " + ", ".join(missing_layout)
            registrar_log_importacao(
                usuario=usuario,
                tipo_importacao="LCTE_IPIRANGA",
                arquivo_origem=file_name,
                hash_arquivo=file_hash,
                lote_importacao=lote,
                quantidade_linhas=len(df),
                status="ERRO",
                mensagem=message,
                detalhes={"aba": sheet_name, "linha_cabecalho_promovida": promoted_header_row, "colunas_encontradas": columns, "colunas_arquivo": list(map(str, df.columns))},
            )
            return {"status": "ERRO", "arquivo": file_name, "mensagem": message, "linhas": 0, "colunas_encontradas": columns}

        original_rows = []
        normalized_rows = []
        provisional_sequences: dict[str, int] = {}
        for index, raw in enumerate(df.to_dict(orient="records")):
            base = _base_original_row(raw, lote, file_name, usuario, imported_at, file_hash, index)
            original_rows.append(base)
            draft = normalize_lcte_row(raw, columns, base, 0)
            provisional_base = "|".join(
                [
                    str(draft.get("placa_norm") or ""),
                    str(draft.get("data_operacao") or ""),
                    str(draft.get("origem_norm") or ""),
                    str(draft.get("destino_norm") or ""),
                ]
            )
            has_doc = any(draft.get(field) for field in ["cte", "nf", "pedido", "romaneio", "numero_viagem"])
            sequence = 0
            if not has_doc:
                provisional_sequences[provisional_base] = provisional_sequences.get(provisional_base, 0) + 1
                sequence = provisional_sequences[provisional_base]
                draft["chave_viagem"] = _make_trip_key(draft, sequence)
            normalized_rows.append(draft)

        inconsistencies = lcte_inconsistencies(normalized_rows)
        stats = import_stats(normalized_rows, "data_operacao")
        inserted = insert_rows(LCTE_ORIGINAL_TABLE, original_rows)
        insert_rows(LCTE_NORMALIZED_TABLE, normalized_rows)
        registrar_log_importacao(
            usuario=usuario,
            tipo_importacao="LCTE_IPIRANGA",
            arquivo_origem=file_name,
            hash_arquivo=file_hash,
            lote_importacao=lote,
            quantidade_linhas=len(df),
            quantidade_registros_inseridos=inserted,
            quantidade_registros_ignorados=len(inconsistencies),
            status="SUCESSO",
            mensagem="Arquivo LCTE Ipiranga importado.",
            detalhes={
                "aba": sheet_name,
                "linha_cabecalho_promovida": promoted_header_row,
                "colunas_encontradas": columns,
                "colunas_arquivo": list(map(str, df.columns)),
                "viagens": len(normalized_rows),
                **stats,
                "origens_validas": sum(1 for row in normalized_rows if row.get("origem_norm")),
                "destinos_validos": sum(1 for row in normalized_rows if row.get("destino_norm")),
                "inconsistencias": inconsistencies[:200],
            },
        )
        return {
            "status": "SUCESSO",
            "arquivo": file_name,
            "lote": lote,
            "linhas": len(df),
            "viagens": len(normalized_rows),
            **stats,
            "origens_validas": sum(1 for row in normalized_rows if row.get("origem_norm")),
            "destinos_validos": sum(1 for row in normalized_rows if row.get("destino_norm")),
            "inconsistencias": pd.DataFrame(inconsistencies),
            "linha_cabecalho_promovida": promoted_header_row,
            "colunas_encontradas": columns,
            "amostra": df.head(20),
        }
    except Exception as exc:
        registrar_log_importacao(
            usuario=usuario,
            tipo_importacao="LCTE_IPIRANGA",
            arquivo_origem=file_name,
            hash_arquivo=file_hash,
            lote_importacao=lote,
            status="ERRO",
            mensagem=str(exc),
        )
        return {"status": "ERRO", "arquivo": file_name, "mensagem": str(exc), "linhas": 0}


def import_rastreador_files(
    files: list[BinaryIO],
    usuario: str,
    duplicate_mode: str = "bloquear",
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> dict[str, Any]:
    lote = make_lote("RASTREADOR")
    rows = []
    total_lines = 0
    success = errors = duplicates = 0
    total = len(files)
    for index_file, file in enumerate(files, start=1):
        file_name = getattr(file, "name", f"rastreador_{index_file}.xlsx")
        if progress_callback:
            progress_callback(index_file, total, file_name)
        content = _file_bytes(file)
        file_hash = hash_file_bytes(content)
        placa_arquivo = extrair_placa_do_nome_arquivo(file_name)
        if hash_already_imported(file_hash, "RASTREADOR_PLACA"):
            if duplicate_mode == "bloquear":
                duplicates += 1
                rows.append({"arquivo": file_name, "placa_identificada": placa_arquivo, "linhas": 0, "status": "DUPLICADO", "mensagem": "Este arquivo já foi importado anteriormente."})
                continue
            if duplicate_mode == "substituir":
                delete_by_hash(file_hash, "RASTREADOR_PLACA")
        imported_at = brasilia_now_iso()
        try:
            df, sheet_name = read_tabular_file(file_name, content)
            df, promoted_header_row = promote_header_row(df, RASTREADOR_ALIASES)
            columns = column_map(df, RASTREADOR_ALIASES)
            file_lines = len(df)
            stats = _empty_import_stats()
            inserted = 0
            original_rows: list[dict[str, Any]] = []
            normalized_rows: list[dict[str, Any]] = []

            def flush_chunks() -> None:
                nonlocal inserted
                if original_rows:
                    inserted += insert_rows(RASTREADOR_ORIGINAL_TABLE, original_rows, RASTREADOR_INSERT_CHUNK_SIZE)
                    original_rows.clear()
                if normalized_rows:
                    insert_rows(RASTREADOR_NORMALIZED_TABLE, normalized_rows, RASTREADOR_INSERT_CHUNK_SIZE)
                    normalized_rows.clear()

            df_columns = list(df.columns)
            for row_index, values in enumerate(df.itertuples(index=False, name=None)):
                raw = dict(zip(df_columns, values))
                original_base = _base_original_row(
                    raw,
                    lote,
                    file_name,
                    usuario,
                    imported_at,
                    file_hash,
                    row_index,
                    {"placa_arquivo": placa_arquivo},
                )
                normalized_base = _base_original_row(raw, lote, file_name, usuario, imported_at, file_hash, row_index)
                original_rows.append(original_base)
                normalized_row = normalize_rastreador_row(raw, columns, normalized_base, placa_arquivo)
                normalized_rows.append(normalized_row)
                _update_import_stats(stats, normalized_row, "data_hora")
                if len(original_rows) >= RASTREADOR_INSERT_CHUNK_SIZE:
                    flush_chunks()
            flush_chunks()
            registrar_log_importacao(
                usuario=usuario,
                tipo_importacao="RASTREADOR_PLACA",
                arquivo_origem=file_name,
                hash_arquivo=file_hash,
                lote_importacao=lote,
                quantidade_linhas=file_lines,
                quantidade_registros_inseridos=inserted,
                quantidade_registros_ignorados=stats["registros_com_erro"],
                status="SUCESSO",
                mensagem="Relatório rastreador importado.",
                detalhes={"aba": sheet_name, "linha_cabecalho_promovida": promoted_header_row, "placa_arquivo": placa_arquivo, "colunas_encontradas": columns, "colunas_arquivo": list(map(str, df.columns)), **stats},
            )
            success += 1
            total_lines += file_lines
            rows.append({"arquivo": file_name, "placa_identificada": placa_arquivo, "linhas": file_lines, "status": "SUCESSO", "mensagem": "Importado.", "linha_cabecalho_promovida": promoted_header_row, **stats})
            del df
            gc.collect()
        except Exception as exc:
            errors += 1
            try:
                delete_by_hash(file_hash, "RASTREADOR_PLACA")
            except Exception:
                pass
            registrar_log_importacao(
                usuario=usuario,
                tipo_importacao="RASTREADOR_PLACA",
                arquivo_origem=file_name,
                hash_arquivo=file_hash,
                lote_importacao=lote,
                status="ERRO",
                mensagem=str(exc),
                detalhes={"placa_arquivo": placa_arquivo},
            )
            rows.append({"arquivo": file_name, "placa_identificada": placa_arquivo, "linhas": 0, "status": "ERRO", "mensagem": str(exc)})
    return {
        "lote": lote,
        "arquivos_sucesso": success,
        "arquivos_erro": errors,
        "arquivos_duplicados": duplicates,
        "total_linhas": total_lines,
        "resultado": pd.DataFrame(rows),
    }
