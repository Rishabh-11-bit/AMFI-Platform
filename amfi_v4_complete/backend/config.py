"""AMFI v4 — Application settings loaded from .env via pydantic-settings."""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # App
    debug: bool = False
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    secret_key: str = "change-me-generate-with-openssl-rand-hex-32"

    # Authentication (set AUTH_ENABLED=true in .env to require JWT login)
    auth_enabled: bool = False

    # Public-facing base URL — used in notification links (Teams, Slack, email)
    public_url: str = "http://localhost:8000"

    # CORS allowed origins (comma-separated; "*" = all, use your domain in production)
    cors_origins: str = "*"

    # Credential encryption key — auto-derived from secret_key if blank
    # Set ENCRYPTION_KEY to an independent Fernet key for extra security
    encryption_key: str = ""

    # Max simultaneous agent executions (prevents DB lock pileup).
    # 5 is the right ceiling for SQLite; use 20-50 with PostgreSQL.
    max_concurrent_agents: int = 5

    # Database — default to SQLite for Python 3.14 (asyncpg has no wheel yet)
    database_url: str = "sqlite+aiosqlite:///./amfi_v4.db"

    # Ollama (primary AI engine — local, offline)
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"
    ollama_timeout: int = 45

    # Claude API (optional fallback)
    anthropic_api_key: str = ""

    # Agent behaviour
    agent_max_attempts: int = 3
    auto_execute_low_risk: bool = True
    agent_confidence_threshold: float = 0.75

    # SSH
    ssh_timeout: int = 15
    ssh_connect_timeout: int = 5

    # Ansible
    playbooks_dir: str = "./playbooks"

    # SLA (minutes)
    sla_p1_response: int = 15
    sla_p1_resolve: int = 60
    sla_p2_response: int = 60
    sla_p2_resolve: int = 240
    sla_p3_response: int = 240
    sla_p3_resolve: int = 1440
    sla_p4_response: int = 1440
    sla_p4_resolve: int = 4320

    # SMTP notifications
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""

    # Slack notifications
    slack_webhook: str = ""

    # Team escalation emails
    l1_email: str = ""
    l2_email: str = ""
    l3_email: str = ""

    # High-risk actions (always require human approval before execution)
    high_risk_actions: str = (
        "rollback_config,failover_standby,bounce_interface,scale_resources,"
        "kill_top_process,restart_service,restart_db_service,clear_memory_cache"
    )

    # NMS polling
    nms_poll_seconds: int = 300

    # ── Microsoft Teams ──────────────────────────────────────────────────────
    teams_webhook: str = ""

    # ── PagerDuty ────────────────────────────────────────────────────────────
    pagerduty_integration_key: str = ""   # Events API v2 routing key
    pagerduty_api_token: str = ""         # REST API token (for updates)

    # ── OpsGenie ─────────────────────────────────────────────────────────────
    opsgenie_api_key: str = ""
    opsgenie_api_url: str = "https://api.opsgenie.com"

    # ── VictorOps / Splunk On-Call ────────────────────────────────────────────
    victorops_api_key: str = ""
    victorops_routing_key: str = "amfi"

    # ── xMatters ──────────────────────────────────────────────────────────────
    xmatters_webhook_url: str = ""

    # ── ServiceNow ────────────────────────────────────────────────────────────
    servicenow_url: str = ""              # e.g. https://instance.service-now.com
    servicenow_user: str = ""
    servicenow_password: str = ""
    servicenow_incident_table: str = "incident"
    servicenow_assignment_group: str = ""
    servicenow_caller_id: str = ""

    # ── Jira Service Management ───────────────────────────────────────────────
    jira_url: str = ""                    # e.g. https://company.atlassian.net
    jira_user: str = ""                   # email address
    jira_api_token: str = ""
    jira_project_key: str = "OPS"
    jira_issue_type: str = "Incident"

    # ── Freshservice ─────────────────────────────────────────────────────────
    freshservice_domain: str = ""         # e.g. company.freshservice.com
    freshservice_api_key: str = ""

    # ── Zendesk ───────────────────────────────────────────────────────────────
    zendesk_subdomain: str = ""
    zendesk_email: str = ""
    zendesk_api_token: str = ""

    # ── ManageEngine ServiceDesk Plus ─────────────────────────────────────────
    manageengine_url: str = ""
    manageengine_api_key: str = ""

    # ── BMC Remedy / Helix ────────────────────────────────────────────────────
    remedy_url: str = ""
    remedy_user: str = ""
    remedy_password: str = ""

    # ── Datadog ───────────────────────────────────────────────────────────────
    datadog_api_key: str = ""
    datadog_app_key: str = ""
    datadog_site: str = "datadoghq.com"

    # ── Nagios / Icinga2 ─────────────────────────────────────────────────────
    nagios_url: str = ""
    nagios_user: str = ""
    nagios_password: str = ""
    icinga2_url: str = ""
    icinga2_user: str = ""
    icinga2_password: str = ""

    # ── New Relic ─────────────────────────────────────────────────────────────
    newrelic_api_key: str = ""
    newrelic_account_id: str = ""

    # ── Dynatrace ─────────────────────────────────────────────────────────────
    dynatrace_url: str = ""               # e.g. https://abc12345.live.dynatrace.com
    dynatrace_api_token: str = ""

    # ── Grafana ───────────────────────────────────────────────────────────────
    grafana_url: str = ""
    grafana_token: str = ""

    # ── Splunk ────────────────────────────────────────────────────────────────
    splunk_hec_url: str = ""
    splunk_hec_token: str = ""

    # ── Elastic ───────────────────────────────────────────────────────────────
    elastic_url: str = ""
    elastic_api_key: str = ""

    @property
    def high_risk_actions_list(self) -> list[str]:
        return [a.strip() for a in self.high_risk_actions.split(",") if a.strip()]


@lru_cache()
def get_settings() -> Settings:
    return Settings()
