# Staging / Rollback Readiness Plan

Bu plan Codex Dev Center uygulamasının kendi repo/app yayına alma akışı içindir.

## Ön Canlı Kapısı

- Readiness suite PASS olmalı.
- GitHub safe flow secret scan PASS olmalı.
- Ön canlı komutu `CODEX_STAGING_DEPLOY_COMMAND` ile tanımlanmalı.
- Ön canlı smoke test sonucu PASS olmalı.
- Ön canlı adımı canlı müşteri verisi, IAM, secret, billing, DNS/firewall veya Google Ads mutate işlemi yapmamalı.

## Geri Alma Kapısı

- Geri alma komutu `CODEX_ROLLBACK_COMMAND` ile tanımlanmalı.
- Geri alma simülasyonu PASS olmalı.
- Deploy sonrası health check FAIL olursa controller otomatik geri alma başlatabilir.
- Geri alma raporu `reports/rollback_simulation_last_report.md` altında tutulur.

## Yasak Otomatik İşlemler

- Secret değerlerini görüntüleme veya değiştirme
- IAM owner/editor yetki değişikliği
- Billing ayarı değiştirme
- Database veri silme
- Geri döndürülemez migration
- DNS/firewall kritik değişiklik
- Google Ads canlı mutate işlemi
- Canlı müşteri/veri kaybı riski taşıyan işlem

Bu istisnalar gerekiyorsa otomatik yayına alma durur ve risk raporu üretilir.
