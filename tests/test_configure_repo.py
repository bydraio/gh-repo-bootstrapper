"""Regression tests for provider-free generated repository configuration."""

import json
import subprocess
import sys
import unittest
from unittest.mock import patch

import bootstrap


class ConfigureRepoTests(unittest.TestCase):
    def _config(self):
        return {
            "name": "example",
            "owner": "octocat",
            "repo_type": "nextjs",
            "private": False,
            "postgres": False,
            "release_please_client_id": "client-id",
            "release_please_app_key": "private-key",
        }

    def test_configure_repo_writes_only_release_please_credentials(self):
        calls = []

        def run(command, **kwargs):
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0)

        with patch.object(bootstrap.subprocess, "run", side_effect=run):
            bootstrap.configure_repo(self._config())

        variable_names = [
            command[3] for command, _kwargs in calls if command[:3] == ["gh", "variable", "set"]
        ]
        secret_names = [
            command[3] for command, _kwargs in calls if command[:3] == ["gh", "secret", "set"]
        ]
        self.assertEqual(variable_names, ["RELEASE_PLEASE_CLIENT_ID"])
        self.assertEqual(secret_names, ["RELEASE_PLEASE_APP_KEY"])

    def test_selected_actions_excludes_provider_actions(self):
        calls = []

        def run(command, **kwargs):
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0)

        with patch.object(bootstrap.subprocess, "run", side_effect=run):
            bootstrap.configure_repo(self._config())

        command, kwargs = next(
            (command, kwargs)
            for command, kwargs in calls
            if command[2] == "repos/octocat/example/actions/permissions/selected-actions"
        )
        payload = json.loads(kwargs["input"].decode())
        self.assertEqual(payload["patterns_allowed"], ["amannn/action-semantic-pull-request@*"])

    def test_nextjs_render_is_provider_free_and_preserves_postgres(self):
        files = bootstrap.generate_files({**self._config(), "name": "sample", "postgres": True})
        rendered = "\n".join(
            content for path, content in files.items() if path != ".gitignore"
        ).lower()
        self.assertNotIn("vercel", rendered)
        self.assertNotIn("cloudflare", rendered)
        self.assertNotIn("wrangler", rendered)
        self.assertNotIn("wrangler.jsonc", files)
        self.assertIn(".vercel/", files[".gitignore"])
        self.assertIn(".wrangler/", files[".gitignore"])
        self.assertIn("postgres", files[".github/workflows/test.yml"].lower())
        self.assertNotIn("deployments: write", files[".github/workflows/release-please.yml"])

    def test_gather_config_has_no_provider_keys(self):
        with patch.object(
            sys,
            "argv",
            [
                "bootstrap.py",
                "--name",
                "sample",
                "--type",
                "nextjs",
                "--org",
                "octocat",
                "--non-interactive",
                "--dry-run",
            ],
        ):
            config = bootstrap.gather_config(bootstrap.parse_args())

        self.assertFalse({"vercel", "cloudflare", "vercel_token", "cloudflare_api_token"} & config.keys())

    def test_retired_provider_flags_are_rejected(self):
        for flag in ("--vercel", "--no-vercel", "--cloudflare", "--no-cloudflare"):
            with self.subTest(flag=flag), patch.object(sys, "argv", ["bootstrap.py", flag]):
                with self.assertRaises(SystemExit) as error:
                    bootstrap.parse_args()
            self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
