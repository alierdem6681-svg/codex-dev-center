import json
import tempfile
import unittest
from pathlib import Path

from supervisor import memory_os_runtime


class MemoryOsRuntimeTest(unittest.TestCase):
    def assert_no_sensitive_values(self, payload: dict, sensitive_values: list[str]) -> None:
        encoded = json.dumps(payload, sort_keys=True)
        for value in sensitive_values:
            self.assertNotIn(value, encoded)

    def test_sanitize_record_redacts_content_and_drops_unsafe_metadata(self):
        api_value = "sk-" + "memoryosruntimefakevalue1234567890"
        token_value = "telegram-" + "token-value-that-should-not-persist"
        env_assignment = "OPENAI_API_KEY=" + api_value
        record = {
            "title": "Memory OS devam baglami",
            "content": f"Use {env_assignment} and bot_" + f"token={token_value}",
            "summary": "Runtime kaydi hazirlandi.",
            "tags": ["memory-os", "runtime"],
            "metadata": {
                "task_id": "CTO-ACTION-1",
                "root_task_id": "CTO-MEMORY-OS",
                "api_" + "key": api_value,
                "env": env_assignment,
                "source": "telegram",
            },
        }

        safe = memory_os_runtime.sanitize_memory_record(record)

        self.assertEqual(safe["schema_version"], "memory_os_record_v1")
        self.assertTrue(safe["redaction"]["applied"])
        self.assertIn("metadata.api_key", safe["redaction"]["redacted_fields"])
        self.assertIn("metadata.env", safe["redaction"]["redacted_fields"])
        self.assertNotIn("api-key", safe["metadata"])
        self.assertNotIn("env", safe["metadata"])
        self.assert_no_sensitive_values(safe, [api_value, token_value])
        self.assertIn("[REDACTED", json.dumps(safe, sort_keys=True))
        self.assertFalse(safe["redaction"]["raw_payload_stored"])
        self.assertFalse(safe["redaction"]["credential_values_stored"])
        self.assertFalse(safe["redaction"]["environment_values_stored"])
        self.assertFalse(safe["redaction"]["private_material_stored"])

    def test_append_memory_record_writes_state_and_audit_under_runtime_root(self):
        contract = memory_os_runtime.memory_contract()
        contract["max_records"] = 2
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for index in range(3):
                memory_os_runtime.append_memory_record(
                    root,
                    {
                        "title": f"Memory OS record {index}",
                        "content": f"safe content {index}",
                        "tags": ["memory-os"],
                        "metadata": {"task_id": f"task-{index}", "source": "unit"},
                    },
                    contract=contract,
                )

            state_path = root / contract["runtime_state_file"]
            audit_path = root / "logs" / "cto_audit.ndjson"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            audit_text = audit_path.read_text(encoding="utf-8")

        self.assertEqual(state["schema_version"], "memory_os_runtime_state_v1")
        self.assertEqual(state["record_count"], 2)
        self.assertEqual([item["title"] for item in state["records"]], ["Memory OS record 1", "Memory OS record 2"])
        self.assertIn("memory_os_record_stored", audit_text)
        self.assertNotIn("safe content", audit_text)
        self.assertFalse(state["raw_payload_storage_allowed"])
        self.assertFalse(state["credential_value_storage_allowed"])

    def test_recall_returns_summary_without_raw_content_or_sensitive_query(self):
        api_value = "sk-" + "memoryosqueryfakevalue1234567890"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            memory_os_runtime.append_memory_record(
                root,
                {
                    "title": "Memory OS Runtime Module",
                    "content": "Guvende tutulacak runtime state ve recall sozlesmesi.",
                    "summary": "Runtime state ve recall sozlesmesi hazir.",
                    "tags": ["memory-os", "runtime"],
                    "recall_keys": ["memory-os-runtime"],
                    "metadata": {"task_id": "task-1", "source": "unit"},
                },
            )
            result = memory_os_runtime.recall_memory(root, "memory runtime api_" + f"key={api_value}", limit=3)

        self.assertEqual(result["schema_version"], "memory_os_summary_v1")
        self.assertEqual(result["record_count"], 1)
        self.assertEqual(result["items"][0]["title"], "Memory OS Runtime Module")
        self.assertTrue(result["query_redaction_applied"])
        self.assertFalse(result["raw_content_included"])
        self.assertFalse(result["credential_values_included"])
        self.assert_no_sensitive_values(result, [api_value])

    def test_contract_validation_loads_module_settings(self):
        result = memory_os_runtime.validate_contract()

        self.assertTrue(result["ok"])
        self.assertEqual(result["runtime_state_file"], "state/memory_os_runtime.json")
        self.assertFalse(result["raw_payload_storage_allowed"])
        self.assertFalse(result["credential_value_storage_allowed"])
        self.assertFalse(result["environment_value_storage_allowed"])
        self.assertFalse(result["private_material_storage_allowed"])


if __name__ == "__main__":
    unittest.main()
