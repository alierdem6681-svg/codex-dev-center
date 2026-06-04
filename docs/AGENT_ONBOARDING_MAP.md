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
- supervisor/read_only_execution.py içindeki `CHECK_MODE=read_only|dry_run|write_enabled` yazma politikası state/report yazımlarını `write-skipped` kanıtına çevirebilir
- supervisor/production_readiness_suite.py
- supervisor/production_readiness_suite.py `CHECK_MODE=read_only` veya `CHECK_MODE=dry_run` altında state/report yazmadan JSON sonucunda `write_evidence` ve `write_status=completed_with_write_skipped` döndürür
- supervisor/production_readiness_suite.py içindeki `static_non_mutating_contract` simülasyon kapıları
- supervisor/production_readiness_suite.py içindeki staging/rollback `dry_run_non_mutating_contract` doğrulaması
- supervisor/production_readiness_suite.py içindeki `telegram_result_report_flow` kapısı staging health/smoke, rollback planı ve readiness sonucunu Telegram-safe kısa özet sözleşmesiyle doğrular; gerçek Telegram API çağırmaz
- supervisor/task_status_constants.py içindeki dispatch contract metadata normalizasyonu `root_task_id`, `dispatch_id`, `attempt`, `max_attempts`, `last_error_code`, `claimed_at` ve `finished_at` alanlarını varsayılanlar
- supervisor/telegram_asset_safety.py içindeki manifest, limit, checksum, MIME/uzantı, redaction, simulator ve dashboard-safe snapshot sözleşmeleri gerçek Telegram API'ye fallback yapmaz
- supervisor/worker_runner.py worker claim sırasında `worker_id` ve `claimed_at` alanlarını yazar; terminal task statusları yeniden worker-eligible sayılmaz
- supervisor/worker_runner.py içindeki controlled repo apply path allowlist ve PR pipeline kapıları
- supervisor/cto_autonomous_delivery.py içindeki `root-cause-report` komutu `PIPELINE_FAILED` apply child tasklari icin yeni kok task acmadan `root_cause`, `last_error`, `retryable` ve `recommended_fix` alanlarini dondurur
- supervisor/telegram_asset_manifest.py Telegram asset manifest v1 kontratını network kullanmadan doğrular; 20 MB limit, SHA-256, MIME/storage metadata ve forbidden raw/file URL/sensitive field kontrollerini sabitler
- supervisor/telegram_asset_intake.py Telegram `photo`, `document`, caption ve unsupported medya payload'larını ham dosya indirmeden güvenli metadata event'ine sınıflandırır
- supervisor/telegram_direct_cto.py yetkili chat'ten gelen asset medya mesajlarını `Telegram Asset Intake` routed task'ına çevirir; raw `file_id` veya raw payload loglamaz
- tests/safe_test_scratch.py test runtime dosyalarını repo dışı scratch alanına yönlendirir; `TEST_SCRATCH_ROOT`, `RUNNER_TEMP/test-scratch`, `TMPDIR/test-scratch` önceliği, atomik per-test dizin ve repo write guard sözleşmesini tutar
- supervisor/production_deploy_controller.py
- supervisor/github_safe_flow.py
- supervisor/production_environment_manager.py health/smoke yazımlarında aynı read-only/dry-run write policy helper'ını kullanır
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
- Expand state regresyonu `tests/test_runtime_status_model.py` icindeki `DashboardPipelineFlowUiTest` ile stable key, click-intent handler ve refresh state merge sozlesmesini kontrol eder.
- `/api/pipeline-flow` live polling kontrati `serverRevision`, `resetToken`, `requiresUiReset`, `mergePolicy` ve `initialUiDefaults` alanlarini dondurur. Frontend eski veya ayni revision refresh'lerini uygulamaz; reset token degismedikce client-owned stage/expand/filter/scroll state korunmalidir.
- `/api/status` ana ve legacy panelde `qualityGateView` alanini dondurur; dashboard kalite kapisi badge, renk, filtre ve ozet karari icin sadece bu kontrati kullanmalidir. `quality_gate_status` legacy diagnostik bilgi olarak `legacy_quality_gate_status` altinda tasinir ve pozitif READY karari uretmez.
- `web_panel/static/index.html` Gorevler listesi render oncesinde deterministik siralama uygular; `RUNNING`/`Calisiyor` gorevleri ustte kalir, `DEPLOYED`/canli gorevler varsayilan listeden gizlenir ve `Canliya alinanlari goster` checkbox'i ile dahil edilir.
- Gorev filtreleri runtime yenilemelerinde secili degeri korumali ve filtre option HTML'i degismediyse yeniden yazilmamalidir; bu sayede filtre secimi panel davranisini bozmaz.

