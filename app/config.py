from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# ملخص: إعدادات التطبيق تُحمّل من المتغيرات البيئية وملف .env.
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False
    )

    bot_token: str
    bot_channel: str
    database_url: str = "sqlite+aiosqlite:///./db.sqlite3"
    redis_url: str | None = None
    require_redis: bool = False
    admin_ids: list[int] = []

    # Webhook configuration (if webhook_url is set -> webhook mode)
    webhook_url: str | None = None  # e.g. https://example.com
    webhook_path_template: str = "/webhook/{token}"
    webhook_secret: str | None = None
    webapp_host: str = "0.0.0.0"  # nosec B104 - container binding by design
    webapp_port: int = 8080

    @field_validator("bot_channel")
    @classmethod
    def normalize_channel(cls, value: str) -> str:
        v = value.strip()
        if not v.startswith("@") and not v.replace("-", "").isdigit():
            raise ValueError("BOT_CHANNEL must start with @ or be channel id")
        return v

    @field_validator("admin_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, value):
        if value is None:
            return []
        if isinstance(value, list):
            return [int(x) for x in value]
        s = str(value)
        parts = [p.strip() for p in s.split(",") if p.strip()]
        try:
            return [int(p) for p in parts]
        except Exception:
            return []

    def webhook_path(self, token: str) -> str:
        path = self.webhook_path_template.replace("{token}", token)
        if not path.startswith("/"):
            path = "/" + path
        return path

    def webhook_full_url(self, token: str) -> str:
        assert self.webhook_url, "webhook_url is not set"  # nosec B101 - validated upstream
        base = self.webhook_url.rstrip("/")
        return base + self.webhook_path(token)


settings = Settings()
