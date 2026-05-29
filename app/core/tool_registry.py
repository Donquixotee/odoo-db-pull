from dataclasses import dataclass


@dataclass(frozen=True)
class ToolDefinition:
    id: str
    name: str
    route: str
    api_prefix: str
    description: str = ""
    icon: str = "apps"


TOOLS = [
    ToolDefinition(
        id="odoo_db_pull",
        name="Odoo DB Pull",
        route="/tools/odoo-db-pull",
        api_prefix="/api",
        description="Pull Odoo databases and filestores between local and remote targets.",
        icon="cloud_download",
    ),
    ToolDefinition(
        id="time_tracker",
        name="Time Tracker",
        route="/tools/time-tracker",
        api_prefix="/api/time-tracker",
        description="Track part-time tasks, hours, earnings, and payment status.",
        icon="schedule",
    ),
    ToolDefinition(
        id="snippet_vault",
        name="Snippet Vault",
        route="/tools/snippet-vault",
        api_prefix="/api/snippet-vault",
        description="Store frequently used commands, credentials, queries, and notes.",
        icon="content_paste",
    ),
    ToolDefinition(
        id="postgres_maintenance",
        name="Postgres Maintenance",
        route="/tools/postgres-maintenance",
        api_prefix="/api/postgres-maintenance",
        description="Inspect local PostgreSQL databases and run maintenance operations.",
        icon="database",
    ),
    ToolDefinition(
        id="odoo_cron_debugger",
        name="Odoo Cron Debugger",
        route="/tools/odoo-cron-debugger",
        api_prefix="/api/odoo-cron-debugger",
        description="Monitor and kill stuck Odoo crons blocking module updates.",
        icon="timer_off",
    ),
]
