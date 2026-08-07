from __future__ import annotations

from io import BytesIO

import pandas as pd


def _column_width(df: pd.DataFrame, column: str) -> int:
    if df.empty:
        return 12
    data = df[column]
    if isinstance(data, pd.DataFrame):
        data = data.iloc[:, 0]
    lengths = data.fillna("").astype(str).str.len()
    width = lengths.quantile(0.9)
    if pd.isna(width):
        return 12
    return max(12, min(45, int(width) + 2))


def dataframe_to_excel(sheets: dict[str, pd.DataFrame]) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        for name, df in sheets.items():
            sheet_name = (name or "relatorio")[:31]
            df.to_excel(writer, sheet_name=sheet_name, index=False)
            worksheet = writer.sheets[sheet_name]
            for idx, column in enumerate(df.columns):
                worksheet.set_column(idx, idx, _column_width(df, column))
    return output.getvalue()
