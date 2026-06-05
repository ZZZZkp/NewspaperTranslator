import pathlib
import sys
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

try:
    from newspaper_translator.config import AppSettings, ConfigurationError, GeminiSettings, MineruSettings
except ImportError:
    AppSettings = None
    ConfigurationError = None
    GeminiSettings = None
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

    def test_gmail_config_path_is_optional_and_defaults_to_empty(self) -> None:
        self.assertIsNotNone(AppSettings, "AppSettings should be importable from newspaper_translator.config")

        env = {
            "APP_ENV": "test",
            "DATABASE_URL": "sqlite:///tmp/newspaper-translator.db",
            "STORAGE_ROOT": "/tmp/newspaper-translator-data",
        }

        settings = AppSettings.from_env(env)

        self.assertEqual(settings.gmail_config_path, "")

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

    def test_loads_gemini_settings_from_environment(self) -> None:
        self.assertIsNotNone(GeminiSettings, "GeminiSettings should be importable from newspaper_translator.config")

        env = {
            "GEMINI_TOKEN": "gemini-token",
            "GEMINI_MODEL": "gemini-2.5-flash",
            "GEMINI_TIMEOUT_SECONDS": "45",
        }

        settings = GeminiSettings.from_env(env)

        self.assertEqual(settings.api_token, "gemini-token")
        self.assertEqual(settings.model, "gemini-2.5-flash")
        self.assertEqual(settings.timeout_seconds, 45)

    def test_loads_gemini_proxy_settings_from_environment_when_compat_mode_is_enabled(self) -> None:
        self.assertIsNotNone(GeminiSettings, "GeminiSettings should be importable from newspaper_translator.config")

        env = {
            "GEMINI_API_COMPAT_MODE": "openai_compatible",
            "GOOGLE_GEMINI_BASE_URL": "https://nuoapi.com/v1beta",
            "GEMINI_API_KEY": "proxy-gemini-key",
            "GEMINI_MODEL": "gemini-2.5-flash",
            "GEMINI_TIMEOUT_SECONDS": "45",
        }

        settings = GeminiSettings.from_env(env)

        self.assertEqual(settings.api_token, "proxy-gemini-key")
        self.assertEqual(settings.base_url, "https://nuoapi.com/v1beta")
        self.assertEqual(settings.api_compat_mode, "openai_compatible")
        self.assertEqual(settings.model, "gemini-2.5-flash")
        self.assertEqual(settings.timeout_seconds, 45)

    def test_fails_fast_when_required_gemini_token_is_missing(self) -> None:
        self.assertIsNotNone(GeminiSettings, "GeminiSettings should be importable from newspaper_translator.config")
        self.assertIsNotNone(ConfigurationError, "ConfigurationError should be importable from newspaper_translator.config")

        env = {
            "GEMINI_TOKEN": "",
        }

        with self.assertRaises(ConfigurationError) as context:
            GeminiSettings.from_env(env)

        self.assertIn("GEMINI_TOKEN", str(context.exception))

    def test_fails_fast_when_required_proxy_gemini_api_key_is_missing(self) -> None:
        self.assertIsNotNone(GeminiSettings, "GeminiSettings should be importable from newspaper_translator.config")
        self.assertIsNotNone(ConfigurationError, "ConfigurationError should be importable from newspaper_translator.config")

        env = {
            "GEMINI_API_COMPAT_MODE": "openai_compatible",
            "GOOGLE_GEMINI_BASE_URL": "https://nuoapi.com/v1beta",
            "GEMINI_API_KEY": "",
        }

        with self.assertRaises(ConfigurationError) as context:
            GeminiSettings.from_env(env)

        self.assertIn("GEMINI_API_KEY", str(context.exception))


class DeepSeekSettingsTests(unittest.TestCase):
    def test_loads_deepseek_settings_from_environment(self) -> None:
        from newspaper_translator.config import DeepSeekSettings

        settings = DeepSeekSettings.from_env(
            {
                "DEEPSEEK_API_KEY": "deepseek-key",
                "DEEPSEEK_BASE_URL": "https://api.deepseek.com/",
                "DEEPSEEK_MODEL": "deepseek-chat",
                "DEEPSEEK_TIMEOUT_SECONDS": "45",
            }
        )

        self.assertEqual(settings.api_key, "deepseek-key")
        self.assertEqual(settings.base_url, "https://api.deepseek.com")
        self.assertEqual(settings.model, "deepseek-chat")
        self.assertEqual(settings.timeout_seconds, 45)

    def test_deepseek_settings_fail_fast_without_api_key(self) -> None:
        from newspaper_translator.config import ConfigurationError, DeepSeekSettings

        with self.assertRaises(ConfigurationError):
            DeepSeekSettings.from_env({"DEEPSEEK_MODEL": "deepseek-chat"})

    def test_deepseek_settings_default_base_model_and_timeout(self) -> None:
        from newspaper_translator.config import DeepSeekSettings

        settings = DeepSeekSettings.from_env({"DEEPSEEK_API_KEY": "deepseek-key"})

        self.assertEqual(settings.base_url, "https://api.deepseek.com")
        self.assertEqual(settings.model, "deepseek-chat")
        self.assertEqual(settings.timeout_seconds, 120)


if __name__ == "__main__":
    unittest.main()
