from dataclasses import dataclass


@dataclass(frozen=True)
class ToolDefinition:
    id: str
    name: str
    route: str
    api_prefix: str
    description: str = ""


TOOLS = [
    ToolDefinition(
        id="odoo_db_pull",
        name="Odoo DB Pull",
        route="/tools/odoo-db-pull",
        api_prefix="/api",
        description="Pull Odoo databases and filestores between local and remote targets.",
    ),
]
