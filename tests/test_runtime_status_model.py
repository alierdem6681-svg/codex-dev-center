import sys
import tempfile
import unittest
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from supervisor import (  # noqa: E402
    cto_autonomous_delivery,
    lifecycle_manager,
    progress_aware_runner,
    direct_cto_async_job,
    task_validation_engine,
    telegram_direct_cto_simulator,
    worker_runner,
)
from supervisor.task_status_constants import (  # noqa: E402
    TASK_STATUS_APPROVAL_REQUIRED,
    TASK_STATUS_DONE,
    TASK_STATUS_FAILED_RETRYABLE,
    TASK_STATUS_FAILED_TIMEOUT,
    TASK_STATUS_PIPELINE_FAILED,
    TASK_STATUS_PROPOSAL_DONE,
    TASK_STATUS_PROPOSAL_READY,
    TASK_STATUS_READY_FOR_VALIDATION,
)

WORKER_LIFECYCLE_SPEC = importlib.util.spec_from_file_location(
    "worker_lifecycle_check_test_module",
    ROOT / "scripts" / "worker_lifecycle_check.py",
)
worker_lifecycle_check = importlib.util.module_from_spec(WORKER_LIFECYCLE_SPEC)
assert WORKER_LIFECYCLE_SPEC.loader is not None
WORKER_LIFECYCLE_SPEC.loader.exec_module(worker_lifecycle_check)


