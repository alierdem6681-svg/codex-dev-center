# CODEX DEV CENTER - AGENTS.md

Bu depo/dizin Codex Dev Center ana çalışma alanıdır.

## Zorunlu İlk Okuma Sırası

Her Codex, agent veya worker işe başlamadan önce şu dosyaları okumalıdır:

1. constitution/ANAYASA.md
2. docs/ARCHITECTURE.md
3. docs/ROADMAP.md
4. docs/HANDOVER.md
5. state/system_state.json
6. memory/project_memory.md

## Kullanıcı Profili

Kullanıcının teknik bilgisi yoktur. Bu yüzden:
- Tek parça terminal paketleri üret.
- Her paketin sonunda ne yapıldığını net yaz.
- Kullanıcıdan teknik karar bekleme.
- Düşük/orta riskli işleri güvenli şekilde ilerlet.
- Yüksek riskli işleri açık onaya bağla.

## Telegram Kuralı

Kullanıcının mesajları Codex'e aynen iletilmelidir:
- Özetleme yok
- Düzeltme yok
- Yorum ekleme yok
- Yönlendirme yok
- Filtre yok

Codex'in normal konuşma yanıtları kullanıcıya aynen gönderilmelidir.

Ancak şunlar Telegram'a gönderilmemelidir:
- Uzun kod blokları
- Uzun terminal çıktıları
- diff çıktıları
- stack trace dump
- log dump
- dosya içerikleri
- yüzlerce satırlık teknik çıktı

Bu teknik çıktılar logs/ ve reports/ altına yazılmalıdır.

## Canlı Ortam Kuralı

Sistem canlıya alma hazırlığı yapabilir. Production deploy sadece GitHub Actions `Deploy to VM` workflow'u üzerinden yapılır. VM'ye doğrudan SSH ile bağlanma, production runtime dosyalarına elle müdahale etme ve terminalden production deploy çalıştırma yasaktır.

Production workflow manuel çalışır ve confirm alanına tam olarak `DEPLOY-CODEX-VM` yazılmadan ilerlemez. Hedef VM `codex-dev-center-01`, runtime dizini `/opt/codex-dev-center` olarak tanımlıdır.

Veri silme, migration, secret erişimi, IAM, DNS/firewall, billing, Google Ads mutate ve maliyet artıran cloud işlemleri risk kapısına bağlıdır ve otomatik yapılmaz.

Owner-directed emergency repair exception:
- Queue/lifecycle/worker sistemi kendi kendine yeni görev alamayacak kadar bozulursa ve owner açıkça doğrudan VM repair isterse, Codex dışarıdan bakım yapabilir.
- Bu istisnada önce timestamped archive alınır, queue snapshot saklanır, destructive olmayan runtime state onarımı yapılır ve finalde commit/push + servis health raporu verilir.
- Bu istisna secret/IAM/billing/DNS/firewall/destructive database/Google Ads live mutate yasağını kaldırmaz.

## Çalışma Prensibi

Her görev:
- task id almalı
- log yazmalı
- değişen dosyaları raporlamalı
- test sonucunu yazmalı
- HANDOVER.md dosyasını güncellemelidir.

## İlk Büyük Görev

docs/CODEX_MASTER_PROMPT.md dosyasını oku ve bu sistemin aşağı doğru mimarisini inşa etmeye başla.

---

## STEP 10 REQUIRED READS

Her yeni Codex/agent/worker su dosyalari okumalidir:

- docs/MODULAR_ARCHITECTURE_STANDARD.md
- docs/CTO_FULL_AUTHORITY_POLICY.md
- docs/WORKER_LIFECYCLE_POLICY.md
- docs/DRIFT_CONTROL_POLICY.md
- state/cto_authority_policy.json
- state/modular_development_policy.json
- state/worker_lifecycle_policy.json
- state/drift_control_policy.json

---

## STEP 17A LIVING DOCUMENTATION RULE

