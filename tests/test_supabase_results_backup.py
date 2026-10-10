import json
import unittest
from unittest.mock import MagicMock, patch

from estadias_app import supabase_results_backup as backup
from src.modules.estadias.repository import CROSS_TABLE


class SupabaseResultsBackupTest(unittest.TestCase):
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
