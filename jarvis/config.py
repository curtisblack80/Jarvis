"""Configuration and secrets loading.

Tunables come from ``config.yaml`` (editable without touching code).
Secrets come from the environment / a git-ignored ``.env`` file — never source.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

# Project root = the directory that holds config.yaml (one up from this package).
ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"


class ConfigError(RuntimeError):
    """Raised when configuration or required secrets are missing."""


class Config:
    """A thin, dotted-access wrapper over the YAML config plus secrets.

    Keep this boring: it loads ``config.yaml`` and the ``.env`` file once, and
    hands back values. Anything tunable belongs in the YAML, not in code.
    """

    def __init__(self, data: dict[str, Any]):
        self._data = data

    # --- loading -----------------------------------------------------------

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        # Load .env into the process environment if present (no-op otherwise).
        load_dotenv(ROOT / ".env")

        path = path or CONFIG_PATH
        if not path.exists():
            raise ConfigError(f"Config file not found: {path}")
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return cls(data)

    # --- access ------------------------------------------------------------

    def get(self, dotted_key: str, default: Any = None) -> Any:
        """Fetch a nested value by dotted path, e.g. ``model.name``."""
        node: Any = self._data
        for part in dotted_key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def require(self, dotted_key: str) -> Any:
        value = self.get(dotted_key)
        if value is None:
            raise ConfigError(f"Missing required config key: {dotted_key}")
        return value

    @staticmethod
    def secret(env_var: str, *, required: bool = True) -> str | None:
        """Read a secret from the environment. Secrets never live in YAML."""
        value = os.environ.get(env_var)
        if required and not value:
            raise ConfigError(
                f"Missing required secret: ${env_var}. "
                f"Copy .env.example to .env and fill it in."
            )
        return value
