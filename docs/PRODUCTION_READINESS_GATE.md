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
- Ön canlı smoke test PASS
- Geri alma simulation PASS
- Ön canlı ve geri alma dry-run non-mutating JSON sözleşmesi PASS
- Restart simulation PASS
- Failure injection simulation PASS

## Simülasyon Kanıtı

Restart ve failure injection kapıları canlı servis, cloud veya production deploy çalıştırmadan doğrulanır.

- `staging_smoke_test` dry-run sonucunda `dry_run=true` ve `mutating_cloud_operations_performed=false` alanlarını doğrular.
- `rollback_simulation` dry-run sonucunda `dry_run=true`, `git_reset_performed=false` ve `data_mutation_performed=false` alanlarını doğrular.
- `restart_simulation` service watchdog restart yolu ve safe rollback sözleşmesini statik olarak doğrular.
- `failure_injection_simulation` JSON hata yakalama, güvenlik taraması ve kritik operasyon approval sözleşmesini statik olarak doğrular.
- Bu kapılar `static_non_mutating_contract` modunda çalışır ve `production_deploy_performed=false` beyanını korur.
- Standart kalite raporu staging/rollback `dry_run_non_mutating_contract` ve restart/failure injection `static_non_mutating_contract` detaylarını da arar; eksik detay gate'i fail yapar.

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