Bundan sonra her geliştirme paketi sonunda yaşayan dokümantasyon güncel tutulacaktır.

Güncellenmesi gereken ana dosyalar:
- docs/AGENT_ONBOARDING_MAP.md
- AGENTS.md
- constitution/ANAYASA.md
- docs/HANDOVER.md
- docs/ROADMAP.md
- memory/project_memory.md
- state/system_state.json
- state/module_registry.json
- state/module_settings.json
- state/action_catalog.json
- reports/
- logs/

MODEL POLICY GPT55 XHIGH
All CTO, worker and future Codex processes must use model gpt-5.5 with reasoning effort xhigh when available.

---

## GITHUB ACTIONS VM DEPLOY GATE V1

Bu repo artik Codex Dev Center uygulamasinin kendi repo/app yayina alma akisi icin GitHub Actions manuel production gate'e sahiptir.

Canliya alma sadece su kosullarda calisabilir:
- `.github/workflows/deploy-vm.yml` icindeki `Deploy to VM` workflow'u manuel calistirilir.
- Confirm alani tam olarak `DEPLOY-CODEX-VM` olur.
- Self-hosted runner hedefi `codex-dev-center-01` olur.
- Runtime dizini `/opt/codex-dev-center` olur.
- `supervisor/production_readiness_suite.py --json` PASS olmali.
- On canli kapisi PASS olmali.
- Geri alma simulasyonu PASS olmali.
- Secret leakage ve forbidden operation scan PASS olmali.
- `CODEX_STAGING_DEPLOY_COMMAND`, `CODEX_PRODUCTION_DEPLOY_COMMAND`, `CODEX_ROLLBACK_COMMAND` tanimli olmali.
- `CODEX_PRODUCTION_DEPLOY_EXECUTE=1` olmali.
- Kritik istisna bulunmamali.
- Restart ve failure injection kalite kapıları production işlemi yapmadan `static_non_mutating_contract` kanıtı üretmelidir.

`production_deploy_channel=github_actions_manual` iken controller GitHub Actions disinda production deploy denemesini `github_actions_workflow_required` blocker'i ile durdurur.

Kritik istisnalar otomatik yapilmaz: secret degeri gorme/degistirme, IAM owner/editor degisikligi, billing, database veri silme, geri dondurulemez migration, kritik DNS/firewall degisikligi, Google Ads live mutate ve canli veri kaybi riski. Bu hallerde controller durur ve risk raporu uretir.

## AUTONOMOUS PRODUCTION ENVIRONMENT V1

Deploy komutlari artik `state_templates/deploy_policy.json` icinde policy-bound default olarak tanimlidir. Environment variable varsa override eder; yoksa controller default komutlari kullanir.

Default komutlar:
- `CODEX_STAGING_DEPLOY_COMMAND={python} supervisor/production_environment_manager.py staging-deploy`
- `CODEX_PRODUCTION_DEPLOY_COMMAND={python} supervisor/production_environment_manager.py production-deploy`
- `CODEX_ROLLBACK_COMMAND={python} supervisor/production_environment_manager.py rollback`
- `CODEX_PRODUCTION_DEPLOY_EXECUTE=1`

Production kapsami sadece Codex Dev Center kendi panel/CTO/worker/recovery/dashboard runtime akisi ile sinirlidir.

## DASHBOARD CONTROLLED EXECUTION VISIBILITY V1

Dashboard `/api/status` payload'u controlled execution proposal durumunu salt okunur olarak gosterebilir. Bu gorunurluk production deploy, secret/env/token/private key, IAM, billing, DNS/firewall, destructive database veya reklam platformu live-write yetkisi vermez.

## DASHBOARD PIPELINE TRACKING V1

Ana ve legacy panel `/api/status` payload'lari runtime `github_actions_status.json` ve `pipeline_status.json` dosyalarini salt okunur `github_actions` ve `pipeline_status` alanlariyla gosterir. Bu gorunurluk production deploy veya kritik altyapi islemi yetkisi vermez.

