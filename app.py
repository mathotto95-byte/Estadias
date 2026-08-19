from __future__ import annotations

import json
import threading
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd
import streamlit as st

from estadias_app.auth import authenticate, using_default_admin
from estadias_app.github_backup import (
    all_database_tables,
    backup_json_bytes,
    backup_to_github,
    data_signature,
    github_auto_backup_enabled,
    github_backup_configured,
    github_diagnostic,
    github_settings,
    prune_history,
    restore_from_github_if_empty,
    restore_json_bytes,
    test_github_connection,
)
from src.config.settings import ensure_directories
from src.database.connection import database_status
from src.database.migrations import create_modular_tables
from src.database.connection import get_connection
from src.modules.estadias.repository import clear_estadias_full_database, clear_estadias_import_residues
from src.modules.estadias.page import (
    render_config_page,
    render_control_page,
    render_cross_page,
    render_dashboard_page,
    render_imports_page,
    render_logs_page,
    render_rastreador_page,
    render_teste_lcte_rastreador_page,
)
from src.reports.exporter import dataframe_to_excel
from src.utils.timezone import brasilia_now, brasilia_now_iso


MENU = [
    "Dashboard",
    "Importacoes",
    "Base CONTROL",
    "Relatorios Rastreador por Placa",
    "Cruzamento LCTE x CONTROL x Rastreador",
    "TESTE LCTE x RASTREADOR",
    "Logs de Importacao",
    "Configuracoes",
    "Backup do Banco",
]


def initialize_database() -> None:
    ensure_directories()
    with get_connection() as conn:
        create_modular_tables(conn)


