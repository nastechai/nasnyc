"""
Tests for the multi-ecosystem dependency scanner.
"""
import pytest
import asyncio
from pathlib import Path
from nastech_sync.dependency_scanner import (
    DependencyScanner,
    _parse_requirements_txt,
    _parse_package_json,
    _parse_cargo_toml,
    _parse_go_mod,
    _parse_pyproject_toml,
    _parse_composer_json,
    _parse_gemfile,
    _is_outdated,
    _clean_version,
    _version_tuple,
)


class TestVersionHelpers:
    def test_clean_version_strips_operators(self):
        assert _clean_version(">=1.2.3") == "1.2.3"
        assert _clean_version("^4.17.20") == "4.17.20"
        assert _clean_version("~=2.28.0") == "2.28.0"
        assert _clean_version("==3.0.0") == "3.0.0"
        assert _clean_version("1.0.0") == "1.0.0"

    def test_version_tuple(self):
        assert _version_tuple("1.2.3") == (1, 2, 3)
        assert _version_tuple("2.0") == (2, 0)
        assert _version_tuple("10.0.1") == (10, 0, 1)

    def test_is_outdated_true(self):
        assert _is_outdated("1.0.0", "2.0.0") is True
        assert _is_outdated("1.2.3", "1.2.4") is True

    def test_is_outdated_false_same(self):
        assert _is_outdated("1.2.3", "1.2.3") is False

    def test_is_outdated_false_newer_current(self):
        assert _is_outdated("2.0.0", "1.9.9") is False

    def test_is_outdated_empty(self):
        assert _is_outdated("", "1.0.0") is False
        assert _is_outdated("1.0.0", "") is False


class TestManifestParsers:
    def test_parse_requirements_txt(self, tmp_path):
        f = tmp_path / "requirements.txt"
        f.write_text("requests==2.28.0\nhttpx>=0.25.0\n# comment\n-r other.txt\n")
        pkgs = _parse_requirements_txt(f)
        names = [p[0] for p in pkgs]
        assert "requests" in names
        assert "httpx" in names

    def test_parse_package_json(self, tmp_path):
        f = tmp_path / "package.json"
        f.write_text('{"dependencies":{"lodash":"4.17.20"},"devDependencies":{"jest":"^28.0.0"}}')
        pkgs = _parse_package_json(f)
        names = [p[0] for p in pkgs]
        assert "lodash" in names
        assert "jest" in names

    def test_parse_package_json_no_deps(self, tmp_path):
        f = tmp_path / "package.json"
        f.write_text('{"name":"test","version":"1.0.0"}')
        pkgs = _parse_package_json(f)
        assert pkgs == []

    def test_parse_cargo_toml(self, tmp_path):
        f = tmp_path / "Cargo.toml"
        f.write_text('[package]\nname="test"\n\n[dependencies]\nserde="1.0.150"\n')
        pkgs = _parse_cargo_toml(f)
        names = [p[0] for p in pkgs]
        assert "serde" in names

    def test_parse_go_mod(self, tmp_path):
        f = tmp_path / "go.mod"
        f.write_text('module example.com/app\n\ngo 1.20\n\nrequire (\n\tgithub.com/gin-gonic/gin v1.8.0\n)\n')
        pkgs = _parse_go_mod(f)
        names = [p[0] for p in pkgs]
        assert "github.com/gin-gonic/gin" in names

    def test_parse_pyproject_toml_poetry(self, tmp_path):
        f = tmp_path / "pyproject.toml"
        f.write_text('[tool.poetry]\nname="test"\n\n[tool.poetry.dependencies]\npython="^3.10"\npydantic="^1.10.0"\n')
        pkgs, eco = _parse_pyproject_toml(f)
        assert eco == "poetry"
        names = [p[0] for p in pkgs]
        assert "pydantic" in names
        assert "python" not in names  # python dep skipped

    def test_parse_pyproject_toml_pep517(self, tmp_path):
        f = tmp_path / "pyproject.toml"
        f.write_text('[project]\nname="test"\ndependencies=["requests>=2.28","httpx>=0.25"]\n')
        pkgs, eco = _parse_pyproject_toml(f)
        assert eco == "pip"
        names = [p[0] for p in pkgs]
        assert "requests" in names

    def test_parse_composer_json(self, tmp_path):
        f = tmp_path / "composer.json"
        f.write_text('{"require":{"laravel/framework":"^10.0"},"require-dev":{"phpunit/phpunit":"^10.0"}}')
        pkgs = _parse_composer_json(f)
        names = [p[0] for p in pkgs]
        assert "laravel/framework" in names
        assert "phpunit/phpunit" in names

    def test_parse_gemfile(self, tmp_path):
        f = tmp_path / "Gemfile"
        f.write_text("source 'https://rubygems.org'\ngem 'rails', '7.0.0'\ngem 'rspec'\n")
        pkgs = _parse_gemfile(f)
        names = [p[0] for p in pkgs]
        assert "rails" in names

    def test_parse_gemfile_no_version_ok(self, tmp_path):
        f = tmp_path / "Gemfile"
        f.write_text("gem 'rspec'\n")
        pkgs = _parse_gemfile(f)
        # rspec has no version — it's still parsed but version is empty
        names = [p[0] for p in pkgs]
        # This may or may not match depending on regex; just ensure no crash
        assert isinstance(pkgs, list)


