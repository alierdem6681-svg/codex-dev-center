# Codex Safe Task Execution

Bu modül Codex CLI ile görev yürütme altyapısını hazırlar.

Varsayılan durum:
- enabled: false
- unattended_execution_enabled: false
- production değişiklikleri kapalı
- secret okuma kapalı
- GCloud mutate kapalı

Akış:
1. Görev hazırlanır
2. Ayrı workspace oluşturulur
3. Prompt ve context dosyaları yazılır
4. Log capture açılır
5. Output Guard uygulanır
6. Test zorunlu tutulur
7. Rapor üretilir
8. Handover güncellenir
9. High/critical aksiyonlar approval gate ister
