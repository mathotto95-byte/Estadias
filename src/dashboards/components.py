from __future__ import annotations

import hashlib
import inspect
import re

import pandas as pd
import streamlit as st


def metric_grid(metrics: dict[str, object], columns: int = 4) -> None:
    cols = st.columns(columns)
    for index, (label, value) in enumerate(metrics.items()):
        cols[index % columns].metric(label, value)


def _sanitize_widget_key(value: object) -> str:
    value = str(value or "")
    value = re.sub(r"[^a-zA-Z0-9_-]+", "_", value)
    return value.strip("_").lower()


def _build_dataframe_widget_key(
    df: pd.DataFrame,
    height: int,
    max_rows: int,
    table_name: str | None,
) -> str:
    caller = next((frame for frame in inspect.stack()[2:] if frame.function != "render_dataframe"), None)
    caller_signature = ""
    if caller is not None:
        caller_signature = f"{caller.filename}|{caller.function}|{caller.lineno}"
    columns_signature = "|".join(map(str, df.columns))
    raw_signature = f"{table_name}|{caller_signature}|{columns_signature}|{len(df)}|{height}|{max_rows}"
    digest = hashlib.md5(raw_signature.encode("utf-8")).hexdigest()[:10]
    fallback_name = caller.function if caller is not None else "dataframe"
    base_name = _sanitize_widget_key(table_name or fallback_name)
    return f"rows_{base_name}_{digest}"


def render_dataframe(
    df: pd.DataFrame | None,
    height: int = 460,
    max_rows: int = 500,
    key: str | None = None,
    table_name: str | None = None,
    **kwargs,
) -> None:
    if df is None:
        return
    if df.empty:
        st.info("Sem dados para exibir.")
        return
    if key is None:
        key = _build_dataframe_widget_key(df, height, max_rows, table_name)
    max_visible_rows = max(1, min(max_rows, len(df))) if max_rows else max(1, len(df))
    visible_rows = st.number_input(
        "Linhas exibidas",
        min_value=1,
        max_value=max_visible_rows,
        value=min(100, max_visible_rows),
        step=10,
        key=key,
    )
    display_df = df.head(int(visible_rows))
    if len(display_df) < len(df):
        st.caption(f"Exibindo {len(display_df)} de {len(df)} registros. Use filtros ou exporte para ver o conjunto completo.")
    st.session_state.last_rendered_rows = len(display_df)
    st.session_state.last_available_rows = len(df)
    dataframe_kwargs = {
        "use_container_width": True,
        "hide_index": True,
        "height": height,
        "row_height": 28,
    }
    dataframe_kwargs.update(kwargs)
    try:
        st.dataframe(display_df, **dataframe_kwargs)
    except TypeError:
        dataframe_kwargs.pop("row_height", None)
        st.dataframe(display_df, **dataframe_kwargs)


def simple_bar_chart(df: pd.DataFrame, category: str, value: str, title: str, agg: str = "sum") -> None:
    st.subheader(title)
    if df.empty or category not in df or value not in df:
        st.info("Sem dados suficientes.")
        return
    if agg == "count":
        chart = df.groupby(category, dropna=False)[value].count().sort_values(ascending=False)
    else:
        chart = df.groupby(category, dropna=False)[value].sum(numeric_only=True).sort_values(ascending=False)
    st.bar_chart(chart)
