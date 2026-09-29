import sqlite3
import sys
import types
import unittest
from io import BytesIO
from unittest.mock import patch
from zipfile import ZIP_STORED, ZipFile

import pandas as pd
from pypdf import PdfReader

streamlit = types.ModuleType("streamlit")
streamlit.cache_data = lambda **kwargs: lambda func: func
sys.modules.setdefault("streamlit", streamlit)

from src.modules.estadias import repository
from src.modules.estadias import page
from src.modules.estadias.page import _estadia_period_specs


class PdfPositionPeriodTest(unittest.TestCase):
    def test_zip_reuses_selected_specs_and_snapshot_positions(self):
        spec = {
            "lcte_id": 10, "tipo": "DESTINO", "placa": "ABC1234", "nf": "86135",
            "chegada": "2026-08-16 10:00:00", "saida": "2026-08-17 10:00:00",
        }
        positions = pd.DataFrame([{
            "placa_norm": "ABC1234", "data_hora": "2026-08-16 12:00:00",
            "cidade": "SANTOS", "velocidade": 0, "fonte": "RASTREADOR_RESUMIDO_30_MIN",
        }])
        with patch.object(page, "_estadia_period_specs", side_effect=AssertionError("nao recalcular")), patch.object(
            page, "_sample_positions_for_result", side_effect=AssertionError("ja resumido")
        ), patch.object(page, "read_estadia_positions_period", return_value=positions):
            result = page._tracker_positions_pdf_zip([spec], [0])
        with ZipFile(BytesIO(result)) as archive:
            item = archive.infolist()[0]
            self.assertEqual(item.compress_type, ZIP_STORED)
            text = PdfReader(BytesIO(archive.read(item.filename))).pages[0].extract_text()
        self.assertIn("86135", text)

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
