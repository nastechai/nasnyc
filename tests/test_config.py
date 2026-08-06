"""
Tests for NasTech Sync configuration loading.
"""
import os
import pytest
from pathlib import Path
from nastech_sync.config import (
    load_config, default_branding_rules, BrandingRule, NasTechSyncConfig
)


class TestDefaultBrandingRules:
    """Verify branding rule set is correct and in order."""

    def test_has_minimum_rules(self):
        rules = default_branding_rules()
        assert len(rules) >= 10, "Expected at least 10 branding rules"

    def test_full_github_url_before_bare_org(self):
        rules = default_branding_rules()
        finds = [r.find for r in rules]
        full_url_idx = next((i for i, f in enumerate(finds) if "NousResearch/hermes-agent" in f), None)
        bare_org_idx = next((i for i, f in enumerate(finds) if f == "NousResearch"), None)
        assert full_url_idx is not None, "Full GitHub URL rule missing"
        assert bare_org_idx is not None, "Bare NousResearch rule missing"
        assert full_url_idx < bare_org_idx, (
            f"Full URL rule ({full_url_idx}) must come before bare org ({bare_org_idx})"
        )

    def test_hermes_agent_before_bare_hermes(self):
        rules = default_branding_rules()
        finds = [r.find for r in rules]
        agent_idx = finds.index("hermes-agent")
        hermes_idx = finds.index("hermes")
        assert agent_idx < hermes_idx, "hermes-agent rule must precede bare hermes rule"

    def test_all_rules_have_find_and_replace(self):
        for rule in default_branding_rules():
            assert rule.find, f"Rule has empty find: {rule}"
            assert rule.replace, f"Rule has empty replace: {rule}"

    def test_no_nastech_in_find(self):
        """The 'find' fields should not contain NasTech terms — that would be circular."""
        for rule in default_branding_rules():
            assert "nastech" not in rule.find.lower(), (
                f"Rule find '{rule.find}' contains 'nastech' — circular replacement risk"
            )


class TestLoadConfig:
    """Config loading from YAML and env vars."""

    def test_default_config_loads(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("""
upstream:
  url: https://github.com/NousResearch/hermes-agent
downstream:
  url: https://github.com/nastechai/NasTech-Agent
""")
        config = load_config(str(cfg_file))
        assert "NousResearch" in config.upstream.url
        assert "nastechai" in config.downstream.url

    def test_env_var_overrides_github_token(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("upstream:\n  url: https://github.com/NousResearch/hermes-agent\ndownstream:\n  url: https://github.com/nastechai/NasTech-Agent\n")
        monkeypatch.setenv("GITHUB_TOKEN", "test-token-123")
        config = load_config(str(cfg_file))
        assert config.github_token == "test-token-123"

    def test_env_var_overrides_openai_key(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("upstream:\n  url: https://github.com/NousResearch/hermes-agent\ndownstream:\n  url: https://github.com/nastechai/NasTech-Agent\n")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        config = load_config(str(cfg_file))
        assert config.openai_api_key == "sk-test"

    def test_branding_rules_loaded(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("upstream:\n  url: https://github.com/NousResearch/hermes-agent\ndownstream:\n  url: https://github.com/nastechai/NasTech-Agent\n")
        config = load_config(str(cfg_file))
        assert len(config.branding_rules) >= 10

    def test_extra_branding_rules_appended(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("""
upstream:
  url: https://github.com/NousResearch/hermes-agent
downstream:
  url: https://github.com/nastechai/NasTech-Agent
extra_branding_rules:
  - find: "OldName"
    replace: "NewName"
""")
        config = load_config(str(cfg_file))
        finds = [r.find for r in config.branding_rules]
        assert "OldName" in finds

    def test_work_dir_default(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("upstream:\n  url: https://github.com/NousResearch/hermes-agent\ndownstream:\n  url: https://github.com/nastechai/NasTech-Agent\n")
        monkeypatch.delenv("NASTECH_WORK_DIR", raising=False)
        config = load_config(str(cfg_file))
        assert ".nastech-sync" in config.work_dir


class TestBrandingRuleDataclass:
    def test_default_case_sensitive(self):
        rule = BrandingRule(find="Hermes", replace="NasTech")
        assert rule.case_sensitive is True

    def test_case_insensitive_flag(self):
        rule = BrandingRule(find="hermes", replace="nastech", case_sensitive=False)
        assert rule.case_sensitive is False
