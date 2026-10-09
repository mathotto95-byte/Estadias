from __future__ import annotations

import json
import threading
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd
import streamlit as st

from estadias_app.auth import authenticate, users_missing
from estadias_app.github_backup import (
    BACKUP_TABLES,
    all_database_tables,
    backup_json_bytes,
    backup_to_github,
    start_analysis_backup_scheduler,
    data_signature,
    github_auto_backup_enabled,
    github_backup_configured,
    github_backup_versions,
    import_backup_json_bytes,
    imported_database_counts,
    imported_database_tables,
    restore_from_github_if_empty,
    restore_github_version,
    restore_analysis_marks_from_github,
    restore_json_bytes,
    table_counts,
    test_github_connection,
)
from src.config.settings import ROOT_DIR, ensure_directories
from src.database.migrations import create_modular_tables
from src.database.connection import get_connection, get_database_config
from src.modules.estadias.repository import clear_estadias_full_database, clear_estadias_import_residues
from src.modules.estadias.page import (
    render_cross_page,
    render_gps_verification_page,
    render_imports_page,
    render_ots_otd_page,
)
from src.reports.exporter import dataframe_to_excel
from src.utils.timezone import brasilia_now, brasilia_now_iso
from src.utils.rw_theme import apply_theme, render_brand_header, render_login_header, render_sidebar_logo


MENU = [
    "Importação",
    "Estadias",
    "Conferência GPS",
    "OTS e OTD",
    "Backup do Banco",
]


LARGE_SESSION_EXPORT_KEYS = (
    "estadias_importacoes_backup_bytes",
    "estadias_zip_backup_bytes",
    "estadias_pdf_export_preparado",
)

# Bump when migrations change so Streamlit does not reuse an old initialization.
DATABASE_SCHEMA_VERSION = 2


@st.cache_resource(show_spinner=False)
def initialize_database(schema_version: int) -> None:
    if get_database_config().db_type == "postgres":
        with get_connection() as conn:
            schema = conn.execute("select current_schema()").fetchone()[0]
            if schema != "estadias":
                raise RuntimeError("Schema estadias nao encontrado. Execute a migracao administrativa antes de conectar o app.")
            required = ("mod_estadias_lcte_normalizada", "mod_estadias_cruzamento_inicial", "mod_estadias_analise_manual")
            for table in required:
                if conn.execute("select to_regclass(?)", (f"estadias.{table}",)).fetchone()[0] is None:
                    raise RuntimeError(f"Tabela estadias.{table} ausente. Execute a migracao administrativa.")
        return
    ensure_directories()
    with get_connection() as conn:
        create_modular_tables(conn)


def _clear_large_session_exports() -> None:
    for key in LARGE_SESSION_EXPORT_KEYS:
        st.session_state.pop(key, None)


def _apply_theme() -> None:
    apply_theme(ROOT_DIR / "assets" / "rodo_wall_logo.png")


def _require_login() -> str:
    if st.session_state.get("authenticated") and st.session_state.get("username"):
        username = str(st.session_state["username"])
        render_sidebar_logo()
        st.sidebar.subheader("Usuario")
        st.sidebar.success(username)
        if st.sidebar.button("Sair", use_container_width=True):
            st.session_state.pop("authenticated", None)
            st.session_state.pop("username", None)
            st.rerun()
        return username

    _, center, _ = st.columns([1, 1.3, 1])
    with center:
        with st.container(border=True):
            render_login_header("Estadias", "Acesso restrito")
            if users_missing():
                st.error("Configure [users] nos Secrets para liberar o acesso.")
                st.stop()
            with st.form("login_form"):
                username = st.text_input("Usuario")
                password = st.text_input("Senha", type="password")
                submitted = st.form_submit_button("Entrar", type="primary", use_container_width=True)
            if submitted:
                if authenticate(username, password):
                    st.session_state["authenticated"] = True
                    st.session_state["username"] = str(username).strip()
                    st.rerun()
                st.error("Usuario ou senha invalidos.")
    st.stop()


def _run_backup_background(reason: str) -> None:
    if not github_auto_backup_enabled():
        return
    st.session_state["last_github_backup_result"] = {
        "status": "EM_SEGUNDO_PLANO",
        "message": "Backup GitHub iniciado em segundo plano.",
        "records": 0,
    }
    thread = threading.Thread(target=backup_to_github, args=(reason,), daemon=True, name=f"estadias-github-backup-{reason}")
    thread.start()


def _restore_from_github_once() -> None:
    if st.session_state.get("github_restore_checked"):
        return
    st.session_state["github_restore_checked"] = True
    result = restore_from_github_if_empty()
    if result.get("status") == "RESTAURADO":
        st.session_state["last_github_restore_result"] = result


