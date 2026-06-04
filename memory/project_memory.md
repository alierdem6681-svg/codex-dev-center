# PROJECT MEMORY

Bu sistem Denizkan Bey'in projelerini Codex/CTO/worker mimarisi ile geliştirmek için kurulmaktadır.

Kullanıcı teknik bilmediğini açıkça belirtmiştir. Bu nedenle sistem:
- Kendi dokümantasyonunu tutmalı
- Kaldığı yerden devam edebilmeli
- Her geliştirmeyi loglamalı
- Her görevi raporlamalı
- Yeni gelen Codex'e durumu anlatabilmeli
- Telegram'da gereksiz kod çıktısı göndermemeli
- Kullanıcı mesajlarını değiştirmeden Codex'e aktarmalıdır

İlk hedef:
- VM üzerinde Codex CLI kurmak
- 4 worker oluşturmak
- CTO/Supervisor katmanı oluşturmak
- Web panel hazırlamak
- Telegram bağlantısını kurmak

## 2026-06-04 Owner Queue Repair Memory

Owner-directed emergency repair was performed directly on VM `codex-dev-center-01` because CTO/worker queue state itself was unhealthy and could not safely receive another queued task.

Key facts:
- Runtime path: `/opt/codex-dev-center`
- Source checkout: `/home/alierdem6681/codex-dev-center-github-export`
- Main archive: `/opt/codex-dev-center/archives/system_repair_20260604_054027`
- Queue cleanup archive: `/opt/codex-dev-center/archives/system_repair_20260604_054027/queue_owner_cleanup`
- Original queue: 1161 tasks
- Cleanup candidates: 719
- Active queue remaining after cleanup: 0
- Cleanup status: `CANCELLED_BY_OWNER_CLEANUP`
- System state after cleanup: `READY_FOR_NEW_TASKS`

Repair code now uses locked/fsynced atomic JSON writes, terminal `NO_CHANGE` for repo apply no-op, safer lifecycle pending counts, duplicate start no-op checks, broader validation false-positive safety phrases, and an owner cleanup script.

## STEP 17A Memory

Kullanıcı bundan sonra her geliştirme sonrası AGENT_ONBOARDING_MAP.md dahil tüm ilgili yaşayan dokümantasyonun güncel tutulmasını istedi. Living Documentation temel politikası ve modül dosyaları oluşturuldu.

## STEP 18I Memory

Telegram görevlerinin yanlışlıkla workerlar tarafından alınması düzeltildi. source=telegram görevleri artık CTO tarafından işleniyor. Telegram CTO cevap döngüsü başarılı şekilde doğrulandı.

STEP 19B-10A Memory
User requires CTO, workers and all future Codex processes to use gpt-5.5 with xhigh reasoning.

## 2026-06-03 Dashboard Controlled Execution Proposal Visibility

Controlled execution proposal durumu dashboard status API'sine `controlled_execution` olarak eklendi. Panel Ayarlar bolumu son controlled execution task/rapor bilgisini ve proposal modunda repo degisikligi ile production deploy'un kapali oldugunu gosterir.

Bu paket production deploy, secret/env/token/private key, IAM, billing, DNS/firewall, destructive database veya Google Ads live mutate islemi yapmadi.

## Autonomous Production Delivery System v1 Memory

2026-06-02 tarihinde Codex Dev Center kendi repo/app deploy akisi icin otomatik production delivery iskeleti eklendi. Production deploy controller, production readiness suite, GitHub safe flow, staging/rollback dokumanlari, production readiness gate, action catalog, dashboard settings ve production policy template dosyalari eklendi. Dashboard Turkce pipeline bolumleriyle genisletildi.

Otomatik production sadece tum readiness kapilari PASS ise, on canli ve geri alma kapilari hazirsa, secret/forbidden scan temizse, staging/production/rollback komutlari runtime env ile tanimliysa ve `CODEX_PRODUCTION_DEPLOY_EXECUTE=1` aciksa calisabilir. Secret, IAM owner/editor, billing, database veri silme, geri dondurulemez migration, kritik DNS/firewall, Google Ads mutate ve canli veri kaybi riski otomatik blokajdir.
## 2026-06-02 Autonomous Production Environment v1

