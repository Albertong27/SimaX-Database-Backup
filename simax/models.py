from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Source(Input):
    name: str = Field(min_length=1, max_length=80)
    engine: Literal["postgresql", "mysql", "oracle", "sqlserver"]
    host: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9.:-]{0,252}$")
    port: int = Field(ge=1, le=65535)
    database: str = Field(pattern=r"^[a-zA-Z_][a-zA-Z0-9_$-]{0,62}$")
    username: str = Field(pattern=r"^[a-zA-Z_][a-zA-Z0-9_.@$-]{0,62}$")
    password_env: str = Field(pattern=r"^SIMAX_SECRET_[A-Z0-9_]{1,80}$")
    environment: Literal["PROD", "STAGING", "DEV", "DISPOSABLE"] = "DEV"
    role: Literal["source", "target"] = "source"
    tls: Literal["verify-full", "disable"] = "verify-full"

    @model_validator(mode="after")
    def local_plaintext_only(self):
        if self.tls == "disable" and self.host not in {"localhost", "127.0.0.1"}:
            raise ValueError("Unencrypted connections are allowed only on loopback.")
        return self


class Policy(Input):
    name: str = Field(min_length=1, max_length=80)
    source_id: str
    destination: str = Field(default="local", pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
    trigger: Literal["manual", "daily"] = "manual"
    time: str = Field(default="03:00", pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
    timezone: str = "Asia/Jakarta"
    enabled: bool = True

    @field_validator("timezone")
    @classmethod
    def timezone_exists(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Choose an IANA time zone, such as Asia/Jakarta.") from None
        return value


class Settings(Input):
    timezone: str = "Asia/Jakarta"
    recovery_limit_hours: int = Field(default=24, ge=1, le=8760)
    restore_test_limit_days: int = Field(default=30, ge=1, le=3650)

    @field_validator("timezone")
    @classmethod
    def timezone_exists(cls, value):
        return Policy.timezone_exists(value)


class RestorePreview(Input):
    artifact_id: str
    target_id: str


class RestoreConfirm(Input):
    token: str
    target_name: str
    acknowledge_code: bool = False
