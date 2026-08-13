from __future__ import annotations

import json
from typing import Any

from src.database.connection import get_connection
from src.database.schema import adapt_sql, create_base_table_sql, ensure_columns


IPIRANGA_IMPORT_TYPES = ("PORTAL_IPP", "PORTAL26", "KM_IPP")
FATURAMENTO_IMPORT_TYPES = ("COUPA", "NSDOCS", "LCTE")
ESTADIAS_IMPORT_TYPES = ("LCTE_IPIRANGA", "CONTROL", "RASTREADOR_PLACA")

MODULAR_BASE_TABLES = {
    "mod_ipiranga_portal_ipp_original": "Ipiranga Portal IPP original",
    "mod_ipiranga_portal_ipp_normalizada": "Ipiranga Portal IPP normalizada",
    "mod_ipiranga_portal26_original": "Ipiranga Portal26 original",
    "mod_ipiranga_portal26_normalizada": "Ipiranga Portal26 normalizada",
    "mod_ipiranga_km_ipp_original": "Ipiranga KM IPP original",
    "mod_ipiranga_km_ipp_normalizada": "Ipiranga KM IPP normalizada",
    "mod_faturamento_coupa_original": "Faturamento Coupa original",
    "mod_faturamento_coupa_normalizada": "Faturamento Coupa normalizada",
    "mod_faturamento_nsdocs_original": "Faturamento NSDOCS original",
    "mod_faturamento_nsdocs_normalizada": "Faturamento NSDOCS normalizada",
    "mod_faturamento_lcte_original": "Faturamento LCTE original",
    "mod_faturamento_lcte_normalizada": "Faturamento LCTE normalizada",
}

MODULAR_COPY_MAP = {
    "base_portal_ipp_original": "mod_ipiranga_portal_ipp_original",
    "base_portal_ipp_normalizada": "mod_ipiranga_portal_ipp_normalizada",
    "base_portal26_original": "mod_ipiranga_portal26_original",
    "base_fretes_ipp_original": "mod_ipiranga_km_ipp_original",
    "base_fretes_ipp_notas_normalizadas": "mod_ipiranga_km_ipp_normalizada",
    "base_coupa_original": "mod_faturamento_coupa_original",
    "base_coupa_fluxos_normalizados": "mod_faturamento_coupa_normalizada",
    "base_nsdocs_original": "mod_faturamento_nsdocs_original",
    "base_kmm_original": "mod_faturamento_lcte_original",
    "base_kmm_fat_notas_normalizadas": "mod_faturamento_lcte_notas_normalizadas",
}


def _json_default(value: Any) -> str:
    return str(value)


def modular_log_tables() -> tuple[str, ...]:
    return (
        "logs_sistema_modular",
        "mod_ipiranga_logs_importacao",
        "mod_faturamento_logs_importacao",
        "mod_faturamento_coupa_logs_importacao",
        "mod_estadias_logs_importacao",
        "historico_backups_modular",
    )


def modular_tables() -> tuple[str, ...]:
    return tuple(MODULAR_BASE_TABLES) + (
        "mod_faturamento_lcte_notas_normalizadas",
        "mod_faturamento_coupa_lcte_original",
        "mod_faturamento_coupa_lcte_normalizada",
        "mod_faturamento_coupa_lcte_notas_normalizadas",
        "mod_faturamento_coupa_contrato_original",
        "mod_faturamento_coupa_contrato_normalizada",
        "mod_faturamento_coupa_mapeamento_original",
        "mod_faturamento_coupa_mapeamento_normalizada",
        "mod_faturamento_coupa_mapeamento_pendencias",
        "mod_faturamento_coupa_mapeamento_logs",
        "mod_faturamento_coupa_mapeamento_historico",
        "mod_faturamento_coupa_validacao_resultado",
        "mod_faturamento_coupa_diagnostico_lcte_mapeamento_coupa",
        "mod_faturamento_coupa_saldo_lcte_resultado",
        "mod_faturamento_de_para_cnpj_coupa",
        "mod_faturamento_historico_de_para_cnpj_coupa",
        "mod_faturamento_coupa_validacao_tarifas",
        "mod_faturamento_validacao_tripla_ipp",
        "mod_faturamento_validacao_tripla_ipp_resultado",
        "mod_faturamento_auditoria_cte_flags",
        "mod_faturamento_historico_auditoria_cte_flags",
        "mod_faturamento_tempo_nf_cte_resultados",
        "mod_estadias_control_original",
        "mod_estadias_control_normalizada",
        "mod_estadias_lcte_original",
        "mod_estadias_lcte_normalizada",
        "mod_estadias_rastreador_original",
        "mod_estadias_rastreador_normalizada",
        "mod_estadias_logs_importacao",
        "mod_estadias_cruzamento_inicial",
        "mod_estadias_configuracoes",
        "mod_estadias_locais_operacionais",
        "mod_estadias_parametros_cliente",
        "mod_estadias_auditoria",
        "mod_estadias_conclusoes",
        "mod_estadias_preferencias_colunas",
        "mod_estadias_historico_status",
        *modular_log_tables(),
    )


def create_import_log_table(conn, table: str) -> None:
    conn.execute(
        adapt_sql(
            conn,
            f"""
            create table if not exists {table} (
                id integer primary key autoincrement,
                data_hora text,
                usuario text,
                tipo_importacao text,
                arquivo_origem text,
                hash_arquivo text,
                quantidade_linhas integer default 0,
                quantidade_registros_inseridos integer default 0,
                quantidade_registros_atualizados integer default 0,
                quantidade_registros_ignorados integer default 0,
                status text,
                mensagem text,
                detalhes_json text,
                lote_importacao text,
                created_at text,
                updated_at text
            )
            """,
        )
    )


def _table_columns(conn, table: str) -> set[str]:
    if getattr(conn, "db_type", "sqlite") == "postgres":
        rows = conn.execute(
            """
            select column_name
            from information_schema.columns
            where table_schema = 'public' and table_name = ?
            """,
            (table,),
        ).fetchall()
        return {row["column_name"] for row in rows}
    return {row["name"] for row in conn.execute(f"pragma table_info({table})").fetchall()}


def _create_index_if_column(conn, table: str, index: str, column: str) -> None:
    if column in _table_columns(conn, table):
        conn.execute(f"create index if not exists {index} on {table}({column})")


def _create_index_if_columns(conn, table: str, index: str, columns: list[str]) -> None:
    existing = _table_columns(conn, table)
    selected = [column for column in columns if column in existing]
    if len(selected) == len(columns):
        conn.execute(f"create index if not exists {index} on {table}({', '.join(selected)})")


