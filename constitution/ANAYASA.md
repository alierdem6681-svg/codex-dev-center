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

Worker dispatch sözleşmesi izlenebilir olmalıdır: queue task kayıtları `root_task_id`, `dispatch_id`, `worker_id`, `attempt`, `max_attempts`, `last_error_code`, `claimed_at` ve `finished_at` alanlarını taşımalı; terminal task statusları yeniden worker kuyruğuna alınmamalıdır.

Paralel worker regression kapısı dört düşük/orta riskli simülasyon task için dispatch, wake, tek claim, tek terminal status ve duplicate claim/terminal olmaması davranışını production deploy yapmadan doğrulamalıdır.

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

Dashboard controlled execution proposal görünürlüğü salt okunurdur. Proposal durumu göstermek production deploy, secret/env/token/private key, IAM, billing, DNS/firewall, destructive database veya reklam platformu canlı yazma yetkisi anlamına gelmez.

Dashboard pipeline tracking görünürlüğü de salt okunurdur. Ana ve legacy panel `/api/status` payload'larında GitHub Actions ve pipeline marker durumunu göstermek production deploy veya kritik altyapı işlemi yetkisi anlamına gelmez.

Dashboard pipeline flow görünürlüğü salt okunurdur. Ana ve legacy panel `/api/pipeline-flow` payload'larında task stage akışını göstermek raw kullanıcı mesajı, uzun açıklama, stdout/stderr, log, terminal dump, production deploy veya kritik altyapı işlemi yetkisi anlamına gelmez.

Telegram asset intake backend fotoğraf ve doküman mesajlarını dosya indirmeden metadata event'ine sınıflandırabilir. Raw `file_id`, raw payload, token, secret, env, header veya private key bilgisi loglanamaz ya da Telegram/task mesajına yazılamaz. Dosya indirme, kalıcı saklama, checksum ve malware scan ayrı güvenlik aşamasına bağlıdır.

Validated proposal apply akışı yalnızca izole git worktree ve ayrı worker branch üzerinde ilerler. PR öncesi exact path allowlist, runtime/secret path blokajı, secret scan ve local pipeline PASS olmadan değişiklik tamamlanmış sayılmaz.
Apply raporu patch scope, diff review, secret scan, local pipeline, production deploy yapılmadı kanıtı ve rollback notu içermelidir.

Kalite kapısı standart raporu mevcut readiness artefact'lerinden `pass` veya `fail` kararı üretir. Eksik artefact, başarısız test veya dry-run dışı simülasyon kanıtı production deploy izni sayılmaz ve canlı mutasyon yetkisi vermez.

Kalite kapısı retry simülasyonu ilk deneme ve en fazla bir retry sonucunu non-blocking raporlar; bu rapor production deploy, secret/env/token/private key, IAM, billing, DNS/firewall, destructive database veya reklam platformu canlı yazma yetkisi vermez.

Read-only ve dry-run analiz modlarında kontrol runner'ları state/report yazamıyorsa crash üretmemeli; yazma niyetini `write-skipped` kanıtı olarak raporlamalıdır. `CHECK_MODE=read_only` veya `CHECK_MODE=dry_run` production deploy, secret/env/token/private key, IAM, billing, DNS/firewall, destructive database veya reklam platformu canlı yazma yetkisi vermez.

Dashboard kalite kapısı görünümü tek kaynaklı olmalıdır. Ana ve legacy panel `/api/status` payload'undaki `qualityGateView`, readiness ve health girdilerinden merkezi olarak üretilir; legacy `quality_gate_status` yalnızca diagnostik/fallback bilgi olarak taşınır ve tek başına pozitif canlıya hazır kararı veremez.

Dashboard ham readiness rapor metnini gösterirken `report_text_status.readiness` metadata'sını da döndürmelidir. Rapor policy güncellemesinden eskiyse veya policy `required_gates` listesini tam yansıtmıyorsa ham PASS metni güncel kanıt sayılmaz ve `UNKNOWN`/stale olarak işaretlenir.

Production readiness sonucu Telegram'a bildirilecekse önce `telegram_result_report_flow` sözleşmesiyle kısa ve güvenli özet doğrulanmalıdır. Bu özet staging health/smoke, rollback planı, readiness sonucu ve production deploy yapılmadı bilgisini taşıyabilir; diff, stdout/stderr, stack trace, raw payload, Telegram `file_id`, secret/env/token/private key değeri veya runtime path bilgisi taşıyamaz ve gerçek Telegram API çağrısı yapmadan test edilir.

Arka plan CTO ACK, progress-aware watchdog ve retryable hata sınıflandırması production readiness içinde ayrı sözleşmeyle doğrulanmalıdır. Aynı Telegram `update_id` için `ack_correlation_id` tek job/tek ACK davranışını korumalı; yalnız stdout gürültüsü anlamlı progress sayılmamalı; timeout/usage-limit/geçici worker hataları retryable, proposal üretmeden biten veya kritik destructive istekler non-retryable/approval kapsamında kalmalıdır.

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

## 10. Telegram Asset Güvenliği

Telegram asset sözleşmeleri gerçek Telegram API'ye fallback yapmadan, secret/env/token/private key değeri okumadan ve runtime state mutasyonu yapmadan test edilir. Asset manifest, limit, checksum, MIME/uzantı ve dashboard hata görünürlüğü redaction kurallarına bağlı kalmalıdır.

