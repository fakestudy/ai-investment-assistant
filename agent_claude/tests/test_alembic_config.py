from configparser import ConfigParser
from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class AlembicConfigTest(unittest.TestCase):
    def test_alembic_ini_points_to_migrations_directory(self) -> None:
        config_path = PROJECT_ROOT / "alembic.ini"
        self.assertTrue(config_path.exists())

        parser = ConfigParser()
        parser.read(config_path)

        self.assertEqual(parser.get("alembic", "script_location"), "migrations")

    def test_revision_template_exists(self) -> None:
        template_path = PROJECT_ROOT / "migrations" / "script.py.mako"

        self.assertTrue(template_path.exists())


if __name__ == "__main__":
    unittest.main()
