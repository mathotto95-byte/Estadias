import unittest
from unittest.mock import MagicMock, patch

from estadias_app import github_backup


class RestorePostgresTest(unittest.TestCase):
    def test_failed_row_aborts_restore_instead_of_committing_partial_data(self):
        conn = MagicMock()
        conn.db_type = "postgres"
        conn.execute.side_effect = [None, RuntimeError("invalid row")]
        context = MagicMock()
        context.__enter__.return_value = conn

        payload = {
            "schema": "estadias_importacoes_backup_v1",
            "tables": {github_backup.LCTE_NORMALIZED_TABLE: [{"id": 1}, {"id": 2}]},
        }
        with patch.object(github_backup, "get_connection", return_value=context), \
             patch.object(github_backup, "_table_exists", return_value=True), \
             patch.object(github_backup, "_table_columns", return_value=["id"]):
            with self.assertRaisesRegex(ValueError, "linha 2"):
                github_backup.restore_payload(payload, "merge")
        self.assertEqual(context.__exit__.call_args.args[0], ValueError)

    def test_restored_ids_advance_postgres_sequence(self):
        conn = MagicMock()
        conn.db_type = "postgres"
        context = MagicMock()
        context.__enter__.return_value = conn
        payload = {
            "schema": "estadias_importacoes_backup_v1",
            "tables": {github_backup.LCTE_NORMALIZED_TABLE: [{"id": 42}]},
        }
        with patch.object(github_backup, "get_connection", return_value=context), \
             patch.object(github_backup, "_table_exists", return_value=True), \
             patch.object(github_backup, "_table_columns", return_value=["id"]):
            result = github_backup.restore_payload(payload, "merge")
        self.assertEqual(result["restored"], 1)
        self.assertIn("setval(pg_get_serial_sequence", conn.execute.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
