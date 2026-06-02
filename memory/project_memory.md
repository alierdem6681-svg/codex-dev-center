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
