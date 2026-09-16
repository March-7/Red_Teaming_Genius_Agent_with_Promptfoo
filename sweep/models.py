"""Explicit target matrix and read-only model catalogue preflight."""
from __future__ import annotations

import copy
from typing import Any

MATRIX = (
    ("Qwen3.8-Max / high", "default", "qwen3.8-max"),
    ("DeepSeek-V4.1-Flash / high", "deepseek-v4.1-flash", "deepseek-v4.1-flash"),
)


def matrix_targets(template: dict[str, Any]) -> list[dict[str, Any]]:
    targets = []
    for label, profile, _ in MATRIX:
        target = copy.deepcopy(template)
        target["label"] = label
        config = target.setdefault("config", {})
        config.pop("reasoning_effort", None)
        config["passthrough"] = {
            "model_profile": profile, "reasoning_effort": "high", "thinking": "on",
        }
        targets.append(target)
    return targets


def target_settings(targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    settings = []
    for target in targets:
        config = target.get("config", {})
        body = config.get("passthrough") or config.get("body") or {}
        settings.append({
            "label": target.get("label", target.get("id")),
            "model_profile": body.get("model_profile"),
            "reasoning_effort": body.get("reasoning_effort"),
            "thinking": body.get("thinking"),
        })
    return settings


def validate_matrix(targets: list[dict[str, Any]]) -> None:
    expected = [{"label": label, "model_profile": profile,
                 "reasoning_effort": "high", "thinking": "on"}
                for label, profile, _ in MATRIX]
    if target_settings(targets) != expected:
        raise ValueError("matrix requires Qwen3.8-Max/high and DeepSeek-V4.1-Flash/high targets")
    for target in targets:
        config = target.get("config", {})
        openai_target = (
            target.get("id") == "openai:chat:genius-agent"
            and config.get("apiBaseUrl") == "http://127.0.0.1:4030/v1"
        )
        http_target = (
            target.get("id") == "http://127.0.0.1:4030/v1/chat/completions"
            and config.get("url") == "http://127.0.0.1:4030/v1/chat/completions"
        )
        if not (openai_target or http_target):
            raise ValueError("matrix must use the local Genius shim")
        if config.get("metadata", {}).get("model_profile"):
            raise ValueError("metadata.model_profile must not override matrix passthrough")


def catalogue_snapshot(service: Any, targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    snapshots = []
    expected_names = {profile: name for _, profile, name in MATRIX}
    for setting in target_settings(targets):
        profile = setting["model_profile"]
        model = service.resolve_model_profile(profile)
        if model.get("enabled") is not True:
            raise ValueError(f"Genius profile {profile} is not enabled")
        if model.get("model_name") != expected_names[profile]:
            raise ValueError(f"Genius profile {profile} no longer resolves to the expected model")
        levels = model.get("reasoning_levels") or []
        if levels and setting["reasoning_effort"] not in levels:
            raise ValueError(f"Genius profile {profile} does not advertise the requested effort")
        snapshots.append({**setting,
            "catalogue": {k: model.get(k) for k in (
                "profile_name", "model_name", "display_name", "provider", "enabled",
                "reasoning_levels", "thinking", "reasoning_effort")},
            "effort_support": "advertised" if levels else "not-advertised-requested-explicitly",
            "effective_backend_settings": "unverified",
        })
    return snapshots
