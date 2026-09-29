import sqlite3
import sys
import types
import unittest
from datetime import datetime
from unittest.mock import patch

streamlit = types.ModuleType("streamlit")
streamlit.cache_data = lambda **kwargs: lambda func: func
sys.modules.setdefault("streamlit", streamlit)

from src.modules.estadias import repository
from src.modules.estadias.page import _analysis_deadline_status


class AnalysisDeadlineTest(unittest.TestCase):
    def test_fifteen_day_deadline_and_response(self):
        sent = "2026-09-29T10:00:00"
        self.assertEqual(_analysis_deadline_status(sent, "", datetime(2026, 10, 14, 9)), ("14/10/2026 10:00", "Aguardando resposta"))
        self.assertEqual(_analysis_deadline_status(sent, "", datetime(2026, 10, 14, 11))[1], "Prazo vencido")
        self.assertEqual(_analysis_deadline_status(sent, "2026-10-15T12:00:00", datetime(2026, 10, 16))[1], "Respondida")

    def test_marking_keeps_original_sent_time(self):
        with sqlite3.connect(":memory:") as conn:
            conn.execute(f"create table {repository.CROSS_TABLE} (lcte_id integer, analise_enviada_em text, analise_respondida_em text, atualizado_em text, atualizado_por text)")
            conn.execute(f"insert into {repository.CROSS_TABLE} (lcte_id) values (1)")
            with patch.object(repository, "get_connection", return_value=conn), patch.object(repository, "registrar_status_evento"), patch.object(repository, "_invalidate_read_cache"):
                repository.save_analysis_flags(1, True, False, "tester")
                sent = conn.execute(f"select analise_enviada_em from {repository.CROSS_TABLE}").fetchone()[0]
                repository.save_analysis_flags(1, True, True, "tester")
                stored = conn.execute(f"select analise_enviada_em, analise_respondida_em from {repository.CROSS_TABLE}").fetchone()
        self.assertEqual(stored[0], sent)
        self.assertTrue(stored[1])


if __name__ == "__main__":
    unittest.main()
