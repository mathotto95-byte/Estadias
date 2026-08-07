from __future__ import annotations

from src.database.connection import get_connection
from src.normalizers.fields import to_datetime


BASE_TABLES = {
    "KMM / LCTE": "base_kmm_original",
    "KMM / LCTE / FAT": "base_kmm_original",
    "FAT_07_26": "base_fat_kmm_original",
    "NSDOCS": "base_nsdocs_original",
    "COUPA": "base_coupa_original",
    "PORTAL IPP": "base_portal_ipp_original",
    "CONTROL / VIAGENS": "base_control_viagens",
    "RASTREADOR": "base_rastreador",
    "KM ORIGEM DESTINO": "base_km_origem_destino",
}


COMMON_BASE_COLUMNS = """
    id integer primary key autoincrement,
    importacao_id integer,
    tipo_base text not null,
    arquivo_origem text,
    aba_origem text,
    data_importacao text,
    row_hash text not null,
    hash_registro text,
    key_hash text,
    original_json text not null,
    normalized_json text not null,
    status_registro text default 'ATIVO',
    numero_nf text,
    nota_fiscal text,
    chave_acesso text,
    cte_numero text,
    chave_cte text,
    chave_nfe text,
    transportador_cnpj text,
    emitente text,
    destinatario text,
    natureza_operacao text,
    cliente text,
    cobranca text,
    origem text,
    origem_normalizada text,
    uf_origem text,
    destino text,
    destino_normalizada text,
    uf_destino text,
    produto text,
    mercadoria text,
    placa text,
    motorista text,
    emissao_nf text,
    emissao_cte text,
    volume real,
    valor real,
    frete_unitario real,
    total_conhecimento real,
    peso_frete real,
    pedagio real,
    vale_pedagio real,
    pedagio_informado real,
    id_icms_st text,
    cfop text,
    base_icms real,
    valor_icms real,
    base_icms_st real,
    valor_icms_st real,
    complemento text,
    status_complemento_normalizado text,
    complemento_original text,
    observacao_original text,
    complemento_coluna_b_norm text,
    observacao_norm text,
    complemento_observacao_norm text,
    cte_complementar_norm text,
    motivo_identificacao_complemento text,
    status text,
    observacao text,
    inserido_por text,
    tabela_frete text,
    item text,
    qtd real,
    dt_inicio text,
    dt_termino text,
    distancia real,
    tipo_contratacao text,
    valor_bitrem real,
    valor_rodotrem real,
    resposta_transportador text,
    resposta_transportador_norm text,
    origem_coupa_tipo text,
    produto_normalizado text,
    dt_inicio_original text,
    dt_termino_original text,
    dt_inicio_dt text,
    dt_termino_dt text,
    mes_referencia_coupa text,
    origem_norm text,
    destino_norm text,
    produto_norm text,
    cliente_norm text,
    rota_norm text,
    tipo_contratacao_norm text,
    dt_inicio_formatada text,
    dt_termino_formatada text,
    data_emissao_original text,
    data_emissao_dt text,
    data_emissao_nf_original text,
    data_emissao_nf_dt text,
    mes_referencia text,
    origem_original text,
    destino_original text,
    produto_original text,
    tipo_contratacao_original text,
    resposta_transportador_original text,
    cliente_original text,
    operacao_original text,
    placa_original text,
    volume_original text,
    valor_kmm_original text,
    operacao_norm text,
    placa_norm text,
    volume_normalizado real,
    valor_kmm real,
    cte text,
    numero_original text,
    numero_norm text,
    nota_fiscal_norm text,
    vinculo text,
    canhoto text,
    pago text,
    vinculo_norm text,
    canhoto_norm text,
    pago_norm text,
    data_emissao_portal_original text,
    data_emissao_portal_dt text,
    valor_portal_original text,
    valor_portal real,
    coluna_origem_valor_portal text,
    nome_coluna_aw_portal text,
    indice_coluna_valor_portal integer,
    quantidade_colunas_portal integer,
    valor_portal_frete real,
    valor_portal_pedagio real,
    valor_portal_base_calculo real,
    valor_portal_imposto real,
    valor_portal_total real,
    valor_unitario_frete real,
    tipo_frete text,
    tipo_frete_norm text,
    nome_produto_portal text,
    arquivo text,
    viagem text,
    codigo text,
    pedido text,
    codigo_monitoramento text,
    codigo_oferta text,
    agendamento text,
    data_inicio text,
    data_carga text,
    data_descarga text,
    data_hora text,
    data_limite text,
    cidade_uf text,
    latitude real,
    longitude real,
    referencia text,
    permanencia real,
    km real,
    tipo_operacao text,
    tipo_base_origem text,
    lote_importacao text,
    unique(tipo_base, row_hash)
"""


def create_base_table_sql(table: str) -> str:
    return f"create table if not exists {table} ({COMMON_BASE_COLUMNS})"


def create_ots_otd_table(conn) -> None:
    conn.execute(
        adapt_sql(
            conn,
            """
            create table if not exists ots_otd_registros (
                id integer primary key autoincrement,
                previsao_carga text not null,
                data_limite text not null,
                agendamento_carga text not null,
                agenda_gfl text not null,
                codigo_monitoramento text not null,
                tipo_registro text not null,
                data_hora_registro text not null,
                usuario_registro text not null,
                registro_origem_id integer,
                dados_alterados text,
                created_at text,
                updated_at text
            )
            """,
        )
    )
    ensure_columns(
        conn,
        "ots_otd_registros",
        {
            "previsao_carga": "text",
            "data_limite": "text",
            "agendamento_carga": "text",
            "agenda_gfl": "text",
            "codigo_monitoramento": "text",
            "tipo_registro": "text",
            "data_hora_registro": "text",
            "usuario_registro": "text",
            "registro_origem_id": "integer",
            "dados_alterados": "text",
            "created_at": "text",
            "updated_at": "text",
        },
    )
    conn.execute("create index if not exists idx_ots_otd_codigo on ots_otd_registros(codigo_monitoramento)")
    conn.execute("create index if not exists idx_ots_otd_data on ots_otd_registros(data_hora_registro desc)")
    conn.execute("create index if not exists idx_ots_otd_status on ots_otd_registros(tipo_registro)")
    conn.execute(
        """
        create unique index if not exists ux_ots_otd_original_codigo
        on ots_otd_registros(codigo_monitoramento)
        where tipo_registro = 'ORIGINAL'
        """
    )


def database_type(conn) -> str:
    return getattr(conn, "db_type", "sqlite")


def adapt_sql(conn, sql: str) -> str:
    if database_type(conn) != "postgres":
        return sql
    return (
        sql.replace("integer primary key autoincrement", "serial primary key")
        .replace("original_json text not null", "original_json jsonb not null")
        .replace("normalized_json text not null", "normalized_json jsonb not null")
    )


def ensure_columns(conn, table: str, columns: dict[str, str]) -> None:
    if database_type(conn) == "postgres":
        existing = {
            row["column_name"]
            for row in conn.execute(
                """
                select column_name
                from information_schema.columns
                where table_schema = 'public' and table_name = ?
                """,
                (table,),
            ).fetchall()
        }
    else:
        existing = {
            row["name"]
            for row in conn.execute(f"pragma table_info({table})").fetchall()
        }
    for name, definition in columns.items():
        if name not in existing:
            try:
                conn.execute(adapt_sql(conn, f"alter table {table} add column {name} {definition}"))
            except Exception as exc:
                message = str(exc).lower()
                if "duplicate column" not in message and "already exists" not in message:
                    raise


