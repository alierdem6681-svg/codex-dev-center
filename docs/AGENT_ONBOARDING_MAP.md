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
- supervisor/codex_quality_gate.py içindeki `retry-simulation` komutu non-blocking retry deneme raporu üretir ve standard rapora gömülür
- supervisor/production_readiness_suite.py
- supervisor/production_readiness_suite.py içindeki `static_non_mutating_contract` simülasyon kapıları
- supervisor/production_readiness_suite.py içindeki staging/rollback `dry_run_non_mutating_contract` doğrulaması
- supervisor/task_status_constants.py içindeki dispatch contract metadata normalizasyonu `root_task_id`, `dispatch_id`, `attempt`, `max_attempts`, `last_error_code`, `claimed_at` ve `finished_at` alanlarını varsayılanlar
- supervisor/telegram_asset_safety.py içindeki manifest, limit, checksum, MIME/uzantı, redaction, simulator ve dashboard-safe snapshot sözleşmeleri gerçek Telegram API'ye fallback yapmaz
- supervisor/worker_runner.py worker claim sırasında `worker_id` ve `claimed_at` alanlarını yazar; terminal task statusları yeniden worker-eligible sayılmaz
- supervisor/worker_runner.py içindeki controlled repo apply path allowlist ve PR pipeline kapıları
- supervisor/telegram_asset_manifest.py Telegram asset manifest v1 kontratını network kullanmadan doğrular; 20 MB limit, SHA-256, MIME/storage metadata ve forbidden raw/file URL/sensitive field kontrollerini sabitler
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
- `/api/pipeline-flow` ana ve legacy panelde read-only pipeline stage payload'u dondurur; raw mesaj, uzun description, stdout/stderr, log veya terminal dump dondurmemelidir. `DEPLOYED` stage siralamasinda son stage olarak kalmalidir.
- `web_panel/static/index.html` Pipeline Flow ana gorev expand/collapse state'ini stable main task key ile tutar; polling refresh selected stage veya kullanici toggle state'ini resetlememelidir.
- Expand state regresyonu `tests/test_runtime_status_model.py` icindeki `DashboardPipelineFlowUiTest` ile stable key, toggle handler ve refresh state merge sozlesmesini kontrol eder.
- `/api/pipeline-flow` live polling kontrati `serverRevision`, `resetToken`, `requiresUiReset`, `mergePolicy` ve `initialUiDefaults` alanlarini dondurur. Frontend eski veya ayni revision refresh'lerini uygulamaz; reset token degismedikce client-owned stage/expand/filter/scroll state korunmalidir.
- `web_panel/static/index.html` Gorevler listesi render oncesinde deterministik siralama uygular; `RUNNING`/`Calisiyor` gorevleri ustte kalir, `DEPLOYED`/canli gorevler varsayilan listeden gizlenir ve `Canliya alinanlari goster` checkbox'i ile dahil edilir.
- Gorev filtreleri runtime yenilemelerinde secili degeri korumali ve filtre option HTML'i degismediyse yeniden yazilmamalidir; bu sayede filtre secimi panel davranisini bozmaz.

Controlled apply notu:
- Validated proposal apply isleri izole git worktree/worker branch uzerinde calisir.
- Tekil allowlist dosyalari exact match ister; `AGENTS.md.bak` ve `AGENTS.md/child` guvenli repo apply path'i sayilmaz.
- Runtime `state/`, `logs/`, `reports/`, `workspaces/` ve secret/env/token/private key kapsami PR apply disinda kalir.
- Apply raporu `Controlled Apply Checklist` ve `Rollback Note` bolumleriyle patch scope, diff review, secret scan, local pipeline ve production deploy yapılmadı kanitini yazmalidir.

Queue/status normalizer notu:
- `supervisor/task_status_constants.py` queue task statuslarini merkezi olarak normalize eder.
- Status aliaslari case farki ve yaygin ayirici varyantlariyla okunur; `ready for validation`, `ready-for-validation`, `ready/for.validation`, `FAILED TIMEOUT` ve `FAILED.TIMEOUT` gibi girdiler standart enumlara cevrilir.
- Queue normalizasyonu dispatch contract alanlarını da tamamlar: `root_task_id`, `dispatch_id`, `worker_id`, `attempt`, `max_attempts`, `last_error_code`, `claimed_at`, `finished_at`.
- Worker claim akışı `worker_id` ve `claimed_at` yazar; bu görünürlük production deploy veya runtime state dışı mutasyon yetkisi vermez.
- Bilinmeyen status degerleri guvenli varsayilan olarak `QUEUED` kalir ve `cto_doctor --fix` yalniz runtime kuyrugunda normalizasyon yapar.
- 2026-06-04 owner repair sonrasinda runtime queue bilincli olarak bosaltildi. Snapshot `/opt/codex-dev-center/archives/system_repair_20260604_054027/queue_owner_cleanup` altindadir; yeni gorevler temiz queue uzerinden alinmalidir.

Telegram asset manifest contract notu:
- `telegram_asset_manifest_contract` modulu runtime asset indirme kodu yazilmadan once manifest schema version `1` sozlesmesini sabitler.
- Testler `tests/fixtures/telegram_asset_manifest/` fixture setleriyle gercek Telegram, network veya runtime storage kullanmadan calisir.
- Manifest `policy.max_bytes`, Telegram `file_size` ve original `size_bytes` alanlari `20971520` byte ustune cikarsa test/validator fail olur.
- Manifest icinde raw payload, Telegram file URL veya sensitive credential-like alanlar kabul edilmez.

Dashboard Telegram asset inbox backend notu:
- `web_panel/telegram_asset_inbox.py` runtime `state/telegram_asset*` kaynaklarini read-only okuyarak dashboard liste/detay DTO allowlist uretir.
- Ana ve legacy panel `GET /api/dashboard/telegram-assets` ve `GET /api/dashboard/telegram-assets/{asset_id}` endpointlerini ayni helper'a baglar.
- Payload ham Telegram id, chat id, signed URL, storage path/bucket/object key, secret-like alan, raw message veya upstream payload dondurmemelidir.
- POST veya mutate niyetli endpoint davranisi read-only 405 kalmalidir; runtime Telegram asset intake ve UI tablo/detay gorunumu ayri paketlerde ilerlemelidir.

Telegram asset safety notu:
- `modules/telegram_asset_safety/` ve `supervisor/telegram_asset_safety.py` gelecekteki Telegram asset intake icin non-mutating test sozlesmesini tutar.
- Manifest dogrulama, limitler, checksum, MIME/uzanti eslesmesi, secret redaction, simulator retry/idempotency ve dashboard-safe snapshot davranisi `tests/test_telegram_asset_safety.py` ile sabitlenir.
- Bu sozlesme gercek Telegram API cagrisi, asset indirme, production deploy veya secret/env/token/private key degeri okuma yetkisi vermez.

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
