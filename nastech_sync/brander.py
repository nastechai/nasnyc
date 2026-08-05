"""
Branding engine — applies NasTech branding to file contents and paths.
Replaces all Hermes / NousResearch references with NasTech equivalents.
"""

import re
import fnmatch
import logging
from pathlib import Path
from typing import Optional

from .config import NasTechSyncConfig, BrandingRule

logger = logging.getLogger("nastech_sync.brander")


class Brander:
    def __init__(self, config: NasTechSyncConfig):
        self.config = config
        self._text_extensions = set(config.text_extensions)
        self._exclude_patterns = config.exclude_patterns

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_text_file(self, path: Path) -> bool:
        """Return True if this file should have branding applied to its content."""
        name = path.name
        suffix = path.suffix

        # Check by extension
        if suffix in self._text_extensions:
            return True

        # Check by exact filename (e.g. Dockerfile, Makefile, LICENSE)
        if name in self._text_extensions:
            return True

        return False

    def is_excluded(self, rel_path: str) -> bool:
        """Return True if this path should be skipped entirely."""
        parts = Path(rel_path).parts
        for pattern in self._exclude_patterns:
            for part in parts:
                if fnmatch.fnmatch(part, pattern):
                    return True
            if fnmatch.fnmatch(rel_path, pattern):
                return True
        return False

    def brand_text(self, content: str, source_path: Optional[str] = None) -> str:
        """Apply all branding rules to a text string and return the result."""
        result = content
        for rule in self.config.branding_rules:
            result = self._apply_rule(result, rule)
        return result

    def brand_path(self, rel_path: str) -> str:
        """
        Return a new relative path with NasTech branding applied to
        directory names and filename.
        """
        parts = list(Path(rel_path).parts)
        branded_parts = []
        for part in parts:
            branded = part
            for rule in self.config.branding_rules:
                branded = self._apply_rule(branded, rule)
            branded_parts.append(branded)
        return str(Path(*branded_parts)) if branded_parts else rel_path

    def brand_file(self, src: Path, dst: Path) -> bool:
        """
        Copy src to dst, applying branding to text content.
        Returns True if any branding was applied to the content.
        """
        dst.parent.mkdir(parents=True, exist_ok=True)

        if not self.is_text_file(src):
            dst.write_bytes(src.read_bytes())
            return False

        try:
            original = src.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            logger.warning("Could not read %s as text (%s), copying verbatim", src, exc)
            dst.write_bytes(src.read_bytes())
            return False

        branded = self.brand_text(original, source_path=str(src))
        changed = branded != original
        dst.write_text(branded, encoding="utf-8")

        if changed:
            logger.debug("Branded: %s", src)

        return changed

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _apply_rule(self, text: str, rule: BrandingRule) -> str:
        if rule.case_sensitive:
            return text.replace(rule.find, rule.replace)
        else:
            return re.sub(re.escape(rule.find), rule.replace, text, flags=re.IGNORECASE)

    # ------------------------------------------------------------------
    # Diff summary
    # ------------------------------------------------------------------

    def describe_changes(self, original: str, branded: str) -> list[str]:
        """Return a list of human-readable change descriptions."""
        changes = []
        for rule in self.config.branding_rules:
            count = original.count(rule.find) if rule.case_sensitive else len(
                re.findall(re.escape(rule.find), original, re.IGNORECASE)
            )
            if count:
                changes.append(f"  '{rule.find}' → '{rule.replace}' ({count}x)")
        return changes