def initialize_database() -> None:
    with get_connection() as conn:
        conn.execute(
            adapt_sql(conn, """
            create table if not exists importacoes (
                id integer primary key autoincrement,
                nome_arquivo text not null,
                tipo_base text not null,
                aba_importada text,
                data_importacao text not null,
                linhas_lidas integer default 0,
                linhas_novas integer default 0,
                linhas_atualizadas integer default 0,
                linhas_duplicadas integer default 0,
                linhas_erro integer default 0,
                status text not null,
                mensagem_erro text,
                usuario text,
                perfil_usuario text
            )
            """)
        )
        ensure_columns(
            conn,
            "importacoes",
            {
                "usuario": "text",
                "perfil_usuario": "text",
                "linhas_atualizadas": "integer default 0",
            },
        )
        for table in BASE_TABLES.values():
            conn.execute(adapt_sql(conn, create_base_table_sql(table)))
            ensure_columns(
                conn,
                table,
                {
                    "codigo_oferta": "text",
                    "data_carga": "text",
                    "data_descarga": "text",
                    "referencia": "text",
                    "permanencia": "real",
                    "km": "real",
                    "tipo_operacao": "text",
                    "tipo_base_origem": "text",
                    "lote_importacao": "text",
                    "status": "text",
                    "hash_registro": "text",
                    "origem_normalizada": "text",
                    "destino_normalizada": "text",
                    "status_registro": "text default 'ATIVO'",
                    "natureza_operacao": "text",
                    "pedagio_informado": "real",
                    "resposta_transportador_norm": "text",
                    "origem_coupa_tipo": "text",
                    "produto_normalizado": "text",
                    "dt_inicio_original": "text",
                    "dt_termino_original": "text",
                    "dt_inicio_dt": "text",
                    "dt_termino_dt": "text",
                    "mes_referencia_coupa": "text",
                    "origem_norm": "text",
                    "destino_norm": "text",
                    "produto_norm": "text",
                    "cliente_norm": "text",
                    "rota_norm": "text",
                    "tipo_contratacao_norm": "text",
                    "dt_inicio_formatada": "text",
                    "dt_termino_formatada": "text",
                    "data_emissao_original": "text",
                    "data_emissao_dt": "text",
                    "data_emissao_nf_original": "text",
                    "data_emissao_nf_dt": "text",
                    "mes_referencia": "text",
                    "origem_original": "text",
                    "destino_original": "text",
                    "produto_original": "text",
                    "tipo_contratacao_original": "text",
                    "resposta_transportador_original": "text",
                    "cliente_original": "text",
                    "operacao_original": "text",
                    "placa_original": "text",
                    "volume_original": "text",
                    "valor_kmm_original": "text",
                    "complemento_original": "text",
                    "observacao_original": "text",
                    "complemento_coluna_b_norm": "text",
                    "observacao_norm": "text",
                    "complemento_observacao_norm": "text",
                    "cte_complementar_norm": "text",
                    "motivo_identificacao_complemento": "text",
                    "operacao_norm": "text",
                    "placa_norm": "text",
                    "volume_normalizado": "real",
                    "valor_kmm": "real",
                    "cte": "text",
                    "numero_original": "text",
                    "numero_norm": "text",
                    "nota_fiscal_norm": "text",
                    "vinculo": "text",
                    "canhoto": "text",
                    "pago": "text",
                    "vinculo_norm": "text",
                    "canhoto_norm": "text",
                    "pago_norm": "text",
                    "data_emissao_portal_original": "text",
                    "data_emissao_portal_dt": "text",
                    "valor_portal_original": "text",
                    "valor_portal": "real",
                    "coluna_origem_valor_portal": "text",
                    "nome_coluna_aw_portal": "text",
                    "indice_coluna_valor_portal": "integer",
                    "quantidade_colunas_portal": "integer",
                    "valor_portal_frete": "real",
                    "valor_portal_pedagio": "real",
                    "valor_portal_base_calculo": "real",
                    "valor_portal_imposto": "real",
                    "valor_portal_total": "real",
                    "valor_unitario_frete": "real",
                    "tipo_frete": "text",
                    "tipo_frete_norm": "text",
                    "nome_produto_portal": "text",
                    "created_at": "text",
                    "updated_at": "text",
                    "source_file": "text",
                    "import_batch_id": "integer",
                    "sync_status": "text default 'SINCRONIZADO'",
                    "last_synced_at": "text",
                },
            )
            conn.execute(f"create index if not exists idx_{table}_nf on {table}(nota_fiscal)")
            conn.execute(f"create index if not exists idx_{table}_cte on {table}(cte_numero)")
            conn.execute(f"create index if not exists idx_{table}_key on {table}(key_hash)")

        conn.execute(
            adapt_sql(conn, """
            create table if not exists arquivos_importados (
                id integer primary key autoincrement,
                importacao_id integer,
                nome_arquivo text not null,
                tipo_base text,
                caminho_armazenado text,
                data_importacao text,
                usuario text,
                status text,
                hash_arquivo text
            )
            """)
        )
        conn.execute("create index if not exists idx_arquivos_importados_importacao on arquivos_importados(importacao_id)")

        conn.execute(
            adapt_sql(conn, """
            create table if not exists base_kmm_notas_normalizadas (
                id integer primary key autoincrement,
                kmm_original_id integer not null,
                importacao_id integer,
                cte_numero text,
                nota_fiscal text,
                nota_fiscal_normalizada text,
                chave_cte text,
                chave_nfe text,
                emissao_nf text,
                emissao_cte text,
                situacao text,
                complemento text,
                status_complemento_normalizado text,
                placa text,
                motorista text,
                cliente text,
                cobranca text,
                municipio_cobranca text,
                uf_origem text,
                origem text,
                uf_destino text,
                destino text,
                mercadoria text,
                volume real,
                valor real,
                frete_unitario real,
                total_conhecimento real,
                peso_frete real,
                pedagio real,
                vale_pedagio real,
                pedagio_informado real,
                id_icms_st text,
                cfop text,
                base_icms real,
                valor_icms real,
                base_icms_st real,
                valor_icms_st real,
                inserido_por text,
                tabela_frete text,
                arquivo_origem text,
                data_importacao text,
                status_registro text default 'ATIVO',
                unique(kmm_original_id, nota_fiscal_normalizada)
            )
            """)
        )
        ensure_columns(
            conn,
            "base_kmm_notas_normalizadas",
            {
                "status_registro": "text default 'ATIVO'",
                "cliente": "text",
                "valor": "real",
                "pedagio_informado": "real",
            },
        )
        conn.execute(
            adapt_sql(conn, """
            create table if not exists base_kmm_fat_notas_normalizadas (
                id integer primary key autoincrement,
                base_original_id integer not null,
                importacao_id integer,
                tipo_base text,
                data_emissao text,
                data_emissao_dt text,
                cte text,
                cte_numero text,
                nota_fiscal_original text,
                nota_fiscal_individual text,
                nota_fiscal_norm text,
                total_conhecimento real,
                peso_frete real,
                valor_faturado_kmm real,
                frete_unitario real,
                volume real,
                volume_normalizado real,
                mercadoria text,
                produto text,
                produto_norm text,
                origem text,
                destino text,
                origem_norm text,
                destino_norm text,
                municipio_remetente text,
                municipio_destinatario text,
                placa text,
                placa_norm text,
                base_icms real,
                valor_icms real,
                tabela_frete text,
                operacao_norm text,
                arquivo_origem text,
                data_importacao text,
                status_registro text default 'ATIVO',
                signature text unique
            )
            """)
        )
        ensure_columns(
            conn,
            "base_kmm_fat_notas_normalizadas",
            {
                "tipo_base": "text",
                "data_emissao": "text",
                "data_emissao_dt": "text",
                "cte": "text",
                "valor_faturado_kmm": "real",
                "produto_norm": "text",
                "origem_norm": "text",
                "destino_norm": "text",
                "municipio_remetente": "text",
                "municipio_destinatario": "text",
                "placa_norm": "text",
                "operacao_norm": "text",
                "complemento_original": "text",
                "observacao_original": "text",
                "complemento_coluna_b_norm": "text",
                "observacao_norm": "text",
                "complemento_observacao_norm": "text",
                "cte_complementar_norm": "text",
                "motivo_identificacao_complemento": "text",
                "chave_nfe": "text",
                "status_registro": "text default 'ATIVO'",
                "signature": "text",
            },
        )
        conn.execute("create index if not exists idx_kmm_fat_nf_norm on base_kmm_fat_notas_normalizadas(nota_fiscal_norm)")
        conn.execute("create index if not exists idx_kmm_fat_cte on base_kmm_fat_notas_normalizadas(cte)")

        conn.execute(
            adapt_sql(conn, """
            create table if not exists base_kmm_faturamento_consolidado (
                id integer primary key autoincrement,
                chave_faturamento_coupa text,
                nota_fiscal_norm text,
                nota_fiscal text,
                nf_original text,
                chave_nfe text,
                cte text,
                cte_numero text,
                cte_normal text,
                ctes_complementares text,
                ctes_todos text,
                cliente text,
                cobranca text,
                cliente_norm text,
                razao_social_cobranca text,
                razao_social_cobranca_norm text,
                cliente_equivalente text,
                cliente_equivalente_norm text,
                placa text,
                motorista text,
                origem text,
                destino text,
                origem_norm text,
                destino_norm text,
                municipio_remetente text,
                municipio_destinatario text,
                produto text,
                mercadoria text,
                produto_norm text,
                operacao text,
                operacao_norm text,
                data_emissao_nf text,
                data_emissao text,
                data_emissao_dt text,
                data_emissao_cte_normal text,
                data_primeiro_cte text,
                data_ultimo_cte text,
                emissao_cte text,
                valor_cte_normal real,
                valor_cte_complementar real,
                valor_faturado_total_kmm real,
                valor real,
                valor_kmm real,
                valor_faturado_kmm real,
                peso_frete real,
                peso_frete_normal real,
                peso_frete_complementar real,
                peso_frete_total real,
                total_conhecimento real,
                total_conhec_normal real,
                total_conhec_complementar real,
                total_conhec_total real,
                frete_unitario real,
                volume real,
                volume_normalizado real,
                tem_complemento text,
                quantidade_complementos integer,
                status_complemento_cte text,
                status_complemento_normalizado text,
                complemento text,
                observacao text,
                complemento_original text,
                observacao_original text,
                complemento_coluna_b_norm text,
                observacao_norm text,
                complemento_observacao_norm text,
                cte_complementar_norm text,
                motivo_identificacao_complemento text,
                arquivo_origem text,
                lote_importacao text,
                tipo_base text,
                source_table text,
                source_ids text,
                signature text unique,
                status_registro text default 'ATIVO'
            )
            """)
        )
        ensure_columns(
            conn,
            "base_kmm_faturamento_consolidado",
            {
                "chave_faturamento_coupa": "text",
                "nota_fiscal_norm": "text",
                "nota_fiscal": "text",
                "nf_original": "text",
                "chave_nfe": "text",
                "cte": "text",
                "cte_numero": "text",
                "cte_normal": "text",
                "ctes_complementares": "text",
                "ctes_todos": "text",
                "cliente": "text",
                "cobranca": "text",
                "cliente_norm": "text",
                "razao_social_cobranca": "text",
                "razao_social_cobranca_norm": "text",
                "cliente_equivalente": "text",
                "cliente_equivalente_norm": "text",
                "placa": "text",
                "motorista": "text",
                "origem": "text",
                "destino": "text",
                "origem_norm": "text",
                "destino_norm": "text",
                "municipio_remetente": "text",
                "municipio_destinatario": "text",
                "produto": "text",
                "mercadoria": "text",
                "produto_norm": "text",
                "operacao": "text",
                "operacao_norm": "text",
                "data_emissao_nf": "text",
                "data_emissao": "text",
                "data_emissao_dt": "text",
                "data_emissao_cte_normal": "text",
                "data_primeiro_cte": "text",
                "data_ultimo_cte": "text",
                "emissao_cte": "text",
                "valor_cte_normal": "real",
                "valor_cte_complementar": "real",
                "valor_faturado_total_kmm": "real",
                "valor": "real",
                "valor_kmm": "real",
                "valor_faturado_kmm": "real",
                "peso_frete": "real",
                "peso_frete_normal": "real",
                "peso_frete_complementar": "real",
                "peso_frete_total": "real",
                "total_conhecimento": "real",
                "total_conhec_normal": "real",
                "total_conhec_complementar": "real",
                "total_conhec_total": "real",
                "frete_unitario": "real",
                "volume": "real",
                "volume_normalizado": "real",
                "tem_complemento": "text",
                "quantidade_complementos": "integer",
                "status_complemento_cte": "text",
                "status_complemento_normalizado": "text",
                "complemento": "text",
                "observacao": "text",
                "complemento_original": "text",
                "observacao_original": "text",
                "complemento_coluna_b_norm": "text",
                "observacao_norm": "text",
                "complemento_observacao_norm": "text",
                "cte_complementar_norm": "text",
                "motivo_identificacao_complemento": "text",
                "arquivo_origem": "text",
                "lote_importacao": "text",
                "tipo_base": "text",
                "source_table": "text",
                "source_ids": "text",
                "signature": "text",
                "status_registro": "text default 'ATIVO'",
            },
        )
        conn.execute("create index if not exists idx_kmm_fat_cons_nf on base_kmm_faturamento_consolidado(nota_fiscal_norm)")
        conn.execute("create index if not exists idx_kmm_fat_cons_cte on base_kmm_faturamento_consolidado(cte)")
        conn.execute("create index if not exists idx_kmm_fat_cons_key on base_kmm_faturamento_consolidado(chave_faturamento_coupa)")

        conn.execute(
            adapt_sql(conn, """
            create table if not exists base_portal_ipp_normalizada (
                id integer primary key autoincrement,
                portal_original_id integer not null,
                importacao_id integer,
                numero_original text,
                numero_norm text,
                nota_fiscal_norm text,
                data_emissao_portal_dt text,
                vinculo text,
                canhoto text,
                pago text,
                vinculo_norm text,
                canhoto_norm text,
                pago_norm text,
                valor_portal_original text,
                valor_portal real,
                coluna_origem_valor_portal text,
                nome_coluna_aw_portal text,
                indice_coluna_valor_portal integer,
                quantidade_colunas_portal integer,
                valor_portal_frete real,
                valor_portal_pedagio real,
                valor_portal_base_calculo real,
                valor_portal_imposto real,
                valor_portal_total real,
                valor_unitario_frete real,
                tipo_frete text,
                tipo_frete_norm text,
                produto text,
                produto_norm text,
                quantidade real,
                arquivo_origem text,
                data_importacao text,
                status_registro text default 'ATIVO',
                signature text unique
            )
            """)
        )
        ensure_columns(
            conn,
            "base_portal_ipp_normalizada",
            {
                "nota_fiscal_norm": "text",
                "data_emissao_portal_dt": "text",
                "valor_portal_original": "text",
                "valor_portal": "real",
                "coluna_origem_valor_portal": "text",
                "nome_coluna_aw_portal": "text",
                "indice_coluna_valor_portal": "integer",
                "quantidade_colunas_portal": "integer",
                "valor_portal_total": "real",
                "valor_unitario_frete": "real",
                "tipo_frete_norm": "text",
                "produto_norm": "text",
                "quantidade": "real",
                "status_registro": "text default 'ATIVO'",
                "signature": "text",
            },
        )
        conn.execute("create index if not exists idx_portal_ipp_numero_norm on base_portal_ipp_normalizada(numero_norm)")
        conn.execute(
            adapt_sql(conn, """
            create table if not exists base_vale_pedagio_rota_eixo (
                id integer primary key autoincrement,
                origem text not null,
                destino text not null,
                origem_normalizada text not null,
                destino_normalizada text not null,
                quantidade_eixos real not null,
                valor_por_eixo real,
                valor_total_atualizado real,
                km_rota real,
                mes_referencia text not null,
                observacao text,
                arquivo_origem text,
                data_importacao text,
                usuario_importacao text,
                status text default 'VALOR ATUALIZADO',
                signature text unique
            )
            """)
        )
        ensure_columns(
            conn,
            "base_vale_pedagio_rota_eixo",
            {
                "valor_por_eixo": "real",
                "valor_total_atualizado": "real",
                "km_rota": "real",
                "observacao": "text",
                "arquivo_origem": "text",
                "data_importacao": "text",
                "usuario_importacao": "text",
                "status": "text default 'VALOR ATUALIZADO'",
                "signature": "text",
            },
        )
        conn.execute(
            adapt_sql(conn, """
            create table if not exists historico_vale_pedagio_rota_eixo (
                id integer primary key autoincrement,
                vale_pedagio_id integer,
                origem text,
                destino text,
                quantidade_eixos real,
                mes_referencia text,
                valor_por_eixo_anterior real,
                valor_total_anterior real,
                valor_por_eixo_novo real,
                valor_total_novo real,
                observacao text,
                arquivo_origem text,
                data_alteracao text,
                usuario_importacao text,
                tipo_atualizacao text,
                signature text
            )
            """)
        )
        conn.execute(
            adapt_sql(conn, """
            create table if not exists base_coupa_fluxos_normalizados (
                id integer primary key autoincrement,
                coupa_original_id integer not null,
                importacao_id integer,
                item text,
                qtd real,
                dt_inicio text,
                dt_termino text,
                origem text,
                destino text,
                distancia real,
                tipo_contratacao text,
                produto text,
                valor_bitrem real,
                valor_rodotrem real,
                resposta_transportador text,
                resposta_transportador_norm text,
                origem_coupa_tipo text,
                produto_normalizado text,
                dt_inicio_original text,
                dt_termino_original text,
                dt_inicio_dt text,
                dt_termino_dt text,
                dt_inicio_formatada text,
                dt_termino_formatada text,
                mes_referencia_coupa text,
                origem_norm text,
                destino_norm text,
                produto_norm text,
                tipo_contratacao_norm text,
                rota_norm text,
                arquivo text,
                reajuste text,
                arquivo_origem text,
                data_importacao text,
                status_registro text default 'ATIVO'
            )
            """)
        )
        ensure_columns(
            conn,
            "base_coupa_fluxos_normalizados",
            {
                "status_registro": "text default 'ATIVO'",
                "resposta_transportador_norm": "text",
                "origem_coupa_tipo": "text",
                "produto_normalizado": "text",
                "dt_inicio_original": "text",
                "dt_termino_original": "text",
                "dt_inicio_dt": "text",
                "dt_termino_dt": "text",
                "dt_inicio_formatada": "text",
                "dt_termino_formatada": "text",
                "mes_referencia_coupa": "text",
                "origem_norm": "text",
                "destino_norm": "text",
                "produto_norm": "text",
                "tipo_contratacao_norm": "text",
                "rota_norm": "text",
            },
        )
        for table in ["base_coupa_original"]:
            ensure_columns(
                conn,
                table,
                {
                    "resposta_transportador_norm": "text",
                    "origem_coupa_tipo": "text",
                    "produto_normalizado": "text",
                    "dt_inicio_original": "text",
                    "dt_termino_original": "text",
                    "dt_inicio_dt": "text",
                    "dt_termino_dt": "text",
                    "mes_referencia_coupa": "text",
                    "origem_norm": "text",
                    "destino_norm": "text",
                    "produto_norm": "text",
                    "cliente_norm": "text",
                    "rota_norm": "text",
                    "tipo_contratacao_norm": "text",
                },
            )
        conn.execute(
            adapt_sql(conn, """
            create table if not exists de_para_origem_coupa_kmm (
                id integer primary key autoincrement,
                origem_coupa_original text,
                origem_coupa_norm text,
                origem_kmm_equivalente text,
                origem_kmm_norm text,
                observacao text,
                ativo text default 'SIM',
                usuario_cadastro text,
                data_cadastro text,
                signature text unique
            )
            """)
        )
        conn.execute(
            adapt_sql(conn, """
            create table if not exists de_para_coupa_fat (
                id integer primary key autoincrement,
                campo text,
                valor_coupa_original text,
                valor_coupa_norm text,
                valor_fat_original text,
                valor_fat_norm text,
                ativo text default 'SIM',
                observacao text,
                usuario_cadastro text,
                data_cadastro text,
                signature text unique
            )
            """)
        )
        ensure_columns(
            conn,
            "de_para_coupa_fat",
            {
                "campo": "text",
                "valor_coupa_original": "text",
                "valor_coupa_norm": "text",
                "valor_fat_original": "text",
                "valor_fat_norm": "text",
                "ativo": "text default 'SIM'",
                "observacao": "text",
                "usuario_cadastro": "text",
                "data_cadastro": "text",
                "signature": "text",
            },
        )
        conn.execute("create index if not exists idx_depara_coupa_fat_campo on de_para_coupa_fat(campo, valor_coupa_norm)")
        conn.execute(
            adapt_sql(conn, """
            create table if not exists de_para_produto_coupa_kmm (
                id integer primary key autoincrement,
                produto_original text,
                produto_norm text,
                produto_mapeado text,
                ativo text default 'SIM',
                usuario text,
                data_cadastro text,
                signature text unique
            )
            """)
        )
        ensure_columns(
            conn,
            "de_para_produto_coupa_kmm",
            {
                "produto_original": "text",
                "produto_norm": "text",
                "produto_mapeado": "text",
                "ativo": "text default 'SIM'",
                "usuario": "text",
                "data_cadastro": "text",
                "signature": "text",
            },
        )
        conn.execute("create index if not exists idx_depara_produto_coupa_kmm_norm on de_para_produto_coupa_kmm(produto_norm)")
        ensure_columns(
            conn,
            "de_para_origem_coupa_kmm",
            {
                "origem_coupa_original": "text",
                "origem_coupa_norm": "text",
                "origem_kmm_equivalente": "text",
                "origem_kmm_norm": "text",
                "observacao": "text",
                "ativo": "text default 'SIM'",
                "usuario_cadastro": "text",
                "data_cadastro": "text",
                "signature": "text",
            },
        )
        conn.execute(
            adapt_sql(conn, """
            create table if not exists conferencia_notas_sem_cte (
                id integer primary key autoincrement,
                nf text not null,
                chave_acesso text,
                emitente text,
                destinatario text,
                emissao_nf text,
                volume_nf real,
                status_original text,
                conferida text default 'NAO',
                justificativa text,
                responsavel text,
                usuario_logado text,
                data_hora_conferencia text,
                arquivo_origem text,
                data_importacao text,
                signature text unique
            )
            """)
        )
        ensure_columns(
            conn,
            "conferencia_notas_sem_cte",
            {
                "chave_acesso": "text",
                "emitente": "text",
                "destinatario": "text",
                "emissao_nf": "text",
                "volume_nf": "real",
                "status_original": "text",
                "conferida": "text default 'NAO'",
                "justificativa": "text",
                "responsavel": "text",
                "usuario_logado": "text",
                "data_hora_conferencia": "text",
                "arquivo_origem": "text",
                "data_importacao": "text",
                "signature": "text",
            },
        )
        conn.execute(
            adapt_sql(conn, """
            create table if not exists historico_conferencia_notas_sem_cte (
                id integer primary key autoincrement,
                conferencia_id integer,
                nf text,
                chave_acesso text,
                justificativa_anterior text,
                justificativa_nova text,
                responsavel text,
                data_hora_alteracao text,
                arquivo_origem text,
                signature text
            )
            """)
        )
        create_analysis_tables(conn)
        normalize_tempo_nf_cte_existing_rows(conn)


