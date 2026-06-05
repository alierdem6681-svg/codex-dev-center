# Production Deploy Runbook

Tarih: 2026-06-02

Bu runbook Codex Dev Center uygulamasının kendi panel, CTO, worker, recovery, watchdog, lifecycle ve dashboard akışı içindir. Google Ads, müşteri verisi, IAM, secret, billing, database, DNS veya firewall işlemi bu runbook kapsamına girmez.

## Production Tanımı

Production hedefi GitHub Actions self-hosted runner ile yönetilen VM çalışma zamanıdır:

- VM hedefi: `codex-dev-center-01`
- Runtime dizini: `/opt/codex-dev-center`
- Production dashboard: VM içinde `127.0.0.1:8080`, dış erişimde mevcut statik IP panel adresi
- Staging dashboard: `127.0.0.1:18080`
- Panel servisi: `web_panel/panel_server.py`
- Deploy yöneticisi: `supervisor/production_environment_manager.py`
- Deploy controller: `supervisor/production_deploy_controller.py`
- Panel giriş modu: üyelik/giriş kapalı, doğrudan dashboard erişimi

Production dosyalarına doğrudan SSH ile müdahale edilmez. Backup, validate, restart ve smoke check adımları GitHub Actions self-hosted runner üzerinde çalışır.

## GitHub Actions Kapısı

Canlıya alma sadece GitHub Actions workflow ile yapılır:

- Workflow adı: `Deploy to VM`
- Workflow dosyası: `.github/workflows/deploy-vm.yml`
- Tetikleme: `workflow_dispatch`; tüm gate'ler PASS ise CTO kullanıcıdan ayrıca deploy onayı istemeden tetikleyebilir
- Zorunlu confirm alanı: `DEPLOY-CODEX-VM`
- Runner hedefi: `codex-dev-center-01`
- Runtime dizini: `/opt/codex-dev-center`

Confirm alanı tam olarak `DEPLOY-CODEX-VM` değilse workflow daha checkout öncesinde durur. Bu confirm alanı ayrı insan onayı değil, workflow emniyet kilididir. Runner adı veya hostname `codex-dev-center-01` ile eşleşmezse deploy durur.

Windows geliştirme ortamında systemd yoksa servis keşfi panel portu, process durumu, health endpoint ve runtime state dosyaları üzerinden yapılır. Production restart adımı yalnızca VM runner üzerinde systemd servisleri varsa çalışır.

Runner ön koşulları:

- `python3`
- `tar`
- `rsync`
- `curl`
- `systemctl` erişimi
- `/opt/codex-dev-center` ve `/opt/codex-dev-center-backups` için gerekli sudo yetkisi

## Komutlar

Policy-bound varsayılan komutlar yerel doğrulama ve controller blokajları içindir:

- `CODEX_STAGING_DEPLOY_COMMAND={python} supervisor/production_environment_manager.py staging-deploy`
- `CODEX_PRODUCTION_DEPLOY_COMMAND={python} supervisor/production_environment_manager.py production-deploy`
- `CODEX_ROLLBACK_COMMAND={python} supervisor/production_environment_manager.py rollback`
- `CODEX_PRODUCTION_DEPLOY_EXECUTE=1`

Shell script karşılıkları:

- `scripts/staging_deploy.sh`
- `scripts/production_deploy.sh`
- `scripts/rollback_production.sh`
- `scripts/health_check.sh`
- `scripts/smoke_test.sh`

Bu komutlar production'a doğrudan terminalden deploy etme yolu olarak kullanılmaz. `production_deploy_channel=github_actions_manual` olduğunda controller GitHub Actions dışında production deploy'u `github_actions_workflow_required` blocker'ı ile durdurur. CTO'nun otomatik deploy kararı `supervisor/cto_autonomous_delivery.py` üzerinden gate PASS, branch/PR/merge marker'ı ve kritik işlem taraması ile verilir.

## Sıra

1. GitHub Actions `Deploy to VM` workflow'u manuel çalıştırılır.
2. Confirm alanı `DEPLOY-CODEX-VM` olarak doğrulanır.
3. Runner hedefinin `codex-dev-center-01` olduğu doğrulanır.
4. İstenen branch veya commit checkout edilir.
5. Python compile ve JSON validation çalışır.
6. Production readiness suite çalışır.
7. Mevcut runtime `/opt/codex-dev-center-backups` altına yedeklenir.
8. Repo içeriği `/opt/codex-dev-center` dizinine senkronize edilir.
9. Runtime içinde compile, JSON validation ve non-secret policy sync çalışır.
10. Kurulu systemd servisleri varsa restart edilir.
11. Production health check `127.0.0.1:8080/health` üzerinden geçer.
12. Production smoke check `/` dashboard ve `/api/status` public read-only erişimini doğrular.
13. GitHub Actions step summary deploy, backup ve smoke sonucunu kaydeder.

## Rollback

Rollback mekanizması güvenli ve mantıksaldır. Otomatik `git reset`, veri silme veya irreversible migration yapmaz. Kaydedilen rollback noktası son sağlıklı commit, branch, portlar ve deploy zamanını içerir. Production deploy health/smoke başarısız olursa controller rollback komutunu çağırır.

## Raporlar

- `reports/production_environment_last_report.md`
- `reports/staging_deploy_last_report.md`
- `reports/production_runtime_last_report.md`
- `reports/rollback_production_last_report.md`
- `reports/production_deploy_last_report.md`
- `reports/production_readiness_last_report.md`

## Panel Erişimi

Tokenlı URL ve kullanıcı adı/şifre akışı kullanılmaz. Panel `/` üzerinden doğrudan dashboard'u açar; `/api/status` ve read-only dashboard API'ları cookie veya login gerektirmeden okunabilir.

`/login` eski giriş ekranına gitmez, dashboard'a yönlenir. Auth setup/login endpointleri `auth_disabled` sözleşmesiyle kapalı kalır. Bu görünürlük production deploy, secret/env/token/private key, IAM, billing, DNS/firewall, destructive database veya reklam platformu live-write yetkisi vermez; dışa açık POST operasyonları read-only/gate sınırında kalmalıdır.

## Durdurulacak Riskler

Aşağıdaki işlemler otomatik yapılmaz:

- Secret değerini görüntüleme veya değiştirme
- Token, private key veya env değeri
- IAM owner/editor yetki değişikliği
- Billing değişikliği
- Database veri silme
- Geri döndürülemez migration
- Kritik DNS/firewall değişikliği
- Google Ads canlı mutate
- Canlı müşteri veya veri kaybı riski
