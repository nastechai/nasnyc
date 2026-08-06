"""
NasTech Dependency Scanner — multi-ecosystem package version checker.

Supported ecosystems:
  • npm / yarn / pnpm  — package.json
  • pip               — requirements.txt, setup.cfg, pyproject.toml
  • poetry            — pyproject.toml [tool.poetry]
  • cargo (Rust)      — Cargo.toml
  • go                — go.mod
  • composer (PHP)    — composer.json
  • bundler (Ruby)    — Gemfile / Gemfile.lock
  • dotnet (C#)       — *.csproj / *.vbproj / *.fsproj
  • gradle (Java)     — build.gradle / build.gradle.kts
  • maven (Java)      — pom.xml

Usage:
  scanner = DependencyScanner(root_path="/path/to/project")
  report = await scanner.scan()
  for result in report.outdated():
      print(result)
"""

import re
import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import xml.etree.ElementTree as ET

import httpx

logger = logging.getLogger("nastech_sync.dependency_scanner")


@dataclass
class PackageInfo:
    name: str
    current_version: str
    latest_version: Optional[str]
    ecosystem: str
    manifest_file: str
    is_outdated: bool = False
    latest_url: Optional[str] = None
    error: Optional[str] = None

    def __str__(self) -> str:
        status = "✅" if not self.is_outdated else "⬆️"
        if self.error:
            status = "❌"
        ver_info = f"{self.current_version}"
        if self.is_outdated and self.latest_version:
            ver_info += f" → {self.latest_version}"
        return f"{status} [{self.ecosystem}] {self.name} {ver_info}"


@dataclass
class ScanReport:
    root_path: str
    packages: list[PackageInfo] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def outdated(self) -> list[PackageInfo]:
        return [p for p in self.packages if p.is_outdated]

    def up_to_date(self) -> list[PackageInfo]:
        return [p for p in self.packages if not p.is_outdated and not p.error]

    def errored(self) -> list[PackageInfo]:
        return [p for p in self.packages if p.error]

    def by_ecosystem(self) -> dict[str, list[PackageInfo]]:
        result: dict[str, list[PackageInfo]] = {}
        for p in self.packages:
            result.setdefault(p.ecosystem, []).append(p)
        return result

    def summary(self) -> str:
        total = len(self.packages)
        outdated = len(self.outdated())
        errors = len(self.errored())
        return (
            f"Scanned {total} packages across {len(self.by_ecosystem())} ecosystems. "
            f"Outdated: {outdated} | Up-to-date: {total - outdated - errors} | Errors: {errors}"
        )

    def markdown_report(self) -> str:
        lines = ["# NasTech Dependency Report\n"]
        lines.append(f"**{self.summary()}**\n")

        by_eco = self.by_ecosystem()
        for eco, pkgs in sorted(by_eco.items()):
            lines.append(f"\n## {eco.upper()}\n")
            lines.append("| Package | Current | Latest | Status |")
            lines.append("|---------|---------|--------|--------|")
            for p in sorted(pkgs, key=lambda x: x.name):
                status = "✅ Up to date" if not p.is_outdated else f"⬆️ **{p.latest_version}**"
                if p.error:
                    status = f"❌ {p.error}"
                latest = p.latest_version or "unknown"
                lines.append(f"| `{p.name}` | `{p.current_version}` | `{latest}` | {status} |")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Version helpers
# ---------------------------------------------------------------------------

def _clean_version(v: str) -> str:
    """Strip range specifiers to get a bare version string."""
    return re.sub(r"^[^0-9]*", "", str(v)).strip() if v else ""


def _version_tuple(v: str) -> tuple:
    try:
        return tuple(int(x) for x in re.split(r"[.\-]", v.split("+")[0]) if x.isdigit())
    except Exception:
        return (0,)


def _is_outdated(current: str, latest: str) -> bool:
    if not current or not latest:
        return False
    try:
        return _version_tuple(_clean_version(latest)) > _version_tuple(_clean_version(current))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Registry helpers (async HTTP)
# ---------------------------------------------------------------------------

async def _fetch_json(client: httpx.AsyncClient, url: str) -> Optional[dict]:
    try:
        r = await client.get(url, timeout=10, follow_redirects=True)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        logger.debug("HTTP error for %s: %s", url, e)
    return None


async def _npm_latest(client: httpx.AsyncClient, pkg: str) -> Optional[str]:
    data = await _fetch_json(client, f"https://registry.npmjs.org/{pkg}/latest")
    return data.get("version") if data else None


async def _pypi_latest(client: httpx.AsyncClient, pkg: str) -> Optional[str]:
    data = await _fetch_json(client, f"https://pypi.org/pypi/{pkg}/json")
    if data:
        return data.get("info", {}).get("version")
    return None


