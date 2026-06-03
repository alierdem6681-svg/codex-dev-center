# CODEX DEV CENTER ANAYASASI

## 1. Ana Amaç

Bu sistemin amacı, proje geliştirme süreçlerini Codex/CTO mantığıyla yönetmek, görevleri çalışanlara dağıtmak, yapılan tüm geliştirmeleri kaydetmek ve yeni gelen Codex/agent/worker sistemlerinin kaldığı yerden devam edebilmesini sağlamaktır.

## 2. Kalıcı Hafıza Zorunluluğu

Her agent, worker veya Codex oturumu işe başlamadan önce aşağıdaki dosyaları okumalıdır:

1. AGENTS.md
2. constitution/ANAYASA.md
3. docs/ARCHITECTURE.md
4. docs/ROADMAP.md
5. docs/HANDOVER.md
6. memory/project_memory.md

## 3. Çalışma Kuralı

Hiçbir agent doğrudan kontrolsüz canlı değişiklik yapamaz.

Önce görevi anlar, plan çıkarır, dosya değişikliklerini yapar, test eder, log yazar, rapor üretir ve risk seviyesine göre onay ister veya otomatik kapılardan geçer.

## 4. Telegram Kuralı

Kullanıcının Telegram mesajları Codex'e aynen iletilir. Kod çıktısı, uzun terminal çıktısı, diff, stack trace ve log dump Telegram'a gönderilmez; teknik çıktı log dosyasına kaydedilir.

## 5. Çalışan Kuralı

Başlangıç rolleri:

- worker-1: Backend ve altyapı
- worker-2: Frontend ve panel
- worker-3: DevOps, yayına alma ve servisler
- worker-4: Test, kalite ve denetim

## 6. Canlı Ortam Kuralı

Canlıya alma işlemi yalnızca GitHub Actions `Deploy to VM` workflow'u üzerinden yapılabilir. VM'ye doğrudan SSH ile bağlanılamaz, production runtime dosyalarına elle müdahale edilemez ve terminalden production deploy çalıştırılamaz.

Workflow manuel çalışır. Confirm alanına tam olarak `DEPLOY-CODEX-VM` yazılmadan deploy ilerlemez. Hedef VM `codex-dev-center-01`, runtime dizini `/opt/codex-dev-center` olmalıdır.

Kalite kapıları ve risk politikaları zorunludur.

Kritik istisnalar otomatik yapılamaz:

- Secret değerlerini görüntüleme veya değiştirme
- IAM owner/editor yetki değişikliği
- Billing ayarı değiştirme
- Database veri silme
- Geri döndürülemez migration
- DNS/firewall kritik değişiklik
- Google Ads canlı mutate işlemi
- Canlı müşteri/veri kaybı riski taşıyan işlem

## 7. Autonomous Production Delivery

Codex Dev Center uygulamasının kendi repo/app deploy akışı için GitHub Actions manuel yayına alma kapısı kullanılır. Tüm readiness kapıları, ön canlı kapısı, geri alma simülasyonu, secret scan ve forbidden operation scan PASS olmadan production çalışmaz.

Production için staging, production ve rollback komutları environment veya policy default ile tanımlanmalıdır. `CODEX_PRODUCTION_DEPLOY_EXECUTE=1` environment veya policy default olmadan production komutu çalışmaz. `production_deploy_channel=github_actions_manual` olduğunda GitHub Actions dışındaki production deploy denemeleri `github_actions_workflow_required` blocker'ı ile durur.

Codex Dev Center kendi uygulama kapsamında policy default komutlar `state_templates/deploy_policy.json` içinde tanımlıdır. Bu kapsam Google Ads, IAM, secret, billing, database, DNS/firewall veya müşteri verisi mutate işlemlerini kapsamaz.

## 8. Kayıt Zorunluluğu

Her görev için kayıt tutulur:

- Görev ID
- Başlangıç zamanı
- Bitiş zamanı
- Sorumlu çalışan
- Değişen dosyalar
- Test sonucu
- Hata varsa hata özeti
- Son durum
- Devam notu
- Simülasyon kapıları için canlı mutasyon yapılmadığını gösteren kanıt

## 9. Devir Teslim Kuralı

Her geliştirme sonunda HANDOVER.md, ROADMAP.md ve memory/project_memory.md güncellenir.
