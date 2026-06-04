# ROADMAP

## 2026-06-04 Owner Queue Repair And Production Sync

- [x] VM/runtime/service path discovery completed.
- [x] Timestamped archive created before repair.
- [x] Full runtime queue archived before cleanup.
- [x] Active queue cleared to 0 tasks with `CANCELLED_BY_OWNER_CLEANUP` archive status.
- [x] Runtime system state set to `READY_FOR_NEW_TASKS`.
- [x] Locked/fsynced JSON helper added for queue/state writes.
- [x] Lifecycle pending count and duplicate worker start behavior fixed.
- [x] Repo apply no-change loop classified as terminal `NO_CHANGE`.
- [x] Validation false-positive handling extended for negative safety phrases.
- [ ] Final production runtime sync from current source commit.
- [ ] Service restart and health smoke after deploy.
- [ ] Commit and push final repair.

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
- [x] Eksik runtime marker dosyalarinda ana ve legacy `/api/status` payload sozlesmesi unit test ile sabitlendi.
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
- [x] Production readiness artefact'inden standart `quality-gate-report.json` ve `quality-gate-summary.md` çıktısı üretilir.
- [x] Quality gate retry simülasyonu ilk deneme, en fazla bir retry ve `retry_changed_result` alanlarını non-blocking standard rapor görünürlüğüne bağlar.

## Faz 31 - Controlled Apply Pipeline Validation

- [x] Repo apply path normalizasyonu exact file allowlist davranışıyla güçlendirildi.
- [x] Runtime/secret path blokajı ve traversal koruması unit test ile sabitlendi.
- [x] Controlled apply validation davranışı handover, onboarding, memory ve state template kayıtlarına işlendi.
- [x] Apply raporu patch scope, diff review, secret scan, local pipeline ve rollback notu içeren controlled checklist üretir.

## Faz 32 - Queue / Status Normalizer Retry

- [x] Queue task status normalizer case, bosluk, tire ve noktalama ayirici aliaslarini standart enumlara cevirir.
- [x] `ready for validation`, `ready-for-validation`, `ready/for.validation`, `FAILED-TIMEOUT`, `FAILED.TIMEOUT`, `in-progress` ve `completed` varyantlari unit test ile sabitlendi.
- [x] CTO router normalizasyon davranisi onboarding, handover, memory ve state template kayitlarina islendi.

## Faz 33 - Dashboard Pipeline Flow Backend

- [x] `/api/pipeline-flow` read-only backend kontrati eklendi.
- [x] Gercek task status enumlari sabit pipeline stage sirasina maplenir.
- [x] Bos stage, failed, blocked, approval ve `DEPLOYED` son stage davranisi unit test ile sabitlendi.
- [x] Endpoint raw mesaj, uzun aciklama, log, stdout/stderr veya terminal dump dondurmez.
- [x] Ana gorev expand/collapse state'i stable key ile polling refresh'ten ayrildi.
- [x] Live polling response `serverRevision`, `resetToken`, `requiresUiReset` ve `mergePolicy` kontratiyla client-owned UI state'i korur.
- [ ] UI stage tab gorunumu sonraki kucuk pakete birakildi.

## Faz 34 - Worker Dispatch v2 Contract Metadata

- [x] Queue task normalizasyonu `root_task_id`, `dispatch_id`, `attempt`, `max_attempts`, `last_error_code`, `claimed_at` ve `finished_at` alanlarini varsayilanlar.
- [x] Worker claim akisi `worker_id` ve `claimed_at` alanlarini task kaydina yazar.
- [x] Router subtask dispatch contract ve worker claim metadata davranisi unit test ile sabitlendi.
- [x] Stale `ASSIGNED/RUNNING` claim timeout durumunda aktif worker sahipligi yoksa `attempt` artirilarak yeniden dispatch edilir.
- [x] `max_attempts` doldugunda stale claim terminal `FAILED_TIMEOUT` olur ve yeniden worker-eligible sayilmaz.
- [x] Aktif worker ayni `current_task` uzerinde calisiyorsa eski `claimed_at` tek basina redispatch tetiklemez.

