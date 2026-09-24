"""Tema visual Rodo Wall (azul e dourado) para Streamlit.

Arquivo autocontido: depende apenas de streamlit (e, opcionalmente, Pillow).
Para usar em outro projeto, copie este arquivo e chame no inicio do app:

    from rw_theme import apply_theme, render_brand_header
    apply_theme("assets/rodo_wall_logo.png")
    render_brand_header("Titulo", "Subtitulo")
"""
from __future__ import annotations

import base64
import html
import io
from functools import lru_cache
from pathlib import Path

import streamlit as st

# "gold": logo original tingida de dourado (a arte original e escura e some no fundo azul).
# "original": cores originais, sobre uma placa clara.
_state = {"style": "gold", "has_logo": False}

_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap');
:root {
  --rw-bg: #030914; --rw-panel: #071526; --rw-navy: #020d3f;
  --rw-blue: #2563eb; --rw-gold: #d4af37; --rw-gold-d: #c49a12;
  --rw-border: rgba(212, 175, 55, 0.30); --rw-text: #f8fafc; --rw-muted: rgba(248, 250, 252, 0.68);
  --rw-ok: #34d399; --rw-bad: #f87171;
  --rw-logo-url: url("__LOGO__"); --rw-logo-ratio: __RATIO__;
}
html, body, .stApp, .stMarkdown, p, label, h1, h2, h3, h4, button, input, textarea {
  font-family: Inter, system-ui, -apple-system, "Segoe UI", Arial, sans-serif;
}
.stApp {background: var(--rw-bg) !important; color: var(--rw-text) !important;}
[data-testid="stHeader"] {background: transparent !important;}
.block-container {padding: 1.1rem clamp(0.75rem, 2vw, 2rem) 2rem; max-width: none; width: 100%;}
h1, h2, h3, label, p, span, div {color: var(--rw-text);}
h1, h2, h3 {font-weight: 800;}
h1 {font-size: 2rem !important;}
h2 {font-size: 1.6rem !important;}
hr {border-color: var(--rw-border) !important;}
[data-testid="stCaptionContainer"] p {color: var(--rw-muted) !important;}
[data-testid="stSidebar"] {background: var(--rw-navy) !important; border-right: 1px solid var(--rw-border);}
[data-testid="stSidebar"] * {color: var(--rw-text) !important;}

/* Cartoes de metrica */
div[data-testid="stMetric"] {background: var(--rw-panel); border: 1px solid var(--rw-border); border-left: 4px solid var(--rw-gold); border-radius: 8px; padding: 14px 16px;}
div[data-testid="stMetric"] [data-testid="stMetricValue"] * {color: var(--rw-text) !important; font-weight: 800;}
div[data-testid="stMetric"] [data-testid="stMetricLabel"] * {color: var(--rw-muted) !important; font-size: 0.68rem !important; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; white-space: normal !important; overflow: visible !important; text-overflow: clip !important; line-height: 1.25;}

/* Containers, expanders e tabelas */
div[data-testid="stExpander"], div[data-testid="stVerticalBlockBorderWrapper"] {background: rgba(7, 21, 38, 0.72); border: 1px solid var(--rw-border); border-radius: 8px;}
div[data-testid="stDataFrame"] {border: 1px solid var(--rw-border); border-radius: 8px; min-width: 0;}

[data-testid="stForm"] {border: none !important; padding: 0 !important;}

/* Abas */
button[data-baseweb="tab"] {color: var(--rw-muted); font-weight: 600;}
button[data-baseweb="tab"][aria-selected="true"], button[data-baseweb="tab"][aria-selected="true"] * {color: var(--rw-gold) !important;}
[data-baseweb="tab-highlight"] {background-color: var(--rw-gold) !important; height: 3px !important;}
[data-baseweb="tab-border"] {background-color: var(--rw-border) !important;}

/* Botoes: secundario = contorno dourado; primario = dourado cheio */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {
  background: transparent; border: 1px solid var(--rw-gold); border-radius: 8px; color: var(--rw-gold) !important; font-weight: 700;
}
.stButton > button *, .stDownloadButton > button *, .stFormSubmitButton > button * {color: inherit !important;}
.stButton > button:hover, .stDownloadButton > button:hover, .stFormSubmitButton > button:hover {background: rgba(212, 175, 55, 0.14); border-color: var(--rw-gold); color: var(--rw-gold) !important;}
.stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"],
button[data-testid="stBaseButton-primary"], button[data-testid="stBaseButton-primaryFormSubmit"] {
  background: var(--rw-gold); border-color: var(--rw-gold); color: var(--rw-navy) !important;
}
.stButton > button[kind="primary"]:hover, .stDownloadButton > button[kind="primary"]:hover, .stFormSubmitButton > button[kind="primary"]:hover,
button[data-testid="stBaseButton-primary"]:hover, button[data-testid="stBaseButton-primaryFormSubmit"]:hover {
  background: var(--rw-gold-d); border-color: var(--rw-gold-d); color: var(--rw-navy) !important;
}