Production deploy blocker'lari giderildi. Sistem artik env eksikliginde BLOCKED kalmadan policy-bound default komutlari kullanir:

- `CODEX_STAGING_DEPLOY_COMMAND={python} supervisor/production_environment_manager.py staging-deploy`
- `CODEX_PRODUCTION_DEPLOY_COMMAND={python} supervisor/production_environment_manager.py production-deploy`
- `CODEX_ROLLBACK_COMMAND={python} supervisor/production_environment_manager.py rollback`
- `CODEX_PRODUCTION_DEPLOY_EXECUTE=1`

Eklenen manager staging'i 18080 portunda, production'i 8080 portunda dogrular. Rollback otomatik `git reset` yapmaz; son saglikli commit ve runtime bilgisi `state/rollback_point.json` icinde korunur.

Kritik dis kapsam ayni kalir: secret/IAM/billing/database/DNS/firewall/Google Ads/customer data mutate yok.

## 2026-06-02 Panel Username/Password Auth v1

Panel tokenli URL yerine kullanici adi/sifre login akisi eklendi. `web_panel/auth.py` PBKDF2 parola hash'i ve imzali session cookie uretir. `web_panel/static/login.html` login ve ilk kullanici kurulum ekranidir.

Runtime secret dosyalari repo disinda kalir:

- `state/panel_auth.json`
- `state/panel_session_secret.txt`

Ilk kullanici varsayilan olarak yalnizca lokal erisimden kurulabilir; uzak kurulum icin `CODEX_PANEL_ALLOW_REMOTE_SETUP=1` gerekir. Otomasyon token query kullanmaz, servis oturum cookie'si uretir.

## 2026-06-02 GitHub Actions VM Deploy Gate v1

Kullanici production dosyalarina dogrudan SSH/VM mudahalesi yapilmamasini, canliya alma isleminin sadece GitHub Actions uzerinden yapilmasini istedi.

Yeni sozlesme:

- Repo: `alierdem6681-svg/codex-dev-center`
- Workflow adi: `Deploy to VM`
- Workflow turu: manuel `workflow_dispatch`
- Confirm alani: `DEPLOY-CODEX-VM`
- VM hedefi: `codex-dev-center-01`
- Runtime dizini: `/opt/codex-dev-center`

`.github/workflows/deploy-vm.yml` GitHub Actions main workflow'u olarak guclendirildi. Workflow self-hosted runner uzerinde confirm, runner hedefi, checkout, preflight, backup, runtime sync, validate, service restart ve smoke check adimlarini calistirir.

Policy `production_deploy_channel=github_actions_manual` oldu. Controller ve production environment manager GitHub Actions disinda production deploy denemesini `github_actions_workflow_required` blocker'i ile durdurur.

Bu paket production deploy calistirmadi; branch/commit/PR hazirlamak icindir.

## 2026-06-02 Panel First User Bootstrap Workflow v1

Canli panel ilk kullanici kurulumu GitHub Actions self-hosted runner uzerinden yapilacak sekilde workflow eklendi.

- Workflow: `Bootstrap Panel User`
- Dosya: `.github/workflows/bootstrap-panel-user.yml`
- Confirm: `BOOTSTRAP-PANEL-USER`
- Secret kaynaklari: `CODEX_PANEL_BOOTSTRAP_USERNAME`, `CODEX_PANEL_BOOTSTRAP_PASSWORD`
- Runtime auth state: `/opt/codex-dev-center/state/panel_auth.json`

Parola repo'ya, dokumantasyona veya loglara yazilmamalidir. Workflow `auth.setup_user()` ile PBKDF2 hash uretir, panel servisini restart eder ve login smoke check calistirir.

## 2026-06-02 Pipeline Observability + QA Hardening v1

Dashboard pipeline gorunurlugu ve deploy QA kapilari genisletildi.

- `Pipeline Gözlemi` dashboard bolumu runner, son deploy run, son smoke, commit, backup ve task-to-deploy marker bilgilerini gosterir.
- Deploy workflow runtime `state/github_actions_status.json` ve `state/pipeline_status.json` yazar.
- Deploy workflow YAML sanity, forbidden executable scan, backup file validation, public health/login ve API auth behavior kontrollerini calistirir.
- VM Smoke Check workflow son smoke sonucunu runtime state'e yazar.
- Production readiness suite `yaml_validation` kapisi eklendi.

