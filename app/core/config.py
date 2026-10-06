"""Environment-driven application configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sqlalchemy.engine import make_url


class ConfigurationError(RuntimeError):
    """Raised when application configuration is missing or invalid."""


@dataclass(frozen=True, slots=True)
class Settings:
    """Validated settings shared by Flask and the dependency container."""

    environment: str
    secret_key: str
    jwt_secret_key: str
    log_level: str
    upload_root: Path
    geoip_database_path: str
    trusted_proxy_ips: str
    database_url: str
    test_database_url: str
    redis_url: str
    redis_namespace: str
    jwt_access_ttl_minutes: int
    jwt_refresh_ttl_days: int
    jwt_session_max_days: int
    cookie_secure: bool
    cookie_samesite: str
    cors_origins: tuple[str, ...]
    frontend_url: str
    sms_provider: str
    email_provider: str
    payment_provider: str
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    email_from: str
    kavenegar_api_key: str
    kavenegar_sender: str
    kavenegar_login_template: str
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
        jwt_secret_key = os.getenv("JWT_SECRET_KEY", "development-jwt-only-change-me")
        if selected_environment == "production" and (
            secret_key == "development-only-change-me" or len(secret_key) < 32
        ):
            raise ConfigurationError(
                "Production SECRET_KEY must be explicitly set to at least 32 characters."
            )
        if selected_environment == "production" and (
            jwt_secret_key == "development-jwt-only-change-me" or len(jwt_secret_key) < 32
        ):
            raise ConfigurationError(
                "Production JWT_SECRET_KEY must be explicitly set to at least 32 characters."
            )

        problem_base_uri = os.getenv(
            "PROBLEM_BASE_URI", "https://api.neurotech.local/problems"
        ).rstrip("/")
        if not problem_base_uri.startswith(("http://", "https://")):
            raise ConfigurationError("PROBLEM_BASE_URI must be an absolute HTTP(S) URI.")

        access_minutes = _positive_int("JWT_ACCESS_TTL_MINUTES", 15)
        refresh_days = _positive_int("JWT_REFRESH_TTL_DAYS", 7)
        session_days = _positive_int("JWT_SESSION_MAX_DAYS", 30)
        if refresh_days > session_days:
            raise ConfigurationError("JWT_REFRESH_TTL_DAYS cannot exceed JWT_SESSION_MAX_DAYS.")

        cookie_samesite = os.getenv("COOKIE_SAMESITE", "Lax").capitalize()
        if cookie_samesite not in {"Lax", "Strict", "None"}:
            raise ConfigurationError("COOKIE_SAMESITE must be one of: Lax, Strict, None.")

        database_url = os.getenv(
            "DATABASE_URL",
            "mysql+pymysql://neurotech_dev:change-me@127.0.0.1:3306/neurotech_dev?charset=utf8mb4",
        )
        test_database_url = os.getenv(
            "TEST_DATABASE_URL",
            "mysql+pymysql://neurotech_test:change-me@127.0.0.1:3306/"
            "neurotech_test?charset=utf8mb4",
        )
        active_database_url = (
            test_database_url if selected_environment == "testing" else database_url
        )
        default_redis_namespace = {
            "development": "neurotech:dev",
            "testing": "neurotech:test",
            "production": "neurotech:prod",
        }[selected_environment]
        redis_namespace = (
            os.getenv("TEST_REDIS_NAMESPACE", "neurotech:test")
            if selected_environment == "testing"
            else os.getenv("REDIS_NAMESPACE", default_redis_namespace)
        ).rstrip(":")
        if selected_environment == "testing":
            parsed_test_url = make_url(test_database_url)
            if parsed_test_url.get_backend_name() in {"mysql", "mariadb"} and (
                parsed_test_url.database != "neurotech_test"
            ):
                raise ConfigurationError(
                    "TEST_DATABASE_URL must target the neurotech_test database."
                )
            if not redis_namespace.startswith("neurotech:test"):
                raise ConfigurationError("TEST_REDIS_NAMESPACE must start with neurotech:test.")

        return cls(
            environment=selected_environment,
            secret_key=secret_key,
            jwt_secret_key=jwt_secret_key,
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            upload_root=Path(os.getenv("UPLOAD_ROOT", "storage/uploads")),
            geoip_database_path=os.getenv("GEOIP_DATABASE_PATH", ""),
            trusted_proxy_ips=os.getenv("TRUSTED_PROXY_IPS", ""),
            database_url=active_database_url,
            test_database_url=test_database_url,
            redis_url=os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"),
            redis_namespace=redis_namespace,
            jwt_access_ttl_minutes=access_minutes,
            jwt_refresh_ttl_days=refresh_days,
            jwt_session_max_days=session_days,
            cookie_secure=_boolean("COOKIE_SECURE", selected_environment == "production"),
            cookie_samesite=cookie_samesite,
            cors_origins=tuple(
                item.strip()
                for item in os.getenv(
                    "CORS_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173"
                ).split(",")
                if item.strip()
            ),
            frontend_url=os.getenv("FRONTEND_URL", "http://127.0.0.1:5173").rstrip("/"),
            sms_provider=os.getenv("SMS_PROVIDER", "fake").lower(),
            email_provider=os.getenv("EMAIL_PROVIDER", "fake").lower(),
            payment_provider=os.getenv("PAYMENT_PROVIDER", "fake").lower(),
            smtp_host=os.getenv("SMTP_HOST", "smtp.gmail.com"),
            smtp_port=_positive_int("SMTP_PORT", 587),
            smtp_username=os.getenv("SMTP_USERNAME", ""),
            smtp_password=os.getenv("SMTP_PASSWORD", ""),
            email_from=os.getenv("EMAIL_FROM", "neuro.tech.pishro@gmail.com"),
            kavenegar_api_key=os.getenv("KAVENEGAR_API_KEY", ""),
            kavenegar_sender=os.getenv("KAVENEGAR_SENDER", "20006535"),
            kavenegar_login_template=os.getenv("KAVENEGAR_LOGIN_TEMPLATE", "surgitrack-login"),
            service_name=os.getenv("SERVICE_NAME", "neurotech-api"),
            service_version=os.getenv("SERVICE_VERSION", "0.1.0"),
            problem_base_uri=problem_base_uri,
        )

    def as_flask_config(self) -> dict[str, Any]:
        """Return framework-facing settings without leaking the dataclass itself."""

        return {
            "ENVIRONMENT": self.environment,
            "SECRET_KEY": self.secret_key,
            "JWT_SECRET_KEY": self.jwt_secret_key,
            "LOG_LEVEL": self.log_level,
            "UPLOAD_ROOT": str(self.upload_root),
            "GEOIP_DATABASE_PATH": self.geoip_database_path,
            "TRUSTED_PROXY_IPS": self.trusted_proxy_ips,
            "DATABASE_URL": self.database_url,
            "TEST_DATABASE_URL": self.test_database_url,
            "REDIS_URL": self.redis_url,
            "REDIS_NAMESPACE": self.redis_namespace,
            "SMS_PROVIDER": self.sms_provider,
            "EMAIL_PROVIDER": self.email_provider,
            "PAYMENT_PROVIDER": self.payment_provider,
            "SERVICE_NAME": self.service_name,
            "SERVICE_VERSION": self.service_version,
            "PROBLEM_BASE_URI": self.problem_base_uri,
            "DEBUG": self.debug,
            "TESTING": self.testing,
            "JSON_SORT_KEYS": False,
            "OPENAPI_VERSION": "3.1.0",
            "API_TITLE": "NeuroTech API",
            "API_VERSION": self.service_version,
            "OPENAPI_URL_PREFIX": "/api/v1",
            "OPENAPI_JSON_PATH": "openapi.json",
            "OPENAPI_SWAGGER_UI_PATH": (
                "/docs" if self.environment in {"development", "testing"} else None
            ),
            "OPENAPI_SWAGGER_UI_URL": "https://cdn.jsdelivr.net/npm/swagger-ui-dist/",
            "JWT_TOKEN_LOCATION": ["cookies"],
            "JWT_ACCESS_TOKEN_EXPIRES": timedelta(minutes=self.jwt_access_ttl_minutes),
            "JWT_REFRESH_TOKEN_EXPIRES": timedelta(days=self.jwt_refresh_ttl_days),
            "JWT_COOKIE_SECURE": self.cookie_secure,
            "JWT_COOKIE_SAMESITE": self.cookie_samesite,
            "JWT_COOKIE_CSRF_PROTECT": True,
            "JWT_CSRF_HEADER_NAME": "X-CSRF-TOKEN",
            "JWT_ACCESS_COOKIE_PATH": "/api/",
            "JWT_REFRESH_COOKIE_PATH": "/api/v1/auth/refresh",
            "RATELIMIT_STORAGE_URI": self.redis_url,
            "RATELIMIT_KEY_PREFIX": self.redis_namespace,
            "RATELIMIT_HEADERS_ENABLED": True,
            "RATELIMIT_ENABLED": not self.testing,
            "CORS_ORIGINS": self.cors_origins,
            "FRONTEND_URL": self.frontend_url,
        }


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as error:
        raise ConfigurationError(f"{name} must be an integer.") from error
    if value <= 0:
        raise ConfigurationError(f"{name} must be greater than zero.")
    return value


def _boolean(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{name} must be a boolean.")
