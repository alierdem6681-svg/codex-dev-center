# AGENT ONBOARDING MAP

## Amaç

Hafızası olmayan yeni bir ajan bu dosyadan başlayarak tüm sistemi öğrenir.

## Başlangıç Sırası

Yeni ajan sırasıyla şunları okur:

1. docs/AGENT_ONBOARDING_MAP.md
2. prompts/NEW_AGENT_START_PROMPT.md
3. AGENTS.md
4. constitution/ANAYASA.md
5. docs/HANDOVER.md
6. docs/ROADMAP.md
7. memory/project_memory.md
8. state/system_state.json

## Mimari Okuma

Sonra şunları okur:

1. docs/ARCHITECTURE.md
2. docs/MODULAR_ARCHITECTURE_STANDARD.md
3. docs/CTO_FULL_AUTHORITY_POLICY.md
4. docs/WORKER_LIFECYCLE_POLICY.md
5. docs/DRIFT_CONTROL_POLICY.md
6. docs/SERVICE_RECOVERY_POLICY.md

## State Dosyaları

Sonra şunları okur:

1. state/module_registry.json
2. state/module_settings.json
3. state/action_catalog.json
4. state/worker_profiles.json
5. state/task_queue.json
6. state/workers.json
7. state/approval_requests.json
8. state/approval_policy.json
9. state/cto_authority_policy.json
10. state/modular_development_policy.json
11. state/worker_lifecycle_policy.json
12. state/drift_control_policy.json
13. state/codex_execution_policy.json
14. state/deploy_policy.json
15. state/telegram_config.json
16. state/service_recovery_policy.json

## Modül Keşfi

Ajan `modules/` klasörünü tarar.

Her modül için şunları arar:

- README.md
- module.json
- settings.json
- actions.json
- tests/
- service/
- logs/
- handover.md

## Runtime Keşfi

Ajan şu klasörleri inceler:

- supervisor/
- scripts/
- web_panel/
- logs/
- reports/
- workspaces/

Önemli dosyalar:

- supervisor/supervisor_cli.py
- supervisor/lifecycle_manager.py
- supervisor/drift_checker.py
- supervisor/codex_task_executor.py
- supervisor/codex_quality_gate.py
- supervisor/codex_quality_gate.py içindeki `standard-report` komutu readiness artefact'inden standart kalite raporu üretir
- supervisor/production_readiness_suite.py
- supervisor/production_readiness_suite.py içindeki `static_non_mutating_contract` simülasyon kapıları
- supervisor/production_readiness_suite.py içindeki staging/rollback `dry_run_non_mutating_contract` doğrulaması
- supervisor/worker_runner.py içindeki controlled repo apply path allowlist ve PR pipeline kapıları
- supervisor/production_deploy_controller.py
- supervisor/github_safe_flow.py
- supervisor/service_watchdog.py
- scripts/queue_owner_cleanup.py
- web_panel/panel_server.py
- docs/STAGING_ROLLBACK_READINESS_PLAN.md
- docs/PRODUCTION_READINESS_GATE.md
- docs/worker_queue_production_sync_repair_20260604_054726.md

Dashboard status API notu:
- `/api/status` payload'u `controlled_execution` alaninda son controlled execution proposal durumunu, task id'sini, rapor adini ve proposal modunda repo/deploy kapilarinin kapali oldugunu gosterir.
- Ana `web_panel/panel_server.py` ve legacy `web_panel/server.py` `/api/status` payload'lari `github_actions` ve `pipeline_status` alanlarini dondurerek `Pipeline Gözlemi` dashboard bolumunu ayni runtime state dosyalariyla besler.
- Runtime marker dosyalari henuz yoksa bu iki alan bos nesne olarak kalmali; payload anahtarlari kaldirilmamalidir.
- Ana panel `GET /api/account/me` ile secret icermeyen hesap/oturum ozeti dondurur ve `POST /api/account/logout` mevcut logout akisi icin alias olarak calisir.
- Account payload password/hash/salt/session cookie degeri gostermemeli; yalnizca read-only kullanici adi, rol etiketi ve oturum zaman ozeti dondurmelidir.

Controlled apply notu:
- Validated proposal apply isleri izole git worktree/worker branch uzerinde calisir.
- Tekil allowlist dosyalari exact match ister; `AGENTS.md.bak` ve `AGENTS.md/child` guvenli repo apply path'i sayilmaz.
- Runtime `state/`, `logs/`, `reports/`, `workspaces/` ve secret/env/token/private key kapsami PR apply disinda kalir.

Queue/status normalizer notu:
- `supervisor/task_status_constants.py` queue task statuslarini merkezi olarak normalize eder.
- Status aliaslari case farki ve yaygin ayirici varyantlariyla okunur; `ready for validation`, `ready-for-validation`, `ready/for.validation`, `FAILED TIMEOUT` ve `FAILED.TIMEOUT` gibi girdiler standart enumlara cevrilir.
- Bilinmeyen status degerleri guvenli varsayilan olarak `QUEUED` kalir ve `cto_doctor --fix` yalniz runtime kuyrugunda normalizasyon yapar.
- 2026-06-04 owner repair sonrasinda runtime queue bilincli olarak bosaltildi. Snapshot `/opt/codex-dev-center/archives/system_repair_20260604_054027/queue_owner_cleanup` altindadir; yeni gorevler temiz queue uzerinden alinmalidir.

## Servis Keşfi

Ajan şu servisleri kontrol eder:

- codex-panel.service
- codex-lifecycle.service
- codex-worker-1.service
- codex-worker-2.service
- codex-worker-3.service
- codex-worker-4.service
- codex-watchdog.service

## İlk Yanıt Formatı

Yeni ajan dosyaları okuduktan sonra ilk yanıtında şunu vermelidir:

1. Okuduğum ana dosyalar
2. Sistemin mevcut fazı
3. Aktif modüller
4. Kilitli / onay isteyen modüller
5. Worker durumu
6. Servis durumu
7. Görev kuyruğu durumu
8. Sonraki mantıklı görev
9. Riskli noktalar
10. Başlamadan önce onay gerekip gerekmediği

## Ana Kural

Yeni ajan sistemi okumadan işlem yapmaz. Dashboard, handover, roadmap, state ve audit kaydı bırakmadan işi bitirmez.

MODEL POLICY GPT55 XHIGH
New agents must know that CTO, workers and future Codex executions use gpt-5.5 with xhigh reasoning by default.
