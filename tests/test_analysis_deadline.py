import sqlite3
import sys
import types
import unittest
from datetime import datetime
from unittest.mock import patch

import pandas as pd

streamlit = types.ModuleType("streamlit")
streamlit.cache_data = lambda **kwargs: lambda func: func
sys.modules.setdefault("streamlit", streamlit)

from src.modules.estadias import repository
from src.modules.estadias.page import _analysis_deadline_status
from estadias_app import github_backup


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

    def test_separate_backup_contains_only_invoice_and_mark_dates(self):
        rows = pd.DataFrame([{"nf": "12345", "analise_enviada_em": "2026-09-29T10:00:00", "analise_respondida_em": ""}])
        with patch.object(github_backup, "github_backup_configured", return_value=True), patch.object(github_backup, "read_sql", return_value=rows), patch.object(github_backup, "github_settings", return_value={}), patch.object(github_backup, "_upload_bytes") as upload:
            result = github_backup.backup_analysis_marks_to_github()
        self.assertEqual(result["status"], "SUCESSO")
        self.assertEqual(upload.call_args.args[1], "backups/estadias_analises.csv")
        self.assertEqual(upload.call_args.args[2].decode("utf-8-sig"), "Nota fiscal,Enviada em,Respondida em\r\n12345,2026-09-29T10:00:00,\r\n")


if __name__ == "__main__":
    unittest.main()