class WorkerStatusModelTest(unittest.TestCase):
    def test_timeout_without_output_is_not_done(self):
        status, reason = worker_runner.classify_worker_result(124, [], "", False)

        self.assertEqual(status, TASK_STATUS_FAILED_TIMEOUT)
        self.assertEqual(reason, "worker_timeout_without_output")

    def test_timeout_with_expected_files_waits_for_validation(self):
        status, _reason = worker_runner.classify_worker_result(
            124,
            ["PLAN.md", "CHANGE_PROPOSAL.md", "TEST_PLAN.md", "RISK_REVIEW.md"],
            "partial output",
            False,
        )

        self.assertEqual(status, TASK_STATUS_READY_FOR_VALIDATION)

    def test_partial_proposal_is_proposal_ready(self):
        status, _reason = worker_runner.classify_worker_result(
            124,
            ["PLAN.md"],
            "draft",
            False,
        )

        self.assertEqual(status, TASK_STATUS_PROPOSAL_READY)

    def test_failure_without_proposal_is_retryable(self):
        status, _reason = worker_runner.classify_worker_result(1, [], "", False)

        self.assertEqual(status, TASK_STATUS_FAILED_RETRYABLE)

    def test_worker_restart_reconciles_own_stale_running_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "task_queue.json"
            queue_path.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "id": "TASK-STALE",
                                "status": "RUNNING",
                                "source": "cto",
                                "risk": "low",
                                "assigned_worker": "worker-3",
                            },
                            {
                                "id": "TASK-OTHER",
                                "status": "RUNNING",
                                "source": "cto",
                                "risk": "low",
                                "assigned_worker": "worker-2",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            original_queue = worker_runner.QUEUE_PATH
            worker_runner.QUEUE_PATH = queue_path
            try:
                recovered = worker_runner.reconcile_stale_running_tasks_for_worker("worker-3")
            finally:
                worker_runner.QUEUE_PATH = original_queue
            payload = json.loads(queue_path.read_text(encoding="utf-8"))

        self.assertEqual(recovered, ["TASK-STALE"])
        self.assertEqual(payload["tasks"][0]["status"], TASK_STATUS_FAILED_RETRYABLE)
        self.assertEqual(payload["tasks"][0]["result"], "worker_service_restarted_before_completion")
        self.assertEqual(payload["tasks"][1]["status"], "RUNNING")


class ProgressAwareRunnerTest(unittest.TestCase):
    def test_output_noise_without_meaningful_progress_stalls(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "out.txt"
            err = root / "err.txt"
            workspace = root / "workspace"
            workspace.mkdir()
            result = progress_aware_runner.run_progress_aware(
                ["bash", "-lc", "while true; do echo noise; sleep 0.2; done"],
                cwd=root,
                stdout_path=out,
                stderr_path=err,
                progress_paths=[workspace],
                progress_state_path=workspace / "progress_watchdog.json",
                stall_seconds=1,
                grace_seconds=0,
                poll_seconds=0.2,
                max_wall_seconds=5,
            )

        self.assertEqual(result["status"], "STALLED")
        self.assertEqual(result["stall_reason"], "no_meaningful_progress")
        self.assertGreater(result["output_activity_count"], 0)
        self.assertEqual(result["meaningful_event_count"], 0)

    def test_file_change_counts_as_meaningful_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            out = root / "out.txt"
            err = root / "err.txt"
            result = progress_aware_runner.run_progress_aware(
                ["bash", "-lc", "sleep 0.3; echo plan > workspace/PLAN.md; sleep 0.3"],
                cwd=root,
                stdout_path=out,
                stderr_path=err,
                progress_paths=[workspace],
                stall_seconds=1,
                grace_seconds=0,
                poll_seconds=0.1,
                max_wall_seconds=5,
            )

        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(result["returncode"], 0)
        self.assertGreaterEqual(result["meaningful_event_count"], 1)

    def test_git_diff_change_counts_as_meaningful_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocesses = [
                ["git", "init"],
                ["git", "config", "user.email", "test@example.invalid"],
                ["git", "config", "user.name", "Test User"],
            ]
            import subprocess

            for cmd in subprocesses:
                subprocess.run(cmd, cwd=str(root), check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            (root / "tracked.txt").write_text("before\n", encoding="utf-8")
            subprocess.run(["git", "add", "tracked.txt"], cwd=str(root), check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["git", "commit", "-m", "init"], cwd=str(root), check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            out = root / "out.txt"
            err = root / "err.txt"
            result = progress_aware_runner.run_progress_aware(
                ["bash", "-lc", "sleep 0.3; printf after >> tracked.txt; sleep 0.3"],
                cwd=root,
                stdout_path=out,
                stderr_path=err,
                progress_paths=[],
                git_roots=[root],
                stall_seconds=1,
                grace_seconds=0,
                poll_seconds=0.1,
                max_wall_seconds=5,
            )

        self.assertEqual(result["status"], "COMPLETED")
        self.assertGreaterEqual(result["meaningful_event_count"], 1)


class TelegramAsyncRoutingTest(unittest.TestCase):
    def test_direct_cto_async_job_has_progress_paths(self):
        self.assertTrue(hasattr(direct_cto_async_job, "REPORTS"))
        self.assertTrue(hasattr(direct_cto_async_job, "JOBS"))

    def test_direct_cto_usage_limit_failure_is_retryable(self):
        failure = direct_cto_async_job.classify_codex_failure(
            "",
            "ERROR: You've hit your usage limit. Try again at 10:56 AM.",
            {"status": "EXITED_NONZERO", "returncode": 1},
        )

        self.assertEqual(failure["status"], TASK_STATUS_FAILED_RETRYABLE)
        self.assertEqual(failure["result"], "codex_usage_limit_retryable")

    def test_direct_cto_generic_nonzero_failure_is_retryable(self):
        failure = direct_cto_async_job.classify_codex_failure(
            "",
            "unexpected nonzero exit",
            {"status": "EXITED_NONZERO", "returncode": 1},
        )

        self.assertEqual(failure["status"], TASK_STATUS_FAILED_RETRYABLE)
        self.assertEqual(failure["result"], "codex_failed_retryable")

    def test_nonlocal_short_message_routes_to_async_job(self):
        result = telegram_direct_cto_simulator.simulate_case(
            "short_async",
            "Bana sistem mimarisi için kısa bir öneri hazırla.",
        )

        self.assertEqual(result["route"], "async_job")
        self.assertTrue(result["async_ack_expected"])

    def test_action_command_routes_to_async_job(self):
        result = telegram_direct_cto_simulator.simulate_case(
            "action_async",
            "Pipeline başlat ve workerlara dağıt.",
        )

        self.assertTrue(result["action_command"])
        self.assertEqual(result["route"], "async_job")


class DeployGateStatusModelTest(unittest.TestCase):
    def test_proposal_done_is_not_deployable(self):
        task = {
            "id": "TASK-1",
            "status": TASK_STATUS_PROPOSAL_DONE,
            "repo_applied": True,
            "risk": "low",
            "title": "normal app work",
        }

        result = cto_autonomous_delivery.evaluate_task(task)

        self.assertFalse(result["ready_for_deploy_gate"])

    def test_done_with_repo_applied_is_deployable(self):
        task = {
            "id": "TASK-2",
            "status": TASK_STATUS_DONE,
            "repo_applied": True,
            "risk": "low",
            "title": "normal app work",
        }

        result = cto_autonomous_delivery.evaluate_task(task)

        self.assertTrue(result["ready_for_deploy_gate"])


class BacklogDispatcherModelTest(unittest.TestCase):
    def test_completed_child_prevents_duplicate_dispatch(self):
        tasks = [
            {"id": "PARENT", "status": TASK_STATUS_PROPOSAL_DONE, "backlog_dispatcher_child": "CHILD"},
            {"id": "CHILD", "status": TASK_STATUS_READY_FOR_VALIDATION},
        ]

        self.assertIsNone(lifecycle_manager.dispatcher_candidate(tasks))

    def test_failed_child_allows_retry(self):
        tasks = [
            {"id": "PARENT", "status": TASK_STATUS_PROPOSAL_DONE, "backlog_dispatcher_child": "CHILD"},
            {"id": "CHILD", "status": TASK_STATUS_FAILED_TIMEOUT},
        ]

        self.assertEqual(lifecycle_manager.dispatcher_candidate(tasks)["id"], "PARENT")

    def test_idle_worker_state_clears_current_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "workers.json"
            path.write_text(
                json.dumps({"workers": [{"id": "worker-1", "status": "IDLE", "current_task": "TASK-1"}]}),
                encoding="utf-8",
            )
            original = lifecycle_manager.WORKERS_PATH
            lifecycle_manager.WORKERS_PATH = path
            try:
                lifecycle_manager.update_worker_state("worker-1", "IDLE", "single_mode_test")
            finally:
                lifecycle_manager.WORKERS_PATH = original
            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertIsNone(payload["workers"][0]["current_task"])

    def test_idle_update_does_not_clear_running_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "workers.json"
            path.write_text(
                json.dumps({"workers": [{"id": "worker-1", "status": "RUNNING", "current_task": "TASK-1"}]}),
                encoding="utf-8",
            )
            original = lifecycle_manager.WORKERS_PATH
            lifecycle_manager.WORKERS_PATH = path
            try:
                lifecycle_manager.update_worker_state("worker-1", "IDLE", "wake_now_test")
            finally:
                lifecycle_manager.WORKERS_PATH = original
            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(payload["workers"][0]["status"], "RUNNING")
        self.assertEqual(payload["workers"][0]["current_task"], "TASK-1")


class WorkerLifecycleRepairTest(unittest.TestCase):
    def test_repair_marks_stale_running_retryable_and_clears_idle_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            state = runtime / "state"
            state.mkdir()
            queue_path = state / "task_queue.json"
            workers_path = state / "workers.json"
            queue_path.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "id": "TASK-STale",
                                "status": "RUNNING",
                                "source": "cto",
                                "risk": "low",
                                "assigned_worker": "worker-1",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            workers_path.write_text(
                json.dumps(
                    {
                        "workers": [
                            {
                                "id": "worker-1",
                                "status": "IDLE",
                                "current_task": "TASK-STale",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            result = worker_lifecycle_check.repair_state_consistency(runtime)
            queue = json.loads(queue_path.read_text(encoding="utf-8"))
            workers = json.loads(workers_path.read_text(encoding="utf-8"))

        self.assertEqual(result["stale_tasks_failed_retryable"], ["TASK-STale"])
        self.assertEqual(queue["tasks"][0]["status"], TASK_STATUS_FAILED_RETRYABLE)
        self.assertIsNone(workers["workers"][0]["current_task"])

    def test_running_task_requires_matching_worker_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            state = runtime / "state"
            state.mkdir()
            (state / "system_state.json").write_text("{}", encoding="utf-8")
            (state / "task_queue.json").write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "id": "TASK-RUN",
                                "status": "RUNNING",
                                "source": "cto",
                                "risk": "low",
                                "assigned_worker": "worker-1",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (state / "workers.json").write_text(
                json.dumps({"workers": [{"id": "worker-1", "status": "IDLE", "current_task": None}]}),
                encoding="utf-8",
            )

            result = worker_lifecycle_check.evaluate(runtime, repair=False)

        self.assertFalse(result["ok"])
        self.assertTrue(any("RUNNING task assigned to worker-1" in item for item in result["errors"]))


class TaskValidationEngineTest(unittest.TestCase):
    def write_ready_runtime(
        self,
        tmp: str,
        pipeline_status: str = "PASS",
        title: str = "normal worker task",
        task_status: str = TASK_STATUS_READY_FOR_VALIDATION,
        result: str | None = None,
        validation_status: str = "PENDING",
    ) -> Path:
        runtime = Path(tmp)
        state = runtime / "state"
        workspace = runtime / "workspaces" / "worker_worker-1_TASK-VAL_20260603_000000"
        state.mkdir(parents=True)
        workspace.mkdir(parents=True)
        for name in task_validation_engine.EXPECTED_WORKER_FILES[:4]:
            (workspace / name).write_text(
                "# Test\n\n"
                "Kapsam disi:\n"
                "- database destructive operation\n"
                "- credential rotation\n\n"
                "Do not change token/private key/env values.\n"
                "Valid worker output.\n",
                encoding="utf-8",
            )
        (state / "production_readiness_status.json").write_text(
            json.dumps({"status": pipeline_status, "ok": pipeline_status == "PASS", "checked_at": "2026-06-03T00:00:00+00:00"}),
            encoding="utf-8",
        )
        (state / "task_queue.json").write_text(
            json.dumps(
                {
                    "tasks": [
                        {
                            "id": "TASK-VAL",
                            "title": title,
                            "description": "Validate safe worker output.",
                            "status": task_status,
                            "result": result,
                            "validation_status": validation_status,
                            "source": "cto",
                            "risk": "low",
                            "assigned_worker": "worker-1",
                            "workspace": str(workspace),
                            "repo_applied": False,
                            "production_deployed": False,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        return runtime

    def test_ready_task_becomes_done_only_with_pipeline_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = self.write_ready_runtime(tmp, pipeline_status="PASS")
            result = task_validation_engine.validate_ready_tasks(runtime, limit=5)
            queue = json.loads((runtime / "state" / "task_queue.json").read_text(encoding="utf-8"))

        self.assertEqual(result["changed"], 1)
        self.assertEqual(queue["tasks"][0]["status"], TASK_STATUS_DONE)
        self.assertEqual(queue["tasks"][0]["validation_status"], "PASS")
        self.assertEqual(queue["tasks"][0]["pipeline_status"], "PASS")
        self.assertFalse(queue["tasks"][0]["production_deployed"])

    def test_pipeline_failure_does_not_mark_task_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = self.write_ready_runtime(tmp, pipeline_status="FAIL")
            result = task_validation_engine.validate_ready_tasks(runtime, limit=5)
            queue = json.loads((runtime / "state" / "task_queue.json").read_text(encoding="utf-8"))

        self.assertEqual(result["changed"], 1)
        self.assertEqual(queue["tasks"][0]["status"], TASK_STATUS_PIPELINE_FAILED)
        self.assertEqual(queue["tasks"][0]["validation_status"], "PASS")
        self.assertEqual(queue["tasks"][0]["pipeline_status"], "FAIL")

    def test_critical_operation_stays_approval_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = self.write_ready_runtime(tmp, pipeline_status="PASS", title="production token rotate")
            result = task_validation_engine.validate_ready_tasks(runtime, limit=5)
            queue = json.loads((runtime / "state" / "task_queue.json").read_text(encoding="utf-8"))

        self.assertEqual(result["changed"], 1)
        self.assertEqual(queue["tasks"][0]["status"], TASK_STATUS_APPROVAL_REQUIRED)
        self.assertTrue(queue["tasks"][0]["critical_operation_findings"])

    def test_engine_approval_can_be_rechecked_when_findings_were_policy_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = self.write_ready_runtime(
                tmp,
                pipeline_status="PASS",
                task_status=TASK_STATUS_APPROVAL_REQUIRED,
                result="critical_operation_requires_user_approval",
                validation_status="APPROVAL_REQUIRED",
            )
            result = task_validation_engine.validate_ready_tasks(runtime, limit=5)
            queue = json.loads((runtime / "state" / "task_queue.json").read_text(encoding="utf-8"))

        self.assertEqual(result["changed"], 1)
        self.assertEqual(queue["tasks"][0]["status"], TASK_STATUS_DONE)
        self.assertEqual(queue["tasks"][0]["critical_operation_findings"], [])


if __name__ == "__main__":
    unittest.main()
