"""
NasTech Dependency Updater — applies version updates to manifest files.

Supports:
  • requirements.txt — bumps pinned or range versions
  • package.json     — bumps all dependency sections
  • Cargo.toml       — bumps [dependencies] versions
  • pyproject.toml   — bumps [project.dependencies] and [tool.poetry.dependencies]
  • go.mod           — bumps require() versions (via `go get` if available)
  • composer.json    — bumps require / require-dev
  • Gemfile          — bumps gem version strings

Can create a Git commit or open a PR for all updates.
"""

import re
import json
import logging
import subprocess
from pathlib import Path
from typing import Optional

from .dependency_scanner import PackageInfo, ScanReport

logger = logging.getLogger("nastech_sync.dependency_updater")


class DependencyUpdater:
    def __init__(self, root_path: str = "."):
        self.root = Path(root_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def apply_updates(
        self,
        report: ScanReport,
        dry_run: bool = False,
        ecosystems: Optional[list[str]] = None,
    ) -> dict[str, list[str]]:
        """
        Apply all updates found in *report*.
        Returns {filepath: [changes]} dict.
        If dry_run=True, returns what WOULD change without writing.
        """
        updates: dict[str, list[str]] = {}

        outdated = report.outdated()
        if not outdated:
            return updates

        # Group by manifest file
        by_file: dict[str, list[PackageInfo]] = {}
        for pkg in outdated:
            if ecosystems and pkg.ecosystem not in ecosystems:
                continue
            by_file.setdefault(pkg.manifest_file, []).append(pkg)

        for fpath, pkgs in by_file.items():
            path = Path(fpath)
            if not path.exists():
                continue
            changes = self._update_manifest(path, pkgs, dry_run=dry_run)
            if changes:
                updates[str(path)] = changes

        return updates

    def _update_manifest(
        self, path: Path, pkgs: list[PackageInfo], dry_run: bool
    ) -> list[str]:
        name = path.name.lower()
        if name in ("requirements.txt", "requirements-dev.txt", "requirements-test.txt"):
            return self._update_requirements_txt(path, pkgs, dry_run)
        elif name == "package.json":
            return self._update_package_json(path, pkgs, dry_run)
        elif name == "cargo.toml":
            return self._update_cargo_toml(path, pkgs, dry_run)
        elif name == "pyproject.toml":
            return self._update_pyproject_toml(path, pkgs, dry_run)
        elif name == "go.mod":
            return self._update_go_mod(path, pkgs, dry_run)
        elif name == "composer.json":
            return self._update_composer_json(path, pkgs, dry_run)
        elif name == "gemfile":
            return self._update_gemfile(path, pkgs, dry_run)
        return []

    # ------------------------------------------------------------------
    # requirements.txt
    # ------------------------------------------------------------------

    def _update_requirements_txt(
        self, path: Path, pkgs: list[PackageInfo], dry_run: bool
    ) -> list[str]:
        content = path.read_text()
        original = content
        changes = []

        for pkg in pkgs:
            if not pkg.latest_version:
                continue
            # Match: pkg_name>=x.y.z or pkg_name==x.y.z or pkg_name~=x.y
            pattern = rf"(?i)({re.escape(pkg.name)})\s*([><=!~^,\s]+)[\d.*]+"
            new_ver = pkg.latest_version
            match = re.search(pattern, content)
            if match:
                op = match.group(2).strip()
                # Preserve the operator, just bump version
                if "==" in op:
                    replacement = f"{pkg.name}=={new_ver}"
                elif ">=" in op:
                    replacement = f"{pkg.name}>={new_ver}"
                elif "~=" in op:
                    # Compatible release: keep major.minor
                    parts = new_ver.split(".")
                    compat = ".".join(parts[:2]) if len(parts) >= 2 else new_ver
                    replacement = f"{pkg.name}~={compat}"
                else:
                    replacement = f"{pkg.name}>={new_ver}"
                content = re.sub(pattern, replacement, content, flags=re.IGNORECASE)
                changes.append(f"{pkg.name}: {pkg.current_version} → {new_ver}")
            else:
                logger.debug("No match for %s in %s — skipping", pkg.name, path.name)

        if content != original and not dry_run:
            path.write_text(content)
        return changes

    # ------------------------------------------------------------------
    # package.json
    # ------------------------------------------------------------------

    def _update_package_json(
        self, path: Path, pkgs: list[PackageInfo], dry_run: bool
    ) -> list[str]:
        try:
            data = json.loads(path.read_text())
        except Exception:
            return []

        changes = []
        pkg_map = {p.name.lower(): p for p in pkgs}

        for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
            if section not in data:
                continue
            for name in list(data[section].keys()):
                pkg = pkg_map.get(name.lower())
                if not pkg or not pkg.latest_version:
                    continue
                old_spec = data[section][name]
                # Preserve prefix: ^, ~, >=, exact, *
                prefix = ""
                m = re.match(r"^([~^>=<]+)", str(old_spec))
                if m:
                    prefix = m.group(1)
                new_spec = f"{prefix}{pkg.latest_version}"
                data[section][name] = new_spec
                changes.append(f"{name}: {old_spec} → {new_spec}")

        if changes and not dry_run:
            path.write_text(json.dumps(data, indent=2) + "\n")
        return changes

    # ------------------------------------------------------------------
    # Cargo.toml (simple regex — toml writer without library)
    # ------------------------------------------------------------------

    def _update_cargo_toml(
        self, path: Path, pkgs: list[PackageInfo], dry_run: bool
    ) -> list[str]:
        content = path.read_text()
        original = content
        changes = []

        for pkg in pkgs:
            if not pkg.latest_version:
                continue
            # Match: pkg_name = "version" or pkg_name = { version = "x.y.z" }
            pattern = rf'(?m)^({re.escape(pkg.name)}\s*=\s*)"([^"]*)"'
            m = re.search(pattern, content)
            if m:
                content = re.sub(pattern, rf'\1"{pkg.latest_version}"', content)
                changes.append(f"{pkg.name}: {pkg.current_version} → {pkg.latest_version}")
            else:
                # Dict form: version = "x.y.z"
                pattern2 = rf'(?m)(^{re.escape(pkg.name)}\s*=\s*\{{[^}}]*version\s*=\s*)"([^"]*)"'
                m2 = re.search(pattern2, content)
                if m2:
                    content = re.sub(pattern2, rf'\1"{pkg.latest_version}"', content)
                    changes.append(f"{pkg.name}: {pkg.current_version} → {pkg.latest_version}")

        if content != original and not dry_run:
            path.write_text(content)
        return changes

    # ------------------------------------------------------------------
    # pyproject.toml
    # ------------------------------------------------------------------

    def _update_pyproject_toml(
        self, path: Path, pkgs: list[PackageInfo], dry_run: bool
    ) -> list[str]:
        content = path.read_text()
        original = content
        changes = []

        for pkg in pkgs:
            if not pkg.latest_version:
                continue
            # Poetry: pkg_name = "^x.y.z" or ">=x.y"
            pattern = rf'(?m)^({re.escape(pkg.name)}\s*=\s*)"([^"]*)"'
            m = re.search(pattern, content, re.IGNORECASE)
            if m:
                old_spec = m.group(2)
                prefix_m = re.match(r"^([~^>=<]+)", old_spec)
                prefix = prefix_m.group(1) if prefix_m else ""
                new_spec = f"{prefix}{pkg.latest_version}"
                content = re.sub(pattern, rf'\1"{new_spec}"', content, flags=re.IGNORECASE)
                changes.append(f"{pkg.name}: {old_spec} → {new_spec}")
            else:
                # PEP 517 list form: "pkg>=x.y"
                for op in (">=", "==", "~=", "!="):
                    pattern2 = rf'"{re.escape(pkg.name)}\s*{re.escape(op)}\s*[\d.*]+"'
                    if re.search(pattern2, content, re.IGNORECASE):
                        new = f'"{pkg.name}{op}{pkg.latest_version}"'
                        content = re.sub(pattern2, new, content, flags=re.IGNORECASE)
                        changes.append(f"{pkg.name}: {pkg.current_version} → {pkg.latest_version}")
                        break

        if content != original and not dry_run:
            path.write_text(content)
        return changes

    # ------------------------------------------------------------------
    # go.mod
    # ------------------------------------------------------------------

    def _update_go_mod(
        self, path: Path, pkgs: list[PackageInfo], dry_run: bool
    ) -> list[str]:
        content = path.read_text()
        original = content
        changes = []

        for pkg in pkgs:
            if not pkg.latest_version:
                continue
            pattern = rf"(?m)(\s+{re.escape(pkg.name)}\s+)v[\d.+\-a-z]+"
            m = re.search(pattern, content)
            if m:
                content = re.sub(pattern, rf"\g<1>v{pkg.latest_version}", content)
                changes.append(f"{pkg.name}: {pkg.current_version} → {pkg.latest_version}")

        if content != original and not dry_run:
            path.write_text(content)
        return changes

    # ------------------------------------------------------------------
    # composer.json
    # ------------------------------------------------------------------

    def _update_composer_json(
        self, path: Path, pkgs: list[PackageInfo], dry_run: bool
    ) -> list[str]:
        try:
            data = json.loads(path.read_text())
        except Exception:
            return []
        changes = []
        pkg_map = {p.name.lower(): p for p in pkgs}

        for section in ("require", "require-dev"):
            for name in list(data.get(section, {}).keys()):
                pkg = pkg_map.get(name.lower())
                if not pkg or not pkg.latest_version:
                    continue
                old = data[section][name]
                prefix_m = re.match(r"^([~^>=<]+)", str(old))
                prefix = prefix_m.group(1) if prefix_m else "^"
                data[section][name] = f"{prefix}{pkg.latest_version}"
                changes.append(f"{name}: {old} → {data[section][name]}")

        if changes and not dry_run:
            path.write_text(json.dumps(data, indent=4) + "\n")
        return changes

    # ------------------------------------------------------------------
    # Gemfile
    # ------------------------------------------------------------------

    def _update_gemfile(
        self, path: Path, pkgs: list[PackageInfo], dry_run: bool
    ) -> list[str]:
        content = path.read_text()
        original = content
        changes = []

        for pkg in pkgs:
            if not pkg.latest_version:
                continue
            pattern = rf"""(gem\s+['"]({re.escape(pkg.name)})['"]\s*,\s*['"])([^'"]+)(['"])"""
            m = re.search(pattern, content, re.IGNORECASE)
            if m:
                content = re.sub(pattern, rf"\g<1>{pkg.latest_version}\4", content, flags=re.IGNORECASE)
                changes.append(f"{pkg.name}: {pkg.current_version} → {pkg.latest_version}")

        if content != original and not dry_run:
            path.write_text(content)
        return changes

    # ------------------------------------------------------------------
    # Utility: run `go mod tidy` / `npm install` / etc. after updates
    # ------------------------------------------------------------------

    def post_update_commands(self, ecosystems: set[str]) -> list[str]:
        """Return shell commands to run after updating manifests."""
        cmds = []
        if "go" in ecosystems:
            cmds.append("go mod tidy")
        if "npm" in ecosystems or "yarn" in ecosystems:
            if (self.root / "yarn.lock").exists():
                cmds.append("yarn install --frozen-lockfile")
            elif (self.root / "pnpm-lock.yaml").exists():
                cmds.append("pnpm install")
            else:
                cmds.append("npm install")
        if "cargo" in ecosystems:
            cmds.append("cargo update")
        if "pip" in ecosystems or "poetry" in ecosystems:
            if (self.root / "poetry.lock").exists():
                cmds.append("poetry update")
            else:
                cmds.append("pip install -r requirements.txt --upgrade")
        if "composer" in ecosystems:
            cmds.append("composer update")
        if "gemfile" in ecosystems:
            cmds.append("bundle update")
        return cmds

    def run_post_update(self, ecosystems: set[str]) -> list[tuple[str, bool, str]]:
        """Run post-update commands. Returns [(cmd, success, output)]."""
        results = []
        for cmd in self.post_update_commands(ecosystems):
            try:
                r = subprocess.run(
                    cmd, shell=True, cwd=self.root,
                    capture_output=True, text=True, timeout=120,
                )
                ok = r.returncode == 0
                output = (r.stdout + r.stderr).strip()
                results.append((cmd, ok, output))
                logger.info("Post-update [%s]: %s", "OK" if ok else "FAIL", cmd)
            except Exception as e:
                results.append((cmd, False, str(e)))
        return results