async def _crates_latest(client: httpx.AsyncClient, pkg: str) -> Optional[str]:
    data = await _fetch_json(client, f"https://crates.io/api/v1/crates/{pkg}")
    if data:
        return data.get("crate", {}).get("max_stable_version") or data.get("crate", {}).get("max_version")
    return None


async def _go_latest(client: httpx.AsyncClient, module: str) -> Optional[str]:
    # Go proxy: strip leading 'v' from module paths that have versions
    url = f"https://proxy.golang.org/{module}/@latest"
    data = await _fetch_json(client, url)
    if data:
        return data.get("Version", "").lstrip("v") or None
    return None


async def _packagist_latest(client: httpx.AsyncClient, pkg: str) -> Optional[str]:
    data = await _fetch_json(client, f"https://packagist.org/packages/{pkg}.json")
    if data:
        versions = list(data.get("package", {}).get("versions", {}).keys())
        stable = [v for v in versions if not re.search(r"(alpha|beta|dev|rc)", v, re.I)]
        if stable:
            return stable[0].lstrip("v")
    return None


async def _rubygems_latest(client: httpx.AsyncClient, pkg: str) -> Optional[str]:
    data = await _fetch_json(client, f"https://rubygems.org/api/v1/gems/{pkg}.json")
    return data.get("version") if data else None


async def _nuget_latest(client: httpx.AsyncClient, pkg: str) -> Optional[str]:
    data = await _fetch_json(client, f"https://api.nuget.org/v3-flatcontainer/{pkg.lower()}/index.json")
    if data:
        versions = data.get("versions", [])
        stable = [v for v in versions if not re.search(r"(alpha|beta|preview|rc)", v, re.I)]
        return stable[-1] if stable else (versions[-1] if versions else None)
    return None


# ---------------------------------------------------------------------------
# Manifest parsers
# ---------------------------------------------------------------------------

def _parse_requirements_txt(path: Path) -> list[tuple[str, str]]:
    """Parse requirements.txt — returns [(name, version_spec), ...]"""
    packages = []
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        # Handle git URLs, env markers
        m = re.match(r"^([A-Za-z0-9_.\-]+)\s*([><=!~^,\s0-9.*]+)?", line)
        if m:
            name = m.group(1)
            ver = (m.group(2) or "").strip()
            packages.append((name, ver))
    return packages


def _parse_package_json(path: Path) -> list[tuple[str, str]]:
    import json
    try:
        data = json.loads(path.read_text())
    except Exception:
        return []
    packages = []
    for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        for name, ver in data.get(section, {}).items():
            if not name.startswith("//"):
                packages.append((name, str(ver)))
    return packages


def _parse_cargo_toml(path: Path) -> list[tuple[str, str]]:
    try:
        import tomllib  # Python 3.11+
    except ImportError:
        try:
            import tomli as tomllib
        except ImportError:
            logger.warning("tomllib/tomli not available — cannot parse Cargo.toml")
            return []
    try:
        data = tomllib.loads(path.read_text())
    except Exception:
        return []
    packages = []
    for section in ("dependencies", "dev-dependencies", "build-dependencies"):
        for name, spec in data.get(section, {}).items():
            if isinstance(spec, str):
                packages.append((name, spec))
            elif isinstance(spec, dict):
                packages.append((name, spec.get("version", "")))
    return packages


def _parse_go_mod(path: Path) -> list[tuple[str, str]]:
    packages = []
    in_require = False
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if line.startswith("require ("):
            in_require = True
            continue
        if in_require and line == ")":
            in_require = False
            continue
        if in_require or line.startswith("require "):
            parts = line.replace("require ", "").split()
            if len(parts) >= 2:
                module, ver = parts[0], parts[1].lstrip("v")
                packages.append((module, ver))
    return packages


def _parse_pyproject_toml(path: Path) -> tuple[list[tuple[str, str]], str]:
    """Returns (packages, ecosystem) — ecosystem is 'poetry' or 'pip'."""
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib
        except ImportError:
            return [], "pip"
    try:
        data = tomllib.loads(path.read_text())
    except Exception:
        return [], "pip"

    # Poetry
    poetry_deps = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
    if poetry_deps:
        packages = []
        for name, spec in poetry_deps.items():
            if name.lower() == "python":
                continue
            if isinstance(spec, str):
                packages.append((name, spec))
            elif isinstance(spec, dict):
                packages.append((name, spec.get("version", "")))
        return packages, "poetry"

    # PEP 517 / setuptools
    deps = data.get("project", {}).get("dependencies", [])
    packages = []
    for dep in deps:
        m = re.match(r"^([A-Za-z0-9_.\-]+)\s*([><=!~^,\s0-9.*]+)?", dep)
        if m:
            packages.append((m.group(1), (m.group(2) or "").strip()))
    return packages, "pip"


