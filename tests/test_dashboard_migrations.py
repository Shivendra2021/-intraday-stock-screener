import os
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestDashboardAndMigrations(unittest.TestCase):
    def test_ensure_research_tables_creates_dashboard_core_tables(self):
        import modules.db_migrations as migrations

        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test.db")
            with patch.dict("os.environ", {}, clear=False):
                with patch("config.DB_PATH", db_path):
                    migrations.ensure_research_tables()

            conn = sqlite3.connect(db_path)
            try:
                tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            finally:
                conn.close()

        for table in {"stock_universe", "picks", "daily_accuracy", "patterns", "price_validations"}:
            self.assertIn(table, tables)

    def test_dashboard_health_returns_json_with_empty_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "dashboard.db")
            with patch("config.DB_PATH", db_path):
                from modules.db_migrations import ensure_research_tables
                ensure_research_tables()

                import dashboard.app as dashboard_app
                dashboard_app.DB_PATH = db_path
                dashboard_app._ensure_dashboard_db()
                with dashboard_app.app.test_client() as client:
                    response = client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn("bot_status", payload)
        self.assertIn("universe_count", payload)


if __name__ == "__main__":
    unittest.main()
