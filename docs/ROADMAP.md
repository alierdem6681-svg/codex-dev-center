# ROADMAP

## Faz 1 - Temel VM ve Hafıza

- [x] VM oluştur
- [x] Statik IP bağla
- [x] Temel dizinleri oluştur
- [x] Anayasa dosyasını oluştur
- [x] Mimari dosyasını oluştur
- [x] Roadmap dosyasını oluştur
- [x] Handover dosyasını oluştur

## Faz 2 - Codex CLI ve Araçlar

- [ ] Node.js kur
- [ ] Python kur
- [ ] Git kur
- [ ] Docker kur
- [ ] Codex CLI kur
- [ ] Codex auth kontrolü yap

## Faz 3 - CTO/Supervisor

- [ ] Supervisor iskeleti oluştur
- [ ] Görev kuyruğu oluştur
- [ ] Worker yönetimi oluştur
- [ ] Log yönlendirme oluştur
- [ ] Telegram Output Guard oluştur

## Faz 4 - Web Panel

- [ ] Basit panel oluştur
- [ ] Görev ekranı oluştur
- [ ] Worker durum ekranı oluştur
- [ ] Log görüntüleme ekranı oluştur
- [ ] Onay ekranı oluştur

## Faz 5 - Telegram

- [ ] Telegram bot ayarı
- [ ] Raw input passthrough
- [ ] Non-mutating output guard
- [ ] Komut dışı doğal dil desteği

## Faz 6 - Deploy Pipeline

- [ ] GitHub bağlantısı
- [ ] Staging deploy
- [ ] Test kontrolü
- [ ] Production deploy kapısı
- [ ] Rollback planı

## Faz 17A - Living Documentation Base

- [x] Living documentation policy oluşturuldu
- [x] Living documentation modül dosyaları oluşturuldu
- [x] AGENTS.md güncellendi
- [x] HANDOVER.md güncellendi
- [ ] Module registry güncelle
- [ ] Action catalog güncelle
- [ ] System state güncelle
- [ ] Validator script ekle
- [ ] Dashboard alanı ekle

## Faz 18I - CTO Telegram Loop

- [x] Telegram görevlerinin workerlar tarafından alınması engellendi
- [x] Telegram görevleri CTO'ya ayrıldı
- [x] CTO Telegram cevap döngüsü doğrulandı
- [ ] CTO worker dispatch v1
- [ ] CTO risk sınıflandırma
- [ ] CTO approval gate entegrasyonu

Faz 19B-10A Model Policy
- [x] gpt-5.5 model policy documented
- [x] xhigh reasoning policy documented
- [x] Dashboard controlled execution proposal status visibility
- [ ] CTO Controlled Execution v1

## Faz 25 - Autonomous Production Delivery System v1

- [x] Production deploy controller eklendi.
- [x] Production readiness suite eklendi.
- [x] GitHub safe flow eklendi.
- [x] Staging / rollback readiness dokumanlari eklendi.
- [x] Production readiness gate dokumani eklendi.
- [x] Deploy policy otomatik production icin guncellendi.
- [x] Dashboard production pipeline bolumleri eklendi.
- [x] Dashboard ayarlari production otomasyon kapilarina baglandi.
- [x] Gercek `CODEX_STAGING_DEPLOY_COMMAND` policy default ile tanimlandi.
- [x] Gercek `CODEX_PRODUCTION_DEPLOY_COMMAND` policy default ile tanimlandi.
- [x] Gercek `CODEX_ROLLBACK_COMMAND` policy default ile tanimlandi.
- [x] Health check ve smoke test scriptleri eklendi.
- [x] Production environment manager eklendi.
- [x] Dashboard deploy command, health, smoke ve rollback gorunurlugu eklendi.
- [x] Panel tokenli giris yerine kullanici adi/sifre auth eklendi.
- [ ] Production deploy sonrasi uzun sureli servis izleme ve kalici Windows/Linux service wrapper standardi.

## Faz 26 - GitHub Actions VM Deploy Gate v1