def _parse_composer_json(path: Path) -> list[tuple[str, str]]:
    import json
    try:
        data = json.loads(path.read_text())
    except Exception:
        return []
    packages = []
    for section in ("require", "require-dev"):
        for name, ver in data.get(section, {}).items():
            if name != "php" and "/" in name:
                packages.append((name, str(ver)))
    return packages


def _parse_gemfile(path: Path) -> list[tuple[str, str]]:
    packages = []
    for line in path.read_text(errors="replace").splitlines():
        m = re.match(r"""gem\s+['"]([^'"]+)['"]\s*(?:,\s*['"]([^'"]+)['"])?""", line.strip())
        if m:
            packages.append((m.group(1), m.group(2) or ""))
    return packages


def _parse_csproj(path: Path) -> list[tuple[str, str]]:
    packages = []
    try:
        tree = ET.parse(path)
        for ref in tree.findall(".//PackageReference"):
            name = ref.get("Include", "")
            ver = ref.get("Version", "")
            if name:
                packages.append((name, ver))
    except Exception:
        pass
    return packages


def _parse_gradle(path: Path) -> list[tuple[str, str]]:
    packages = []
    content = path.read_text(errors="replace")
    # Match: implementation 'group:artifact:version'  or  implementation("g:a:v")
    for m in re.finditer(
        r"""(?:implementation|api|compileOnly|runtimeOnly|testImplementation)\s*[("']([^"']+)[)"']""",
        content,
    ):
        parts = m.group(1).split(":")
        if len(parts) >= 3:
            packages.append((f"{parts[0]}:{parts[1]}", parts[2]))
    return packages


def _parse_pom_xml(path: Path) -> list[tuple[str, str]]:
    packages = []
    try:
        tree = ET.parse(path)
        ns = {"m": "http://maven.apache.org/POM/4.0.0"}
        deps = tree.findall(".//m:dependency", ns) or tree.findall(".//dependency")
        for dep in deps:
            gid = dep.findtext("groupId") or dep.findtext("{http://maven.apache.org/POM/4.0.0}groupId") or ""
            aid = dep.findtext("artifactId") or dep.findtext("{http://maven.apache.org/POM/4.0.0}artifactId") or ""
            ver = dep.findtext("version") or dep.findtext("{http://maven.apache.org/POM/4.0.0}version") or ""
            if gid and aid:
                packages.append((f"{gid}:{aid}", ver.strip("${}")))
    except Exception:
        pass
    return packages


# ---------------------------------------------------------------------------
# Main scanner
# ---------------------------------------------------------------------------

