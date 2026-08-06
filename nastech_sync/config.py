"""
Configuration management for NasTech Sync.
Reads from config.yaml and environment variables.
"""

import os
import yaml
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


@dataclass
class RepoConfig:
    url: str
    branch: str = "main"
    local_path: str = ""


@dataclass
class BrandingRule:
    find: str
    replace: str
    case_sensitive: bool = True


@dataclass
class NasTechSyncConfig:
    upstream: RepoConfig
    downstream: RepoConfig
    # GitHub
    github_token: Optional[str] = None
    github_username: str = "nastechai"
    git_user_name: str = "NasTech-Agent"
    git_user_email: str = "agent@nastechai.com"
    # Paths
    work_dir: str = str(Path.home() / ".nastech-sync" / "workspace")
    log_file: str = str(Path.home() / ".nastech-sync" / "sync.log")
    # AI Brain
    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4o"
    ollama_url: str = "https://api.ollama.com"
    ollama_model: str = "llama3.1"
    ollama_api_key: Optional[str] = None  # for api.ollama.com (Bearer auth)
    # Telegram
    telegram_bot_token: Optional[str] = None
    telegram_chat_ids: str = ""   # comma-separated int IDs
    # Branding
    branding_rules: list = field(default_factory=list)
    # File extensions to apply branding to (others are copied verbatim)
    text_extensions: list = field(default_factory=lambda: [
        ".py", ".md", ".txt", ".yaml", ".yml", ".json", ".toml",
        ".cfg", ".ini", ".sh", ".bash", ".rst", ".html", ".js",
        ".ts", ".tsx", ".jsx", ".css", ".env", ".example",
        "Dockerfile", ".dockerfile", "Makefile", ".mk",
        ".gitignore", ".gitattributes", "LICENSE", "NOTICE",
    ])
    # PR settings
    pr_draft: bool = False
    pr_labels: list = field(default_factory=lambda: ["auto-sync", "nastech-branded"])
    # Dependency check settings
    dep_check_enabled: bool = True
    dep_check_ecosystems: list = field(default_factory=list)  # empty = all
    dep_auto_update: bool = False
    # Files/dirs to never copy from upstream
    exclude_patterns: list = field(default_factory=lambda: [
        ".git", "__pycache__", "*.pyc", "*.pyo",
        ".DS_Store", "node_modules", ".venv", "venv",
    ])


def default_branding_rules() -> list[BrandingRule]:
    """
    Return the default NasTech branding rules.

    ORDER IS CRITICAL — more specific / longer patterns MUST come before
    shorter ones that are substrings of them.  E.g. the full GitHub URL
    must fire before "NousResearch" alone, otherwise "NousResearch" inside
    the URL gets replaced first and the URL rule never matches.
    """
    return [
        # ── Full GitHub URLs (most specific — must be first) ──────────
        BrandingRule(
            "github.com/NousResearch/hermes-agent",
            "github.com/nastechai/NasTech-Agent",
        ),
        BrandingRule(
            "https://github.com/NousResearch",
            "https://github.com/nastechai",
        ),
        BrandingRule(
            "github.com/NousResearch",
            "github.com/nastechai",
        ),

        # ── Docker / registry (before bare org name) ─────────────────
        BrandingRule("nousresearch/hermes-agent", "nastechai/nastech-agent"),
        BrandingRule("nousresearch/hermes", "nastechai/nastech"),

        # ── Repo / project name variants (before bare "hermes") ───────
        BrandingRule("hermes-agent", "NasTech-Agent"),
        BrandingRule("hermes_agent", "nastech_agent"),
        BrandingRule("HermesAgent", "NasTechAgent"),
        BrandingRule("hermes-ai", "nastech-ai"),
        BrandingRule("hermes_ai", "nastech_ai"),

        # ── Organisation name variants (before bare brand word) ───────
        BrandingRule("NousResearch", "NasTech Research"),
        BrandingRule("Nous Research", "NasTech Research"),
        BrandingRule("nous-research", "nastechai"),
        BrandingRule("nousresearch", "nastechai"),

        # ── Brand name — longest/most-specific first ──────────────────
        BrandingRule("HERMES", "NASTECH"),
        BrandingRule("Hermes", "NasTech"),
        BrandingRule("hermes", "nastech"),
    ]


