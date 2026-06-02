# Autonomous Production Policy

Tarih: 2026-06-02

Codex Dev Center kendi uygulama kapsamında production'a yalnızca GitHub Actions üzerinden geçebilir. Production deploy terminalden, doğrudan VM SSH ile veya production runtime dosyalarına elle müdahale edilerek yapılmaz.

Production kapısı GitHub Actions workflow'udur:

- Workflow adı: `Deploy to VM`
- Confirm alanı: `DEPLOY-CODEX-VM`
- VM hedefi: `codex-dev-center-01`
- Runtime dizini: `/opt/codex-dev-center`
- Deploy kanalı: `github_actions_manual`

Bu modelde kalite kapıları zorunludur. Confirm alanı insan onayı değil, yanlış workflow tetiklemeyi engelleyen sabit emniyet anahtarıdır. CTO normal Codex Dev Center app deploy'larında tüm gate'ler PASS ise ayrıca kullanıcı onayı istemeden bu workflow'u tetikleyebilir.

## Canlıya Alma Şartları

Production deploy ancak şu şartların tamamı sağlanırsa çalışır:

- Production readiness suite `PASS`
- Deploy script ve command policy kontrolü `PASS`
- Secret leakage scan `PASS`
- Forbidden operation scan `PASS`
- Git clean kontrolü `PASS`
- GitHub remote sync kontrolü `PASS`
- Staging deploy `PASS`
- Staging health check `PASS`
- Staging smoke test `PASS`
- Rollback simulation `PASS`
- Production health check `PASS`
- Production smoke test `PASS`
- Rollback noktası kaydı `PASS`
- GitHub Actions confirm `DEPLOY-CODEX-VM`
- Runner hedef doğrulaması `codex-dev-center-01`
- İlgili task worker'a atanmış ve branch/PR/merge akışından geçmiş olmalı
- Task `repo_applied`, `branch_merged`, `merged_commit`, `READY_FOR_DEPLOY` veya `MERGED` marker'ı olmadan deploy adayı sayılmaz

## Komut Kaynağı ve Blokaj

Env değişkenleri tanımlıysa yerel controller doğrulamalarında önceliklidir. Tanımlı değilse policy default kullanılır:

- `state_templates/deploy_policy.json`
- `state_templates/production_policy.json`
- `state_templates/module_settings.json`
- `state_templates/action_catalog.json`
- `state_templates/module_registry.json`

Bu nedenle eksik env readiness raporunu gereksiz yere BLOCKED bırakmaz. Ancak `production_deploy_channel=github_actions_manual` olduğunda controller GitHub Actions dışında production deploy'u `github_actions_workflow_required` blocker'ı ile durdurur.

Production deploy için kullanılacak gerçek yol `.github/workflows/deploy-vm.yml` dosyasıdır. Bu workflow backup, validate, runtime sync, non-secret policy sync, service restart ve smoke check adımlarını self-hosted runner üzerinde yürütür.

## Kritik İstisnalar

Aşağıdaki konular otomatik production kapsamı dışındadır ve ayrı risk raporu ister:

- Secret/IAM/billing işlemi
- Token, private key, env değeri veya credential rotation
- Database veri silme veya irreversible migration
- DNS/firewall kritik değişikliği
- Google Ads canlı mutate
- Canlı müşteri veya veri kaybı riski

## Production Sonrası

GitHub Actions deploy tamamlandıktan sonra şu kontroller yapılır:

- Health check
- Smoke test
- Dashboard status doğrulaması
- Telegram bridge statik smoke
- Worker/queue/recovery state görünürlüğü
- Rollback point doğrulaması
- Yönetici özeti raporu

## Stable Mod

CTO stable olana kadar `max_parallel_tasks=1` ile ilerler. Her task worker'a atanır, worker çıktısı CTO tarafından denetlenir, branch/PR/merge sonrası readiness gate çalışır, tüm gate'ler PASS ise production deploy yapılır ve post-deploy health/smoke sonucu kaydedilir. En az 3 düşük riskli task bu şekilde tamamlandıktan sonra VM kaynakları uygunsa paralellik kademeli artırılabilir.