Bu paket CTO task-to-deploy zinciri icin non-destructive dashboard/pipeline marker testi olarak kullanilacak.

## 2026-06-03 Dashboard Pipeline Tracking Apply Retry

Legacy `web_panel/server.py` `/api/status` payload'u ana `web_panel/panel_server.py` ile hizalandi. Artik iki panel server da runtime `state/github_actions_status.json` ve `state/pipeline_status.json` dosyalarini dashboard payload'unda `github_actions` ve `pipeline_status` olarak dondurur.

Davranis `tests/test_runtime_status_model.py` icindeki unit test ile sabitlendi. Compile, unit test ve production readiness suite PASS oldu. Bu sandbox'ta git worktree metadata yolu read-only oldugu icin commit/PR olusturma adimi tamamlanamadi. Production deploy, runtime state mutasyonu, secret/env/token/private key, IAM, billing, DNS/firewall, destructive database veya Google Ads live mutate islemi yapilmadi.

## 2026-06-03 Dashboard Pipeline Tracking Validation

Dashboard pipeline tracking icin ek regresyon testi eklendi. Ana panel ve legacy panel `/api/status` payload'u, runtime `state/github_actions_status.json` ve `state/pipeline_status.json` dosyalari henuz yokken de `github_actions` ve `pipeline_status` anahtarlarini bos nesne olarak dondurmek zorundadir.

Compile, `tests.test_runtime_status_model` ve production readiness suite PASS oldu. Git metadata yolu read-only oldugu icin commit/PR olusturma adimi bu sandbox'ta calistirilamadi. Bu paket production deploy, runtime state mutasyonu, secret/env/token/private key, IAM, billing, DNS/firewall, destructive database veya Google Ads live mutate islemi yapmadi.

## 2026-06-02 Worker Lifecycle Smoke Check v1

Deploy ve VM smoke workflow'larina worker lifecycle kapisi eklendi.

- Bos kuyrukta worker servislerinin inactive/sleeping olmasi hata degildir.
- Worker-eligible aktif gorev varken hicbir worker servisi active degilse workflow fail olur.
- Telegram kaynakli veya high/critical approval bekleyen gorevler worker uyandirma sebebi sayilmaz.
- Deploy smoke bu durumda recovery engine ve lifecycle wake dener, sonra tekrar olcer.
- Worker state `IDLE`, `SLEEPING` veya `STOPPED` iken `current_task` dolu kalirsa workflow fail olur.
- Worker state `RUNNING` ve servis inactive ise workflow fail olur.

## 2026-06-03 Quality Gate Simulation Contracts v1

Production readiness suite icindeki restart ve failure injection simülasyonları non-mutating static contract kanıtına bağlandı. `restart_simulation` artık service watchdog restart yolu ve safe rollback sözleşmesini, `failure_injection_simulation` ise JSON hata yakalama, security scan ve critical approval sözleşmesini repo dosyaları üzerinden doğrular.

Bu paket production deploy, secret/env/token/private key, IAM, billing, DNS/firewall, destructive database veya Google Ads live mutate işlemi yapmadı. Davranış `tests/test_runtime_status_model.py` içindeki unit test ile sabitlendi.

## 2026-06-03 Controlled Apply Pipeline v1 Validation

Validated proposal apply worker akışı için repo path doğrulaması güçlendirildi. `supervisor/worker_runner.py` artık apply path'lerini normalize eder, tekil allowlist dosyalarında exact match ister ve `AGENTS.md.bak`, `AGENTS.md/child`, traversal veya runtime `state/` hedeflerini bloklar.

Davranış `tests/test_runtime_status_model.py` içinde Windows path, `./` prefix, exact file allowlist ve traversal örnekleriyle sabitlendi. Bu paket production deploy, secret/env/token/private key, IAM, billing, DNS/firewall, destructive database veya Google Ads live mutate işlemi yapmadı.

## 2026-06-04 Controlled Apply Pipeline Report Checklist