## DASHBOARD PIPELINE FLOW BACKEND V0

Ana ve legacy panel `/api/pipeline-flow` payload'u task statuslarini pipeline stage sirasina read-only olarak mapler. Payload raw kullanici mesaji, uzun description, stdout/stderr, log, diff veya terminal dump dondurmemelidir. `DEPLOYED` stage siralamasinda son stage olarak kalir. Bu gorunurluk production deploy, secret/env/token/private key, IAM, billing, DNS/firewall, destructive database veya reklam platformu live-write yetkisi vermez.

## TELEGRAM ASSET SAFETY CONTRACT V1

`supervisor/telegram_asset_safety.py` Telegram asset kabulu icin manifest, limit, checksum, MIME/uzanti, secret redaction, simulator ve dashboard-safe snapshot sozlesmesini test eder. Bu kontrat gercek Telegram API'ye fallback yapmaz, asset indirmez, runtime state/log/report mutate etmez ve production deploy yetkisi vermez.

## TELEGRAM ASSET INTAKE BACKEND V1

Telegram CTO hattına gelen fotoğraf ve doküman mesajları backend tarafında raw dosya indirmeden güvenli metadata event'ine sınıflandırılır. Caption sanitize edilir, dosya adı normalize edilir, MIME allowlist ve boyut limiti uygulanır; unsupported medya controlled reject alır.

Raw `file_id`, raw payload, token, secret, env, header veya private key bilgisi Telegram'a, task mesajına, log'a veya rapora yazılmaz. Dosya indirme, kalıcı saklama, checksum ve malware scan ayrı asset processing aşamasına bırakılır.

## WORKER DISPATCH CONTRACT V1

Queue task normalizasyonu dispatch izlenebilirligi icin `root_task_id`, `dispatch_id`, `worker_id`, `attempt`, `max_attempts`, `last_error_code`, `claimed_at` ve `finished_at` alanlarini tamamlar. Worker claim akisi task'i RUNNING yaparken `worker_id` ve `claimed_at` yazar. Terminal statuslar yeniden worker-eligible sayilmaz.

## QUALITY GATE STANDARD REPORT V1

`supervisor/codex_quality_gate.py standard-report` komutu mevcut production readiness artefact'ini okuyarak `reports/quality-gate-report.json` ve `reports/quality-gate-summary.md` uretir. Eksik artefact veya basarisiz lint/test/simulasyon dry-run kapisi sonucu `fail` olur; komut production deploy, secret/env/token/private key, IAM, billing, DNS/firewall, destructive database veya reklam platformu live-write yetkisi vermez.

`supervisor/codex_quality_gate.py retry-simulation` komutu mevcut kalite kapısı test komutlarını değiştirmeden ilk deneme ve en fazla bir retry sonucunu `reports/quality-gate-retry-simulation.json` alanında non-blocking raporlar. Standard report bu artefact'i karar sonucunu değiştirmeden `retry_simulation` olarak gösterir.

Retry simülasyonu artefact'i dry-run ve non-mutating kanıtını `safety_status`, `safety_reasons` ve `required_false_flags` alanlarıyla görünür kılar; bu görünürlük standard kalite kapısı kararını değiştirmez ve production deploy yetkisi vermez.

## READ-ONLY / DRY-RUN WRITE POLICY V1

`supervisor/read_only_execution.py` readiness, drift ve smoke kontrol yazımları için ortak write evidence sözleşmesini sağlar. `CHECK_MODE=read_only` veya `CHECK_MODE=dry_run` olduğunda state/report yazımları dosya oluşturmadan `write-skipped` kanıtına dönüşür; `CHECK_MODE` verilmezse varsayılan `write_enabled` davranışı korunur.

