import sys
import types
import unittest

streamlit = types.ModuleType("streamlit")
streamlit.cache_data = lambda **kwargs: lambda func: func
sys.modules.setdefault("streamlit", streamlit)

from src.modules.estadias.imports import RASTREADOR_ALIASES, column_map, normalize_rastreador_row, read_tabular_file, validate_pgadmin_rastreador_csv


class PgAdminCsvTest(unittest.TestCase):
    def test_accepts_tracker_export_and_rejects_other_layout(self):
        content = (
            'Placa,Data,Município da referência,Cliente referência,Referência,Latitude,Longitude\n'
            'AHQ9D00,2026-09-06 00:03:10,Carambeí,Cliente,Patio,-24.9,-50.1\n'
        ).encode("utf-8")
        validate_pgadmin_rastreador_csv(content)
        frame, _ = read_tabular_file("rastreador.csv", content)
        row = normalize_rastreador_row(frame.iloc[0].to_dict(), column_map(frame, RASTREADOR_ALIASES), {}, "")
        self.assertEqual((row["placa_norm"], row["data_hora"], row["cidade"]), ("AHQ9D00", "2026-09-06 00:03:10", "CARAMBEI"))
        with self.assertRaisesRegex(ValueError, "Colunas ausentes"):
            validate_pgadmin_rastreador_csv(b"foo,bar\n1,2\n")


if __name__ == "__main__":
    unittest.main()