Apply worker raporu artık repo apply PR öncesinde `Controlled Apply Checklist` ve `Rollback Note` bölümlerini üretir. Rapor risk, patch scope dosya sayısı, diff review, secret scan, validation status, local pipeline, production deploy yapılmadı kanıtı ve branch/merge rollback yolunu açıkça yazar.

Davranış `tests/test_runtime_status_model.py` içinde doğrudan rapor bölümü unit testiyle sabitlendi. Bu küçük kapsamlı retry production deploy, runtime state mutasyonu, secret/env/token/private key, IAM, billing, DNS/firewall, destructive database veya Google Ads live mutate işlemi yapmadı.

## 2026-06-03 Staging / Rollback Readiness Apply Validation

Production readiness suite staging ve rollback dry-run sonuçlarını artık non-mutating JSON sözleşmesiyle doğrular. Staging için `dry_run=true` ve `mutating_cloud_operations_performed=false`; rollback için `dry_run=true`, `git_reset_performed=false` ve `data_mutation_performed=false` zorunludur.

Davranış `tests/test_runtime_status_model.py` içinde mutasyon flag'i sapma senaryosuyla sabitlendi. Bu paket production deploy, secret/env/token/private key, IAM, billing, DNS/firewall, destructive database veya Google Ads live mutate işlemi yapmadı.

## 2026-06-03 Queue / Status Normalizer Apply Retry

Queue task status normalizer case, bosluk ve tire aliaslarini standart enumlara cevirecek sekilde guclendirildi. `ready for validation`, `ready-for-validation`, `FAILED-TIMEOUT`, `in-progress` ve `completed` gibi girdiler artik yanlislikla `QUEUED` default'una dusmez.

Davranis `tests/test_runtime_status_model.py` icindeki unit testlerle sabitlendi. Bu paket production deploy, runtime state/log/report mutasyonu, secret/env/token/private key, IAM, billing, DNS/firewall, destructive database veya Google Ads live mutate islemi yapmadi.

## 2026-06-03 Queue / Status Normalizer Separator Hardening

Queue task status normalizer yaygin noktalama/ayirici farklarina karsi guclendirildi. `ready/for.validation` artik `READY_FOR_VALIDATION`, `FAILED.TIMEOUT` artik `FAILED_TIMEOUT` olarak normalize edilir.

Davranis `tests/test_runtime_status_model.py` icindeki unit testlerle sabitlendi. Compile, unit test ve gecici `/tmp` repo kopyasinda production readiness suite PASS oldu. Bu sandbox'ta git metadata yolu read-only oldugu icin commit/push/PR olusturulamadi. Bu paket production deploy, runtime state/log/report mutasyonu, secret/env/token/private key, IAM, billing, DNS/firewall, destructive database veya Google Ads live mutate islemi yapmadi.

## 2026-06-03 Quality Gate Standard Report Apply

Codex quality gate artik production readiness artefact'ini standart kalite raporuna indirger. `supervisor/codex_quality_gate.py standard-report` komutu `quality-gate-report.json` ve `quality-gate-summary.md` uretir; `lint`, `unit_test`, `integration_test` ve `simulation_dry_run` check'lerinden herhangi biri eksik veya basarisizsa sonuc `fail` olur.

Simulasyon dry-run kaniti icin `production_deploy_performed=false`, `staging_deploy_performed=false` ve `mutating_cloud_operations_performed=false` bayraklari zorunludur. Bu paket production deploy, runtime state mutasyonu, secret/env/token/private key, IAM, billing, DNS/firewall, destructive database veya Google Ads live mutate islemi yapmadi.

Local git metadata dizini read-only oldugu icin commit hazirlanamadi. GitHub connector branch/PR cagrisinin iptal edilmesi nedeniyle PR acma adimi tamamlanamadi.

## 2026-06-04 Quality Gate Retry Simulation Apply

Codex quality gate retry simülasyonu eklendi. `supervisor/codex_quality_gate.py retry-simulation` mevcut kalite kapısı test komutlarını değiştirmeden ilk deneme ve en fazla bir retry sonucunu `reports/quality-gate-retry-simulation.json` formatında raporlar.

