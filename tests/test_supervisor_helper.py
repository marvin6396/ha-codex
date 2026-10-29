"""Exercise the actual shell dispatcher with a fake curl, never a live API."""
import json
import os
import shutil
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "home_assistant_codex_app/ha-codex-ha"
MOCK_CURL = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
a = sys.argv[1:]
method = a[a.index('--request') + 1]
url = a[-1]
body = sys.stdin.read()
record = {'method': method, 'url': url, 'body': json.loads(body) if body else None, 'argv': a}
with open(os.environ['REQUEST_LOG'], 'a') as f:
    f.write(json.dumps(record) + '\n')
if os.environ.get('MOCK_CURL_FAILURE'):
    print('secret-response-that-must-not-be-printed')
    sys.exit(22)
if os.environ.get('MOCK_API_FAILURE'):
    print(json.dumps({'result': 'error', 'message': 'secret-response-that-must-not-be-printed'}))
elif '/logs?' in url:
    print('Cloudflared: Registered tunnel connection')
elif url.endswith('/core/api/config/core/check_config'):
    print(json.dumps({'result': 'invalid' if os.environ.get('MOCK_BAD_CONFIG') else 'valid'}))
elif url.endswith('/options/validate'):
    print(json.dumps({'result': 'ok', 'data': {'valid': not bool(os.environ.get('MOCK_BAD_OPTIONS')), 'message': 'secret-validation-detail'}}))
elif url.endswith('/info'):
    print(json.dumps({'result': 'ok', 'data': {'slug': 'test_addon', 'options': {'password': 'retained-secret', 'external_hostname': 'old.example', 'nested': {'old': 1}}}}))
else:
    print(json.dumps({'result': 'ok', 'data': {'job_id': 'test-job'}}))
