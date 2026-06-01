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