Rapor her deneme için `command`, `attempt`, `exit_code`, `duration_seconds`, `result`, `failure_hint` ve `retry_changed_result` alanlarını üretir. `standard-report` bu artefact'i `retry_simulation` alanında non-blocking gösterir; retry simülasyonu standard kalite kapısı kararını değiştirmez.

Bu paket production deploy, staging deploy, runtime state/log/report mutasyonu, secret/env/token/private key, IAM, billing, DNS/firewall, destructive database veya Google Ads live mutate işlemi yapmadı.

## 2026-06-04 Dashboard Pipeline Flow Backend v0

Dashboard icin read-only `/api/pipeline-flow` backend kontrati eklendi. `web_panel/pipeline_flow.py` runtime queue, pipeline marker, GitHub Actions marker, deploy ve smoke marker dosyalarini salt okunur okur; task statuslarini merkezi enumlardan sabit stage sirasina mapler.

Guvenlik siniri:
- Endpoint raw kullanici mesaji, uzun description, stdout/stderr, log veya terminal dump dondurmez.
- `DEPLOYED` stage siralamasinda son stage olarak kalir.
- Bos stage, failed, blocked ve approval davranisi unit test ile sabitlendi.

Bu paket production deploy, staging deploy, runtime state/log/report mutasyonu, secret/env/token/private key, IAM, billing, DNS/firewall, destructive database veya Google Ads live mutate islemi yapmadi.

Local JSON validation, compile, `tests.test_runtime_status_model`, gecici `/tmp` git repo kopyasinda production readiness suite, `git diff --check` ve secret pattern scan PASS oldu. Local commit/PR tamamlanamadi: git metadata dizini read-only oldugu icin `git add` basarisiz oldu; GitHub connector branch olusturma cagrisi `user cancelled MCP tool call` sonucu iptal edildi.

## 2026-06-04 Worker Dispatch v2 Apply Retry

Worker Dispatch v2 apply retry kucuk kapsama indirildi. Queue task normalizasyonu artik dispatch contract metadata alanlarini varsayilanlar: `root_task_id`, `dispatch_id`, `worker_id`, `attempt`, `max_attempts`, `last_error_code`, `claimed_at`, `finished_at`.

Worker claim akisi task'i `RUNNING` yaparken `worker_id` ve `claimed_at` yazar. Router subtask metadata ve worker claim metadata davranisi `tests/test_runtime_status_model.py` icinde unit test ile sabitlendi.

Bu paket production deploy, staging deploy, runtime state/log/report mutasyonu, secret/env/token/private key, IAM, billing, DNS/firewall, destructive database veya Google Ads live mutate islemi yapmadi.

## 2026-06-04 Dashboard Gorev Listesi Duzeni Apply

Dashboard Gorevler listesi artik render oncesinde deterministik comparator kullanir. `RUNNING` / `Calisiyor` gorevleri listenin ustunde kalir; canliya alinmis gorevler varsayilan listeden gizlenir ve `Canliya alinanlari goster` checkbox'i ile dahil edilir.

Canli gorev algisi `DEPLOYED`, `isLive`, `liveAt`, `deployment_status`, `delivery_level=DEPLOYED` ve `production_deployed` sinyallerini okur. Filtre option'lari runtime yenilemelerinde gereksiz yeniden yazilmaz, secili filtre korunur.

Davranis `tests/test_dashboard_account_menu_markup.py` icindeki dashboard markup regresyon testiyle sabitlendi. Production deploy, staging deploy, runtime state/log/report mutasyonu, secret/env/token/private key, IAM, billing, DNS/firewall, destructive database veya Google Ads live mutate islemi yapilmadi.

## 2026-06-04 Dashboard Pipeline Expand State Apply

Pipeline Flow ana gorev expand/collapse state'i polling datasindan ayrildi. `web_panel/static/index.html` stable main task key ile `pipelineMainTaskExpanded` map'i tutar; polling refresh yalniz server snapshot'ini yeniler ve kullanicinin actigi/kapattigi ana gorev durumunu resetlemez.

