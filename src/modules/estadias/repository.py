from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from src.database.connection import get_connection, read_sql
from src.modules.repository import latest_import_logs, table_count, table_exists
from src.utils.timezone import brasilia_now_iso


CONTROL_ORIGINAL_TABLE = "mod_estadias_control_original"
CONTROL_NORMALIZED_TABLE = "mod_estadias_control_normalizada"
LCTE_ORIGINAL_TABLE = "mod_estadias_lcte_original"
LCTE_NORMALIZED_TABLE = "mod_estadias_lcte_normalizada"
RASTREADOR_ORIGINAL_TABLE = "mod_estadias_rastreador_original"
RASTREADOR_NORMALIZED_TABLE = "mod_estadias_rastreador_normalizada"
LOG_TABLE = "mod_estadias_logs_importacao"
CROSS_TABLE = "mod_estadias_cruzamento_inicial"
CONFIG_TABLE = "mod_estadias_configuracoes"
LOCAIS_TABLE = "mod_estadias_locais_operacionais"
PARAMETROS_TABLE = "mod_estadias_parametros_cliente"
AUDITORIA_TABLE = "mod_estadias_auditoria"
CONCLUSOES_TABLE = "mod_estadias_conclusoes"
PREFERENCIAS_COLUNAS_TABLE = "mod_estadias_preferencias_colunas"
STATUS_LOG_TABLE = "mod_estadias_historico_status"


def counts() -> dict[str, int]:
    return {
        "Total de viagens LCTE": table_count(LCTE_NORMALIZED_TABLE),
        "Total de registros CONTROL": table_count(CONTROL_NORMALIZED_TABLE),
        "Total de registros Rastreador": table_count(RASTREADOR_NORMALIZED_TABLE),
        "Total de arquivos rastreador importados": distinct_count(RASTREADOR_NORMALIZED_TABLE, "arquivo_origem"),
        "Total de placas LCTE": distinct_count(LCTE_NORMALIZED_TABLE, "placa_norm"),
        "Total de placas rastreador": distinct_count(RASTREADOR_NORMALIZED_TABLE, "placa_norm"),
        "Registros sem placa": table_count_where(LCTE_NORMALIZED_TABLE, "coalesce(placa_norm, '') = ''")
        + table_count_where(CONTROL_NORMALIZED_TABLE, "coalesce(placa_norm, '') = ''")
        + table_count_where(RASTREADOR_NORMALIZED_TABLE, "coalesce(placa_norm, '') = ''"),
        "Registros com erro de data/hora": table_count_where(LCTE_NORMALIZED_TABLE, "coalesce(data_operacao, '') = ''")
        + table_count_where(CONTROL_NORMALIZED_TABLE, "coalesce(data_hora_inicio, '') = ''")
        + table_count_where(RASTREADOR_NORMALIZED_TABLE, "coalesce(data_hora, '') = ''"),
    }


def distinct_count(table: str, column: str) -> int:
    if not table_exists(table):
        return 0
    with get_connection() as conn:
        row = conn.execute(f"select count(distinct {column}) from {table} where coalesce({column}, '') <> ''").fetchone()
    return int(row[0] or 0) if row else 0


def table_count_where(table: str, where_sql: str) -> int:
    if not table_exists(table):
        return 0
    with get_connection() as conn:
        row = conn.execute(f"select count(*) from {table} where {where_sql}").fetchone()
    return int(row[0] or 0) if row else 0


def latest_logs(limit: int = 30) -> pd.DataFrame:
    return latest_import_logs(LOG_TABLE, limit)


def hash_already_imported(hash_arquivo: str, tipo_importacao: str) -> bool:
    if not hash_arquivo or not table_exists(LOG_TABLE):
        return False
    with get_connection() as conn:
        row = conn.execute(
            """
            select 1
            from mod_estadias_logs_importacao
            where hash_arquivo = ? and tipo_importacao = ? and upper(coalesce(status, '')) = 'SUCESSO'
            limit 1
            """,
            (hash_arquivo, tipo_importacao),
        ).fetchone()
    return bool(row)


