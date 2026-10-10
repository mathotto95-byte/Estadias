from __future__ import annotations

import threading

import streamlit as st

from estadias_app.auth import authenticate, users_missing
from estadias_app import supabase_results_backup
from estadias_app.github_backup import (
    BACKUP_TABLES,
    backup_to_github,
    start_analysis_backup_scheduler,
    data_signature,
    github_auto_backup_enabled,
    github_backup_configured,
    github_backup_versions,
    restore_github_version,
    restore_analysis_marks_from_github,
    restore_json_bytes,
    table_counts,
)
from src.config.settings import ROOT_DIR, ensure_directories
from src.database.migrations import create_modular_tables
from src.database.connection import get_connection, get_database_config
from src.modules.estadias.repository import CROSS_TABLE, clear_estadias_full_database, clear_estadias_import_residues
from src.modules.estadias.page import (
    render_cross_page,
    render_gps_verification_page,
    render_imports_page,
    render_ots_otd_page,
)
from src.utils.rw_theme import apply_theme, render_brand_header, render_login_header, render_sidebar_logo


MENU = [
    "Importação",
    "Estadias",
    "Conferência GPS",
    "OTS e OTD",
    "Backup do Banco",
]


LARGE_SESSION_EXPORT_KEYS = (
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
            st.session_state.clear()
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
    changed = st.session_state.pop("estadias_data_changed", False)
    if "last_data_signature" in st.session_state and not changed:
        return
    try:
        signature = data_signature()
    except Exception:
        return
    previous = st.session_state.get("last_data_signature")
    st.session_state["last_data_signature"] = signature
    if previous and (previous != signature or changed):
        _run_backup_background("alteracao_dados")


def render_backup_page() -> None:
    st.subheader("Backup do Banco")
    counts = table_counts(BACKUP_TABLES)
    trips = counts.get(CROSS_TABLE, 0)
    saved = st.session_state.get("estadias_supabase_status")
    copies = {item["slot"]: item for item in (saved or {}).get("copias", [])}
    current = copies.get("atual")

    c1, c2, c3 = st.columns(3)
    c1.metric("Viagens calculadas", trips)
    c2.metric("Supabase", current["gerado_em"][:19].replace("T", " ") if current else ("Sem copia" if saved else "Nao verificado"))
    c3.metric("GitHub secundario", "Configurado" if github_backup_configured() else "Nao configurado")

    if not supabase_results_backup.configured():
        st.warning("Backup Supabase nao configurado.")
    else:
        connection = supabase_results_backup.connection_summary()
        if connection.get("error"):
            st.warning(connection["error"])
        check_col, preview_col, send_col = st.columns(3)
        if check_col.button("Atualizar resumo", use_container_width=True):
            try:
                st.session_state["estadias_supabase_status"] = supabase_results_backup.status()
                st.rerun()
            except Exception as exc:
                st.error(f"Falha ao consultar Supabase: {exc}")
        if preview_col.button("Dimensionar backup", use_container_width=True, disabled=trips <= 0):
            try:
                st.session_state["estadias_supabase_preview"] = supabase_results_backup.preview()
            except Exception as exc:
                st.error(f"Nao foi possivel dimensionar: {exc}")
        if send_col.button("Enviar resultados", use_container_width=True, disabled=trips <= 0):
            try:
                result = supabase_results_backup.upload()
                st.session_state.pop("estadias_supabase_preview", None)
                st.session_state["estadias_supabase_status"] = supabase_results_backup.status()
                st.success(f"{result['viagens']} viagens: {result['status'].lower()}.")
                st.rerun()
            except Exception as exc:
                st.error(f"Backup nao enviado: {exc}")
        estimate = st.session_state.get("estadias_supabase_preview")
        if estimate:
            st.caption(
                f"Arquivo: {estimate['bytes_compactados'] / 1048576:.2f} MB | "
                f"Duas copias: {estimate['bytes_armazenados_apos_envio'] / 1048576:.2f} MB | "
                f"Variacao: {estimate['variacao_bytes'] / 1048576:+.2f} MB | "
                f"{estimate['status'].replace('_', ' ')}"
            )
        if copies:
            st.caption("Supabase: " + " | ".join(
                f"{slot}: {item['viagens']} viagens, {item['bytes_compactados'] / 1048576:.2f} MB"
                for slot, item in copies.items()
            ))

    with st.expander("Backup secundario no GitHub"):
        st.caption("Copia independente dos resultados e da base LCTE. Posicoes GPS nao sao incluidas.")
        if not github_backup_configured():
            st.info("GitHub nao configurado.")
        elif get_database_config().db_type == "postgres":
            st.info("Backup GitHub desativado para banco operacional PostgreSQL.")
        else:
            if st.button("Enviar copia ao GitHub", use_container_width=True):
                st.session_state["last_github_backup_result"] = backup_to_github("manual")
            result = st.session_state.get("last_github_backup_result") or {}
            if result:
                (st.success if result.get("status") in {"SUCESSO", "SEM_ALTERACAO"} else st.warning)(
                    result.get("message") or result.get("status")
                )
            if st.button("Verificar copias do GitHub", use_container_width=True):
                try:
                    st.session_state["estadias_github_versions"] = github_backup_versions()
                except Exception as exc:
                    st.error(f"Falha ao consultar GitHub: {exc}")
            versions = st.session_state.get("estadias_github_versions") or []
            if versions:
                selection = st.selectbox("Copia para recuperar", [item["label"] for item in versions])
                confirmation = st.text_input("Digite RESTAURAR GITHUB para substituir o banco", key="confirm_github_restore")
                if st.button("Restaurar copia do GitHub", disabled=confirmation.strip().upper() != "RESTAURAR GITHUB", use_container_width=True):
                    try:
                        st.session_state["estadias_database_restore_result"] = restore_github_version(selection)
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Falha ao restaurar: {exc}")
            if st.toggle("Recuperar marcacoes de analise", key="show_restore_marks"):
                if st.button("Verificar marcacoes", use_container_width=True):
                    try:
                        st.session_state["analysis_restore_preview"] = restore_analysis_marks_from_github()
                    except Exception as exc:
                        st.error(f"Falha ao consultar marcacoes: {exc}")
                marks = st.session_state.get("analysis_restore_preview")
                if marks:
                    st.caption(f"Prontas: {marks['ready']} | Sem viagem: {marks['missing']} | Ja presentes: {marks['already_present']}")
                    confirm_marks = st.text_input("Digite RESTAURAR ANALISE", key="confirm_analysis_restore")
                    if st.button("Aplicar marcacoes", disabled=not marks["ready"] or confirm_marks.strip().upper() != "RESTAURAR ANALISE", use_container_width=True):
                        try:
                            result = restore_analysis_marks_from_github(str(st.session_state.get("username") or ""), dry_run=False)
                            st.session_state["analysis_restore_result"] = result
                            st.session_state["skip_next_auto_backup"] = True
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Falha ao recuperar marcacoes: {exc}")
                restored_marks = st.session_state.pop("analysis_restore_result", None)
                if restored_marks:
                    st.success(f"{restored_marks['restored']} marcacoes recuperadas.")

    with st.expander("Recuperar dados"):
        if copies:
            slot = st.selectbox("Copia do Supabase", list(copies))
            if st.button("Preparar copia do Supabase", use_container_width=True):
                try:
                    st.session_state["estadias_supabase_download"] = (slot, supabase_results_backup.download(slot))
                except Exception as exc:
                    st.error(f"Falha ao preparar copia: {exc}")
            prepared = st.session_state.get("estadias_supabase_download")
            if prepared and prepared[0] == slot:
                st.download_button("Baixar copia JSON", prepared[1], f"estadias_resultado_{slot}.json", "application/json", use_container_width=True)
        restored = st.session_state.get("estadias_database_restore_result")
        if isinstance(restored, dict):
            st.success(f"Ultima recuperacao: {restored.get('restored', 0)} restaurados, {restored.get('errors', 0)} erros.")
        uploaded = st.file_uploader("Arquivo JSON de backup", type=["json"], key="database_backup_upload")
        mode = st.radio("Modo", ["Mesclar", "Substituir"], horizontal=True)
        confirmation = st.text_input("Digite RESTAURAR para substituir", key="confirm_json_restore") if mode == "Substituir" else ""
        if st.button("Importar backup", disabled=uploaded is None or (mode == "Substituir" and confirmation.strip().upper() != "RESTAURAR"), use_container_width=True):
            try:
                st.session_state["estadias_database_restore_result"] = restore_json_bytes(
                    uploaded.getvalue(), "replace" if mode == "Substituir" else "merge"
                )
                st.rerun()
            except Exception as exc:
                st.error(f"Falha ao importar backup: {exc}")

    with st.expander("Manutencao do banco"):
        st.warning("As acoes abaixo removem dados operacionais. Confirme somente apos verificar uma copia recuperavel.")
        confirm_residue = st.text_input("Digite LIMPAR RESIDUOS", key="confirm_clear_import_residues")
        if st.button("Limpar residuos das importacoes", disabled=confirm_residue.strip().upper() != "LIMPAR RESIDUOS", use_container_width=True):
            result = clear_estadias_import_residues()
            st.success(f"{int(result.get('total_deleted') or 0)} registros removidos; resultados preservados.")
        confirm_full = st.text_input("Digite ZERAR BANCO", key="confirm_clear_full_database")
        if st.button("Zerar banco operacional completo", disabled=confirm_full.strip().upper() != "ZERAR BANCO", use_container_width=True):
            result = clear_estadias_full_database()
            for key in list(st.session_state):
                if str(key).startswith("estadias_"):
                    del st.session_state[key]
            st.success(f"{int(result.get('total_deleted') or 0)} registros removidos.")
            st.rerun()


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
        start_analysis_backup_scheduler()
    if st.sidebar.button("Atualizar pagina", use_container_width=True):
        st.rerun()
    render_brand_header("Estadias", "Sistema independente com backup de resultados no Supabase e copia no GitHub.")
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
