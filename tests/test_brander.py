"""
Tests for the NasTech branding engine.
"""
import pytest
from nastech_sync.brander import Brander


class TestBrandingRules:
    """Core branding correctness."""

    def test_bare_hermes_replaced(self, brander):
        assert brander.brand_text("Hermes") == "NasTech"

    def test_bare_nousresearch_replaced(self, brander):
        assert brander.brand_text("NousResearch") == "NasTech Research"

    def test_hermes_agent_replaced(self, brander):
        assert brander.brand_text("hermes-agent") == "NasTech-Agent"

    def test_upper_hermes_replaced(self, brander):
        assert brander.brand_text("HERMES") == "NASTECH"

    def test_hermes_underscore_replaced(self, brander):
        assert brander.brand_text("hermes_agent") == "nastech_agent"

    def test_camel_hermes_replaced(self, brander):
        assert brander.brand_text("HermesAgent") == "NasTechAgent"

    def test_nousresearch_variants(self, brander):
        assert brander.brand_text("nousresearch") == "nastechai"
        assert brander.brand_text("nous-research") == "nastechai"
        assert brander.brand_text("Nous Research") == "NasTech Research"

    def test_hermes_ai_replaced(self, brander):
        assert brander.brand_text("hermes-ai") == "nastech-ai"


class TestURLOrderSafety:
    """URL rules must fire before bare-word rules — critical ordering test."""

    def test_full_github_url_not_double_replaced(self, brander):
        inp = "github.com/NousResearch/hermes-agent"
        out = brander.brand_text(inp)
        assert "nastechai/NasTech-Agent" in out, f"Expected nastechai URL, got: {out}"
        assert "NousResearch" not in out, f"NousResearch leaked: {out}"

    def test_https_github_url(self, brander):
        inp = "https://github.com/NousResearch/hermes-agent"
        out = brander.brand_text(inp)
        assert "nastechai" in out
        assert "NousResearch" not in out

    def test_mixed_url_and_bare_word(self, brander):
        inp = "hermes-agent by NousResearch — see github.com/NousResearch/hermes-agent for Hermes 3"
        out = brander.brand_text(inp)
        assert "github.com/nastechai/NasTech-Agent" in out
        assert "NousResearch" not in out
        assert "Hermes 3" not in out or "NasTech 3" in out

    def test_docker_image_url(self, brander):
        inp = "nousresearch/hermes-agent:latest"
        out = brander.brand_text(inp)
        assert "nastechai/nastech-agent:latest" in out

    def test_sentence_with_url(self, brander):
        """URL inside a sentence — URL rule fires first, then bare words."""
        inp = "Check out NousResearch at github.com/NousResearch/hermes-agent"
        out = brander.brand_text(inp)
        assert "NousResearch" not in out
        assert "github.com/nastechai/NasTech-Agent" in out


class TestBranding100Percent:
    """Verify 100% branding — no upstream terms leak through."""

    UPSTREAM_TERMS = [
        "hermes-agent", "hermes_agent", "HermesAgent", "hermes-ai",
        "Hermes", "HERMES", "hermes",
        "NousResearch", "nousresearch", "Nous Research", "nous-research",
    ]

    @pytest.mark.parametrize("term", UPSTREAM_TERMS)
    def test_no_upstream_term_survives(self, brander, term):
        """Every upstream term must be transformed — none survive branding."""
        text = f"This is about {term} the model"
        result = brander.brand_text(text)
        # The exact input term must not appear verbatim in the output
        assert term not in result, (
            f"Upstream term '{term}' survived branding!\n"
            f"Input:  {text}\n"
            f"Output: {result}"
        )

    def test_output_contains_nastech(self, brander):
        inp = "The Hermes model by NousResearch is great. See hermes-agent on GitHub."
        out = brander.brand_text(inp)
        assert "NasTech" in out or "nastech" in out


class TestBranderPathBranding:
    """Test file path branding."""

    def test_path_with_hermes(self, brander):
        result = brander.brand_path("src/hermes_agent/main.py")
        assert "nastech_agent" in result
        assert "hermes_agent" not in result

    def test_path_preserves_extension(self, brander):
        result = brander.brand_path("docs/hermes-agent.md")
        assert result.endswith(".md")

    def test_path_unchanged_when_no_match(self, brander):
        result = brander.brand_path("src/main.py")
        assert result == "src/main.py"


class TestBranderDescribeChanges:
    """Test the describe_changes helper."""

    def test_describes_substitutions(self, brander):
        original = "Hermes is great"
        branded = brander.brand_text(original)
        changes = brander.describe_changes(original, branded)
        assert len(changes) > 0

    def test_no_changes_when_identical(self, brander):
        text = "NasTech is great"
        changes = brander.describe_changes(text, text)
        assert changes == []