class DependencyScanner:
    """
    Walks a project directory and scans all dependency manifests it finds.
    Checks latest versions from upstream registries asynchronously.
    """

    MANIFEST_MAP = {
        "requirements.txt": "requirements",
        "requirements-dev.txt": "requirements",
        "requirements-test.txt": "requirements",
        "package.json": "npm",
        "Cargo.toml": "cargo",
        "go.mod": "go",
        "pyproject.toml": "pyproject",
        "composer.json": "composer",
        "Gemfile": "gemfile",
        "pom.xml": "maven",
        "build.gradle": "gradle",
        "build.gradle.kts": "gradle",
    }
    CSPROJ_GLOB = "**/*.csproj"
    SKIP_DIRS = {
        ".git", "node_modules", ".venv", "venv", "__pycache__",
        "vendor", "target", ".cargo", "dist", "build", ".tox",
    }

    def __init__(self, root_path: str = "."):
        self.root = Path(root_path)

    def _is_excluded(self, path: Path) -> bool:
        """Return True if this path is inside a skip directory."""
        try:
            rel = path.relative_to(self.root)
        except ValueError:
            rel = path
        return any(part in self.SKIP_DIRS for part in rel.parts)

    def _find_manifests(self) -> list[tuple[Path, str]]:
        found = []
        for path in self.root.rglob("*"):
            if not path.is_file():
                continue
            if self._is_excluded(path):
                continue
            if path.name in self.MANIFEST_MAP:
                found.append((path, self.MANIFEST_MAP[path.name]))
        # .csproj / .vbproj files
        for glob in ("*.csproj", "*.vbproj"):
            for path in self.root.rglob(glob):
                if path.is_file() and not self._is_excluded(path):
                    found.append((path, "dotnet"))
        return found

    async def _check_package(
        self,
        client: httpx.AsyncClient,
        name: str,
        current: str,
        ecosystem: str,
        manifest_file: str,
    ) -> PackageInfo:
        latest = None
        url = None
        error = None
        try:
            if ecosystem in ("pip", "poetry"):
                latest = await _pypi_latest(client, name)
                url = f"https://pypi.org/project/{name}/"
            elif ecosystem == "npm":
                latest = await _npm_latest(client, name)
                url = f"https://www.npmjs.com/package/{name}"
            elif ecosystem == "cargo":
                latest = await _crates_latest(client, name)
                url = f"https://crates.io/crates/{name}"
            elif ecosystem == "go":
                latest = await _go_latest(client, name)
                url = f"https://pkg.go.dev/{name}"
            elif ecosystem == "composer":
                latest = await _packagist_latest(client, name)
                url = f"https://packagist.org/packages/{name}"
            elif ecosystem == "gemfile":
                latest = await _rubygems_latest(client, name)
                url = f"https://rubygems.org/gems/{name}"
            elif ecosystem == "dotnet":
                latest = await _nuget_latest(client, name)
                url = f"https://www.nuget.org/packages/{name}"
            # gradle/maven: skip version check (Maven Central API is complex)
        except Exception as e:
            error = str(e)[:80]

        clean_current = _clean_version(current)
        clean_latest = _clean_version(latest) if latest else None
        outdated = _is_outdated(clean_current, clean_latest) if clean_latest else False

        return PackageInfo(
            name=name,
            current_version=clean_current or current or "unknown",
            latest_version=clean_latest,
            ecosystem=ecosystem,
            manifest_file=str(manifest_file),
            is_outdated=outdated,
            latest_url=url,
            error=error,
        )

    async def scan(self, concurrency: int = 20) -> ScanReport:
        """Scan all manifests and check for outdated packages."""
        report = ScanReport(root_path=str(self.root))
        manifests = self._find_manifests()

        if not manifests:
            logger.info("No dependency manifests found in %s", self.root)
            return report

        # Collect all packages across manifests
        raw_packages: list[tuple[str, str, str, str]] = []  # (name, version, ecosystem, file)

        for path, kind in manifests:
            try:
                pairs: list[tuple[str, str]] = []
                ecosystem = kind

                if kind == "requirements":
                    pairs = _parse_requirements_txt(path)
                    ecosystem = "pip"
                elif kind == "npm":
                    pairs = _parse_package_json(path)
                    ecosystem = "npm"
                elif kind == "cargo":
                    pairs = _parse_cargo_toml(path)
                    ecosystem = "cargo"
                elif kind == "go":
                    pairs = _parse_go_mod(path)
                    ecosystem = "go"
                elif kind == "pyproject":
                    pairs, ecosystem = _parse_pyproject_toml(path)
                elif kind == "composer":
                    pairs = _parse_composer_json(path)
                    ecosystem = "composer"
                elif kind == "gemfile":
                    pairs = _parse_gemfile(path)
                    ecosystem = "gemfile"
                elif kind == "dotnet":
                    pairs = _parse_csproj(path)
                    ecosystem = "dotnet"
                elif kind == "gradle":
                    pairs = _parse_gradle(path)
                    ecosystem = "gradle"
                elif kind == "maven":
                    pairs = _parse_pom_xml(path)
                    ecosystem = "maven"

                logger.info("Found %d packages in %s [%s]", len(pairs), path.name, ecosystem)
                for name, ver in pairs:
                    if name:
                        raw_packages.append((name, ver, ecosystem, str(path)))
            except Exception as e:
                report.errors.append(f"Error parsing {path}: {e}")
                logger.warning("Error parsing %s: %s", path, e)

        # De-duplicate by (name, ecosystem)
        seen: set[tuple[str, str]] = set()
        deduped = []
        for name, ver, eco, fpath in raw_packages:
            key = (name.lower(), eco)
            if key not in seen:
                seen.add(key)
                deduped.append((name, ver, eco, fpath))

        logger.info("Checking %d unique packages against upstream registries...", len(deduped))

        # Check all packages concurrently (bounded)
        sem = asyncio.Semaphore(concurrency)
        async with httpx.AsyncClient(
            headers={"User-Agent": "NasTech-Sync/1.0"},
            timeout=15,
        ) as client:
            async def bounded_check(name, ver, eco, fpath):
                async with sem:
                    return await self._check_package(client, name, ver, eco, fpath)

            tasks = [
                bounded_check(name, ver, eco, fpath)
                for name, ver, eco, fpath in deduped
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        for r in results:
            if isinstance(r, PackageInfo):
                report.packages.append(r)
            elif isinstance(r, Exception):
                report.errors.append(str(r))

        outdated_count = len(report.outdated())
        logger.info("Scan complete. %d outdated out of %d packages.", outdated_count, len(report.packages))
        return report


async def scan_directory(path: str = ".") -> ScanReport:
    """Convenience wrapper."""
    scanner = DependencyScanner(root_path=path)
    return await scanner.scan()
