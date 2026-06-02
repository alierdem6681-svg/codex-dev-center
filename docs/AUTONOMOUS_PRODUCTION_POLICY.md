# Autonomous Production Policy

Tarih: 2026-06-02

Codex Dev Center kendi uygulama kapsamında production'a manuel onay beklemeden geçebilir. Bu yetki sadece tüm kalite kapıları PASS olduğunda geçerlidir.

## Otomatik Geçiş Şartları

Production deploy ancak şu şartların tamamı sağlanırsa çalışır:

- Production readiness suite `PASS`
- Deploy script ve command policy kontrolü `PASS`
- Secret leakage scan `PASS`
- Forbidden operation scan `PASS`
- Git clean kontrolü `PASS`
- GitHub remote sync kontrolü `PASS`
- Staging deploy `PASS`
- Staging health check `PASS`
- Staging smoke test `PASS`
- Rollback simulation `PASS`
- Production health check `PASS`
- Production smoke test `PASS`
- Rollback noktası kaydı `PASS`

## Otomatik Komut Kaynağı

Env değişkenleri tanımlıysa önceliklidir. Tanımlı değilse policy default kullanılır:

- `state_templates/deploy_policy.json`
- `state_templates/production_policy.json`
- `state_templates/module_settings.json`
- `state_templates/action_catalog.json`
- `state_templates/module_registry.json`

Bu nedenle eksik env sistemi BLOCKED bırakmaz; güvenli default komutlar controller tarafından çözülür.

## Kritik İstisnalar

Aşağıdaki konular otomatik production kapsamı dışındadır ve ayrı risk raporu ister:

- Secret/IAM/billing işlemi
- Database veri silme veya irreversible migration
- DNS/firewall kritik değişikliği
- Google Ads canlı mutate
- Canlı müşteri veya veri kaybı riski

## Production Sonrası

Deploy tamamlandıktan sonra şu kontroller yapılır:

- Health check
- Smoke test
- Dashboard status doğrulaması
- Telegram bridge statik smoke
- Worker/queue/recovery state görünürlüğü
- Rollback point doğrulaması
- Yönetici özeti raporu
