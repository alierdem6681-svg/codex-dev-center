import sys
import tempfile
import unittest
import importlib.util
import json
import contextlib
import io
import os
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "web_panel"))

from supervisor import (  # noqa: E402
    codex_quality_gate,
    critical_operation_policy,
    cto_autonomous_delivery,
    direct_cto_job_recovery,
    lifecycle_manager,
    production_readiness_suite,
    progress_aware_runner,
    direct_cto_async_job,
    direct_cto_progress_watcher,
    supervisor_cli,
    task_validation_engine,
    telegram_direct_cto,
    telegram_direct_cto_simulator,
    worker_runner,
)
from supervisor.task_status_constants import (  # noqa: E402
    TASK_STATUS_APPROVAL_REQUIRED,
    TASK_STATUS_DEPLOYED,
    TASK_STATUS_DONE,
    TASK_STATUS_FAILED_RETRYABLE,
    TASK_STATUS_FAILED_TIMEOUT,
    TASK_STATUS_NO_CHANGE,
    TASK_STATUS_PIPELINE_FAILED,
    TASK_STATUS_PROPOSAL_DONE,
    TASK_STATUS_PROPOSAL_READY,
    TASK_STATUS_READY_FOR_VALIDATION,
    TASK_STATUS_RUNNING,
    normalize_queue_payload,
    normalize_status,
)

WORKER_LIFECYCLE_SPEC = importlib.util.spec_from_file_location(
    "worker_lifecycle_check_test_module",
    ROOT / "scripts" / "worker_lifecycle_check.py",
)
worker_lifecycle_check = importlib.util.module_from_spec(WORKER_LIFECYCLE_SPEC)
assert WORKER_LIFECYCLE_SPEC.loader is not None
WORKER_LIFECYCLE_SPEC.loader.exec_module(worker_lifecycle_check)

PANEL_SERVER_SPEC = importlib.util.spec_from_file_location(
    "panel_server_test_module",
    ROOT / "web_panel" / "panel_server.py",
)
panel_server = importlib.util.module_from_spec(PANEL_SERVER_SPEC)
assert PANEL_SERVER_SPEC.loader is not None
PANEL_SERVER_SPEC.loader.exec_module(panel_server)

LEGACY_PANEL_SERVER_SPEC = importlib.util.spec_from_file_location(
    "legacy_panel_server_test_module",
    ROOT / "web_panel" / "server.py",
)
legacy_panel_server = importlib.util.module_from_spec(LEGACY_PANEL_SERVER_SPEC)
assert LEGACY_PANEL_SERVER_SPEC.loader is not None
LEGACY_PANEL_SERVER_SPEC.loader.exec_module(legacy_panel_server)


