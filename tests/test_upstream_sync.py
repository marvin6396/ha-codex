"""Merge real local Git histories; no GitHub account or API is involved."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / ".github/scripts/prepare-upstream-sync.py"
spec = importlib.util.spec_from_file_location("upstream_sync", SCRIPT)
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)
CONFIG = sync.CONFIG
BASE = '''name: HA Codex
version: "1.2.35"
url: https://github.com/ambient-home-systems/ha-codex
homeassistant_api: true
options:
  model: default
schema:
  model: str
'''


class UpstreamSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "fork"
        self.repo.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@localhost")
        self.git("config", "commit.gpgsign", "false")
        path = self.repo / CONFIG
        path.parent.mkdir()
        path.write_text(BASE)
        (self.repo / "unrelated.txt").write_text("base\n")
        self.commit("Base upstream release")
        self.git("tag", "v1.2.35")
        self.git("branch", "upstream-work")
        fork = BASE.replace('name: HA Codex', 'name: HA Codex Supervisor')
        fork = fork.replace('version: "1.2.35"', 'version: "1.2.35-supervisor.1"')
        fork = fork.replace("ambient-home-systems/ha-codex", "marvin6396/ha-codex")
        fork = fork.replace("homeassistant_api: true", "homeassistant_api: true\nhassio_api: true\nhassio_role: manager")
        fork += "  supervisor_access: list(off|read|manage)\n"
        path.write_text(fork)
        (self.repo / "FORK-CHANGELOG.md").write_text("Initial fork\n")
        (self.repo / "fork-only.txt").write_text("keep this\n")
        self.commit("Add Supervisor extension")
        self.fork_head = self.git("rev-parse", "HEAD").strip()
        upstream = self.root / "upstream.git"
        subprocess.run(["git", "init", "--bare", str(upstream)], check=True, capture_output=True)
        self.git("remote", "add", "upstream", str(upstream))
        self.git("push", "upstream", "refs/tags/v1.2.35")

    def git(self, *args):
        return sync.git(self.repo, *args).stdout

    def commit(self, message):
        self.git("add", ".")
        self.git("commit", "-m", message)

    def upstream_release(self, *, conflict=False, version="1.2.36", mismatched=False):
        self.git("switch", "upstream-work")
        config = BASE.replace('version: "1.2.35"', f'version: "{version}"')
        config += "  new_upstream_option: bool\n"
        if conflict:
            config = config.replace("name: HA Codex", "name: Upstream renamed")
        (self.repo / CONFIG).write_text(config)
        (self.repo / "upstream-only.txt").write_text("new upstream feature\n")
        self.commit("New upstream release")
        self.upstream_head = self.git("rev-parse", "HEAD").strip()
        tag = "v9.9.9" if mismatched else f"v{version}"
        self.git("tag", tag)
        self.git("push", "upstream", f"refs/tags/{tag}")
        self.git("switch", "main")
        return tag

    def test_already_integrated_release_is_noop(self):
        self.assertEqual(sync.prepare(self.repo, "v1.2.35"), {"update": "false"})
        self.assertEqual(self.git("branch", "--show-current").strip(), "main")
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), self.fork_head)

    def test_version_conflict_merges_both_sides_without_changing_main(self):
        tag = self.upstream_release()
        result = sync.prepare(self.repo, tag)
        self.assertEqual(result["update"], "true")
        self.assertEqual(result["branch"], "upstream-sync/v1.2.36")
        self.assertEqual(result["version"], "1.2.36-supervisor.1")
        config = (self.repo / CONFIG).read_text()
        for expected in ("HA Codex Supervisor", "hassio_role: manager", "marvin6396/ha-codex",
                         "supervisor_access: list(off|read|manage)", "new_upstream_option: bool",
                         'version: "1.2.36-supervisor.1"'):
            self.assertIn(expected, config)
        self.assertNotIn("SYNC_VERSION_PLACEHOLDER", config)
        self.assertTrue((self.repo / "fork-only.txt").exists())
        self.assertTrue((self.repo / "upstream-only.txt").exists())
        self.assertEqual(self.git("rev-parse", "main").strip(), self.fork_head)
        self.assertEqual(len(self.git("rev-list", "--parents", "-n", "1", "HEAD").split()), 3)
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertEqual(sync.git(self.repo, "merge-base", "--is-ancestor", self.upstream_head, "HEAD").returncode, 0)

    def test_nonversion_conflict_aborts_and_preserves_main(self):
        tag = self.upstream_release(conflict=True)
        before = (self.repo / CONFIG).read_text()
        with self.assertRaisesRegex(RuntimeError, "beyond its version"):
            sync.prepare(self.repo, tag)
        self.assertEqual(self.git("branch", "--show-current").strip(), "main")
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), self.fork_head)
        self.assertEqual((self.repo / CONFIG).read_text(), before)
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_other_file_conflict_aborts(self):
        self.git("switch", "upstream-work")
        (self.repo / "unrelated.txt").write_text("upstream change\n")
        self.commit("Upstream conflicting file")
        self.git("switch", "main")
        (self.repo / "unrelated.txt").write_text("fork change\n")
        self.commit("Fork conflicting file")
        head = self.git("rev-parse", "HEAD").strip()
        tag = self.upstream_release()
        with self.assertRaisesRegex(RuntimeError, "Manual merge required"):
            sync.prepare(self.repo, tag)
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), head)
        self.assertEqual((self.repo / "unrelated.txt").read_text(), "fork change\n")
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_dirty_worktree_is_not_touched(self):
        (self.repo / "private-local.txt").write_text("uncommitted\n")
        with self.assertRaisesRegex(RuntimeError, "dirty"):
            sync.prepare(self.repo, "v1.2.36")
        self.assertEqual((self.repo / "private-local.txt").read_text(), "uncommitted\n")

    def test_tag_validation(self):
        for tag in ("main", "v1.2.36;touch nope", "v1.2.3-beta", "../v1.2.3"):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                sync.prepare(self.repo, tag)

    def test_release_tag_and_manifest_must_match(self):
        tag = self.upstream_release(mismatched=True)
        with self.assertRaisesRegex(RuntimeError, "does not match"):
            sync.prepare(self.repo, tag)
        self.assertEqual(self.git("branch", "--show-current").strip(), "main")


if __name__ == "__main__":
    unittest.main()
