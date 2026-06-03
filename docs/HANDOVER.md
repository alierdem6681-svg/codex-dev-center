# HANDOVER

## Son Durum

VM oluşturuldu ve temel Codex Dev Center dizin yapısı kuruldu.

## Yeni Gelen Codex / Agent Önce Ne Yapmalı?

Sırasıyla şu dosyaları oku:

1. constitution/ANAYASA.md
2. docs/ARCHITECTURE.md
3. docs/ROADMAP.md
4. docs/HANDOVER.md
5. state/system_state.json
6. memory/project_memory.md

## Şu Anki Öncelik

Codex CLI ve temel geliştirme araçlarını kur.

## Dikkat Edilecekler

Kullanıcının teknik bilgisi düşük. Tüm işlemler tek parça terminal paketleriyle yapılmalı.

Telegram tarafında:
- Kullanıcı mesajları aynen geçirilmeli
- Codex normal cevapları aynen gönderilmeli
- Sadece teknik çıktı Telegram'a gönderilmemeli

---

## STEP 17A Tamamlandı

Living Documentation temel politikası eklendi.

Oluşturulanlar:
- docs/LIVING_DOCUMENTATION_POLICY.md
- modules/living_documentation_guard/module.json
- modules/living_documentation_guard/settings.json
- modules/living_documentation_guard/actions.json

Sonraki adım:
STEP 17B ile module_registry, action_catalog ve system_state güncellenecek.

## STEP 18I Telegram CTO Loop Fixed

Telegram → Bridge → Task Queue → CTO → Telegram cevap döngüsü çalışıyor.

Düzeltmeler:
- Workerlar artık source=telegram görevlerini almıyor.
- Telegram görevleri sadece CTO tarafından işleniyor.
- CTO cevap verince görev DONE oluyor.
- Beklenen sonuç: telegram_cto_v1_replied.

STEP 19B-10A Model Policy
Codex model policy documented: model=gpt-5.5, reasoning=xhigh, bubblewrap installed, read-only exec verified.

---

## Dashboard Controlled Execution Proposal Visibility

Tarih: 2026-06-03

Eklenenler:
- `web_panel/panel_server.py` ve legacy `web_panel/server.py` status payload'u `controlled_execution` ozeti dondurur.
- Dashboard Ayarlar bolumu son controlled execution task/rapor durumunu ve proposal modunun repo mutation/deploy kapali oldugunu gosterir.
- `state_templates/dashboard_settings.json` ve `state_templates/module_settings.json` icinde `show_controlled_execution_status` bayragi eklendi.

Not:
- Bu paket production deploy calistirmadi.
- Runtime `state/` dosyalari repo tarafinda ignore edildigi icin repo icinde state dosyasi olusturulmadi.

---

## Autonomous Production Delivery System v1

Tarih: 2026-06-02

Eklenenler:
- `supervisor/production_deploy_controller.py`
- `supervisor/production_readiness_suite.py`
- `supervisor/github_safe_flow.py`
- `docs/STAGING_ROLLBACK_READINESS_PLAN.md`
- `docs/PRODUCTION_READINESS_GATE.md`
- `state_templates/action_catalog.json`
- `state_templates/dashboard_settings.json`
- `state_templates/production_policy.json`
- `state_templates/production_readiness_policy.json`
- `state_templates/github_safe_flow_policy.json`

Dashboard artik Canli Ortam hazirlik durumu, test kapilari, On Canli, Geri Alma, son Yayina Alma, otomatik yayina alma ayari, GitHub senkronizasyonu, hata/riskler ve Calisan/Gorev Kuyrugu/Toparlama durumlarini gosterir.

Canli ortam notu:
- Gercek staging/production/rollback komutlari environment ile tanimlanmadan canli deploy calismaz.
- `CODEX_PRODUCTION_DEPLOY_EXECUTE=1` olmadan production komutu calismaz.
- Kritik istisnalar otomatik bloklanir.

---