def delete_by_hash(hash_arquivo: str, tipo_importacao: str) -> None:
    if not hash_arquivo:
        return
    if tipo_importacao == "CONTROL":
        tables = (CONTROL_ORIGINAL_TABLE, CONTROL_NORMALIZED_TABLE)
    elif tipo_importacao == "LCTE_IPIRANGA":
        tables = (LCTE_ORIGINAL_TABLE, LCTE_NORMALIZED_TABLE)
    else:
        tables = (RASTREADOR_ORIGINAL_TABLE, RASTREADOR_NORMALIZED_TABLE)
    with get_connection() as conn:
        for table in tables:
            conn.execute(f"delete from {table} where hash_arquivo = ?", (hash_arquivo,))


def clear_lcte_base() -> dict[str, int]:
    tables = [
        LCTE_ORIGINAL_TABLE,
        LCTE_NORMALIZED_TABLE,
        CROSS_TABLE,
        CONCLUSOES_TABLE,
        STATUS_LOG_TABLE,
    ]
    deleted: dict[str, int] = {}
    with get_connection() as conn:
        db_type = getattr(conn, "db_type", "sqlite")
        def exists(table: str) -> bool:
            if db_type == "postgres":
                row = conn.execute(
                    """
                    select 1
                    from information_schema.tables
                    where table_schema = 'public' and table_name = ?
                    """,
                    (table,),
                ).fetchone()
            else:
                row = conn.execute("select 1 from sqlite_master where type = 'table' and name = ?", (table,)).fetchone()
            return bool(row)

        for table in tables:
            if not exists(table):
                deleted[table] = 0
                continue
            before = conn.execute(f"select count(*) from {table}").fetchone()
            deleted[table] = int(before[0] or 0) if before else 0
            conn.execute(f"delete from {table}")
            if db_type != "postgres":
                conn.execute("delete from sqlite_sequence where name = ?", (table,))
        if exists(LOG_TABLE):
            before = conn.execute(
                """
                select count(*)
                from mod_estadias_logs_importacao
                where tipo_importacao = 'LCTE_IPIRANGA'
                """
            ).fetchone()
            deleted[f"{LOG_TABLE}:LCTE_IPIRANGA"] = int(before[0] or 0) if before else 0
            conn.execute("delete from mod_estadias_logs_importacao where tipo_importacao = 'LCTE_IPIRANGA'")
    return deleted


def clear_estadias_imported_database() -> dict[str, int]:
    tables = [
        LCTE_ORIGINAL_TABLE,
        LCTE_NORMALIZED_TABLE,
        CONTROL_ORIGINAL_TABLE,
        CONTROL_NORMALIZED_TABLE,
        RASTREADOR_ORIGINAL_TABLE,
        RASTREADOR_NORMALIZED_TABLE,
        LOG_TABLE,
        CROSS_TABLE,
        AUDITORIA_TABLE,
        CONCLUSOES_TABLE,
        STATUS_LOG_TABLE,
    ]
    deleted: dict[str, int] = {}
    with get_connection() as conn:
        db_type = getattr(conn, "db_type", "sqlite")

        def exists(table: str) -> bool:
            if db_type == "postgres":
                row = conn.execute(
                    """
                    select 1
                    from information_schema.tables
                    where table_schema = 'public' and table_name = ?
                    """,
                    (table,),
                ).fetchone()
            else:
                row = conn.execute("select 1 from sqlite_master where type = 'table' and name = ?", (table,)).fetchone()
            return bool(row)

        for table in tables:
            if not exists(table):
                deleted[table] = 0
                continue
            before = conn.execute(f"select count(*) from {table}").fetchone()
            deleted[table] = int(before[0] or 0) if before else 0
            conn.execute(f"delete from {table}")
            if db_type != "postgres":
                conn.execute("delete from sqlite_sequence where name = ?", (table,))
    return deleted