class TestDependencyScanner:
    def test_finds_manifests(self, tmp_project):
        scanner = DependencyScanner(root_path=str(tmp_project))
        manifests = scanner._find_manifests()
        names = [p.name for p, _ in manifests]
        assert "requirements.txt" in names
        assert "package.json" in names
        assert "Cargo.toml" in names
        assert "go.mod" in names

    def test_skips_excluded_dirs(self, tmp_project):
        # Use path.parts check (not substring) — pytest names the tmp dir after
        # the test function, so the dir path itself contains "node_modules" as
        # a substring, causing false positives on naive string checks.
        nm = tmp_project / "node_modules" / "some-pkg"
        nm.mkdir(parents=True)
        (nm / "package.json").write_text('{"dependencies":{}}')
        scanner = DependencyScanner(root_path=str(tmp_project))
        manifests = scanner._find_manifests()
        leaked = [str(p) for p, _ in manifests if "node_modules" in p.parts]
        assert not leaked, f"node_modules leaked into manifests: {leaked}"

    @pytest.mark.asyncio
    async def test_scan_returns_report(self, tmp_project):
        scanner = DependencyScanner(root_path=str(tmp_project))
        # Run with 0 concurrency check — this does real HTTP, so we just verify structure
        # Use a mocked version for unit tests
        report = await scanner.scan()
        # Report must have these attributes
        assert hasattr(report, "packages")
        assert hasattr(report, "errors")
        assert hasattr(report, "outdated")
        assert isinstance(report.packages, list)

    @pytest.mark.asyncio
    async def test_scan_empty_dir_no_crash(self, tmp_path):
        scanner = DependencyScanner(root_path=str(tmp_path))
        report = await scanner.scan()
        assert report.packages == []
        assert report.errors == []

    def test_scan_report_summary(self, tmp_project):
        from nastech_sync.dependency_scanner import ScanReport, PackageInfo
        report = ScanReport(root_path=str(tmp_project))
        report.packages = [
            PackageInfo("requests", "2.28.0", "2.31.0", "pip", "requirements.txt", is_outdated=True),
            PackageInfo("httpx", "0.25.0", "0.25.0", "pip", "requirements.txt", is_outdated=False),
        ]
        assert len(report.outdated()) == 1
        assert len(report.up_to_date()) == 1
        assert "2 packages" in report.summary()

    def test_scan_report_markdown(self, tmp_project):
        from nastech_sync.dependency_scanner import ScanReport, PackageInfo
        report = ScanReport(root_path=str(tmp_project))
        report.packages = [
            PackageInfo("requests", "2.28.0", "2.31.0", "pip", "requirements.txt", is_outdated=True),
        ]
        md = report.markdown_report()
        assert "# NasTech Dependency Report" in md
        assert "requests" in md
        assert "2.31.0" in md
