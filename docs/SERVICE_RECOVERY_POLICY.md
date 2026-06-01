# SERVICE RECOVERY POLICY

## Amaç

VM yeniden başlasa, servis çökerse veya workerlar durursa sistem kendini toparlamalıdır.

## Otomatik Kalkması Gereken Servisler

- codex-panel.service
- codex-lifecycle.service
- codex-worker-1.service
- codex-worker-2.service
- codex-worker-3.service
- codex-worker-4.service
- codex-watchdog.service

## Recovery Kuralı

Sistem şunları yapmalıdır:

1. VM reboot sonrası servisleri otomatik başlat
2. Panel çalışmıyorsa başlat
3. Lifecycle çalışmıyorsa başlat
4. Kuyrukta iş varsa workerları uyandır
5. Kuyruk boşsa workerları SLEEPING moduna al
6. Drift check çalıştır
7. Health raporu üret
8. Sorunları logs/service_watchdog.log dosyasına yaz
9. Dashboard state dosyasını güncelle

## Kritik Not

Self-healing sistemi düşük/orta riskli servis toparlama işlemleri yapabilir.

Ancak şunları yapamaz:

- Production deploy açmak
- Secret okumak
- IAM yetkisi vermek
- Veritabanı silmek
- GCloud maliyet artıran işlem yapmak
- Google Ads mutate yapmak
