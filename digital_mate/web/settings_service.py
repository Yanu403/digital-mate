"""Settings service — read/write .env file.

Provides CRUD for .env values with secret redaction for the API layer.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Fields that should be masked in API responses
_SECRET_PATTERNS = re.compile(
    r"(token|key|secret|password)", re.IGNORECASE
)


class SettingsService:
    """Manages the .env file for the Digital Mate project."""

    def __init__(self, project_root: Path) -> None:
        self._env_path = project_root / ".env"
        self._project_root = project_root

    def _read_raw(self) -> dict[str, str]:
        """Read the .env file and return key-value pairs."""
        if not self._env_path.exists():
            return {}
        result: dict[str, str] = {}
        for line in self._env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            result[key] = value
        return result

    def get(self, key: str, default: str = "") -> str:
        """Get a single setting value."""
        data = self._read_raw()
        return data.get(key, default)

    def get_all_redacted(self) -> dict[str, Any]:
        """Return all settings with secrets masked.

        Returns:
            Dict of settings with secret values replaced by ***.
        """
        data = self._read_raw()
        result: dict[str, Any] = {}
        for key, value in data.items():
            if _SECRET_PATTERNS.search(key) and value:
                # Show first 4 and last 4 chars
                if len(value) > 8:
                    result[key] = value[:4] + "•" * (len(value) - 8) + value[-4:]
                else:
                    result[key] = "•" * len(value)
            else:
                result[key] = value
        result["_exists"] = True
        return result

    def exists(self) -> bool:
        """Check if .env file exists."""
        return self._env_path.exists()

    def has_required(self) -> bool:
        """Check if required fields are present."""
        data = self._read_raw()
        return bool(data.get("TELEGRAM_BOT_TOKEN")) and bool(data.get("LLM_API_KEY"))

    def save(self, updates: dict[str, Any]) -> None:
        """Update the .env file with new values.

        Args:
            updates: Dict of key-value pairs to write.
                Empty string values will be removed.
        """
        existing = self._read_raw()
        for key, value in updates.items():
            if key.startswith("_"):
                continue  # Skip meta keys
            if value == "" or value is None:
                existing.pop(key, None)
            else:
                existing[key] = str(value)

        lines: list[str] = []
        for key, value in existing.items():
            # Quote values that contain spaces
            if " " in str(value):
                lines.append(f'{key}="{value}"')
            else:
                lines.append(f"{key}={value}")

        self._env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        logger.info("Settings saved to %s", self._env_path)
