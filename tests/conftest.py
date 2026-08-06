"""
Shared test fixtures for NasTech Sync.
"""
import pytest
from pathlib import Path
from nastech_sync.config import NasTechSyncConfig, RepoConfig, default_branding_rules


@pytest.fixture
def config():
    """Minimal config for tests — no real repos, no tokens."""
    return NasTechSyncConfig(
        upstream=RepoConfig(url="https://github.com/NousResearch/hermes-agent"),
        downstream=RepoConfig(url="https://github.com/nastechai/NasTech-Agent"),
        github_token=None,
        work_dir="/tmp/nastech-test-workspace",
        branding_rules=default_branding_rules(),
    )


@pytest.fixture
def brander(config):
    from nastech_sync.brander import Brander
    return Brander(config)


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """A temporary directory with sample dependency manifests for testing."""
    # requirements.txt
    (tmp_path / "requirements.txt").write_text(
        "requests==2.28.0\nhttpx>=0.25.0\nfastapi==0.100.0\n"
    )
    # package.json
    (tmp_path / "package.json").write_text(
        '{"dependencies": {"lodash": "4.17.20", "axios": "^0.27.0"}, "devDependencies": {"jest": "^28.0.0"}}'
    )
    # Cargo.toml
    (tmp_path / "Cargo.toml").write_text(
        '[package]\nname = "test"\nversion = "0.1.0"\n\n[dependencies]\nserde = "1.0.150"\ntokio = "1.25.0"\n'
    )
    # go.mod
    (tmp_path / "go.mod").write_text(
        'module example.com/app\n\ngo 1.20\n\nrequire (\n\tgithub.com/gin-gonic/gin v1.8.0\n)\n'
    )
    # pyproject.toml (poetry)
    (tmp_path / "pyproject.toml").write_text(
        '[tool.poetry]\nname = "test"\n\n[tool.poetry.dependencies]\npython = "^3.10"\npydantic = "^1.10.0"\n'
    )
    return tmp_path
