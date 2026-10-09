import unittest
from unittest.mock import patch

from src.database.connection import DatabaseConnectionError, get_database_config


class DatabaseSelectionTest(unittest.TestCase):
    def test_url_alone_does_not_switch_existing_app(self):
        with patch("src.database.connection._read_secret", side_effect=lambda key: {"DATABASE_URL": "postgresql://example", "ESTADIAS_POSTGRES_ENABLED": ""}.get(key, "")):
            self.assertEqual(get_database_config().db_type, "sqlite")

    def test_explicit_activation_uses_postgres(self):
        with patch("src.database.connection._read_secret", side_effect=lambda key: {"DATABASE_URL": "postgresql://example", "ESTADIAS_POSTGRES_ENABLED": "SIM"}.get(key, "")):
            self.assertEqual(get_database_config().db_type, "postgres")

    def test_activation_requires_url(self):
        with patch("src.database.connection._read_secret", side_effect=lambda key: {"DATABASE_URL": "", "ESTADIAS_POSTGRES_ENABLED": "SIM"}.get(key, "")):
            with self.assertRaises(DatabaseConnectionError):
                get_database_config()


if __name__ == "__main__":
    unittest.main()
