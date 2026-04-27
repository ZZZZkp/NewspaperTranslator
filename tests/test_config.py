import pathlib
import sys
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

try:
    from newspaper_translator.config import AppSettings, ConfigurationError, MineruSettings
except ImportError:
    AppSettings = None
    ConfigurationError = None
    MineruSettings = None


class AppSettingsTests(unittest.TestCase):
    def test_loads_required_application_settings_from_environment(self) -> None:
        self.assertIsNotNone(AppSettings, "AppSettings should be importable from newspaper_translator.config")

        env = {
            "APP_ENV": "test",
            "DATABASE_URL": "sqlite:///tmp/newspaper-translator.db",
            "STORAGE_ROOT": "/tmp/newspaper-translator-data",
            "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
        }

        settings = AppSettings.from_env(env)

        self.assertEqual(settings.app_env, "test")
        self.assertEqual(settings.database_url, "sqlite:///tmp/newspaper-translator.db")
        self.assertEqual(settings.storage_root, "/tmp/newspaper-translator-data")
        self.assertEqual(settings.gmail_config_path, "/tmp/gmail-config.json")

    def test_fails_fast_when_required_gmail_config_path_is_missing(self) -> None:
        self.assertIsNotNone(AppSettings, "AppSettings should be importable from newspaper_translator.config")
        self.assertIsNotNone(ConfigurationError, "ConfigurationError should be importable from newspaper_translator.config")

        env = {
            "APP_ENV": "test",
            "DATABASE_URL": "sqlite:///tmp/newspaper-translator.db",
            "STORAGE_ROOT": "/tmp/newspaper-translator-data",
            "GMAIL_CONFIG_PATH": "",
        }

        with self.assertRaises(ConfigurationError) as context:
            AppSettings.from_env(env)

        self.assertIn("GMAIL_CONFIG_PATH", str(context.exception))

    def test_loads_mineru_settings_from_environment(self) -> None:
        self.assertIsNotNone(MineruSettings, "MineruSettings should be importable from newspaper_translator.config")

        env = {
            "MINERU_API_TOKEN": "mineru-token",
            "MINERU_MODEL_VERSION": "vlm",
            "MINERU_LANGUAGE": "en",
            "MINERU_ENABLE_OCR": "true",
            "MINERU_ENABLE_TABLE": "false",
            "MINERU_ENABLE_FORMULA": "true",
            "MINERU_PAGE_RANGES": "1-3",
            "MINERU_POLL_INTERVAL_SECONDS": "5",
            "MINERU_POLL_TIMEOUT_SECONDS": "120",
        }

        settings = MineruSettings.from_env(env)

        self.assertEqual(settings.api_token, "mineru-token")
        self.assertEqual(settings.model_version, "vlm")
        self.assertEqual(settings.language, "en")
        self.assertTrue(settings.enable_ocr)
        self.assertFalse(settings.enable_table)
        self.assertTrue(settings.enable_formula)
        self.assertEqual(settings.page_ranges, "1-3")
        self.assertEqual(settings.poll_interval_seconds, 5)
        self.assertEqual(settings.poll_timeout_seconds, 120)

    def test_fails_fast_when_required_mineru_token_is_missing(self) -> None:
        self.assertIsNotNone(MineruSettings, "MineruSettings should be importable from newspaper_translator.config")
        self.assertIsNotNone(ConfigurationError, "ConfigurationError should be importable from newspaper_translator.config")

        env = {
            "MINERU_API_TOKEN": "",
        }

        with self.assertRaises(ConfigurationError) as context:
            MineruSettings.from_env(env)

        self.assertIn("MINERU_API_TOKEN", str(context.exception))


if __name__ == "__main__":
    unittest.main()