IPIRANGA_TABLES = [
    "base_fretes_ipp_original",
    "base_fretes_ipp_notas_normalizadas",
    "base_portal26_original",
    "base_bases_ipp",
    "analise_ipiranga_fretes_portal26",
    "conferencia_ipiranga_fretes",
    "historico_ipiranga_fretes",
    "geracao_lancamento_frete_logs",
    "painel_ipiranga_logs",
    "modelo_lancamento_frete_mapeamento",
    "historico_notas_portal26",
    "controle_tarefas_ipiranga",
    "historico_tarefas_ipiranga",
]


def classify_tempo_nf_cte_minutes(minutes: float | None) -> str:
    if minutes is None:
        return ""
    if minutes < 10:
        return "Excelente"
    if minutes <= 30:
        return "No prazo"
    if minutes <= 60:
        return "Prazo 2"
    return "Verificar"


def normalize_tempo_nf_cte_existing_rows(conn) -> None:
    try:
        rows = conn.execute(
            """
            select id, minutos, emissao_nf, emissao_cte, uf_origem, faixa_tempo, status_prazo
            from analise_tempo_nf_cte
            """
        ).fetchall()
    except Exception:
        return
    for row in rows:
        parsed_nf = to_datetime(row["emissao_nf"])
        parsed_cte = to_datetime(row["emissao_cte"])
        uf_origem = str(row["uf_origem"] or "").strip().upper()
        ajuste_aplicado = "Sim" if parsed_nf and uf_origem in {"MT", "MS"} else "Nao"
        minutos_ajuste = 60 if ajuste_aplicado == "Sim" else 0
        motivo_ajuste = "UF origem MT/MS - conversao para horario de Brasilia" if ajuste_aplicado == "Sim" else ""
        nf_ajustada = parsed_nf
        if parsed_nf and ajuste_aplicado == "Sim":
            from datetime import timedelta

            nf_ajustada = parsed_nf + timedelta(minutes=60)
        tempo_original = (parsed_cte - parsed_nf).total_seconds() / 60 if parsed_nf and parsed_cte else None
        tempo_ajustado = (parsed_cte - nf_ajustada).total_seconds() / 60 if parsed_cte and nf_ajustada else tempo_original
        status = ""
        try:
            status = classify_tempo_nf_cte_minutes(float(tempo_ajustado))
        except (TypeError, ValueError):
            pass
        faixa_tempo = status or row["faixa_tempo"]
        status_prazo = status or row["status_prazo"]
        data_nf = parsed_nf.date().isoformat() if parsed_nf else ""
        hora_nf = parsed_nf.strftime("%H:%M:%S") if parsed_nf else ""
        horario_valido = "SIM" if parsed_nf and hora_nf != "00:00:00" else "NAO"
        conn.execute(
            """
            update analise_tempo_nf_cte
            set faixa_tempo = ?,
                status_prazo = ?,
                data_emissao_nf_original = ?,
                data_emissao_nf_ajustada = ?,
                ajuste_fuso_aplicado = ?,
                minutos_ajuste_fuso = ?,
                motivo_ajuste_fuso = ?,
                tempo_original_minutos = ?,
                tempo_ajustado_minutos = ?,
                data_emissao_nf = ?,
                hora_emissao_nf = ?,
                emissao_nf_tem_horario_valido = ?
            where id = ?
            """,
            (
                faixa_tempo,
                status_prazo,
                row["emissao_nf"],
                nf_ajustada.isoformat(timespec="seconds") if nf_ajustada else "",
                ajuste_aplicado,
                minutos_ajuste,
                motivo_ajuste,
                tempo_original,
                tempo_ajustado,
                data_nf,
                hora_nf,
                horario_valido,
                row["id"],
            ),
        )