## 11. Test Scratch Standardı

Testler ana repo dizinine runtime state, cache, config, log veya output dosyası yazmamalıdır. Test scratch root önceliği `TEST_SCRATCH_ROOT`, `$RUNNER_TEMP/test-scratch`, `$TMPDIR/test-scratch` şeklindedir ve repo içine çözülen scratch root reddedilir.

Her test benzersiz scratch dizini kullanmalı, temp/home/cache/config/output değişkenlerini scratch alanına yönlendirmeli ve allowlist dışı repo mutasyonlarını repo write guard ile fail etmelidir.

## 12. Kontrol Görevleri, Retry ve State Güvenliği

Readiness, audit, risk review, test plan ve proposal-only işler feature delivery gibi canlıya alma işi sayılamaz; `Controls / Readiness` hattında izlenir ve repo apply/canlı mutasyon yetkisi varsayılan olarak kapalıdır.

Repo apply boş diff ürettiğinde hedef zaten sağlanmışsa terminal başarıdır; retry veya yeni backlog görevi açılmaz. Timeout ve usage-limit durumlarında retry kararı aynı task üzerinde idempotency key ile tutulmalıdır.

State JSON yazımları atomik tmp+fsync+rename akışıyla yapılmalı, kalan tmp dosyaları otomatik doğru state kabul edilmemeli ve audit çıktısı secret değerleri loglamamalıdır.

## 13. Apply, Retry ve Claim Onarımı

Repo apply raporları stage plan, diff review, secret scan, local test, rollback note ve production deploy yapılmadı kanıtını ayrı ayrı göstermelidir.

Quality gate retry simülasyonu dry-run safety alanlarını (`safety_status`, `safety_reasons`, `required_false_flags`) üretmelidir.

Worker aktif sahipliği olmayan stale dispatch claim'leri yeni kök görev açmadan aynı task üzerinde retry'a alınmalı; deneme sınırı dolarsa `FAILED_TIMEOUT` terminal statüsü verilmelidir.

Worker claim ve finish akışlarında `task_queue.json` ile `workers.json` aynı worker state transaction lock altında tutarlı güncellenmelidir. Bir worker aynı anda yalnızca bir aktif `current_task` taşıyabilir; aktif `current_task` varken ikinci task claim edilemez.

## 14. Ön Canlı Readiness Wrapper Kuralı

Ön canlı health/smoke kontrolleri production varsayılan wrapperlarıyla çalıştırılmamalıdır. Staging kapısı için `scripts/staging_health_check.sh` ve `scripts/staging_smoke_test.sh` kullanılmalı; bu wrapperlar scope'u explicit `staging` olarak geçirir.

Bu kural production deploy izni, secret/env/token/private key erişimi, IAM, billing, DNS/firewall, destructive database veya reklam platformu canlı yazma yetkisi vermez.

## 15. Worker Bootstrap Preflight Kuralı

Worker bootstrap tanısı repo checkout, local `.git/` metadata ve test yüzeyi gereksinimleri açıkça istenmişse bunları hazır saymadan önce doğrulamalıdır. Repo apply akışı izole clone üzerinde bu sıkı preflight kapısını kullanır; eksik repo veya test yüzeyi `bootstrap_diagnostics.json` içinde açık reason code ile fail olur.

Pipeline analizi ve kalite tanısı gibi işlerde CI/pipeline kanıtı ayrıca istenirse preflight `pipeline_evidence_missing` reason code'u üretmelidir. Bu tanı sadece güvenli marker/dosya adlarını raporlar; log dump veya secret/env/token/private key değeri okumaz.

Bu kontrol secret/env/token/private key değeri okumaz, production deploy yapmaz ve IAM, billing, DNS/firewall, destructive database veya reklam platformu canlı yazma yetkisi vermez.

## 16. Dashboard Nötr Arka Plan Kuralı

Ana dashboard arayüzü doğa/manzara bitmap arka planı kullanmaz. Panel kabuğu nötr solid arka planla kalmalı, scenic asset referansı regression test ile engellenmelidir.

## 17. Dashboard Güncel Görev Listesi Kuralı

Ana dashboard görev listesi varsayılan olarak geçmiş/canlı/kapalı kayıtları veri silmeden UI katmanında gizlemeli ve yalnızca güncel görev bağlamını göstermelidir. Kullanıcı `Geçmiş/canlı kayıtları göster` seçeneğiyle bu kayıtları geçici olarak dahil edebilir. Güncel görev yoksa boş durum açıkça `Güncel görev yok.` olarak görünmelidir.

## 18. Dashboard Doğrudan Erişim Kuralı

Ana dashboard üyelik/login kapısı kullanmadan doğrudan açılmalıdır. `/`, `/index.html`, `/api/status`, `/api/pipeline-flow` ve dashboard read-only API'leri oturum cookie'si istemeden çalışır; eski `/login` bağlantısı dashboard'a yönlenir. Public POST operasyon yüzeyi `dashboard_direct_access_read_only` ile kapalı kalır. Bu kural production deploy, secret/env/token/private key, IAM, billing, DNS/firewall, destructive database veya reklam platformu canlı yazma yetkisi vermez.