def _auto_backup_if_data_changed() -> None:
    if st.session_state.pop("skip_next_auto_backup", False):
        st.session_state["last_github_backup_result"] = {
            "status": "IGNORADO_IMPORTACAO_PESADA",
            "message": "Backup automatico ignorado apos importacao pesada. Envie manualmente quando a tela estiver estavel.",
            "records": 0,
        }
        try:
            st.session_state["last_data_signature"] = data_signature()
        except Exception:
            pass
        st.session_state.pop("estadias_data_changed", None)
        return
    if "last_data_signature" in st.session_state and not st.session_state.pop("estadias_data_changed", False):
        return
    try:
        signature = data_signature()
    except Exception:
        return
    previous = st.session_state.get("last_data_signature")
    st.session_state["last_data_signature"] = signature
    if previous and previous != signature:
        _run_backup_background("alteracao_dados")


def _database_zip() -> bytes:
    tables = all_database_tables()
    import_tables = imported_database_tables()
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("estadias_resultado_backup.json", backup_json_bytes())
        archive.writestr("estadias_importacoes_backup.json", import_backup_json_bytes())
        archive.writestr("estadias_resultado_backup.xlsx", dataframe_to_excel(tables))
        archive.writestr("estadias_importacoes_backup.xlsx", dataframe_to_excel(import_tables))
        archive.writestr(
            "manifesto.json",
            json.dumps(
                {
                    "gerado_em": brasilia_now_iso(),
                    "resultado": {name: int(len(df)) for name, df in tables.items()},
                    "importacoes": {name: int(len(df)) for name, df in import_tables.items()},
                    "observacao": "Contem resultados e base LCTE normalizada. Posicoes GPS nao fazem parte do backup.",
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    return output.getvalue()


def render_backup_page() -> None:
    st.subheader("Backup e recuperacao")
    st.caption("O backup salva resultados e base LCTE normalizada. Posicoes GPS nao fazem parte do backup.")
    backup_col, test_col = st.columns(2)
    if backup_col.button("Enviar backup para GitHub", use_container_width=True, disabled=not github_backup_configured()):
        st.session_state["last_github_backup_result"] = backup_to_github("manual")
    if test_col.button("Testar conexao GitHub", use_container_width=True):
        st.session_state["last_github_connection_test"] = test_github_connection()
    for key in ("last_github_backup_result", "last_github_connection_test"):
        result = st.session_state.get(key) or {}
        if result:
            (st.success if result.get("status") in {"SUCESSO", "SEM_ALTERACAO"} else st.warning)(result.get("message") or result.get("status"))
    if github_backup_configured():
        if st.button("Verificar copias no GitHub", use_container_width=True):
            try:
                st.session_state["estadias_github_versions"] = github_backup_versions()
            except Exception as exc:
                st.error(f"Falha ao consultar backups: {exc}")
        versions = st.session_state.get("estadias_github_versions") or []
        if versions:
            st.dataframe(pd.DataFrame(versions), use_container_width=True, hide_index=True)
            selection = st.selectbox("Copia para recuperar", [item["label"] for item in versions])
            confirmation = st.text_input("Digite RESTAURAR GITHUB para substituir o banco", key="confirm_github_restore")
            if st.button("Restaurar copia selecionada", disabled=confirmation.strip().upper() != "RESTAURAR GITHUB", use_container_width=True):
                try:
                    result = restore_github_version(selection)
                    st.session_state["estadias_database_restore_result"] = result
                    st.rerun()
                except Exception as exc:
                    st.error(f"Falha ao restaurar a copia: {exc}")
        with st.expander("Receber marcacoes de analise do GitHub"):
            st.caption("Recupera datas de envio, resposta e flags Sem tratativa por nota fiscal. Marcacoes existentes nao sao substituidas.")
            if st.button("Verificar backup das marcacoes", use_container_width=True):
                try:
                    st.session_state["analysis_restore_preview"] = restore_analysis_marks_from_github()
                except Exception as exc:
                    st.error(f"Nao foi possivel receber as marcacoes: {exc}")
            preview = st.session_state.get("analysis_restore_preview")
            if preview:
                st.write({"No backup": preview["backup"], "Prontas para recuperar": preview["ready"], "Sem viagem": preview["missing"], "Ambiguas": preview["ambiguous"], "Invalidas": preview["invalid"], "Ja presentes": preview["already_present"]})
                confirmation_marks = st.text_input("Digite RESTAURAR ANALISE para confirmar", key="confirm_analysis_restore")
                if st.button("Aplicar marcacoes", disabled=not preview["ready"] or confirmation_marks.strip().upper() != "RESTAURAR ANALISE", use_container_width=True):
                    try:
                        result = restore_analysis_marks_from_github(str(st.session_state.get("username") or ""), dry_run=False)
                        st.session_state["analysis_restore_result"] = result
                        st.session_state["skip_next_auto_backup"] = True
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Falha ao recuperar as marcacoes: {exc}")
            result = st.session_state.pop("analysis_restore_result", None)
            if result:
                st.success(f"{result['restored']} marcacao(oes) recuperada(s) do GitHub.")
    counts = table_counts(BACKUP_TABLES)
    import_counts = imported_database_counts()
    total = sum(counts.values())
    import_total = sum(import_counts.values())
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Tabelas resultado", len(counts))
    c2.metric("Registros resultado", total)
    c3.metric("Tabelas importacao", len(import_counts))
    c4.metric("Registros importacao", import_total)
    stamp = brasilia_now().strftime("%Y%m%d_%H%M%S")
    col1, col2 = st.columns(2)
    if col1.button("Preparar resultado JSON", use_container_width=True, disabled=total <= 0):
        try:
            st.download_button(
                "Baixar resultado JSON preparado",
                backup_json_bytes(),
                f"estadias_resultado_{stamp}.json",
                "application/json",
                use_container_width=True,
            )
        except Exception as exc:
            st.error(f"Nao foi possivel preparar o JSON de resultado: {exc}")
    if col2.button("Preparar resultado Excel", use_container_width=True, disabled=total <= 0):
        try:
            st.download_button(
                "Baixar resultado Excel preparado",
                dataframe_to_excel(all_database_tables()),
                f"estadias_resultado_{stamp}.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        except Exception as exc:
            st.error(f"Nao foi possivel preparar o Excel de resultado: {exc}")

    prep1, prep2 = st.columns(2)
    if prep1.button("Preparar JSON das importacoes", use_container_width=True, disabled=import_total <= 0):
        try:
            st.download_button(
                "Baixar importacoes JSON preparado",
                import_backup_json_bytes(),
                f"estadias_importacoes_{stamp}.json",
                "application/json",
                use_container_width=True,
            )
        except Exception as exc:
            st.error(f"Nao foi possivel preparar o JSON das importacoes: {exc}")
    if prep2.button("Preparar ZIP completo", use_container_width=True, disabled=(total + import_total) <= 0):
        try:
            st.download_button(
                "Baixar ZIP completo preparado",
                _database_zip(),
                f"backup_completo_estadias_{stamp}.zip",
                "application/zip",
                use_container_width=True,
            )
        except Exception as exc:
            st.error(f"Nao foi possivel preparar o ZIP completo: {exc}")

    st.divider()
    st.subheader("Limpar residuos das importacoes")
    st.warning("Remove somente LCTE, RASTREADOR e logs de importacao. Os resultados calculados, conclusoes, auditoria e configuracoes ficam preservados.")
    confirm_residue = st.text_input("Digite LIMPAR RESIDUOS para liberar", key="confirm_clear_import_residues")
    if st.button(
        "Limpar residuos das importacoes",
        type="primary",
        use_container_width=True,
        disabled=confirm_residue.strip().upper() != "LIMPAR RESIDUOS",
    ):
        result = clear_estadias_import_residues()
        deleted = result.get("deleted") or {}
        for key in list(st.session_state):
            if str(key).startswith(("estadias_lcte_", "estadias_control_", "estadias_rastreador_", "estadias_last_tracker_import")):
                del st.session_state[key]
        st.success(f"Residuos limpos. Registros removidos: {int(result.get('total_deleted') or 0)}.")
        if result.get("message"):
            st.caption(str(result.get("message")))
        if deleted:
            st.dataframe(pd.DataFrame([{"tabela": key, "registros_removidos": value} for key, value in deleted.items()]), use_container_width=True, hide_index=True)

    with st.expander("Zerar banco operacional completo", expanded=False):
        st.error("Remove importacoes, resultados, conclusoes, auditoria, logs, locais, parametros e preferencias. Mantem somente a estrutura e configuracoes internas.")
        confirm_full = st.text_input("Digite ZERAR BANCO para liberar", key="confirm_clear_full_database")
        if st.button(
            "Zerar banco completo",
            type="primary",
            use_container_width=True,
            disabled=confirm_full.strip().upper() != "ZERAR BANCO",
        ):
            result = clear_estadias_full_database()
            deleted = result.get("deleted") or {}
            for key in list(st.session_state):
                if str(key).startswith("estadias_"):
                    del st.session_state[key]
            st.success(f"Banco operacional zerado. Registros removidos: {int(result.get('total_deleted') or 0)}.")
            if result.get("message"):
                st.caption(str(result.get("message")))
            if deleted:
                st.dataframe(pd.DataFrame([{"tabela": key, "registros_removidos": value} for key, value in deleted.items()]), use_container_width=True, hide_index=True)
            st.rerun()

    st.divider()
    st.subheader("Importar backup JSON")
    last_restore = st.session_state.get("estadias_database_restore_result")
    if isinstance(last_restore, dict):
        schema_label = "completo" if last_restore.get("schema") == "estadias_completo_v1" else ("importacoes" if last_restore.get("schema") == "estadias_importacoes_backup_v1" else "resultados")
        st.success(
            f"Ultimo backup de {schema_label} importado. "
            f"Restaurados: {last_restore.get('restored', 0)} | "
            f"Ignorados: {last_restore.get('ignored', 0)} | "
            f"Erros: {last_restore.get('errors', 0)}"
        )
        per_table = last_restore.get("per_table") or {}
        if per_table:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "tabela": table,
                            "linhas_no_json": values.get("arquivo", 0),
                            "restaurados": values.get("restaurados", 0),
                            "ignorados": values.get("ignorados", 0),
                            "erros": values.get("erros", 0),
                        }
                        for table, values in per_table.items()
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )
        if last_restore.get("schema") == "estadias_importacoes_backup_v1":
            st.warning("Esse JSON contem bases de importacao, nao o painel final. Para aparecer no Cruzamento, importe tambem o JSON de resultados ou recalcule apos importar LCTE e rastreador.")
    uploaded = st.file_uploader("Arquivo JSON de resultado ou importacoes", type=["json"], key="database_backup_upload")
    mode_label = st.radio("Modo de importacao", ["Substituir banco atual", "Mesclar com banco atual"], horizontal=True)
    mode = "replace" if mode_label.startswith("Substituir") else "merge"
    confirm = ""
    if mode == "replace":
        st.warning("Substituir apaga somente o grupo do JSON importado: resultado ou importacoes. Backup vazio nao substitui dados existentes.")
        confirm = st.text_input("Digite RESTAURAR para liberar a substituicao")
    disabled = uploaded is None or (mode == "replace" and confirm.strip().upper() != "RESTAURAR")
    if st.button("Importar banco", type="primary", use_container_width=True, disabled=disabled):
        try:
            result = restore_json_bytes(uploaded.getvalue(), mode)
            st.session_state["estadias_database_restore_result"] = result
            schema_label = "completo" if result.get("schema") == "estadias_completo_v1" else ("importacoes" if result.get("schema") == "estadias_importacoes_backup_v1" else "resultados")
            st.success(f"Backup de {schema_label} importado. Restaurados: {result.get('restored', 0)} | Ignorados: {result.get('ignored', 0)}")
            st.caption("Depois de importar resultado e importacoes, use Recalcular regras no Cruzamento para aplicar a logica atual.")
            st.rerun()
        except Exception as exc:
            st.error(f"Nao foi possivel importar o banco: {exc}")


def main() -> None:
    st.set_page_config(page_title="Estadias", page_icon="E", layout="wide")
    _apply_theme()
    _clear_large_session_exports()
    username = _require_login()
    try:
        initialize_database(DATABASE_SCHEMA_VERSION)
    except Exception as exc:
        st.error(f"Banco de dados indisponivel: {exc}")
        st.stop()
    if get_database_config().db_type != "postgres":
        _restore_from_github_once()
        start_analysis_backup_scheduler()
    if st.sidebar.button("Atualizar pagina", use_container_width=True):
        st.rerun()
    render_brand_header("Estadias", "Sistema independente com banco proprio e backup direto no GitHub.")
    if st.session_state.pop("next_menu", None) == "Importação":
        st.session_state["main_menu"] = "Importação"
    if st.session_state.get("main_menu") not in MENU:
        st.session_state["main_menu"] = "Estadias"
    page = st.sidebar.radio("Menu", MENU, key="main_menu")
    st.divider()

    if page == "Importação":
        render_imports_page(username, "ADMIN")
    elif page == "Estadias":
        render_cross_page(username)
    elif page == "Conferência GPS":
        render_gps_verification_page()
    elif page == "OTS e OTD":
        render_ots_otd_page()
    elif page == "Backup do Banco":
        render_backup_page()

    if get_database_config().db_type != "postgres":
        _auto_backup_if_data_changed()


if __name__ == "__main__":
    main()