def _apply_theme() -> None:
    st.markdown(
        """
        <style>
        :root {
            --rw-bg: #030914;
            --rw-panel: #071526;
            --rw-navy: #020d3f;
            --rw-gold: #d4af37;
            --rw-border: rgba(212, 175, 55, 0.32);
            --rw-text: #f8fafc;
            --rw-muted: rgba(248, 250, 252, 0.72);
        }
        .stApp {background: var(--rw-bg) !important; color: var(--rw-text) !important;}
        .block-container {padding-top: 1.1rem; max-width: 1550px;}
        h1, h2, h3, label, p, span, div {color: var(--rw-text);}
        [data-testid="stCaptionContainer"] p {color: var(--rw-muted) !important;}
        [data-testid="stSidebar"] {background: var(--rw-navy) !important; border-right: 1px solid var(--rw-border);}
        [data-testid="stSidebar"] * {color: var(--rw-text) !important;}
        div[data-testid="stMetric"] {background: var(--rw-navy); border: 1px solid var(--rw-border); border-radius: 8px; padding: 12px 14px;}
        div[data-testid="stMetric"] * {color: var(--rw-text) !important;}
        div[data-testid="stExpander"], div[data-testid="stVerticalBlockBorderWrapper"] {
            background: rgba(7, 21, 38, 0.72);
            border: 1px solid var(--rw-border);
            border-radius: 8px;
        }
        div[data-testid="stDataFrame"] {border: 1px solid var(--rw-border); border-radius: 8px; overflow: hidden;}
        .stButton > button, .stDownloadButton > button {
            background: var(--rw-panel);
            border: 1px solid var(--rw-gold);
            border-radius: 8px;
            color: var(--rw-text) !important;
            font-weight: 800;
        }
        .stButton > button:hover, .stDownloadButton > button:hover,
        .stButton > button[kind="primary"] {
            background: var(--rw-gold);
            color: var(--rw-bg) !important;
            border-color: var(--rw-gold);
        }
        [data-baseweb="input"], [data-baseweb="select"] > div {
            background: var(--rw-panel) !important;
            border-color: var(--rw-border) !important;
        }
        [data-baseweb="input"] input, [data-baseweb="select"] div {color: var(--rw-text) !important;}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _require_login() -> str:
    if st.session_state.get("authenticated") and st.session_state.get("username"):
        username = str(st.session_state["username"])
        st.sidebar.subheader("Usuario")
        st.sidebar.success(username)
        if st.sidebar.button("Sair", use_container_width=True):
            st.session_state.pop("authenticated", None)
            st.session_state.pop("username", None)
            st.rerun()
        return username

    st.title("Estadias")
    st.caption("Acesso restrito")
    if using_default_admin():
        st.warning("Usuario inicial ativo: admin / admin. Configure usuarios nos Secrets antes de liberar para a equipe.")
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
        return
    try:
        signature = data_signature()
    except Exception:
        return
    previous = st.session_state.get("last_data_signature")
    st.session_state["last_data_signature"] = signature
    if previous and previous != signature:
        _run_backup_background("alteracao_dados")


def _render_github_sidebar() -> None:
    settings = github_settings()
    diagnostic = github_diagnostic()
    if st.sidebar.button("Atualizar pagina", use_container_width=True, key="refresh_page"):
        st.rerun()
    st.sidebar.divider()
    st.sidebar.subheader("Backup GitHub")
    st.sidebar.caption("Destino: arquivo JSON no GitHub, nao Release.")
    if github_backup_configured():
        st.sidebar.caption(f"Repo: {settings['repository']} | Branch: {settings['branch']}")
        st.sidebar.caption(f"Arquivo: {settings['latest_path']}")
    else:
        st.sidebar.warning("GitHub backup nao configurado.")
    st.sidebar.caption(f"Token: {diagnostic.get('token_masked')} | {diagnostic.get('token_length', 0)} caracteres")

    if st.sidebar.button("Testar conexao GitHub", use_container_width=True):
        result = test_github_connection()
        st.session_state["last_github_connection_test"] = result
        if result.get("status") == "SUCESSO":
            st.session_state.pop("last_github_backup_result", None)
    last_test = st.session_state.get("last_github_connection_test") or {}
    if last_test:
        if last_test.get("status") == "SUCESSO":
            st.sidebar.success(last_test.get("message"))
        else:
            st.sidebar.warning(last_test.get("message") or last_test.get("status"))

    last_restore = st.session_state.get("last_github_restore_result") or {}
    if last_restore:
        st.sidebar.success(f"Restaurado do GitHub: {last_restore.get('records', 0)} registro(s).")

    last_backup = st.session_state.get("last_github_backup_result") or {}
    if last_backup:
        status = str(last_backup.get("status") or "")
        if status == "SUCESSO":
            st.sidebar.success(f"Backup GitHub OK: {last_backup.get('records', 0)} registro(s).")
        elif status == "EM_SEGUNDO_PLANO":
            st.sidebar.info("Backup GitHub iniciado em segundo plano.")
        elif status not in {"", "NAO_CONFIGURADO"}:
            st.sidebar.warning(last_backup.get("message") or status)

    if st.sidebar.button("Enviar backup para GitHub", use_container_width=True, disabled=not github_backup_configured()):
        st.session_state.pop("last_github_connection_test", None)
        result = backup_to_github("manual")
        st.session_state["last_github_backup_result"] = result
        if result.get("status") == "SUCESSO":
            st.sidebar.success("Backup enviado para GitHub.")
        else:
            st.sidebar.warning(result.get("message") or "Backup GitHub nao concluido.")

    if st.sidebar.button(
        "Limpar historico antigo de backups",
        use_container_width=True,
        disabled=not github_backup_configured(),
        help="Remove snapshots antigos de backups/history, mantendo apenas os mais recentes. Reduz o tamanho do repositorio.",
    ):
        prune_result = prune_history()
        if prune_result.get("status") == "SUCESSO":
            st.sidebar.success(f"Historico limpo: {prune_result.get('removidos', 0)} arquivo(s) removido(s).")
        elif prune_result.get("status") == "NAO_CONFIGURADO":
            st.sidebar.warning("GitHub backup nao configurado.")
        else:
            st.sidebar.warning(f"Limpeza parcial: {prune_result.get('removidos', 0)} removido(s), {prune_result.get('erros', 0)} erro(s).")


def _render_status() -> None:
    status = database_status()
    cols = st.columns(4)
    cols[0].metric("Banco", "Supabase" if status["db_type"] == "postgres" else "SQLite")
    cols[1].metric("Conexao", "OK" if status["connected"] else "Falha")
    cols[2].metric("Viagens LCTE", int(status.get("rows") or 0))
    cols[3].metric("Atualizado", brasilia_now().strftime("%d/%m/%Y %H:%M"))
    if not status["connected"]:
        st.error(status.get("error") or "Banco indisponivel.")
    else:
        st.caption(status.get("database") or "")


def _database_zip() -> bytes:
    tables = all_database_tables()
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("estadias_resultado_backup.json", backup_json_bytes())
        archive.writestr("estadias_resultado_backup.xlsx", dataframe_to_excel(tables))
        archive.writestr(
            "manifesto.json",
            json.dumps(
                {
                    "gerado_em": brasilia_now_iso(),
                    "tabelas": {name: int(len(df)) for name, df in tables.items()},
                    "observacao": "Backup enxuto: contem resultados, conclusoes e configuracoes. Bases importadas LCTE/CONTROL/RASTREADOR ficam fora para reduzir tamanho.",
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    return output.getvalue()


def render_backup_page() -> None:
    st.subheader("Backup e recuperacao dos resultados")
    st.caption("Backup enxuto: salva resultados, conclusoes, auditoria e configuracoes. Planilhas importadas LCTE/CONTROL/RASTREADOR nao entram no backup.")
    tables = all_database_tables()
    total = sum(len(df) for df in tables.values())
    c1, c2, c3 = st.columns(3)
    c1.metric("Tabelas", len(tables))
    c2.metric("Registros", total)
    c3.metric("Formato seguro", "JSON")
    stamp = brasilia_now().strftime("%Y%m%d_%H%M%S")
    col1, col2, col3 = st.columns(3)
    col1.download_button("Baixar resultado JSON", backup_json_bytes(), f"estadias_resultado_{stamp}.json", "application/json", use_container_width=True)
    col2.download_button(
        "Baixar resultado Excel",
        dataframe_to_excel(tables),
        f"estadias_resultado_{stamp}.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
    col3.download_button("Baixar resultado ZIP", _database_zip(), f"backup_resultado_estadias_{stamp}.zip", "application/zip", use_container_width=True)

    st.divider()
    st.subheader("Limpar residuos das importacoes")
    st.warning("Remove somente LCTE, CONTROL, RASTREADOR e logs de importacao. Os resultados calculados, conclusoes, auditoria e configuracoes ficam preservados.")
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
    st.subheader("Importar resultados")
    uploaded = st.file_uploader("Arquivo JSON de backup de resultados", type=["json"], key="database_backup_upload")
    mode_label = st.radio("Modo de importacao", ["Mesclar com banco atual", "Substituir banco atual"], horizontal=True)
    mode = "replace" if mode_label.startswith("Substituir") else "merge"
    confirm = ""
    if mode == "replace":
        st.warning("Substituir apaga o banco atual antes de importar. Backup vazio nao substitui dados existentes.")
        confirm = st.text_input("Digite RESTAURAR para liberar a substituicao")
    disabled = uploaded is None or (mode == "replace" and confirm.strip().upper() != "RESTAURAR")
    if st.button("Importar banco", type="primary", use_container_width=True, disabled=disabled):
        try:
            result = restore_json_bytes(uploaded.getvalue(), mode)
            st.success(f"Banco importado. Restaurados: {result.get('restored', 0)} | Ignorados: {result.get('ignored', 0)}")
            st.caption("Depois de importar, use o botao lateral Enviar backup para GitHub.")
            st.rerun()
        except Exception as exc:
            st.error(f"Nao foi possivel importar o banco: {exc}")


def main() -> None:
    st.set_page_config(page_title="Estadias", page_icon="E", layout="wide")
    _apply_theme()
    username = _require_login()
    initialize_database()
    _restore_from_github_once()
    _render_github_sidebar()
    st.title("Estadias")
    st.caption("Sistema independente com banco proprio e backup direto no GitHub.")
    _render_status()
    page = st.sidebar.radio("Menu", MENU, key="main_menu")
    st.divider()

    if page == "Dashboard":
        render_dashboard_page()
    elif page == "Importacoes":
        render_imports_page(username, "ADMIN")
    elif page == "Base CONTROL":
        render_control_page()
    elif page == "Relatorios Rastreador por Placa":
        render_rastreador_page()
    elif page == "Cruzamento LCTE x CONTROL x Rastreador":
        render_cross_page(username)
    elif page == "TESTE LCTE x RASTREADOR":
        render_teste_lcte_rastreador_page(username)
    elif page == "Logs de Importacao":
        render_logs_page()
    elif page == "Configuracoes":
        render_config_page(username)
    elif page == "Backup do Banco":
        render_backup_page()

    _auto_backup_if_data_changed()


if __name__ == "__main__":
    main()
