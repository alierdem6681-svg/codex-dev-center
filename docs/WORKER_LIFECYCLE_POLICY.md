# WORKER LIFECYCLE POLICY

Workerlar kuyruk bosken uyumali veya dusuk kaynak moduna gecmelidir.
Is gelince CTO/Supervisor uygun worker'i uyandirmalidir.

Durumlar:
- SLEEPING
- IDLE
- ASSIGNED
- RUNNING
- REVIEWING
- BLOCKED
- ERROR
- STOPPED

CTO gorev dagitirken sunlari dikkate alir:
- Worker rolu
- Worker yetenegi
- Risk limiti
- Mevcut yuk
- Gecmis hata durumu
- Gorevin modulu
- Hedef uyumu

Worker Dispatch v2 small apply ile CTO router ve lifecycle backlog dispatcher worker profil dosyalarini salt okunur okuyarak role/capability/risk uygunluguna gore secim yapar. Lease, retry backoff ve event telemetry sonraki paket kapsamindadir.
