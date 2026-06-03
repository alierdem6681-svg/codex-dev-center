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

## STEP 17A Memory

Kullanıcı bundan sonra her geliştirme sonrası AGENT_ONBOARDING_MAP.md dahil tüm ilgili yaşayan dokümantasyonun güncel tutulmasını istedi. Living Documentation temel politikası ve modül dosyaları oluşturuldu.

## STEP 18I Memory

Telegram görevlerinin yanlışlıkla workerlar tarafından alınması düzeltildi. source=telegram görevleri artık CTO tarafından işleniyor. Telegram CTO cevap döngüsü başarılı şekilde doğrulandı.

STEP 19B-10A Memory
User requires CTO, workers and all future Codex processes to use gpt-5.5 with xhigh reasoning.

## 2026-06-03 Dashboard Controlled Execution Proposal Visibility

Controlled execution proposal durumu dashboard status API'sine `controlled_execution` olarak eklendi. Panel Ayarlar bolumu son controlled execution task/rapor bilgisini ve proposal modunda repo degisikligi ile production deploy'un kapali oldugunu gosterir.

Bu paket production deploy, secret/env/token/private key, IAM, billing, DNS/firewall, destructive database, credential rotation veya Google Ads live mutate islemi yapmadi.

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

Davranis `tests/test_runtime_status_model.py` icindeki unit test ile sabitlendi. Compile, unit test ve production readiness suite PASS oldu. Bu sandbox'ta git worktree metadata yolu read-only oldugu icin commit/PR olusturma adimi tamamlanamadi. Production deploy, runtime state mutasyonu, secret/env/token/private key, IAM, billing, DNS/firewall, destructive database, credential rotation veya Google Ads live mutate islemi yapilmadi.

## 2026-06-03 Dashboard Pipeline Tracking Validation

Dashboard pipeline tracking icin ek regresyon testi eklendi. Ana panel ve legacy panel `/api/status` payload'u, runtime `state/github_actions_status.json` ve `state/pipeline_status.json` dosyalari henuz yokken de `github_actions` ve `pipeline_status` anahtarlarini bos nesne olarak dondurmek zorundadir.

Compile, `tests.test_runtime_status_model` ve production readiness suite PASS oldu. Git metadata yolu read-only oldugu icin commit/PR olusturma adimi bu sandbox'ta calistirilamadi. Bu paket production deploy, runtime state mutasyonu, secret/env/token/private key, IAM, billing, DNS/firewall, destructive database, credential rotation veya Google Ads live mutate islemi yapmadi.

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

Davranış `tests/test_runtime_status_model.py` içinde Windows path, `./` prefix, exact file allowlist ve traversal örnekleriyle sabitlendi. Bu paket production deploy, secret/env/token/private key, IAM, billing, DNS/firewall, destructive database, credential rotation veya Google Ads live mutate işlemi yapmadı.

## 2026-06-03 Staging / Rollback Readiness Apply Validation

Production readiness suite staging ve rollback dry-run sonuçlarını artık non-mutating JSON sözleşmesiyle doğrular. Staging için `dry_run=true` ve `mutating_cloud_operations_performed=false`; rollback için `dry_run=true`, `git_reset_performed=false` ve `data_mutation_performed=false` zorunludur.

Davranış `tests/test_runtime_status_model.py` içinde mutasyon flag'i sapma senaryosuyla sabitlendi. Bu paket production deploy, secret/env/token/private key, IAM, billing, DNS/firewall, destructive database, credential rotation veya Google Ads live mutate işlemi yapmadı.