'''


class SupervisorHelperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.tmp = Path(self.temp.name)
        self.log = self.tmp / "requests.jsonl"
        installed = self.tmp / "installed"
        installed.mkdir()
        for name in ("ha-codex-ha", "ha-codex-supervisor"):
            target = installed / name
            shutil.copyfile(HELPER.parent / name, target)
            target.chmod(0o755)
        self.helper = installed / "ha-codex-ha"
        mock = self.tmp / "curl"
        mock.write_text(MOCK_CURL)
        mock.chmod(0o755)
        self.env = {
            "PATH": f"{self.tmp}:{os.environ['PATH']}",
            "LANG": "C.UTF-8",
            "SUPERVISOR_TOKEN": "test-only-token",
            "REQUEST_LOG": str(self.log),
            "HA_CODEX_SUPERVISOR_ACCESS": "read",
        }

    def run_helper(self, *args, mode=None, **env):
        child_env = dict(self.env, **env)
        if mode is not None:
            child_env["HA_CODEX_SUPERVISOR_ACCESS"] = mode
        return subprocess.run(["bash", str(self.helper), "supervisor", *args],
                              env=child_env, capture_output=True, text=True)

    def requests(self):
        return [json.loads(s) for s in self.log.read_text().splitlines()] if self.log.exists() else []

    def patch(self, text='{"external_hostname":"ha.example"}'):
        path = self.tmp / "options.json"
        path.write_text(text)
        return str(path)

    def test_help_without_permissions_or_token(self):
        r = self.run_helper("--help", mode="off", SUPERVISOR_TOKEN="")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("options-set", r.stdout)
        self.assertEqual(self.requests(), [])

    def test_off_and_unknown_modes_fail_closed(self):
        for mode in ("off", "", "admin", "true"):
            with self.subTest(mode=mode):
                self.assertEqual(self.run_helper("addons", mode=mode).returncode, 77)
        self.assertEqual(self.requests(), [])

    def test_missing_token(self):
        self.assertEqual(self.run_helper("addons", SUPERVISOR_TOKEN="").returncode, 78)
        self.assertEqual(self.requests(), [])

    def test_read_routes_and_auth(self):
        cases = [
            (("addons",), "/addons"), (("store",), "/store"),
            (("backups",), "/backups"), (("jobs",), "/jobs"),
            (("job", "job-123"), "/jobs/job-123"),
            (("backup-info", "abcd1234"), "/backups/abcd1234/info"),
            (("addon-info", "test_addon"), "/addons/test_addon/info"),
            (("addon-stats", "test_addon"), "/addons/test_addon/stats"),
            (("info", "system"), "/info"),
        ]
        cases += [(("info", x), f"/{x}/info") for x in
                  ("supervisor", "core", "os", "host", "network", "hardware", "resolution")]
        for args, path in cases:
            with self.subTest(args=args):
                r = self.run_helper(*args)
                self.assertEqual(r.returncode, 0, r.stderr)
                req = self.requests()[-1]
                self.assertEqual(req["url"], "http://supervisor" + path)
                self.assertEqual(req["method"], "GET")
                self.assertIn("Authorization: Bearer test-only-token", req["argv"])
                self.assertNotIn("test-only-token", r.stdout + r.stderr)

    def test_info_does_not_print_options(self):
        r = self.run_helper("addon-info", "test_addon")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("options", r.stdout)
        self.assertNotIn("retained-secret", r.stdout)

    def test_log_targets_and_line_limits(self):
        for target, path in (("core", "/core"), ("supervisor", "/supervisor"),
                             ("host", "/host"), ("test_addon", "/addons/test_addon")):
            for lines in ("2", "1000"):
                r = self.run_helper("logs", target, lines)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn("Registered tunnel", r.stdout)
                self.assertEqual(self.requests()[-1]["url"], f"http://supervisor{path}/logs?lines={lines}&no_colors")

    def test_invalid_inputs_never_reach_api(self):
        cases = [("addon-info", "../core"), ("addon-info", "self?query"),
                 ("addon-info", "a/b"), ("info", "docker"), ("addons", "extra"),
                 ("job", "--url"), ("host", "wipe"), ("api", "/os/datadisk/wipe"),
                 ("addon", "security", "test_addon"), ("update", "docker"),
                 ("update", "core", "../bad"), ("backup-create", "unknown", "x")]
        cases += [("logs", "core", x) for x in ("0", "1", "1001", "-1", "010", "2&verbose", "many")]
        for args in cases:
            with self.subTest(args=args):
                self.assertNotEqual(self.run_helper(*args, mode="manage").returncode, 0)
        self.assertEqual(self.requests(), [])

    def test_read_mode_blocks_every_management_family(self):
        cases = [("addon", action, "test_addon") for action in
                 ("start", "stop", "restart", "rebuild", "install", "update", "uninstall")]
        cases += [("options-set", "test_addon", "x"), ("options-validate", "test_addon", "x"),
                  ("store-reload",), ("update", "os"), ("update", "core"),
                  ("update", "supervisor"), ("backup-create", "full", "x"),
                  ("backup-restore", "full", "abc", "x"), ("backup-delete", "abc"),
                  ("host", "reboot"), ("host", "shutdown")]
        for args in cases:
            with self.subTest(args=args):
                self.assertEqual(self.run_helper(*args).returncode, 77)
        self.assertEqual(self.requests(), [])

    def test_manage_routes(self):
        for action in ("start", "stop", "restart", "rebuild", "uninstall", "install", "update"):
            r = self.run_helper("addon", action, "test_addon", mode="manage")
            self.assertEqual(r.returncode, 0, r.stderr)
            req = self.requests()[-1]
            base = "/store/addons" if action in ("install", "update") else "/addons"
            self.assertEqual(req["url"], f"http://supervisor{base}/test_addon/{action}")
            self.assertEqual(req["method"], "POST")
            self.assertEqual(req["body"], {"background": True} if action in ("install", "update") else {})
        for args, method, path in [(("store-reload",), "POST", "/store/reload"),
                                   (("backup-delete", "abc"), "DELETE", "/backups/abc"),
                                   (("host", "reboot"), "POST", "/host/reboot"),
                                   (("host", "shutdown"), "POST", "/host/shutdown")]:
            r = self.run_helper(*args, mode="manage")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual((self.requests()[-1]["method"], self.requests()[-1]["url"]),
                             (method, "http://supervisor" + path))

    def test_option_merge_preserves_secrets_and_validates_before_save(self):
        patch = self.patch('{"external_hostname":"ha.example","nested":{"new":2}}')
        r = self.run_helper("options-set", "test_addon", patch, mode="manage")
        self.assertEqual(r.returncode, 0, r.stderr)
        requests = self.requests()
        self.assertEqual([x["method"] for x in requests], ["GET", "POST", "POST"])
        self.assertTrue(requests[1]["url"].endswith("/options/validate"))
        expected = {"password": "retained-secret", "external_hostname": "ha.example", "nested": {"new": 2}}
        self.assertEqual(requests[1]["body"], expected)
        self.assertEqual(requests[2]["body"], {"options": expected})
        self.assertNotIn("retained-secret", r.stdout + r.stderr)
        for req in requests:
            self.assertNotIn("retained-secret", " ".join(req["argv"]))

    def test_invalid_options_are_not_saved_or_echoed(self):
        r = self.run_helper("options-set", "test_addon", self.patch(), mode="manage", MOCK_BAD_OPTIONS="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(len(self.requests()), 2)
        self.assertNotIn("secret-validation-detail", r.stdout + r.stderr)

    def test_validate_only_does_not_save(self):
        r = self.run_helper("options-validate", "test_addon", self.patch(), mode="manage")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.requests()), 2)

    def test_json_file_validation(self):
        for content in ("[]", "null", "1", "{} {}", "{broken", ""):
            with self.subTest(content=content):
                r = self.run_helper("options-set", "test_addon", self.patch(content), mode="manage")
                self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.requests(), [])

    def test_backup_jobs_and_password_not_in_argv(self):
        for action in ("backup-create", "backup-restore"):
            for kind in ("full", "partial"):
                path = self.patch('{"name":"test","password":"backup-secret","background":false}')
                args = [action, kind] + (["abc"] if action == "backup-restore" else []) + [path]
                r = self.run_helper(*args, mode="manage")
                self.assertEqual(r.returncode, 0, r.stderr)
                req = self.requests()[-1]
                expected_path = f"/backups/abc/restore/{kind}" if action == "backup-restore" else f"/backups/new/{kind}"
                self.assertEqual(req["url"], "http://supervisor" + expected_path)
                self.assertTrue(req["body"]["background"])
                self.assertNotIn("backup-secret", " ".join(req["argv"]))

    def test_update_version_and_core_check(self):
        for target in ("core", "os", "supervisor"):
            r = self.run_helper("update", target, "2026.10.4", mode="manage", HA_CODEX_HOME_ASSISTANT_CONTROL="true")
            self.assertEqual(r.returncode, 0, r.stderr)
            req = self.requests()[-1]
            self.assertEqual(req["url"], f"http://supervisor/{target}/update")
            self.assertEqual(req["body"], {"version": "2026.10.4"})
            if target == "core":
                self.assertTrue(self.requests()[-2]["url"].endswith("/core/api/config/core/check_config"))

    def test_bad_core_config_blocks_update(self):
        r = self.run_helper("update", "core", mode="manage", HA_CODEX_HOME_ASSISTANT_CONTROL="true", MOCK_BAD_CONFIG="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(len(self.requests()), 1)
        self.assertTrue(self.requests()[0]["url"].endswith("/check_config"))

    def test_api_failures_not_reported_as_success_or_echoed(self):
        for env in ("MOCK_CURL_FAILURE", "MOCK_API_FAILURE"):
            for args in (("addons",), ("addon-info", "test_addon"), ("addon", "start", "test_addon")):
                with self.subTest(env=env, args=args):
                    r = self.run_helper(*args, mode="manage", **{env: "1"})
                    self.assertNotEqual(r.returncode, 0)
                    self.assertNotIn("secret-response-that-must-not-be-printed", r.stdout + r.stderr)

    def run_core(self, *args, **env):
        return subprocess.run(["bash", str(self.helper), *args],
                              env=dict(self.env, **env), capture_output=True, text=True)

    def test_cloud_remote_fixed_service_routes(self):
        for action in ("connect", "disconnect"):
            with self.subTest(action=action):
                r = self.run_core("cloud-remote", action, HA_CODEX_HOME_ASSISTANT_CONTROL="true",
                                  HA_CODEX_SUPERVISOR_ACCESS="manage")
                self.assertEqual(r.returncode, 0, r.stderr)
                req = self.requests()[-1]
                self.assertEqual(req["method"], "POST")
                self.assertEqual(req["url"], f"http://supervisor/core/api/services/cloud/remote_{action}")

    def test_cloud_remote_needs_both_permission_settings(self):
        for control, mode in (("false", "manage"), ("true", "off"), ("true", "read")):
            with self.subTest(control=control, mode=mode):
                r = self.run_core("cloud-remote", "disconnect", HA_CODEX_HOME_ASSISTANT_CONTROL=control,
                                  HA_CODEX_SUPERVISOR_ACCESS=mode)
                self.assertEqual(r.returncode, 77)
        self.assertEqual(self.requests(), [])

    def test_cloud_remote_rejects_arbitrary_actions_and_extra_args(self):
        for args in ((), ("logout",), ("remote_disconnect",), ("disconnect", "extra"), ("../logout",)):
            with self.subTest(args=args):
                r = self.run_core("cloud-remote", *args, HA_CODEX_HOME_ASSISTANT_CONTROL="true",
                                  HA_CODEX_SUPERVISOR_ACCESS="manage")
                self.assertEqual(r.returncode, 64)
        self.assertEqual(self.requests(), [])

    def test_cloud_remote_failure_is_not_success(self):
        r = self.run_core("cloud-remote", "disconnect", HA_CODEX_HOME_ASSISTANT_CONTROL="true",
                          HA_CODEX_SUPERVISOR_ACCESS="manage", MOCK_CURL_FAILURE="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("Requested Home Assistant action", r.stdout)


if __name__ == "__main__":
    unittest.main()