Davranis `tests/test_runtime_status_model.py` icindeki frontend markup sozlesmesiyle sabitlendi. Production deploy, staging deploy, runtime state/log/report mutasyonu, secret/env/token/private key, IAM, billing, DNS/firewall, destructive database veya Google Ads live mutate islemi yapilmadi.

## 2026-06-04 Dashboard Pipeline Expand Click Intent Fix

Pipeline Flow ana gorev ac/kapat tercihi artik `details` `toggle` event'inden degil, kullanicinin `summary` click niyetinden senkron kaydedilir. Bu, live polling DOM'u yenilerken acik/kapat state'inin render kaynakli olaylarla yanlis ezilmesini engeller.

Panel `/health` commit ozeti de deploy marker dosyalarini `system_state.json` commit alanlarindan once okur; GitHub Actions deploy'u sonrasi health eski commit raporlamaz.

Davranis `tests/test_runtime_status_model.py` icindeki `DashboardPipelineFlowUiTest` ve health commit summary regresyon testiyle sabitlendi.

## 2026-06-04 Read-Only Analysis Write Tolerance

Direct CTO read-only sandbox icinde `drift_checker.py` ve `production_readiness_suite.py` rapor/state yazamadiginda artik crash etmez. Suite JSON sonucu uretmeye devam eder ve yazma sonucunu `runtime_write_status` altinda `read_only` olarak raporlar.

Davranis `tests/test_runtime_status_model.py` icindeki read-only write tolerance regresyon testleriyle sabitlendi.

## 2026-06-04 Telegram Asset Manifest Contract Apply

Telegram asset storage backlog icin ilk repo/app degisikligi olarak manifest v1 sozlesmesi sabitlendi. `supervisor/telegram_asset_manifest.py` network kullanmadan manifest alanlarini, SHA-256 formatini, MIME/storage metadata alanlarini, `20971520` byte limitini ve forbidden raw/file URL/sensitive field kontrollerini dogrular.

Fixture setleri `tests/fixtures/telegram_asset_manifest/` altinda tutulur ve `tests/test_telegram_asset_manifest_contract.py` ile valid, boundary, limit-asimi ve forbidden-field davranislari test edilir. `telegram_asset_manifest_contract` modulu state template registry/settings/action catalog icine eklendi.

Bu paket production deploy, staging deploy, canli Telegram API cagrisi, runtime storage mutasyonu, secret/env/token/private key, IAM, billing, DNS/firewall, destructive database veya Google Ads live mutate islemi yapmadi. Repo worktree icinde runtime `state/` dizini yoktu ve olusturulmadi.

## 2026-06-04 Dashboard Pipeline Expand State Tests Apply

Dashboard Pipeline Flow ana gorevleri artik expand/collapse tercihini `main_task_code` / `root_task_id` anahtariyla ayni sayfa oturumunda korur. Polling, stage refresh veya `renderPipelineFlow()` yeniden cizimi kullanicinin kapattigi aktif ana gorevi otomatik tekrar acmaz.

Davranis `tests/test_runtime_status_model.py` icindeki `DashboardPipelineFlowUiTest` regresyon testiyle sabitlendi. Compile, dashboard markup testleri, ana runtime status unittest paketi, `/tmp` kopyasinda production readiness suite, whitespace ve secret pattern diff scan PASS oldu. Production deploy, staging deploy, runtime state/log/report mutasyonu, secret/env/token/private key, IAM, billing, DNS/firewall, destructive database veya Google Ads live mutate islemi yapilmadi.

## 2026-06-04 Dashboard Pipeline Live Polling Contract Apply

Dashboard Pipeline Flow polling kontrati genisletildi. `/api/pipeline-flow` artik `serverRevision`, `resetToken`, `requiresUiReset`, `mergePolicy`, `flowId`, `runId`, `generatedAt` ve `initialUiDefaults` alanlarini dondurur.

Frontend eski/ayni revision response'larini ayni reset token altinda full replace olarak uygulamaz. Reset token degismedikce veya `requiresUiReset=true` gelmedikce active stage ve ana gorev expand/collapse state'i client-owned overlay olarak korunur.

