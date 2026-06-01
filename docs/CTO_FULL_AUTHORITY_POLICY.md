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
- high: onay gerekir
- critical: coklu onay + rollback plan gerekir
- catastrophic: coklu onay + rollback + bekleme suresi gerekir

Gercek GCloud IAM yetkisi henuz verilmedi.
Bu ayri ve kritik onayli paketle yapilacak.