Bu görünürlük production deploy, secret/env/token/private key, IAM, billing, DNS/firewall, destructive database veya reklam platformu live-write yetkisi vermez.

## DASHBOARD QUALITY GATE VIEW CONTRACT V1

Ana ve legacy panel `/api/status` payload'lari `qualityGateView` alanini dondurur. Dashboard badge, renk, filtre ve kalite kapisi ozeti icin tek karar kaynagi bu alan olmalidir.

`qualityGateView` `production_readiness_status.json`, `last_health_check_status.json` ve diagnostik `quality_gate_status.json` girdilerinden uretilir. Legacy `quality_gate_status` pozitif `READY` karari uretmek icin kullanilamaz; yalnizca `legacy_quality_gate_status` olarak tasinir veya eksik/stale durumda non-authoritative fallback nedeni verir.

Stale veya eksik readiness/health kaynagi `UNKNOWN` sonucudur. Bu gorunurluk production deploy, secret/env/token/private key, IAM, billing, DNS/firewall, destructive database veya reklam platformu live-write yetkisi vermez.

## OBSERVED ISSUE COMPLETION CONTRACT V1

Drift registry/settings farklari tek alert sinyaliyle otomatik eklenmez; `supervisor/drift_checker.py` adaylari kanit kaynaklari ve confidence ile siniflandirir.

Repo apply no-change sonucu terminal basaridir. `supervisor/repo_apply_outcome.py` `NO_CHANGE`, `DONE`, `RETRY` ve `BACKLOG` kararlarini `enqueue_target` ile aciklar; terminal no-change retry/backlog uretmez.

Readiness, audit, risk review, test plan ve proposal-only isler `Controls / Readiness` lane'ine gider. Worker workspace preflight tanisi secret degeri loglamadan `bootstrap_diagnostics.json` uretir. Timeout ve usage-limit retry kararlari ayni task uzerinde idempotency key ile raporlanir. Atomic JSON state audit tmp dosyalarini otomatik guvenilir saymadan state parse edilebilirligini raporlar.

## CONTROLLED APPLY PIPELINE V1

Validated proposal apply worker'lari sadece izole git worktree ve worker branch uzerinde calisir. Repo apply degisiklikleri PR oncesi exact path allowlist, blocked runtime/secret path kontrolu, secret scan ve local pipeline kapilarindan gecmelidir.

`AGENTS.md` gibi tekil allowlist dosyalari sadece exact dosya eslesmesiyle kabul edilir; `AGENTS.md.bak` veya `AGENTS.md/child` gibi varyantlar repo apply icin guvenli sayilmaz. Runtime `state/`, `logs/`, `reports/`, `workspaces/`, secret/env/token/private key, IAM, billing, DNS/firewall, destructive database ve reklam platformu live-write kapsam disi kalir.

Apply raporu patch scope, diff review, secret scan, local pipeline, production deploy yapılmadı kanıtı ve rollback notunu içermelidir.

## SAFE TEST SCRATCH STANDARD V1

Testler repo checkout icine runtime state, cache, config, log veya output dosyasi yazmamalidir. Ortak helper `tests/safe_test_scratch.py` uzerinden scratch root sirasi `TEST_SCRATCH_ROOT`, `$RUNNER_TEMP/test-scratch`, `$TMPDIR/test-scratch` olarak cozulur; repo icindeki scratch root reddedilir.

Her test icin `{suite}/{worker_id}/{test_name_hash}-{pid}-{counter}` formatinda atomik benzersiz dizin olusturulur. `TMPDIR`, `TEMP`, `TMP`, `HOME`, `XDG_CACHE_HOME`, `XDG_CONFIG_HOME`, `CODEX_TEST_OUTPUT_DIR` ve `TEST_SCRATCH_ACTIVE_DIR` aktif scratch alanina yonlendirilir. `guard_repo_clean()` allowlist disi repo mutasyonlarini test fail'e cevirmek icin kullanilir.
