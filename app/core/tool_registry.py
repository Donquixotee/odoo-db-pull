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
]
