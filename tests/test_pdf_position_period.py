import sqlite3
import sys
import types
import unittest
from unittest.mock import patch

import pandas as pd

streamlit = types.ModuleType("streamlit")
streamlit.cache_data = lambda **kwargs: lambda func: func
sys.modules.setdefault("streamlit", streamlit)

from src.modules.estadias import repository
from src.modules.estadias.page import _estadia_period_specs


class PdfPositionPeriodTest(unittest.TestCase):
    def test_pdf_uses_lcte_trip_id_not_cross_row_id(self):
        rows = pd.DataFrame([{
            "id": 99, "lcte_id": 10, "nf": "86135", "placa_norm": "ABC1234",
            "chegada_destino": "2026-08-16 10:00:00", "saida_destino": "2026-08-17 10:00:00",
            "estadia_descarga_min": 60,
        }])
        self.assertEqual(_estadia_period_specs(rows)[0]["lcte_id"], 10)

    def test_same_trip_id_never_brings_other_plate_or_date(self):
        with sqlite3.connect(":memory:") as conn:
            conn.execute(f"create table {repository.ESTADIA_POSITIONS_TABLE} (lcte_id integer, tipo_estadia text, placa_norm text, data_hora text)")
            conn.executemany(
                f"insert into {repository.ESTADIA_POSITIONS_TABLE} values (?, ?, ?, ?)",
                [
                    (10, "DESTINO", "ABC1234", "2026-08-16 12:00:00"),
                    (10, "DESTINO", "ABC1234", "2026-09-01 12:00:00"),
                    (10, "DESTINO", "XYZ9876", "2026-08-16 13:00:00"),
                ],
            )
            with patch.object(repository, "table_exists", return_value=True), patch.object(
                repository, "read_sql", side_effect=lambda sql, params: pd.read_sql_query(sql, conn, params=params)
            ):
                rows = repository.read_estadia_positions_period(
                    10, "DESTINO", "ABC1234", "2026-08-16 00:00:00", "2026-08-17 00:00:00"
                )
        self.assertEqual(rows["data_hora"].tolist(), ["2026-08-16 12:00:00"])


if __name__ == "__main__":
    unittest.main()