def create_modular_tables(conn) -> None:
    for table in MODULAR_BASE_TABLES:
        conn.execute(adapt_sql(conn, create_base_table_sql(table)))

    conn.execute(
        adapt_sql(
            conn,
            """
            create table if not exists mod_faturamento_lcte_notas_normalizadas (
                id integer primary key autoincrement,
                importacao_id integer,
                lcte_original_id integer,
                arquivo_origem text,
                lote_importacao text,
                cte_norm text,
                nota_fiscal_norm text,
                chave_nfe text,
                chave_cte text,
                razao_social_cobranca text,
                razao_social_cobranca_norm text,
                produto text,
                produto_norm text,
                origem text,
                origem_norm text,
                destino text,
                destino_norm text,
                placa text,
                motorista text,
                data_nf text,
                data_cte text,
                volume real,
                valor real,
                complemento text,
                detalhes_json text,
                created_at text,
                updated_at text,
                sync_status text default 'SINCRONIZADO',
                last_synced_at text
            )
            """,
        )
    )

    create_import_log_table(conn, "mod_ipiranga_logs_importacao")
    create_import_log_table(conn, "mod_faturamento_logs_importacao")
    create_import_log_table(conn, "mod_faturamento_coupa_logs_importacao")
    create_import_log_table(conn, "mod_estadias_logs_importacao")

    conn.execute(adapt_sql(conn, "create table if not exists mod_faturamento_coupa_lcte_original (id integer primary key autoincrement, lote_importacao text, arquivo_origem text, usuario_importacao text, data_hora_importacao text, hash_arquivo text, numero_linha integer, hash_registro text, dados_json text, created_at text, updated_at text)"))
    conn.execute(
        adapt_sql(
            conn,
            """
            create table if not exists mod_faturamento_coupa_lcte_normalizada (
                id integer primary key autoincrement,
                lote_importacao text,
                arquivo_origem text,
                usuario_importacao text,
                data_hora_importacao text,
                hash_arquivo text,
                numero_linha integer,
                hash_registro text,
                cte text,
                cte_norm text,
                nota_fiscal text,
                nota_fiscal_norm text,
                chave_nfe text,
                data_emissao_cte text,
                data_emissao_lcte text,
                data_emissao_nf text,
                hora_emissao_cte text,
                hora_emissao_nf text,
                data_hora_cte text,
                data_hora_nf text,
                razao_social_cobranca text,
                razao_social_cobranca_norm text,
                cnpj_cobranca text,
                cnpj_cobranca_norm text,
                cnpj_lcte_para_coupa_norm text,
                origem_cnpj_lcte_para_coupa text,
                remetente text,
                remetente_norm text,
                cnpj_remetente text,
                cnpj_remetente_norm text,
                cnpj_cpf_remetente_original text,
                cnpj_cpf_remetente_norm text,
                destinatario text,
                destinatario_norm text,
                cnpj_destinatario text,
                cnpj_destinatario_norm text,
                cnpj_cpf_destinatario_original text,
                cnpj_cpf_destinatario_norm text,
                local_coleta text,
                local_coleta_norm text,
                local_entrega text,
                local_entrega_norm text,
                origem text,
                origem_norm text,
                destino text,
                destino_norm text,
                produto text,
                produto_norm text,
                produto_lcte text,
                produto_lcte_norm text,
                produto_grupo_lcte text,
                volume_lcte_original text,
                volume_lcte real,
                volume_lcte_m3 real,
                volume real,
                volume_litros real,
                valor_frete real,
                valor_cte real,
                valor_total_cte real,
                peso_frete real,
                frete_unitario real,
                pedagio real,
                impostos real,
                placa text,
                placa_norm text,
                motorista text,
                operacao text,
                tabela_frete text,
                complemento_original text,
                complemento_norm text,
                observacao text,
                observacao_norm text,
                cte_complementar_norm text,
                motivo_identificacao_complemento text,
                dados_json text,
                created_at text,
                updated_at text
            )
            """,
        )
    )
    conn.execute(
        adapt_sql(
            conn,
            """
            create table if not exists mod_faturamento_coupa_lcte_notas_normalizadas (
                id integer primary key autoincrement,
                lote_importacao text,
                arquivo_origem text,
                usuario_importacao text,
                data_hora_importacao text,
                hash_arquivo text,
                numero_linha integer,
                hash_registro text,
                cte_norm text,
                nota_fiscal_norm text,
                chave_nfe text,
                razao_social_cobranca text,
                razao_social_cobranca_norm text,
                cnpj_cobranca_norm text,
                produto text,
                produto_norm text,
                origem text,
                origem_norm text,
                destino text,
                destino_norm text,
                placa text,
                data_nf text,
                data_cte text,
                volume_litros real,
                valor_frete real,
                complemento_norm text,
                dados_json text,
                created_at text,
                updated_at text
            )
            """,
        )
    )
    conn.execute(adapt_sql(conn, "create table if not exists mod_faturamento_coupa_contrato_original (id integer primary key autoincrement, lote_importacao text, arquivo_origem text, usuario_importacao text, data_hora_importacao text, hash_arquivo text, numero_linha integer, hash_registro text, dados_json text, created_at text, updated_at text)"))
    conn.execute(
        adapt_sql(
            conn,
            """
            create table if not exists mod_faturamento_coupa_contrato_normalizada (
                id integer primary key autoincrement,
                lote_importacao text,
                arquivo_origem text,
                usuario_importacao text,
                data_hora_importacao text,
                hash_arquivo text,
                numero_linha integer,
                hash_registro text,
                arquivo_coupa text,
                coluna_arquivo_origem text,
                aba_origem_coupa text,
                codigo_coupa text,
                codigo_coupa_norm text,
                item_coupa text,
                coluna_item_origem text,
                contrato_coupa text,
                nomenclatura_coupa text,
                nomenclatura_coupa_norm text,
                origem_coupa text,
                origem_coupa_norm text,
                origem_coupa_original text,
                coluna_origem_origem text,
                destino_coupa text,
                destino_coupa_norm text,
                destino_coupa_original text,
                coluna_destino_origem text,
                produto_coupa text,
                produto_coupa_norm text,
                produto_grupo_coupa text,
                produto_coupa_original text,
                coluna_produto_origem text,
                cnpj_coupa text,
                cnpj_coupa_norm text,
                cliente_coupa text,
                cliente_coupa_norm text,
                vigencia_inicio text,
                vigencia_fim text,
                dt_inicio text,
                dt_inicio_original text,
                dt_termino text,
                dt_termino_original text,
                coluna_dt_inicio_origem text,
                coluna_dt_termino_origem text,
                data_base text,
                data_referencia text,
                tarifa_coupa real,
                unidade_tarifa_coupa text,
                volume_contratado real,
                qtd_contratada real,
                qtd_contratada_original text,
                coluna_qtd_origem text,
                volume_minimo real,
                volume_maximo real,
                valor_contratado real,
                valor_total_coupa real,
                status_coupa text,
                observacao_coupa text,
                dados_json text,
                created_at text,
                updated_at text
            )
            """,
        )
    )
    conn.execute(adapt_sql(conn, "create table if not exists mod_faturamento_coupa_mapeamento_original (id integer primary key autoincrement, lote_importacao text, arquivo_origem text, usuario_importacao text, data_hora_importacao text, hash_arquivo text, numero_linha integer, hash_registro text, dados_json text, created_at text, updated_at text)"))
    conn.execute(
        adapt_sql(
            conn,
            """
            create table if not exists mod_faturamento_coupa_mapeamento_normalizada (
                id integer primary key autoincrement,
                lote_importacao text,
                arquivo_origem text,
                usuario_importacao text,
                data_hora_importacao text,
                hash_arquivo text,
                numero_linha integer,
                hash_registro text,
                hash_linha text,
                ativo integer default 1,
                descricao_coupa_original text,
                descricao_coupa_norm text,
                cnpj_original text,
                cnpj_norm text,
                cnpj_mapeamento_norm text,
                cnpj_valido text,
                cnpj_lcte text,
                cnpj_lcte_norm text,
                razao_social_lcte text,
                razao_social_lcte_norm text,
                origem_lcte text,
                origem_lcte_norm text,
                destino_lcte text,
                destino_lcte_norm text,
                produto_lcte text,
                produto_lcte_norm text,
                operacao_lcte text,
                operacao_lcte_norm text,
                tabela_frete_lcte text,
                tabela_frete_lcte_norm text,
                codigo_coupa text,
                contrato_coupa text,
                nomenclatura_coupa text,
                nomenclatura_coupa_norm text,
                origem_coupa text,
                origem_coupa_norm text,
                destino_coupa text,
                destino_coupa_norm text,
                produto_coupa text,
                produto_coupa_norm text,
                cliente_coupa text,
                cliente_coupa_norm text,
                tipo_vinculo text,
                prioridade integer default 999,
                vigencia_inicio text,
                vigencia_fim text,
                observacao text,
                status_mapeamento text,
                diagnostico_json text,
                dados_json text,
                created_by text,
                created_at text,
                updated_by text,
                updated_at text
            )
            """,
        )
    )
    conn.execute(
        adapt_sql(
            conn,
            """
            create table if not exists mod_faturamento_coupa_mapeamento_pendencias (
                id integer primary key autoincrement,
                data_hora_geracao text,
                lote_geracao text,
                cnpj_norm text,
                cnpj_original text,
                razao_social_lcte text,
                qtd_registros_lcte integer default 0,
                valor_total_faturado real default 0,
                volume_total real default 0,
                primeira_data_cte text,
                ultima_data_cte text,
                exemplo_cte text,
                exemplo_nf text,
                origem_cnpj text,
                status_pendencia text,
                resolvido integer default 0,
                data_hora_resolucao text,
                usuario_resolucao text,
                descricao_coupa_resolvida text,
                lote_importacao_resolucao text
            )
            """,
        )
    )
    conn.execute(
        adapt_sql(
            conn,
            """
            create table if not exists mod_faturamento_coupa_mapeamento_logs (
                id integer primary key autoincrement,
                data_hora text,
                usuario text,
                acao text,
                status text,
                mensagem text,
                detalhes_json text
            )
            """,
        )
    )
    conn.execute(
        adapt_sql(
            conn,
            """
            create table if not exists mod_faturamento_coupa_mapeamento_historico (
                id integer primary key autoincrement,
                data_hora text,
                usuario text,
                acao text,
                descricao_coupa text,
                cnpj_norm text,
                cnpj_anterior text,
                cnpj_novo text,
                status text,
                descricao_anterior text,
                descricao_nova text,
                arquivo_origem text,
                lote_importacao text,
                observacao text,
                detalhes_json text
            )
            """,
        )
    )
    conn.execute(
        adapt_sql(
            conn,
            """
            create table if not exists mod_faturamento_coupa_validacao_resultado (
                id integer primary key autoincrement,
                lote_validacao text,
                data_hora_validacao text,
                usuario text,
                cte_norm text,
                nota_fiscal_norm text,
                id_mapeamento integer,
                codigo_coupa text,
                tarifa_coupa real,
                volume_litros real,
                valor_frete real,
                valor_contratado real,
                diferenca real,
                status_validacao text,
                detalhes_json text
            )
            """,
        )
    )
    conn.execute(
        adapt_sql(
            conn,
            """
            create table if not exists mod_faturamento_coupa_diagnostico_lcte_mapeamento_coupa (
                id integer primary key autoincrement,
                lote_diagnostico text,
                data_hora_diagnostico text,
                usuario text,
                cte_norm text,
                nota_fiscal_norm text,
                razao_social_cobranca text,
                cnpj_cobranca_norm text,
                cnpj_lcte_para_coupa_norm text,
                origem_cnpj_lcte_para_coupa text,
                origem_lcte_norm text,
                destino_lcte_norm text,
                produto_lcte_norm text,
                valor_frete real,
                volume_litros real,
                mapeamento_encontrado text,
                id_mapeamento integer,
                tipo_vinculo text,
                nomenclatura_coupa_usada text,
                descricao_coupa_mapeada text,
                descricao_coupa_norm text,
                status_mapeamento_lcte text,
                origem_coupa_mapeada text,
                destino_coupa_mapeada text,
                produto_coupa_mapeado text,
                coupa_encontrado text,
                codigo_coupa text,
                tarifa_coupa real,
                unidade_tarifa_coupa text,
                volume_contratado real,
                valor_contratado real,
                vigencia_inicio text,
                vigencia_fim text,
                status_diagnostico text,
                detalhes_json text
            )
            """,
        )
    )
    conn.execute(
        adapt_sql(
            conn,
            """
            create table if not exists mod_faturamento_coupa_saldo_lcte_resultado (
                id integer primary key autoincrement,
                lote_calculo text,
                data_hora_calculo text,
                lote_validacao text,
                data_hora_validacao text,
                usuario text,
                id_coupa integer,
                codigo_coupa_norm text,
                item text,
                aba_origem_coupa text,
                lote_importacao_coupa text,
                lote_importacao_lcte text,
                dt_inicio text,
                dt_termino text,
                qtd_contratada real,
                qtd_contratada_original text,
                coluna_qtd_origem text,
                origem text,
                origem_coupa text,
                origem_coupa_norm text,
                origem_cnpj_mapeado_norm text,
                destino text,
                destino_coupa text,
                destino_coupa_norm text,
                destino_cnpj_mapeado_norm text,
                produto text,
                produto_coupa text,
                produto_coupa_norm text,
                produto_grupo_coupa text,
                status_periodo text,
                volume_lcte_abatido real,
                volume_lcte_m3_total real,
                saldo real,
                saldo_qtd real,
                percentual_consumido real,
                percentual_saldo real,
                status_saldo text,
                status_saldo_coupa text,
                qtd_lctes_abatidos integer default 0,
                qtd_ctes integer default 0,
                qtd_nfs integer default 0,
                valor_faturado_lcte real default 0,
                qtd_linhas_lcte_antes_deduplicacao integer default 0,
                qtd_linhas_lcte_depois_deduplicacao integer default 0,
                qtd_duplicidades_removidas integer default 0,
                primeiro_cte text,
                ultimo_cte text,
                origem_match text,
                destino_match text,
                produto_match text,
                status_match_direcao text,
                tipo_match_lcte text,
                cnpj_remetente_lcte_esperado text,
                cnpj_destinatario_lcte_esperado text,
                ctes_encontrados text,
                volume_lcte_total real,
                saldo_calculado real,
                lcte_ids_json text,
                diagnostico_json text,
                detalhes_json text
            )
            """,
        )
    )
    for table, index in {
        "mod_faturamento_coupa_lcte_original": "idx_coupa_lcte_orig_hash",
        "mod_faturamento_coupa_lcte_normalizada": "idx_coupa_lcte_norm_hash",
        "mod_faturamento_coupa_lcte_notas_normalizadas": "idx_coupa_lcte_notas_hash",
        "mod_faturamento_coupa_contrato_original": "idx_coupa_contrato_orig_hash",
        "mod_faturamento_coupa_contrato_normalizada": "idx_coupa_contrato_norm_hash",
        "mod_faturamento_coupa_mapeamento_original": "idx_coupa_map_orig_hash",
        "mod_faturamento_coupa_mapeamento_normalizada": "idx_coupa_map_norm_hash",
    }.items():
        conn.execute(f"create unique index if not exists {index} on {table}(hash_registro)")

    conn.execute(
        adapt_sql(
            conn,
            """
            create table if not exists mod_faturamento_de_para_cnpj_coupa (
                id integer primary key autoincrement,
                cnpj text,
                cnpj_norm text,
                razao_social_lcte text,
                razao_social_lcte_norm text,
                nomenclatura_coupa text,
                nomenclatura_coupa_norm text,
                tipo_vinculo text,
                origem_destino text,
                observacao text,
                ativo integer default 1,
                codigo_coupa text,
                localidade_coupa text,
                uf text,
                cidade text,
                cliente text,
                tipo_operacao text,
                created_at text,
                created_by text,
                updated_at text,
                updated_by text
            )
            """,
        )
    )
    conn.execute(
        adapt_sql(
            conn,
            """
            create table if not exists mod_faturamento_historico_de_para_cnpj_coupa (
                id integer primary key autoincrement,
                id_de_para integer,
                data_hora text,
                usuario text,
                acao text,
                valor_anterior_json text,
                valor_novo_json text,
                observacao text
            )
            """,
        )
    )
    conn.execute(
        adapt_sql(
            conn,
            """
            create table if not exists mod_faturamento_coupa_validacao_tarifas (
                id integer primary key autoincrement,
                lote_validacao text,
                data_hora_validacao text,
                usuario text,
                origem text,
                origem_norm text,
                destino text,
                destino_norm text,
                produto text,
                produto_norm text,
                data_referencia text,
                tarifa_contratada real,
                volume_contratado real,
                volume_emitido real,
                valor_contratado real,
                valor_faturado real,
                diferenca real,
                status text,
                usou_de_para_coupa text default 'NAO',
                id_de_para_coupa integer,
                nomenclatura_coupa_usada text,
                status_de_para_coupa text,
                detalhes_json text
            )
            """,
        )
    )
    conn.execute(
        adapt_sql(
            conn,
            """
            create table if not exists mod_faturamento_validacao_tripla_ipp_resultado (
                id integer primary key autoincrement,
                lote_validacao text,
                data_hora_validacao text,
                usuario text,
                cte_norm text,
                nota_fiscal_norm text,
                chave_nfe text,
                razao_social_cobranca text,
                razao_social_cobranca_norm text,
                produto text,
                produto_norm text,
                origem text,
                origem_norm text,
                destino text,
                destino_norm text,
                placa text,
                motorista text,
                valor_lcte_normal real,
                valor_lcte_complementar real,
                valor_faturado_lcte_total real,
                valor_portal real,
                valor_portal_original text,
                coluna_origem_valor_portal text,
                valor_coupa real,
                tarifa_coupa real,
                volume_lcte real,
                volume_coupa real,
                unidade_tarifa_coupa text,
                diferenca_lcte_portal real,
                diferenca_lcte_coupa real,
                diferenca_portal_coupa real,
                status_kmm text,
                status_portal text,
                status_coupa text,
                status_valor text,
                status_final text,
                usou_de_para_coupa text default 'NAO',
                id_de_para_coupa integer,
                nomenclatura_coupa_usada text,
                arquivo_origem_lcte text,
                arquivo_origem_nsdocs text,
                arquivo_origem_coupa text,
                arquivo_origem_portal text,
                detalhes_json text
            )
            """,
        )
    )
    conn.execute(adapt_sql(conn, "create table if not exists mod_faturamento_validacao_tripla_ipp (id integer primary key autoincrement, lote_validacao text, data_hora text, usuario text, status text, detalhes_json text)"))
    conn.execute(adapt_sql(conn, "create table if not exists mod_faturamento_auditoria_cte_flags (id integer primary key autoincrement, cte_norm text, nota_fiscal_norm text, flag text, status text, observacao text, created_at text, created_by text, updated_at text, updated_by text)"))
    conn.execute(adapt_sql(conn, "create table if not exists mod_faturamento_historico_auditoria_cte_flags (id integer primary key autoincrement, id_flag integer, data_hora text, usuario text, acao text, valor_anterior_json text, valor_novo_json text, observacao text)"))
    conn.execute(adapt_sql(conn, "create table if not exists mod_faturamento_tempo_nf_cte_resultados (id integer primary key autoincrement, lote_validacao text, data_hora_validacao text, usuario text, nota_fiscal_norm text, cte_norm text, data_nf text, data_cte text, tempo_horas real, status text, detalhes_json text)"))
    conn.execute(adapt_sql(conn, "create table if not exists logs_sistema_modular (id integer primary key autoincrement, data_hora text, usuario text, modulo text, submodulo text, acao text, nivel text, mensagem text, detalhes_json text)"))
    conn.execute(adapt_sql(conn, "create table if not exists historico_backups_modular (id integer primary key autoincrement, data_hora text, usuario text, tipo_backup text, modulo text, status text, arquivo_backup text, destino text, tamanho integer, mensagem text, detalhes_json text)"))
    conn.execute(adapt_sql(conn, "create table if not exists mod_estadias_lcte_original (id integer primary key autoincrement, lote_importacao text, arquivo_origem text, usuario_importacao text, data_hora_importacao text, hash_arquivo text, numero_linha integer, dados_json text, created_at text, updated_at text)"))
    conn.execute(
        adapt_sql(
            conn,
            """
            create table if not exists mod_estadias_lcte_normalizada (
                id integer primary key autoincrement,
                lote_importacao text,
                arquivo_origem text,
                usuario_importacao text,
                data_hora_importacao text,
                hash_arquivo text,
                numero_linha integer,
                chave_viagem text,
                cte text,
                nf text,
                chave_nf text,
                placa text,
                placa_norm text,
                placas_composicao text,
                motorista text,
                cliente text,
                cliente_norm text,
                razao_social_cobranca text,
                remetente text,
                destinatario text,
                data_emissao text,
                data_carga text,
                hora_carga text,
                data_hora_carga text,
                data_operacao text,
                origem text,
                origem_norm text,
                uf_origem text,
                destino text,
                destino_norm text,
                uf_destino text,
                volume real,
                produto text,
                tabela_frete text,
                pedido text,
                romaneio text,
                numero_viagem text,
                km_rota real,
                valor_frete real,
                latitude_origem real,
                longitude_origem real,
                latitude_destino real,
                longitude_destino real,
                observacao text,
                dados_json text,
                created_at text,
                updated_at text
            )
            """,
        )
    )
    conn.execute(adapt_sql(conn, "create table if not exists mod_estadias_control_original (id integer primary key autoincrement, lote_importacao text, arquivo_origem text, usuario_importacao text, data_hora_importacao text, hash_arquivo text, numero_linha integer, dados_json text, created_at text, updated_at text)"))
    conn.execute(
        adapt_sql(
            conn,
            """
            create table if not exists mod_estadias_control_normalizada (
                id integer primary key autoincrement,
                lote_importacao text,
                arquivo_origem text,
                usuario_importacao text,
                data_hora_importacao text,
                hash_arquivo text,
                numero_linha integer,
                placa text,
                placa_norm text,
                motorista text,
                cliente text,
                razao_social text,
                local_origem text,
                local_destino text,
                local_evento text,
                data_inicio text,
                hora_inicio text,
                data_fim text,
                hora_fim text,
                data_hora_inicio text,
                data_hora_fim text,
                tipo_evento text,
                status text,
                observacao text,
                valor_estadia real,
                tempo_total real,
                numero_documento text,
                cte text,
                nf text,
                pedido text,
                viagem text,
                dados_json text,
                created_at text,
                updated_at text
            )
            """,
        )
    )
    conn.execute(adapt_sql(conn, "create table if not exists mod_estadias_rastreador_original (id integer primary key autoincrement, lote_importacao text, arquivo_origem text, usuario_importacao text, data_hora_importacao text, hash_arquivo text, numero_linha integer, placa_arquivo text, dados_json text, created_at text, updated_at text)"))
    conn.execute(
        adapt_sql(
            conn,
            """
            create table if not exists mod_estadias_rastreador_normalizada (
                id integer primary key autoincrement,
                lote_importacao text,
                arquivo_origem text,
                usuario_importacao text,
                data_hora_importacao text,
                hash_arquivo text,
                numero_linha integer,
                placa text,
                placa_norm text,
                data text,
                hora text,
                data_hora text,
                latitude real,
                longitude real,
                endereco text,
                cidade text,
                uf text,
                velocidade real,
                ignicao text,
                evento text,
                status text,
                odometro real,
                motorista text,
                dados_json text,
                created_at text,
                updated_at text
            )
            """,
        )
    )
    conn.execute(
        adapt_sql(
            conn,
            """
            create table if not exists mod_estadias_cruzamento_inicial (
                id integer primary key autoincrement,
                lcte_id integer,
                chave_viagem text,
                cte text,
                nf text,
                chave_nf text,
                placa_norm text,
                placas_composicao text,
                data_operacao text,
                data_hora_carga text,
                data_inicio_viagem_referencia text,
                fonte_data_inicio_viagem text,
                origem text,
                uf_origem text,
                destino text,
                uf_destino text,
                cliente text,
                motorista text,
                status_lcte text,
                status_control text,
                status_rastreador text,
                pontuacao_control real,
                classificacao_control text,
                criterios_control_json text,
                control_id integer,
                encontrou_lcte integer default 0,
                encontrou_control integer default 0,
                encontrou_rastreador integer default 0,
                encontrou_origem integer default 0,
                encontrou_destino integer default 0,
                calculou_estadia integer default 0,
                existe_control integer default 0,
                existe_rastreador integer default 0,
                qtd_registros_control integer default 0,
                qtd_registros_rastreador integer default 0,
                fonte_janela text,
                inicio_janela text,
                fim_janela text,
                qtd_total_pontos_placa integer default 0,
                primeira_data_control text,
                ultima_data_control text,
                primeira_data_rastreador text,
                ultima_data_rastreador text,
                chegada_origem text,
                saida_origem text,
                chegada_destino text,
                saida_destino text,
                control_chegada_origem text,
                control_saida_origem text,
                control_chegada_destino text,
                control_saida_destino text,
                diferenca_chegada_origem_min real,
                diferenca_saida_origem_min real,
                diferenca_chegada_destino_min real,
                diferenca_saida_destino_min real,
                maior_divergencia_min real,
                media_divergencias_min real,
                eventos_comparaveis integer default 0,
                eventos_sem_control integer default 0,
                eventos_sem_rastreador integer default 0,
                dentro_tolerancia_control_rastreador integer default 0,
                tolerancia_control_rastreador_min real,
                tempo_origem_min real,
                tempo_destino_min real,
                regra_especial_origem integer default 0,
                regra_especial_destino integer default 0,
                municipio_operacional_origem text,
                municipio_operacional_destino text,
                metodo_localizacao_origem text,
                metodo_localizacao_destino text,
                qtd_blocos_municipio_origem integer default 0,
                qtd_blocos_municipio_destino integer default 0,
                bloco_selecionado_origem text,
                bloco_selecionado_destino text,
                referencias_visitadas_origem text,
                referencias_visitadas_destino text,
                motivo_escolha_bloco_origem text,
                motivo_escolha_bloco_destino text,
                confianca_permanencia_origem_pct real,
                confianca_permanencia_destino_pct real,
                motivo_confirmacao_saida_origem text,
                motivo_confirmacao_saida_destino text,
                interrupcoes_ignoradas_origem integer default 0,
                interrupcoes_ignoradas_destino integer default 0,
                maior_distancia_temporaria_cerca_origem_km real,
                maior_distancia_temporaria_cerca_destino_km real,
                tempo_oscilacao_absorvido_origem_min real,
                tempo_oscilacao_absorvido_destino_min real,
                tempo_operacional_min real,
                tempo_transito_min real,
                tempo_total_viagem_min real,
                tempo_control_min real,
                tempo_rastreador_min real,
                diferenca_control_rastreador_min real,
                km_percorrido real,
                distancia_ponto_carga_km real,
                distancia_ponto_descarga_km real,
                pontos_origem integer default 0,
                pontos_destino integer default 0,
                franquia_carga_min real,
                franquia_descarga_min real,
                estadia_carga_min real,
                estadia_descarga_min real,
                horas_estadia real,
                elegivel_cobranca integer default 0,
                motivo_nao_elegibilidade text,
                horario_agendado_carga text,
                horario_agendado_descarga text,
                diferenca_agendamento_carga_min real,
                diferenca_agendamento_descarga_min real,
                dentro_limite_operacional integer default 1,
                observacao_manual text,
                valor_estimado_estadia real,
                status_cruzamento text,
                painel_atual text,
                status_processamento text,
                status_permanencia text,
                status_estadia text,
                status_verificacao text,
                status_tratativa text,
                status_retorno text,
                status_cte text,
                concluido integer default 0,
                tratado integer default 0,
                precisa_verificar integer default 0,
                tipo_conclusao text,
                observacao_conclusao text,
                usuario_conclusao text,
                data_hora_conclusao text,
                data_limite_retorno text,
                dias_restantes integer,
                retorno_recebido integer default 0,
                data_retorno text,
                status_prazo text,
                protocolo text,
                valor_solicitado real,
                valor_aprovado real,
                codigo_motivo text,
                descricao_motivo text,
                motivo_falha text,
                diagnostico_json text,
                log_processamento_json text,
                atualizado_em text,
                atualizado_por text
            )
            """,
        )
    )
    conn.execute(
        adapt_sql(
            conn,
            """
            create table if not exists mod_estadias_configuracoes (
                id integer primary key autoincrement,
                chave text,
                valor text,
                descricao text,
                updated_at text,
                updated_by text
            )
            """,
        )
    )
    conn.execute(
        adapt_sql(
            conn,
            """
            create table if not exists mod_estadias_locais_operacionais (
                id integer primary key autoincrement,
                nome_padrao text,
                nome_norm text,
                municipio text,
                uf text,
                razao_social text,
                latitude real,
                longitude real,
                raio_metros real,
                tipo_local text,
                aliases text,
                origem_cadastro text,
                ativo integer default 1,
                ultima_atualizacao text,
                created_at text,
                created_by text,
                updated_at text,
                updated_by text
            )
            """,
        )
    )
    conn.execute(
        adapt_sql(
            conn,
            """
            create table if not exists mod_estadias_parametros_cliente (
                id integer primary key autoincrement,
                cliente text,
                cliente_norm text,
                tipo_operacao text,
                franquia_carga_horas real default 24,
                franquia_descarga_horas real default 24,
                inicio_contagem text,
                regra_agendamento text,
                valor_hora real default 0,
                vigencia_inicial text,
                vigencia_final text,
                observacoes text,
                ativo integer default 1,
                created_at text,
                created_by text,
                updated_at text,
                updated_by text
            )
            """,
        )
    )
    conn.execute(
        adapt_sql(
            conn,
            """
            create table if not exists mod_estadias_auditoria (
                id integer primary key autoincrement,
                data_hora text,
                usuario text,
                acao text,
                chave_viagem text,
                arquivo_origem text,
                valor_anterior_json text,
                valor_novo_json text,
                observacao text,
                detalhes_json text
            )
            """,
        )
    )
    conn.execute(
        adapt_sql(
            conn,
            """
            create table if not exists mod_estadias_conclusoes (
                id integer primary key autoincrement,
                lcte_id integer,
                data_hora_conclusao text,
                usuario_responsavel text,
                painel_origem text,
                painel_destino text,
                tipo_conclusao text,
                status_tratativa text,
                observacao text,
                protocolo text,
                valor_solicitado real,
                valor_aprovado real,
                necessita_retorno integer default 0,
                retorno_recebido integer default 0,
                data_retorno text,
                precisa_verificar integer default 0,
                motivo_verificacao text,
                status_retorno text,
                reaberto integer default 0,
                motivo_reabertura text,
                created_at text,
                created_by text
            )
            """,
        )
    )
    conn.execute(
        adapt_sql(
            conn,
            """
            create table if not exists mod_estadias_preferencias_colunas (
                id integer primary key autoincrement,
                usuario text,
                painel text,
                colunas_json text,
                updated_at text
            )
            """,
        )
    )
    conn.execute(
        adapt_sql(
            conn,
            """
            create table if not exists mod_estadias_historico_status (
                id integer primary key autoincrement,
                data_hora text,
                lcte_id integer,
                usuario text,
                acao text,
                painel_origem text,
                painel_destino text,
                valor_anterior_json text,
                valor_novo_json text,
                justificativa text
            )
            """,
        )
    )
    conn.execute("create unique index if not exists idx_mod_estadias_config_chave on mod_estadias_configuracoes(chave)")
    for chave, descricao in {
        "tolerancia_minutos": "Tolerancia em minutos para cruzamento por horario.",
        "raio_metros_local": "Raio em metros para identificar permanencia no local.",
        "tempo_minimo_parado": "Tempo minimo parado para considerar evento.",
        "considerar_ignicao": "Parametro futuro para avaliar ignicao.",
        "considerar_velocidade_zero": "Parametro futuro para avaliar velocidade zero.",
        "janela_viagem_dias": "Quantidade de dias apos a carga para buscar rastreador.",
        "janela_lcte_horas_antes": "Horas antes da emissao LCTE para iniciar a busca no rastreador.",
        "janela_lcte_dias_depois": "Dias apos a emissao LCTE para encerrar a busca no rastreador.",
        "janela_control_horas_antes": "Horas antes da carga CONTROL para iniciar a busca no rastreador.",
        "janela_control_horas_depois": "Horas apos a descarga CONTROL para encerrar a busca no rastreador.",
        "min_pontos_permanencia": "Quantidade minima de pontos para reconhecer uma permanencia.",
        "valor_hora_estadia": "Valor estimado por hora de estadia.",
        "franquia_padrao_horas": "Franquia padrao em horas para carga e descarga.",
        "tolerancia_sem_sinal_minutos": "Tolerancia para ausencia temporaria de sinal no rastreador.",
        "tolerancia_fora_cerca_minutos": "Tolerancia para saida temporaria da cerca virtual.",
        "tolerancia_raio_extra_metros": "Margem extra em metros antes de encerrar permanencia.",
        "tolerancia_control_rastreador_min": "Tolerancia CONTROL x Rastreador em minutos para validacao automatica.",
        "saida_confirmacao_minutos": "Tempo fora da cerca ou municipio para confirmar saida real.",
        "saida_distancia_confirmacao_km": "Distancia minima para confirmar afastamento da origem ou destino.",
        "saida_posicoes_consecutivas": "Quantidade minima de posicoes consecutivas fora para confirmar saida.",
        "saida_velocidade_media_kmh": "Velocidade media minima para confirmar deslocamento apos saida.",
        "limite_agendamento_minutos": "Limite operacional para diferenca de agendamento.",
    }.items():
        conn.execute(
            """
            insert or ignore into mod_estadias_configuracoes (chave, valor, descricao, updated_at, updated_by)
            values (?, '', ?, '', 'sistema')
            """,
            (chave, descricao),
        )

    ensure_columns(conn, "mod_faturamento_validacao_tripla_ipp_resultado", {"status_de_para_coupa": "text"})
    ensure_columns(
        conn,
        "mod_faturamento_coupa_lcte_normalizada",
        {
            "cnpj_lcte_para_coupa_norm": "text",
            "origem_cnpj_lcte_para_coupa": "text",
            "cnpj_cpf_remetente_original": "text",
            "cnpj_cpf_remetente_norm": "text",
            "cnpj_cpf_destinatario_original": "text",
            "cnpj_cpf_destinatario_norm": "text",
            "produto_lcte": "text",
            "produto_lcte_norm": "text",
            "produto_grupo_lcte": "text",
            "volume_lcte_original": "text",
            "volume_lcte": "real",
            "volume_lcte_m3": "real",
            "data_emissao_lcte": "text",
        },
    )
    ensure_columns(
        conn,
        "mod_faturamento_coupa_contrato_normalizada",
        {
            "dt_inicio": "text",
            "dt_termino": "text",
            "qtd_contratada": "real",
            "qtd_contratada_original": "text",
            "coluna_qtd_origem": "text",
            "arquivo_coupa": "text",
            "coluna_arquivo_origem": "text",
            "aba_origem_coupa": "text",
            "codigo_coupa_norm": "text",
            "item_coupa": "text",
            "coluna_item_origem": "text",
            "dt_inicio_original": "text",
            "dt_termino_original": "text",
            "coluna_dt_inicio_origem": "text",
            "coluna_dt_termino_origem": "text",
            "coluna_origem_origem": "text",
            "coluna_destino_origem": "text",
            "coluna_produto_origem": "text",
            "origem_coupa_original": "text",
            "destino_coupa_original": "text",
            "produto_coupa_original": "text",
            "produto_grupo_coupa": "text",
        },
    )
    ensure_columns(
        conn,
        "mod_faturamento_coupa_saldo_lcte_resultado",
        {
            "lote_calculo": "text",
            "data_hora_calculo": "text",
            "lote_importacao_lcte": "text",
            "codigo_coupa_norm": "text",
            "item": "text",
            "aba_origem_coupa": "text",
            "qtd_contratada_original": "text",
            "coluna_qtd_origem": "text",
            "origem": "text",
            "origem_cnpj_mapeado_norm": "text",
            "destino": "text",
            "destino_cnpj_mapeado_norm": "text",
            "produto": "text",
            "produto_grupo_coupa": "text",
            "status_periodo": "text",
            "volume_lcte_abatido": "real",
            "saldo": "real",
            "status_saldo": "text",
            "status_match_direcao": "text",
            "tipo_match_lcte": "text",
            "cnpj_remetente_lcte_esperado": "text",
            "cnpj_destinatario_lcte_esperado": "text",
            "ctes_encontrados": "text",
            "volume_lcte_total": "real",
            "saldo_calculado": "real",
            "qtd_lctes_abatidos": "integer default 0",
            "qtd_linhas_lcte_antes_deduplicacao": "integer default 0",
            "qtd_linhas_lcte_depois_deduplicacao": "integer default 0",
            "qtd_duplicidades_removidas": "integer default 0",
            "diagnostico_json": "text",
        },
    )
    ensure_columns(
        conn,
        "mod_faturamento_coupa_mapeamento_normalizada",
        {
            "dados_json": "text",
            "hash_linha": "text",
            "descricao_coupa_original": "text",
            "descricao_coupa_norm": "text",
            "cnpj_original": "text",
            "cnpj_norm": "text",
            "cnpj_mapeamento_norm": "text",
            "cnpj_valido": "text",
        },
    )
    ensure_columns(
        conn,
        "mod_faturamento_coupa_mapeamento_historico",
        {
            "descricao_coupa": "text",
            "cnpj_anterior": "text",
            "cnpj_novo": "text",
            "status": "text",
        },
    )
    ensure_columns(
        conn,
        "mod_faturamento_coupa_diagnostico_lcte_mapeamento_coupa",
        {
            "cnpj_lcte_para_coupa_norm": "text",
            "origem_cnpj_lcte_para_coupa": "text",
            "descricao_coupa_mapeada": "text",
            "descricao_coupa_norm": "text",
            "status_mapeamento_lcte": "text",
        },
    )
    ensure_columns(
        conn,
        "mod_estadias_lcte_normalizada",
        {
            "cte": "text",
            "nf": "text",
            "chave_viagem": "text",
            "chave_nf": "text",
            "placa": "text",
            "placa_norm": "text",
            "placas_composicao": "text",
            "motorista": "text",
            "cliente": "text",
            "cliente_norm": "text",
            "razao_social_cobranca": "text",
            "remetente": "text",
            "destinatario": "text",
            "data_emissao": "text",
            "data_carga": "text",
            "hora_carga": "text",
            "data_hora_carga": "text",
            "data_operacao": "text",
            "origem": "text",
            "origem_norm": "text",
            "uf_origem": "text",
            "destino": "text",
            "destino_norm": "text",
            "uf_destino": "text",
            "volume": "real",
            "produto": "text",
            "tabela_frete": "text",
            "pedido": "text",
            "romaneio": "text",
            "numero_viagem": "text",
            "km_rota": "real",
            "valor_frete": "real",
            "latitude_origem": "real",
            "longitude_origem": "real",
            "latitude_destino": "real",
            "longitude_destino": "real",
            "observacao": "text",
            "dados_json": "text",
            "created_at": "text",
            "updated_at": "text",
        },
    )
    ensure_columns(
        conn,
        "mod_estadias_cruzamento_inicial",
        {
            "lcte_id": "integer",
            "chave_viagem": "text",
            "cte": "text",
            "nf": "text",
            "chave_nf": "text",
            "placas_composicao": "text",
            "data_operacao": "text",
            "data_hora_carga": "text",
            "data_inicio_viagem_referencia": "text",
            "fonte_data_inicio_viagem": "text",
            "origem": "text",
            "uf_origem": "text",
            "destino": "text",
            "uf_destino": "text",
            "cliente": "text",
            "motorista": "text",
            "status_lcte": "text",
            "status_control": "text",
            "status_rastreador": "text",
            "pontuacao_control": "real",
            "classificacao_control": "text",
            "criterios_control_json": "text",
            "control_id": "integer",
            "encontrou_lcte": "integer default 0",
            "encontrou_control": "integer default 0",
            "encontrou_rastreador": "integer default 0",
            "encontrou_origem": "integer default 0",
            "encontrou_destino": "integer default 0",
            "calculou_estadia": "integer default 0",
            "fonte_janela": "text",
            "inicio_janela": "text",
            "fim_janela": "text",
            "qtd_total_pontos_placa": "integer default 0",
            "chegada_origem": "text",
            "saida_origem": "text",
            "chegada_destino": "text",
            "saida_destino": "text",
            "control_chegada_origem": "text",
            "control_saida_origem": "text",
            "control_chegada_destino": "text",
            "control_saida_destino": "text",
            "diferenca_chegada_origem_min": "real",
            "diferenca_saida_origem_min": "real",
            "diferenca_chegada_destino_min": "real",
            "diferenca_saida_destino_min": "real",
            "maior_divergencia_min": "real",
            "media_divergencias_min": "real",
            "eventos_comparaveis": "integer default 0",
            "eventos_sem_control": "integer default 0",
            "eventos_sem_rastreador": "integer default 0",
            "dentro_tolerancia_control_rastreador": "integer default 0",
            "tolerancia_control_rastreador_min": "real",
            "tempo_origem_min": "real",
            "tempo_destino_min": "real",
            "regra_especial_origem": "integer default 0",
            "regra_especial_destino": "integer default 0",
            "municipio_operacional_origem": "text",
            "municipio_operacional_destino": "text",
            "metodo_localizacao_origem": "text",
            "metodo_localizacao_destino": "text",
            "qtd_blocos_municipio_origem": "integer default 0",
            "qtd_blocos_municipio_destino": "integer default 0",
            "bloco_selecionado_origem": "text",
            "bloco_selecionado_destino": "text",
            "referencias_visitadas_origem": "text",
            "referencias_visitadas_destino": "text",
            "motivo_escolha_bloco_origem": "text",
            "motivo_escolha_bloco_destino": "text",
            "confianca_permanencia_origem_pct": "real",
            "confianca_permanencia_destino_pct": "real",
            "motivo_confirmacao_saida_origem": "text",
            "motivo_confirmacao_saida_destino": "text",
            "interrupcoes_ignoradas_origem": "integer default 0",
            "interrupcoes_ignoradas_destino": "integer default 0",
            "maior_distancia_temporaria_cerca_origem_km": "real",
            "maior_distancia_temporaria_cerca_destino_km": "real",
            "tempo_oscilacao_absorvido_origem_min": "real",
            "tempo_oscilacao_absorvido_destino_min": "real",
            "tempo_operacional_min": "real",
            "tempo_transito_min": "real",
            "tempo_total_viagem_min": "real",
            "tempo_control_min": "real",
            "tempo_rastreador_min": "real",
            "diferenca_control_rastreador_min": "real",
            "km_percorrido": "real",
            "distancia_ponto_carga_km": "real",
            "distancia_ponto_descarga_km": "real",
            "pontos_origem": "integer default 0",
            "pontos_destino": "integer default 0",
            "franquia_carga_min": "real",
            "franquia_descarga_min": "real",
            "estadia_carga_min": "real",
            "estadia_descarga_min": "real",
            "horas_estadia": "real",
            "elegivel_cobranca": "integer default 0",
            "motivo_nao_elegibilidade": "text",
            "horario_agendado_carga": "text",
            "horario_agendado_descarga": "text",
            "diferenca_agendamento_carga_min": "real",
            "diferenca_agendamento_descarga_min": "real",
            "dentro_limite_operacional": "integer default 1",
            "observacao_manual": "text",
            "valor_estimado_estadia": "real",
            "painel_atual": "text",
            "status_processamento": "text",
            "status_permanencia": "text",
            "status_estadia": "text",
            "status_verificacao": "text",
            "status_tratativa": "text",
            "status_retorno": "text",
            "status_cte": "text",
            "concluido": "integer default 0",
            "tratado": "integer default 0",
            "precisa_verificar": "integer default 0",
            "tipo_conclusao": "text",
            "observacao_conclusao": "text",
            "usuario_conclusao": "text",
            "data_hora_conclusao": "text",
            "data_limite_retorno": "text",
            "dias_restantes": "integer",
            "retorno_recebido": "integer default 0",
            "data_retorno": "text",
            "status_prazo": "text",
            "protocolo": "text",
            "valor_solicitado": "real",
            "valor_aprovado": "real",
            "codigo_motivo": "text",
            "descricao_motivo": "text",
            "motivo_falha": "text",
            "diagnostico_json": "text",
            "log_processamento_json": "text",
        },
    )
    ensure_columns(
        conn,
        "mod_estadias_locais_operacionais",
        {
            "nome_padrao": "text",
            "nome_norm": "text",
            "municipio": "text",
            "uf": "text",
            "razao_social": "text",
            "latitude": "real",
            "longitude": "real",
            "raio_metros": "real",
            "tipo_local": "text",
            "aliases": "text",
            "origem_cadastro": "text",
            "ativo": "integer default 1",
            "ultima_atualizacao": "text",
            "created_at": "text",
            "created_by": "text",
            "updated_at": "text",
            "updated_by": "text",
        },
    )
    ensure_columns(
        conn,
        "mod_estadias_parametros_cliente",
        {
            "cliente": "text",
            "cliente_norm": "text",
            "tipo_operacao": "text",
            "franquia_carga_horas": "real default 24",
            "franquia_descarga_horas": "real default 24",
            "inicio_contagem": "text",
            "regra_agendamento": "text",
            "valor_hora": "real default 0",
            "vigencia_inicial": "text",
            "vigencia_final": "text",
            "observacoes": "text",
            "ativo": "integer default 1",
            "created_at": "text",
            "created_by": "text",
            "updated_at": "text",
            "updated_by": "text",
        },
    )
    ensure_columns(
        conn,
        "mod_estadias_auditoria",
        {
            "data_hora": "text",
            "usuario": "text",
            "acao": "text",
            "chave_viagem": "text",
            "arquivo_origem": "text",
            "valor_anterior_json": "text",
            "valor_novo_json": "text",
            "observacao": "text",
            "detalhes_json": "text",
        },
    )
    for table in modular_tables():
        _create_index_if_column(conn, table, f"idx_{table}_data_hora", "data_hora")
        _create_index_if_column(conn, table, f"idx_{table}_data_hora_validacao", "data_hora_validacao")
        _create_index_if_column(conn, table, f"idx_{table}_lote_importacao", "lote_importacao")
        _create_index_if_column(conn, table, f"idx_{table}_lote_validacao", "lote_validacao")
    _create_index_if_columns(conn, "mod_estadias_rastreador_normalizada", "idx_estadias_rastreador_placa_data", ["placa_norm", "data_hora"])
    _create_index_if_columns(conn, "mod_estadias_lcte_normalizada", "idx_estadias_lcte_placa_data", ["placa_norm", "data_operacao"])
    _create_index_if_columns(conn, "mod_estadias_control_normalizada", "idx_estadias_control_placa_data", ["placa_norm", "data_hora_inicio"])


def initialize_modular_database() -> None:
    with get_connection() as conn:
        create_modular_tables(conn)


def import_log_payload(**kwargs: Any) -> dict[str, Any]:
    payload = {
        "data_hora": kwargs.get("data_hora") or "",
        "usuario": kwargs.get("usuario") or "",
        "tipo_importacao": kwargs.get("tipo_importacao") or "",
        "arquivo_origem": kwargs.get("arquivo_origem") or "",
        "hash_arquivo": kwargs.get("hash_arquivo") or "",
        "quantidade_linhas": int(kwargs.get("quantidade_linhas") or 0),
        "quantidade_registros_inseridos": int(kwargs.get("quantidade_registros_inseridos") or 0),
        "quantidade_registros_atualizados": int(kwargs.get("quantidade_registros_atualizados") or 0),
        "quantidade_registros_ignorados": int(kwargs.get("quantidade_registros_ignorados") or 0),
        "status": kwargs.get("status") or "",
        "mensagem": kwargs.get("mensagem") or "",
        "detalhes_json": json.dumps(kwargs.get("detalhes") or {}, ensure_ascii=False, default=_json_default),
        "lote_importacao": kwargs.get("lote_importacao") or "",
    }
    return payload
