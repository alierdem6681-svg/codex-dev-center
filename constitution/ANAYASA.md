# CODEX DEV CENTER ANAYASASI

## 1. Ana Amaç

Bu sistemin amacı, proje geliştirme süreçlerini Codex/CTO mantığıyla yönetmek, görevleri worker'lara dağıtmak, yapılan tüm geliştirmeleri kaydetmek ve yeni gelen Codex/agent/worker sistemlerinin kaldığı yerden devam edebilmesini sağlamaktır.

## 2. Kalıcı Hafıza Zorunluluğu

Her agent, worker veya Codex oturumu işe başlamadan önce aşağıdaki dosyaları okumak zorundadır:

1. /opt/codex-dev-center/constitution/ANAYASA.md
2. /opt/codex-dev-center/docs/ARCHITECTURE.md
3. /opt/codex-dev-center/docs/ROADMAP.md
4. /opt/codex-dev-center/docs/HANDOVER.md
5. /opt/codex-dev-center/state/system_state.json
6. /opt/codex-dev-center/memory/project_memory.md

## 3. Çalışma Kuralı

Hiçbir agent doğrudan kontrolsüz canlı değişiklik yapamaz.

Önce:
- Görevi anlar
- Plan çıkarır
- Dosya değişikliklerini yapar
- Test eder
- Log yazar
- Rapor üretir
- Gerekirse onay ister

## 4. Telegram Kuralı

Kullanıcının Telegram mesajları Codex'e aynen iletilir.

Kullanıcı mesajlarında:
- Özetleme yapılmaz
- Düzeltme yapılmaz
- Yorum eklenmez
- Yönlendirme yapılmaz
- Filtre uygulanmaz

Codex yanıtlarında:
- Normal konuşma aynen gönderilir
- Kod çıktısı, uzun terminal çıktısı, diff, stack trace ve log dump Telegram'a gönderilmez
- Teknik çıktı log dosyasına kaydedilir
- Telegram'a sadece kısa teknik çıktı bildirimi gönderilir

## 5. Worker Kuralı

Worker'lar ayrı görevlerde çalışır.

Başlangıç worker rolleri:

- worker-1: Backend ve altyapı
- worker-2: Frontend ve panel
- worker-3: DevOps, deploy ve servisler
- worker-4: Test, kalite ve denetim

## 6. Canlı Ortam Kuralı

Canlıya alma işlemi sistem tarafından yapılabilir; ancak risk seviyesine göre güvenlik kapıları uygulanır.

Kritik işlemler:
- Production deploy
- Veritabanı migration
- Veri silme
- Secret erişimi
- DNS değişikliği
- Cloud maliyeti artıran işlemler

Bu işlemler loglanmalı, geri dönüş planı üretmeli ve gerekiyorsa kullanıcıdan açık onay istemelidir.

## 7. Kayıt Zorunluluğu

Her görev için kayıt tutulur:

- Görev ID
- Başlangıç zamanı
- Bitiş zamanı
- Sorumlu worker
- Değişen dosyalar
- Test sonucu
- Hata varsa hata özeti
- Son durum
- Devam notu

## 8. Devir Teslim Kuralı

Her geliştirme sonunda HANDOVER.md güncellenir.

Yeni gelen Codex bu dosyayı okuyarak:
- Ne bitti
- Ne yarım kaldı
- Ne riskli
- Sıradaki görev ne
- Hangi dosyalara bakmalı

bilgilerini öğrenir.
