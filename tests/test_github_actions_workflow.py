"""Structural tests for .github/workflows/weekly_climate_job_radar.yml.

Does not call GitHub, does not run the workflow — parses the YAML and
asserts on its structure (schedule, workflow_dispatch, concurrency, step
ordering) so a future edit can't silently drop a safety property.
"""

from __future__ import annotations

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = PROJECT_ROOT / ".github" / "workflows" / "weekly_climate_job_radar.yml"


def _load_workflow() -> dict:
    with WORKFLOW_PATH.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def test_workflow_file_exists():
    assert WORKFLOW_PATH.exists()


def test_workflow_has_schedule_trigger():
    """Final production state: the workflow runs automatically every
    Monday (see test_schedule_is_weekly_not_daily for the exact cron),
    with workflow_dispatch still available for manual runs."""
    workflow = _load_workflow()
    triggers = workflow.get("on") or workflow.get(True)
    assert triggers is not None
    assert "schedule" in triggers
    assert "workflow_dispatch" in triggers


def test_schedule_runs_at_0800_ist():
    """08:00 IST == 02:30 UTC, regardless of day-of-week cadence."""
    workflow = _load_workflow()
    triggers = workflow.get("on") or workflow.get(True)
    schedule = triggers["schedule"]
    assert len(schedule) == 1
    cron = schedule[0]["cron"]
    minute, hour, day_of_month, month, day_of_week = cron.split()
    assert (minute, hour) == ("30", "2")


def test_schedule_is_temporarily_daily_for_the_observation_period():
    """TEMPORARY: intentionally daily ("30 2 * * *") for a 7-day
    observation period, per explicit instruction. This must be reverted
    to weekly ("30 2 * * 1", Monday only) after the observation window —
    when that happens, restore this test's assertion to
    `cron == "30 2 * * 1"` and `day_of_week != "*"` (its pre-daily form)."""
    workflow = _load_workflow()
    triggers = workflow.get("on") or workflow.get(True)
    schedule = triggers["schedule"]
    cron = schedule[0]["cron"]
    assert cron == "30 2 * * *"


def test_workflow_has_workflow_dispatch_with_dry_run_input():
    workflow = _load_workflow()
    triggers = workflow.get("on") or workflow.get(True)
    assert "workflow_dispatch" in triggers
    dispatch = triggers["workflow_dispatch"]
    assert "inputs" in dispatch
    assert "dry_run" in dispatch["inputs"]


def test_dry_run_input_defaults_to_true():
    workflow = _load_workflow()
    triggers = workflow.get("on") or workflow.get(True)
    dry_run_input = triggers["workflow_dispatch"]["inputs"]["dry_run"]
    assert str(dry_run_input["default"]).lower() == "true"


def test_workflow_has_concurrency_protection():
    workflow = _load_workflow()
    assert "concurrency" in workflow
    concurrency = workflow["concurrency"]
    assert concurrency["group"] == "climate-job-radar-production"
    assert concurrency["cancel-in-progress"] is False


def test_workflow_runs_on_ubuntu_latest():
    workflow = _load_workflow()
    job = next(iter(workflow["jobs"].values()))
    assert job["runs-on"] == "ubuntu-latest"


def test_pytest_step_runs_before_pipeline_step_with_no_continue_on_error():
    """Enforces Part 3: if tests fail, GitHub Actions' default behavior
    (no continue-on-error) must halt the job before scraping/email/commit."""
    workflow = _load_workflow()
    job = next(iter(workflow["jobs"].values()))
    steps = job["steps"]
    names = [step.get("name", "") for step in steps]

    pytest_index = next(i for i, n in enumerate(names) if "test" in n.lower())
    pipeline_index = next(i for i, n in enumerate(names) if "pipeline" in n.lower())
    assert pytest_index < pipeline_index

    pytest_step = steps[pytest_index]
    pipeline_step = steps[pipeline_index]
    assert pytest_step.get("continue-on-error") is not True
    assert pipeline_step.get("continue-on-error") is not True
    assert "pytest" in pytest_step["run"]


def test_pipeline_step_only_sends_secrets_never_prints_password():
    workflow = _load_workflow()
    job = next(iter(workflow["jobs"].values()))
    steps = job["steps"]
    pipeline_step = next(s for s in steps if "pipeline" in s.get("name", "").lower())
    env = pipeline_step.get("env", {})
    assert env.get("SMTP_PASSWORD") == "${{ secrets.SMTP_PASSWORD }}"
    for step in steps:
        run_text = step.get("run", "")
        assert "SMTP_PASSWORD" not in run_text or "secrets.SMTP_PASSWORD" in run_text


def test_commit_step_targets_production_database_and_is_conditional_on_real_run():
    workflow = _load_workflow()
    job = next(iter(workflow["jobs"].values()))
    steps = job["steps"]
    commit_step = next(s for s in steps if "commit" in s.get("name", "").lower())
    assert "data/database/climate_jobs.db" in commit_step["run"]
    assert "dry_run" in commit_step.get("if", "")


def test_workflow_has_write_permission_for_commit():
    workflow = _load_workflow()
    job = next(iter(workflow["jobs"].values()))
    assert job.get("permissions", {}).get("contents") == "write"
