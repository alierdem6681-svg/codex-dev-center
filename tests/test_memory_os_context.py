import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from supervisor import cto_task_router, direct_cto_async_job  # noqa: E402


class MemoryOsContextTest(unittest.TestCase):
    def test_followup_binds_existing_scope_without_new_root_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            (runtime / "state").mkdir()

            first = cto_task_router.submit_task(
                runtime,
                source="telegram",
                title="Memory OS Modülü",
                message="Memory OS modülünü geliştir ve CTO akışına bağla.",
                requested_by="user-1",
                conversation_id="telegram:123",
                worker_eligible=False,
            )
            second = cto_task_router.submit_task(
                runtime,
                source="telegram",
                title="Memory OS Modülü",
                message="onaylıyorum devam",
                requested_by="user-1",
                conversation_id="telegram:123",
                worker_eligible=False,
            )

            queue = json.loads((runtime / "state" / "task_queue.json").read_text(encoding="utf-8"))
            state = json.loads((runtime / "state" / "memory_os_context.json").read_text(encoding="utf-8"))

        self.assertEqual(len(queue["tasks"]), 1)
        self.assertEqual(second["task"]["id"], first["task"]["id"])
        self.assertTrue(second["memory_os_bound_to_existing_scope"])
        self.assertEqual(queue["tasks"][0]["memory_os_scope_root_task_id"], first["task"]["id"])
        self.assertEqual(queue["tasks"][0]["memory_os_continuations"][0]["event_type"], "explicit_request")
        self.assertEqual(state["last_scope"]["root_task_id"], first["task"]["id"])

    def test_async_prompt_includes_memory_os_context_without_raw_payload_dump(self):
        prompt = direct_cto_async_job.build_prompt(
            "onaylıyorum devam",
            memory_os_context={
                "scope_id": "memory-os:ROOT",
                "root_task_id": "ROOT",
                "conversation_id": "telegram:123",
                "title": "Memory OS Modülü",
                "last_user_text": "Memory OS modülünü geliştir.",
            },
        )

        self.assertIn("MEMORY_OS_CONTEXT_START", prompt)
        self.assertIn("root_task_id=ROOT", prompt)
        self.assertIn("Do not create a duplicate root task", prompt)
        self.assertNotIn("token=", prompt.lower())


if __name__ == "__main__":
    unittest.main()