Controlled apply notu:
- Validated proposal apply isleri izole repo clone/worker branch uzerinde calisir; apply clone icinde yerel `.git/` metadata dizini bulunmalidir.
- Tekil allowlist dosyalari exact match ister; `AGENTS.md.bak` ve `AGENTS.md/child` guvenli repo apply path'i sayilmaz.
- Runtime `state/`, `logs/`, `reports/`, `workspaces/` ve secret/env/token/private key kapsami PR apply disinda kalir.
- Apply raporu `Controlled Apply Checklist` ve `Rollback Note` bolumleriyle patch scope, diff review, secret scan, local pipeline ve production deploy yapılmadı kanitini yazmalidir.
- `PIPELINE_FAILED` apply child tasklari icin yeni kok task acmadan root-cause raporu uretilmeli; `workspace_missing` gibi nedenler son hata, retry edilebilirlik ve onerilen duzeltme ile ayrastirilmalidir.

Safe test scratch notu:
- Testler runtime state, cache, config, log veya output dosyalarını repo içine yazmamalıdır.
- `tests.safe_test_scratch.test_scratch()` aktif test için benzersiz scratch dizini açar, `TMPDIR`, `HOME`, `XDG_CACHE_HOME`, `XDG_CONFIG_HOME` ve test output env değerlerini o alana yönlendirir.
- Scratch root repo içinde çözülürse helper fail eder; debug için `TEST_SCRATCH_KEEP=1` veya `KEEP_TEST_SCRATCH=1` dışında scratch alanı temizlenir.
- `guard_repo_clean()` repo write guard sağlar ve allowlist dışı yeni/değişmiş/silinmiş dosyada test fail eder.

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

Telegram asset intake notu:
- `supervisor/telegram_asset_intake.py` Telegram update payload'ında `message`, `edited_message`, `channel_post` ve `edited_channel_post` alanlarını okur.
- Fotoğraf ve doküman mesajları `file_id_ref`, `file_unique_id`, MIME, boyut, sanitize dosya adı, sanitize caption ve idempotency metadata'sına çevrilir.
- Raw `file_id`, raw payload, token, secret veya header bilgisi intake event/task mesajına yazılmaz.
- Dosya indirme, kalıcı saklama, checksum ve malware scan bu backend sınıflandırıcıda yapılmaz; sonraki asset processing aşamasına bırakılır.
- Desteklenmeyen medya ve limit/allowlist dışı dokümanlar controlled reject olarak işaretlenir.

Read-only / dry-run write policy notu:
- `CHECK_MODE` veya `CODEX_CHECK_MODE` `read_only` ya da `dry_run` ise readiness, drift ve smoke write adapter'lari state/report dosyasi olusturmaz.
- Sonuc payload'lari `mode`, `runtime_write_status`, `write_evidence`, `write_status`, `target`, `operation`, `write_attempted`, `write_status=skipped` ve `skip_reason` alanlariyla kanit dondurur.
- `CHECK_MODE` verilmezse davranis `write_enabled` olarak geriye uyumludur.

Observed issue completion notu:
- Drift registry/settings eksikleri `classify_module_registry_settings_candidates()` ile candidate olarak siniflandirilir; tek drift alert sinyali otomatik registry/settings eklemek icin yeterli degildir.
- Repo apply no-change sonucu `classify_repo_apply_outcome()` ile terminal `NO_CHANGE` veya `DONE` olur; terminal sonuclar retry/backlog enqueue etmez.
- `cto_task_router.classify_task_route()` readiness, audit, risk review, test plan ve proposal-only isleri `Controls / Readiness` lane'ine tasir.
- Worker workspace preflight `bootstrap_diagnostics.json` uretir; missing/invalid bootstrap ana isi baslatmadan acik tanı verir.
- Timeout/usage-limit retry kararlari `retry_policy` idempotency key'i ile ayni task uzerinde tutulur.
- `atomic_json_state_audit()` state JSON ve kalan tmp dosyalarini raporlar; tmp dosyasini otomatik guvenilir state saymaz.
- `worker_runner.repo_apply_stage_plan_lines()` apply control report icinde stage plan, diff review, secret scan, local test, rollback ve production deploy kapisini gorunur yapar.
- `codex_quality_gate` retry simulation raporu `safety_status`, `safety_reasons` ve `required_false_flags` dry-run safety alanlarini uretir.
- `supervisor_cli.reconcile_stale_dispatch_claims()` aktif worker sahipligi olmayan stale claim'leri yeni kok gorev acmadan ayni task uzerinde retry/timeout statüsüne taşır.

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
