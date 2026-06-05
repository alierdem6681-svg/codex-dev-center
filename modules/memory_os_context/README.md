# Memory OS Context Binding

This module records the safe runtime contract for Memory OS continuation binding.

It keeps Direct CTO, async job, action mode and worker dispatch flows on the same active Memory OS scope when the same conversation sends short continuation or approval messages such as `devam`, `onayliyorum` or `gelistirmeye baslayalim`.

Safety boundaries:
- Does not store raw Telegram payloads.
- Does not store secret, env, token or private key values.
- Does not grant production deploy authority.
- Does not create duplicate Memory OS root tasks when an active same-conversation scope exists.

Primary implementation:
- `supervisor/memory_os_context.py`
- `supervisor/cto_task_router.py`
- `supervisor/direct_cto_action_mode.py`
- `supervisor/direct_cto_async_job.py`
- `supervisor/telegram_direct_cto.py`
- `supervisor/supervisor_cli.py`

Regression command:

```bash
python3 -m unittest tests.test_runtime_status_model.WorkerStatusModelTest.test_memory_os_router_followup_binds_existing_scope_without_new_root tests.test_runtime_status_model.WorkerStatusModelTest.test_action_mode_memory_os_children_share_router_root_and_followup_is_idempotent tests.test_runtime_status_model.WorkerStatusModelTest.test_telegram_memory_os_approval_resolves_last_scope tests.test_runtime_status_model.WorkerStatusModelTest.test_async_prompt_includes_memory_os_context tests.test_runtime_status_model.BacklogDispatcherModelTest.test_dispatch_preserves_memory_os_scope_context_on_claim
```
