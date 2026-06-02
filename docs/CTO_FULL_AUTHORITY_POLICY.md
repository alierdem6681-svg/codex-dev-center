# CTO FULL AUTHORITY POLICY

Kullanici, en ust CTO/Codex agentinin GCloud genelinde her islemi yapabilecek kapasiteye sahip olmasini istemektedir.

Hedef kapsam:
- Compute Engine
- Cloud Run
- Cloud Build
- Artifact Registry
- BigQuery
- Cloud Storage
- Secret Manager
- IAM
- Logging / Monitoring
- Scheduler
- Pub/Sub
- VPC / Firewall
- Domain / SSL / Load Balancer
- GitHub
- Deploy / rollback
- Worker yonetimi

Not:
Tam teknik erisim hedefi ile kontrolsuz islem ayni sey degildir.

Risk modeli:
- low: otomatik + audit
- medium: otomatik + audit
- high: normal app gelistirme ise gate + audit; kritik altyapi isaretleri varsa onay gerekir
- critical: coklu onay + rollback plan gerekir
- catastrophic: coklu onay + rollback + bekleme suresi gerekir

Gercek GCloud IAM yetkisi henuz verilmedi.
Bu ayri ve kritik onayli paketle yapilacak.

Normal Codex Dev Center app deploy'u production gate'leri PASS ise kullanicidan ayrica deploy onayi istemez. Secret, IAM, billing, DNS, firewall, database destructive operation, credential rotation, token/private key/env degeri degisikligi ve benzeri kritik altyapi islemleri otomatik yetki kapsaminda degildir; `APPROVAL_REQUIRED` veya `BLOCKED` kalir.
