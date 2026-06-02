# CTO Autonomous Delivery Mode

Tarih: 2026-06-02

CTO stable olana kadar tek görevli production delivery modunda çalışır.

## Roller

- CTO: görevi alır, risk sınıflandırır, worker atar, worker çıktısını denetler, gate sonuçlarını izler, deploy kararını verir, health check ve rollback sürecini yönetir.
- Worker: kendisine atanan işi izole akışta hazırlar veya uygular; CTO yerine production deploy kararı vermez.
- Windows Codex: CTO'yu GitHub ve SSH üzerinden izler, yetki/pipeline/runtime/worker engellerini düzeltir.

## Production Kuralı

Tüm zorunlu gate'ler PASS ise normal Codex Dev Center app deploy'u için ayrıca kullanıcı onayı istenmez. CTO GitHub Actions `Deploy to VM` workflow'unu `DEPLOY-CODEX-VM` emniyet anahtarıyla tetikleyebilir.

Gate PASS değilse deploy yapılmaz. CTO hatayı çözer, worker'a düzeltme yaptırır, pipeline'ı tekrar çalıştırır ve yalnızca PASS sonrası production'a alır.

## Kritik Bloklar

Aşağıdakiler otomatik yapılmaz:

- Secret, token, private key veya env değerini görüntüleme/değiştirme
- Credential rotation
- IAM owner/editor değişikliği
- Billing değişikliği
- Firewall veya DNS değişikliği
- Database destructive operation veya geri döndürülemez migration
- Google Ads canlı mutate
- Canlı müşteri/veri kaybı riski

Bu task'lar `APPROVAL_REQUIRED` veya `BLOCKED` kalır.

## Stable Eşiği

Başlangıçta `max_parallel_tasks=1`. En az 3 düşük riskli task worker üzerinden branch/PR/merge, readiness, deploy, health ve smoke adımlarını başarıyla tamamladıktan sonra VM kaynakları uygunsa paralellik 2'ye çıkarılabilir.
