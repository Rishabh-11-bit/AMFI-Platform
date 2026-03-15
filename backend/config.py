"""AMFI Platform — Master Configuration."""
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    app_name: str = "AMFI – IT Service Automation Platform"
    debug: bool = False
    secret_key: str = "change-me-in-production-openssl-rand-hex-32"

    # Database
    database_url: str = "sqlite+aiosqlite:///./amfi.db"

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # SNMP
    snmp_host: str = "0.0.0.0"
    snmp_port: int = 1162
    snmp_community: str = "public"

    # Syslog
    syslog_host: str = "0.0.0.0"
    syslog_port: int = 5514
    syslog_protocol: str = "udp"

    # MQTT
    mqtt_enabled: bool = False
    mqtt_broker: str = "localhost"
    mqtt_port: int = 1883
    mqtt_topic: str = "amfi/events/#"

    # Auth
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # Deduplication
    dedup_window_seconds: int = 120

    # SLA Thresholds (minutes)
    sla_critical_minutes: int = 15
    sla_high_minutes: int = 60
    sla_medium_minutes: int = 240
    sla_low_minutes: int = 1440

    # Remediation
    remediation_poll_interval_seconds: int = 30
    remediation_max_retries: int = 5
    ssh_timeout_seconds: int = 30
    ansible_playbooks_dir: str = "./playbooks"
    terraform_dir: str = "./terraform"

    # Notifications
    slack_webhook_url: str = ""
    teams_webhook_url: str = ""
    pagerduty_routing_key: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    notify_email_to: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()