/* Campos */
[data-baseweb="input"], [data-baseweb="select"] > div {background: var(--rw-panel) !important; border-color: var(--rw-border) !important;}
[data-baseweb="input"]:focus-within, [data-baseweb="select"] > div:focus-within {border-color: var(--rw-gold) !important; box-shadow: 0 0 0 3px rgba(212, 175, 55, 0.18);}
[data-baseweb="input"] input, [data-baseweb="select"] div {color: var(--rw-text) !important;}

/* Marca */
.rw-logo {display: block; aspect-ratio: var(--rw-logo-ratio); background: var(--rw-gold); -webkit-mask: var(--rw-logo-url) center / contain no-repeat; mask: var(--rw-logo-url) center / contain no-repeat;}
.rw-logo--original {background: var(--rw-logo-url) center / contain no-repeat; -webkit-mask: none; mask: none;}
.rw-plate {background: #f8f5ec; border-radius: 12px; padding: 10px 16px; display: inline-block;}
.rw-header {display: flex; align-items: center; gap: 18px; padding: 4px 0 14px; margin-bottom: 12px; border-bottom: 2px solid var(--rw-gold);}
.rw-title {font-size: 1.9rem; font-weight: 800; line-height: 1.1; color: var(--rw-text);}
.rw-sub {font-size: 0.85rem; color: var(--rw-muted); margin-top: 4px;}
.rw-login-head {text-align: center; padding: 6px 0 10px;}
.rw-login-head .rw-title {font-size: 1.6rem; margin-top: 10px;}

/* Selos de status */
.rw-badge {display: inline-block; padding: 3px 10px; border-radius: 999px; font-size: 0.72rem; font-weight: 700;}
.rw-badge--ok {background: rgba(52, 211, 153, 0.14); color: var(--rw-ok);}
.rw-badge--warn {background: rgba(212, 175, 55, 0.16); color: var(--rw-gold);}
.rw-badge--info {background: rgba(37, 99, 235, 0.22); color: #93b4ff;}
.rw-badge--bad {background: rgba(248, 113, 113, 0.14); color: var(--rw-bad);}
.rw-badge--muted {background: rgba(255, 255, 255, 0.08); color: var(--rw-muted);}
"""


@lru_cache(maxsize=8)
def _logo_data(path: str, width: int = 360) -> tuple[str, float]:
    """Retorna (data URI, proporcao largura/altura). Vazio se o arquivo nao existir."""
    file = Path(path)
    if not file.is_file():
        return "", 1.0
    data = file.read_bytes()
    ratio = 1.0
    try:
        from PIL import Image

        image = Image.open(io.BytesIO(data)).convert("RGBA")
        if image.width > width:
            image = image.resize((width, round(image.height * width / image.width)), Image.LANCZOS)
        ratio = image.width / image.height
        buffer = io.BytesIO()
        image.save(buffer, "PNG", optimize=True)
        data = buffer.getvalue()
    except Exception:
        pass
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii"), ratio


def apply_theme(logo_path: str | Path | None = None, logo_style: str = "gold") -> None:
    """Injeta o CSS do tema. Chame uma vez por execucao, antes de renderizar a pagina."""
    uri, ratio = _logo_data(str(logo_path)) if logo_path else ("", 1.0)
    _state["style"] = "original" if logo_style == "original" else "gold"
    _state["has_logo"] = bool(uri)
    css = _CSS.replace("__LOGO__", uri).replace("__RATIO__", f"{ratio:.4f}")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def _logo_html(width: int, center: bool = False) -> str:
    if not _state["has_logo"]:
        return ""
    original = _state["style"] == "original"
    margin = "margin: 0 auto;" if center else ""
    css_class = "rw-logo rw-logo--original" if original else "rw-logo"
    logo = f'<div class="{css_class}" role="img" aria-label="Rodo Wall" style="width: {width}px; {margin}"></div>'
    if original:
        return f'<div class="rw-plate">{logo}</div>'
    return logo


def render_brand_header(title: str, subtitle: str = "", logo_width: int = 130) -> None:
    sub = f'<div class="rw-sub">{html.escape(subtitle)}</div>' if subtitle else ""
    st.markdown(
        f'<div class="rw-header">{_logo_html(logo_width)}<div><div class="rw-title">{html.escape(title)}</div>{sub}</div></div>',
        unsafe_allow_html=True,
    )


def render_login_header(title: str, subtitle: str = "", logo_width: int = 200) -> None:
    sub = f'<div class="rw-sub">{html.escape(subtitle)}</div>' if subtitle else ""
    st.markdown(
        f'<div class="rw-login-head">{_logo_html(logo_width, center=True)}<div class="rw-title">{html.escape(title)}</div>{sub}</div>',
        unsafe_allow_html=True,
    )


def render_sidebar_logo(width: int = 150) -> None:
    logo = _logo_html(width, center=True)
    if logo:
        st.sidebar.markdown(f'<div style="text-align: center; padding: 4px 0 8px;">{logo}</div>', unsafe_allow_html=True)


def badge(text: str, kind: str = "info") -> str:
    """HTML de um selo de status. Use com st.markdown(..., unsafe_allow_html=True). kind: ok, warn, info, bad, muted."""
    kind = kind if kind in {"ok", "warn", "info", "bad", "muted"} else "info"
    return f'<span class="rw-badge rw-badge--{kind}">{html.escape(str(text))}</span>'
