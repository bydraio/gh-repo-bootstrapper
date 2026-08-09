"""Regression tests for the live settings applied to generated repositories."""

import json
import subprocess
import unittest
from unittest.mock import patch

import bootstrap


class ConfigureRepoTests(unittest.TestCase):
    def test_workflow_permissions_are_read_only_without_pr_approvals(self):
        calls = []
        config = {
            "name": "example",
            "owner": "octocat",
            "repo_type": "simple",
            "private": False,
            "vercel": False,
            "cloudflare": False,
            "release_please_client_id": "",
            "release_please_app_key": "",
        }

        def run(command, **kwargs):
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0)

        with patch.object(bootstrap.subprocess, "run", side_effect=run):
            bootstrap.configure_repo(config)

        workflow_call = next(
            (command, kwargs)
            for command, kwargs in calls
            if command[2]
            == "repos/octocat/example/actions/permissions/workflow"
        )
        payload = json.loads(workflow_call[1]["input"].decode())
        self.assertEqual(
            payload,
            {
                "default_workflow_permissions": "read",
                "can_approve_pull_request_reviews": False,
            },
        )

    def _base_vercel_config(self):
        return {
            "name": "example",
            "owner": "octocat",
            "repo_type": "nextjs",
            "private": False,
            "vercel": True,
            "cloudflare": False,
            "vercel_org_id": "org_123",
            "vercel_project_id": "proj_123",
            "vercel_deploy_enabled": "false",
            "release_please_client_id": "",
            "release_please_app_key": "",
        }

    def test_vercel_deploy_enabled_var_is_initialized_when_absent(self):
        calls = []

        def run(command, **kwargs):
            calls.append((command, kwargs))
            if command[:3] == ["gh", "variable", "get"]:
                # Simulate the variable not existing yet (first configure) —
                # gh's actual not-found message, not just a bare failure.
                return subprocess.CompletedProcess(
                    command, 1, stderr=b"variable VERCEL_DEPLOY_ENABLED not found\n"
                )
            return subprocess.CompletedProcess(command, 0)

        with patch.object(bootstrap.subprocess, "run", side_effect=run):
            bootstrap.configure_repo(self._base_vercel_config())

        var_set_calls = {
            command[3]: kwargs["input"].decode()
            for command, kwargs in calls
            if command[:3] == ["gh", "variable", "set"]
        }
        self.assertEqual(var_set_calls.get("VERCEL_DEPLOY_ENABLED"), "false")

    def test_vercel_deploy_enabled_var_is_not_initialized_on_transient_lookup_failure(self):
        # A non-"not found" failure (auth expiry, rate limit, network blip)
        # from `gh variable get` must not be treated the same as absence —
        # doing so would risk the exact silent-revert this whole mechanism
        # exists to prevent, just triggered by a flaky lookup instead of an
        # unconditional write.
        def run(command, **kwargs):
            if command[:3] == ["gh", "variable", "get"]:
                return subprocess.CompletedProcess(
                    command, 1, stderr=b"HTTP 502: Bad Gateway\n"
                )
            return subprocess.CompletedProcess(command, 0)

        with patch.object(bootstrap.subprocess, "run", side_effect=run):
            with self.assertRaises(subprocess.CalledProcessError):
                bootstrap.configure_repo(self._base_vercel_config())

    def test_vercel_deploy_enabled_var_is_not_overwritten_when_already_set(self):
        # configure_repo() runs on every --configure-only re-run, not just
        # initial creation. If VERCEL_DEPLOY_ENABLED already exists, an
        # operator may have flipped it to "true" by hand — a re-run must not
        # silently revert that back to gather_config's always-"false" value.
        calls = []

        def run(command, **kwargs):
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0)

        with patch.object(bootstrap.subprocess, "run", side_effect=run):
            bootstrap.configure_repo(self._base_vercel_config())

        var_set_calls = {
            command[3]
            for command, _kwargs in calls
            if command[:3] == ["gh", "variable", "set"]
        }
        self.assertNotIn("VERCEL_DEPLOY_ENABLED", var_set_calls)
        # The other Vercel variables are still written on every re-run.
        self.assertIn("VERCEL_ORG_ID", var_set_calls)
        self.assertIn("VERCEL_PROJECT_ID", var_set_calls)

    def _base_cloudflare_config(self):
        return {
            "name": "example",
            "owner": "octocat",
            "repo_type": "nextjs",
            "private": False,
            "vercel": False,
            "cloudflare": True,
            "cloudflare_account_id": "acct_123",
            "cloudflare_deploy_enabled": "false",
            "cloudflare_api_token": "cf_token_123",
            "release_please_client_id": "",
            "release_please_app_key": "",
        }

    def test_cloudflare_vars_and_secret_are_set_when_enabled(self):
        calls = []

        def run(command, **kwargs):
            calls.append((command, kwargs))
            if command[:3] == ["gh", "variable", "get"]:
                # Simulate the variable not existing yet (first configure) —
                # gh's actual not-found message, not just a bare failure.
                return subprocess.CompletedProcess(
                    command, 1, stderr=b"variable CLOUDFLARE_DEPLOY_ENABLED not found\n"
                )
            return subprocess.CompletedProcess(command, 0)

        with patch.object(bootstrap.subprocess, "run", side_effect=run):
            bootstrap.configure_repo(self._base_cloudflare_config())

        var_set_calls = {
            command[3]: kwargs["input"].decode()
            for command, kwargs in calls
            if command[:3] == ["gh", "variable", "set"]
        }
        secret_set_calls = {
            command[3]: kwargs["input"].decode()
            for command, kwargs in calls
            if command[:3] == ["gh", "secret", "set"]
        }
        self.assertEqual(var_set_calls.get("CLOUDFLARE_ACCOUNT_ID"), "acct_123")
        self.assertEqual(var_set_calls.get("CLOUDFLARE_DEPLOY_ENABLED"), "false")
        self.assertEqual(secret_set_calls.get("CLOUDFLARE_API_TOKEN"), "cf_token_123")
        self.assertNotIn("VERCEL_ORG_ID", var_set_calls)

    def test_cloudflare_deploy_enabled_var_is_not_overwritten_when_already_set(self):
        calls = []

        def run(command, **kwargs):
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0)

        with patch.object(bootstrap.subprocess, "run", side_effect=run):
            bootstrap.configure_repo(self._base_cloudflare_config())

        var_set_calls = {
            command[3]
            for command, _kwargs in calls
            if command[:3] == ["gh", "variable", "set"]
        }
        self.assertNotIn("CLOUDFLARE_DEPLOY_ENABLED", var_set_calls)
        self.assertIn("CLOUDFLARE_ACCOUNT_ID", var_set_calls)

    def _selected_actions_payload(self, calls):
        call = next(
            (command, kwargs)
            for command, kwargs in calls
            if command[2] == "repos/octocat/example/actions/permissions/selected-actions"
        )
        return json.loads(call[1]["input"].decode())

    def test_wrangler_action_is_always_allowlisted(self):
        # Always applied regardless of cfg["cloudflare"] — this same PUT call
        # also runs on --configure-only, which re-derives cfg from
        # gather_config and could silently drop a conditional pattern on any
        # re-configure that doesn't pass --cloudflare again.
        calls = []
        config = {
            "name": "example",
            "owner": "octocat",
            "repo_type": "simple",
            "private": False,
            "vercel": False,
            "cloudflare": False,
            "release_please_client_id": "",
            "release_please_app_key": "",
        }

        def run(command, **kwargs):
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0)

        with patch.object(bootstrap.subprocess, "run", side_effect=run):
            bootstrap.configure_repo(config)

        payload = self._selected_actions_payload(calls)
        self.assertIn("cloudflare/wrangler-action@*", payload["patterns_allowed"])
        self.assertIn("amannn/action-semantic-pull-request@*", payload["patterns_allowed"])


if __name__ == "__main__":
    unittest.main()
