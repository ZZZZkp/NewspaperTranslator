from dataclasses import dataclass
from typing import Mapping


class ConfigurationError(ValueError):
    """Raised when required application configuration is missing."""


@dataclass(frozen=True)
class AppSettings:
    app_env: str
    database_url: str
    storage_root: str
    gmail_client_id: str
    gmail_client_secret: str
    gmail_refresh_token: str

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "AppSettings":
        return cls(
            app_env=_require_setting(env, "APP_ENV"),
            database_url=_require_setting(env, "DATABASE_URL"),
            storage_root=_require_setting(env, "STORAGE_ROOT"),
            gmail_client_id=_require_setting(env, "GMAIL_CLIENT_ID"),
            gmail_client_secret=_require_setting(env, "GMAIL_CLIENT_SECRET"),
            gmail_refresh_token=_require_setting(env, "GMAIL_REFRESH_TOKEN"),
        )


def _require_setting(env: Mapping[str, str], key: str) -> str:
    value = env.get(key, "").strip()
    if not value:
        raise ConfigurationError(f"Missing required configuration: {key}")
    return value
