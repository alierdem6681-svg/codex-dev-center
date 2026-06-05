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
- high: gate + audit; kullanici onayi istemeden pipeline sonucuna gore ilerler
- critical: gate + audit + rollback plan; kullanici onayi istemeden pipeline sonucuna gore ilerler
- catastrophic: gate + audit + rollback plan + bekleme/health kontrolleri; kullanici onayi istemeden pipeline sonucuna gore ilerler

Gercek GCloud IAM yetkisi henuz verilmedi.
Bu ayri ve pipeline-gated paketle yapilacak.

Normal Codex Dev Center app deploy'u production gate'leri PASS ise kullanicidan ayrica deploy onayi istemez. Secret, IAM, billing, DNS, firewall, database destructive operation, token/private key/env degeri degisikligi ve benzeri kritik altyapi islemleri de kullanici onayi bekletmez; ilgili gate/pipeline PASS degilse `VALIDATION_FAILED`, `PIPELINE_FAILED` veya `BLOCKED` nedeni raporlanir.
