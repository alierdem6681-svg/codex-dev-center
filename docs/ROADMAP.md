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
- [ ] Bootstrap workflow canli ortamda calistirildi ve login dogrulandi.
