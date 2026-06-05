# CODEX DEV CENTER MİMARİSİ

## Hedef Mimari

Telegram
→ Telegram Bridge
→ Telegram Asset Intake Classifier
→ CTO/Supervisor
→ Task Queue
→ 4 Worker
→ Git / Project Files
→ Test
→ Staging
→ Production Deploy
→ Logs / Reports / Handover

## İlk Kurulum Durumu

Bu VM ilk temel sistem için oluşturuldu.

İlk hedef:
- Codex CLI kurulumu
- CTO/Supervisor kurulumu
- 4 worker çalışma iskeleti
- Web panel
- Telegram entegrasyonu
- Kalıcı hafıza
- Görev kuyruğu
- Log sistemi
- Deploy pipeline

## Ana Dizin

/opt/codex-dev-center

## Önemli Dizinler

constitution/
- Ana kurallar

docs/
- Mimari, yol haritası, devir teslim

memory/
- Kalıcı proje hafızası

state/
- Makine tarafından okunabilir sistem durumu

workers/
- Worker çalışma alanları

supervisor/
- CTO/Supervisor sistemi
- Telegram asset intake sınıflandırıcısı dosya indirmeden medya metadata event'i üretir
- Memory OS context binding aynı konuşmadaki devam/onay mesajlarını son aktif Memory OS root task'a bağlar

projects/
- Geliştirilecek projeler

logs/
- Tüm teknik çıktılar

reports/
- İnsan tarafından okunabilir raporlar

backups/
- Yedekler
