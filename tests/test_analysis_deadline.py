import sqlite3
import os
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
from src.database.connection import DbConnection
from src.database.migrations import create_modular_tables
from src.modules.estadias.page import _analysis_deadline_status
from estadias_app import github_backup


class AnalysisDeadlineTest(unittest.TestCase):
    def test_write_marks_backup_check_without_database_scan(self):
        state = {}
        with patch.object(repository.st, "cache_data", create=True) as cache, patch.object(repository.st, "session_state", state, create=True):
            repository._invalidate_read_cache()
        cache.clear.assert_called_once()
        self.assertTrue(state["estadias_data_changed"])

    def test_existing_analysis_dates_migrate_once(self):
        with sqlite3.connect(":memory:") as raw:
            raw.row_factory = sqlite3.Row
            conn = DbConnection(raw, "sqlite")
            create_modular_tables(conn)
            raw.execute(f"drop table {repository.ANALYSIS_TABLE}")
            raw.execute(f"insert into {repository.CROSS_TABLE} (lcte_id, nf, analise_enviada_em) values (1, '123', '2026-09-29T10:00:00')")
            create_modular_tables(conn)
            dates = raw.execute(f"select analise_enviada_em from {repository.ANALYSIS_TABLE} where lcte_id = 1").fetchone()[0]
            legacy = raw.execute(f"select analise_enviada_em from {repository.CROSS_TABLE} where lcte_id = 1").fetchone()[0]
            create_modular_tables(conn)
            self.assertEqual(raw.execute(f"select count(*) from {repository.ANALYSIS_TABLE}").fetchone()[0], 1)
        self.assertEqual(dates, "2026-09-29T10:00:00")
        self.assertEqual(legacy, "")

    def test_fifteen_day_deadline_and_response(self):
        sent = "2026-09-29T10:00:00"
        self.assertEqual(_analysis_deadline_status(sent, "", datetime(2026, 10, 14, 9)), ("14/10/2026 10:00", "Aguardando resposta"))
        self.assertEqual(_analysis_deadline_status(sent, "", datetime(2026, 10, 14, 11))[1], "Prazo vencido")
        self.assertEqual(_analysis_deadline_status(sent, "2026-10-15T12:00:00", datetime(2026, 10, 16))[1], "Respondida")

    def test_marking_keeps_original_sent_time(self):
        with sqlite3.connect(":memory:") as conn:
            conn.execute(f"create table {repository.CROSS_TABLE} (lcte_id integer, nf text)")
            conn.execute(f"create table {repository.ANALYSIS_TABLE} (lcte_id integer primary key, nf text, analise_enviada_em text, analise_respondida_em text, atualizado_em text, atualizado_por text)")
            conn.execute(f"insert into {repository.CROSS_TABLE} values (1, '123')")
            with patch.object(repository, "get_connection", return_value=conn), patch.object(repository, "registrar_status_evento"), patch.object(repository, "_invalidate_read_cache"):
                repository.save_analysis_flags(1, True, False, "tester")
                sent = conn.execute(f"select analise_enviada_em from {repository.ANALYSIS_TABLE}").fetchone()[0]
                repository.save_analysis_flags(1, True, True, "tester")
                stored = conn.execute(f"select analise_enviada_em, analise_respondida_em from {repository.ANALYSIS_TABLE}").fetchone()
        self.assertEqual(stored[0], sent)
        self.assertTrue(stored[1])

    def test_separate_backup_contains_only_invoice_and_mark_dates(self):
        rows = pd.DataFrame([{"nf": "12345", "analise_enviada_em": "2026-09-29T10:00:00", "analise_respondida_em": ""}])
        with patch.object(github_backup, "github_backup_configured", return_value=True), patch.object(github_backup, "read_sql", return_value=rows), patch.object(github_backup, "github_settings", return_value={}), patch.object(github_backup, "_upload_bytes") as upload:
            result = github_backup.backup_analysis_marks_to_github()
        self.assertEqual(result["status"], "SUCESSO")
        self.assertEqual(upload.call_args.args[1], "backups/estadias_analises.csv")
        self.assertEqual(upload.call_args.args[2].decode("utf-8-sig"), "Nota fiscal,Enviada em,Respondida em\r\n12345,2026-09-29T10:00:00,\r\n")

    def test_analysis_backup_runs_at_19_brasilia_time(self):
        before = datetime(2026, 9, 29, 18, 30)
        after = datetime(2026, 9, 29, 19, 1)
        self.assertEqual(github_backup._seconds_until_analysis_backup(before, None), 1800)
        self.assertEqual(github_backup._seconds_until_analysis_backup(after, None), 0)
        self.assertGreater(github_backup._seconds_until_analysis_backup(after, after.date()), 23 * 3600)

    def test_backup_branch_is_separate_from_deployed_main(self):
        with patch.dict(os.environ, {"GITHUB_BRANCH": "main"}, clear=True):
            self.assertEqual(github_backup.github_settings()["branch"], "backup-data")

    def test_receive_marks_skips_ambiguous_invoices(self):
        csv_backup = "Nota fiscal,Enviada em,Respondida em\n123,2026-09-29T10:00:00,\n456,2026-09-29T11:00:00,\n"
        current = pd.DataFrame([
            {"lcte_id": 1, "nf": "123", "analise_enviada_em": None, "analise_respondida_em": None},
            {"lcte_id": 2, "nf": "456", "analise_enviada_em": "", "analise_respondida_em": ""},
            {"lcte_id": 3, "nf": "456", "analise_enviada_em": "", "analise_respondida_em": ""},
        ])
        with patch.object(github_backup, "github_backup_configured", return_value=True), patch.object(github_backup, "github_settings", return_value={}), patch.object(github_backup, "_download_text", return_value=csv_backup), patch.object(github_backup, "read_sql", return_value=current), patch.object(github_backup, "restore_analysis_dates", return_value=1) as restore:
            result = github_backup.restore_analysis_marks_from_github("tester", dry_run=False)
        self.assertEqual((result["restored"], result["ambiguous"]), (1, 1))
        restore.assert_called_once_with([(1, "2026-09-29T10:00:00", "")], "tester")

    def test_receive_marks_preserves_existing_date(self):
        with sqlite3.connect(":memory:") as conn:
            conn.execute(f"create table {repository.CROSS_TABLE} (lcte_id integer, nf text)")
            conn.execute(f"create table {repository.ANALYSIS_TABLE} (lcte_id integer primary key, nf text, analise_enviada_em text, analise_respondida_em text, atualizado_em text, atualizado_por text)")
            conn.execute(f"insert into {repository.CROSS_TABLE} values (1, '123')")
            conn.execute(f"insert into {repository.ANALYSIS_TABLE} values (1, '123', '2026-09-28T09:00:00', '', '', '')")
            with patch.object(repository, "get_connection", return_value=conn), patch.object(repository, "_invalidate_read_cache"):
                repository.restore_analysis_dates([(1, "2026-09-29T10:00:00", "2026-09-30T12:00:00")], "tester")
                dates = conn.execute(f"select analise_enviada_em, analise_respondida_em from {repository.ANALYSIS_TABLE}").fetchone()
        self.assertEqual(dates, ("2026-09-28T09:00:00", "2026-09-30T12:00:00"))


if __name__ == "__main__":
    unittest.main()
