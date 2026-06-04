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
    action_result_watcher,
    codex_quality_gate,
    critical_operation_policy,
    cto_autonomous_delivery,
    cto_task_router,
    direct_cto_action_mode,
    direct_cto_job_recovery,
    lifecycle_manager,
    production_deploy_controller,
    production_environment_manager,
    production_readiness_suite,
    progress_aware_runner,
    direct_cto_async_job,
    direct_cto_progress_watcher,
    supervisor_cli,
    task_recovery_engine,
    task_validation_engine,
    telegram_asset_intake,
    telegram_bridge,
    telegram_direct_cto,
    telegram_direct_cto_simulator,
    telegram_health_watcher,
    worker_runner,
)
from supervisor.task_status_constants import (  # noqa: E402
    TASK_STATUS_APPROVAL_REQUIRED,
    TASK_STATUS_BLOCKED,
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
    TASK_STATUS_VALIDATION_FAILED,
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

import pipeline_flow  # noqa: E402


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

    def test_router_subtasks_get_dispatch_contract_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = cto_task_router.submit_task(
                root=Path(tmp),
                source="dashboard",
                title="Worker Dispatch v2",
                message="worker queue pipeline",
                risk="medium",
                split=True,
            )

        parent = result["task"]
        subtasks = result["subtasks"]

        self.assertEqual(parent["root_task_id"], parent["id"])
        self.assertEqual(parent["dispatch_id"], parent["id"])
        self.assertEqual(parent["attempt"], 1)
        self.assertEqual(parent["max_attempts"], 1)
        self.assertIsNone(parent["claimed_at"])
        self.assertIsNone(parent["finished_at"])
        self.assertEqual(len(subtasks), 3)
        for subtask in subtasks:
            self.assertEqual(subtask["root_task_id"], parent["id"])
            self.assertEqual(subtask["dispatch_id"], subtask["id"])
            self.assertEqual(subtask["attempt"], 1)
            self.assertEqual(subtask["max_attempts"], 1)
            self.assertEqual(subtask["last_error_code"], "")
            self.assertIsNone(subtask["claimed_at"])
            self.assertIsNone(subtask["finished_at"])

    def test_dashboard_cleanup_request_is_not_split_into_readiness_subtasks(self):
        message = (
            "dashboarddaki Raporlar, GitHub Senkronizasyonu, Profil, Kalite Kapıları, "
            "Deploy Komutları, Pipeline Gözlemi ve Production Pipeline alanlarını kaldıralım."
        )
        with tempfile.TemporaryDirectory() as tmp:
            result = cto_task_router.submit_task(
                root=Path(tmp),
                source="telegram",
                title="Dashboard Alan Temizliği",
                message=message,
                risk="medium",
                split=None,
            )

        self.assertEqual(result["subtasks"], [])

    def test_telegram_dashboard_cleanup_metadata_uses_dashboard_title(self):
        message = (
            "dashboarddaki Raporlar, Son Hata ve Çözüm Önerisi, GitHub Senkronizasyonu, "
            "Production Pipeline ve Görev Kuyruğu alanlarını kaldıralım."
        )

        meta = telegram_direct_cto.classify_job_metadata(message)

        self.assertEqual(meta["name"], "Dashboard Alan Temizliği")
        self.assertNotEqual(meta["name"], "Production Readiness Analizi")

    def test_telegram_task_list_ui_metadata_is_not_production_readiness(self):
        message = (
            "Görevler menüsündeki görevler sürekli yer değiştiriyor. Çalışıyor durumları üstte olmalı. "
            "Canlıda olanlar ana listede gösterilmemeli ve checkbox ile açılmalı. "
            "Filtreler seçildiğinde sayfa yenilenip filtre kapanıyor."
        )

        meta = telegram_direct_cto.classify_job_metadata(message)

        self.assertEqual(meta["name"], "Dashboard Görev Listesi Düzeni")
        self.assertNotEqual(meta["name"], "Production Readiness Analizi")

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

    def test_repo_apply_report_sections_include_controlled_apply_notes(self):
        sections = worker_runner.repo_apply_control_report_sections(
            risk="medium",
            branch="worker/test-controlled-apply",
            commit_files=["supervisor/worker_runner.py"],
            unsafe_files=[],
            secret_findings=[],
            validation_status="PASS",
            pipeline_status="PASS",
        )
        text = "\n".join(sections)

        self.assertIn("## Controlled Apply Checklist", text)
        self.assertIn("- Patch scope files: 1", text)
        self.assertIn("- Diff review: PASS", text)
        self.assertIn("- Secret scan: PASS", text)
        self.assertIn("- Local pipeline: PASS", text)
        self.assertIn("- Production deploy: NOT_RUN", text)
        self.assertIn("- Critical operations: blocked_by_policy", text)
        self.assertIn("## Rollback Note", text)
        self.assertIn("delete branch `worker/test-controlled-apply`", text)

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
            self.assertEqual(report["retry_simulation"]["status"], "not_run")

    def test_quality_gate_retry_simulation_records_attempt_fields(self):
        outcomes = [
            {
                "ok": False,
                "returncode": 1,
                "duration_seconds": 0.01,
                "stderr": "AssertionError: failed",
                "stdout": "",
            },
            {
                "ok": True,
                "returncode": 0,
                "duration_seconds": 0.02,
                "stderr": "",
                "stdout": "",
            },
        ]

        def fake_runner(_root, _command, _timeout):
            return outcomes.pop(0)

        report = codex_quality_gate.build_quality_gate_retry_simulation_report(
            ROOT,
            command_specs=[
                {
                    "name": "unit_test",
                    "command": ["python3", "-m", "unittest", "tests.test_runtime_status_model"],
                    "timeout": 120,
                }
            ],
            generated_at="2026-06-04T07:12:00+00:00",
            runner=fake_runner,
        )

        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["flaky_commands"], ["unit_test"])
        self.assertEqual(len(report["attempts"]), 2)
        for attempt in report["attempts"]:
            self.assertEqual(
                set(attempt),
                {
                    "command",
                    "attempt",
                    "exit_code",
                    "duration_seconds",
                    "result",
                    "failure_hint",
                    "retry_changed_result",
                },
            )
            self.assertTrue(attempt["retry_changed_result"])
        self.assertEqual(report["attempts"][0]["attempt"], 1)
        self.assertEqual(report["attempts"][0]["exit_code"], 1)
        self.assertEqual(report["attempts"][0]["result"], "fail")
        self.assertEqual(report["attempts"][0]["failure_hint"], "test_failure")
        self.assertEqual(report["attempts"][1]["attempt"], 2)
        self.assertEqual(report["attempts"][1]["exit_code"], 0)
        self.assertEqual(report["attempts"][1]["result"], "pass")

    def test_standard_quality_report_embeds_retry_simulation_non_blocking(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / "state"
            reports = root / "reports"
            state.mkdir()
            reports.mkdir()
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
            (reports / "quality-gate-retry-simulation.json").write_text(
                json.dumps(
                    {
                        "status": "fail",
                        "dry_run": True,
                        "non_blocking": True,
                        "attempts": [
                            {
                                "command": "python3 supervisor/codex_quality_gate.py json-check",
                                "attempt": 1,
                                "exit_code": 1,
                                "duration_seconds": 0.01,
                                "result": "fail",
                                "failure_hint": "nonzero_exit",
                                "retry_changed_result": False,
                            }
                        ],
                        "commands": [],
                    }
                ),
                encoding="utf-8",
            )

            report = codex_quality_gate.build_standard_quality_report(root)
            summary = codex_quality_gate.render_standard_quality_summary(report)

        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["retry_simulation"]["status"], "fail")
        self.assertTrue(report["retry_simulation"]["non_blocking"])
        self.assertIn("## Retry Simulation", summary)
        self.assertIn("python3 supervisor/codex_quality_gate.py json-check attempt 1", summary)

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

    def test_worker_does_not_claim_terminal_dispatch_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "task_queue.json"
            queue_path.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "id": "TASK-TERMINAL",
                                "status": TASK_STATUS_READY_FOR_VALIDATION,
                                "source": "cto",
                                "risk": "low",
                                "assigned_worker": "worker-1",
                                "worker_eligible": True,
                            }
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
        self.assertEqual(payload["tasks"][0]["status"], TASK_STATUS_READY_FOR_VALIDATION)

    def test_worker_claim_records_dispatch_claim_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "task_queue.json"
            queue_path.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "id": "TASK-CLAIM",
                                "status": "QUEUED",
                                "source": "cto",
                                "risk": "low",
                                "assigned_worker": "",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            original_queue = worker_runner.QUEUE_PATH
            worker_runner.QUEUE_PATH = queue_path
            try:
                claimed = worker_runner.claim_task("worker-2")
            finally:
                worker_runner.QUEUE_PATH = original_queue
            payload = json.loads(queue_path.read_text(encoding="utf-8"))

        self.assertIsNotNone(claimed)
        self.assertEqual(claimed["status"], TASK_STATUS_RUNNING)
        self.assertEqual(claimed["assigned_worker"], "worker-2")
        self.assertEqual(claimed["worker_id"], "worker-2")
        self.assertEqual(claimed["root_task_id"], "TASK-CLAIM")
        self.assertEqual(claimed["dispatch_id"], "TASK-CLAIM")
        self.assertEqual(claimed["attempt"], 1)
        self.assertEqual(claimed["max_attempts"], 1)
        self.assertTrue(claimed["claimed_at"])
        self.assertEqual(claimed["claimed_at"], claimed["started_at"])
        self.assertEqual(payload["tasks"][0]["worker_id"], "worker-2")
        self.assertEqual(payload["tasks"][0]["claimed_at"], claimed["claimed_at"])

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
    def test_asset_intake_classifies_photo_caption_without_raw_file_id(self):
        caption_value = "<script>alert(1)</script> " + "token" + "=sample"
        update = {
            "update_id": 101,
            "message": {
                "message_id": 7,
                "chat": {"id": 12345},
                "from": {"id": 67890, "username": "tester"},
                "caption": caption_value,
                "photo": [
                    {
                        "file_id": "SMALL_PHOTO_FILE_ID",
                        "file_unique_id": "SMALL_UNIQUE",
                        "file_size": 128,
                        "width": 90,
                        "height": 90,
                    },
                    {
                        "file_id": "RAW_PHOTO_FILE_ID_MUST_NOT_LEAK",
                        "file_unique_id": "PHOTO_UNIQUE",
                        "file_size": 2048,
                        "width": 1280,
                        "height": 720,
                    },
                ],
            },
        }

        event = telegram_asset_intake.classify_telegram_update(update)
        serialized = json.dumps(event, ensure_ascii=False)

        self.assertEqual(event["status"], "classified")
        self.assertEqual(event["message_type"], "media_with_caption")
        self.assertEqual(event["asset_type"], "photo")
        self.assertTrue(event["should_enqueue_asset"])
        self.assertEqual(event["file_unique_id"], "PHOTO_UNIQUE")
        self.assertEqual(event["idempotency_key"], "101:PHOTO_UNIQUE")
        self.assertIn("&lt;script&gt;", event["caption_sanitized"])
        self.assertIn("[REDACTED_SECRET]", event["caption_sanitized"])
        self.assertNotIn("sample", event["caption_sanitized"])
        self.assertNotIn("RAW_PHOTO_FILE_ID_MUST_NOT_LEAK", serialized)
        self.assertTrue(event["file_id_ref"].startswith("tg_file_"))

    def test_asset_intake_sanitizes_document_file_name_and_supports_edited_message(self):
        update = {
            "update_id": 102,
            "edited_message": {
                "message_id": 8,
                "chat": {"id": 12345},
                "document": {
                    "file_id": "RAW_DOCUMENT_FILE_ID_MUST_NOT_LEAK",
                    "file_unique_id": "DOC_UNIQUE",
                    "file_name": "../unsafe\x00/path.pdf",
                    "mime_type": "application/pdf",
                    "file_size": 4096,
                },
            },
        }

        event = telegram_asset_intake.classify_telegram_update(update)
        serialized = json.dumps(event, ensure_ascii=False)

        self.assertEqual(event["status"], "classified")
        self.assertEqual(event["update_key"], "edited_message")
        self.assertEqual(event["message_type"], "document")
        self.assertEqual(event["asset_type"], "document")
        self.assertEqual(event["file_name_sanitized"], "path.pdf")
        self.assertNotIn("RAW_DOCUMENT_FILE_ID_MUST_NOT_LEAK", serialized)

    def test_asset_intake_rejects_missing_file_id_and_disallowed_mime(self):
        missing_file = telegram_asset_intake.classify_telegram_update(
            {
                "update_id": 103,
                "message": {
                    "message_id": 9,
                    "chat": {"id": 12345},
                    "photo": [{"file_unique_id": "PHOTO_UNIQUE"}],
                },
            }
        )
        disallowed_mime = telegram_asset_intake.classify_telegram_update(
            {
                "update_id": 104,
                "message": {
                    "message_id": 10,
                    "chat": {"id": 12345},
                    "document": {
                        "file_id": "RAW_EXE_FILE_ID_MUST_NOT_LEAK",
                        "file_unique_id": "EXE_UNIQUE",
                        "file_name": "tool.exe",
                        "mime_type": "application/x-msdownload",
                    },
                },
            }
        )

        self.assertEqual(missing_file["status"], "rejected")
        self.assertEqual(missing_file["reject_reason"], "missing_file_id")
        self.assertFalse(missing_file["should_enqueue_asset"])
        self.assertEqual(disallowed_mime["status"], "rejected")
        self.assertEqual(disallowed_mime["reject_reason"], "mime_type_not_allowed")
        self.assertNotIn("RAW_EXE_FILE_ID_MUST_NOT_LEAK", json.dumps(disallowed_mime, ensure_ascii=False))

    def test_asset_intake_rejects_unsupported_media_type(self):
        event = telegram_asset_intake.classify_telegram_update(
            {
                "update_id": 105,
                "message": {
                    "message_id": 11,
                    "chat": {"id": 12345},
                    "video": {
                        "file_id": "RAW_VIDEO_FILE_ID",
                        "file_unique_id": "VIDEO_UNIQUE",
                    },
                },
            }
        )

        self.assertEqual(event["status"], "rejected")
        self.assertEqual(event["message_type"], "unsupported")
        self.assertEqual(event["unsupported_media_type"], "video")
        self.assertFalse(event["should_enqueue_asset"])

    def test_direct_cto_routes_photo_to_asset_intake_task(self):
        calls = []

        def fake_submit_task(root, source, title, message, **kwargs):
            calls.append(("submit_task", source, title, message, kwargs))
            return {"task": {"id": "TASK-ASSET"}}

        def fake_send_message(token, chat_id, text):
            calls.append(("send_message", chat_id, text))
            return True

        def fail_start_async_job(*_args, **_kwargs):
            raise AssertionError("asset intake should not start a Codex async job")

        originals = (
            telegram_direct_cto.LOGS,
            telegram_direct_cto.audit_passthrough,
            telegram_direct_cto.submit_task,
            telegram_direct_cto.send_message,
            telegram_direct_cto.start_async_job,
        )
        with tempfile.TemporaryDirectory() as tmp:
            telegram_direct_cto.LOGS = Path(tmp)
            telegram_direct_cto.audit_passthrough = lambda *args, **kwargs: {}
            telegram_direct_cto.submit_task = fake_submit_task
            telegram_direct_cto.send_message = fake_send_message
            telegram_direct_cto.start_async_job = fail_start_async_job
            try:
                telegram_direct_cto.handle_message(
                    "TOKEN",
                    "123",
                    {
                        "message_id": 12,
                        "chat": {"id": "123"},
                        "from": {"username": "tester"},
                        "caption": "lütfen incele",
                        "photo": [
                            {
                                "file_id": "RAW_HANDLER_PHOTO_FILE_ID_MUST_NOT_LEAK",
                                "file_unique_id": "HANDLER_PHOTO_UNIQUE",
                                "file_size": 1024,
                            }
                        ],
                    },
                    update_id=106,
                )
            finally:
                (
                    telegram_direct_cto.LOGS,
                    telegram_direct_cto.audit_passthrough,
                    telegram_direct_cto.submit_task,
                    telegram_direct_cto.send_message,
                    telegram_direct_cto.start_async_job,
                ) = originals

        submit = next(call for call in calls if call[0] == "submit_task")
        sent = next(call for call in calls if call[0] == "send_message")
        self.assertEqual(submit[1], "telegram")
        self.assertEqual(submit[2], "Telegram Asset Intake")
        self.assertEqual(submit[4]["risk"], "medium")
        self.assertFalse(submit[4]["worker_eligible"])
        self.assertIn("HANDLER_PHOTO_UNIQUE", submit[3])
        self.assertIn("106:HANDLER_PHOTO_UNIQUE", submit[3])
        self.assertNotIn("RAW_HANDLER_PHOTO_FILE_ID_MUST_NOT_LEAK", submit[3])
        self.assertIn("Medya alındı", sent[2])

    def test_direct_cto_rejects_unsupported_media_without_task(self):
        calls = []

        def fail_submit_task(*_args, **_kwargs):
            raise AssertionError("unsupported media must not create an intake task")

        def fake_send_message(token, chat_id, text):
            calls.append(("send_message", chat_id, text))
            return True

        originals = (
            telegram_direct_cto.LOGS,
            telegram_direct_cto.audit_passthrough,
            telegram_direct_cto.submit_task,
            telegram_direct_cto.send_message,
        )
        with tempfile.TemporaryDirectory() as tmp:
            telegram_direct_cto.LOGS = Path(tmp)
            telegram_direct_cto.audit_passthrough = lambda *args, **kwargs: {}
            telegram_direct_cto.submit_task = fail_submit_task
            telegram_direct_cto.send_message = fake_send_message
            try:
                telegram_direct_cto.handle_message(
                    "TOKEN",
                    "123",
                    {
                        "message_id": 13,
                        "chat": {"id": "123"},
                        "from": {"username": "tester"},
                        "video": {
                            "file_id": "RAW_VIDEO_FILE_ID",
                            "file_unique_id": "VIDEO_UNIQUE",
                        },
                    },
                )
            finally:
                (
                    telegram_direct_cto.LOGS,
                    telegram_direct_cto.audit_passthrough,
                    telegram_direct_cto.submit_task,
                    telegram_direct_cto.send_message,
                ) = originals

        self.assertEqual(calls[0][0], "send_message")
        self.assertIn("reddedildi", calls[0][2])

    def test_legacy_telegram_bridge_polling_disabled_when_direct_cto_owns_bot(self):
        config = {"direct_cto_mode": True, "old_bridge_disabled": True}

        self.assertFalse(
            telegram_bridge.bridge_polling_enabled(config=config, module_settings={}, env={})
        )

    def test_legacy_telegram_bridge_polling_env_can_override_for_manual_maintenance(self):
        config = {"direct_cto_mode": True, "old_bridge_disabled": True}

        self.assertTrue(
            telegram_bridge.bridge_polling_enabled(
                config=config,
                module_settings={},
                env={"CODEX_TELEGRAM_BRIDGE_POLLING_ENABLED": "1"},
            )
        )

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

    def test_development_followup_routes_to_action_async_job(self):
        result = telegram_direct_cto_simulator.simulate_case(
            "development_followup",
            "geliştirmeye başlayalım",
        )

        self.assertTrue(result["action_command"])
        self.assertEqual(result["route"], "async_job")
        self.assertEqual(result["ack_deadline_seconds"], 3)

    def test_fix_phrase_routes_to_action_async_job(self):
        result = telegram_direct_cto_simulator.simulate_case(
            "fix_followup",
            "Dashboard Pipeline Flow alt görev görünümü kendi kendine kapanıyor, bunu düzeltelim.",
        )

        self.assertTrue(result["action_command"])
        self.assertEqual(result["route"], "async_job")
        self.assertEqual(result["ack_deadline_seconds"], 3)

    def test_telegram_asset_action_mode_builds_specific_backlog(self):
        tasks = direct_cto_action_mode.build_backlog(
            "CTO ya telegram üzerinden dosya resim gibi assetler gönderebilmeliyim. geliştirme yapar mısın",
            "20260604-TEST",
        )

        self.assertEqual(
            [task["title"] for task in tasks],
            [
                "Telegram Asset Intake Backend",
                "Telegram Asset Storage And Manifest",
                "Dashboard Telegram Asset Inbox",
                "Telegram Asset Safety Tests",
            ],
        )
        self.assertEqual([task["assigned_worker"] for task in tasks], ["worker-1", "worker-3", "worker-2", "worker-4"])

    def test_dashboard_pipeline_expand_action_mode_builds_specific_backlog(self):
        tasks = direct_cto_action_mode.build_backlog(
            "dashboard pipeline flow ekranında aktif ana görev alt görevleri gösteriyor. "
            "Alt görevler görünmesi diye tıklıyorum ve görünüm kapanıyor ama birkaç saniye sonra otomatik açılıyor. "
            "Bunu düzeltelim.",
            "20260604-TEST",
        )

        self.assertEqual(
            [task["title"] for task in tasks],
            [
                "Dashboard Pipeline Expand State Root Cause",
                "Dashboard Pipeline Expand State Tests",
                "Dashboard Pipeline Live Polling Contract",
            ],
        )
        self.assertEqual([task["assigned_worker"] for task in tasks], ["worker-2", "worker-4", "worker-1"])

    def test_long_task_routes_to_async_before_local_reply(self):
        result = telegram_direct_cto_simulator.simulate_case(
            "long_multistep",
            "Uçtan uca çalış: worker ata, pipeline çalıştır, fail olursa düzelt, gate PASS olunca production'a al.",
        )

        self.assertTrue(result["long_task"])
        self.assertEqual(result["route"], "async_job")
        self.assertTrue(result["async_ack_expected"])
        self.assertEqual(result["ack_deadline_seconds"], 3)

    def test_summary_before_new_tasks_routes_async_without_router_submission(self):
        result = telegram_direct_cto_simulator.simulate_case(
            "summary_before_tasks",
            "Arşivdeki eski görevleri incele. Yeni görev açmadan önce bana kısa özet ver.",
        )

        self.assertTrue(result["summary_before_new_tasks"])
        self.assertEqual(result["route"], "async_job")
        self.assertTrue(result["async_ack_expected"])

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

    def test_handle_message_defers_router_when_summary_is_requested_before_new_tasks(self):
        calls = []

        def fake_start_async_job(chat_id, text, router_task_id=None, action_command=False):
            calls.append(("start_async_job", chat_id, router_task_id, action_command))
            return "JOB-SUMMARY"

        def fake_send_message(token, chat_id, text):
            calls.append(("send_message", chat_id, text))
            return True

        def fail_submit_task(*_args, **_kwargs):
            raise AssertionError("router task must not be created before the requested summary")

        originals = (
            telegram_direct_cto.LOGS,
            telegram_direct_cto.audit_passthrough,
            telegram_direct_cto.start_async_job,
            telegram_direct_cto.send_message,
            telegram_direct_cto.submit_task,
        )
        with tempfile.TemporaryDirectory() as tmp:
            telegram_direct_cto.LOGS = Path(tmp)
            telegram_direct_cto.audit_passthrough = lambda *args, **kwargs: {}
            telegram_direct_cto.start_async_job = fake_start_async_job
            telegram_direct_cto.send_message = fake_send_message
            telegram_direct_cto.submit_task = fail_submit_task
            try:
                telegram_direct_cto.handle_message(
                    "TOKEN",
                    "123",
                    {
                        "chat": {"id": "123"},
                        "from": {"username": "tester"},
                        "text": "Arşivdeki eski görevleri incele. Yeni görev açmadan önce bana kısa özet ver.",
                    },
                )
            finally:
                (
                    telegram_direct_cto.LOGS,
                    telegram_direct_cto.audit_passthrough,
                    telegram_direct_cto.start_async_job,
                    telegram_direct_cto.send_message,
                    telegram_direct_cto.submit_task,
                ) = originals

        self.assertEqual(calls[0], ("start_async_job", "123", None, False))
        self.assertEqual(calls[1][0], "send_message")
        self.assertIn("yeni görev açmayacağım", calls[1][2])

    def test_handle_message_uses_previous_actionable_context_for_development_followup(self):
        calls = []

        def fake_start_async_job(chat_id, text, router_task_id=None, action_command=False):
            calls.append(("start_async_job", chat_id, text, router_task_id, action_command))
            return "JOB-FOLLOWUP"

        def fake_send_message(token, chat_id, text):
            calls.append(("send_message", chat_id, text))
            return True

        def fake_submit_task(root, source, title, message, **kwargs):
            calls.append(("submit_task", source, title, message, kwargs))
            return {"task": {"id": "TASK-FOLLOWUP"}}

        originals = (
            telegram_direct_cto.LOGS,
            telegram_direct_cto.audit_passthrough,
            telegram_direct_cto.start_async_job,
            telegram_direct_cto.send_message,
            telegram_direct_cto.submit_task,
        )
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            telegram_direct_cto.LOGS = log_dir
            (log_dir / "direct_cto_inbox.ndjson").write_text(
                json.dumps(
                    {
                        "received_at": "2026-06-04T10:13:14+00:00",
                        "chat_id": "123",
                        "from_user": "tester",
                        "text": "CTO ya telegram üzerinden dosya resim gibi assetler gönderebilmeliyim. geliştirme yapar mısın",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            telegram_direct_cto.audit_passthrough = lambda *args, **kwargs: {}
            telegram_direct_cto.start_async_job = fake_start_async_job
            telegram_direct_cto.send_message = fake_send_message
            telegram_direct_cto.submit_task = fake_submit_task
            try:
                telegram_direct_cto.handle_message(
                    "TOKEN",
                    "123",
                    {
                        "chat": {"id": "123"},
                        "from": {"username": "tester"},
                        "text": "geliştirmeye başlayalım",
                    },
                )
            finally:
                (
                    telegram_direct_cto.LOGS,
                    telegram_direct_cto.audit_passthrough,
                    telegram_direct_cto.start_async_job,
                    telegram_direct_cto.send_message,
                    telegram_direct_cto.submit_task,
                ) = originals

        submit = next(call for call in calls if call[0] == "submit_task")
        started = next(call for call in calls if call[0] == "start_async_job")
        self.assertIn("telegram üzerinden dosya resim gibi assetler", submit[3])
        self.assertIn("Önceki Telegram geliştirme talebi", started[2])
        self.assertEqual(started[3], "TASK-FOLLOWUP")
        self.assertTrue(started[4])

    def test_archive_review_continuation_is_idempotent(self):
        calls = []

        def fake_submit_task(root, source, title, message, **kwargs):
            calls.append(("submit_task", title, kwargs))
            return {"task": {"id": "TASK-" + str(len(calls)), "title": title}}

        def fake_trigger_lifecycle(root):
            calls.append(("trigger_lifecycle", str(root)))
            return {"ok": True}

        originals = (
            telegram_direct_cto.CONTINUATION_STATE,
            telegram_direct_cto.submit_task,
            telegram_direct_cto.trigger_lifecycle,
        )
        with tempfile.TemporaryDirectory() as tmp:
            telegram_direct_cto.CONTINUATION_STATE = Path(tmp) / "continuations.json"
            telegram_direct_cto.submit_task = fake_submit_task
            telegram_direct_cto.trigger_lifecycle = fake_trigger_lifecycle
            try:
                first = telegram_direct_cto.queue_archive_review_continuation("tester")
                second = telegram_direct_cto.queue_archive_review_continuation("tester")
            finally:
                (
                    telegram_direct_cto.CONTINUATION_STATE,
                    telegram_direct_cto.submit_task,
                    telegram_direct_cto.trigger_lifecycle,
                ) = originals

        submit_calls = [call for call in calls if call[0] == "submit_task"]
        lifecycle_calls = [call for call in calls if call[0] == "trigger_lifecycle"]
        self.assertTrue(first["ok"])
        self.assertFalse(first["already_queued"])
        self.assertTrue(second["already_queued"])
        self.assertEqual(len(submit_calls), 3)
        self.assertEqual(len(lifecycle_calls), 1)

    def test_handle_message_routes_archive_review_continue_without_async_job(self):
        calls = []

        def fail_start_async_job(*_args, **_kwargs):
            raise AssertionError("continue command must route tasks instead of starting a short analysis job")

        def fake_send_message(token, chat_id, text):
            calls.append(("send_message", chat_id, text))
            return True

        def fake_queue_archive_review_continuation(from_user):
            calls.append(("queue_archive_review_continuation", from_user))
            return {"ok": True, "already_queued": False, "task_titles": ["Task A", "Task B"]}

        originals = (
            telegram_direct_cto.LOGS,
            telegram_direct_cto.audit_passthrough,
            telegram_direct_cto.start_async_job,
            telegram_direct_cto.send_message,
            telegram_direct_cto.latest_archive_review_summary_available,
            telegram_direct_cto.queue_archive_review_continuation,
        )
        with tempfile.TemporaryDirectory() as tmp:
            telegram_direct_cto.LOGS = Path(tmp)
            telegram_direct_cto.audit_passthrough = lambda *args, **kwargs: {}
            telegram_direct_cto.start_async_job = fail_start_async_job
            telegram_direct_cto.send_message = fake_send_message
            telegram_direct_cto.latest_archive_review_summary_available = lambda: True
            telegram_direct_cto.queue_archive_review_continuation = fake_queue_archive_review_continuation
            try:
                telegram_direct_cto.handle_message(
                    "TOKEN",
                    "123",
                    {
                        "chat": {"id": "123"},
                        "from": {"username": "tester"},
                        "text": "Job ID: CTO-ARCHIVE-REVIEW-20260604-0753 devam",
                    },
                )
            finally:
                (
                    telegram_direct_cto.LOGS,
                    telegram_direct_cto.audit_passthrough,
                    telegram_direct_cto.start_async_job,
                    telegram_direct_cto.send_message,
                    telegram_direct_cto.latest_archive_review_summary_available,
                    telegram_direct_cto.queue_archive_review_continuation,
                ) = originals

        self.assertEqual(calls[0], ("queue_archive_review_continuation", "tester"))
        self.assertEqual(calls[1][0], "send_message")
        self.assertIn("Devamı başlattım", calls[1][2])

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
    def test_dashboard_route_api_accepts_current_dashboard_shell(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            static = root / "web_panel" / "static"
            static.mkdir(parents=True)
            (static / "index.html").write_text(
                """
                <title>Codex Dev Center Yönetim Paneli</title>
                <div>Görevler, pipeline flow ve güvenli panel yönetimi</div>
                <nav>Pipeline Flow Görevler Workers Çıkış</nav>
                <main>
                  <span>Aktif Kuyruk</span>
                  <span>Canlı İşler</span>
                  <span>Kapalı Kayıt</span>
                  <button>Canlıya alınanları göster</button>
                  <script>
                    const stages = {
                      intake: 'Alım',
                      queue: 'Kuyruk',
                      worker: 'Worker',
                      proposal: 'Proposal',
                      validation: 'Doğrulama',
                      approval: 'Onay',
                      failed: 'Hata',
                      closed: 'Kapalı',
                      deployed: 'Canlı'
                    };
                  </script>
                </main>
                """,
                encoding="utf-8",
            )
            (static / "login.html").write_text(
                "Kullanıcı adı Şifre Giriş Yap İlk kullanıcıyı oluştur",
                encoding="utf-8",
            )

            original_root = production_readiness_suite.ROOT
            production_readiness_suite.ROOT = root
            try:
                results = {}
                production_readiness_suite.dashboard_test(results)
            finally:
                production_readiness_suite.ROOT = original_root

        self.assertTrue(results["dashboard_route_api_test"]["ok"])

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

    def test_stale_direct_cto_job_recovery_is_silent_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_path = self.write_job(tmp, "JOB-SILENT", pid=999999999)
            calls = []
            original_send = direct_cto_job_recovery.tg_send
            direct_cto_job_recovery.tg_send = lambda chat_id, text: calls.append((chat_id, text)) or True
            try:
                result = direct_cto_job_recovery.reconcile_stale_jobs(tmp, stale_seconds=1)
            finally:
                direct_cto_job_recovery.tg_send = original_send
            job = json.loads(job_path.read_text(encoding="utf-8"))

        self.assertEqual(result["changed"], 1)
        self.assertEqual(calls, [])
        self.assertNotIn("stale_recovery_notified_at", job)

    def test_stale_direct_cto_job_recovery_can_notify_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_path = self.write_job(tmp, "JOB-NOTIFY", pid=999999999)
            calls = []
            original_send = direct_cto_job_recovery.tg_send
            direct_cto_job_recovery.tg_send = lambda chat_id, text: calls.append((chat_id, text)) or True
            try:
                result = direct_cto_job_recovery.reconcile_stale_jobs(tmp, stale_seconds=1, notify=True)
            finally:
                direct_cto_job_recovery.tg_send = original_send
            job = json.loads(job_path.read_text(encoding="utf-8"))

        self.assertEqual(result["changed"], 1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "123")
        self.assertIn("stale_recovery_notified_at", job)

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


class DashboardPipelineFlowTest(unittest.TestCase):
    def write_flow_runtime(
        self,
        root: Path,
        tasks: list[dict],
        markers: dict[str, dict] | None = None,
    ) -> Path:
        state = root / "state"
        state.mkdir(parents=True)
        (state / "task_queue.json").write_text(json.dumps({"tasks": tasks}), encoding="utf-8")
        for name, payload in (markers or {}).items():
            (state / name).write_text(json.dumps(payload), encoding="utf-8")
        return state

    def stage_by_id(self, flow: dict, stage_id: str) -> dict:
        return next(stage for stage in flow["stages"] if stage["id"] == stage_id)

    def test_pipeline_flow_keeps_empty_stages_and_deployed_last(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_flow_runtime(root, [])

            flow = pipeline_flow.build_pipeline_flow(root, generated_at="2026-06-04T06:00:00+00:00")

        self.assertTrue(flow["ok"])
        self.assertTrue(flow["non_mutating"])
        self.assertEqual(flow["summary"]["task_count"], 0)
        self.assertEqual(flow["summary"]["current_stage"], None)
        self.assertEqual(flow["summary"]["unmapped_known_statuses"], [])
        self.assertEqual(flow["stages"][-1]["id"], "deployed")
        self.assertEqual(flow["stages"][-1]["statuses"], [TASK_STATUS_DEPLOYED])
        self.assertTrue(all(stage["task_count"] == 0 for stage in flow["stages"]))
        self.assertTrue(all(stage["state"] == "empty" for stage in flow["stages"]))

    def test_pipeline_flow_live_polling_contract_preserves_client_state_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = self.write_flow_runtime(
                root,
                [{"id": "TASK-RUNNING", "status": TASK_STATUS_RUNNING, "risk": "medium"}],
            )

            flow = pipeline_flow.build_pipeline_flow(root, generated_at="2026-06-04T10:30:00+00:00")
            first_revision = flow["serverRevision"]
            future = time.time() + 1
            os.utime(state / "task_queue.json", (future, future))
            later_flow = pipeline_flow.build_pipeline_flow(root)

        self.assertEqual(flow["flowId"], "dashboard_pipeline_flow")
        self.assertEqual(flow["runId"], "runtime_state")
        self.assertEqual(flow["resetToken"], "dashboard_pipeline_flow:runtime_state")
        self.assertEqual(flow["generatedAt"], flow["generated_at"])
        self.assertEqual(flow["generatedAt"], "2026-06-04T10:30:00+00:00")
        self.assertIsInstance(first_revision, int)
        self.assertGreaterEqual(first_revision, 0)
        self.assertGreater(later_flow["serverRevision"], first_revision)
        self.assertFalse(flow["requiresUiReset"])
        self.assertEqual(flow["initialUiDefaults"]["activeFlowStage"], "worker")
        self.assertIn("stages", flow["mergePolicy"]["serverOwned"])
        self.assertIn("main_tasks", flow["mergePolicy"]["serverOwned"])
        self.assertIn("markers", flow["mergePolicy"]["serverOwned"])
        self.assertIn("activeFlowStage", flow["mergePolicy"]["clientOwned"])
        self.assertIn("pipelineMainTaskExpanded", flow["mergePolicy"]["clientOwned"])
        self.assertIn("filters", flow["mergePolicy"]["clientOwned"])

    def test_pipeline_flow_reset_token_uses_safe_run_marker_when_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_flow_runtime(
                root,
                [{"id": "TASK-RUNNING", "status": TASK_STATUS_RUNNING, "risk": "medium"}],
                {"pipeline_status.json": {"last_task_id": "CTO-RUN-123", "stdout": "hidden"}},
            )

            flow = pipeline_flow.build_pipeline_flow(root)

        self.assertEqual(flow["runId"], "CTO-RUN-123")
        self.assertEqual(flow["resetToken"], "dashboard_pipeline_flow:CTO-RUN-123")
        self.assertEqual(flow["markers"]["pipeline_status"]["last_task_id"], "CTO-RUN-123")

    def test_pipeline_flow_maps_failed_blocked_approval_and_validation_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_flow_runtime(
                root,
                [
                    {"id": "TASK-FAILED", "status": TASK_STATUS_FAILED_TIMEOUT, "risk": "medium"},
                    {"id": "TASK-BLOCKED", "status": TASK_STATUS_BLOCKED, "risk": "medium"},
                    {"id": "TASK-APPROVAL", "status": TASK_STATUS_APPROVAL_REQUIRED, "risk": "high"},
                    {"id": "TASK-VALIDATION", "status": TASK_STATUS_VALIDATION_FAILED, "risk": "medium"},
                    {"id": "TASK-DEPLOYED", "status": TASK_STATUS_DEPLOYED, "risk": "low"},
                ],
            )

            flow = pipeline_flow.build_pipeline_flow(root)

        failed = self.stage_by_id(flow, "failed")
        approval = self.stage_by_id(flow, "approval")
        validation = self.stage_by_id(flow, "validation")
        deployed = self.stage_by_id(flow, "deployed")

        self.assertEqual(failed["state"], "failed")
        self.assertEqual({task["id"] for task in failed["tasks"]}, {"TASK-FAILED"})
        self.assertEqual(approval["state"], "blocked")
        self.assertEqual({task["id"] for task in approval["tasks"]}, {"TASK-BLOCKED", "TASK-APPROVAL"})
        self.assertEqual(validation["state"], "failed")
        self.assertEqual({task["id"] for task in validation["tasks"]}, {"TASK-VALIDATION"})
        self.assertEqual(deployed["state"], "complete")
        self.assertEqual(deployed["order"], max(stage["order"] for stage in flow["stages"]))
        self.assertEqual(flow["summary"]["failed_count"], 2)
        self.assertEqual(flow["summary"]["blocked_count"], 2)

    def test_pipeline_flow_groups_main_tasks_and_legacy_records(self):
        root_id = "CTO-TASK-20260604-091747-621734-TELEGRAM-ACTION-COMMAND"
        backlog_id = "CTO-BACKLOG-20260604-091751-464617-TELEGRAM-ACTION-COMMAND"
        apply_id = "CTO-APPLY-20260604-092448-CTO-BACKLOG-20260604-091751-464617-TELEGRAM-ACTION-COMMAND"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_flow_runtime(
                root,
                [
                    {
                        "id": root_id,
                        "status": TASK_STATUS_PROPOSAL_READY,
                        "risk": "medium",
                        "updated_at": "2026-06-04T09:00:00+00:00",
                    },
                    {
                        "id": backlog_id,
                        "status": TASK_STATUS_PROPOSAL_DONE,
                        "root_task_id": root_id,
                        "risk": "medium",
                        "assigned_worker": "worker-1",
                        "updated_at": "2026-06-04T09:10:00+00:00",
                    },
                    {
                        "id": apply_id,
                        "status": TASK_STATUS_RUNNING,
                        "root_task_id": backlog_id,
                        "pull_request_url": "https://github.com/example/repo/pull/1",
                        "merge_blocked_reason": "waiting_for_checks",
                        "risk": "medium",
                        "assigned_worker": "worker-1",
                        "updated_at": "2026-06-04T09:20:00+00:00",
                    },
                    {
                        "id": "CTO-DISPATCH-CHILD",
                        "status": TASK_STATUS_READY_FOR_VALIDATION,
                        "parent_task_id": backlog_id,
                        "deploy_run_id": "100",
                        "smoke_run_id": "101",
                        "risk": "medium",
                        "assigned_worker": "worker-2",
                        "updated_at": "2026-06-04T09:15:00+00:00",
                    },
                    {
                        "id": "TASK-OLD",
                        "status": TASK_STATUS_DONE,
                        "risk": "low",
                        "updated_at": "2026-06-04T08:00:00+00:00",
                    },
                ],
            )

            flow = pipeline_flow.build_pipeline_flow(root)

        self.assertEqual(flow["summary"]["main_task_count"], 2)
        groups = {item["main_task_code"]: item for item in flow["main_tasks"]}
        main = groups[root_id]
        legacy = groups["LEGACY"]

        self.assertEqual(main["main_task_title"], "Telegram Action Command")
        self.assertEqual(main["root_task_id"], root_id)
        self.assertEqual(main["overall_status"], TASK_STATUS_RUNNING)
        self.assertEqual(main["counts"]["tasks"], 4)
        self.assertEqual(main["counts"]["children"], 3)
        self.assertEqual(main["counts_by_status"][TASK_STATUS_RUNNING], 1)
        self.assertEqual(main["progress_percent"], main["progress"]["percent"])
        self.assertEqual(main["latest_pr"]["url"], "https://github.com/example/repo/pull/1")
        self.assertEqual(main["latest_deploy_run"]["run_id"], "100")
        self.assertEqual(main["latest_smoke_run"]["run_id"], "101")
        self.assertEqual(main["blocked_reason"], "waiting_for_checks")
        self.assertEqual({child["id"] for child in main["children"]}, {backlog_id, apply_id, "CTO-DISPATCH-CHILD"})
        self.assertEqual(legacy["main_task_title"], "Gruplanmamış Eski Görevler")
        self.assertEqual(legacy["counts"]["tasks"], 1)
        self.assertEqual(legacy["children"][0]["id"], "TASK-OLD")

    def test_pipeline_flow_reads_safe_markers_without_raw_task_or_terminal_fields(self):
        secret_text = "raw-secret-value-should-not-leak"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_flow_runtime(
                root,
                [
                    {
                        "id": "TASK-SAFE",
                        "status": TASK_STATUS_RUNNING,
                        "risk": "medium",
                        "title": secret_text,
                        "description": secret_text,
                        "message": secret_text,
                        "stdout": secret_text,
                    }
                ],
                {
                    "pipeline_status.json": {
                        "status": "PASS",
                        "task_to_deploy_test": "PASS",
                        "stdout": secret_text,
                    },
                    "github_actions_status.json": {
                        "runner_name": "codex-dev-center-01",
                        "last_deploy_status": "PASS",
                        "stderr": secret_text,
                    },
                    "last_smoke_test_status.json": {
                        "status": "PASS",
                        "ok": True,
                        "log": secret_text,
                    },
                },
            )

            flow = pipeline_flow.build_pipeline_flow(root)

        encoded = json.dumps(flow, ensure_ascii=False)
        self.assertNotIn(secret_text, encoded)
        self.assertNotIn("stdout", encoded)
        self.assertNotIn("stderr", encoded)
        self.assertNotIn("description", encoded)
        self.assertNotIn("title", flow["stages"][2]["tasks"][0])
        self.assertEqual(flow["markers"]["pipeline_status"]["task_to_deploy_test"], "PASS")
        self.assertEqual(flow["markers"]["github_actions"]["runner_name"], "codex-dev-center-01")
        self.assertEqual(flow["markers"]["last_smoke_test"]["status"], "PASS")

    def test_pipeline_flow_payload_is_available_for_all_panel_servers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_flow_runtime(root, [{"id": "TASK-DEPLOYED", "status": TASK_STATUS_DEPLOYED}])

            originals = {
                panel_server: panel_server.ROOT,
                legacy_panel_server: legacy_panel_server.ROOT,
            }
            try:
                for module in originals:
                    module.ROOT = root
                    payload = module.pipeline_flow_payload()
                    self.assertEqual(payload["stages"][-1]["id"], "deployed")
                    self.assertEqual(payload["summary"]["current_stage"], "deployed")
                    self.assertEqual(self.stage_by_id(payload, "deployed")["task_count"], 1)
            finally:
                for module, original_root in originals.items():
                    module.ROOT = original_root


class DashboardPipelineFlowUiTest(unittest.TestCase):
    def test_dashboard_index_has_accessible_pipeline_flow_tabs_and_safe_polling(self):
        html = (ROOT / "web_panel" / "static" / "index.html").read_text(encoding="utf-8")

        self.assertIn("/api/pipeline-flow", html)
        self.assertIn('role="tablist"', html)
        self.assertIn('role="tab"', html)
        self.assertIn('role="tabpanel"', html)
        self.assertIn("pipeline_stage", html)
        self.assertIn("pipelineFlowTabs.addEventListener('keydown'", html)
        self.assertIn("AbortController", html)
        self.assertIn("document.hidden", html)
        self.assertIn("pipelineFlowFailureCount", html)
        self.assertIn("renderPipelineFlow", html)
        self.assertIn("flowDateTime", html)
        self.assertIn("flowMainTasks", html)
        self.assertIn("renderFlowMainTasks", html)
        self.assertIn('class="flow-main-task"', html)
        self.assertIn("pipelineMainTaskExpanded = new Map()", html)
        self.assertIn("function flowMainTaskKey(mainTask)", html)
        self.assertIn("function prunePipelineMainTaskExpanded(currentKeys)", html)
        self.assertIn("prunePipelineMainTaskExpanded([])", html)
        self.assertIn("function rememberPipelineMainTaskToggleIntent(details)", html)
        self.assertIn("function bindFlowMainTaskToggleClicks()", html)
        self.assertIn('data-main-task-key="${esc(key)}"', html)
        self.assertIn("summary.addEventListener('click'", html)
        self.assertIn("pipelineMainTaskExpanded.set(key, !details.open)", html)
        self.assertNotIn("details.addEventListener('toggle'", html)
        self.assertNotIn("event.currentTarget.open", html)
        self.assertIn("pipelineFlowLastAppliedRevision", html)
        self.assertIn("pipelineFlowResetToken", html)
        self.assertIn("function pipelineFlowResponseMeta(payload)", html)
        self.assertIn("function resetPipelineFlowClientState(payload)", html)
        self.assertIn("function applyPipelineFlowResponse(payload)", html)
        self.assertIn("serverRevision", html)
        self.assertIn("resetToken", html)
        self.assertIn("requiresUiReset", html)
        self.assertIn("meta.revision <= pipelineFlowLastAppliedRevision", html)
        self.assertIn("applyPipelineFlowResponse(await res.json())", html)
        self.assertNotIn("latestFlow = await res.json()", html)
        self.assertNotIn('class="flow-main-task" ${index === 0 ?', html)
        self.assertIn("latestFlow.main_tasks", html)
        self.assertIn("day: '2-digit'", html)
        self.assertIn("month: '2-digit'", html)
        self.assertIn("<strong>${esc(task.id || '-')}</strong>", html)
        self.assertIn("${badge(task.status)} ${badge(task.risk || task.risk_level || '-')}", html)
        self.assertNotIn("task.description", html)
        self.assertNotIn("task.stdout", html)
        self.assertNotIn("task.stderr", html)

    def test_dashboard_pipeline_flow_preserves_main_task_expand_state(self):
        html = (ROOT / "web_panel" / "static" / "index.html").read_text(encoding="utf-8")

        self.assertIn("const mainTaskKeys = mainTasks.map(flowMainTaskKey);", html)
        self.assertIn("prunePipelineMainTaskExpanded(mainTaskKeys);", html)
        self.assertIn("const hasStoredExpandedState = pipelineMainTaskExpanded.size > 0;", html)
        self.assertIn("pipelineMainTaskExpanded.set(key, !hasStoredExpandedState && index === 0);", html)
        self.assertIn("const isOpen = key ? pipelineMainTaskExpanded.get(key) === true : index === 0;", html)
        self.assertIn("if (!current.has(key)) pipelineMainTaskExpanded.delete(key);", html)
        self.assertIn("bindFlowMainTaskToggleClicks();", html)
        self.assertNotIn("flowMainTaskIsOpen(mainTask, index)", html)
        self.assertNotIn('data-flow-main-task="${esc(taskKey)}"', html)


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

    def test_deploy_workflow_failure_uses_local_vm_fallback_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = self.deployable_task("TASK-LOCAL-FALLBACK")
            original_dispatch = cto_autonomous_delivery.dispatch_workflow
            original_local = cto_autonomous_delivery.run_local_deploy_fallback
            original_main_head = cto_autonomous_delivery.main_head

            def fail_dispatch(_workflow, wait=False):
                return {"ok": False, "status": "DISPATCH_FAILED", "dispatch": {"returncode": 1}}

            def fake_local(_task):
                return {
                    "ok": True,
                    "status": "LOCAL_VM_FALLBACK_DEPLOYED",
                    "controller": {"ok": True, "status": "PASS"},
                    "run": {
                        "databaseId": "local-test",
                        "url": "",
                        "headSha": "local-sha",
                        "status": "completed",
                        "conclusion": "success",
                        "local_vm_fallback": True,
                        "controller_status": "PASS",
                    },
                }

            cto_autonomous_delivery.dispatch_workflow = fail_dispatch
            cto_autonomous_delivery.run_local_deploy_fallback = fake_local
            cto_autonomous_delivery.main_head = lambda: "local-sha"
            try:
                with self.patched_delivery_runtime(tmp, [task]) as queue_path:
                    base_policy = cto_autonomous_delivery.policy
                    cto_autonomous_delivery.policy = lambda: {
                        **base_policy(),
                        "local_vm_deploy_fallback_enabled": True,
                        "local_vm_deploy_fallback_allowed_actor": "cto_finalizer",
                    }
                    try:
                        result = cto_autonomous_delivery.deploy_task("TASK-LOCAL-FALLBACK", execute=True, wait=True, smoke=True)
                    finally:
                        cto_autonomous_delivery.policy = base_policy
                    queue = json.loads(queue_path.read_text(encoding="utf-8"))
            finally:
                cto_autonomous_delivery.dispatch_workflow = original_dispatch
                cto_autonomous_delivery.run_local_deploy_fallback = original_local
                cto_autonomous_delivery.main_head = original_main_head

        updated = queue["tasks"][0]
        self.assertEqual(result["status"], "DEPLOYED")
        self.assertEqual(result["deployment_path"], "local_vm_fallback_after_workflow_failure")
        self.assertEqual(updated["status"], TASK_STATUS_DEPLOYED)
        self.assertTrue(updated["local_vm_deploy_fallback_used"])
        self.assertEqual(updated["deploy_run_id"], "local-test")

    def test_requested_local_vm_fallback_skips_workflow_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = self.deployable_task("TASK-FORCED-LOCAL-FALLBACK")
            original_dispatch = cto_autonomous_delivery.dispatch_workflow
            original_local = cto_autonomous_delivery.run_local_deploy_fallback
            original_env = os.environ.copy()

            def fail_dispatch(_workflow, wait=False):
                raise AssertionError("workflow dispatch must be skipped when local fallback is requested")

            def fake_local(_task):
                return {
                    "ok": True,
                    "status": "LOCAL_VM_FALLBACK_DEPLOYED",
                    "controller": {"ok": True, "status": "PASS"},
                    "run": {
                        "databaseId": "local-forced",
                        "url": "",
                        "headSha": "local-sha",
                        "status": "completed",
                        "conclusion": "success",
                        "local_vm_fallback": True,
                        "controller_status": "PASS",
                    },
                }

            cto_autonomous_delivery.dispatch_workflow = fail_dispatch
            cto_autonomous_delivery.run_local_deploy_fallback = fake_local
            os.environ["CODEX_LOCAL_DEPLOY_FALLBACK"] = "1"
            try:
                with self.patched_delivery_runtime(tmp, [task]) as queue_path:
                    base_policy = cto_autonomous_delivery.policy
                    cto_autonomous_delivery.policy = lambda: {
                        **base_policy(),
                        "local_vm_deploy_fallback_enabled": True,
                        "local_vm_deploy_fallback_allowed_actor": "cto_finalizer",
                    }
                    try:
                        result = cto_autonomous_delivery.deploy_task("TASK-FORCED-LOCAL-FALLBACK", execute=True, wait=True, smoke=True)
                    finally:
                        cto_autonomous_delivery.policy = base_policy
                    queue = json.loads(queue_path.read_text(encoding="utf-8"))
            finally:
                cto_autonomous_delivery.dispatch_workflow = original_dispatch
                cto_autonomous_delivery.run_local_deploy_fallback = original_local
                os.environ.clear()
                os.environ.update(original_env)

        self.assertEqual(result["status"], "DEPLOYED")
        self.assertEqual(result["deployment_path"], "local_vm_fallback_requested")
        self.assertEqual(queue["tasks"][0]["deploy_run_id"], "local-forced")

    def test_root_cause_mode_blocks_backlog_creation_for_deploy_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            retry = self.deployable_task("TASK-DEPLOY-RETRY")
            retry["deployment_status"] = "DEPLOY_RETRY_REQUIRED"
            retry["deploy_retry_required"] = True
            candidate = {"id": "TASK-CANDIDATE", "status": TASK_STATUS_DONE, "risk": "low", "title": "safe followup"}
            with self.patched_delivery_runtime(tmp, [retry, candidate]) as queue_path:
                status = cto_autonomous_delivery.root_cause_mode_status()
                result = cto_autonomous_delivery.start_next_backlog(execute=True)
                queue = json.loads(queue_path.read_text(encoding="utf-8"))

        self.assertTrue(status["active"])
        self.assertEqual(result["status"], "ROOT_CAUSE_MODE_ACTIVE")
        self.assertEqual(len(queue["tasks"]), 2)

    def test_pipeline_failed_apply_child_requires_root_cause_mode(self):
        task = {"id": "CTO-APPLY-1", "status": TASK_STATUS_PIPELINE_FAILED, "risk": "medium", "parent_task_id": "PARENT"}

        self.assertEqual(cto_autonomous_delivery.backlog_candidate_reason(task), "pipeline_failed_requires_root_cause_mode")

    def test_done_task_is_not_backlog_candidate(self):
        task = {"id": "DONE-PARENT", "status": TASK_STATUS_DONE, "risk": "low", "title": "safe completed work"}

        self.assertEqual(cto_autonomous_delivery.backlog_candidate_reason(task), "done_task_not_backlog_candidate")

    def test_backlog_candidate_skips_parent_with_existing_repo_apply_child(self):
        task = {
            "id": "PARENT",
            "status": TASK_STATUS_PROPOSAL_DONE,
            "risk": "medium",
            "repo_apply_child": "CTO-APPLY-PARENT",
        }

        self.assertEqual(cto_autonomous_delivery.backlog_candidate_reason(task), "repo_apply_child_already_created")

    def test_backlog_candidate_skips_parent_with_existing_dispatcher_child(self):
        task = {
            "id": "PARENT",
            "status": TASK_STATUS_READY_FOR_VALIDATION,
            "risk": "medium",
            "backlog_dispatcher_child": "CTO-DISPATCH-PARENT",
        }

        self.assertEqual(cto_autonomous_delivery.backlog_candidate_reason(task), "backlog_dispatcher_child_already_created")

    def test_backlog_candidate_skips_dispatcher_child(self):
        task = {
            "id": "CTO-DISPATCH-CHILD",
            "status": TASK_STATUS_PROPOSAL_DONE,
            "risk": "medium",
            "source": "cto_backlog_dispatcher",
            "title": "Validation: Dashboard Pipeline Flow UI Tabs",
        }

        self.assertEqual(cto_autonomous_delivery.backlog_candidate_reason(task), "backlog_dispatcher_child_not_backlog_candidate")

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

    def test_ready_for_validation_is_owned_by_validation_engine(self):
        tasks = [{"id": "PARENT", "status": TASK_STATUS_READY_FOR_VALIDATION, "risk": "low", "worker_eligible": True}]

        self.assertIsNone(lifecycle_manager.dispatcher_candidate(tasks))

    def test_active_repo_apply_child_prevents_duplicate_backlog_dispatch(self):
        tasks = [
            {
                "id": "PARENT",
                "status": TASK_STATUS_PROPOSAL_DONE,
                "risk": "medium",
                "repo_apply_child": "APPLY-CHILD",
            },
            {
                "id": "APPLY-CHILD",
                "status": TASK_STATUS_RUNNING,
                "risk": "medium",
            },
        ]

        self.assertIsNone(lifecycle_manager.dispatcher_candidate(tasks))

    def test_pr_backed_repo_apply_child_prevents_duplicate_backlog_dispatch(self):
        tasks = [
            {
                "id": "PARENT",
                "status": TASK_STATUS_PROPOSAL_DONE,
                "risk": "medium",
                "repo_apply_child": "APPLY-CHILD",
            },
            {
                "id": "APPLY-CHILD",
                "status": TASK_STATUS_FAILED_RETRYABLE,
                "source": lifecycle_manager.BACKLOG_DISPATCHER_SOURCE,
                "risk": "medium",
                "result": "repo_apply_pr_ready_pipeline_passed",
                "pull_request_url": "https://example.invalid/pull/1",
                "merge_blocked": True,
            },
        ]

        self.assertIsNone(lifecycle_manager.dispatcher_candidate(tasks))

    def test_proposal_done_prefers_repo_apply_child(self):
        queue = {"tasks": [{"id": "PARENT", "status": TASK_STATUS_PROPOSAL_DONE, "risk": "low", "title": "safe app work"}]}
        child = lifecycle_manager.create_repo_apply_task(queue, queue["tasks"][0])

        self.assertEqual(child["dispatcher_mode"], "apply")
        self.assertEqual(child["execution_mode"], "repo_apply")
        self.assertTrue(child["repo_apply_allowed"])
        self.assertEqual(queue["tasks"][0]["repo_apply_child"], child["id"])

    def test_dispatcher_validation_child_does_not_create_repo_apply_child(self):
        tasks = [
            {
                "id": "VALIDATION-CHILD",
                "status": TASK_STATUS_PROPOSAL_DONE,
                "source": lifecycle_manager.BACKLOG_DISPATCHER_SOURCE,
                "dispatcher_mode": "validation",
                "risk": "medium",
                "title": "Validation: Dashboard Profile / Account Menu",
            }
        ]

        self.assertFalse(lifecycle_manager.is_repo_apply_candidate(tasks[0], tasks))
        self.assertIsNone(lifecycle_manager.repo_apply_candidate(tasks))

    def test_pr_ready_merge_blocked_child_does_not_create_repo_apply_retry(self):
        tasks = [
            {
                "id": "PARENT",
                "status": TASK_STATUS_PROPOSAL_DONE,
                "risk": "medium",
                "repo_apply_child": "CHILD",
                "repo_apply_attempts": 1,
            },
            {
                "id": "CHILD",
                "status": TASK_STATUS_FAILED_RETRYABLE,
                "risk": "medium",
                "result": "repo_apply_pr_ready_pipeline_passed",
                "pull_request_url": "https://example.invalid/pull/1",
                "merge_blocked": True,
            },
        ]

        self.assertFalse(lifecycle_manager.child_allows_retry(tasks, "CHILD"))
        self.assertFalse(lifecycle_manager.is_repo_apply_candidate(tasks[0], tasks))
        self.assertIsNone(lifecycle_manager.repo_apply_candidate(tasks))

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

    def test_root_cause_mode_blocks_lifecycle_dispatcher_children(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            state = runtime / "state"
            state.mkdir()
            queue_path = state / "task_queue.json"
            system_state_path = state / "system_state.json"
            queue_path.write_text(
                json.dumps({"tasks": [{"id": "PARENT", "status": TASK_STATUS_PROPOSAL_DONE, "risk": "low"}]}),
                encoding="utf-8",
            )

            originals = (
                lifecycle_manager.QUEUE_PATH,
                lifecycle_manager.SYSTEM_STATE_PATH,
                lifecycle_manager.cto_autonomous_delivery.root_cause_mode_status,
            )
            lifecycle_manager.QUEUE_PATH = queue_path
            lifecycle_manager.SYSTEM_STATE_PATH = system_state_path
            lifecycle_manager.cto_autonomous_delivery.root_cause_mode_status = lambda _queue=None: {
                "ok": True,
                "active": True,
                "status": "ROOT_CAUSE_MODE_ACTIVE",
                "deploy_retry_task_ids": ["TASK-DEPLOY-RETRY"],
                "pipeline_failed_child_ids": [],
                "reason": "deploy_or_pipeline_root_cause_required",
            }
            try:
                created = lifecycle_manager.ensure_single_backlog_task()
            finally:
                (
                    lifecycle_manager.QUEUE_PATH,
                    lifecycle_manager.SYSTEM_STATE_PATH,
                    lifecycle_manager.cto_autonomous_delivery.root_cause_mode_status,
                ) = originals

            queue = json.loads(queue_path.read_text(encoding="utf-8"))
            system_state = json.loads(system_state_path.read_text(encoding="utf-8"))

        self.assertFalse(created)
        self.assertEqual(len(queue["tasks"]), 1)
        self.assertEqual(system_state["backlog_dispatcher_last_result"], "root_cause_mode_active")

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

    def test_ready_proposal_becomes_proposal_done_without_pipeline_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = self.write_ready_runtime(tmp, pipeline_status="FAIL")
            result = task_validation_engine.validate_ready_tasks(runtime, limit=5)
            queue = json.loads((runtime / "state" / "task_queue.json").read_text(encoding="utf-8"))

        self.assertEqual(result["changed"], 1)
        self.assertEqual(queue["tasks"][0]["status"], TASK_STATUS_PROPOSAL_DONE)
        self.assertEqual(queue["tasks"][0]["validation_status"], "PASS")
        self.assertEqual(queue["tasks"][0]["pipeline_status"], "NOT_REQUIRED")
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

    def test_pipeline_failure_does_not_mark_repo_applied_task_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = self.write_ready_runtime(tmp, pipeline_status="FAIL")
            queue_path = runtime / "state" / "task_queue.json"
            queue = json.loads(queue_path.read_text(encoding="utf-8"))
            queue["tasks"][0]["repo_applied"] = True
            queue_path.write_text(json.dumps(queue), encoding="utf-8")
            result = task_validation_engine.validate_ready_tasks(runtime, limit=5)
            queue = json.loads(queue_path.read_text(encoding="utf-8"))

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

    def test_rotate_procedure_reference_does_not_require_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = self.write_ready_runtime(tmp, pipeline_status="FAIL")
            workspace = next((runtime / "workspaces").glob("worker_worker-1_TASK-VAL_*"))
            (workspace / "LIVING_DOCS_CHECKLIST.md").write_text(
                "# Living Docs\n\n"
                "- [ ] Token sızıntısı şüphesi için rotate prosedürü linklendi.\n"
                "- [ ] Gerçek token/env değeri okunmadı veya yazılmadı.\n",
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


class ActionResultWatcherTest(unittest.TestCase):
    def test_deployed_action_task_is_not_downgraded_by_existing_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            state = runtime / "state"
            logs = runtime / "logs"
            reports = runtime / "reports"
            workspace = runtime / "workspaces" / "worker_worker-1_CTO-ACTION-20260604-120000-01-EXAMPLE_20260604_120001"
            state.mkdir()
            logs.mkdir()
            reports.mkdir()
            workspace.mkdir(parents=True)
            for name in action_result_watcher.EXPECTED[:4]:
                (workspace / name).write_text("ok\n", encoding="utf-8")

            task = {
                "id": "CTO-ACTION-20260604-120000-01-EXAMPLE",
                "status": TASK_STATUS_DEPLOYED,
                "delivery_level": TASK_STATUS_DEPLOYED,
                "deployment_status": TASK_STATUS_DEPLOYED,
                "production_deployed": True,
                "assigned_worker": "worker-1",
                "workspace": str(workspace),
            }
            (state / "task_queue.json").write_text(json.dumps({"tasks": [task]}), encoding="utf-8")
            (state / "workers.json").write_text(json.dumps({"workers": []}), encoding="utf-8")
            (state / "system_state.json").write_text(json.dumps({"production_deployed": True}), encoding="utf-8")

            calls = []
            originals = (
                action_result_watcher.APP,
                action_result_watcher.STATE,
                action_result_watcher.LOGS,
                action_result_watcher.REPORTS,
                action_result_watcher.send_message,
            )
            action_result_watcher.APP = runtime
            action_result_watcher.STATE = state
            action_result_watcher.LOGS = logs
            action_result_watcher.REPORTS = reports
            action_result_watcher.send_message = lambda text: calls.append(text) or True
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    action_result_watcher.main()
            finally:
                (
                    action_result_watcher.APP,
                    action_result_watcher.STATE,
                    action_result_watcher.LOGS,
                    action_result_watcher.REPORTS,
                    action_result_watcher.send_message,
                ) = originals

            queue = json.loads((state / "task_queue.json").read_text(encoding="utf-8"))
            system_state = json.loads((state / "system_state.json").read_text(encoding="utf-8"))

        self.assertEqual(queue["tasks"][0]["status"], TASK_STATUS_DEPLOYED)
        self.assertEqual(queue["tasks"][0]["delivery_level"], TASK_STATUS_DEPLOYED)
        self.assertTrue(queue["tasks"][0]["production_deployed"])
        self.assertTrue(system_state["production_deployed"])
        self.assertEqual(calls, [])


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
                "Token sızıntısı şüphesi için rotate prosedürü linklendi.",
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

    def test_github_actions_channel_allows_cto_local_fallback_context(self):
        cfg = {
            "production_deploy_channel": "github_actions_manual",
            "local_vm_deploy_fallback_enabled": True,
            "local_vm_deploy_fallback_allowed_actor": "cto_finalizer",
        }
        original_env = os.environ.copy()
        try:
            os.environ.pop("GITHUB_ACTIONS", None)
            os.environ["CODEX_LOCAL_DEPLOY_FALLBACK"] = "1"
            os.environ["CODEX_DEPLOY_ACTOR"] = "cto_finalizer"
            self.assertTrue(production_deploy_controller.github_actions_local_fallback_allowed(cfg))
        finally:
            os.environ.clear()
            os.environ.update(original_env)

    def test_environment_manager_github_actions_blocker_is_bypassed_only_for_local_fallback(self):
        original_policy = production_environment_manager.deploy_policy
        original_env = os.environ.copy()
        production_environment_manager.deploy_policy = lambda: {
            "deploy_policy": {
                "production_deploy_channel": "github_actions_manual",
                "local_vm_deploy_fallback_enabled": True,
            },
            "production_policy": {"local_vm_deploy_fallback_allowed_actor": "cto_finalizer"},
            "commands": {},
        }
        try:
            os.environ.pop("GITHUB_ACTIONS", None)
            os.environ.pop("CODEX_LOCAL_DEPLOY_FALLBACK", None)
            os.environ.pop("CODEX_DEPLOY_ACTOR", None)
            self.assertFalse(production_environment_manager.github_actions_local_fallback_allowed())
            os.environ["CODEX_LOCAL_DEPLOY_FALLBACK"] = "1"
            os.environ["CODEX_DEPLOY_ACTOR"] = "cto_finalizer"
            self.assertTrue(production_environment_manager.github_actions_local_fallback_allowed())
        finally:
            production_environment_manager.deploy_policy = original_policy
            os.environ.clear()
            os.environ.update(original_env)

    def test_environment_manager_updates_runtime_commit_markers(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            state = runtime / "state"
            state.mkdir()
            state_path = state / "system_state.json"
            state_path.write_text(json.dumps({"system_state": "READY_FOR_NEW_TASKS"}), encoding="utf-8")

            originals = (
                production_environment_manager.ROOT,
                production_environment_manager.STATE,
                production_environment_manager.git_origin_main_head,
            )
            production_environment_manager.ROOT = runtime
            production_environment_manager.STATE = state
            production_environment_manager.git_origin_main_head = lambda: "new-head"
            try:
                production_environment_manager.update_runtime_commit_markers("new-head")
            finally:
                (
                    production_environment_manager.ROOT,
                    production_environment_manager.STATE,
                    production_environment_manager.git_origin_main_head,
                ) = originals

            updated = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual(updated["system_state"], "READY_FOR_NEW_TASKS")
        self.assertEqual(updated["production_running_commit"], "new-head")
        self.assertEqual(updated["github_origin_main_commit"], "new-head")
        self.assertTrue(updated["production_github_sync"])

    def test_environment_manager_health_accepts_auth_required_status_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            state = runtime / "state"
            reports = runtime / "reports"
            for relative in [
                "web_panel/panel_server.py",
                "web_panel/static/index.html",
                "supervisor/production_environment_manager.py",
                "supervisor/production_deploy_controller.py",
            ]:
                path = runtime / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("ok\n", encoding="utf-8")
            state.mkdir()
            reports.mkdir()

            def fake_http_json(port, path):
                if path == "/health":
                    return {"ok": True, "status": 200, "body": {"ok": True}}
                if path == "/api/status":
                    return {"ok": False, "status": 401, "body": {"ok": False, "login": "/login"}}
                return {"ok": False, "status": 404, "body": {}}

            originals = (
                production_environment_manager.ROOT,
                production_environment_manager.STATE,
                production_environment_manager.REPORTS,
                production_environment_manager.http_json,
                production_environment_manager.service_discovery,
            )
            production_environment_manager.ROOT = runtime
            production_environment_manager.STATE = state
            production_environment_manager.REPORTS = reports
            production_environment_manager.http_json = fake_http_json
            production_environment_manager.service_discovery = lambda: {"systemd_available": False}
            try:
                payload = production_environment_manager.health_check("production")
            finally:
                (
                    production_environment_manager.ROOT,
                    production_environment_manager.STATE,
                    production_environment_manager.REPORTS,
                    production_environment_manager.http_json,
                    production_environment_manager.service_discovery,
                ) = originals

        self.assertTrue(payload["ok"])
        self.assertTrue(payload["status_api"]["ok"])
        self.assertTrue(payload["status_api"]["auth_required"])

    def test_environment_manager_smoke_accepts_current_dashboard_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            state = runtime / "state"
            reports = runtime / "reports"
            state.mkdir()
            reports.mkdir()

            originals = (
                production_environment_manager.ROOT,
                production_environment_manager.STATE,
                production_environment_manager.REPORTS,
                production_environment_manager.health_check,
                production_environment_manager.http_json,
                production_environment_manager.http_text,
            )
            production_environment_manager.ROOT = runtime
            production_environment_manager.STATE = state
            production_environment_manager.REPORTS = reports
            production_environment_manager.health_check = lambda scope="production": {"ok": True}
            production_environment_manager.http_json = lambda port, path: {
                "ok": True,
                "status": 200,
                "body": {"production_environment": {}, "deploy_commands": {}},
            }
            production_environment_manager.http_text = lambda port, path: {
                "ok": True,
                "body": "Pipeline Flow Görevler Canlıya alınanları göster Çıkış",
            }
            try:
                payload = production_environment_manager.smoke_test("production")
            finally:
                (
                    production_environment_manager.ROOT,
                    production_environment_manager.STATE,
                    production_environment_manager.REPORTS,
                    production_environment_manager.health_check,
                    production_environment_manager.http_json,
                    production_environment_manager.http_text,
                ) = originals

        self.assertTrue(payload["ok"])
        self.assertTrue(payload["checks"]["index_turkish_labels"])

    def test_telegram_health_watcher_suppresses_auto_report_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            state = runtime / "state"
            logs = runtime / "logs"

            originals = (
                telegram_health_watcher.APP,
                telegram_health_watcher.STATE,
                telegram_health_watcher.LOGS,
                telegram_health_watcher.status_snapshot,
                telegram_health_watcher.send_health,
            )
            telegram_health_watcher.APP = runtime
            telegram_health_watcher.STATE = state
            telegram_health_watcher.LOGS = logs
            telegram_health_watcher.status_snapshot = lambda: [{"service": "codex-panel", "active": "active", "enabled": "enabled"}]
            telegram_health_watcher.send_health = lambda _reason: (_ for _ in ()).throw(AssertionError("auto report must be suppressed"))
            try:
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    telegram_health_watcher.main()
                log_text = (logs / "telegram_health_watcher.log").read_text(encoding="utf-8")
            finally:
                (
                    telegram_health_watcher.APP,
                    telegram_health_watcher.STATE,
                    telegram_health_watcher.LOGS,
                    telegram_health_watcher.status_snapshot,
                    telegram_health_watcher.send_health,
                ) = originals

        self.assertIn("TELEGRAM_HEALTH_WATCHER=SUPPRESSED_AUTO_DISABLED", out.getvalue())
        self.assertIn("auto_report_enabled=false", log_text)

    def test_task_recovery_preserves_ready_phase_on_empty_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            state = runtime / "state"
            reports = runtime / "reports"
            logs = runtime / "logs"
            state.mkdir()
            reports.mkdir()
            logs.mkdir()
            (state / "task_queue.json").write_text(json.dumps({"tasks": []}), encoding="utf-8")
            (state / "workers.json").write_text(
                json.dumps({"workers": [{"id": "worker-1", "status": "SLEEPING", "current_task": None}]}),
                encoding="utf-8",
            )
            (state / "system_state.json").write_text(
                json.dumps(
                    {
                        "phase": "READY_FOR_NEW_TASKS",
                        "system_state": "READY_FOR_NEW_TASKS",
                        "state": "READY_FOR_NEW_TASKS",
                        "ready_for_new_tasks": True,
                    }
                ),
                encoding="utf-8",
            )

            originals = (
                task_recovery_engine.APP,
                task_recovery_engine.STATE,
                task_recovery_engine.REPORTS,
                task_recovery_engine.LOGS,
            )
            task_recovery_engine.APP = runtime
            task_recovery_engine.STATE = state
            task_recovery_engine.REPORTS = reports
            task_recovery_engine.LOGS = logs
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    task_recovery_engine.main()
            finally:
                (
                    task_recovery_engine.APP,
                    task_recovery_engine.STATE,
                    task_recovery_engine.REPORTS,
                    task_recovery_engine.LOGS,
                ) = originals

            system_state = json.loads((state / "system_state.json").read_text(encoding="utf-8"))

        self.assertEqual(system_state["phase"], "READY_FOR_NEW_TASKS")
        self.assertEqual(system_state["system_state"], "READY_FOR_NEW_TASKS")
        self.assertEqual(system_state["state"], "READY_FOR_NEW_TASKS")

    def test_task_recovery_marks_system_busy_when_active_queue_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            state = runtime / "state"
            reports = runtime / "reports"
            logs = runtime / "logs"
            state.mkdir()
            reports.mkdir()
            logs.mkdir()
            (state / "task_queue.json").write_text(
                json.dumps(
                    {
                        "tasks": [
                            {"id": "OLD", "status": "DEPLOYED", "risk": "low"},
                            {"id": "ACTIVE", "status": "RUNNING", "risk": "medium", "assigned_worker": "worker-1"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (state / "workers.json").write_text(json.dumps({"workers": []}), encoding="utf-8")
            (state / "system_state.json").write_text(
                json.dumps(
                    {
                        "phase": "READY_FOR_NEW_TASKS",
                        "system_state": "READY_FOR_NEW_TASKS",
                        "state": "READY_FOR_NEW_TASKS",
                        "ready_for_new_tasks": True,
                        "production_deployed": True,
                        "repo_changes_applied": True,
                        "production_github_sync": True,
                    }
                ),
                encoding="utf-8",
            )

            originals = (
                task_recovery_engine.APP,
                task_recovery_engine.STATE,
                task_recovery_engine.REPORTS,
                task_recovery_engine.LOGS,
            )
            task_recovery_engine.APP = runtime
            task_recovery_engine.STATE = state
            task_recovery_engine.REPORTS = reports
            task_recovery_engine.LOGS = logs
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    task_recovery_engine.main()
            finally:
                (
                    task_recovery_engine.APP,
                    task_recovery_engine.STATE,
                    task_recovery_engine.REPORTS,
                    task_recovery_engine.LOGS,
                ) = originals

            system_state = json.loads((state / "system_state.json").read_text(encoding="utf-8"))

        self.assertEqual(system_state["phase"], "step_23a_task_recovery_engine_active")
        self.assertEqual(system_state["system_state"], "BUSY")
        self.assertEqual(system_state["state"], "BUSY")
        self.assertEqual(system_state["active_queue_remaining"], 1)
        self.assertFalse(system_state["ready_for_new_tasks"])
        self.assertTrue(system_state["production_deployed"])
        self.assertTrue(system_state["repo_changes_applied"])
        self.assertTrue(system_state["production_github_sync"])

    def test_task_recovery_does_not_downgrade_proposal_done_with_apply_child(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            state = runtime / "state"
            reports = runtime / "reports"
            logs = runtime / "logs"
            workspace = runtime / "workspaces" / "worker_worker-1_PARENT_20260604_000000"
            state.mkdir()
            reports.mkdir()
            logs.mkdir()
            workspace.mkdir(parents=True)
            for name in task_recovery_engine.EXPECTED[:4]:
                (workspace / name).write_text("# ok\n", encoding="utf-8")
            (state / "task_queue.json").write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "id": "PARENT",
                                "status": TASK_STATUS_PROPOSAL_DONE,
                                "risk": "medium",
                                "workspace": str(workspace),
                                "repo_apply_child": "APPLY",
                                "result": "validated_worker_proposal_ready_for_apply",
                                "delivery_level": TASK_STATUS_PROPOSAL_DONE,
                            },
                            {"id": "APPLY", "status": TASK_STATUS_RUNNING, "risk": "medium", "worker_eligible": True},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (state / "workers.json").write_text(json.dumps({"workers": []}), encoding="utf-8")
            (state / "system_state.json").write_text(json.dumps({"ready_for_new_tasks": True}), encoding="utf-8")

            originals = (
                task_recovery_engine.APP,
                task_recovery_engine.STATE,
                task_recovery_engine.REPORTS,
                task_recovery_engine.LOGS,
            )
            task_recovery_engine.APP = runtime
            task_recovery_engine.STATE = state
            task_recovery_engine.REPORTS = reports
            task_recovery_engine.LOGS = logs
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    task_recovery_engine.main()
            finally:
                (
                    task_recovery_engine.APP,
                    task_recovery_engine.STATE,
                    task_recovery_engine.REPORTS,
                    task_recovery_engine.LOGS,
                ) = originals

            queue = json.loads((state / "task_queue.json").read_text(encoding="utf-8"))

        self.assertEqual(queue["tasks"][0]["status"], TASK_STATUS_PROPOSAL_DONE)
        self.assertEqual(queue["tasks"][0]["result"], "validated_worker_proposal_ready_for_apply")
        self.assertEqual(queue["tasks"][0]["delivery_level"], TASK_STATUS_PROPOSAL_DONE)

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
