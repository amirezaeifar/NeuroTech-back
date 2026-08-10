"""Environment-driven application configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


class ConfigurationError(RuntimeError):
    """Raised when application configuration is missing or invalid."""


@dataclass(frozen=True, slots=True)
class Settings:
    """Validated settings shared by Flask and the dependency container."""

    environment: str
    secret_key: str
    log_level: str
    upload_root: Path
    sms_provider: str
    payment_provider: str
    service_name: str
    service_version: str
    problem_base_uri: str

    @property
    def debug(self) -> bool:
        return self.environment == "development"

    @property
    def testing(self) -> bool:
        return self.environment == "testing"

    @classmethod
    def from_env(cls, environment: str | None = None) -> Settings:
        """Load settings from ``.env`` and process environment variables."""

        load_dotenv()
        selected_environment = (environment or os.getenv("APP_ENV", "development")).lower()
        if selected_environment not in {"development", "testing", "production"}:
            raise ConfigurationError("APP_ENV must be one of: development, testing, production.")

        secret_key = os.getenv("SECRET_KEY", "development-only-change-me")
        if selected_environment == "production" and (
            secret_key == "development-only-change-me" or len(secret_key) < 32
        ):
            raise ConfigurationError(
                "Production SECRET_KEY must be explicitly set to at least 32 characters."
            )

        problem_base_uri = os.getenv(
            "PROBLEM_BASE_URI", "https://api.neurotech.local/problems"
        ).rstrip("/")
        if not problem_base_uri.startswith(("http://", "https://")):
            raise ConfigurationError("PROBLEM_BASE_URI must be an absolute HTTP(S) URI.")

        return cls(
            environment=selected_environment,
            secret_key=secret_key,
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            upload_root=Path(os.getenv("UPLOAD_ROOT", "storage/uploads")),
            sms_provider=os.getenv("SMS_PROVIDER", "fake").lower(),
            payment_provider=os.getenv("PAYMENT_PROVIDER", "fake").lower(),
            service_name=os.getenv("SERVICE_NAME", "neurotech-api"),
            service_version=os.getenv("SERVICE_VERSION", "0.1.0"),
            problem_base_uri=problem_base_uri,
        )

    def as_flask_config(self) -> dict[str, Any]:
        """Return framework-facing settings without leaking the dataclass itself."""

        return {
            "ENVIRONMENT": self.environment,
            "SECRET_KEY": self.secret_key,
            "LOG_LEVEL": self.log_level,
            "UPLOAD_ROOT": str(self.upload_root),
            "SMS_PROVIDER": self.sms_provider,
            "PAYMENT_PROVIDER": self.payment_provider,
            "SERVICE_NAME": self.service_name,
            "SERVICE_VERSION": self.service_version,
            "PROBLEM_BASE_URI": self.problem_base_uri,
            "DEBUG": self.debug,
            "TESTING": self.testing,
            "JSON_SORT_KEYS": False,
        }
