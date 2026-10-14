import json
import sys
import types
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

streamlit = types.ModuleType("streamlit")
streamlit.cache_data = lambda **kwargs: lambda func: func
sys.modules.setdefault("streamlit", streamlit)

from estadias_app import supabase_results_backup as backup
from src.modules.estadias.repository import CROSS_TABLE


class SupabaseResultsBackupTest(unittest.TestCase):
    def test_daily_schedule_runs_at_20_brasilia_and_catches_up(self):
        before = datetime(2026, 10, 14, 19, 30)
        after = datetime(2026, 10, 14, 20, 10)
        self.assertEqual(backup._seconds_until_daily_backup(before, None), 1800)
        self.assertEqual(backup._seconds_until_daily_backup(after, None), 0)
        self.assertEqual(backup._seconds_until_daily_backup(after, after.date()), (timedelta(days=1) - timedelta(minutes=10)).total_seconds())

    def test_scheduler_stays_off_without_supabase_connection(self):
        with patch.object(backup, "configured", return_value=False), patch.object(backup.threading, "Thread") as thread:
            backup.start_daily_backup_scheduler()
        thread.assert_not_called()

    def test_separate_password_overrides_url_password(self):
        secrets = {
            "ESTADIAS_RESULTADOS_DATABASE_URL": "postgresql://user:old@host:5432/postgres",
            "ESTADIAS_RESULTADOS_DB_PASSWORD": "new@password",
        }
        with patch.object(backup, "_read_secret", side_effect=secrets.get), patch.object(backup, "_connect_postgres") as connect:
            backup._connect()
        connect.assert_called_once_with(secrets["ESTADIAS_RESULTADOS_DATABASE_URL"], password="new@password")

    def test_connection_summary_never_exposes_password(self):
        url = "postgresql://estadias_backup.ref:secret@aws-1-sa-east-1.pooler.supabase.com:5432/postgres"
        with patch.object(backup, "_read_secret", return_value=url):
            summary = backup.connection_summary()
        self.assertEqual(summary["user"], "estadias_backup.ref")
        self.assertNotIn("secret", str(summary))

    def test_connection_summary_flags_missing_project_ref(self):
        url = "postgresql://estadias_backup:secret@aws-1-sa-east-1.pooler.supabase.com:5432/postgres"
        with patch.object(backup, "_read_secret", return_value=url):
            self.assertIn("IDENTIFICADOR", backup.connection_summary()["error"])

    def test_snapshot_requires_trips_and_ignores_generation_time_for_hash(self):
        with self.assertRaisesRegex(ValueError, "Nao ha resultados"):
            backup._snapshot({"tables": {CROSS_TABLE: []}})
        first = {"generated_at": "2026-10-10T10:00:00", "tables": {CROSS_TABLE: [{"lcte_id": 1}]}}
        second = first | {"generated_at": "2026-10-10T11:00:00"}
        _, first_hash, trips = backup._snapshot(first)
        _, second_hash, _ = backup._snapshot(second)
        self.assertEqual(trips, 1)
        self.assertEqual(first_hash, second_hash)

    def test_preview_estimates_two_slot_storage_without_writing(self):
        payload = {"tables": {CROSS_TABLE: [{"lcte_id": 1}]}}
        content, _, _ = backup._snapshot(payload)
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [("atual", "old", 100), ("anterior", "older", 50)]
        context = MagicMock()
        context.__enter__.return_value = conn
        with patch.object(backup, "backup_payload", return_value=payload), patch.object(backup, "_connect", return_value=context):
            estimate = backup.preview()
        self.assertEqual(estimate["bytes_armazenados_apos_envio"], len(content) + 100)
        self.assertEqual(estimate["variacao_bytes"], len(content) - 50)
        self.assertEqual(conn.execute.call_count, 1)

    def test_upload_writes_only_changed_snapshot(self):
        payload = {"schema": "estadias_backup_v1", "generated_at": "2026-10-10", "tables": {CROSS_TABLE: [{"lcte_id": 1}]}}
        conn = MagicMock()
        table_cursor = MagicMock()
        table_cursor.fetchone.return_value = ("estadias.resultado_backups",)
        current_cursor = MagicMock()
        current_cursor.fetchone.return_value = None
        conn.execute.side_effect = [table_cursor, current_cursor, MagicMock(), MagicMock()]
        context = MagicMock()
        context.__enter__.return_value = conn
        with patch.object(backup, "backup_payload", return_value=payload), patch.object(backup, "_connect", return_value=context):
            result = backup.upload()
        self.assertEqual(result["status"], "SUCESSO")
        self.assertEqual(conn.execute.call_count, 4)

    def test_manual_upload_does_not_rotate_automatic_copies(self):
        payload = {"schema": "estadias_completo_v1", "results": {"tables": {CROSS_TABLE: [{"lcte_id": 1}]}}, "imports": {"tables": {}}}
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = ("estadias.resultado_backups",)
        context = MagicMock()
        context.__enter__.return_value = conn
        with patch.object(backup, "_complete_backup_bytes", return_value=json.dumps(payload).encode()), patch.object(backup, "_valid_complete_backup", return_value=True), patch.object(backup, "_connect", return_value=context):
            result = backup.upload_manual()
        self.assertEqual(result["viagens"], 1)
        self.assertEqual(conn.execute.call_count, 2)
        self.assertIn("'manual'", conn.execute.call_args.args[0])
        self.assertNotIn("'anterior'", conn.execute.call_args.args[0])

    def test_manual_copy_can_be_downloaded(self):
        payload = {"schema": "estadias_completo_v1", "results": {"tables": {CROSS_TABLE: [{"lcte_id": 1}]}}, "imports": {"tables": {}}}
        content, digest, _ = backup._snapshot(payload)
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = (digest, content)
        context = MagicMock()
        context.__enter__.return_value = conn
        with patch.object(backup, "_connect", return_value=context):
            restored = backup.download("manual")
        self.assertEqual(json.loads(restored)["schema"], "estadias_completo_v1")

    def test_download_checks_hash(self):
        payload = {"schema": "estadias_backup_v1", "generated_at": "2026-10-10", "tables": {CROSS_TABLE: [{"lcte_id": 1}]}}
        content, digest, _ = backup._snapshot(payload)
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = (digest, content)
        context = MagicMock()
        context.__enter__.return_value = conn
        with patch.object(backup, "_connect", return_value=context):
            result = backup.download()
        self.assertEqual(json.loads(result)["tables"][CROSS_TABLE][0]["lcte_id"], 1)


if __name__ == "__main__":
    unittest.main()