def _load_dotenv(work_dir: str) -> None:
    """Load .env file from work_dir into os.environ (does not overwrite existing vars)."""
    env_file = Path(work_dir) / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip()
        if k and k not in os.environ:  # don't overwrite shell env
            os.environ[k] = v


def load_config(config_path: Optional[str] = None) -> NasTechSyncConfig:
    """Load config from YAML file + .env file + environment variable overrides."""
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH

    raw: dict = {}
    if path.exists():
        with open(path) as f:
            raw = yaml.safe_load(f) or {}

    # Determine work_dir early so we can load .env from it
    work_dir_early = (
        os.environ.get("NASTECH_WORK_DIR")
        or raw.get("work_dir")
        or str(Path.home() / ".nastech-sync" / "workspace")
    )
    _load_dotenv(work_dir_early)

    upstream_cfg = raw.get("upstream", {})
    downstream_cfg = raw.get("downstream", {})

    # Determine work dir
    work_dir = (
        os.environ.get("NASTECH_WORK_DIR")
        or raw.get("work_dir")
        or str(Path.home() / ".nastech-sync" / "workspace")
    )

    upstream = RepoConfig(
        url=upstream_cfg.get("url", "https://github.com/NousResearch/hermes-agent"),
        branch=upstream_cfg.get("branch", "main"),
        local_path=upstream_cfg.get("local_path", str(Path(work_dir) / "upstream")),
    )

    downstream = RepoConfig(
        url=downstream_cfg.get("url", "https://github.com/nastechai/NasTech-Agent"),
        branch=downstream_cfg.get("branch", "main"),
        local_path=downstream_cfg.get("local_path", str(Path(work_dir) / "downstream")),
    )

    # Build branding rules (custom rules in config override defaults)
    branding_rules = default_branding_rules()
    for rule in raw.get("extra_branding_rules", []):
        branding_rules.append(BrandingRule(
            find=rule["find"],
            replace=rule["replace"],
            case_sensitive=rule.get("case_sensitive", True),
        ))

    return NasTechSyncConfig(
        upstream=upstream,
        downstream=downstream,
        # GitHub
        github_token=os.environ.get("GITHUB_TOKEN") or raw.get("github_token"),
        github_username=raw.get("github_username", "nastechai"),
        git_user_name=raw.get("git_user_name", "NasTech-Agent"),
        git_user_email=raw.get("git_user_email", "agent@nastechai.com"),
        # Paths
        work_dir=work_dir,
        log_file=raw.get("log_file", str(Path.home() / ".nastech-sync" / "sync.log")),
        # AI Brain
        openai_api_key=os.environ.get("OPENAI_API_KEY") or raw.get("openai_api_key"),
        openai_model=raw.get("openai_model", "gpt-4o"),
        ollama_url=os.environ.get("OLLAMA_URL") or raw.get("ollama_url", "https://api.ollama.com"),
        ollama_model=raw.get("ollama_model", "llama3.1"),
        ollama_api_key=os.environ.get("OLLAMA_API_KEY") or raw.get("ollama_api_key"),
        # Telegram
        telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN") or raw.get("telegram_bot_token"),
        telegram_chat_ids=os.environ.get("TELEGRAM_CHAT_IDS") or raw.get("telegram_chat_ids", ""),
        # Branding
        branding_rules=branding_rules,
        text_extensions=raw.get("text_extensions", NasTechSyncConfig.__dataclass_fields__["text_extensions"].default_factory()),
        exclude_patterns=raw.get("exclude_patterns", NasTechSyncConfig.__dataclass_fields__["exclude_patterns"].default_factory()),
    )
