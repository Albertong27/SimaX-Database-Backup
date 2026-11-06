from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from .schedules import parse_cron


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


Credential = Annotated[str, StringConstraints(strip_whitespace=False, max_length=4096, pattern=r"^[^\x00]*$")]


class Source(Input):
    name: str = Field(min_length=1, max_length=80)
    engine: Literal["postgresql", "mysql", "oracle", "sqlserver"]
    host: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9.:-]{0,252}$")
    port: int = Field(ge=1, le=65535)
    database: str = Field(pattern=r"^[a-zA-Z_][a-zA-Z0-9_$-]{0,62}$")
    username: str = Field(pattern=r"^[a-zA-Z_][a-zA-Z0-9_.@$-]{0,62}$")
    password: Credential | None = None
    environment: Literal["PROD", "STAGING", "DEV", "DISPOSABLE"] = "DEV"
    role: Literal["source", "target"] = "source"
    tls: Literal["verify-full", "disable"] = "verify-full"


class Schedule(Input):
    trigger: Literal["manual", "daily", "weekly", "cron"] = "manual"
    time: str = Field(default="03:00", pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
    timezone: str = "Asia/Jakarta"
    weekdays: list[int] = Field(default_factory=lambda: [0], max_length=7)
    cron: str = Field(default="0 3 * * *", max_length=256)

    @field_validator("weekdays")
    @classmethod
    def valid_weekdays(cls, value):
        if any(day < 0 or day > 6 for day in value) or len(set(value)) != len(value):
            raise ValueError("Choose unique weekdays from Monday (0) to Sunday (6).")
        return sorted(value)

    @model_validator(mode="after")
    def valid_schedule(self):
        if self.trigger == "weekly" and not self.weekdays:
            raise ValueError("Choose at least one weekday.")
        if self.trigger == "cron":
            parse_cron(self.cron)
        return self

    @field_validator("timezone")
    @classmethod
    def timezone_exists(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Choose an IANA time zone, such as Asia/Jakarta.") from None
        return value


class Policy(Schedule):
    trigger: Literal["manual", "daily", "weekly", "cron", "table-change", "database-change", "webhook", "mqtt"] = "manual"
    name: str = Field(min_length=1, max_length=80)
    source_id: str
    destination: str = Field(default="local", pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
    enabled: bool = True
    poll_seconds: int = Field(default=300, ge=60, le=86400)
    change_tables: list[str] = Field(default_factory=list, max_length=100)
    acknowledge_scan: bool = False
    debounce_seconds: int = Field(default=10, ge=0, le=300)
    cooldown_seconds: int = Field(default=300, ge=60, le=86400)
    event_secret: Credential | None = None
    mqtt_host: str = Field(default="localhost", pattern=r"^[a-zA-Z0-9][a-zA-Z0-9.:-]{0,252}$")
    mqtt_port: int = Field(default=8883, ge=1, le=65535)
    mqtt_topic: str = Field(default="simax/backup", min_length=1, max_length=200)
    mqtt_tls: bool = True
    mqtt_username: str = Field(default="", max_length=128)
    mqtt_password: Credential | None = None
    freshness_minutes: int = Field(default=1440, ge=5, le=525600)
    retention_enabled: bool = False
    retention_days: int = Field(default=30, ge=1, le=3650)
    retention_keep_last: int = Field(default=12, ge=2, le=10000)
    retention_hold: bool = False

    @field_validator("mqtt_topic")
    @classmethod
    def exact_topic(cls, value):
        if any(c in "+#" or ord(c) < 32 for c in value):
            raise ValueError("Use one exact MQTT topic without wildcards or control characters.")
        return value

    @model_validator(mode="after")
    def valid_event_trigger(self):
        if self.trigger in {"table-change", "database-change"} and not self.acknowledge_scan:
            raise ValueError("Acknowledge the read-only full-table scans and polling gaps before enabling change observation.")
        if self.trigger == "table-change" and not self.change_tables:
            raise ValueError("Choose at least one table to watch.")
        if any(not name or len(name) > 260 or any(ord(c) < 32 for c in name) for name in self.change_tables):
            raise ValueError("Use table names from the source preflight inventory, one per line.")
        if len(set(self.change_tables)) != len(self.change_tables):
            raise ValueError("Table selection contains duplicates.")
        return self


class TriggerEvent(Input):
    event_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}$")


class MqttEvent(TriggerEvent):
    timestamp: int = Field(strict=True)
    signature: str = Field(pattern=r"^[a-f0-9]{64}$")


class Settings(Input):
    timezone: str = "Asia/Jakarta"
    recovery_limit_hours: int = Field(default=24, ge=1, le=8760)
    restore_test_limit_days: int = Field(default=30, ge=1, le=3650)
    recovery_target_minutes: int = Field(default=15, ge=1, le=1440)
    minimum_free_gib: int = Field(default=2, ge=1, le=10240)

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


class ArtifactPin(Input):
    pinned: bool