def create_ipiranga_tables(conn) -> None:
    conn.execute(
        adapt_sql(conn, """
        create table if not exists base_fretes_ipp_original (
            id integer primary key autoincrement,
            data_emissao text,
            cte text,
            notas_fiscais text,
            total_conhec real,
            operacao text,
            municipio_remetente text,
            municipio_destinatario text,
            placa_tracao text,
            cnpj_cpf_remetente text,
            mercadoria text,
            volume real,
            volume_normalizado real,
            frete_unitario real,
            peso_frete real,
            base_calc_icms real,
            valor_icms real,
            original_json text,
            arquivo_origem text,
            data_importacao text,
            usuario_importacao text,
            hash_registro text,
            signature text unique
        )
        """)
    )
    ensure_columns(
        conn,
        "base_fretes_ipp_original",
        {
            "volume_normalizado": "real",
            "original_json": "text",
            "usuario_importacao": "text",
            "hash_registro": "text",
            "signature": "text",
        },
    )
    conn.execute(
        adapt_sql(conn, """
        create table if not exists base_fretes_ipp_notas_normalizadas (
            id integer primary key autoincrement,
            frete_original_id integer,
            data_emissao text,
            cte text,
            nota_fiscal_original text,
            nota_fiscal_individual text,
            nota_fiscal_norm text,
            total_conhec real,
            operacao text,
            municipio_remetente text,
            municipio_destinatario text,
            municipio_destinatario_norm text,
            placa_tracao text,
            cnpj_cpf_remetente text,
            mercadoria text,
            volume real,
            volume_normalizado real,
            frete_unitario real,
            peso_frete real,
            base_calc_icms real,
            valor_icms real,
            arquivo_origem text,
            data_importacao text,
            usuario_importacao text,
            hash_registro text,
            signature text unique
        )
        """)
    )
    ensure_columns(
        conn,
        "base_fretes_ipp_notas_normalizadas",
        {
            "nota_fiscal_norm": "text",
        },
    )
    try:
        conn.execute(
            """
            update base_fretes_ipp_notas_normalizadas
            set nota_fiscal_norm = nota_fiscal_individual
            where coalesce(nota_fiscal_norm, '') = ''
            """
        )
    except Exception:
        pass
    conn.execute(
        adapt_sql(conn, """
        create table if not exists base_portal26_original (
            id integer primary key autoincrement,
            numero_original text,
            numero_norm text,
            nota_fiscal_norm text,
            nota_fiscal text,
            nota_fiscal_normalizada text,
            vinculo text,
            canhoto text,
            pago text,
            vinculo_norm text,
            canhoto_norm text,
            pago_norm text,
            original_json text,
            arquivo_origem text,
            data_importacao text,
            usuario_importacao text,
            hash_registro text,
            signature text unique
        )
        """)
    )
    ensure_columns(
        conn,
        "base_portal26_original",
        {
            "numero_original": "text",
            "numero_norm": "text",
            "nota_fiscal_norm": "text",
            "nota_fiscal": "text",
            "nota_fiscal_normalizada": "text",
            "vinculo": "text",
            "canhoto": "text",
            "pago": "text",
            "vinculo_norm": "text",
            "canhoto_norm": "text",
            "pago_norm": "text",
        },
    )
    try:
        conn.execute(
            """
            update base_portal26_original
            set numero_original = coalesce(numero_original, nota_fiscal),
                numero_norm = coalesce(nullif(numero_norm, ''), nota_fiscal_normalizada),
                nota_fiscal_norm = coalesce(nullif(nota_fiscal_norm, ''), nota_fiscal_normalizada)
            """
        )
    except Exception:
        pass
    conn.execute(
        adapt_sql(conn, """
        create table if not exists base_bases_ipp (
            id integer primary key autoincrement,
            base_original text,
            base_norm text,
            municipio_norm text,
            codigo_custo_frete text,
            codigo_custo_tribut text,
            codigo_principal text,
            original_json text,
            arquivo_origem text,
            data_importacao text,
            usuario_importacao text,
            hash_registro text,
            signature text unique
        )
        """)
    )
    conn.execute(
        adapt_sql(conn, """
        create table if not exists analise_ipiranga_fretes_portal26 (
            id integer primary key autoincrement,
            data text,
            cte text,
            nota_fiscal text,
            valor real,
            operacao text,
            municipio_remetente text,
            municipio_destinatario text,
            municipio_destinatario_norm text,
            placa text,
            cnpj_cpf_remetente text,
            mercadoria text,
            volume real,
            volume_normalizado real,
            frete_unitario real,
            peso_frete real,
            base_calc_icms real,
            valor_icms real,
            vinculo text,
            canhoto text,
            pago text,
            vinculo_norm text,
            canhoto_norm text,
            pago_norm text,
            status text,
            status_cte text,
            codigo_custo_frete text,
            codigo_custo_tribut text,
            base_ipp_encontrada text,
            flag_conferido text default 'NAO',
            justificativa text,
            usuario_conferencia text,
            data_hora_conferencia text,
            arquivo_origem text,
            data_processamento text,
            hash_registro text,
            signature text unique
        )
        """)
    )
    ensure_columns(
        conn,
        "analise_ipiranga_fretes_portal26",
        {
            "cnpj_cpf_remetente": "text",
            "mercadoria": "text",
            "volume": "real",
            "volume_normalizado": "real",
            "frete_unitario": "real",
            "peso_frete": "real",
            "base_calc_icms": "real",
            "valor_icms": "real",
        },
    )
    conn.execute(
        adapt_sql(conn, """
        create table if not exists conferencia_ipiranga_fretes (
            id integer primary key autoincrement,
            signature text unique,
            cte text,
            nota_fiscal text,
            status text,
            flag_conferido text default 'NAO',
            justificativa text,
            usuario_conferencia text,
            data_hora_conferencia text,
            origem_tela text
        )
        """)
    )
    conn.execute(
        adapt_sql(conn, """
        create table if not exists historico_ipiranga_fretes (
            id integer primary key autoincrement,
            signature text,
            cte text,
            nota_fiscal text,
            acao text,
            valor_anterior text,
            valor_novo text,
            justificativa text,
            usuario text,
            data_hora text,
            origem_tela text
        )
        """)
    )
    conn.execute(
        adapt_sql(conn, """
        create table if not exists geracao_lancamento_frete_logs (
            id integer primary key autoincrement,
            data_hora text,
            usuario text,
            ctes text,
            status text,
            registros_processados integer default 0,
            registros_gerados integer default 0,
            mensagem_erro text,
            duracao_segundos real,
            arquivo_gerado text,
            signature text unique
        )
        """)
    )
    conn.execute(
        adapt_sql(conn, """
        create table if not exists painel_ipiranga_logs (
            id integer primary key autoincrement,
            data_hora text,
            usuario text,
            acao text,
            etapa text,
            status text,
            registros_processados integer default 0,
            registros_gerados integer default 0,
            mensagem_erro text,
            duracao_segundos real,
            signature text unique
        )
        """)
    )
    conn.execute(
        adapt_sql(conn, """
        create table if not exists modelo_lancamento_frete_mapeamento (
            id integer primary key autoincrement,
            nome_campo text unique,
            celula_modelo text,
            origem_dado text,
            obrigatorio text default 'SIM',
            observacao text,
            signature text unique
        )
        """)
    )
    conn.execute(
        adapt_sql(conn, """
        create table if not exists historico_notas_portal26 (
            id integer primary key autoincrement,
            numero_original text,
            numero_norm text,
            vinculo text,
            canhoto text,
            pago text,
            vinculo_norm text,
            canhoto_norm text,
            pago_norm text,
            status_portal26 text,
            primeira_data_identificada text,
            ultima_data_identificada text,
            arquivo_origem text,
            data_importacao text,
            usuario_importacao text,
            tipo_movimento text,
            hash_registro text,
            signature text unique
        )
        """)
    )
    conn.execute(
        adapt_sql(conn, """
        create table if not exists controle_tarefas_ipiranga (
            id integer primary key autoincrement,
            signature text unique,
            cte text,
            nota_fiscal text,
            nota_fiscal_norm text,
            valor real,
            valor_total_conhec real,
            operacao text,
            municipio_remetente text,
            municipio_destinatario text,
            placa text,
            status_original text,
            etapa_tarefa text,
            tarefa text,
            data_tarefa text,
            prazo_retorno text,
            usuario_tarefa text,
            situacao_retorno text,
            observacao_tarefa text,
            data_ultima_atualizacao text,
            data_resolucao text,
            status_portal26_atual text,
            arquivo_origem text
        )
        """)
    )
    conn.execute(
        adapt_sql(conn, """
        create table if not exists historico_tarefas_ipiranga (
            id integer primary key autoincrement,
            signature text,
            cte text,
            nota_fiscal text,
            acao text,
            valor_anterior text,
            valor_novo text,
            valor_total_conhec real,
            usuario text,
            data_hora text,
            observacao text
        )
        """)
    )
    ensure_columns(
        conn,
        "controle_tarefas_ipiranga",
        {
            "valor_total_conhec": "real",
        },
    )
    ensure_columns(
        conn,
        "historico_tarefas_ipiranga",
        {
            "valor_total_conhec": "real",
        },
    )


