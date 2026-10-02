from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections.abc import Iterable, Mapping, Sequence


REQUIRED_PR_WORKFLOWS = ("Frontend CI", "Repository hygiene", "Repo Launch Doctor")
REQUIRED_DISPATCH_WORKFLOWS = (
    ("Frontend CI", "ci.yml"),
    ("Repository hygiene", "repository-hygiene.yml"),
    ("Repo Launch Doctor", "repo-launch-doctor.yml"),
)
RETRY_EXIT_CODE = 75


def select_latest_workflow_run_ids(runs: Iterable[Mapping[str, object]]) -> dict[str, int]:
    runs = tuple(runs)
    selected: dict[str, int] = {}
    for workflow_name in REQUIRED_PR_WORKFLOWS:
        matching = [
            int(run["databaseId"])
            for run in runs
            if run.get("workflowName") == workflow_name and run.get("databaseId") is not None
        ]
        if matching:
            selected[workflow_name] = max(matching)
    return selected


def _run(args: Sequence[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(args), flush=True)
    return subprocess.run(args, check=check, text=True, capture_output=True)


def _stdout(args: Sequence[str]) -> str:
    return _run(args).stdout.strip()


def _json(args: Sequence[str]) -> object:
    output = _stdout(args)
    return json.loads(output or "null")


def _wait_for_value(label: str, getter, *, attempts: int, interval_sec: float):
    for attempt in range(1, attempts + 1):
        value = getter()
        if value:
            return value
        print(f"waiting for {label} ({attempt}/{attempts})", flush=True)
        time.sleep(interval_sec)
    raise RuntimeError(f"timed out waiting for {label}")


def _ensure_pull_request(repo: str, branch: str, base: str, title: str, body: str) -> int:
    result = _json(
        [
            "gh",
            "pr",
            "list",
            "--repo",
            repo,
            "--head",
            branch,
            "--base",
            base,
            "--state",
            "open",
            "--limit",
            "1",
            "--json",
            "number",
        ]
    )
    if isinstance(result, list) and result:
        return int(result[0]["number"])

    # GitHub CLI can occasionally return an empty exact --head query inside
    # Actions even when the PR already exists. Fall back to an open-PR scan
    # and match the immutable head ref name before attempting creation.
    fallback = _json(
        [
            "gh",
            "pr",
            "list",
            "--repo",
            repo,
            "--base",
            base,
            "--state",
            "open",
            "--limit",
            "100",
            "--json",
            "number,headRefName",
        ]
    )
    if isinstance(fallback, list):
        for item in fallback:
            if isinstance(item, Mapping) and str(item.get("headRefName") or "") == branch:
                return int(item["number"])

    url = _stdout(
        [
            "gh",
            "pr",
            "create",
            "--repo",
            repo,
            "--base",
            base,
            "--head",
            branch,
            "--title",
            title,
            "--body",
            body,
        ]
    )
    return int(url.rstrip("/").rsplit("/", 1)[-1])


def _wait_for_readiness(repo: str, branch: str, head_sha: str, attempts: int, interval_sec: float) -> None:
    _run(["gh", "workflow", "run", "repo-launch-doctor.yml", "--repo", repo, "--ref", branch])

    def find_run_id() -> int | None:
        runs = _json(
            [
                "gh",
                "run",
                "list",
                "--repo",
                repo,
                "--workflow",
                "repo-launch-doctor.yml",
                "--branch",
                branch,
                "--event",
                "workflow_dispatch",
                "--commit",
                head_sha,
                "--limit",
                "1",
                "--json",
                "databaseId",
            ]
        )
        if isinstance(runs, list) and runs:
            return int(runs[0]["databaseId"])
        return None

    run_id = _wait_for_value(
        f"public-readiness workflow for {head_sha}",
        find_run_id,
        attempts=attempts,
        interval_sec=interval_sec,
    )
    _run(["gh", "run", "watch", str(run_id), "--repo", repo, "--compact", "--exit-status"])
    checked_sha = _stdout(["gh", "run", "view", str(run_id), "--repo", repo, "--json", "headSha", "--jq", ".headSha"])
    if checked_sha != head_sha:
        raise RuntimeError(f"public-readiness checked {checked_sha} instead of {head_sha}")


def _list_dispatched_run_ids(
    repo: str, branch: str, head_sha: str, workflow_file: str, workflow_name: str
) -> set[int]:
    runs = _json(
        [
            "gh",
            "run",
            "list",
            "--repo",
            repo,
            "--workflow",
            workflow_file,
            "--branch",
            branch,
            "--event",
            "workflow_dispatch",
            "--commit",
            head_sha,
            "--limit",
            "20",
            "--json",
            "databaseId,workflowName",
        ]
    )
    if not isinstance(runs, list):
        return set()
    # The GitHub API's `--workflow` filter can transiently return runs from a
    # different workflow that was dispatched around the same time. Re-check
    # workflowName here so a same-timestamp Frontend CI run is never mistaken
    # for the Repo Launch Doctor run (or vice versa).
    return {
        int(run["databaseId"])
        for run in runs
        if isinstance(run, Mapping)
        and run.get("databaseId") is not None
        and run.get("workflowName") == workflow_name
    }


def _wait_for_dispatched_workflows(
    repo: str,
    branch: str,
    head_sha: str,
    attempts: int,
    interval_sec: float,
) -> None:
    run_ids: dict[str, int] = {}
    for workflow_name, workflow_file in REQUIRED_DISPATCH_WORKFLOWS:
        existing_ids = _list_dispatched_run_ids(repo, branch, head_sha, workflow_file, workflow_name)
        _run(["gh", "workflow", "run", workflow_file, "--repo", repo, "--ref", branch])

        def find_new_run_id() -> int | None:
            new_ids = (
                _list_dispatched_run_ids(repo, branch, head_sha, workflow_file, workflow_name) - existing_ids
            )
            return max(new_ids) if new_ids else None

        run_ids[workflow_name] = _wait_for_value(
            f"dispatched {workflow_name} workflow for {head_sha}",
            find_new_run_id,
            attempts=attempts,
            interval_sec=interval_sec,
        )

    for workflow_name, _workflow_file in REQUIRED_DISPATCH_WORKFLOWS:
        run_id = run_ids[workflow_name]
        _run(["gh", "run", "watch", str(run_id), "--repo", repo, "--compact", "--exit-status"])
        checked_sha = _stdout(
            ["gh", "run", "view", str(run_id), "--repo", repo, "--json", "headSha", "--jq", ".headSha"]
        )
        if checked_sha != head_sha:
            raise RuntimeError(f"{workflow_name} checked {checked_sha} instead of {head_sha}")


def _wait_for_required_pr_workflows(repo: str, head_sha: str, attempts: int, interval_sec: float) -> None:
    def find_runs() -> dict[str, int] | None:
        runs = _json(
            [
                "gh",
                "run",
                "list",
                "--repo",
                repo,
                "--commit",
                head_sha,
                "--event",
                "pull_request",
                "--limit",
                "50",
                "--json",
                "databaseId,workflowName,status,conclusion",
            ]
        )
        if not isinstance(runs, list):
            return None
        selected = select_latest_workflow_run_ids(run for run in runs if isinstance(run, Mapping))
        return selected if len(selected) == len(REQUIRED_PR_WORKFLOWS) else None

    run_ids = _wait_for_value(
        f"required pull-request workflows for {head_sha}",
        find_runs,
        attempts=attempts,
        interval_sec=interval_sec,
    )
    for workflow_name in REQUIRED_PR_WORKFLOWS:
        run_id = run_ids[workflow_name]
        conclusion = _stdout(
            [
                "gh",
                "run",
                "view",
                str(run_id),
                "--repo",
                repo,
                "--json",
                "conclusion",
                "--jq",
                '.conclusion // ""',
            ]
        )
        if conclusion == "action_required":
            _run(["gh", "api", "--method", "POST", f"repos/{repo}/actions/runs/{run_id}/approve"])

    for workflow_name in REQUIRED_PR_WORKFLOWS:
        _run(
            [
                "gh",
                "run",
                "watch",
                str(run_ids[workflow_name]),
                "--repo",
                repo,
                "--compact",
                "--exit-status",
            ]
        )


def _remote_branch_sha(branch: str) -> str:
    output = _stdout(["git", "ls-remote", "origin", f"refs/heads/{branch}"])
    return output.split()[0] if output else ""


def publish_checked_pull_request(args: argparse.Namespace) -> int:
    repo = args.repo or os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not repo:
        raise RuntimeError("repository is required through --repo or GITHUB_REPOSITORY")

    pr_number = _ensure_pull_request(repo, args.branch, args.base, args.title, args.body)
    if args.workflow_mode == "trusted-dispatch":
        _wait_for_dispatched_workflows(
            repo,
            args.branch,
            args.head_sha,
            args.wait_attempts,
            args.poll_interval_sec,
        )
    else:
        _wait_for_readiness(repo, args.branch, args.head_sha, args.wait_attempts, args.poll_interval_sec)
        _wait_for_required_pr_workflows(repo, args.head_sha, args.wait_attempts, args.poll_interval_sec)

    current_pr_sha = _stdout(
        ["gh", "pr", "view", str(pr_number), "--repo", repo, "--json", "headRefOid", "--jq", ".headRefOid"]
    )
    if current_pr_sha != args.head_sha:
        print(f"pull request head moved from {args.head_sha} to {current_pr_sha}", file=sys.stderr)
        return RETRY_EXIT_CODE

    if args.expected_base_sha:
        current_base_sha = _remote_branch_sha(args.base)
        if current_base_sha != args.expected_base_sha:
            print(f"{args.base} advanced from {args.expected_base_sha} to {current_base_sha}", file=sys.stderr)
            return RETRY_EXIT_CODE

    for attempt in range(1, args.merge_attempts + 1):
        result = _run(
            [
                "gh",
                "pr",
                "merge",
                str(pr_number),
                "--repo",
                repo,
                "--squash",
                "--delete-branch",
                "--match-head-commit",
                args.head_sha,
            ],
            check=False,
        )
        if result.returncode == 0:
            print(f"merged pull request #{pr_number}", flush=True)
            return 0
        print(f"merge attempt {attempt}/{args.merge_attempts} was not accepted", file=sys.stderr, flush=True)
        time.sleep(args.merge_interval_sec)

    return RETRY_EXIT_CODE


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create, verify, and squash-merge a protected pull request.")
    parser.add_argument("--repo", default="")
    parser.add_argument("--branch", required=True)
    parser.add_argument("--base", default="main")
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--body", required=True)
    parser.add_argument("--expected-base-sha", default="")
    parser.add_argument(
        "--workflow-mode",
        choices=("pull-request", "trusted-dispatch"),
        default="pull-request",
    )
    parser.add_argument("--wait-attempts", type=int, default=60)
    parser.add_argument("--poll-interval-sec", type=float, default=5.0)
    parser.add_argument("--merge-attempts", type=int, default=12)
    parser.add_argument("--merge-interval-sec", type=float, default=10.0)
    return parser


def main() -> int:
    try:
        return publish_checked_pull_request(build_parser().parse_args())
    except (RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError, ValueError) as exc:
        print(f"checked pull request failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
