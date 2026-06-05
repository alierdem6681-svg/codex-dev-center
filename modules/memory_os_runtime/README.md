# Memory OS Runtime

Memory OS Runtime defines the safe runtime state contract for project memory records.

It stores only sanitized records under runtime `state/memory_os_runtime.json`, never raw
payloads, credential values, environment values, tokens, private material, or terminal
dumps. Recall helpers return summary items only; raw record content is not included in
dashboard or recall snapshots.

## Contract

- State schema: `memory_os_runtime_state_v1`
- Record schema: `memory_os_record_v1`
- Summary schema: `memory_os_summary_v1`
- Runtime file: `state/memory_os_runtime.json`
- Write path: `supervisor.memory_os_runtime.append_memory_record()`
- Recall path: `supervisor.memory_os_runtime.recall_memory()`
- Health snapshot: `supervisor.memory_os_runtime.build_memory_health_snapshot()`

## Safety Rules

- Sensitive text is redacted before persistence.
- Metadata uses an allowlist; unsafe or credential-like metadata keys are dropped.
- Audit records contain identifiers and counts only, not memory content.
- Unit tests use temporary roots and do not create repo-local runtime state.