## Faz 35 - Dashboard Gorev Listesi Duzeni

- [x] Gorevler listesi deterministik comparator ile siralanir.
- [x] `RUNNING` / `Calisiyor` gorevleri listenin ustunde kalir.
- [x] Canliya alinmis gorevler varsayilan ana listeden gizlenir.
- [x] `Canliya alinanlari goster` checkbox'i canli gorevleri listeye dahil eder.
- [x] Filtre option'lari yenilemede gereksiz yeniden yazilmayarak secili filtre korunur.
- [x] Dashboard markup regresyon testi ile davranis sozlesmesi sabitlendi.

## Faz 36 - Telegram Asset Manifest Contract

- [x] Telegram asset manifest schema version `1` repo fixture olarak eklendi.
- [x] Network kullanmayan manifest validator eklendi.
- [x] Valid, boundary, limit-asimi ve forbidden-field fixture setleri eklendi.
- [x] `20971520` byte Telegram indirme limiti unit test ile sabitlendi.
- [x] Raw payload, Telegram file URL ve sensitive credential-like alan redaksiyon kontrati test edildi.
- [ ] Runtime Telegram asset intake ve dashboard inbox gorunumu sonraki kucuk paketlere birakildi.

## Faz 37 - Dashboard Pipeline Expand State Tests

- [x] Pipeline ana gorev expand/collapse tercihi polling ve render refresh sonrasinda korunur.
- [x] Kullanici kapattigi aktif ana gorev otomatik tekrar acilmaz.
- [x] Kullanici ac/kapat niyeti `toggle` event'i yerine `summary` click handler ile senkron kaydedilir.
- [x] Expand state davranisi dashboard pipeline flow UI regresyon testiyle sabitlendi.

## Faz 38 - Dashboard Telegram Asset Inbox Backend

- [x] Dashboard Telegram Asset Inbox icin read-only DTO helper eklendi.
- [x] Ana ve legacy panel `GET /api/dashboard/telegram-assets` endpointlerini ayni guvenli payload sozlesmesine baglar.
- [x] Liste ve detay payload'lari ham Telegram id, storage path, signed URL veya secret-like alan dondurmez.
- [x] Filtre, cursor, single manifest ve panel server wrapper davranisi unit test ile sabitlendi.
- [ ] Runtime Telegram asset intake akisi sonraki kucuk pakete birakildi.
- [ ] Dashboard inbox UI tablo/detay gorunumu sonraki kucuk pakete birakildi.

## Faz 39 - Telegram Asset Safety Tests

- [x] Telegram asset manifest/limit/checksum/MIME sozlesmesi non-mutating module olarak eklendi.
- [x] Secret redaction, simulator retry/idempotency ve dashboard-safe snapshot davranisi unit test ile sabitlendi.
- [x] Module registry, settings ve action template kayitlari eklendi.
- [ ] Gercek Telegram asset intake backend sonraki kucuk pakette bu sozlesmeye baglanacak.
- [ ] Dashboard asset inbox UI sonraki kucuk pakette stub veriden runtime veriye genisletilecek.

## Faz 40 - Telegram Asset Intake Backend

- [x] Telegram `photo`, `document`, caption ve unsupported medya payload'lari guvenli metadata event'ine siniflandirilir.
- [x] Direct CTO handler medya mesajlarini `Telegram Asset Intake` routed task'ina cevirir.
- [x] Raw `file_id`, raw payload, token, secret veya header bilgisi intake task/log mesajina yazilmaz.
- [x] Dokuman MIME allowlist, dosya boyutu limiti, caption uzunluk limiti ve dosya adi sanitization davranisi unit test ile sabitlendi.
- [x] Dosya indirme, kalici saklama, checksum ve malware scan sonraki asset processing asamasina birakildi.
- [ ] Telegram Asset Storage And Manifest paketi sonraki kucuk kapsam olarak uygulanacak.

## Faz 41 - Repo Apply Isolated Clone Guard

