from dataclasses import dataclass
from typing import Mapping


class ConfigurationError(ValueError):
    """Raised when required application configuration is missing."""


@dataclass(frozen=True)
class AppSettings:
    app_env: str
    database_url: str
    storage_root: str
    gmail_config_path: str

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "AppSettings":
        return cls(
            app_env=_require_setting(env, "APP_ENV"),
            database_url=_require_setting(env, "DATABASE_URL"),
            storage_root=_require_setting(env, "STORAGE_ROOT"),
            gmail_config_path=_require_setting(env, "GMAIL_CONFIG_PATH"),
        )


@dataclass(frozen=True)
class MineruSettings:
    api_token: str
    model_version: str
    language: str
    enable_ocr: bool
    enable_table: bool
    enable_formula: bool
    page_ranges: str
    poll_interval_seconds: int
    poll_timeout_seconds: int

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "MineruSettings":
        return cls(
            api_token=_require_setting(env, "MINERU_API_TOKEN"),
            model_version=env.get("MINERU_MODEL_VERSION", "vlm").strip() or "vlm",
            language=env.get("MINERU_LANGUAGE", "ch").strip() or "ch",
            enable_ocr=_read_bool_setting(env, "MINERU_ENABLE_OCR", default=False),
            enable_table=_read_bool_setting(env, "MINERU_ENABLE_TABLE", default=True),
            enable_formula=_read_bool_setting(env, "MINERU_ENABLE_FORMULA", default=True),
            page_ranges=env.get("MINERU_PAGE_RANGES", "").strip(),
            poll_interval_seconds=_read_int_setting(
                env,
                "MINERU_POLL_INTERVAL_SECONDS",
                default=2,
            ),
            poll_timeout_seconds=_read_int_setting(
                env,
                "MINERU_POLL_TIMEOUT_SECONDS",
                default=300,
            ),
        )


@dataclass(frozen=True)
class GeminiSettings:
    api_token: str
    model: str
    timeout_seconds: int

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "GeminiSettings":
        return cls(
            api_token=_require_setting(env, "GEMINI_TOKEN"),
            model=env.get("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash",
            timeout_seconds=_read_int_setting(
                env,
                "GEMINI_TIMEOUT_SECONDS",
                default=120,
            ),
        )


def _require_setting(env: Mapping[str, str], key: str) -> str:
    value = env.get(key, "").strip()
    if not value:
        raise ConfigurationError(f"Missing required configuration: {key}")
    return value


def _read_bool_setting(env: Mapping[str, str], key: str, *, default: bool) -> bool:
    value = env.get(key)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _read_int_setting(env: Mapping[str, str], key: str, *, default: int) -> int:
    value = env.get(key)
    if value is None or not value.strip():
        return default
    return int(value.strip())