Davranis `tests/test_runtime_status_model.py` icindeki backend kontrat ve frontend markup testleriyle sabitlendi. Production deploy, staging deploy, runtime state/log/report mutasyonu, secret/env/token/private key, IAM, billing, DNS/firewall, destructive database veya Google Ads live mutate islemi yapilmadi.

## 2026-06-04 Dashboard Telegram Asset Inbox Backend Apply

Dashboard Telegram Asset Inbox icin kucuk backend kontrati eklendi. `web_panel/telegram_asset_inbox.py` runtime `state/telegram_asset*` kaynaklarini read-only okur, liste/detay DTO allowlist uretir ve ham Telegram id, chat id, signed URL, storage path/bucket/object key veya secret-like alanlari payload disinda tutar.

Ana panel ve legacy panel `GET /api/dashboard/telegram-assets` ile `GET /api/dashboard/telegram-assets/{asset_id}` endpointlerini ayni helper'a baglar; POST denemeleri read-only 405 dondurur. `tests/test_telegram_asset_inbox.py` redaction, filtre/cursor, single manifest ve panel server wrapper davranisini sabitler.

Bu paket production deploy, staging deploy, canli Telegram API cagrisi, runtime asset storage mutasyonu, secret/env/token/private key, IAM, billing, DNS/firewall, destructive database veya Google Ads live mutate islemi yapmadi. Runtime Telegram asset intake ve dashboard UI tablo/detay gorunumu sonraki kucuk paketlere birakildi.

## 2026-06-04 Telegram Asset Safety Tests Apply

Telegram asset akisi icin ilk non-mutating guvenlik sozlesmesi eklendi. `supervisor/telegram_asset_safety.py` manifest schema, asset sayisi/boyutu, toplam boyut, caption uzunlugu, path traversal, tehlikeli uzanti, MIME/uzanti uyumu, sha256 checksum, secret redaction, simulator-only Telegram send ve dashboard-safe snapshot davranisini dogrular.

Davranis `tests/test_telegram_asset_safety.py` icinde unit test ile sabitlendi. `modules/telegram_asset_safety/` ve `state_templates` kayitlari module/action gorunurlugu icin guncellendi. Bu paket gercek Telegram API cagrisi, asset indirme, production/staging deploy, runtime state/log/workspace mutasyonu, secret/env/token/private key, IAM, billing, DNS/firewall, destructive database veya Google Ads live mutate islemi yapmadi.

## 2026-06-04 Telegram Asset Intake Backend Apply

Telegram CTO hattına gelen medya mesajları için backend sınıflandırıcı eklendi. `supervisor/telegram_asset_intake.py` `message`, `edited_message`, `channel_post` ve `edited_channel_post` payload'larından fotoğraf, doküman, caption, text ve unsupported medya ayrımı yapar.

Direct CTO handler yetkili chat'ten gelen fotoğraf/doküman mesajlarını dosya indirmeden `Telegram Asset Intake` routed task'ına dönüştürür. Raw `file_id` ve raw payload task/log mesajına yazılmaz; hash `file_id_ref`, `file_unique_id`, MIME, boyut, sanitize dosya adı, sanitize caption ve idempotency metadata'sı kullanılır.

Bu paket dosya indirme, kalıcı saklama, checksum, malware scan, production deploy, staging deploy, runtime `state/`, `logs/`, `reports/`, secret/env/token/private key, IAM, billing, DNS/firewall, destructive database veya Google Ads live mutate işlemi yapmadı. Davranış `tests/test_runtime_status_model.py` içindeki Telegram asset intake ve direct CTO routing testleriyle sabitlendi.

Local `git add` git metadata dizini read-only olduğu için çalışmadı. GitHub connector branch oluşturma çağrısı `user cancelled MCP tool call` sonucu tamamlanmadığı için bu sandbox içinde commit/PR açılamadı.

## 2026-06-04 Direct CTO Observed Issue Backlog Routing

Direct CTO Telegram hattı artık `görev olarak aç`, `görevleri aç`, `kendine görev` ve `görevlendir` gibi açık görev üretme ifadelerini action-command olarak ele alır. “10 hata/eksik/sorunu görev olarak aç” sınıfındaki istekler read-only raporla kalmaz; `direct_cto_action_mode` üzerinden 10 parçalı gözlem backlog paketi üretir.

