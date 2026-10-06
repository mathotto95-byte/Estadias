import sqlite3
import json
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
from src.modules.estadias.page import _analysis_deadline_status, _apply_summary_filters, _build_cross_summary_table
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
        rows = pd.DataFrame([{"nf": "12345", "analise_enviada_em": "2026-09-29T10:00:00", "analise_respondida_em": "", "sem_tratativa_origem": 1, "sem_tratativa_destino": 0}])
        with patch.object(github_backup, "github_backup_configured", return_value=True), patch.object(github_backup, "read_sql", return_value=rows), patch.object(github_backup, "github_settings", return_value={}), patch.object(github_backup, "_upload_bytes") as upload:
            result = github_backup.backup_analysis_marks_to_github()
        self.assertEqual(result["status"], "SUCESSO")
        self.assertEqual(upload.call_args.args[1], "backups/estadias_analises.csv")
        self.assertEqual(upload.call_args.args[2].decode("utf-8-sig"), "Nota fiscal,Enviada em,Respondida em,Sem tratativa origem,Sem tratativa destino\r\n12345,2026-09-29T10:00:00,,1,0\r\n")

    def test_no_treatment_is_per_location_and_can_be_undone(self):
        with sqlite3.connect(":memory:") as conn:
            conn.execute(f"create table {repository.CROSS_TABLE} (lcte_id integer, nf text)")
            conn.execute(f"create table {repository.ANALYSIS_TABLE} (lcte_id integer primary key, nf text, analise_enviada_em text, analise_respondida_em text, sem_tratativa_origem integer default 0, sem_tratativa_destino integer default 0, atualizado_em text, atualizado_por text)")
            conn.execute(f"insert into {repository.CROSS_TABLE} values (1, '123')")
            with patch.object(repository, "get_connection", return_value=conn), patch.object(repository, "registrar_status_evento"), patch.object(repository, "_invalidate_read_cache"):
                repository.save_no_treatment_flag(1, "ORIGEM", True, "tester")
                flags = conn.execute(f"select sem_tratativa_origem, sem_tratativa_destino from {repository.ANALYSIS_TABLE}").fetchone()
                repository.save_no_treatment_flag(1, "ORIGEM", False, "tester")
                undone = conn.execute(f"select sem_tratativa_origem from {repository.ANALYSIS_TABLE}").fetchone()[0]
        self.assertEqual(flags, (1, 0))
        self.assertEqual(undone, 0)

    def test_no_treatment_hides_only_marked_line(self):
        cross = pd.DataFrame([{"lcte_id": 1, "nf": "123", "placa_norm": "ABC1234", "encontrou_origem": 1, "encontrou_destino": 1,
                               "tempo_origem_min": 1500, "tempo_destino_min": 1500, "estadia_carga_min": 60, "estadia_descarga_min": 60,
                               "sem_tratativa_origem": 1, "sem_tratativa_destino": 0}])
        summary = _build_cross_summary_table(cross)
        self.assertEqual(_apply_summary_filters(summary, {"tratativa": "Ativos"})["Tipo"].tolist(), ["DESTINO"])
        self.assertEqual(_apply_summary_filters(summary, {"tratativa": "Sem tratativa"})["Tipo"].tolist(), ["ORIGEM"])

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

    def test_receive_no_treatment_without_analysis_dates(self):
        csv_backup = "Nota fiscal,Enviada em,Respondida em,Sem tratativa origem,Sem tratativa destino\n123,,,1,0\n"
        current = pd.DataFrame([{"lcte_id": 1, "nf": "123", "analise_enviada_em": None, "analise_respondida_em": None,
                                 "sem_tratativa_origem": 0, "sem_tratativa_destino": 0}])
        with patch.object(github_backup, "github_backup_configured", return_value=True), patch.object(github_backup, "github_settings", return_value={}), patch.object(github_backup, "_download_text", return_value=csv_backup), patch.object(github_backup, "read_sql", return_value=current), patch.object(github_backup, "save_no_treatment_flag") as save:
            result = github_backup.restore_analysis_marks_from_github("tester", dry_run=False)
        self.assertEqual((result["ready"], result["restored"]), (1, 1))
        save.assert_called_once_with(1, "ORIGEM", True, "tester")

    def test_old_complete_backup_remains_valid(self):
        old_tables = {table: [] for table in github_backup.BACKUP_TABLES if table != repository.ANALYSIS_TABLE}
        old_tables[repository.CROSS_TABLE] = [{"lcte_id": 1}]
        imports = {table: [] for table in github_backup.IMPORT_BACKUP_TABLES}
        payload = {"schema": "estadias_completo_v1",
                   "results": {"schema": "estadias_backup_v1", "tables": old_tables, "records": {table: len(rows) for table, rows in old_tables.items()}},
                   "imports": {"schema": "estadias_importacoes_backup_v1", "tables": imports, "records": {table: 0 for table in imports}}}
        self.assertTrue(github_backup._valid_complete_backup(json.dumps(payload).encode()))

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