## Autonomous Production Environment v1

Tarih: 2026-06-02

Eksik deploy target blocker'lari policy-bound default komutlarla kapatildi.

Eklenenler:
- `supervisor/production_environment_manager.py`
- `scripts/staging_deploy.sh`
- `scripts/production_deploy.sh`
- `scripts/rollback_production.sh`
- `scripts/health_check.sh`
- `scripts/smoke_test.sh`
- `docs/PRODUCTION_DEPLOY_RUNBOOK.md`
- `docs/AUTONOMOUS_PRODUCTION_POLICY.md`

Yeni production tanimi:
- Codex Dev Center paneli ve CTO/worker/recovery/watchdog/lifecycle runtime akisi.
- Production portu: 8080.
- Staging portu: 18080.
- Google Ads, IAM, secret, billing, database, DNS/firewall veya musteri verisi mutate yok.

Deploy controller artik env yoksa `state_templates/deploy_policy.json` icindeki default komutlari kullanir. `CODEX_PRODUCTION_DEPLOY_EXECUTE=1` default policy ile tanimlidir.

---

## Panel Username/Password Auth v1

Tarih: 2026-06-02

Panel tokenli URL yerine kullanici adi/sifre oturumuna tasindi.

Eklenenler:
- `web_panel/auth.py`
- `web_panel/static/login.html`

Yeni davranis:
- `/login` kullanici adi/sifre ekrani gosterir.
- Ilk kullanici sadece lokal erisimden veya `CODEX_PANEL_ALLOW_REMOTE_SETUP=1` ile olusturulabilir.
- Sifre hash'i runtime `state/panel_auth.json` icinde PBKDF2 olarak tutulur.
- Session secret runtime `state/panel_session_secret.txt` icinde tutulur.
- Repo icine sifre, token veya session secret yazilmaz.
- Deploy health/smoke otomasyonu query token yerine imzali servis oturumu kullanir.

---

## GitHub Actions VM Deploy Gate v1

Tarih: 2026-06-02

Yeni production kurali:
- VM'ye dogrudan SSH ile baglanma yok.
- Production runtime dosyalarina elle mudahale yok.
- Canliya alma sadece GitHub Actions `Deploy to VM` workflow'u ile yapilir.
- Workflow manuel calisir ve confirm alani tam olarak `DEPLOY-CODEX-VM` ister.
- Runner hedefi `codex-dev-center-01`, runtime dizini `/opt/codex-dev-center`.

Guncellenen deploy workflow:
- `.github/workflows/deploy-vm.yml`

Guncellenenler:
- `supervisor/production_environment_manager.py`
- `supervisor/production_deploy_controller.py`
- `supervisor/production_readiness_suite.py`
- `state_templates/deploy_policy.json`
- `state_templates/production_policy.json`
- `state_templates/production_readiness_policy.json`
- `state_templates/dashboard_settings.json`
- `state_templates/module_settings.json`
- `state_templates/action_catalog.json`
- `state_templates/module_registry.json`
- `docs/PRODUCTION_DEPLOY_RUNBOOK.md`
- `docs/AUTONOMOUS_PRODUCTION_POLICY.md`

Beklenen sonuc:
- Local/controller production deploy denemesi GitHub Actions disinda `github_actions_workflow_required` blocker'i ile durur.
- GitHub Actions workflow'u backup, validate, runtime sync, service restart ve smoke check adimlarini self-hosted runner uzerinden yurutur.
- Bu paket production deploy calistirmadi; sadece repo, policy ve workflow hazirligi yapildi.

---

## Panel First User Bootstrap Workflow v1

Tarih: 2026-06-02

Eklenenler:
- `.github/workflows/bootstrap-panel-user.yml`

