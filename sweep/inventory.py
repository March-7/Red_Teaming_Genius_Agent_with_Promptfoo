"""Inventory definitions and offline validation for the Genius sweep."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


INVENTORY_VERSION = 1
EXPECTED_GROUP_COUNT = 6
EXPECTED_PLUGIN_COUNT = 39

ALLOWED_STATUSES = {
    "ready",
    "blocked-prerequisite",
    "not-applicable",
    "candidate",
    "no-finding-in-small-sample",
    "target-error",
}

CUSTOM_PLUGIN_IDS = {"policy", "intent"}

BUILTIN_PLUGIN_IDS = frozenset(
    {
        "hijacking",
        "system-prompt-override",
        "excessive-agency",
        "tool-discovery",
        "overreliance",
        "hallucination",
        "goal-misalignment",
        "off-topic",
        "imitation",
        "agentic:memory-poisoning",
        "cross-session-leak",
        "harmful:privacy",
        "pii:session",
        "pii:api-db",
        "pii:social",
        "rbac",
        "bola",
        "bfla",
        "indirect-prompt-injection",
        "rag-poisoning",
        "rag-document-exfiltration",
        "rag-source-attribution",
        "data-exfil",
        "mcp",
        "ssrf",
        "shell-injection",
        "sql-injection",
        "debug-access",
        "reasoning-dos",
        "divergent-repetition",
        "harmful:chemical-biological-weapons",
        "harmful:unsafe-practices",
        "harmful:specialized-advice",
        "harmful:cybercrime",
        "harmful:cybercrime:malicious-code",
        "harmful:misinformation-disinformation",
        "unverifiable-claims",
        "harmful:copyright-violations",
        "harmful:intellectual-property",
    }
)


GROUPS: list[dict[str, Any]] = [
    {
        "id": "p0-agent-control",
        "priority": 0,
        "description": "Agent goal and control failures that are immediately relevant to Genius.",
        "plugins": [
            {"id": "hijacking", "prerequisites": [], "status": "ready"},
            {"id": "system-prompt-override", "prerequisites": [], "status": "ready"},
            {"id": "excessive-agency", "prerequisites": [], "status": "ready"},
            {"id": "tool-discovery", "prerequisites": [], "status": "ready"},
            {"id": "overreliance", "prerequisites": [], "status": "ready"},
            {"id": "hallucination", "prerequisites": [], "status": "ready"},
            {"id": "goal-misalignment", "prerequisites": [], "status": "ready"},
            {"id": "off-topic", "prerequisites": [], "status": "ready"},
            {"id": "imitation", "prerequisites": [], "status": "ready"},
        ],
    },
    {
        "id": "p1-memory-session-data",
        "priority": 1,
        "description": "Session, memory, trace, and data-isolation boundaries.",
        "plugins": [
            {
                "id": "agentic:memory-poisoning",
                "prerequisites": ["multi_turn_session_reuse"],
                "status": "blocked-prerequisite",
            },
            {
                "id": "cross-session-leak",
                "prerequisites": ["two_isolated_sessions"],
                "status": "blocked-prerequisite",
            },
            {"id": "harmful:privacy", "prerequisites": [], "status": "ready"},
            {
                "id": "pii:session",
                "prerequisites": ["synthetic_session_pii"],
                "status": "blocked-prerequisite",
            },
            {
                "id": "pii:api-db",
                "prerequisites": ["api_or_db_access"],
                "status": "blocked-prerequisite",
            },
            {"id": "pii:social", "prerequisites": [], "status": "ready"},
        ],
    },
    {
        "id": "p1-authorization-boundaries",
        "priority": 1,
        "description": "RBAC and object/function authorization boundaries.",
        "plugins": [
            {
                "id": "rbac",
                "prerequisites": ["second_role", "rbac_matrix"],
                "status": "blocked-prerequisite",
            },
            {
                "id": "bola",
                "prerequisites": ["two_isolated_objects", "authorization_matrix"],
                "status": "blocked-prerequisite",
            },
            {
                "id": "bfla",
                "prerequisites": ["admin_role", "function_authorization_matrix"],
                "status": "blocked-prerequisite",
            },
        ],
    },
    {
        "id": "p1-external-content-supply-chain",
        "priority": 1,
        "description": "Untrusted web, file, RAG, MCP, and data-exfiltration channels.",
        "plugins": [
            {
                "id": "indirect-prompt-injection",
                "prerequisites": ["untrusted_input_variable"],
                "status": "blocked-prerequisite",
            },
            {
                "id": "rag-poisoning",
                "prerequisites": ["rag_document_store"],
                "status": "blocked-prerequisite",
            },
            {
                "id": "rag-document-exfiltration",
                "prerequisites": ["rag_document_store"],
                "status": "blocked-prerequisite",
            },
            {
                "id": "rag-source-attribution",
                "prerequisites": ["rag_document_store"],
                "status": "blocked-prerequisite",
            },
            {
                "id": "data-exfil",
                "prerequisites": [
                    "external_network_canary",
                    "promptfoo_cloud_tracking",
                ],
                "status": "blocked-prerequisite",
            },
            {
                "id": "mcp",
                "prerequisites": ["mounted_mcp_server"],
                "status": "blocked-prerequisite",
            },
        ],
    },
    {
        "id": "p1-tool-execution",
        "priority": 1,
        "description": "Shell, SQL, web fetch, SSRF, and debug execution boundaries.",
        "plugins": [
            {
                "id": "ssrf",
                "prerequisites": ["web_fetch_tool", "controlled_http_canary"],
                "status": "blocked-prerequisite",
            },
            {
                "id": "shell-injection",
                "prerequisites": ["execute_shell_command_tool"],
                "status": "blocked-prerequisite",
            },
            {
                "id": "sql-injection",
                "prerequisites": ["execute_sql_tool"],
                "status": "blocked-prerequisite",
            },
            {
                "id": "debug-access",
                "prerequisites": ["debug_interface"],
                "missing_behavior": "not-applicable",
                "status": "not-applicable",
            },
        ],
    },
    {
        "id": "p2-domain-resource-safety",
        "priority": 2,
        "description": "Research-domain safety, IP, misinformation, and resource exhaustion.",
        "plugins": [
            {"id": "reasoning-dos", "prerequisites": [], "status": "ready"},
            {
                "id": "divergent-repetition",
                "prerequisites": [],
                "status": "ready",
            },
            {
                "id": "harmful:chemical-biological-weapons",
                "prerequisites": [],
                "status": "ready",
            },
            {
                "id": "harmful:unsafe-practices",
                "prerequisites": [],
                "status": "ready",
            },
            {
                "id": "harmful:specialized-advice",
                "prerequisites": [],
                "status": "ready",
            },
            {
                "id": "harmful:cybercrime",
                "prerequisites": [],
                "status": "ready",
            },
            {
                "id": "harmful:cybercrime:malicious-code",
                "prerequisites": [],
                "status": "ready",
            },
            {
                "id": "harmful:misinformation-disinformation",
                "prerequisites": [],
                "status": "ready",
            },
            {
                "id": "unverifiable-claims",
                "prerequisites": [],
                "status": "ready",
            },
            {
                "id": "harmful:copyright-violations",
                "prerequisites": [],
                "status": "ready",
            },
            {
                "id": "harmful:intellectual-property",
                "prerequisites": [],
                "status": "ready",
            },
        ],
    },
]


def build_inventory() -> dict[str, Any]:
    """Return a deterministic inventory document with explicit group bindings."""
    groups: list[dict[str, Any]] = []
    for group in GROUPS:
        plugins = []
        for plugin in group["plugins"]:
            item = dict(plugin)
            item["group"] = group["id"]
            plugins.append(item)
        groups.append(
            {
                "id": group["id"],
                "priority": group["priority"],
                "description": group["description"],
                "plugins": plugins,
            }
        )
    return {
        "version": INVENTORY_VERSION,
        "promptfoo_version": "0.122.2",
        "groups": groups,
    }


def load_inventory(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("inventory must be a JSON object")
    return payload


def iter_plugins(inventory: dict[str, Any]) -> Iterable[dict[str, Any]]:
    for group in inventory.get("groups", []):
        if not isinstance(group, dict):
            continue
        for plugin in group.get("plugins", []):
            if isinstance(plugin, dict):
                yield plugin


def validate_inventory(inventory: dict[str, Any]) -> list[str]:
    """Validate structure, uniqueness, plugin IDs, statuses, and group binding."""
    errors: list[str] = []
    groups = inventory.get("groups")
    if not isinstance(groups, list):
        return ["inventory.groups must be a list"]
    if len(groups) != EXPECTED_GROUP_COUNT:
        errors.append(f"expected {EXPECTED_GROUP_COUNT} groups, found {len(groups)}")

    group_ids: list[str] = []
    plugin_ids: list[str] = []
    plugin_groups: dict[str, list[str]] = {}
    for group_index, group in enumerate(groups):
        if not isinstance(group, dict):
            errors.append(f"group {group_index} must be an object")
            continue
        group_id = group.get("id")
        if not isinstance(group_id, str) or not group_id:
            errors.append(f"group {group_index} is missing a non-empty id")
        elif group_id in group_ids:
            errors.append(f"duplicate group id: {group_id}")
        else:
            group_ids.append(group_id)
        if not isinstance(group.get("priority"), int):
            errors.append(f"group {group_id} priority must be an integer")

        plugins = group.get("plugins")
        if not isinstance(plugins, list):
            errors.append(f"group {group_id} plugins must be a list")
            continue
        for plugin_index, plugin in enumerate(plugins):
            label = f"{group_id} plugin {plugin_index}"
            if not isinstance(plugin, dict):
                errors.append(f"{label} must be an object")
                continue
            plugin_id = plugin.get("id")
            if not isinstance(plugin_id, str) or not plugin_id:
                errors.append(f"{label} is missing a non-empty id")
                continue
            if plugin_id in CUSTOM_PLUGIN_IDS:
                errors.append(f"custom plugin is not allowed: {plugin_id}")
            if plugin_id not in BUILTIN_PLUGIN_IDS:
                errors.append(f"unsupported plugin id: {plugin_id}")
            if plugin_id in plugin_ids:
                errors.append(f"duplicate plugin id: {plugin_id}")
            plugin_ids.append(plugin_id)
            plugin_groups.setdefault(plugin_id, []).append(group_id)
            if len(plugin_groups[plugin_id]) > 1:
                errors.append(
                    "plugin assigned to multiple groups: "
                    f"{plugin_id} -> {', '.join(plugin_groups[plugin_id])}"
                )
            if plugin.get("group") != group_id:
                errors.append(f"plugin {plugin_id} group binding mismatch")
            status = plugin.get("status")
            if status not in ALLOWED_STATUSES:
                errors.append(f"plugin {plugin_id} has invalid status: {status}")
            prerequisites = plugin.get("prerequisites")
            if not isinstance(prerequisites, list) or not all(
                isinstance(item, str) and item for item in prerequisites
            ):
                errors.append(f"plugin {plugin_id} prerequisites must be a string list")

    if len(plugin_ids) != EXPECTED_PLUGIN_COUNT:
        errors.append(f"expected {EXPECTED_PLUGIN_COUNT} plugins, found {len(plugin_ids)}")
    if len(set(plugin_ids)) != len(plugin_ids):
        errors.append("plugin ids must be unique")
    return errors


def evaluate_prerequisites(
    plugin: dict[str, Any],
    available_conditions: set[str] | frozenset[str] | list[str],
) -> dict[str, Any]:
    """Evaluate a plugin prerequisite gate without contacting Genius."""
    available = set(available_conditions)
    prerequisites = plugin.get("prerequisites")
    if not isinstance(prerequisites, list):
        prerequisites = []
    missing = [item for item in prerequisites if item not in available]
    if not missing:
        return {"status": "ready", "missing": []}
    if plugin.get("missing_behavior") == "not-applicable":
        return {"status": "not-applicable", "missing": missing}
    return {"status": "blocked-prerequisite", "missing": missing}


def find_plugin(
    inventory: dict[str, Any],
    group_id: str,
    plugin_id: str,
) -> dict[str, Any] | None:
    for group in inventory.get("groups", []):
        if not isinstance(group, dict) or group.get("id") != group_id:
            continue
        for plugin in group.get("plugins", []):
            if isinstance(plugin, dict) and plugin.get("id") == plugin_id:
                return plugin
    return None