class WorkerStatusModelTest(unittest.TestCase):
    def test_task_status_normalizer_accepts_case_space_hyphen_and_separator_variants(self):
        self.assertEqual(normalize_status("ready for validation"), TASK_STATUS_READY_FOR_VALIDATION)
        self.assertEqual(normalize_status("ready/for.validation"), TASK_STATUS_READY_FOR_VALIDATION)
        self.assertEqual(normalize_status("FAILED-TIMEOUT"), TASK_STATUS_FAILED_TIMEOUT)
        self.assertEqual(normalize_status("FAILED.TIMEOUT"), TASK_STATUS_FAILED_TIMEOUT)
        self.assertEqual(normalize_status("in-progress"), TASK_STATUS_RUNNING)
        self.assertEqual(normalize_status("Completed"), TASK_STATUS_DONE)

    def test_queue_payload_reports_noncanonical_status_normalization(self):
        payload = {
            "tasks": [
                {"id": "TASK-READY", "status": "ready for validation", "risk": "medium"},
                {"id": "TASK-DONE", "status": "completed", "risk": "low"},
            ]
        }

        normalized, changes = normalize_queue_payload(payload)

        self.assertEqual(normalized["tasks"][0]["status"], TASK_STATUS_READY_FOR_VALIDATION)
        self.assertEqual(normalized["tasks"][1]["status"], TASK_STATUS_DONE)
        self.assertEqual([change["id"] for change in changes], ["TASK-READY", "TASK-DONE"])
        self.assertEqual(changes[0]["to_status"], TASK_STATUS_READY_FOR_VALIDATION)
        self.assertEqual(changes[1]["to_status"], TASK_STATUS_DONE)

    def test_critical_policy_ignores_explicit_safety_boundaries(self):
        safe_text = "\n".join(
            [
                "Kapsam dışı:",
                "- database destructive operation",
                "- irreversible migration",
                "Secret, IAM, billing, DNS, firewall veya database işlemi yapılmadı.",
                "Ana repo dosyalarını değiştirme; token/private key/env değerlerine dokunma.",
            ]
        )

        self.assertEqual(critical_operation_policy.critical_operation_findings(safe_text), [])

    def test_critical_policy_keeps_real_critical_changes_blocked(self):
        findings = critical_operation_policy.critical_operation_findings(
            "\n".join(
                [
                    "production token rotate",
                    "iam grant owner role",
                    "billing update payment settings",
                    "dns add record",
                    "firewall open production port",
                    "drop table customer_events",
                    "google ads mutate live campaign",
                ]
            )
        )

        self.assertIn("token_private_key_env_value_change", findings)
        self.assertIn("iam_owner_editor_change", findings)
        self.assertIn("billing_change", findings)
        self.assertIn("dns_change", findings)
        self.assertIn("firewall_change", findings)
        self.assertIn("database_destructive_operation", findings)
        self.assertIn("google_ads_live_mutate", findings)

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

    def test_repo_apply_requires_explicit_task_flag(self):
        self.assertFalse(worker_runner.task_allows_repo_apply({"dispatcher_mode": "validation"}))
        self.assertTrue(worker_runner.task_allows_repo_apply({"execution_mode": "repo_apply"}))
        self.assertTrue(worker_runner.task_allows_repo_apply({"repo_apply_allowed": True}))

    def test_repo_apply_path_allowlist_blocks_runtime_state(self):
        self.assertTrue(worker_runner.is_safe_repo_apply_path("supervisor/worker_runner.py"))
        self.assertTrue(worker_runner.is_safe_repo_apply_path("tests/test_runtime_status_model.py"))
        self.assertTrue(worker_runner.is_safe_repo_apply_path("./docs/ROADMAP.md"))
        self.assertTrue(worker_runner.is_safe_repo_apply_path("web_panel\\panel_server.py"))
        self.assertFalse(worker_runner.is_safe_repo_apply_path("state/task_queue.json"))
        self.assertFalse(worker_runner.is_safe_repo_apply_path(".env"))
        self.assertFalse(worker_runner.is_safe_repo_apply_path("AGENTS.md.bak"))
        self.assertFalse(worker_runner.is_safe_repo_apply_path("AGENTS.md/child"))
        self.assertFalse(worker_runner.is_safe_repo_apply_path("docs/../state/task_queue.json"))

    def test_repo_apply_ignores_generated_runtime_artifacts_only(self):
        self.assertTrue(worker_runner.is_ignorable_repo_apply_artifact("reports/apply-worker.md"))
        self.assertTrue(worker_runner.is_ignorable_repo_apply_artifact("logs/apply-worker.log"))
        self.assertTrue(worker_runner.is_ignorable_repo_apply_artifact("./tmp/apply-worker.log"))
        self.assertFalse(worker_runner.is_ignorable_repo_apply_artifact("state_templates/module_registry.json"))
        self.assertFalse(worker_runner.is_ignorable_repo_apply_artifact("docs/ROADMAP.md"))

    def test_production_readiness_simulation_contracts_are_non_mutating(self):
        contracts = production_readiness_suite.readiness_simulation_contracts()

        self.assertTrue(contracts["restart"]["ok"])
        self.assertTrue(contracts["failure_injection"]["ok"])
        self.assertFalse(contracts["production_deploy_performed"])
        self.assertFalse(contracts["mutating_cloud_operations_performed"])
        for group in ("restart", "failure_injection"):
            self.assertEqual(contracts[group]["mode"], "static_non_mutating_contract")
            self.assertTrue(contracts[group]["contracts"])
            self.assertTrue(all(item["ok"] for item in contracts[group]["contracts"]))

    def test_standard_quality_report_passes_with_required_readiness_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / "state"
            state.mkdir()
            gates = [
                "python_compile_check",
                "json_validation",
                "yaml_validation",
                "secret_leakage_scan",
                "forbidden_operation_scan",
                "unit_test",
                "integration_test",
                "staging_smoke_test",
                "rollback_simulation",
                "restart_simulation",
                "failure_injection_simulation",
            ]
            (state / "production_readiness_status.json").write_text(
                json.dumps(
                    {
                        "tests": {gate: {"ok": True, "status": "PASS"} for gate in gates},
                        "production_deploy_performed": False,
                        "staging_deploy_performed": False,
                        "mutating_cloud_operations_performed": False,
                    }
                ),
                encoding="utf-8",
            )

            report = codex_quality_gate.write_standard_quality_report(root)
            report_file = root / "reports" / "quality-gate-report.json"
            summary_file = root / "reports" / "quality-gate-summary.md"

            self.assertEqual(report["status"], "pass")
            self.assertTrue(all(check["status"] == "pass" for check in report["checks"]))
            self.assertTrue(report_file.exists())
            self.assertTrue(summary_file.exists())
            self.assertEqual(json.loads(report_file.read_text(encoding="utf-8"))["status"], "pass")

    def test_standard_quality_report_fails_when_required_artifact_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = codex_quality_gate.build_standard_quality_report(
                Path(tmp),
                generated_at="2026-06-03T19:17:22+00:00",
            )

        self.assertEqual(report["status"], "fail")
        self.assertEqual({check["status"] for check in report["checks"]}, {"missing"})
        self.assertTrue(all(check["reason"].startswith("missing_artifact:") for check in report["checks"]))

    def test_standard_quality_report_fails_on_mutating_simulation_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / "state"
            state.mkdir()
            gates = [
                "python_compile_check",
                "json_validation",
                "yaml_validation",
                "secret_leakage_scan",
                "forbidden_operation_scan",
                "unit_test",
                "integration_test",
                "staging_smoke_test",
                "rollback_simulation",
                "restart_simulation",
                "failure_injection_simulation",
            ]
            (state / "production_readiness_status.json").write_text(
                json.dumps(
                    {
                        "tests": {gate: {"ok": True, "status": "PASS"} for gate in gates},
                        "production_deploy_performed": False,
                        "staging_deploy_performed": True,
                        "mutating_cloud_operations_performed": False,
                    }
                ),
                encoding="utf-8",
            )

            report = codex_quality_gate.build_standard_quality_report(root)

        self.assertEqual(report["status"], "fail")
        simulation = next(check for check in report["checks"] if check["name"] == "simulation_dry_run")
        self.assertEqual(simulation["status"], "fail")
        self.assertIn("mutating_flags_not_false:staging_deploy_performed", simulation["reason"])

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

    def test_worker_does_not_claim_second_task_while_already_running_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "task_queue.json"
            queue_path.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "id": "TASK-RUNNING",
                                "status": "RUNNING",
                                "source": "cto",
                                "risk": "low",
                                "assigned_worker": "worker-1",
                            },
                            {
                                "id": "TASK-NEXT",
                                "status": "PENDING",
                                "source": "cto",
                                "risk": "low",
                                "assigned_worker": "worker-1",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            original_queue = worker_runner.QUEUE_PATH
            worker_runner.QUEUE_PATH = queue_path
            try:
                claimed = worker_runner.claim_task("worker-1")
            finally:
                worker_runner.QUEUE_PATH = original_queue
            payload = json.loads(queue_path.read_text(encoding="utf-8"))

        self.assertIsNone(claimed)
        self.assertEqual(payload["tasks"][0]["status"], "RUNNING")
        self.assertEqual(payload["tasks"][1]["status"], "PENDING")

    def test_late_progress_update_does_not_reopen_finished_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            queue_path = state / "task_queue.json"
            workers_path = state / "workers.json"
            queue_path.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "id": "TASK-DONE",
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
                                "status": "RUNNING",
                                "current_task": "TASK-DONE",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            originals = (worker_runner.QUEUE_PATH, worker_runner.WORKERS_PATH)
            worker_runner.QUEUE_PATH = queue_path
            worker_runner.WORKERS_PATH = workers_path
            try:
                worker_runner.finish_task(
                    "TASK-DONE",
                    "worker-1",
                    TASK_STATUS_READY_FOR_VALIDATION,
                    "worker_output_ready_for_validation",
                )
                worker_runner.update_task_progress(
                    "TASK-DONE",
                    "worker-1",
                    {
                        "status": "RUNNING",
                        "updated_at": "2026-06-03T10:00:00+00:00",
                        "elapsed_seconds": 1,
                        "meaningful_event_count": 1,
                    },
                )
            finally:
                worker_runner.QUEUE_PATH, worker_runner.WORKERS_PATH = originals
            queue = json.loads(queue_path.read_text(encoding="utf-8"))
            workers = json.loads(workers_path.read_text(encoding="utf-8"))

        self.assertEqual(queue["tasks"][0]["status"], TASK_STATUS_READY_FOR_VALIDATION)
        self.assertNotIn("progress_watchdog", queue["tasks"][0])
        self.assertEqual(workers["workers"][0]["status"], "IDLE")
        self.assertIsNone(workers["workers"][0]["current_task"])


class ProgressAwareRunnerTest(unittest.TestCase):
    def test_snapshot_paths_tolerates_deleted_directory_during_walk(self):
        class VanishingPath:
            name = "vanishing"

            def exists(self):
                return True

            def is_dir(self):
                return True

            def rglob(self, pattern):
                raise FileNotFoundError("deleted during scan")

        self.assertEqual(progress_aware_runner.snapshot_paths([VanishingPath()]), {})

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

    def test_direct_cto_save_job_preserves_progress_watcher_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_file = Path(tmp) / "JOB-MERGE.json"
            job_file.write_text(
                json.dumps(
                    {
                        "id": "JOB-MERGE",
                        "status": "RUNNING",
                        "progress_update_count": 2,
                        "last_progress_sent_at": "2026-06-03T10:00:00+00:00",
                    }
                ),
                encoding="utf-8",
            )
            job = {"id": "JOB-MERGE", "status": "FINAL_REPORTED", "result": "telegram_notified"}
            direct_cto_async_job.save_job(job_file, job)
            payload = json.loads(job_file.read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], "FINAL_REPORTED")
        self.assertEqual(payload["result"], "telegram_notified")
        self.assertEqual(payload["progress_update_count"], 2)
        self.assertEqual(job["progress_update_count"], 2)

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
        self.assertEqual(result["ack_deadline_seconds"], 3)

    def test_long_task_routes_to_async_before_local_reply(self):
        result = telegram_direct_cto_simulator.simulate_case(
            "long_multistep",
            "Uçtan uca çalış: worker ata, pipeline çalıştır, fail olursa düzelt, gate PASS olunca production'a al.",
        )

        self.assertTrue(result["long_task"])
        self.assertEqual(result["route"], "async_job")
        self.assertTrue(result["async_ack_expected"])
        self.assertEqual(result["ack_deadline_seconds"], 3)

    def test_critical_operation_routes_to_approval_before_async(self):
        result = telegram_direct_cto_simulator.simulate_case(
            "database_destructive",
            "Production database " + "delete" + " from users çalıştır.",
        )

        self.assertIn("database_destructive_operation", result["critical_operation_findings"])
        self.assertEqual(result["route"], "local_natural_reply")
        self.assertEqual(result["reply_kind"], "approval_required")
        self.assertFalse(result["async_ack_expected"])

    def test_handle_message_starts_async_job_and_sends_ack_without_sync_codex(self):
        calls = []

        def fake_start_async_job(chat_id, text, router_task_id=None, action_command=False):
            calls.append(("start_async_job", chat_id, router_task_id, action_command))
            return "JOB-ACK"

        def fake_send_message(token, chat_id, text):
            calls.append(("send_message", chat_id, text))
            return True

        def fail_run_codex(_text):
            raise AssertionError("run_codex must not be called by Telegram handler")

        originals = (
            telegram_direct_cto.LOGS,
            telegram_direct_cto.audit_passthrough,
            telegram_direct_cto.start_async_job,
            telegram_direct_cto.send_message,
            telegram_direct_cto.run_codex,
        )
        with tempfile.TemporaryDirectory() as tmp:
            telegram_direct_cto.LOGS = Path(tmp)
            telegram_direct_cto.audit_passthrough = lambda *args, **kwargs: {}
            telegram_direct_cto.start_async_job = fake_start_async_job
            telegram_direct_cto.send_message = fake_send_message
            telegram_direct_cto.run_codex = fail_run_codex
            try:
                started = time.monotonic()
                telegram_direct_cto.handle_message(
                    "TOKEN",
                    "123",
                    {
                        "chat": {"id": "123"},
                        "from": {"username": "tester"},
                        "text": "Bana sistem mimarisi için kısa bir öneri hazırla.",
                    },
                )
                elapsed = time.monotonic() - started
            finally:
                (
                    telegram_direct_cto.LOGS,
                    telegram_direct_cto.audit_passthrough,
                    telegram_direct_cto.start_async_job,
                    telegram_direct_cto.send_message,
                    telegram_direct_cto.run_codex,
                ) = originals

        self.assertLess(elapsed, 1)
        self.assertEqual(calls[0][0], "start_async_job")
        self.assertEqual(calls[1][0], "send_message")
        self.assertIn("JOB-ACK", calls[1][2])

    def test_handle_message_blocks_critical_operation_before_async_job(self):
        calls = []

        def fail_start_async_job(*_args, **_kwargs):
            raise AssertionError("critical operation must not start async job")

        def fake_send_message(token, chat_id, text):
            calls.append(("send_message", chat_id, text))
            return True

        originals = (
            telegram_direct_cto.LOGS,
            telegram_direct_cto.audit_passthrough,
            telegram_direct_cto.start_async_job,
            telegram_direct_cto.send_message,
        )
        with tempfile.TemporaryDirectory() as tmp:
            telegram_direct_cto.LOGS = Path(tmp)
            telegram_direct_cto.audit_passthrough = lambda *args, **kwargs: {}
            telegram_direct_cto.start_async_job = fail_start_async_job
            telegram_direct_cto.send_message = fake_send_message
            try:
                telegram_direct_cto.handle_message(
                    "TOKEN",
                    "123",
                    {
                        "chat": {"id": "123"},
                        "from": {"username": "tester"},
                        "text": "Production database " + "delete" + " from users çalıştır.",
                    },
                )
            finally:
                (
                    telegram_direct_cto.LOGS,
                    telegram_direct_cto.audit_passthrough,
                    telegram_direct_cto.start_async_job,
                    telegram_direct_cto.send_message,
                ) = originals

        self.assertEqual(len(calls), 1)
        self.assertIn("APPROVAL_REQUIRED", calls[0][2])


