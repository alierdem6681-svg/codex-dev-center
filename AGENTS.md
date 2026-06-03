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

Dashboard `/api/status` payload'u controlled execution proposal durumunu salt okunur olarak gosterebilir. Bu gorunurluk production deploy, secret/env/token/private key, IAM, billing, DNS/firewall, destructive database, credential rotation veya reklam platformu live-write yetkisi vermez.