def create_analysis_tables(conn) -> None:
    create_ipiranga_tables(conn)
    conn.execute(
        adapt_sql(conn, """
        create table if not exists tarefas_operacionais (
            id integer primary key autoincrement,
            modulo text,
            submodulo text,
            tipo_tarefa text,
            cte text,
            nf text,
            chave_referencia text unique,
            valor_referencia real,
            data_base text,
            prazo_limite text,
            dias_restantes integer,
            status_prazo text,
            status_tarefa text,
            responsavel text,
            observacao text,
            cliente text,
            placa text,
            data_criacao text,
            data_atualizacao text,
            data_resolucao text,
            usuario_criacao text,
            usuario_atualizacao text,
            origem_tarefa text,
            nota_fiscal_norm text,
            origem text,
            destino text,
            produto text,
            valor_faturado real,
            data_emissao_nf text,
            source_table text,
            source_signature text,
            signature text unique
        )
        """)
    )
    ensure_columns(
        conn,
        "tarefas_operacionais",
        {
            "modulo": "text",
            "submodulo": "text",
            "tipo_tarefa": "text",
            "cte": "text",
            "nf": "text",
            "chave_referencia": "text",
            "valor_referencia": "real",
            "data_base": "text",
            "prazo_limite": "text",
            "dias_restantes": "integer",
            "status_prazo": "text",
            "status_tarefa": "text",
            "responsavel": "text",
            "observacao": "text",
            "cliente": "text",
            "placa": "text",
            "data_criacao": "text",
            "data_atualizacao": "text",
            "data_resolucao": "text",
            "usuario_criacao": "text",
            "usuario_atualizacao": "text",
            "origem_tarefa": "text",
            "nota_fiscal_norm": "text",
            "origem": "text",
            "destino": "text",
            "produto": "text",
            "valor_faturado": "real",
            "data_emissao_nf": "text",
            "source_table": "text",
            "source_signature": "text",
            "signature": "text",
        },
    )
    conn.execute("create index if not exists idx_tarefas_modulo_status on tarefas_operacionais(modulo, status_tarefa)")
    conn.execute("create index if not exists idx_tarefas_prazo on tarefas_operacionais(prazo_limite)")
    conn.execute("create index if not exists idx_tarefas_nf_cte on tarefas_operacionais(nf, cte)")
    conn.execute(
        adapt_sql(conn, """
        create table if not exists historico_tarefas_operacionais (
            id integer primary key autoincrement,
            tarefa_id integer,
            chave_referencia text,
            modulo text,
            tipo_tarefa text,
            cte text,
            nf text,
            acao text,
            valor_anterior text,
            valor_novo text,
            usuario text,
            data_hora text,
            observacao text,
            signature text unique
        )
        """)
    )
    conn.execute(
        adapt_sql(conn, """
        create table if not exists fretes_ipp_logs (
            id integer primary key autoincrement,
            data_hora_inicio text,
            data_hora_fim text,
            usuario text,
            status text,
            registros_kmm integer default 0,
            registros_portal integer default 0,
            registros_gerados integer default 0,
            portal_sem_kmm integer default 0,
            divergencias_valor integer default 0,
            tarefas_criadas integer default 0,
            tarefas_atualizadas integer default 0,
            tarefas_resolvidas integer default 0,
            mensagem_erro text,
            duracao_segundos real,
            signature text unique
        )
        """)
    )
    conn.execute(
        adapt_sql(conn, """
        create table if not exists analise_fretes_ipp (
            id integer primary key autoincrement,
            tipo_registro text,
            data_emissao text,
            data_emissao_nf text,
            data_portal text,
            cte text,
            nota_fiscal text,
            nota_fiscal_norm text,
            cliente text,
            origem text,
            destino text,
            municipio_remetente text,
            municipio_destinatario text,
            produto text,
            produto_norm text,
            operacao text,
            placa text,
            motorista text,
            volume real,
            volume_normalizado real,
            valor_faturado_kmm real,
            valor_total_cte_kmm real,
            frete_unitario real,
            base_icms real,
            valor_icms real,
            numero_portal text,
            valor_portal real,
            valor_total_portal real,
            valor_pedagio_portal real,
            valor_base_calculo_portal real,
            valor_imposto_portal real,
            tipo_frete_portal text,
            produto_portal text,
            quantidade_portal real,
            valor_unitario_portal real,
            vinculo text,
            canhoto text,
            pago text,
            vinculo_norm text,
            canhoto_norm text,
            pago_norm text,
            status_portal_ipp text,
            status_valor_portal text,
            diferenca_kmm_portal real,
            valor_acordado_coupa real,
            tarifa_coupa real,
            status_coupa text,
            camada_match_coupa text,
            diferenca_kmm_coupa real,
            status_final_frete text,
            status_tarefa text,
            status_prazo text,
            prazo_tarefa text,
            dias_restantes integer,
            responsavel text,
            observacao text,
            arquivo_kmm text,
            arquivo_portal text,
            data_processamento text,
            usuario_processamento text,
            signature text unique
        )
        """)
    )
    ensure_columns(
        conn,
        "analise_fretes_ipp",
        {
            "cte_normal": "text",
            "ctes_complementares": "text",
            "complemento_original": "text",
            "observacao_original": "text",
            "motivo_identificacao_complemento": "text",
            "valor_cte_normal": "real",
            "valor_cte_complementar": "real",
            "valor_kmm_total": "real",
            "tem_complemento": "text",
            "status_complemento_cte": "text",
            "diferenca_sem_complemento": "real",
            "diferenca_com_complemento": "real",
            "razao_social_cobranca": "text",
            "razao_social_cobranca_norm": "text",
            "cliente_equivalente": "text",
            "cliente_equivalente_norm": "text",
        },
    )
    conn.execute(
        adapt_sql(conn, """
        create table if not exists analise_complementos_operacionais (
            id integer primary key autoincrement,
            nf text,
            cte text,
            data_emissao_nf text,
            data_limite_60_dias text,
            dias_restantes integer,
            valor_original real,
            valor_correto real,
            diferenca real,
            tipo_complemento text,
            status_prazo text,
            status_tarefa text,
            modulo_origem text,
            observacao text,
            signature text unique
        )
        """)
    )
    conn.execute(
        adapt_sql(conn, """
        create table if not exists analise_complementos_frete (
            id integer primary key autoincrement,
            signature text unique,
            data_analise text,
            cte text,
            nf text,
            nota_fiscal_norm text,
            cliente text,
            placa text,
            motorista text,
            origem text,
            destino text,
            produto text,
            operacao text,
            data_emissao_nf text,
            data_emissao_cte text,
            data_limite_60_dias text,
            dias_restantes integer,
            status_prazo_60_dias text,
            valor_faturado_kmm real,
            valor_portal_ipp real,
            valor_acordado_coupa real,
            valor_correto_sugerido real,
            diferenca_kmm_portal real,
            diferenca_kmm_coupa real,
            diferenca_portal_coupa real,
            valor_complemento_sugerido real,
            tipo_complemento text,
            motivo_complemento text,
            origem_divergencia text,
            status_complemento text,
            status_tarefa text,
            tarefa_id text,
            observacao text,
            usuario_analise text,
            arquivo_origem text,
            lote_importacao text
        )
        """)
    )
    ensure_columns(
        conn,
        "analise_complementos_frete",
        {
            "cte_normal": "text",
            "ctes_complementares": "text",
            "complemento_original": "text",
            "observacao_original": "text",
            "motivo_identificacao_complemento": "text",
            "valor_cte_normal": "real",
            "valor_cte_complementar": "real",
            "valor_kmm_total": "real",
            "tem_complemento": "text",
            "status_complemento_cte": "text",
            "diferenca_sem_complemento": "real",
            "diferenca_com_complemento": "real",
        },
    )
    conn.execute(
        adapt_sql(conn, """
        create table if not exists complementos_frete_logs (
            id integer primary key autoincrement,
            data_hora_inicio text,
            data_hora_fim text,
            usuario text,
            status text,
            registros_analisados integer default 0,
            correcoes_identificadas integer default 0,
            complementos_identificados integer default 0,
            tarefas_criadas integer default 0,
            tarefas_atualizadas integer default 0,
            tarefas_resolvidas integer default 0,
            mensagem text,
            signature text unique
        )
        """)
    )
    conn.execute(
        adapt_sql(conn, """
        create table if not exists modelos_planilhas_complementos (
            id integer primary key autoincrement,
            tipo_modelo text,
            nome_modelo text,
            arquivo_modelo text,
            ativo text,
            data_upload text,
            usuario_upload text,
            signature text unique
        )
        """)
    )
    for table in ["base_kmm_tempos_normalizada", "base_control_viagens_normalizada", "base_rastreador_normalizada"]:
        conn.execute(
            adapt_sql(conn, f"""
            create table if not exists {table} (
                id integer primary key autoincrement,
                origem_id integer,
                cte text,
                nf text,
                placa text,
                cliente text,
                data_inicio text,
                data_fim text,
                tempo_minutos real,
                status text,
                arquivo_origem text,
                data_importacao text,
                signature text unique
            )
            """)
        )
    conn.execute(
        adapt_sql(conn, """
        create table if not exists analise_nsdocs_x_kmm (
            id integer primary key autoincrement,
            nsdocs_id integer,
            numero_nf text,
            chave_acesso text,
            emitente text,
            destinatario text,
            natureza_operacao text,
            transportador_cnpj text,
            valor_nf real,
            emissao_nf text,
            placa_nsdocs text,
            volumes_nsdocs real,
            cte_kmm text,
            emissao_cte text,
            placa_kmm text,
            volume_kmm real,
            cobranca_kmm text,
            origem_kmm text,
            destino_kmm text,
            inserido_por text,
            status_analise text,
            observacao text,
            arquivo_origem text,
            data_importacao text,
            signature text unique
        )
        """)
    )
    ensure_columns(
        conn,
        "analise_nsdocs_x_kmm",
        {
            "arquivo_origem": "text",
            "data_importacao": "text",
            "natureza_operacao": "text",
        },
    )
    conn.execute(
        adapt_sql(conn, """
        create table if not exists analise_auditoria_kmm (
            id integer primary key autoincrement,
            kmm_id integer,
            arquivo_origem text,
            emissao_cte text,
            cte_numero text,
            notas_fiscais text,
            placa text,
            volume real,
            id_icms_st text,
            cfop text,
            total_conhecimento real,
            base_icms real,
            valor_icms real,
            base_icms_st real,
            valor_icms_st real,
            resultado text,
            lista_erros text,
            signature text unique
        )
        """)
    )
    ensure_columns(
        conn,
        "analise_auditoria_kmm",
        {
            "emissao_cte": "text",
            "cobranca": "text",
            "emitente": "text",
            "destinatario": "text",
            "uf_origem": "text",
            "uf_destino": "text",
            "tabela_frete": "text",
        },
    )
    conn.execute(
        adapt_sql(conn, """
        create table if not exists conferencia_auditoria_kmm (
            id integer primary key autoincrement,
            signature text unique,
            numero_conhecimento text,
            nota_fiscal text,
            chave_cte text,
            placa text,
            data_emissao text,
            razao_social_cobranca text,
            erro text,
            flag_conferido text default 'NAO',
            justificativa text,
            usuario_conferencia text,
            data_hora_conferencia text,
            arquivo_origem text,
            status_conferencia text default 'PENDENTE'
        )
        """)
    )
    ensure_columns(
        conn,
        "conferencia_auditoria_kmm",
        {
            "signature": "text",
            "numero_conhecimento": "text",
            "nota_fiscal": "text",
            "chave_cte": "text",
            "placa": "text",
            "data_emissao": "text",
            "razao_social_cobranca": "text",
            "erro": "text",
            "flag_conferido": "text default 'NAO'",
            "justificativa": "text",
            "usuario_conferencia": "text",
            "data_hora_conferencia": "text",
            "arquivo_origem": "text",
            "status_conferencia": "text default 'PENDENTE'",
        },
    )
    conn.execute(
        adapt_sql(conn, """
        create table if not exists historico_conferencia_auditoria_kmm (
            id integer primary key autoincrement,
            signature text,
            numero_conhecimento text,
            acao text,
            valor_anterior text,
            valor_novo text,
            justificativa text,
            usuario text,
            data_hora text,
            origem_tela text
        )
        """)
    )
    conn.execute(
        adapt_sql(conn, """
        create table if not exists analise_tempo_nf_cte (
            id integer primary key autoincrement,
            numero_nf text,
            cte_numero text,
            emissao_nf text,
            emissao_cte text,
            cliente text,
            cobranca text,
            origem text,
            destino text,
            placa text,
            inserido_por text,
            minutos real,
            horas real,
            faixa_tempo text,
            status_prazo text,
            observacao text,
            uf_origem text,
            data_emissao_nf_original text,
            data_emissao_nf_ajustada text,
            ajuste_fuso_aplicado text,
            minutos_ajuste_fuso integer default 0,
            motivo_ajuste_fuso text,
            tempo_original_minutos real,
            tempo_ajustado_minutos real,
            data_emissao_nf text,
            hora_emissao_nf text,
            emissao_nf_tem_horario_valido text,
            signature text unique
        )
        """)
    )
    ensure_columns(
        conn,
        "analise_tempo_nf_cte",
        {
            "uf_origem": "text",
            "data_emissao_nf_original": "text",
            "data_emissao_nf_ajustada": "text",
            "ajuste_fuso_aplicado": "text",
            "minutos_ajuste_fuso": "integer default 0",
            "motivo_ajuste_fuso": "text",
            "tempo_original_minutos": "real",
            "tempo_ajustado_minutos": "real",
            "data_emissao_nf": "text",
            "hora_emissao_nf": "text",
            "emissao_nf_tem_horario_valido": "text",
        },
    )
    conn.execute(
        adapt_sql(conn, """
        create table if not exists conferencia_tempo_nf_cte (
            id integer primary key autoincrement,
            signature text unique,
            numero_conhecimento text,
            nota_fiscal text,
            chave_cte text,
            placa text,
            cliente text,
            origem text,
            uf_origem text,
            destino text,
            data_emissao_nf_original text,
            data_emissao_nf_ajustada text,
            data_emissao_cte text,
            tempo_original_minutos real,
            tempo_ajustado_minutos real,
            status_tempo text,
            flag_conferido text default 'NAO',
            justificativa text,
            usuario_conferencia text,
            data_hora_conferencia text,
            arquivo_origem text,
            status_conferencia text default 'PENDENTE'
        )
        """)
    )
    ensure_columns(
        conn,
        "conferencia_tempo_nf_cte",
        {
            "signature": "text",
            "numero_conhecimento": "text",
            "nota_fiscal": "text",
            "chave_cte": "text",
            "placa": "text",
            "cliente": "text",
            "origem": "text",
            "uf_origem": "text",
            "destino": "text",
            "data_emissao_nf_original": "text",
            "data_emissao_nf_ajustada": "text",
            "data_emissao_cte": "text",
            "tempo_original_minutos": "real",
            "tempo_ajustado_minutos": "real",
            "status_tempo": "text",
            "flag_conferido": "text default 'NAO'",
            "justificativa": "text",
            "usuario_conferencia": "text",
            "data_hora_conferencia": "text",
            "arquivo_origem": "text",
            "status_conferencia": "text default 'PENDENTE'",
        },
    )
    conn.execute(
        adapt_sql(conn, """
        create table if not exists historico_conferencia_tempo_nf_cte (
            id integer primary key autoincrement,
            signature text,
            numero_conhecimento text,
            nota_fiscal text,
            acao text,
            valor_anterior text,
            valor_novo text,
            justificativa text,
            usuario text,
            data_hora text,
            origem_tela text
        )
        """)
    )
    conn.execute(
        adapt_sql(conn, """
        create table if not exists analise_frete_unitario (
            id integer primary key autoincrement,
            kmm_id integer,
            cliente text,
            cobranca text,
            origem text,
            destino text,
            produto text,
            frete_unitario real,
            frete_referencia real,
            diferenca real,
            status_analise text,
            observacao text,
            signature text unique
        )
        """)
    )
    for table in [
        "analise_kmm_x_coupa",
        "analise_kmm_portal_ipp",
        "analise_tripla_ipiranga",
        "analise_coupa_x_faturado_volume",
        "analise_coupa_x_faturado_valor",
        "analise_indicadores_cliente",
        "analise_indicadores_placa",
        "analise_indicadores_tempo",
        "analise_estadias",
        "analise_desempenho_frota",
    ]:
        conn.execute(
            adapt_sql(conn, f"""
            create table if not exists {table} (
                id integer primary key autoincrement,
                cliente text,
                placa text,
                origem text,
                destino text,
                cobranca text,
                produto text,
                periodo text,
                volume real,
                valor real,
                quantidade integer,
                indicador text,
                status text,
                observacao text,
                signature text unique
            )
            """)
        )

    ensure_columns(
        conn,
        "analise_kmm_x_coupa",
        {
            "cte": "text",
            "nota_fiscal": "text",
            "tipo_operacao": "text",
            "peso_frete_kmm": "real",
            "tarifa_coupa": "real",
            "frete_calculado": "real",
            "diferenca": "real",
            "diferenca_percentual": "real",
            "km": "real",
            "arquivo_origem": "text",
            "camada_match": "text",
            "motivo_nao_gerado": "text",
            "resposta_transportador": "text",
            "origem_coupa": "text",
            "destino_coupa": "text",
            "produto_coupa": "text",
            "produto_normalizado": "text",
            "dt_inicio_coupa": "text",
            "dt_termino_coupa": "text",
            "distancia_coupa": "real",
            "volume_normalizado": "real",
            "motivo_nao_match": "text",
            "valor_realizado": "real",
            "frete_esperado": "real",
            "diferenca_valor": "real",
            "status_comparacao": "text",
            "base_faturamento": "text",
            "status_match_coupa": "text",
            "status_periodo_coupa": "text",
            "status_calculo": "text",
            "status_final": "text",
            "km_origem": "text",
            "unidade_tarifa_coupa": "text",
            "base_calculo_coupa": "text",
            "volume_usado_coupa": "real",
            "km_usado_coupa": "real",
            "cte_normal": "text",
            "ctes_complementares": "text",
            "complemento_original": "text",
            "observacao_original": "text",
            "motivo_identificacao_complemento": "text",
            "valor_cte_normal": "real",
            "valor_cte_complementar": "real",
            "valor_kmm_total": "real",
            "tem_complemento": "text",
            "status_complemento_cte": "text",
            "diferenca_sem_complemento": "real",
            "diferenca_com_complemento": "real",
        },
    )

    conn.execute(
        adapt_sql(conn, """
        create table if not exists diagnostico_kmm_x_coupa (
            id integer primary key autoincrement,
            numero_conhecimento text,
            nota_fiscal text,
            cliente text,
            origem text,
            destino text,
            produto text,
            volume real,
            data_emissao text,
            motivo_nao_gerado text,
            etapa_falha text,
            data_processamento text,
            usuario_processamento text,
            signature text unique
        )
        """)
    )
    ensure_columns(
        conn,
        "diagnostico_kmm_x_coupa",
        {
            "origem_kmm": "text",
            "destino_kmm": "text",
            "produto_kmm": "text",
            "produto_normalizado": "text",
            "sugestao": "text",
            "camada_match": "text",
            "resposta_transportador": "text",
            "origem_coupa": "text",
            "destino_coupa": "text",
            "produto_coupa": "text",
            "dt_inicio_coupa": "text",
            "dt_termino_coupa": "text",
            "diferenca_periodo_dias": "integer default 0",
            "motivo_nao_match": "text",
            "sugestao_correcao": "text",
            "base_faturamento": "text",
            "status_periodo_coupa": "text",
            "data_emissao_kmm": "text",
            "km_origem": "text",
        },
    )
    conn.execute(
        adapt_sql(conn, """
        create table if not exists analise_kmm_portal_ipp (
            id integer primary key autoincrement,
            data text,
            cte text,
            nota_fiscal text,
            nota_fiscal_norm text,
            cliente text,
            origem text,
            destino text,
            municipio_remetente text,
            municipio_destinatario text,
            produto text,
            produto_norm text,
            operacao text,
            placa text,
            valor_faturado_kmm real,
            valor_total_cte_kmm real,
            valor_portal real,
            valor_portal_original text,
            coluna_origem_valor_portal text,
            nome_coluna_aw_portal text,
            status_match_portal text,
            valor_portal_frete real,
            valor_portal_total real,
            diferenca_kmm_portal real,
            status_portal text,
            status_valor_portal text,
            vinculo text,
            canhoto text,
            pago text,
            vinculo_norm text,
            canhoto_norm text,
            pago_norm text,
            arquivo_kmm text,
            arquivo_portal text,
            data_processamento text,
            usuario_processamento text,
            signature text unique
        )
        """)
    )
    conn.execute(
        adapt_sql(conn, """
        create table if not exists analise_tripla_ipiranga (
            id integer primary key autoincrement,
            data text,
            cte text,
            nota_fiscal text,
            nota_fiscal_norm text,
            cliente text,
            origem text,
            destino text,
            municipio_remetente text,
            municipio_destinatario text,
            produto text,
            operacao text,
            placa text,
            valor_acordado_coupa real,
            valor_faturado_kmm real,
            valor_lancado_portal_ipp real,
            valor_portal real,
            valor_portal_original text,
            coluna_origem_valor_portal text,
            nome_coluna_aw_portal text,
            status_match_portal text,
            qtd_linhas_portal integer,
            qtd_valores_portal_preenchidos integer,
            valores_portal_encontrados text,
            status_portal_resumo text,
            diferenca_kmm_coupa real,
            diferenca_kmm_portal real,
            diferenca_portal_coupa real,
            status_coupa text,
            status_portal text,
            status_valor_portal text,
            status_final text,
            vinculo text,
            canhoto text,
            pago text,
            camada_match_coupa text,
            motivo_nao_match text,
            data_processamento text,
            usuario_processamento text,
            signature text unique
        )
        """)
    )
    conn.execute(
        adapt_sql(conn, """
        create table if not exists diagnostico_validacao_tripla_ipp (
            id integer primary key autoincrement,
            data_processamento text,
            usuario_processamento text,
            cte text,
            nota_fiscal text,
            nota_fiscal_norm text,
            valor_coupa real,
            valor_kmm real,
            valor_portal real,
            diferenca real,
            status text,
            motivo text,
            sugestao text,
            origem text,
            destino text,
            produto text,
            signature text unique
        )
        """)
    )
    ensure_columns(
        conn,
        "analise_kmm_portal_ipp",
        {
            "data": "text",
            "cte": "text",
            "nota_fiscal": "text",
            "nota_fiscal_norm": "text",
            "cliente": "text",
            "origem": "text",
            "destino": "text",
            "municipio_remetente": "text",
            "municipio_destinatario": "text",
            "produto_norm": "text",
            "operacao": "text",
            "valor_faturado_kmm": "real",
            "valor_total_cte_kmm": "real",
            "valor_portal": "real",
            "valor_portal_original": "text",
            "coluna_origem_valor_portal": "text",
            "nome_coluna_aw_portal": "text",
            "status_match_portal": "text",
            "valor_portal_frete": "real",
            "valor_portal_total": "real",
            "diferenca_kmm_portal": "real",
            "status_portal": "text",
            "status_valor_portal": "text",
            "vinculo": "text",
            "canhoto": "text",
            "pago": "text",
            "vinculo_norm": "text",
            "canhoto_norm": "text",
            "pago_norm": "text",
            "arquivo_kmm": "text",
            "arquivo_portal": "text",
            "data_processamento": "text",
            "usuario_processamento": "text",
            "signature": "text",
            "razao_social_cobranca": "text",
            "razao_social_cobranca_norm": "text",
            "cliente_equivalente": "text",
            "cliente_equivalente_norm": "text",
        },
    )
    ensure_columns(
        conn,
        "analise_tripla_ipiranga",
        {
            "data": "text",
            "cte": "text",
            "nota_fiscal": "text",
            "nota_fiscal_norm": "text",
            "cliente": "text",
            "razao_social_cobranca": "text",
            "razao_social_cobranca_norm": "text",
            "cliente_equivalente": "text",
            "cliente_equivalente_norm": "text",
            "origem": "text",
            "destino": "text",
            "municipio_remetente": "text",
            "municipio_destinatario": "text",
            "operacao": "text",
            "valor_acordado_coupa": "real",
            "valor_faturado_kmm": "real",
            "valor_lancado_portal_ipp": "real",
            "valor_portal": "real",
            "valor_portal_original": "text",
            "coluna_origem_valor_portal": "text",
            "nome_coluna_aw_portal": "text",
            "status_match_portal": "text",
            "qtd_linhas_portal": "integer",
            "qtd_valores_portal_preenchidos": "integer",
            "valores_portal_encontrados": "text",
            "status_portal_resumo": "text",
            "valor_coupa": "real",
            "tarifa_coupa": "real",
            "unidade_tarifa_coupa": "text",
            "base_calculo_coupa": "text",
            "volume_usado_coupa": "real",
            "km_usado_coupa": "real",
            "status_valor_kmm": "text",
            "campo_valor_kmm": "text",
            "peso_frete_kmm": "real",
            "total_conhecimento_kmm": "real",
            "frete_unitario_kmm": "real",
            "arquivo_portal_origem": "text",
            "tabela_portal_usada": "text",
            "cte_normal": "text",
            "ctes_complementares": "text",
            "complemento_original": "text",
            "observacao_original": "text",
            "motivo_identificacao_complemento": "text",
            "valor_kmm_normal": "real",
            "valor_kmm_complementar": "real",
            "valor_kmm_total": "real",
            "tem_complemento": "text",
            "status_complemento_cte": "text",
            "diferenca_sem_complemento": "real",
            "diferenca_com_complemento": "real",
            "diferenca_kmm_coupa": "real",
            "diferenca_kmm_portal": "real",
            "diferenca_portal_coupa": "real",
            "status_coupa": "text",
            "status_portal": "text",
            "status_valor_portal": "text",
            "status_final": "text",
            "vinculo": "text",
            "canhoto": "text",
            "pago": "text",
            "camada_match_coupa": "text",
            "motivo_nao_match": "text",
            "data_processamento": "text",
            "usuario_processamento": "text",
            "signature": "text",
        },
    )
    ensure_columns(
        conn,
        "diagnostico_validacao_tripla_ipp",
        {
            "data_processamento": "text",
            "usuario_processamento": "text",
            "cte": "text",
            "nota_fiscal": "text",
            "nota_fiscal_norm": "text",
            "valor_coupa": "real",
            "valor_kmm": "real",
            "valor_portal": "real",
            "diferenca": "real",
            "status": "text",
            "motivo": "text",
            "sugestao": "text",
            "origem": "text",
            "destino": "text",
            "produto": "text",
            "signature": "text",
        },
    )
    conn.execute("create index if not exists idx_analise_kmm_portal_nf on analise_kmm_portal_ipp(nota_fiscal_norm)")
    conn.execute("create index if not exists idx_tripla_ipp_nf on analise_tripla_ipiranga(nota_fiscal_norm)")
    conn.execute("create index if not exists idx_tripla_ipp_status on analise_tripla_ipiranga(status_final)")
    conn.execute(
        adapt_sql(conn, """
        create table if not exists diagnostico_coupa_x_faturado (
            id integer primary key autoincrement,
            item_coupa text,
            cliente text,
            origem text,
            destino text,
            produto text,
            periodo_inicio text,
            periodo_fim text,
            qtd_coupa real,
            valor_coupa real,
            valor_faturado real,
            volume_faturado real,
            motivo_valor_zero text,
            etapa_falha text,
            status text,
            data_processamento text,
            usuario_processamento text,
            signature text unique
        )
        """)
    )

    conn.execute(
        adapt_sql(conn, """
        create table if not exists inconsistencias (
            id integer primary key autoincrement,
            modulo_origem text,
            tipo_inconsistencia text,
            cliente text,
            placa text,
            nota_fiscal text,
            cte text,
            viagem text,
            codigo_monitoramento text,
            origem text,
            destino text,
            cobranca text,
            produto text,
            periodo text,
            pedido_coupa text,
            valor_envolvido real,
            volume_envolvido real,
            tempo_envolvido real,
            diferenca_valor real,
            diferenca_volume real,
            percentual_diferenca real,
            prioridade text,
            status_tratamento text default 'EM ABERTO',
            responsavel text,
            observacao text,
            arquivo_origem text,
            data_identificacao text,
            signature text unique
        )
        """)
    )
    conn.execute(
        adapt_sql(conn, """
        create table if not exists historico_tratamento_inconsistencias (
            id integer primary key autoincrement,
            inconsistencia_id integer,
            status_anterior text,
            status_novo text,
            responsavel text,
            observacao text,
            acao_tomada text,
            motivo_decisao text,
            data_alteracao text,
            tipo_atualizacao text,
            regra_correcao text
        )
        """)
    )
    ensure_columns(
        conn,
        "historico_tratamento_inconsistencias",
        {
            "usuario": "text",
            "perfil_usuario": "text",
        },
    )
    conn.execute(
        """
        create table if not exists configuracoes (
            chave text primary key,
            valor text,
            atualizado_em text
        )
        """
    )
    conn.execute(
        adapt_sql(conn, """
        create table if not exists usuarios (
            id integer primary key autoincrement,
            username text not null,
            nome text,
            email text,
            senha_hash text,
            perfil text,
            ativo text default 'SIM',
            origem text,
            data_criacao text,
            data_atualizacao text,
            ultimo_login text,
            criado_por text,
            atualizado_em text,
            unique(username)
        )
        """)
    )
    ensure_columns(
        conn,
        "usuarios",
        {
            "senha_hash": "text",
            "data_criacao": "text",
            "data_atualizacao": "text",
            "ultimo_login": "text",
            "criado_por": "text",
        },
    )
    conn.execute("create index if not exists idx_usuarios_username on usuarios(username)")
    conn.execute(
        adapt_sql(conn, """
        create table if not exists usuario_permissoes_modulo (
            id integer primary key autoincrement,
            usuario_id integer,
            modulo text,
            pode_visualizar text default 'SIM',
            pode_importar text default 'NAO',
            pode_editar text default 'NAO',
            pode_exportar text default 'NAO',
            pode_excluir text default 'NAO',
            pode_backup text default 'NAO',
            data_atualizacao text,
            usuario_atualizacao text
        )
        """)
    )
    conn.execute("create index if not exists idx_usuario_permissoes_usuario on usuario_permissoes_modulo(usuario_id)")
    conn.execute(
        adapt_sql(conn, """
        create table if not exists security_logs (
            id integer primary key autoincrement,
            usuario text,
            perfil text,
            acao text not null,
            tela text,
            data_hora text not null,
            status text not null,
            mensagem text,
            detalhes text,
            ip text,
            session_id text
        )
        """)
    )
    ensure_columns(
        conn,
        "security_logs",
        {
            "detalhes": "text",
            "ip": "text",
        },
    )
    conn.execute("create index if not exists idx_security_logs_data on security_logs(data_hora desc)")
    conn.execute("create index if not exists idx_security_logs_usuario on security_logs(usuario)")
    conn.execute(
        adapt_sql(conn, """
        create table if not exists backup_logs (
            id integer primary key autoincrement,
            data_hora_inicio text,
            data_hora_fim text,
            usuario text,
            status text,
            etapa text,
            tabela text,
            banco_origem text,
            banco_destino text,
            total_tabelas integer default 0,
            total_registros_processados integer default 0,
            total_registros_enviados integer default 0,
            total_registros_atualizados integer default 0,
            total_registros_ignorados integer default 0,
            mensagem_erro text,
            detalhes_tecnicos text,
            duracao_segundos real
        )
        """)
    )
    ensure_columns(
        conn,
        "backup_logs",
        {
            "etapa": "text",
            "tabela": "text",
            "total_registros_processados": "integer default 0",
            "detalhes_tecnicos": "text",
        },
    )
    conn.execute("create index if not exists idx_backup_logs_data on backup_logs(data_hora_inicio desc)")
    conn.execute(
        adapt_sql(conn, """
        create table if not exists backup_table_logs (
            id integer primary key autoincrement,
            id_backup integer,
            tabela text,
            status text,
            registros_local integer default 0,
            registros_enviados integer default 0,
            registros_ignorados integer default 0,
            erro text,
            detalhes_tecnicos text,
            duracao_segundos real
        )
        """)
    )
    conn.execute("create index if not exists idx_backup_table_logs_backup on backup_table_logs(id_backup)")
    conn.execute(
        adapt_sql(conn, """
        create table if not exists restore_logs (
            id integer primary key autoincrement,
            data_hora_inicio text,
            data_hora_fim text,
            usuario text,
            etapa text,
            status text,
            origem text,
            destino text,
            modo_restauracao text,
            total_tabelas integer default 0,
            total_tabelas_supabase integer default 0,
            total_registros_supabase integer default 0,
            total_registros_restaurados integer default 0,
            total_registros_ignorados integer default 0,
            total_registros_atualizados integer default 0,
            mensagem_erro text,
            detalhes_tecnicos text,
            traceback_sanitizado text,
            duracao_segundos real
        )
        """)
    )
    ensure_columns(conn, "restore_logs", {
        "etapa": "text",
        "total_tabelas_supabase": "integer default 0",
        "total_registros_supabase": "integer default 0",
        "traceback_sanitizado": "text",
    })
    conn.execute("create index if not exists idx_restore_logs_data on restore_logs(data_hora_inicio desc)")
    conn.execute(
        adapt_sql(conn, """
        create table if not exists restore_table_logs (
            id integer primary key autoincrement,
            id_restore integer,
            restore_log_id integer,
            tabela text,
            status text,
            registros_supabase integer default 0,
            registros_restaurados integer default 0,
            registros_atualizados integer default 0,
            registros_ignorados integer default 0,
            erro text,
            mensagem_erro text,
            detalhes_tecnicos text,
            duracao_segundos real
        )
        """)
    )
    ensure_columns(conn, "restore_table_logs", {
        "restore_log_id": "integer",
        "registros_atualizados": "integer default 0",
        "mensagem_erro": "text",
    })
    conn.execute("create index if not exists idx_restore_table_logs_restore on restore_table_logs(id_restore)")
    conn.execute(
        adapt_sql(conn, """
        create table if not exists sync_logs (
            id integer primary key autoincrement,
            data_hora_inicio text,
            data_hora_fim text,
            usuario text,
            acao text,
            direcao text,
            status text,
            origem text,
            destino text,
            total_tabelas integer default 0,
            total_registros_processados integer default 0,
            total_registros_inseridos integer default 0,
            total_registros_atualizados integer default 0,
            total_registros_ignorados integer default 0,
            mensagem_erro text,
            traceback_sanitizado text,
            duracao_segundos real
        )
        """)
    )
    conn.execute("create index if not exists idx_sync_logs_data on sync_logs(data_hora_inicio desc)")
    conn.execute(
        adapt_sql(conn, """
        create table if not exists sync_table_logs (
            id integer primary key autoincrement,
            sync_log_id integer,
            tabela text,
            status text,
            registros_origem integer default 0,
            registros_inseridos integer default 0,
            registros_atualizados integer default 0,
            registros_ignorados integer default 0,
            mensagem_erro text,
            duracao_segundos real
        )
        """)
    )
    conn.execute("create index if not exists idx_sync_table_logs_sync on sync_table_logs(sync_log_id)")
    conn.execute(
        adapt_sql(conn, """
        create table if not exists backup_runtime_control (
            id integer primary key autoincrement,
            backup_em_execucao text default 'NAO',
            tipo_backup text,
            inicio_execucao text,
            fim_execucao text,
            status text,
            usuario_ou_origem text,
            mensagem text
        )
        """)
    )
    ensure_columns(
        conn,
        "backup_runtime_control",
        {
            "backup_em_execucao": "text default 'NAO'",
            "tipo_backup": "text",
            "inicio_execucao": "text",
            "fim_execucao": "text",
            "status": "text",
            "usuario_ou_origem": "text",
            "mensagem": "text",
        },
    )
    conn.execute(
        adapt_sql(conn, """
        create table if not exists backup_automatico_logs (
            id integer primary key autoincrement,
            data_hora_inicio text,
            data_hora_fim text,
            status text,
            tipo_backup text,
            origem text,
            tabelas_processadas integer default 0,
            registros_enviados integer default 0,
            registros_ignorados integer default 0,
            mensagem text,
            duracao_segundos real
        )
        """)
    )
    ensure_columns(
        conn,
        "backup_automatico_logs",
        {
            "data_hora_inicio": "text",
            "data_hora_fim": "text",
            "status": "text",
            "tipo_backup": "text",
            "origem": "text",
            "tabelas_processadas": "integer default 0",
            "registros_enviados": "integer default 0",
            "registros_ignorados": "integer default 0",
            "mensagem": "text",
            "duracao_segundos": "real",
        },
    )
    conn.execute("create index if not exists idx_backup_auto_logs_data on backup_automatico_logs(data_hora_inicio desc)")
    conn.execute(
        adapt_sql(conn, """
        create table if not exists painel_processamento_logs (
            id integer primary key autoincrement,
            painel text,
            data_hora_inicio text,
            data_hora_fim text,
            usuario text,
            status text,
            bases_utilizadas text,
            registros_processados integer default 0,
            registros_gerados integer default 0,
            mensagem_erro text,
            quantidade_sem_match integer default 0,
            quantidade_sem_tarifa integer default 0,
            quantidade_sem_km integer default 0,
            quantidade_com_tarifa integer default 0,
            quantidade_calculada integer default 0,
            quantidade_tarifa_sem_calculo integer default 0,
            quantidade_fora_periodo integer default 0,
            quantidade_produto_nao_mapeado integer default 0,
            quantidade_valor_zero integer default 0,
            quantidade_descartada integer default 0,
            quantidade_gerada integer default 0,
            quantidade_ajuste_fuso integer default 0,
            quantidade_horario_0000 integer default 0,
            duracao_segundos real
        )
        """)
    )
    ensure_columns(
        conn,
        "painel_processamento_logs",
        {
            "quantidade_sem_match": "integer default 0",
            "quantidade_sem_tarifa": "integer default 0",
            "quantidade_sem_km": "integer default 0",
            "quantidade_com_tarifa": "integer default 0",
            "quantidade_calculada": "integer default 0",
            "quantidade_tarifa_sem_calculo": "integer default 0",
            "quantidade_fora_periodo": "integer default 0",
            "quantidade_produto_nao_mapeado": "integer default 0",
            "quantidade_valor_zero": "integer default 0",
            "quantidade_descartada": "integer default 0",
            "quantidade_gerada": "integer default 0",
            "quantidade_ajuste_fuso": "integer default 0",
            "quantidade_horario_0000": "integer default 0",
        },
    )
    conn.execute("create index if not exists idx_painel_logs_painel_data on painel_processamento_logs(painel, data_hora_inicio desc)")
    from src.database.migrations import create_modular_tables

    create_modular_tables(conn)
    ensure_unique_indexes(conn)
    ensure_performance_indexes(conn)
    ensure_sync_control_columns(conn)


