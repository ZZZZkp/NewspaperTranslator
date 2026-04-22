import pathlib
import sys
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

try:
    from newspaper_translator.config import AppSettings, ConfigurationError
except ImportError:
    AppSettings = None
    ConfigurationError = None


class AppSettingsTests(unittest.TestCase):
    def test_loads_required_application_settings_from_environment(self) -> None:
        self.assertIsNotNone(AppSettings, "AppSettings should be importable from newspaper_translator.config")

        env = {
            "APP_ENV": "test",
            "DATABASE_URL": "sqlite:///tmp/newspaper-translator.db",
            "STORAGE_ROOT": "/tmp/newspaper-translator-data",
            "GMAIL_CLIENT_ID": "client-id",
            "GMAIL_CLIENT_SECRET": "client-secret",
            "GMAIL_REFRESH_TOKEN": "refresh-token",
        }

        settings = AppSettings.from_env(env)

        self.assertEqual(settings.app_env, "test")
        self.assertEqual(settings.database_url, "sqlite:///tmp/newspaper-translator.db")
        self.assertEqual(settings.storage_root, "/tmp/newspaper-translator-data")
        self.assertEqual(settings.gmail_client_id, "client-id")
        self.assertEqual(settings.gmail_client_secret, "client-secret")
        self.assertEqual(settings.gmail_refresh_token, "refresh-token")

    def test_fails_fast_when_required_gmail_credentials_are_missing(self) -> None:
        self.assertIsNotNone(AppSettings, "AppSettings should be importable from newspaper_translator.config")
        self.assertIsNotNone(ConfigurationError, "ConfigurationError should be importable from newspaper_translator.config")

        env = {
            "APP_ENV": "test",
            "DATABASE_URL": "sqlite:///tmp/newspaper-translator.db",
            "STORAGE_ROOT": "/tmp/newspaper-translator-data",
            "GMAIL_CLIENT_ID": "client-id",
            "GMAIL_CLIENT_SECRET": "",
            "GMAIL_REFRESH_TOKEN": "refresh-token",
        }

        with self.assertRaises(ConfigurationError) as context:
            AppSettings.from_env(env)

        self.assertIn("GMAIL_CLIENT_SECRET", str(context.exception))


if __name__ == "__main__":
    unittest.main()