- [x] Production deploy kanali `github_actions_manual` olarak policy'ye baglandi.
- [x] `Deploy to VM` manuel GitHub Actions workflow'u eklendi.
- [x] Confirm alani `DEPLOY-CODEX-VM` zorunlu yapildi.
- [x] VM hedefi `codex-dev-center-01` olarak dogrulaniyor.
- [x] Runtime dizini `/opt/codex-dev-center` olarak workflow ve policy'ye baglandi.
- [x] Dogrudan VM SSH ve production runtime dosya mudahalesi policy'de yasaklandi.
- [x] Controller GitHub Actions disinda production deploy'u `github_actions_workflow_required` ile blokluyor.
- [x] Readiness suite workflow dosyasini ve confirm/runner/runtime sozlesmesini kontrol ediyor.
- [ ] Self-hosted runner uzerinde ilk manuel workflow calistirma ve servis restart/smoke sonucu.

## Faz 27 - Panel First User Bootstrap

- [x] VM'ye SSH kullanmadan ilk panel kullanicisi olusturma workflow'u eklendi.
- [x] Kullanici/sifre kaynagi GitHub Secrets olarak tanimlandi.
- [x] Runtime auth state PBKDF2 hash uretimiyle olusturulacak.
- [x] Bootstrap sonrasi panel restart ve login smoke check zorunlu.
- [x] Bootstrap workflow canli ortamda calistirildi ve login dogrulandi.

## Faz 28 - Pipeline Observability + QA Hardening

- [x] Dashboard'a runner, son deploy, son smoke, backup ve task-to-deploy marker gorunurlugu eklendi.
- [x] Deploy workflow YAML sanity ve forbidden executable scan kapilariyla guclendirildi.
- [x] Deploy workflow backup dosyasi varligini dogrular.
- [x] Deploy workflow local/public health ve login kontrollerini calistirir.
- [x] Deploy workflow unauthorized/authorized API davranisini dogrular.
- [x] Runtime `github_actions_status.json` ve `pipeline_status.json` state dosyalari dashboard'a baglandi.
- [x] Legacy panel status payload'u da `github_actions` ve `pipeline_status` alanlariyla dashboard pipeline tracking sozlesmesine hizalandi.
- [x] Production readiness suite `yaml_validation` kapisi eklendi.
- [x] Bu paket PR/merge/deploy akisi ile canli dashboard'da dogrulandi.

## Faz 29 - Worker Lifecycle Smoke Gate

- [x] Worker servis durumunu kuyruk durumuyla birlikte degerlendiren `worker_lifecycle_check.py` eklendi.
- [x] Bos kuyrukta sleeping/inactive worker durumu beklenen davranis olarak siniflandirildi.
- [x] Worker-eligible aktif kuyruk varken worker servislerinin tamamen inactive kalmasi fail kapisina baglandi.
- [x] `IDLE/SLEEPING + current_task` ve `RUNNING + inactive service` tutarsizliklari fail olur.
- [x] Telegram ve high/critical approval görevleri worker-eligible sayilmadan raporlanir.
- [x] Deploy smoke worker-eligible görev varsa recovery + lifecycle wake dener.

## Faz 30 - Quality Gate Simulation Contracts

- [x] Production readiness restart simülasyonu non-mutating static contract kanıtına bağlandı.
- [x] Failure injection simülasyonu JSON hata yakalama, security scan ve critical approval sözleşmelerini doğrular.
- [x] Simülasyon sözleşmeleri unit test ve state template kayıtlarıyla sabitlendi.
- [x] Ön canlı ve geri alma dry-run çıktıları non-mutating JSON sözleşmesiyle doğrulanır.

## Faz 31 - Controlled Apply Pipeline Validation

- [x] Repo apply path normalizasyonu exact file allowlist davranışıyla güçlendirildi.
- [x] Runtime/secret path blokajı ve traversal koruması unit test ile sabitlendi.
- [x] Controlled apply validation davranışı handover, onboarding, memory ve state template kayıtlarına işlendi.