def ensure_unique_indexes(conn) -> None:
    for table in [
        "analise_nsdocs_x_kmm",
        "analise_auditoria_kmm",
        "analise_tempo_nf_cte",
        "analise_frete_unitario",
        "analise_kmm_x_coupa",
        "analise_coupa_x_faturado_volume",
        "analise_coupa_x_faturado_valor",
        "analise_indicadores_cliente",
        "analise_indicadores_placa",
        "analise_indicadores_tempo",
        "analise_estadias",
        "analise_desempenho_frota",
        "inconsistencias",
        "conferencia_notas_sem_cte",
        "conferencia_auditoria_kmm",
        "historico_conferencia_auditoria_kmm",
        "conferencia_tempo_nf_cte",
        "historico_conferencia_tempo_nf_cte",
        *IPIRANGA_TABLES,
        "tarefas_operacionais",
        "historico_tarefas_operacionais",
        "analise_fretes_ipp",
        "fretes_ipp_logs",
        "analise_complementos_operacionais",
        "analise_complementos_frete",
        "complementos_frete_logs",
        "modelos_planilhas_complementos",
        "base_kmm_tempos_normalizada",
        "base_control_viagens_normalizada",
        "base_rastreador_normalizada",
        "base_vale_pedagio_rota_eixo",
        "de_para_origem_coupa_kmm",
        "de_para_produto_coupa_kmm",
        "diagnostico_kmm_x_coupa",
        "diagnostico_validacao_tripla_ipp",
        "diagnostico_coupa_x_faturado",
    ]:
        conn.execute(f"create unique index if not exists ux_{table}_signature on {table}(signature)")