Bu paket read-only/dry-run test modu, güvenli scratch standardı, dashboard quality gate kontratı, drift registry, repo-apply no-change, pipeline failed kök neden raporu, production readiness misroute, worker workspace bootstrap, timeout/backoff ve atomic JSON state audit görevlerini worker'lara dağıtacak şekilde sabitlendi. Davranış `tests/test_runtime_status_model.py` regresyon testleriyle korunur.

## 2026-06-04 Worker Dispatch Claim Race Guard

Worker lifecycle `wake-now` artık worker servislerini başlatmadan önce state'i IDLE yapıp dispatch'i çalıştırır; servis başlatma dispatch sonrasına alınmıştır. `supervisor_cli dispatch` queue/workers dosyalarını lock altında günceller ve önceden atanmış `assigned_worker` değerini idle worker sırası farklı diye başka workera ezmez.

Bu guard, aynı task'ın iki worker tarafından claim edilmesi, recovery task çoğalması ve apply assignment/worker_id tutarsızlığı riskini kapatır. Davranış `tests/test_runtime_status_model.py` içindeki dispatch ve wake-order regresyon testleriyle sabitlendi.

## 2026-06-04 Repo Apply Isolated Clone Guard

Repo apply worker sandbox icinde commit/PR uretebilsin diye apply workspace artik `git worktree` degil, kendi `.git/` metadata dizini olan izole repo clone olarak hazirlanir. Clone origin remote'u kaynak repo remote'una cevrilir, `origin/main` fetch edilir ve worker branch bu referanstan acilir.

Bu guard, `git add` sirasinda sandbox disindaki `.git/worktrees/.../index.lock` yoluna yazma denemesi yuzunden olusan commit/PR hatasini kapatir. Apply clone icinde repo-local git identity ayarlanir ve commit/push stderr bilgisi metadata'ya yazilir. Davranis `tests/test_runtime_status_model.py` icindeki metadata regresyon testiyle sabitlendi.

## 2026-06-04 Pending Dispatch Rebalance Guard

Dispatch artik `PENDING/QUEUED` ve henuz claim edilmemis task'larda tercih edilen worker mesgulse bosta duran worker'a atama yapabilir. `ASSIGNED/RUNNING` task'lar korunur; calisan is baska workera ezilmez.

Bu guard, repo apply child task'larinin tek worker uzerine yigilip diger workerlarin bos kalmasini engeller. Davranis `tests/test_runtime_status_model.py` icindeki busy preassigned worker regresyon testiyle sabitlendi.

## 2026-06-04 Pipeline Failed Root Cause Reporting Apply

`PIPELINE_FAILED` apply child tasklari artik yeni kok backlog task'i acmadan okunabilir kok neden raporu uretebilir. `cto_autonomous_delivery.pipeline_failed_root_cause_report()` task id, parent id, `root_cause`, `last_error`, retry edilebilirlik ve onerilen duzeltme alanlarini dondurur.

`workspace_missing` kok nedeni workspace/repo clone bootstrap kontrolu olarak raporlanir ve unit test ile sabitlenmistir. Bu paket production deploy, staging deploy, runtime state/log/report mutasyonu, secret/env/token/private key, IAM, billing, DNS/firewall, destructive database veya Google Ads live mutate islemi yapmadi.

## 2026-06-04 Read-Only / Dry-Run Test Mode Apply

Readiness, drift ve smoke kontrol yazımları ortak `supervisor/read_only_execution.py` helper'ına bağlandı. `CHECK_MODE=read_only` veya `CHECK_MODE=dry_run` olduğunda state/report dosyası oluşturulmaz; sonuç payload'ı `write_evidence` ve `write_status=completed_with_write_skipped` ile hedef, operasyon ve skip nedenini döndürür.

Varsayılan mod `write_enabled` kaldığı için mevcut write-enabled ortam davranışı geriye uyumludur. Davranış `tests/test_runtime_status_model.py` içinde read-only, dry-run ve smoke write-skip regresyon testleriyle sabitlendi. Production deploy, staging deploy, secret/env/token/private key, IAM, billing, DNS/firewall, destructive database veya reklam platformu live-write yapılmadı.