class DirectCtoProgressWatcherTest(unittest.TestCase):
    def write_job(self, root, job_id, status):
        path = Path(root) / f"{job_id}.json"
        path.write_text(json.dumps({"id": job_id, "status": status}), encoding="utf-8")
        return path

    def test_terminal_job_breaks_long_progress_sleep_quickly(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_jobs = direct_cto_progress_watcher.JOBS
            direct_cto_progress_watcher.JOBS = Path(tmp)
            try:
                self.write_job(tmp, "JOB-TERMINAL", "FAILED_RETRYABLE")
                started = time.time()
                stopped = direct_cto_progress_watcher.sleep_until_next_update_or_terminal(
                    "JOB-TERMINAL",
                    total_seconds=60,
                    poll_seconds=0.05,
                )
            finally:
                direct_cto_progress_watcher.JOBS = original_jobs

        self.assertTrue(stopped)
        self.assertLess(time.time() - started, 1)

    def test_active_job_waits_until_short_interval_finishes(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_jobs = direct_cto_progress_watcher.JOBS
            direct_cto_progress_watcher.JOBS = Path(tmp)
            try:
                self.write_job(tmp, "JOB-RUNNING", "RUNNING")
                stopped = direct_cto_progress_watcher.sleep_until_next_update_or_terminal(
                    "JOB-RUNNING",
                    total_seconds=0.1,
                    poll_seconds=0.02,
                )
            finally:
                direct_cto_progress_watcher.JOBS = original_jobs

        self.assertFalse(stopped)


class ProductionReadinessSuiteScanTest(unittest.TestCase):
    def test_iter_repo_text_files_tolerates_deleted_directory_during_walk(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            keep = root / "keep.py"
            keep.write_text("print('ok')\n", encoding="utf-8")

            def fake_walk(path, onerror=None):
                yield str(root), ["workspaces"], ["keep.py"]
                if onerror:
                    onerror(FileNotFoundError(str(root / "workspaces" / "vanished")))

            original_root = production_readiness_suite.ROOT
            original_walk = production_readiness_suite.os.walk
            production_readiness_suite.ROOT = root
            production_readiness_suite.os.walk = fake_walk
            try:
                files = list(production_readiness_suite.iter_repo_text_files())
            finally:
                production_readiness_suite.ROOT = original_root
                production_readiness_suite.os.walk = original_walk

        self.assertEqual(files, [keep])

    def test_dry_run_non_mutating_contract_requires_json_flags(self):
        result = {
            "ok": True,
            "stdout": json.dumps(
                {
                    "ok": True,
                    "status": "PASS",
                    "dry_run": True,
                    "mutating_cloud_operations_performed": False,
                }
            ),
        }

        contract = production_readiness_suite.dry_run_non_mutating_contract(
            result,
            ["mutating_cloud_operations_performed"],
        )

        self.assertTrue(contract["ok"])
        self.assertEqual(contract["mode"], "dry_run_non_mutating_contract")

        result["stdout"] = json.dumps(
            {
                "ok": True,
                "status": "PASS",
                "dry_run": True,
                "mutating_cloud_operations_performed": True,
            }
        )

        contract = production_readiness_suite.dry_run_non_mutating_contract(
            result,
            ["mutating_cloud_operations_performed"],
        )

        self.assertFalse(contract["ok"])
        self.assertEqual(contract["flag_mismatches"], ["mutating_cloud_operations_performed"])

    def test_staging_and_rollback_rejects_mutating_rollback_dry_run(self):
        staging_payload = {
            "ok": True,
            "status": "PASS",
            "dry_run": True,
            "mutating_cloud_operations_performed": False,
        }
        rollback_payload = {
            "ok": True,
            "status": "PASS",
            "dry_run": True,
            "git_reset_performed": True,
            "data_mutation_performed": False,
        }

        def fake_run_cmd(cmd, timeout=120):
            if "staging-deploy" in cmd:
                return {"ok": True, "stdout": json.dumps(staging_payload), "stderr": "", "returncode": 0}
            if "rollback" in cmd:
                return {"ok": True, "stdout": json.dumps(rollback_payload), "stderr": "", "returncode": 0}
            return {"ok": False, "stdout": "", "stderr": "unexpected command", "returncode": 1}

        original_run_cmd = production_readiness_suite.run_cmd
        original_reports = production_readiness_suite.REPORTS
        with tempfile.TemporaryDirectory(dir=production_readiness_suite.ROOT) as tmp:
            production_readiness_suite.run_cmd = fake_run_cmd
            production_readiness_suite.REPORTS = Path(tmp) / "reports"
            try:
                results = {}
                production_readiness_suite.staging_and_rollback(results)
            finally:
                production_readiness_suite.run_cmd = original_run_cmd
                production_readiness_suite.REPORTS = original_reports

        self.assertTrue(results["staging_smoke_test"]["ok"])
        self.assertFalse(results["rollback_simulation"]["ok"])
        self.assertEqual(
            results["rollback_simulation"]["details"]["contract"]["flag_mismatches"],
            ["git_reset_performed"],
        )


class DirectCtoJobRecoveryTest(unittest.TestCase):
    def write_job(self, root, job_id, status="RUNNING", pid=999999999):
        jobs_dir = Path(root) / "state" / "direct_cto_jobs"
        jobs_dir.mkdir(parents=True)
        old = "2026-06-03T00:00:00+00:00"
        (jobs_dir / f"{job_id}.json").write_text(
            json.dumps(
                {
                    "id": job_id,
                    "status": status,
                    "chat_id": "123",
                    "created_at": old,
                    "started_at": old,
                    "updated_at": old,
                }
            ),
            encoding="utf-8",
        )
        (jobs_dir / f"{job_id}.progress.json").write_text(
            json.dumps({"status": "RUNNING", "pid": pid, "updated_at": old}),
            encoding="utf-8",
        )
        return jobs_dir / f"{job_id}.json"

    def test_stale_running_direct_cto_job_without_process_is_retryable(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_path = self.write_job(tmp, "JOB-STALE", pid=999999999)
            result = direct_cto_job_recovery.reconcile_stale_jobs(tmp, stale_seconds=1, notify=False)
            job = json.loads(job_path.read_text(encoding="utf-8"))

        self.assertEqual(result["changed"], 1)
        self.assertEqual(job["status"], TASK_STATUS_FAILED_RETRYABLE)
        self.assertEqual(job["result"], "direct_cto_process_lost_retryable")

    def test_running_direct_cto_job_with_live_process_is_left_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_path = self.write_job(tmp, "JOB-LIVE", pid=os.getpid())
            result = direct_cto_job_recovery.reconcile_stale_jobs(tmp, stale_seconds=1, notify=False)
            job = json.loads(job_path.read_text(encoding="utf-8"))

        self.assertEqual(result["changed"], 0)
        self.assertEqual(job["status"], "RUNNING")


class DashboardDirectCtoJobsSummaryTest(unittest.TestCase):
    def write_job(self, jobs_dir, name, status, mtime):
        path = jobs_dir / f"{name}.json"
        path.write_text(json.dumps({"id": name, "status": status}), encoding="utf-8")
        os.utime(path, (mtime, mtime))
        return path

    def test_active_direct_cto_job_outside_recent_limit_is_counted_and_listed(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            jobs_dir = state / "direct_cto_jobs"
            jobs_dir.mkdir(parents=True)
            self.write_job(jobs_dir, "JOB-OLD-ACTIVE", "RUNNING", 1)
            for idx in range(8):
                self.write_job(jobs_dir, f"JOB-RECENT-{idx}", "FINAL_REPORTED", 100 + idx)

            original_state = panel_server.STATE
            panel_server.STATE = state
            try:
                summary = panel_server.direct_cto_jobs_summary(limit=4)
            finally:
                panel_server.STATE = original_state

        ids = [job.get("id") for job in summary["jobs"]]
        self.assertEqual(summary["count"], 9)
        self.assertEqual(summary["active_count"], 1)
        self.assertIn("JOB-OLD-ACTIVE", ids)


class DashboardControlledExecutionSummaryTest(unittest.TestCase):
    def test_controlled_execution_summary_exposes_proposal_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            reports = Path(tmp) / "reports"
            reports.mkdir(parents=True)
            report = reports / "CONTROLLED_EXECUTION_20260603_120000.md"
            report.write_text("# report\n", encoding="utf-8")
            original_reports = panel_server.REPORTS
            panel_server.REPORTS = reports
            try:
                summary = panel_server.controlled_execution_summary(
                    {
                        "controlled_execution_proposal_ready": True,
                        "last_controlled_execution_task": "TASK-CONTROLLED",
                        "last_controlled_execution_workspace": "/opt/codex-dev-center/workspaces/controlled_TASK",
                    }
                )
            finally:
                panel_server.REPORTS = original_reports

        self.assertEqual(summary["status"], "PROPOSAL_READY")
        self.assertTrue(summary["proposal_ready"])
        self.assertEqual(summary["last_task"], "TASK-CONTROLLED")
        self.assertEqual(summary["latest_report"], "CONTROLLED_EXECUTION_20260603_120000.md")
        self.assertFalse(summary["proposal_mode_repo_mutation_allowed"])
        self.assertFalse(summary["proposal_mode_production_deploy_allowed"])
        self.assertFalse(summary["critical_operations_allowed"])


class DashboardPipelineTrackingStatusTest(unittest.TestCase):
    def test_status_payload_keeps_pipeline_tracking_keys_when_markers_are_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            state.mkdir(parents=True)

            originals = {
                panel_server: panel_server.STATE,
                legacy_panel_server: legacy_panel_server.STATE,
            }
            try:
                for module in originals:
                    module.STATE = state
                    payload = module.status_payload()
                    self.assertIn("github_actions", payload)
                    self.assertIn("pipeline_status", payload)
                    self.assertEqual(payload["github_actions"], {})
                    self.assertEqual(payload["pipeline_status"], {})
            finally:
                for module, original_state in originals.items():
                    module.STATE = original_state

    def test_status_payload_exposes_pipeline_tracking_for_all_panel_servers(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            state.mkdir(parents=True)
            (state / "github_actions_status.json").write_text(
                json.dumps(
                    {
                        "runner_name": "codex-dev-center-01",
                        "last_deploy_status": "PASS",
                        "last_deploy_run_id": "26814905600",
                    }
                ),
                encoding="utf-8",
            )
            (state / "pipeline_status.json").write_text(
                json.dumps({"task_to_deploy_test": "PASS", "checked_at": "2026-06-03T00:00:00+00:00"}),
                encoding="utf-8",
            )

            originals = {
                panel_server: panel_server.STATE,
                legacy_panel_server: legacy_panel_server.STATE,
            }
            try:
                for module in originals:
                    module.STATE = state
                    payload = module.status_payload()
                    self.assertEqual(payload["github_actions"]["last_deploy_status"], "PASS")
                    self.assertEqual(payload["github_actions"]["runner_name"], "codex-dev-center-01")
                    self.assertEqual(payload["pipeline_status"]["task_to_deploy_test"], "PASS")
            finally:
                for module, original_state in originals.items():
                    module.STATE = original_state


class DeployGateStatusModelTest(unittest.TestCase):
    def deployable_task(self, task_id: str = "TASK-DEPLOY") -> dict:
        return {
            "id": task_id,
            "status": TASK_STATUS_DONE,
            "repo_applied": True,
            "branch_merged": True,
            "validation_status": "PASS",
            "pipeline_status": "PASS",
            "risk": "low",
            "title": "safe deployment scope note",
            "description": "Kapsam dışı:\n- irreversible migration yapılmadı.\nDo not change token/private key/env values.",
        }

    @contextlib.contextmanager
    def patched_delivery_runtime(self, tmp: str, tasks: list[dict]):
        runtime = Path(tmp)
        state = runtime / "state"
        reports = runtime / "reports"
        state.mkdir(parents=True)
        reports.mkdir(parents=True)
        queue = state / "task_queue.json"
        queue.write_text(json.dumps({"tasks": tasks}), encoding="utf-8")
        original_queue = cto_autonomous_delivery.QUEUE
        original_state = cto_autonomous_delivery.STATE
        original_reports = cto_autonomous_delivery.REPORTS
        original_policy = cto_autonomous_delivery.policy
        original_readiness = cto_autonomous_delivery.run_readiness
        cto_autonomous_delivery.QUEUE = queue
        cto_autonomous_delivery.STATE = state
        cto_autonomous_delivery.REPORTS = reports
        cto_autonomous_delivery.policy = lambda: {
            "production_deploy_requires_user_approval_for_normal_app_changes": False,
            "production_deploy_allowed_when_all_gates_pass": True,
            "max_parallel_tasks": 1,
            "stable_successful_low_risk_deploy_threshold": 3,
        }
        cto_autonomous_delivery.run_readiness = lambda: {
            "ok": True,
            "status": "PASS",
            "score_percent": 100,
            "failed": [],
        }
        try:
            yield queue
        finally:
            cto_autonomous_delivery.QUEUE = original_queue
            cto_autonomous_delivery.STATE = original_state
            cto_autonomous_delivery.REPORTS = original_reports
            cto_autonomous_delivery.policy = original_policy
            cto_autonomous_delivery.run_readiness = original_readiness

    def test_proposal_done_is_not_deployable(self):
        task = {
            "id": "TASK-1",
            "status": TASK_STATUS_PROPOSAL_DONE,
            "repo_applied": True,
            "validation_status": "PASS",
            "pipeline_status": "PASS",
            "risk": "low",
            "title": "normal app work",
        }

        result = cto_autonomous_delivery.evaluate_task(task)

        self.assertFalse(result["ready_for_deploy_gate"])

    def test_done_with_repo_applied_is_deployable(self):
        task = self.deployable_task("TASK-2")

        result = cto_autonomous_delivery.evaluate_task(task)

        self.assertTrue(result["ready_for_deploy_gate"])

    def test_safe_boundary_context_does_not_block_deploy_gate(self):
        task = self.deployable_task("TASK-CRED-SAFE")

        result = cto_autonomous_delivery.evaluate_task(task)

        self.assertTrue(result["ready_for_deploy_gate"])
        self.assertFalse(result["critical"]["approval_required"])
        self.assertEqual(result["critical"]["source"], "structured_task_state")

    def test_done_repo_applied_requires_validation_and_pipeline_pass(self):
        task = self.deployable_task("TASK-GATES")
        task["pipeline_status"] = "FAIL"

        result = cto_autonomous_delivery.evaluate_task(task)

        self.assertFalse(result["ready_for_deploy_gate"])

    def test_active_approval_required_blocks_deploy_gate(self):
        task = self.deployable_task("TASK-ACTIVE-APPROVAL")
        task["approval_required"] = True
        task["critical_operation_findings"] = ["token_private_key_env_value_change"]

        result = cto_autonomous_delivery.evaluate_task(task)

        self.assertFalse(result["ready_for_deploy_gate"])
        self.assertTrue(result["critical"]["approval_required"])

    def test_proposal_ready_and_ready_for_validation_are_not_deployable(self):
        for status in [TASK_STATUS_PROPOSAL_READY, TASK_STATUS_READY_FOR_VALIDATION]:
            task = self.deployable_task(f"TASK-{status}")
            task["status"] = status

            result = cto_autonomous_delivery.evaluate_task(task)

            self.assertFalse(result["ready_for_deploy_gate"])

    def test_deploy_task_does_not_return_approval_required_for_safe_boundary_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = self.deployable_task("TASK-DEPLOY-SAFE")
            with self.patched_delivery_runtime(tmp, [task]):
                result = cto_autonomous_delivery.deploy_task("TASK-DEPLOY-SAFE", execute=False, smoke=True)

        self.assertEqual(result["status"], "DRY_RUN_GATES_PASS_DEPLOY_ALLOWED")
        self.assertFalse(result["evaluation"]["critical"]["approval_required"])

    def test_deploy_task_blocks_active_approval_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = self.deployable_task("TASK-DEPLOY-ACTIVE-APPROVAL")
            task["approval_required"] = True
            with self.patched_delivery_runtime(tmp, [task]):
                result = cto_autonomous_delivery.deploy_task("TASK-DEPLOY-ACTIVE-APPROVAL", execute=False, smoke=True)

        self.assertEqual(result["status"], "APPROVAL_REQUIRED")

    def test_pr_ready_candidate_uses_structured_gate_not_raw_task_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = self.deployable_task("TASK-PR-SAFE")
            task["status"] = TASK_STATUS_DONE
            task["repo_applied"] = False
            task["branch_merged"] = False
            task["delivery_level"] = "PR_READY"
            task["pull_request_number"] = 123
            with self.patched_delivery_runtime(tmp, [task]):
                candidate = cto_autonomous_delivery.pr_ready_candidate()

        self.assertEqual(candidate, "TASK-PR-SAFE")

    def test_merge_pr_task_uses_structured_gate_not_raw_task_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = self.deployable_task("TASK-MERGE-SAFE")
            task["status"] = TASK_STATUS_DONE
            task["repo_applied"] = False
            task["branch_merged"] = False
            task["delivery_level"] = "PR_READY"
            task["pull_request_number"] = 123
            original_run = cto_autonomous_delivery.run

            def fake_run(_args, cwd=None, timeout=300):
                return {
                    "ok": True,
                    "returncode": 0,
                    "stdout": json.dumps(
                        {
                            "number": 123,
                            "url": "https://example.invalid/pr/123",
                            "state": "OPEN",
                            "isDraft": False,
                            "mergeStateStatus": "CLEAN",
                            "headRefName": "worker/task",
                            "baseRefName": "main",
                            "mergeCommit": None,
                        }
                    ),
                    "stderr": "",
                    "cmd": "gh pr view 123",
                }

            cto_autonomous_delivery.run = fake_run
            try:
                with self.patched_delivery_runtime(tmp, [task]):
                    result = cto_autonomous_delivery.merge_pr_task("TASK-MERGE-SAFE", execute=False)
            finally:
                cto_autonomous_delivery.run = original_run

        self.assertEqual(result["status"], "DRY_RUN_PR_READY_TO_MERGE")

    def test_dirty_pr_is_marked_conflict_and_skipped_by_finalizer(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = self.deployable_task("TASK-MERGE-DIRTY")
            task["status"] = TASK_STATUS_DONE
            task["repo_applied"] = False
            task["branch_merged"] = False
            task["delivery_level"] = "PR_READY"
            task["pull_request_number"] = 47
            original_run = cto_autonomous_delivery.run

            def fake_run(_args, cwd=None, timeout=300):
                return {
                    "ok": True,
                    "returncode": 0,
                    "stdout": json.dumps(
                        {
                            "number": 47,
                            "url": "https://example.invalid/pr/47",
                            "state": "OPEN",
                            "isDraft": False,
                            "mergeStateStatus": "DIRTY",
                            "headRefName": "worker/task",
                            "baseRefName": "main",
                            "mergeCommit": None,
                        }
                    ),
                    "stderr": "",
                    "cmd": "gh pr view 47",
                }

            cto_autonomous_delivery.run = fake_run
            try:
                with self.patched_delivery_runtime(tmp, [task]) as queue_path:
                    result = cto_autonomous_delivery.merge_pr_task("TASK-MERGE-DIRTY", execute=True)
                    queue = json.loads(queue_path.read_text(encoding="utf-8"))
                    candidate = cto_autonomous_delivery.pr_ready_candidate()
            finally:
                cto_autonomous_delivery.run = original_run

        updated = queue["tasks"][0]
        self.assertEqual(result["status"], "PR_NOT_MERGEABLE")
        self.assertEqual(updated["delivery_level"], "PR_CONFLICT")
        self.assertEqual(updated["deployment_status"], "MERGE_CONFLICT")
        self.assertEqual(updated["status"], TASK_STATUS_FAILED_RETRYABLE)
        self.assertTrue(updated["merge_blocked"])
        self.assertEqual(candidate, "")

    def test_finalizer_skips_conflicting_pr_and_deploys_next_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            ready = self.deployable_task("TASK-READY-NEXT")
            ready["status"] = TASK_STATUS_DONE
            ready["repo_applied"] = False
            ready["branch_merged"] = False
            ready["delivery_level"] = "PR_READY"
            ready["pull_request_number"] = 59
            conflict = self.deployable_task("TASK-CONFLICT-FIRST")
            conflict["status"] = TASK_STATUS_DONE
            conflict["repo_applied"] = False
            conflict["branch_merged"] = False
            conflict["delivery_level"] = "PR_READY"
            conflict["pull_request_number"] = 47
            original_run = cto_autonomous_delivery.run
            original_dispatch = cto_autonomous_delivery.dispatch_workflow
            original_sleep = cto_autonomous_delivery.time.sleep
            calls: list[list[str]] = []

            def fake_run(args, cwd=None, timeout=300):
                calls.append(args)
                if args[:3] == ["gh", "pr", "merge"]:
                    return {"ok": True, "returncode": 0, "stdout": "", "stderr": "", "cmd": "gh pr merge 59"}
                if args[:3] == ["gh", "pr", "view"]:
                    number = str(args[3])
                    merged = any(call[:3] == ["gh", "pr", "merge"] for call in calls)
                    if number == "47":
                        payload = {
                            "number": 47,
                            "url": "https://example.invalid/pr/47",
                            "state": "OPEN",
                            "isDraft": False,
                            "mergeStateStatus": "DIRTY",
                            "headRefName": "worker/conflict",
                            "baseRefName": "main",
                            "mergeCommit": None,
                        }
                    else:
                        payload = {
                            "number": 59,
                            "url": "https://example.invalid/pr/59",
                            "state": "MERGED" if merged else "OPEN",
                            "isDraft": False,
                            "mergeStateStatus": "CLEAN",
                            "headRefName": "worker/ready",
                            "baseRefName": "main",
                            "mergeCommit": {"oid": "merge59"} if merged else None,
                        }
                    return {"ok": True, "returncode": 0, "stdout": json.dumps(payload), "stderr": "", "cmd": "gh pr view"}
                return {"ok": False, "returncode": 1, "stdout": "", "stderr": "unexpected command", "cmd": " ".join(args)}

            def fake_dispatch(workflow, wait=False):
                run_id = "100" if workflow == cto_autonomous_delivery.DEPLOY_WORKFLOW else "101"
                return {
                    "ok": True,
                    "status": "WORKFLOW_SUCCESS_REUSED",
                    "deduped": True,
                    "run": {
                        "databaseId": run_id,
                        "url": f"https://example.invalid/runs/{run_id}",
                        "headSha": "main-sha",
                        "status": "completed",
                        "conclusion": "success",
                    },
                }

            cto_autonomous_delivery.run = fake_run
            cto_autonomous_delivery.dispatch_workflow = fake_dispatch
            cto_autonomous_delivery.time.sleep = lambda _seconds: None
            try:
                with self.patched_delivery_runtime(tmp, [ready, conflict]) as queue_path:
                    result = cto_autonomous_delivery.finalize_latest(execute=True, wait=True, smoke=True)
                    queue = json.loads(queue_path.read_text(encoding="utf-8"))
            finally:
                cto_autonomous_delivery.run = original_run
                cto_autonomous_delivery.dispatch_workflow = original_dispatch
                cto_autonomous_delivery.time.sleep = original_sleep

        by_id = {task["id"]: task for task in queue["tasks"]}
        self.assertEqual(result["status"], "DEPLOYED")
        self.assertEqual(result["task_id"], "TASK-READY-NEXT")
        self.assertEqual(result["skipped"][0]["task_id"], "TASK-CONFLICT-FIRST")
        self.assertEqual(by_id["TASK-CONFLICT-FIRST"]["delivery_level"], "PR_CONFLICT")
        self.assertEqual(by_id["TASK-CONFLICT-FIRST"]["deployment_status"], "MERGE_CONFLICT")
        self.assertFalse(by_id["TASK-CONFLICT-FIRST"]["worker_eligible"])
        self.assertEqual(by_id["TASK-READY-NEXT"]["status"], TASK_STATUS_DEPLOYED)
        self.assertEqual(by_id["TASK-READY-NEXT"]["deploy_run_id"], "100")
        self.assertEqual(by_id["TASK-READY-NEXT"]["smoke_run_id"], "101")

    def test_failed_merge_rechecks_and_marks_already_merged(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = self.deployable_task("TASK-MERGE-RACE")
            task["status"] = TASK_STATUS_DONE
            task["repo_applied"] = False
            task["branch_merged"] = False
            task["delivery_level"] = "PR_READY"
            task["pull_request_number"] = 61
            original_run = cto_autonomous_delivery.run
            calls: list[list[str]] = []

            def fake_run(args, cwd=None, timeout=300):
                calls.append(args)
                if args[:3] == ["gh", "pr", "merge"]:
                    return {
                        "ok": False,
                        "returncode": 1,
                        "stdout": "/usr/bin/git: exit status 1",
                        "stderr": "",
                        "cmd": "gh pr merge 61 --squash",
                    }
                return {
                    "ok": True,
                    "returncode": 0,
                    "stdout": json.dumps(
                        {
                            "number": 61,
                            "url": "https://example.invalid/pr/61",
                            "state": "MERGED" if any(call[:3] == ["gh", "pr", "merge"] for call in calls) else "OPEN",
                            "isDraft": False,
                            "mergeStateStatus": "UNKNOWN",
                            "headRefName": "worker/task",
                            "baseRefName": "main",
                            "mergeCommit": {"oid": "abc123"},
                        }
                    ),
                    "stderr": "",
                    "cmd": "gh pr view 61",
                }

            cto_autonomous_delivery.run = fake_run
            try:
                with self.patched_delivery_runtime(tmp, [task]) as queue_path:
                    result = cto_autonomous_delivery.merge_pr_task("TASK-MERGE-RACE", execute=True)
                    queue = json.loads(queue_path.read_text(encoding="utf-8"))
            finally:
                cto_autonomous_delivery.run = original_run

        updated = queue["tasks"][0]
        self.assertEqual(result["status"], "ALREADY_MERGED")
        self.assertTrue(updated["repo_applied"])
        self.assertTrue(updated["branch_merged"])
        self.assertEqual(updated["delivery_level"], "READY_FOR_DEPLOY")
        self.assertEqual(updated["merged_commit"], "abc123")

    def test_failed_merge_git_exit_status_marks_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = self.deployable_task("TASK-MERGE-GIT-EXIT")
            task["status"] = TASK_STATUS_DONE
            task["repo_applied"] = False
            task["branch_merged"] = False
            task["delivery_level"] = "PR_READY"
            task["pull_request_number"] = 62
            original_run = cto_autonomous_delivery.run

            def fake_run(args, cwd=None, timeout=300):
                if args[:3] == ["gh", "pr", "merge"]:
                    return {
                        "ok": False,
                        "returncode": 1,
                        "stdout": "/usr/bin/git: exit status 1",
                        "stderr": "",
                        "cmd": "gh pr merge 62 --squash",
                    }
                return {
                    "ok": True,
                    "returncode": 0,
                    "stdout": json.dumps(
                        {
                            "number": 62,
                            "url": "https://example.invalid/pr/62",
                            "state": "OPEN",
                            "isDraft": False,
                            "mergeStateStatus": "UNKNOWN",
                            "headRefName": "worker/task",
                            "baseRefName": "main",
                            "mergeCommit": None,
                        }
                    ),
                    "stderr": "",
                    "cmd": "gh pr view 62",
                }

            cto_autonomous_delivery.run = fake_run
            try:
                with self.patched_delivery_runtime(tmp, [task]) as queue_path:
                    result = cto_autonomous_delivery.merge_pr_task("TASK-MERGE-GIT-EXIT", execute=True)
                    queue = json.loads(queue_path.read_text(encoding="utf-8"))
            finally:
                cto_autonomous_delivery.run = original_run

        updated = queue["tasks"][0]
        self.assertEqual(result["status"], "PR_NOT_MERGEABLE")
        self.assertEqual(updated["delivery_level"], "PR_CONFLICT")
        self.assertEqual(updated["deployment_status"], "MERGE_CONFLICT")
        self.assertEqual(updated["merge_blocked_reason"], "merge_command_git_exit_status_1")

    def test_successful_deploy_and_smoke_runs_for_same_commit_are_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = self.deployable_task("TASK-DEDUPE")
            original_main_head = cto_autonomous_delivery.main_head
            original_workflow_runs = cto_autonomous_delivery.workflow_runs
            requested: list[str] = []

            def fake_workflow_runs(workflow):
                requested.append(workflow)
                run_id = "200" if workflow == cto_autonomous_delivery.DEPLOY_WORKFLOW else "201"
                return {
                    "ok": True,
                    "runs": [
                        {
                            "databaseId": run_id,
                            "url": f"https://example.invalid/runs/{run_id}",
                            "headSha": "origin-main-sha",
                            "status": "completed",
                            "conclusion": "success",
                        }
                    ],
                }

            cto_autonomous_delivery.main_head = lambda: "origin-main-sha"
            cto_autonomous_delivery.workflow_runs = fake_workflow_runs
            try:
                with self.patched_delivery_runtime(tmp, [task]) as queue_path:
                    result = cto_autonomous_delivery.deploy_task("TASK-DEDUPE", execute=True, wait=False, smoke=True)
                    queue = json.loads(queue_path.read_text(encoding="utf-8"))
            finally:
                cto_autonomous_delivery.main_head = original_main_head
                cto_autonomous_delivery.workflow_runs = original_workflow_runs

        updated = queue["tasks"][0]
        self.assertEqual(result["status"], "DEPLOYED")
        self.assertEqual(result["deploy"]["status"], "WORKFLOW_SUCCESS_REUSED")
        self.assertEqual(result["smoke"]["status"], "WORKFLOW_SUCCESS_REUSED")
        self.assertEqual(requested, [cto_autonomous_delivery.DEPLOY_WORKFLOW, cto_autonomous_delivery.SMOKE_WORKFLOW])
        self.assertEqual(updated["deploy_run_id"], "200")
        self.assertEqual(updated["deploy_run_url"], "https://example.invalid/runs/200")
        self.assertEqual(updated["deploy_commit"], "origin-main-sha")
        self.assertEqual(updated["smoke_run_id"], "201")
        self.assertEqual(updated["smoke_run_url"], "https://example.invalid/runs/201")
        self.assertEqual(updated["smoke_commit"], "origin-main-sha")

    def test_deploy_success_without_successful_smoke_is_not_deployed(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = self.deployable_task("TASK-SMOKE-PENDING")
            original_dispatch = cto_autonomous_delivery.dispatch_workflow
            calls: list[str] = []

            def fake_dispatch(workflow, wait=False):
                calls.append(workflow)
                if workflow == cto_autonomous_delivery.DEPLOY_WORKFLOW:
                    return {
                        "ok": True,
                        "status": "WORKFLOW_SUCCESS_REUSED",
                        "run": {
                            "databaseId": "300",
                            "url": "https://example.invalid/runs/300",
                            "headSha": "origin-main-sha",
                            "status": "completed",
                            "conclusion": "success",
                        },
                    }
                return {
                    "ok": True,
                    "status": "WORKFLOW_DISPATCHED",
                    "run": {
                        "databaseId": "301",
                        "url": "https://example.invalid/runs/301",
                        "headSha": "origin-main-sha",
                        "status": "queued",
                        "conclusion": "",
                    },
                }

            cto_autonomous_delivery.dispatch_workflow = fake_dispatch
            try:
                with self.patched_delivery_runtime(tmp, [task]) as queue_path:
                    result = cto_autonomous_delivery.deploy_task("TASK-SMOKE-PENDING", execute=True, wait=False, smoke=True)
                    queue = json.loads(queue_path.read_text(encoding="utf-8"))
            finally:
                cto_autonomous_delivery.dispatch_workflow = original_dispatch

        updated = queue["tasks"][0]
        self.assertEqual(result["status"], "SMOKE_IN_PROGRESS")
        self.assertEqual(calls, [cto_autonomous_delivery.DEPLOY_WORKFLOW, cto_autonomous_delivery.SMOKE_WORKFLOW])
        self.assertEqual(updated["status"], TASK_STATUS_DONE)
        self.assertEqual(updated["deployment_status"], "DEPLOY_IN_PROGRESS")
        self.assertFalse(updated.get("production_deployed", False))
        self.assertEqual(updated["deploy_run_id"], "300")
        self.assertEqual(updated["smoke_run_id"], "301")

    def test_execute_deploy_without_smoke_does_not_mark_deployed(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = self.deployable_task("TASK-NO-SMOKE")
            with self.patched_delivery_runtime(tmp, [task]) as queue_path:
                result = cto_autonomous_delivery.deploy_task("TASK-NO-SMOKE", execute=True, smoke=False)
                queue = json.loads(queue_path.read_text(encoding="utf-8"))

        self.assertEqual(result["status"], "SMOKE_REQUIRED_FOR_DEPLOYED")
        self.assertEqual(queue["tasks"][0]["status"], TASK_STATUS_DONE)
        self.assertNotEqual(queue["tasks"][0]["status"], TASK_STATUS_DEPLOYED)
        self.assertFalse(queue["tasks"][0].get("production_deployed", False))
        self.assertEqual(queue["tasks"][0]["deployment_status"], "DEPLOY_RETRY_REQUIRED")

    def test_choose_worker_prefers_least_active_worker(self):
        queue = {
            "tasks": [
                {
                    "id": "TASK-1",
                    "status": "RUNNING",
                    "source": "cto",
                    "worker_eligible": True,
                    "assigned_worker": "worker-1",
                },
                {
                    "id": "TASK-2",
                    "status": "QUEUED",
                    "source": "cto",
                    "worker_eligible": True,
                    "assigned_worker": "worker-2",
                },
            ]
        }

        self.assertEqual(cto_autonomous_delivery.choose_worker(queue), "worker-3")


class BacklogDispatcherModelTest(unittest.TestCase):
    def setUp(self):
        self._logs_tmp = tempfile.TemporaryDirectory()
        self._original_lifecycle_logs = lifecycle_manager.LOGS
        lifecycle_manager.LOGS = Path(self._logs_tmp.name) / "logs"

    def tearDown(self):
        lifecycle_manager.LOGS = self._original_lifecycle_logs
        self._logs_tmp.cleanup()

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

    def test_proposal_done_prefers_repo_apply_child(self):
        queue = {"tasks": [{"id": "PARENT", "status": TASK_STATUS_PROPOSAL_DONE, "risk": "low", "title": "safe app work"}]}
        child = lifecycle_manager.create_repo_apply_task(queue, queue["tasks"][0])

        self.assertEqual(child["dispatcher_mode"], "apply")
        self.assertEqual(child["execution_mode"], "repo_apply")
        self.assertTrue(child["repo_apply_allowed"])
        self.assertEqual(queue["tasks"][0]["repo_apply_child"], child["id"])

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

    def test_active_mode_selects_multiple_assigned_workers(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "task_queue.json"
            path.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "id": "TASK-1",
                                "status": "RUNNING",
                                "source": "cto",
                                "worker_eligible": True,
                                "assigned_worker": "worker-1",
                            },
                            {
                                "id": "TASK-2",
                                "status": "PENDING",
                                "source": "cto",
                                "worker_eligible": True,
                                "assigned_worker": "worker-2",
                            },
                            {
                                "id": "TASK-3",
                                "status": "QUEUED",
                                "source": "cto",
                                "worker_eligible": True,
                                "assigned_worker": "worker-3",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            original = lifecycle_manager.QUEUE_PATH
            lifecycle_manager.QUEUE_PATH = path
            try:
                selected = lifecycle_manager.selected_workers_for_active_mode()
            finally:
                lifecycle_manager.QUEUE_PATH = original

        self.assertEqual(selected, ["worker-1", "worker-2", "worker-3"])

    def test_active_mode_uses_idle_worker_when_pending_is_assigned_to_busy_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "task_queue.json"
            path.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "id": "TASK-1",
                                "status": "RUNNING",
                                "source": "cto",
                                "worker_eligible": True,
                                "assigned_worker": "worker-1",
                            },
                            {
                                "id": "TASK-2",
                                "status": "QUEUED",
                                "source": "cto",
                                "worker_eligible": True,
                                "assigned_worker": "worker-1",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            original = lifecycle_manager.QUEUE_PATH
            lifecycle_manager.QUEUE_PATH = path
            try:
                selected = lifecycle_manager.selected_workers_for_active_mode()
            finally:
                lifecycle_manager.QUEUE_PATH = original

        self.assertEqual(selected, ["worker-1", "worker-2"])

    def test_no_standard_candidate_uses_autonomous_backlog_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            state = runtime / "state"
            state.mkdir()
            queue_path = state / "task_queue.json"
            system_state_path = state / "system_state.json"
            queue_path.write_text(
                json.dumps({"tasks": [{"id": "DONE-PARENT", "status": TASK_STATUS_DONE, "risk": "low"}]}),
                encoding="utf-8",
            )

            calls = []

            def fake_start_next_backlog(execute=False):
                calls.append(execute)
                return {
                    "ok": True,
                    "status": "BACKLOG_CONTINUATION_CREATED",
                    "parent_task_id": "DONE-PARENT",
                    "child_task": {"id": "CHILD"},
                }

            originals = (
                lifecycle_manager.QUEUE_PATH,
                lifecycle_manager.SYSTEM_STATE_PATH,
                lifecycle_manager.cto_autonomous_delivery.start_next_backlog,
            )
            lifecycle_manager.QUEUE_PATH = queue_path
            lifecycle_manager.SYSTEM_STATE_PATH = system_state_path
            lifecycle_manager.cto_autonomous_delivery.start_next_backlog = fake_start_next_backlog
            try:
                created = lifecycle_manager.ensure_single_backlog_task()
            finally:
                (
                    lifecycle_manager.QUEUE_PATH,
                    lifecycle_manager.SYSTEM_STATE_PATH,
                    lifecycle_manager.cto_autonomous_delivery.start_next_backlog,
                ) = originals

            system_state = json.loads(system_state_path.read_text(encoding="utf-8"))

        self.assertTrue(created)
        self.assertEqual(calls, [True])
        self.assertEqual(system_state["backlog_dispatcher_last_result"], "autonomous_backlog_created")
        self.assertEqual(system_state["backlog_dispatcher_last_child"], "CHILD")

    def test_backlog_fallback_can_fill_parallel_capacity(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            state = runtime / "state"
            state.mkdir()
            queue_path = state / "task_queue.json"
            system_state_path = state / "system_state.json"
            queue_path.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "id": "ACTIVE",
                                "status": "RUNNING",
                                "source": "cto",
                                "worker_eligible": True,
                                "assigned_worker": "worker-1",
                            },
                            {"id": "DONE-PARENT", "status": TASK_STATUS_DONE, "risk": "low"},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            calls = []

            def fake_start_next_backlog(execute=False):
                calls.append(execute)
                return {
                    "ok": True,
                    "status": "BACKLOG_CONTINUATION_CREATED",
                    "parent_task_id": "DONE-PARENT",
                    "child_task": {"id": "CHILD"},
                }

            originals = (
                lifecycle_manager.QUEUE_PATH,
                lifecycle_manager.SYSTEM_STATE_PATH,
                lifecycle_manager.cto_autonomous_delivery.start_next_backlog,
            )
            lifecycle_manager.QUEUE_PATH = queue_path
            lifecycle_manager.SYSTEM_STATE_PATH = system_state_path
            lifecycle_manager.cto_autonomous_delivery.start_next_backlog = fake_start_next_backlog
            try:
                created = lifecycle_manager.ensure_single_backlog_task()
            finally:
                (
                    lifecycle_manager.QUEUE_PATH,
                    lifecycle_manager.SYSTEM_STATE_PATH,
                    lifecycle_manager.cto_autonomous_delivery.start_next_backlog,
                ) = originals

        self.assertTrue(created)
        self.assertEqual(calls, [True])

    def test_validation_can_run_while_workers_remain_active(self):
        calls = []

        originals = (
            lifecycle_manager.VALIDATION_INTERVAL_SECONDS,
            lifecycle_manager.validation_candidate_count,
            lifecycle_manager.run_validation_engine,
            lifecycle_manager.time.monotonic,
        )
        lifecycle_manager.VALIDATION_INTERVAL_SECONDS = 60
        lifecycle_manager.validation_candidate_count = lambda: 3
        lifecycle_manager.run_validation_engine = lambda: calls.append("run") or True
        lifecycle_manager.time.monotonic = lambda: 61.0
        try:
            last_validation, changed = lifecycle_manager.maybe_run_validation(0.0)
        finally:
            (
                lifecycle_manager.VALIDATION_INTERVAL_SECONDS,
                lifecycle_manager.validation_candidate_count,
                lifecycle_manager.run_validation_engine,
                lifecycle_manager.time.monotonic,
            ) = originals

        self.assertTrue(changed)
        self.assertEqual(last_validation, 61.0)
        self.assertEqual(calls, ["run"])

    def test_validation_respects_interval_between_runs(self):
        calls = []

        originals = (
            lifecycle_manager.VALIDATION_INTERVAL_SECONDS,
            lifecycle_manager.validation_candidate_count,
            lifecycle_manager.run_validation_engine,
            lifecycle_manager.time.monotonic,
        )
        lifecycle_manager.VALIDATION_INTERVAL_SECONDS = 60
        lifecycle_manager.validation_candidate_count = lambda: 3
        lifecycle_manager.run_validation_engine = lambda: calls.append("run") or True
        lifecycle_manager.time.monotonic = lambda: 119.0
        try:
            last_validation, changed = lifecycle_manager.maybe_run_validation(60.0)
        finally:
            (
                lifecycle_manager.VALIDATION_INTERVAL_SECONDS,
                lifecycle_manager.validation_candidate_count,
                lifecycle_manager.run_validation_engine,
                lifecycle_manager.time.monotonic,
            ) = originals

        self.assertFalse(changed)
        self.assertEqual(last_validation, 60.0)
        self.assertEqual(calls, [])


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
                "- irreversible migration\n\n"
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

    def test_ready_proposal_becomes_proposal_done_only_with_pipeline_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = self.write_ready_runtime(tmp, pipeline_status="PASS")
            result = task_validation_engine.validate_ready_tasks(runtime, limit=5)
            queue = json.loads((runtime / "state" / "task_queue.json").read_text(encoding="utf-8"))

        self.assertEqual(result["changed"], 1)
        self.assertEqual(queue["tasks"][0]["status"], TASK_STATUS_PROPOSAL_DONE)
        self.assertEqual(queue["tasks"][0]["validation_status"], "PASS")
        self.assertEqual(queue["tasks"][0]["pipeline_status"], "PASS")
        self.assertEqual(queue["tasks"][0]["deployment_status"], "APPLY_REQUIRED")
        self.assertFalse(queue["tasks"][0]["production_deployed"])

    def test_ready_repo_applied_task_can_be_done_with_pipeline_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = self.write_ready_runtime(tmp, pipeline_status="PASS")
            queue_path = runtime / "state" / "task_queue.json"
            queue = json.loads(queue_path.read_text(encoding="utf-8"))
            queue["tasks"][0]["repo_applied"] = True
            queue_path.write_text(json.dumps(queue), encoding="utf-8")
            result = task_validation_engine.validate_ready_tasks(runtime, limit=5)
            queue = json.loads(queue_path.read_text(encoding="utf-8"))

        self.assertEqual(result["changed"], 1)
        self.assertEqual(queue["tasks"][0]["status"], TASK_STATUS_DONE)
        self.assertEqual(queue["tasks"][0]["deployment_status"], "READY_FOR_DEPLOY")

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
        self.assertEqual(queue["tasks"][0]["status"], TASK_STATUS_PROPOSAL_DONE)
        self.assertEqual(queue["tasks"][0]["critical_operation_findings"], [])

    def test_risk_review_boundary_examples_do_not_require_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = self.write_ready_runtime(tmp, pipeline_status="PASS")
            workspace = next((runtime / "workspaces").glob("worker_worker-1_TASK-VAL_*"))
            (workspace / "RISK_REVIEW.md").write_text(
                "# RISK_REVIEW\n\n"
                "## Dokunulmayacak Alanlar\n\n"
                "- Production deploy.\n"
                "- IAM, billing, DNS, firewall.\n"
                "- Database destructive islemleri.\n"
                "- Secret, env, token, private key ve credential rotation.\n\n"
                "## Riskler\n\n"
                "- yuksek risk: secret, IAM, deploy, DNS, firewall, database destructive.\n"
                "- `gcloud projects add-iam-policy-binding` high risk donmeli.\n",
                encoding="utf-8",
            )
            result = task_validation_engine.validate_ready_tasks(runtime, limit=5)
            queue = json.loads((runtime / "state" / "task_queue.json").read_text(encoding="utf-8"))

        self.assertEqual(result["changed"], 1)
        self.assertEqual(queue["tasks"][0]["status"], TASK_STATUS_PROPOSAL_DONE)
        self.assertEqual(queue["tasks"][0]["critical_operation_findings"], [])


class SupervisorCliCompletionTest(unittest.TestCase):
    def run_complete_task(self, tmp, task):
        runtime = Path(tmp)
        state = runtime / "state"
        logs = runtime / "logs"
        reports = runtime / "reports"
        state.mkdir()
        logs.mkdir()
        reports.mkdir()
        (state / "task_queue.json").write_text(json.dumps({"tasks": [task]}), encoding="utf-8")
        (state / "workers.json").write_text(json.dumps({"workers": [{"id": "worker-1", "status": "RUNNING", "current_task": task["id"]}]}), encoding="utf-8")

        originals = (supervisor_cli.STATE_DIR, supervisor_cli.LOG_DIR, supervisor_cli.REPORT_DIR)
        supervisor_cli.STATE_DIR = state
        supervisor_cli.LOG_DIR = logs
        supervisor_cli.REPORT_DIR = reports
        try:
            args = type("Args", (), {"task_id": task["id"], "result": "manual"})()
            with contextlib.redirect_stdout(io.StringIO()):
                supervisor_cli.complete_task(args)
        finally:
            supervisor_cli.STATE_DIR, supervisor_cli.LOG_DIR, supervisor_cli.REPORT_DIR = originals

        return json.loads((state / "task_queue.json").read_text(encoding="utf-8"))

    def test_cli_complete_task_without_gates_waits_for_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue = self.run_complete_task(
                tmp,
                {
                    "id": "TASK-MANUAL",
                    "status": "RUNNING",
                    "validation_status": "PENDING",
                    "pipeline_status": "NOT_RUN",
                },
            )

        self.assertEqual(queue["tasks"][0]["status"], TASK_STATUS_READY_FOR_VALIDATION)
        self.assertEqual(queue["tasks"][0]["result"], "manual_completion_requires_validation_pipeline_pass")

    def test_cli_complete_task_with_gates_can_mark_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue = self.run_complete_task(
                tmp,
                {
                    "id": "TASK-MANUAL",
                    "status": "RUNNING",
                    "validation_status": "PASS",
                    "pipeline_status": "PASS",
                },
            )

        self.assertEqual(queue["tasks"][0]["status"], TASK_STATUS_DONE)
        self.assertEqual(queue["tasks"][0]["result"], "manual")


class SystemRepairControlsTest(unittest.TestCase):
    def test_no_change_status_is_terminal_alias(self):
        self.assertEqual(normalize_status("no change"), TASK_STATUS_NO_CHANGE)
        self.assertEqual(normalize_status("noop"), TASK_STATUS_NO_CHANGE)

    def test_critical_policy_ignores_turkish_negative_safety_phrases(self):
        safe_text = "\n".join(
            [
                "Google Ads API mutate islemi yapma.",
                "Secret okuma ve token/private key gosterme.",
                "IAM, billing, DNS ve firewall degistirme.",
                "Production deploy yapma; mutate kapali.",
            ]
        )
        self.assertEqual(critical_operation_policy.critical_operation_findings(safe_text), [])

    def test_lifecycle_pending_count_excludes_assigned_and_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            state = runtime / "state"
            state.mkdir()
            queue_path = state / "task_queue.json"
            queue_path.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {"id": "P", "status": "PENDING", "risk": "low"},
                            {"id": "Q", "status": "QUEUED", "risk": "low"},
                            {"id": "A", "status": "ASSIGNED", "risk": "low"},
                            {"id": "R", "status": "RUNNING", "risk": "low"},
                            {"id": "F", "status": "FAILED_RETRYABLE", "risk": "low"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            original = lifecycle_manager.QUEUE_PATH
            lifecycle_manager.QUEUE_PATH = queue_path
            try:
                pending, running, active = lifecycle_manager.queue_counts()
            finally:
                lifecycle_manager.QUEUE_PATH = original

        self.assertEqual(pending, 2)
        self.assertEqual(running, 1)
        self.assertEqual(active, 4)

    def test_owner_cleanup_archives_and_empties_queue(self):
        spec = importlib.util.spec_from_file_location(
            "queue_owner_cleanup_test_module",
            ROOT / "scripts" / "queue_owner_cleanup.py",
        )
        queue_owner_cleanup = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(queue_owner_cleanup)

        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            state = runtime / "state"
            state.mkdir()
            (runtime / "reports").mkdir()
            (state / "task_queue.json").write_text(
                json.dumps(
                    {
                        "tasks": [
                            {"id": "TASK-1", "status": "RUNNING", "risk": "low"},
                            {"id": "TASK-2", "status": "FAILED_RETRYABLE", "risk": "low"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (state / "workers.json").write_text(
                json.dumps({"workers": [{"id": "worker-1", "status": "RUNNING", "current_task": "TASK-1"}]}),
                encoding="utf-8",
            )
            (state / "system_state.json").write_text(json.dumps({"phase": "BUSY"}), encoding="utf-8")

            archive = runtime / "archives" / "repair"
            payload = queue_owner_cleanup.cleanup(runtime, archive, execute=True)

            queue = json.loads((state / "task_queue.json").read_text(encoding="utf-8"))
            workers = json.loads((state / "workers.json").read_text(encoding="utf-8"))
            system_state = json.loads((state / "system_state.json").read_text(encoding="utf-8"))
            archive_snapshot_exists = (archive / "task_queue_before_owner_cleanup.json").exists()

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["original_task_count"], 2)
        self.assertEqual(queue["tasks"], [])
        self.assertEqual(queue["cleanup_status"], "CANCELLED_BY_OWNER_CLEANUP")
        self.assertEqual(workers["workers"][0]["status"], "IDLE")
        self.assertEqual(system_state["system_state"], "READY_FOR_NEW_TASKS")
        self.assertTrue(archive_snapshot_exists)


if __name__ == "__main__":
    unittest.main()
