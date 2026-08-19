from __future__ import annotations

from importlib import import_module

from .base import Connector
from .connectors import CONNECTORS as BUILTIN_CONNECTORS

_PROVIDER_MODULES = ("vk", "pinterest", "meta", "tiktok", "youtube")


def build_registry() -> dict[str, Connector]:
    registry: dict[str, Connector] = dict(BUILTIN_CONNECTORS)
    package = __package__ or "app.integrations"
    for module_name in _PROVIDER_MODULES:
        qualified = f"{package}.{module_name}"
        try:
            module = import_module(qualified)
        except ModuleNotFoundError as exc:
            if exc.name != qualified:
                raise
            continue
        provider_connectors = getattr(module, "CONNECTORS", None)
        if not isinstance(provider_connectors, dict):
            raise RuntimeError(f"{qualified} must expose CONNECTORS dict")
        overlap = set(registry) & set(provider_connectors)
        if overlap:
            raise RuntimeError(f"duplicate connector channels: {', '.join(sorted(overlap))}")
        registry.update(provider_connectors)
    return registry


CONNECTORS = build_registry()
