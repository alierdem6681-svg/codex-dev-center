# HANDOVER

## Son Durum

VM oluşturuldu ve temel Codex Dev Center dizin yapısı kuruldu.

## Yeni Gelen Codex / Agent Önce Ne Yapmalı?

Sırasıyla şu dosyaları oku:

1. constitution/ANAYASA.md
2. docs/ARCHITECTURE.md
3. docs/ROADMAP.md
4. docs/HANDOVER.md
5. state/system_state.json
6. memory/project_memory.md

## Şu Anki Öncelik

Codex CLI ve temel geliştirme araçlarını kur.

## Dikkat Edilecekler

Kullanıcının teknik bilgisi düşük. Tüm işlemler tek parça terminal paketleriyle yapılmalı.

Telegram tarafında:
- Kullanıcı mesajları aynen geçirilmeli
- Codex normal cevapları aynen gönderilmeli
- Sadece teknik çıktı Telegram'a gönderilmemeli

---

## STEP 17A Tamamlandı

Living Documentation temel politikası eklendi.

Oluşturulanlar:
- docs/LIVING_DOCUMENTATION_POLICY.md
- modules/living_documentation_guard/module.json
- modules/living_documentation_guard/settings.json
- modules/living_documentation_guard/actions.json

Sonraki adım:
STEP 17B ile module_registry, action_catalog ve system_state güncellenecek.

## STEP 18I Telegram CTO Loop Fixed

Telegram → Bridge → Task Queue → CTO → Telegram cevap döngüsü çalışıyor.

Düzeltmeler:
- Workerlar artık source=telegram görevlerini almıyor.
- Telegram görevleri sadece CTO tarafından işleniyor.
- CTO cevap verince görev DONE oluyor.
- Beklenen sonuç: telegram_cto_v1_replied.

STEP 19B-10A Model Policy
Codex model policy documented: model=gpt-5.5, reasoning=xhigh, bubblewrap installed, read-only exec verified.
