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
