from __future__ import annotations

import re

from pcbsmith.templates.models import CircuitTemplateUse


def bound_net(use: CircuitTemplateUse, local_name: str, default: str) -> str:
    return use.net_bindings.get(local_name, default)


def internal_net(use: CircuitTemplateUse, local_name: str) -> str:
    instance = safe_instance(use.instance or use.template_id)
    return f"{instance}_{local_name.upper()}"


def design_name(use: CircuitTemplateUse) -> str:
    if use.instance:
        return f"{use.template_id}:{use.instance}"
    return use.template_id


def safe_instance(instance: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9]+", "_", instance).strip("_").upper()
    return safe or "TEMPLATE"


def string_param(use: CircuitTemplateUse, key: str, default: str) -> str:
    value = use.params.get(key, default)
    if isinstance(value, bool):
        raise ValueError(f"{key} must be a string")
    return str(value)


def int_param(use: CircuitTemplateUse, key: str, default: int, *, minimum: int) -> int:
    value = use.params.get(key, default)
    if isinstance(value, bool):
        raise ValueError(f"{key} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be an integer") from exc
    if parsed < minimum:
        raise ValueError(f"{key} must be at least {minimum}")
    return parsed


__all__ = [
    "bound_net",
    "design_name",
    "int_param",
    "internal_net",
    "string_param",
]
