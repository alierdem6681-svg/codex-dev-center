import sys
import tempfile
import unittest
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from supervisor import cto_autonomous_delivery, lifecycle_manager, worker_runner  # noqa: E402
from supervisor.task_status_constants import (  # noqa: E402
    TASK_STATUS_DONE,
    TASK_STATUS_FAILED_RETRYABLE,
    TASK_STATUS_FAILED_TIMEOUT,
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


if __name__ == "__main__":
    unittest.main()