def table_columns(conn, table: str) -> set[str]:
    if database_type(conn) == "postgres":
        return {
            row["column_name"]
            for row in conn.execute(
                """
                select column_name
                from information_schema.columns
                where table_schema = 'public' and table_name = ?
                """,
                (table,),
            ).fetchall()
        }
    return {row["name"] for row in conn.execute(f"pragma table_info({table})").fetchall()}


def create_index_if_columns(conn, table: str, name: str, columns: list[str]) -> None:
    existing = table_columns(conn, table)
    selected = [column for column in columns if column in existing]
    if not selected:
        return
    conn.execute(f"create index if not exists {name} on {table}({', '.join(selected)})")


def ensure_performance_indexes(conn) -> None:
    index_specs = {
        "base_kmm_original": [
            ("idx_kmm_emissao_cte", ["emissao_cte"]),
            ("idx_kmm_cte_numero", ["cte_numero"]),
            ("idx_kmm_nota_fiscal", ["nota_fiscal"]),
            ("idx_kmm_placa", ["placa"]),
            ("idx_kmm_cobranca", ["cobranca"]),
            ("idx_kmm_origem", ["origem"]),
            ("idx_kmm_destino", ["destino"]),
            ("idx_kmm_tabela_frete", ["tabela_frete"]),
            ("idx_kmm_hash_registro", ["hash_registro"]),
            ("idx_kmm_key_hash", ["key_hash"]),
        ],
        "base_kmm_notas_normalizadas": [
            ("idx_kmm_notas_nf_norm", ["nota_fiscal_normalizada"]),
            ("idx_kmm_notas_cte", ["cte_numero"]),
        ],
        "base_kmm_fat_notas_normalizadas": [
            ("idx_kmm_fat_notas_nf_norm", ["nota_fiscal_norm"]),
            ("idx_kmm_fat_notas_cte", ["cte"]),
            ("idx_kmm_fat_notas_status", ["status_registro"]),
        ],
        "base_portal_ipp_normalizada": [
            ("idx_portal_ipp_norm_nf", ["numero_norm"]),
            ("idx_portal_ipp_norm_status", ["status_registro"]),
        ],
        "base_nsdocs_original": [
            ("idx_nsdocs_numero_nf", ["numero_nf"]),
            ("idx_nsdocs_chave_acesso", ["chave_acesso"]),
            ("idx_nsdocs_transportador", ["transportador_cnpj"]),
            ("idx_nsdocs_emissao_nf", ["emissao_nf"]),
            ("idx_nsdocs_hash_registro", ["hash_registro"]),
            ("idx_nsdocs_key_hash", ["key_hash"]),
        ],
        "base_coupa_original": [
            ("idx_coupa_origem", ["origem"]),
            ("idx_coupa_destino", ["destino"]),
            ("idx_coupa_produto", ["produto"]),
            ("idx_coupa_dt_inicio", ["dt_inicio"]),
            ("idx_coupa_dt_termino", ["dt_termino"]),
            ("idx_coupa_hash_registro", ["hash_registro"]),
            ("idx_coupa_key_hash", ["key_hash"]),
        ],
        "inconsistencias": [
            ("idx_inc_modulo", ["modulo_origem"]),
            ("idx_inc_tipo", ["tipo_inconsistencia"]),
            ("idx_inc_status", ["status_tratamento"]),
            ("idx_inc_cliente", ["cliente"]),
            ("idx_inc_placa", ["placa"]),
            ("idx_inc_data", ["data_identificacao"]),
        ],
        "conferencia_notas_sem_cte": [
            ("idx_conf_nf", ["nf"]),
            ("idx_conf_conferida", ["conferida"]),
            ("idx_conf_responsavel", ["responsavel"]),
            ("idx_conf_data", ["data_hora_conferencia"]),
        ],
        "conferencia_auditoria_kmm": [
            ("idx_conf_audit_signature", ["signature"]),
            ("idx_conf_audit_flag", ["flag_conferido"]),
            ("idx_conf_audit_usuario", ["usuario_conferencia"]),
            ("idx_conf_audit_data", ["data_hora_conferencia"]),
        ],
        "conferencia_tempo_nf_cte": [
            ("idx_conf_tempo_signature", ["signature"]),
            ("idx_conf_tempo_flag", ["flag_conferido"]),
            ("idx_conf_tempo_usuario", ["usuario_conferencia"]),
            ("idx_conf_tempo_data", ["data_hora_conferencia"]),
        ],
        "base_fretes_ipp_notas_normalizadas": [
            ("idx_fretes_ipp_nf", ["nota_fiscal_individual"]),
            ("idx_fretes_ipp_nf_norm", ["nota_fiscal_norm"]),
            ("idx_fretes_ipp_cte", ["cte"]),
            ("idx_fretes_ipp_destino", ["municipio_destinatario_norm"]),
        ],
        "base_portal26_original": [
            ("idx_portal26_nf", ["nota_fiscal_normalizada"]),
            ("idx_portal26_numero_norm", ["numero_norm"]),
            ("idx_portal26_nf_norm", ["nota_fiscal_norm"]),
            ("idx_portal26_pago", ["pago_norm"]),
        ],
        "base_bases_ipp": [
            ("idx_bases_ipp_municipio", ["municipio_norm"]),
        ],
        "analise_ipiranga_fretes_portal26": [
            ("idx_ipiranga_status", ["status"]),
            ("idx_ipiranga_cte", ["cte"]),
            ("idx_ipiranga_nf", ["nota_fiscal"]),
            ("idx_ipiranga_base", ["base_ipp_encontrada"]),
        ],
        "diagnostico_kmm_x_coupa": [
            ("idx_diag_kmm_coupa_motivo", ["motivo_nao_gerado"]),
            ("idx_diag_kmm_coupa_etapa", ["etapa_falha"]),
            ("idx_diag_kmm_coupa_data", ["data_processamento"]),
        ],
        "diagnostico_coupa_x_faturado": [
            ("idx_diag_coupa_fat_status", ["status"]),
            ("idx_diag_coupa_fat_etapa", ["etapa_falha"]),
            ("idx_diag_coupa_fat_data", ["data_processamento"]),
        ],
        "tarefas_operacionais": [
            ("idx_tarefas_operacionais_modulo", ["modulo", "submodulo"]),
            ("idx_tarefas_operacionais_status", ["status_tarefa", "status_prazo"]),
            ("idx_tarefas_operacionais_prazo", ["prazo_limite"]),
            ("idx_tarefas_operacionais_nf_cte", ["nf", "cte"]),
        ],
        "analise_fretes_ipp": [
            ("idx_fretes_ipp_nf", ["nota_fiscal_norm"]),
            ("idx_fretes_ipp_cte", ["cte"]),
            ("idx_fretes_ipp_status", ["status_final_frete", "status_portal_ipp"]),
            ("idx_fretes_ipp_data", ["data_emissao", "data_portal"]),
        ],
        "fretes_ipp_logs": [
            ("idx_fretes_ipp_logs_data", ["data_hora_inicio"]),
            ("idx_fretes_ipp_logs_status", ["status"]),
        ],
        "analise_complementos_operacionais": [
            ("idx_complementos_tipo", ["tipo_complemento"]),
            ("idx_complementos_prazo", ["data_limite_60_dias"]),
            ("idx_complementos_status", ["status_tarefa", "status_prazo"]),
        ],
        "analise_complementos_frete": [
            ("idx_complementos_frete_tipo", ["tipo_complemento"]),
            ("idx_complementos_frete_prazo", ["data_limite_60_dias", "status_prazo_60_dias"]),
            ("idx_complementos_frete_status", ["status_complemento", "status_tarefa"]),
            ("idx_complementos_frete_nf_cte", ["nota_fiscal_norm", "cte"]),
        ],
        "complementos_frete_logs": [
            ("idx_complementos_frete_logs_data", ["data_hora_inicio"]),
            ("idx_complementos_frete_logs_status", ["status"]),
        ],
        "modelos_planilhas_complementos": [
            ("idx_modelos_complementos_tipo", ["tipo_modelo", "ativo"]),
        ],
        "de_para_origem_coupa_kmm": [
            ("idx_depara_coupa_norm", ["origem_coupa_norm"]),
            ("idx_depara_kmm_norm", ["origem_kmm_norm"]),
            ("idx_depara_ativo", ["ativo"]),
        ],
        "de_para_produto_coupa_kmm": [
            ("idx_depara_produto_norm", ["produto_norm"]),
            ("idx_depara_produto_ativo", ["ativo"]),
        ],
    }
    analysis_tables = [
        "analise_nsdocs_x_kmm",
        "analise_auditoria_kmm",
        "analise_kmm_x_coupa",
        "analise_kmm_portal_ipp",
        "analise_tripla_ipiranga",
        "analise_coupa_x_faturado_volume",
        "analise_coupa_x_faturado_valor",
        "analise_frete_unitario",
        "analise_tempo_nf_cte",
        "analise_indicadores_cliente",
        "analise_indicadores_placa",
        "analise_estadias",
        "analise_desempenho_frota",
    ]
    for table in analysis_tables:
        index_specs.setdefault(table, [])
        index_specs[table].extend(
            [
                (f"idx_{table}_processamento", ["data_processamento"]),
                (f"idx_{table}_mes", ["mes", "periodo"]),
                (f"idx_{table}_cliente", ["cliente", "cobranca"]),
                (f"idx_{table}_placa", ["placa"]),
                (f"idx_{table}_status", ["status", "status_analise", "resultado"]),
                (f"idx_{table}_arquivo", ["arquivo_origem"]),
            ]
        )
    for table, specs in index_specs.items():
        for name, columns in specs:
            create_index_if_columns(conn, table, name, columns)


