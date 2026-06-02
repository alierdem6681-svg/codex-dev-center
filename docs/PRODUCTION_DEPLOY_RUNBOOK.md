# Production Deploy Runbook

Tarih: 2026-06-02

Bu runbook Codex Dev Center uygulamasının kendi panel, CTO, worker, recovery, watchdog, lifecycle ve dashboard akışı içindir. Google Ads, müşteri verisi, IAM, secret, billing, database, DNS veya firewall işlemi bu runbook kapsamına girmez.

## Production Tanımı

Production hedefi yerel Codex Dev Center çalışma zamanıdır:

- Production dashboard: `127.0.0.1:8080`
- Staging dashboard: `127.0.0.1:18080`
- Panel servisi: `web_panel/panel_server.py`
- Deploy yöneticisi: `supervisor/production_environment_manager.py`
- Deploy controller: `supervisor/production_deploy_controller.py`
- Panel giriş modu: kullanıcı adı/şifre, imzalı oturum çerezi

Windows ortamında systemd yoksa servis keşfi panel portu, process durumu, health endpoint ve runtime state dosyaları üzerinden yapılır.

## Komutlar

Policy-bound varsayılan komutlar:

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

## Sıra

1. Git clean kontrolü yapılır.
2. GitHub `origin/main` senkronu doğrulanır.
3. Secret scan ve forbidden operation scan çalışır.
4. Python compile ve JSON validation çalışır.
5. Unit, integration, regression, worker/queue/recovery, dashboard ve Telegram smoke kapıları geçer.
6. Staging 18080 portunda ayağa kalkar.
7. Staging health ve smoke test geçer.
8. Rollback simulation geçer.
9. Production 8080 portunda doğru repo köküyle çalışır.
10. Production health ve smoke test geçer.
11. Rollback noktası `state/rollback_point.json` içine kaydedilir.
12. Son raporlar `reports/` altında güncellenir.

## Rollback

Rollback mekanizması güvenli ve mantıksaldır. Otomatik `git reset`, veri silme veya irreversible migration yapmaz. Kaydedilen rollback noktası son sağlıklı commit, branch, portlar ve deploy zamanını içerir. Production deploy health/smoke başarısız olursa controller rollback komutunu çağırır.

## Raporlar

- `reports/production_environment_last_report.md`
- `reports/staging_deploy_last_report.md`
- `reports/production_runtime_last_report.md`
- `reports/rollback_production_last_report.md`
- `reports/production_deploy_last_report.md`
- `reports/production_readiness_last_report.md`

## Panel Girişi

Tokenlı URL kullanılmaz. Panel `/login` üzerinden kullanıcı adı ve şifre ister. İlk kullanıcı runtime içinde oluşturulur; parola hash'i `state/panel_auth.json`, session secret ise `state/panel_session_secret.txt` altında tutulur. Bu dosyalar repo'ya yazılmaz.

Uzak sunucuda ilk kullanıcı kurulumu güvenlik gereği varsayılan olarak kapalıdır. Uzak ilk kurulum gerekirse VM içinde `CODEX_PANEL_USERNAME` ve `CODEX_PANEL_PASSWORD` verilerek servis başlatılır veya `CODEX_PANEL_ALLOW_REMOTE_SETUP=1` bilinçli olarak açılır.

## Durdurulacak Riskler

Aşağıdaki işlemler otomatik yapılmaz:

- Secret değerini görüntüleme veya değiştirme
- IAM owner/editor yetki değişikliği
- Billing değişikliği
- Database veri silme
- Geri döndürülemez migration
- Kritik DNS/firewall değişikliği
- Google Ads canlı mutate
- Canlı müşteri veya veri kaybı riski
