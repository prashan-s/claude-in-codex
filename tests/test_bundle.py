"""Release metadata stays consistent; the local bundle builder (when present) still passes.

The manifest checks need no extra files, so they run everywhere, including CI.
scripts/bundle.py is a git-ignored maintainer tool; its tests skip when it is absent.
"""

import importlib.util
import json
import re
import shutil
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "scripts" / "bundle.py"


def _png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()[:24]
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{path} is not a PNG"
    return struct.unpack(">II", data[16:24])


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))
        self.overlay = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.ui = self.manifest["extensions"]["com.openai"]["interface"]

    def test_versions_match_everywhere(self):
        project = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M)
        package = re.search(r'__version__ = "([^"]+)"', (ROOT / "src" / "cic" / "__init__.py").read_text(encoding="utf-8"))
        versions = {project.group(1), package.group(1), self.manifest["version"], self.overlay["version"]}
        self.assertEqual(len(versions), 1, f"version drift: {versions}")

    def test_listing_fields_fit_directory_limits(self):
        self.assertLessEqual(len(self.ui["displayName"]), 30)
        self.assertLessEqual(len(self.ui["shortDescription"]), 30)
        self.assertLessEqual(len(self.ui["longDescription"]), 4000)
        prompts = self.ui["defaultPrompt"]
        self.assertLessEqual(len(prompts), 3)
        self.assertTrue(all(0 < len(p) <= 128 and "\n" not in p for p in prompts))
        for key in ("skills", "mcpServers", "apps", "interface"):
            self.assertNotIn(key, self.manifest)
        self.assertEqual(self.overlay["interface"]["shortDescription"], self.ui["shortDescription"])

    def test_icons_are_square_pngs_of_the_right_size(self):
        for field, minimum in (("logo", 256), ("composerIcon", 48)):
            width, height = _png_size(ROOT / self.ui[field])
            self.assertEqual(width, height)
            self.assertGreaterEqual(width, minimum)


@unittest.skipUnless(BUNDLE.exists(), "local bundle script not present (it is git-ignored)")
class BundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("bundle", BUNDLE)
        cls.bundle = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.bundle)

    def test_package_passes_submission_checks(self):
        errors, _, _ = self.bundle.validate(ROOT)
        self.assertEqual(errors, [])

    def test_zip_has_one_plugin_directory_with_everything_referenced(self):
        _, _, manifest = self.bundle.validate(ROOT)
        with tempfile.TemporaryDirectory() as tmp:
            archive = self.bundle.build(ROOT, manifest, Path(tmp))
            with zipfile.ZipFile(archive) as bundle:
                names = bundle.namelist()
        self.assertTrue(all(name.startswith("claude-in-codex/") for name in names))
        for required in ("plugin.json", ".codex-plugin/plugin.json", "assets/logo.png", "assets/composer-icon.png",
                         "skills/claude-delegate/SKILL.md", "PRIVACY.md", "TERMS.md", "LICENSE"):
            self.assertIn(f"claude-in-codex/{required}", names)
        self.assertFalse(any(name.endswith((".app.json", ".html")) or "/src/" in name for name in names))

    def test_validator_catches_listing_mistakes(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "plugin"
            shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns(".git", ".venv", "dist", "__pycache__"))
            manifest = json.loads((copy / "plugin.json").read_text())
            manifest["extensions"]["com.openai"]["interface"]["shortDescription"] = "This subtitle is far too long to pass"
            manifest["apps"] = "./.app.json"
            (copy / "plugin.json").write_text(json.dumps(manifest))
            errors, _, _ = self.bundle.validate(copy)
        self.assertTrue(any("shortDescription" in e for e in errors))
        self.assertTrue(any("top-level 'apps'" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