Yeni davranis:
- Ilk panel kullanicisi VM'ye SSH kullanmadan GitHub Actions self-hosted runner uzerinden olusturulur.
- Workflow adi `Bootstrap Panel User`.
- Confirm alani `BOOTSTRAP-PANEL-USER` ister.
- Kullanici adi ve sifre repo'ya yazilmaz; `CODEX_PANEL_BOOTSTRAP_USERNAME` ve `CODEX_PANEL_BOOTSTRAP_PASSWORD` GitHub Secrets uzerinden okunur.
- Workflow auth state'i runtime `state/panel_auth.json` icinde PBKDF2 hash olarak olusturur, `codex-panel` servisini restart eder ve login smoke check calistirir.

---

## Pipeline Observability + QA Hardening v1

Tarih: 2026-06-02

Eklenenler:
- Dashboard `Pipeline Gözlemi` bölümü.
- Runtime `state/github_actions_status.json` ve `state/pipeline_status.json` okuma desteği.
- Deploy workflow YAML sanity, forbidden executable scan, backup file validation, public health/login, unauthorized/authorized API behavior check ve runtime pipeline state yazımı.
- VM Smoke Check workflow runtime smoke state yazımı.
- Production readiness suite `yaml_validation` kapısı.

Amaç:
- CTO task-to-deploy zinciri için güvenli, küçük ve non-destructive bir dashboard/pipeline marker değişikliğini PR/merge/deploy akışından geçirmek.
- Son deploy run ID, commit, runner, smoke, backup ve zincir test sonucunu dashboard görünürlüğüne almak.

Canli dogrulama:
- Deploy run: `26814905600` PASS.
- Post-deploy smoke run: `26814934445` PASS.
- Public health: `http://34.185.153.184:8080/health` 200.
- Login page: `http://34.185.153.184:8080/login` 200.
- Dashboard `Pipeline Gözlemi`: PASS.
- Runtime marker: `pipeline_status.task_to_deploy_test=PASS`.

---

## Worker Lifecycle Smoke Check v1

Tarih: 2026-06-02

Eklenenler:
- `scripts/worker_lifecycle_check.py`
- Deploy ve VM smoke workflow'larında worker lifecycle kapısı.

Yeni davranis:
- Kuyrukta worker-eligible aktif görev varsa en az bir worker servisinin aktif olması zorunludur.
- `source=telegram` görevleri CTO tarafına ayrıldığı için worker uyandırma sebebi sayılmaz.
- Yüksek/kritik risk görevleri approval beklediği için worker uyandırma sebebi sayılmaz.
- Kuyrukta worker-eligible görev yoksa worker servislerinin sleeping/inactive olması beklenen idle davranış olarak kabul edilir.
- Deploy smoke kapısı gerekirse recovery + lifecycle wake dener ve tekrar ölçer.
- `IDLE`, `SLEEPING` veya `STOPPED` worker üstünde `current_task` dolu kalırsa kapı fail olur.
- `RUNNING` worker current_task taşırken servis aktif değilse kapı fail olur.

---

## Quality Gate Simulation Contracts v1

Tarih: 2026-06-03

Görev: CTO-APPLY-20260603-161439 / CTO-DISPATCH-20260603-072048-CTO-AUTO-04-QUALITY-GATE-SIMULATION

Eklenenler:
- `supervisor/production_readiness_suite.py` içinde restart ve failure injection simülasyonları `static_non_mutating_contract` kanıtına bağlandı.
- `tests/test_runtime_status_model.py` simülasyon sözleşmelerinin PASS ve non-mutating olduğunu doğrular.
- `state_templates/module_registry.json`, `state_templates/module_settings.json` ve `state_templates/action_catalog.json` production readiness simülasyon sözleşmesini görünür kılar.

Yeni davranış:
- `restart_simulation` canlı servis restart etmeden service watchdog ve safe rollback sözleşmesini kontrol eder.
- `failure_injection_simulation` canlı işlem yapmadan JSON hata yakalama, security scan ve critical approval sözleşmesini kontrol eder.
- Production deploy, secret, IAM, billing, DNS/firewall, database veya Google Ads live mutate yapılmadı.