def insert_rows(table: str, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    columns = list(rows[0].keys())
    placeholders = ", ".join("?" for _ in columns)
    sql = f"insert into {table} ({', '.join(columns)}) values ({placeholders})"
    values = [tuple(row.get(column) for column in columns) for row in rows]
    with get_connection() as conn:
        conn.executemany(sql, values)
    return len(rows)


def select_distinct(table: str, column: str, limit: int = 500) -> list[str]:
    if not table_exists(table):
        return []
    df = read_sql(
        f"""
        select distinct {column} as value
        from {table}
        where coalesce({column}, '') <> ''
        order by {column}
        limit ?
        """,
        (limit,),
    )
    return df["value"].fillna("").astype(str).tolist() if not df.empty else []


def read_filtered(table: str, filters: dict[str, Any] | None = None, limit: int = 1000) -> pd.DataFrame:
    if not table_exists(table):
        return pd.DataFrame()
    filters = filters or {}
    where = []
    params: list[Any] = []
    for column, value in filters.items():
        if value in [None, "", [], ()]:
            continue
        if isinstance(value, (list, tuple, set)):
            values = [str(item) for item in value if str(item or "").strip()]
            if not values:
                continue
            where.append(f"{column} in ({', '.join('?' for _ in values)})")
            params.extend(values)
        else:
            where.append(f"{column} like ?")
            params.append(f"%{value}%")
    where_sql = f"where {' and '.join(where)}" if where else ""
    return read_sql(f"select * from {table} {where_sql} order by id desc limit ?", tuple(params + [limit]))


def read_control(filters: dict[str, Any] | None = None, limit: int = 1000) -> pd.DataFrame:
    return read_filtered(CONTROL_NORMALIZED_TABLE, filters, limit)


def read_lcte(filters: dict[str, Any] | None = None, limit: int = 1000) -> pd.DataFrame:
    return read_filtered(LCTE_NORMALIZED_TABLE, filters, limit)


def read_rastreador(filters: dict[str, Any] | None = None, limit: int = 1000) -> pd.DataFrame:
    return read_filtered(RASTREADOR_NORMALIZED_TABLE, filters, limit)


def sample(table: str, limit: int = 100) -> pd.DataFrame:
    return read_filtered(table, {}, limit)


def arquivos_rastreador_importados(limit: int = 500) -> pd.DataFrame:
    if not table_exists(RASTREADOR_NORMALIZED_TABLE):
        return pd.DataFrame()
    return read_sql(
        """
        select arquivo_origem, lote_importacao, hash_arquivo, max(data_hora_importacao) as ultima_importacao,
               count(*) as linhas, count(distinct placa_norm) as placas
        from mod_estadias_rastreador_normalizada
        group by arquivo_origem, lote_importacao, hash_arquivo
        order by ultima_importacao desc
        limit ?
        """,
        (limit,),
    )


def placas_disponiveis() -> pd.DataFrame:
    rows = []
    for origem, table in [("LCTE", LCTE_NORMALIZED_TABLE), ("CONTROL", CONTROL_NORMALIZED_TABLE), ("RASTREADOR", RASTREADOR_NORMALIZED_TABLE)]:
        for placa in select_distinct(table, "placa_norm", 2000):
            rows.append({"Origem": origem, "Placa": placa})
    return pd.DataFrame(rows)


def read_cross(limit: int = 1000) -> pd.DataFrame:
    return read_filtered(CROSS_TABLE, {}, limit)


def replace_cross(rows: list[dict[str, Any]], usuario: str) -> int:
    with get_connection() as conn:
        conn.execute(f"delete from {CROSS_TABLE}")
    now = brasilia_now_iso()
    payload = [row | {"atualizado_em": now, "atualizado_por": usuario} for row in rows]
    return insert_rows(CROSS_TABLE, payload)


def read_config() -> pd.DataFrame:
    return read_filtered(CONFIG_TABLE, {}, 100)


def read_locais(limit: int = 1000) -> pd.DataFrame:
    return read_filtered(LOCAIS_TABLE, {}, limit)


def read_parametros(limit: int = 1000) -> pd.DataFrame:
    return read_filtered(PARAMETROS_TABLE, {}, limit)


def read_auditoria(limit: int = 1000) -> pd.DataFrame:
    return read_filtered(AUDITORIA_TABLE, {}, limit)


def read_conclusoes(limit: int = 200000) -> pd.DataFrame:
    return read_filtered(CONCLUSOES_TABLE, {}, limit)


def read_conclusoes_map() -> dict[int, dict[str, Any]]:
    df = read_conclusoes(200000)
    if df.empty or "lcte_id" not in df:
        return {}
    df = df.sort_values("data_hora_conclusao")
    result: dict[int, dict[str, Any]] = {}
    for row in df.to_dict(orient="records"):
        try:
            result[int(row.get("lcte_id") or 0)] = row
        except Exception:
            continue
    return result


def save_conclusao(lcte_id: int, payload: dict[str, Any], usuario: str, painel_origem: str = "ESTADIAS") -> None:
    now = brasilia_now_iso()
    precisa_retorno = bool(payload.get("necessita_retorno"))
    retorno_recebido = bool(payload.get("retorno_recebido"))
    data_limite = ""
    status_prazo = "Nao necessita retorno"
    dias_restantes = 0
    if precisa_retorno:
        limite_dt = datetime.fromisoformat(now) + timedelta(days=15)
        data_limite = limite_dt.isoformat(sep=" ", timespec="seconds")
        dias_restantes = 15
        status_prazo = "Retorno recebido" if retorno_recebido else "Dentro do prazo"
    row = {
        "lcte_id": int(lcte_id or 0),
        "data_hora_conclusao": now,
        "usuario_responsavel": usuario,
        "painel_origem": painel_origem,
        "painel_destino": "CONCLUIDOS",
        "tipo_conclusao": str(payload.get("tipo_conclusao") or ""),
        "status_tratativa": str(payload.get("status_tratativa") or ""),
        "observacao": str(payload.get("observacao") or ""),
        "protocolo": str(payload.get("protocolo") or ""),
        "valor_solicitado": payload.get("valor_solicitado") or 0,
        "valor_aprovado": payload.get("valor_aprovado") or 0,
        "necessita_retorno": int(precisa_retorno),
        "retorno_recebido": int(retorno_recebido),
        "data_retorno": str(payload.get("data_retorno") or ""),
        "precisa_verificar": int(bool(payload.get("precisa_verificar"))),
        "motivo_verificacao": str(payload.get("motivo_verificacao") or ""),
        "status_retorno": str(payload.get("status_retorno") or ""),
        "created_at": now,
        "created_by": usuario,
    }
    insert_rows(CONCLUSOES_TABLE, [row])
    with get_connection() as conn:
        conn.execute(
            f"""
            update {CROSS_TABLE}
            set painel_atual = 'CONCLUIDOS',
                concluido = 1,
                tratado = 1,
                precisa_verificar = ?,
                tipo_conclusao = ?,
                observacao_conclusao = ?,
                usuario_conclusao = ?,
                data_hora_conclusao = ?,
                data_limite_retorno = ?,
                dias_restantes = ?,
                retorno_recebido = ?,
                data_retorno = ?,
                status_retorno = ?,
                status_prazo = ?,
                protocolo = ?,
                valor_solicitado = ?,
                valor_aprovado = ?,
                status_tratativa = ?,
                status_cte = ?
            where lcte_id = ?
            """,
            (
                int(bool(payload.get("precisa_verificar"))),
                str(payload.get("tipo_conclusao") or ""),
                str(payload.get("observacao") or ""),
                usuario,
                now,
                data_limite,
                dias_restantes,
                int(retorno_recebido),
                str(payload.get("data_retorno") or ""),
                str(payload.get("status_retorno") or ""),
                status_prazo,
                str(payload.get("protocolo") or ""),
                payload.get("valor_solicitado") or 0,
                payload.get("valor_aprovado") or 0,
                str(payload.get("status_tratativa") or ""),
                "Aguardando retorno" if precisa_retorno and not retorno_recebido else "Concluido",
                int(lcte_id or 0),
            ),
        )
    registrar_status_evento(
        lcte_id=lcte_id,
        usuario=usuario,
        acao="CONCLUIR_ESTADIA",
        painel_origem=painel_origem,
        painel_destino="CONCLUIDOS",
        valor_anterior_json="",
        valor_novo_json=str(payload),
        justificativa=str(payload.get("observacao") or ""),
    )


def registrar_status_evento(
    lcte_id: int,
    usuario: str,
    acao: str,
    painel_origem: str = "",
    painel_destino: str = "",
    valor_anterior_json: str = "",
    valor_novo_json: str = "",
    justificativa: str = "",
) -> None:
    insert_rows(
        STATUS_LOG_TABLE,
        [
            {
                "data_hora": brasilia_now_iso(),
                "lcte_id": int(lcte_id or 0),
                "usuario": usuario,
                "acao": acao,
                "painel_origem": painel_origem,
                "painel_destino": painel_destino,
                "valor_anterior_json": valor_anterior_json,
                "valor_novo_json": valor_novo_json,
                "justificativa": justificativa,
            }
        ],
    )


def reabrir_conclusao(lcte_id: int, usuario: str, painel_destino: str, justificativa: str = "") -> None:
    destino = str(painel_destino or "VERIFICACAO").upper()
    if destino not in {"VERIFICACAO", "ESTADIAS"}:
        destino = "VERIFICACAO"
    with get_connection() as conn:
        conn.execute(
            f"""
            update {CROSS_TABLE}
            set painel_atual = ?,
                concluido = 0,
                tratado = 0,
                precisa_verificar = ?,
                status_tratativa = 'REABERTO',
                status_retorno = '',
                status_cte = 'Reaberto',
                tipo_conclusao = '',
                observacao_conclusao = ?,
                data_hora_conclusao = '',
                data_limite_retorno = '',
                dias_restantes = 0,
                retorno_recebido = 0,
                data_retorno = '',
                status_prazo = ''
            where lcte_id = ?
            """,
            (destino, 1 if destino == "VERIFICACAO" else 0, justificativa, int(lcte_id or 0)),
        )
    registrar_status_evento(
        lcte_id=lcte_id,
        usuario=usuario,
        acao="REABRIR_ESTADIA",
        painel_origem="CONCLUIDOS",
        painel_destino=destino,
        valor_novo_json=f'{{"destino": "{destino}"}}',
        justificativa=justificativa,
    )


def read_preferencia_colunas(usuario: str, painel: str) -> list[str]:
    if not table_exists(PREFERENCIAS_COLUNAS_TABLE):
        return []
    df = read_sql(
        """
        select colunas_json
        from mod_estadias_preferencias_colunas
        where usuario = ? and painel = ?
        order by updated_at desc
        limit 1
        """,
        (usuario, painel),
    )
    if df.empty:
        return []
    import json

    try:
        value = json.loads(str(df.iloc[0]["colunas_json"] or "[]"))
        return [str(item) for item in value if str(item or "").strip()]
    except Exception:
        return []


def save_preferencia_colunas(usuario: str, painel: str, colunas: list[str]) -> None:
    import json

    now = brasilia_now_iso()
    with get_connection() as conn:
        conn.execute(
            """
            delete from mod_estadias_preferencias_colunas
            where usuario = ? and painel = ?
            """,
            (usuario, painel),
        )
    insert_rows(
        PREFERENCIAS_COLUNAS_TABLE,
        [
            {
                "usuario": usuario,
                "painel": painel,
                "colunas_json": json.dumps(colunas, ensure_ascii=False),
                "updated_at": now,
            }
        ],
    )


def save_config(df: pd.DataFrame, usuario: str) -> int:
    if df.empty:
        return 0
    now = brasilia_now_iso()
    saved = 0
    with get_connection() as conn:
        for row in df.to_dict(orient="records"):
            conn.execute(
                """
                update mod_estadias_configuracoes
                set valor = ?, descricao = ?, updated_at = ?, updated_by = ?
                where chave = ?
                """,
                (
                    str(row.get("valor") or ""),
                    str(row.get("descricao") or ""),
                    now,
                    usuario,
                    str(row.get("chave") or ""),
                ),
            )
            saved += 1
    return saved


def replace_editable_table(table: str, df: pd.DataFrame, usuario: str) -> int:
    if df.empty:
        return 0
    now = brasilia_now_iso()
    rows = []
    for row in df.to_dict(orient="records"):
        payload = {key: ("" if value is None else value) for key, value in row.items() if key != "id"}
        payload["updated_at"] = now
        payload["updated_by"] = usuario
        payload.setdefault("created_at", now)
        payload.setdefault("created_by", usuario)
        rows.append(payload)
    with get_connection() as conn:
        conn.execute(f"delete from {table}")
    return insert_rows(table, rows)


def save_locais(df: pd.DataFrame, usuario: str) -> int:
    return replace_editable_table(LOCAIS_TABLE, df, usuario)


def save_parametros(df: pd.DataFrame, usuario: str) -> int:
    return replace_editable_table(PARAMETROS_TABLE, df, usuario)


def registrar_auditoria(
    usuario: str,
    acao: str,
    chave_viagem: str = "",
    arquivo_origem: str = "",
    valor_anterior_json: str = "",
    valor_novo_json: str = "",
    observacao: str = "",
    detalhes_json: str = "",
) -> None:
    insert_rows(
        AUDITORIA_TABLE,
        [
            {
                "data_hora": brasilia_now_iso(),
                "usuario": usuario,
                "acao": acao,
                "chave_viagem": chave_viagem,
                "arquivo_origem": arquivo_origem,
                "valor_anterior_json": valor_anterior_json,
                "valor_novo_json": valor_novo_json,
                "observacao": observacao,
                "detalhes_json": detalhes_json,
            }
        ],
    )
