import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".github" / "scripts"))

import checked_pr_merge  # noqa: E402
from checked_pr_merge import (  # noqa: E402
    REQUIRED_DISPATCH_WORKFLOWS,
    REQUIRED_PR_WORKFLOWS,
    build_parser,
    select_latest_workflow_run_ids,
)


class CheckedPullRequestMergeTests(unittest.TestCase):
    def test_selects_latest_run_for_each_required_workflow(self):
        runs = [
            {"databaseId": 10, "workflowName": "Frontend CI"},
            {"databaseId": 11, "workflowName": "Repository hygiene"},
            {"databaseId": 12, "workflowName": "Frontend CI"},
            {"databaseId": 13, "workflowName": "Repo Launch Doctor"},
            {"databaseId": 14, "workflowName": "Unrelated"},
        ]

        selected = select_latest_workflow_run_ids(runs)

        self.assertEqual(
            selected,
            {
                "Frontend CI": 12,
                "Repository hygiene": 11,
                "Repo Launch Doctor": 13,
            },
        )
        self.assertEqual(tuple(selected), REQUIRED_PR_WORKFLOWS)

    def test_selects_all_workflows_from_one_shot_iterable(self):
        runs = iter(
            [
                {"databaseId": 20, "workflowName": "Repository hygiene"},
                {"databaseId": 21, "workflowName": "Repo Launch Doctor"},
                {"databaseId": 22, "workflowName": "Frontend CI"},
            ]
        )

        selected = select_latest_workflow_run_ids(runs)

        self.assertEqual(
            selected,
            {
                "Frontend CI": 22,
                "Repository hygiene": 20,
                "Repo Launch Doctor": 21,
            },
        )

    def test_trusted_dispatch_mode_has_explicit_workflow_files(self):
        self.assertEqual(
            REQUIRED_DISPATCH_WORKFLOWS,
            (
                ("Frontend CI", "ci.yml"),
                ("Repository hygiene", "repository-hygiene.yml"),
                ("Repo Launch Doctor", "repo-launch-doctor.yml"),
            ),
        )
        parsed = build_parser().parse_args(
            [
                "--branch",
                "automation/update-vods",
                "--head-sha",
                "abc",
                "--title",
                "title",
                "--body",
                "body",
                "--workflow-mode",
                "trusted-dispatch",
            ]
        )
        self.assertEqual(parsed.workflow_mode, "trusted-dispatch")

    def test_existing_pr_fallback_matches_head_ref_without_recreating(self):
        with mock.patch.object(
            checked_pr_merge,
            "_json",
            side_effect=[[], [{"number": 149, "headRefName": "release/youtube-captions-feedback"}]],
        ), mock.patch.object(checked_pr_merge, "_stdout") as create:
            number = checked_pr_merge._ensure_pull_request(
                "owner/repo",
                "release/youtube-captions-feedback",
                "main",
                "title",
                "body",
            )

        self.assertEqual(number, 149)
        create.assert_not_called()

    def test_trusted_automation_workflows_are_dispatchable_without_live_checks(self):
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        hygiene = (ROOT / ".github" / "workflows" / "repository-hygiene.yml").read_text(encoding="utf-8")
        update = (ROOT / ".github" / "workflows" / "update-vods.yml").read_text(encoding="utf-8")
        youtube = (ROOT / ".github" / "workflows" / "process-youtube-material.yml").read_text(encoding="utf-8")

        self.assertIn("run_live:", ci)
        self.assertIn("inputs.run_live == true", ci)
        self.assertIn("workflow_dispatch:", hygiene)
        self.assertIn("--workflow-mode trusted-dispatch", update)
        self.assertIn("--workflow-mode trusted-dispatch", youtube)

    def test_list_dispatched_run_ids_ignores_other_workflow_run_ids(self):
        # `gh run list --workflow <file>` can transiently include a run from a
        # different workflow that was dispatched around the same time (as
        # happened for automation/update-vods PR #114, where the Repo Launch
        # Doctor lookup returned a Frontend CI run id). The workflowName must
        # still be checked so that run is never mistaken for the real one.
        sample_runs = [
            {"databaseId": 33817504551, "workflowName": "Frontend CI"},
            {"databaseId": 33817523382, "workflowName": "Repo Launch Doctor"},
        ]
        with mock.patch.object(checked_pr_merge, "_json", return_value=sample_runs):
            result = checked_pr_merge._list_dispatched_run_ids(
                "owner/repo",
                "automation/update-vods",
                "f818cd5",
                "repo-launch-doctor.yml",
                "Repo Launch Doctor",
            )

        self.assertEqual(result, {33817523382})

    def test_release_and_update_workflows_delegate_checked_merge(self):
        script_reference = "python .github/scripts/checked_pr_merge.py"
        release = (ROOT / ".github" / "workflows" / "publish-release.yml").read_text(encoding="utf-8")
        update = (ROOT / ".github" / "workflows" / "update-vods.yml").read_text(encoding="utf-8")

        self.assertIn(script_reference, release)
        self.assertIn("--workflow-mode trusted-dispatch", release)
        self.assertIn(script_reference, update)
        for workflow in (release, update):
            self.assertNotIn('required_pr_workflows=("Frontend CI"', workflow)
            self.assertNotIn("gh run watch", workflow)


if __name__ == "__main__":
    unittest.main()
