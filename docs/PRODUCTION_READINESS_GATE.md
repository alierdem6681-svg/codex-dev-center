# Production Readiness Gate

Canlı ortama otomatik yayına alma yalnızca Codex Dev Center uygulamasının kendi repo/app deploy akışı için geçerlidir.

## Zorunlu Kapılar

- Python compile check PASS
- JSON validation PASS
- Import smoke test PASS
- Unit test PASS
- Integration test PASS
- Regression test PASS
- Worker lifecycle test PASS
- Queue / recovery test PASS
- Dashboard route/API test PASS
- Telegram bridge/direct CTO test PASS
- Secret leakage scan PASS
- Forbidden operation scan PASS
- Ön canlı health/smoke wrapper sözleşmesi PASS
- Ön canlı smoke test PASS
- Geri alma simulation PASS
- Telegram güvenli sonuç raporu akışı PASS
- ACK / progress-aware watchdog / retryable sınıflandırma kontratı PASS
- Ön canlı ve geri alma dry-run non-mutating JSON sözleşmesi PASS
- Restart simulation PASS
- Failure injection simulation PASS
- Parallel worker regression PASS

## Simülasyon Kanıtı

Restart ve failure injection kapıları canlı servis, cloud veya production deploy çalıştırmadan doğrulanır.

- `staging_smoke_test` dry-run sonucunda `dry_run=true` ve `mutating_cloud_operations_performed=false` alanlarını doğrular.
- `scripts/staging_health_check.sh` ve `scripts/staging_smoke_test.sh` staging scope'u explicit geçirir; production scope varsayılan wrapperları ön canlı kapısı yerine kullanılmamalıdır.
- `rollback_simulation` dry-run sonucunda `dry_run=true`, `git_reset_performed=false` ve `data_mutation_performed=false` alanlarını doğrular.
- `ack_watchdog_retry_contract` aynı Telegram update için ACK correlation id ve duplicate ACK suppression davranışını, output gürültüsünü anlamlı progress saymayan watchdog ayrımını ve retryable/non-retryable hata matrisini doğrular.
- `restart_simulation` service watchdog restart yolu ve safe rollback sözleşmesini statik olarak doğrular.
- `failure_injection_simulation` JSON hata yakalama, güvenlik taraması ve kritik operasyon approval sözleşmesini statik olarak doğrular.
- `parallel_worker_regression` dört dummy/simülasyon task için dispatch, wake, tek worker claim, tek terminal status ve duplicate claim/terminal olmaması sözleşmesini geçici queue fixture'ı ile doğrular.
- ACK/watchdog/retry kapısı `static_and_fixture_non_mutating_contract`, restart/failure injection kapıları `static_non_mutating_contract`, paralel worker kapısı `parallel_worker_lifecycle_simulation` modunda çalışır; hepsi `production_deploy_performed=false` beyanını korur.

## Telegram Sonuç Raporu

Readiness suite `telegram_result_report_flow` kapısıyla kullanıcıya gidebilecek kısa Telegram özetini doğrular.

- Özet staging health/smoke, rollback planı, genel readiness durumu ve production deploy yapılmadı bilgisini içerir.
- Özet en fazla 900 karakter ve 12 satır olmalıdır.
- Diff, stdout/stderr, stack trace, raw payload, Telegram `file_id`, token/private key/env değeri veya runtime path bilgisi içeremez.
- Bu kapı gerçek Telegram API çağırmaz; sadece güvenli özet sözleşmesini test eder.

## Dashboard Kanıt Görünürlüğü

Dashboard ham `reports/production_readiness_last_report.md` metnini gösterirse `/api/status` içinde `report_text_status.readiness` metadata'sını da döndürmelidir.

- Rapor `Generated at` tarihi policy `updated_at` tarihinden eskiyse status `UNKNOWN`, freshness `stale` olur.
- Rapor policy `required_gates` listesini tam içermiyorsa `missing_required_gate` reason code'u ve eksik gate listesi döner.
- Ham PASS metni bu metadata olmadan güncel readiness kanıtı sayılmaz.

## Otomatik Yayına Alma Kuralı

`production_requires_explicit_approval=false` normal Codex Dev Center app deploy'u için hedef kuraldır. Bu, kontrolsüz yayına alma anlamına gelmez.

Controller şu şartlar olmadan canlıya geçmez:

- Production readiness suite PASS
- Ön canlı kapısı PASS
- Geri alma kapısı PASS
- `CODEX_STAGING_DEPLOY_COMMAND` tanımlı
- `CODEX_PRODUCTION_DEPLOY_COMMAND` tanımlı
- `CODEX_ROLLBACK_COMMAND` tanımlı
- `CODEX_PRODUCTION_DEPLOY_EXECUTE=1`
- Kritik istisna yok
- İlgili görev worker'a atanmış, worker çıktısı CTO tarafından denetlenmiş, branch/PR/merge akışı tamamlanmış ve deploy adayı olarak işaretlenmiş

## Kritik İstisnalar

Secret, token/private key/env değeri, IAM owner/editor, billing, database veri silme, geri döndürülemez migration, kritik DNS/firewall değişikliği, Google Ads canlı mutate ve canlı veri kaybı riski otomatik yapılamaz.

Bu durumlardan biri gerekiyorsa controller `critical_exception_detected` ile durur ve risk raporu üretir.