- [x] Repo apply worker `git worktree` yerine sandbox icinde yerel `.git/` metadata dizini olan izole repo clone kullanir.
- [x] Clone origin'i GitHub remote'a cevrilir, worker branch `origin/main` tabanindan acilir.
- [x] `.git` dosyasi ile dis metadata'ya isaret eden worktree formu apply icin reddedilir.
- [x] Metadata kontrati unit test ile sabitlendi.

## Faz 42 - Pending Dispatch Rebalance Guard

- [x] Pending/queued task tercih edilen worker mesgulse bosta duran worker'a dengelenebilir.
- [x] Assigned/running task'lar reassign edilmez; aktif claim korunur.
- [x] Dispatch rebalance kontrati unit test ile sabitlendi.

## Faz 43 - Pipeline Failed Root Cause Reporting

- [x] `PIPELINE_FAILED` apply child tasklari icin yeni kok gorev acmadan root cause raporu uretilir.
- [x] Rapor `root_cause`, `last_error`, `retryable` ve `recommended_fix` alanlarini ayrastirir.
- [x] `workspace_missing` senaryosu unit test ile sabitlendi.
- [x] Production deploy ve runtime state/log/report mutasyonu yapilmadan repo sozlesmesi guncellendi.

## Faz 44 - Read-Only / Dry-Run Write Policy

- [x] Ortak read-only/dry-run write evidence helper'i eklendi.
- [x] Readiness suite `CHECK_MODE=read_only|dry_run` altında state/report yazmadan `write-skipped` kanıtı döndürür.
- [x] Drift checker aynı write evidence sözleşmesine bağlandı.
- [x] Health/smoke test status ve report yazımları dry-run/read-only modda atlanır.
- [x] Read-only, dry-run ve smoke write-skip davranışı unit testlerle sabitlendi.

## Faz 45 - Dashboard Quality Gate Status Contract

- [x] Ana ve legacy `/api/status` payload'u `qualityGateView` kontrat v1 alanini dondurur.
- [x] Readiness + health kaynaklari tek merkezi mapper ile `READY`, `DEGRADED`, `NOT_READY`, `UNKNOWN` durumlarina iner.
- [x] Legacy `quality_gate_status` sadece `legacy_quality_gate_status` diagnostik alanina tasinir; pozitif READY fallback kaynagi olmaz.
- [x] Missing/stale readiness veya health kaynaklari `UNKNOWN` sonucuna baglandi.
- [x] Kontrat davranisi runtime status unit testleriyle sabitlendi.

## Faz 46 - Safe Test Scratch Standard

- [x] Ortak `tests.safe_test_scratch` helper'i eklendi.
- [x] Scratch root onceligi `TEST_SCRATCH_ROOT`, `RUNNER_TEMP/test-scratch`, `TMPDIR/test-scratch` olarak sabitlendi.
- [x] Per-test atomik scratch dizini ve runtime env redirect davranisi unit test ile dogrulandi.
- [x] Repo write guard allowlist disi checkout mutasyonunu yakalayacak sekilde sabitlendi.
- [x] Module registry, settings ve action template kayitlari eklendi.
- [ ] Mevcut uzun test dosyalarinin tempfile kullanimlari sonraki kucuk paketlerde helper'a kademeli tasinacak.

## Faz 47 - Observed Issue Completion Pack

- [x] Drift module registry/settings adaylari kanit ve confidence ile siniflandirildi.
- [x] Repo apply no-change/DONE terminal outcome sozlesmesi eklendi.
- [x] Production readiness ve audit isleri `Controls / Readiness` lane'ine yonlendirildi.
- [x] Worker workspace bootstrap preflight ve diagnostics dosyasi eklendi.
- [x] Timeout/usage-limit retry/backoff idempotency sozlesmesi eklendi.
- [x] Atomic JSON state/tmp audit helper'i eklendi.
- [x] Production readiness dry-run JSON stdout parser'i uzun/prefixed payload icin sabitlendi.
- [x] Superseded duplicate parent task'larindan backlog continuation uretilmesi engellendi.
- [x] Direct CTO action mode'da implementation sinyalli islerin plan-only kapanmasi engellendi.
- [x] Module registry, settings, action catalog ve runtime status unit testleri guncellendi.
