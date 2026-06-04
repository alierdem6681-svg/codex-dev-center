# CODEX DEV CENTER MİMARİSİ

## Hedef Mimari

Telegram
→ Telegram Bridge
→ Telegram Asset Safety Contracts
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

projects/
- Geliştirilecek projeler

logs/
- Tüm teknik çıktılar

reports/
- İnsan tarafından okunabilir raporlar

backups/
- Yedekler

## Telegram Asset Safety Contracts

`supervisor/telegram_asset_safety.py` Telegram asset akisi icin dis API cagirmayan, dosya indirmeyen ve runtime asset yazmayan sozlesme katmanidir.
Kabul, limit, manifest, redaction, simulator ve dashboard smoke davranislari unit testlerle sabitlenir.
