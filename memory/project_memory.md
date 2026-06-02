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
