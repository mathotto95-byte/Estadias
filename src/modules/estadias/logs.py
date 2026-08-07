from __future__ import annotations

from src.database.connection import get_connection
from src.database.migrations import import_log_payload
from src.modules.repository import insert_system_log
from src.utils.timezone import brasilia_now_iso


def registrar_log_importacao(**kwargs) -> None:
    kwargs = dict(kwargs)
    kwargs["data_hora"] = kwargs.get("data_hora") or brasilia_now_iso()
    payload = import_log_payload(**kwargs)
    with get_connection() as conn:
        conn.execute(
            """
            insert into mod_estadias_logs_importacao (
                data_hora, usuario, tipo_importacao, arquivo_origem, hash_arquivo,
                quantidade_linhas, quantidade_registros_inseridos,
                quantidade_registros_atualizados, quantidade_registros_ignorados,
                status, mensagem, detalhes_json, lote_importacao
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            tuple(payload[column] for column in [
                "data_hora", "usuario", "tipo_importacao", "arquivo_origem", "hash_arquivo",
                "quantidade_linhas", "quantidade_registros_inseridos",
                "quantidade_registros_atualizados", "quantidade_registros_ignorados",
                "status", "mensagem", "detalhes_json", "lote_importacao",
            ]),
        )
    tipo = payload["tipo_importacao"]
    submodulo = {
        "LCTE_IPIRANGA": "IMPORTACAO_LCTE_IPIRANGA",
        "CONTROL": "IMPORTACAO_CONTROL",
        "RASTREADOR_PLACA": "IMPORTACAO_RASTREADOR",
    }.get(tipo, "IMPORTACAO")
    acao = {
        "LCTE_IPIRANGA": "IMPORTAR_LCTE_IPIRANGA",
        "CONTROL": "IMPORTAR_CONTROL",
        "RASTREADOR_PLACA": "IMPORTAR_RASTREADOR_PLACA",
    }.get(tipo, "IMPORTAR")
    insert_system_log(
        payload["usuario"],
        "ESTADIAS",
        submodulo,
        acao,
        payload["status"] or "INFO",
        payload["mensagem"],
        {"arquivo_origem": payload["arquivo_origem"], "lote_importacao": payload["lote_importacao"]},
    )