def ensure_sync_control_columns(conn) -> None:
    tables = [
        *BASE_TABLES.values(),
        "base_kmm_notas_normalizadas",
        "base_kmm_fat_notas_normalizadas",
        "base_kmm_faturamento_consolidado",
        "base_portal_ipp_normalizada",
        "base_coupa_fluxos_normalizados",
        "base_vale_pedagio_rota_eixo",
        "conferencia_notas_sem_cte",
        "historico_conferencia_notas_sem_cte",
        "conferencia_auditoria_kmm",
        "historico_conferencia_auditoria_kmm",
        "conferencia_tempo_nf_cte",
        "historico_conferencia_tempo_nf_cte",
        *IPIRANGA_TABLES,
        "tarefas_operacionais",
        "historico_tarefas_operacionais",
        "analise_fretes_ipp",
        "fretes_ipp_logs",
        "analise_complementos_operacionais",
        "analise_complementos_frete",
        "complementos_frete_logs",
        "modelos_planilhas_complementos",
        "base_kmm_tempos_normalizada",
        "base_control_viagens_normalizada",
        "base_rastreador_normalizada",
        "de_para_origem_coupa_kmm",
        "de_para_coupa_fat",
        "de_para_produto_coupa_kmm",
        "diagnostico_kmm_x_coupa",
        "diagnostico_validacao_tripla_ipp",
        "diagnostico_coupa_x_faturado",
        "inconsistencias",
        "historico_tratamento_inconsistencias",
        "configuracoes",
        "usuario_permissoes_modulo",
        "backup_automatico_logs",
        "importacoes",
        "arquivos_importados",
        "analise_nsdocs_x_kmm",
        "analise_auditoria_kmm",
        "analise_kmm_x_coupa",
        "analise_kmm_portal_ipp",
        "analise_tripla_ipiranga",
        "analise_coupa_x_faturado_volume",
        "analise_coupa_x_faturado_valor",
        "analise_frete_unitario",
        "analise_tempo_nf_cte",
        "analise_indicadores_cliente",
        "analise_indicadores_placa",
        "analise_indicadores_tempo",
        "analise_estadias",
        "analise_desempenho_frota",
    ]
    columns = {
        "created_at": "text",
        "updated_at": "text",
        "source_file": "text",
        "import_batch_id": "integer",
        "sync_status": "text default 'SINCRONIZADO'",
        "last_synced_at": "text",
    }
    for table in dict.fromkeys(tables):
        try:
            ensure_columns(conn, table, columns)
            create_index_if_columns(conn, table, f"idx_{table}_sync_status", ["sync_status"])
        except Exception:
            pass
