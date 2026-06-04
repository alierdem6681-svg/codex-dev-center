# CONTROLLED APPLY PIPELINE

## Amac

Controlled Apply Pipeline, onaylanmis veya validate edilmis proposal ciktisini dogrudan production islemine cevirmeden once izole repo clone ve worker branch uzerinde kucuk, test edilebilir ve geri alinabilir repo degisikligine donusturur.

Bu akisin ciktisi PR/finalizer icin hazir kanittir. Production deploy yapmaz.

## Zorunlu Asamalar

1. Proposal review: Worker sadece task/proposal kanitini apply girdisi olarak kullanir.
2. Isolated clone and branch: Apply yalniz yerel `.git/` metadata dizini olan izole clone icinde ve `worker/...` branch uzerinde calisir.
3. Patch plan: Degisiklik kapsami kucuk tutulur; commit kapsaminda yalniz gerekli repo dosyalari kalir.
4. Diff review: Exact path allowlist, blocked runtime path ve traversal kontrolleri PR oncesi gecmelidir.
5. Secret scan: Degisen text dosyalari credential/private key/token patternlerine karsi taranir.
6. Local tests: Compile, ilgili unit testler ve production readiness dry-run/local gate sonucuna gore PASS/FAIL yazilir.
7. Apply report: Rapor patch scope, diff review, secret scan, local pipeline, production deploy yapilmadi kaniti ve rollback notunu icerir.
8. Rollback note: Branch silme/revert, merge commit revert ve runtime rollback gerekmedigi bilgisi acik yazilir.

## Kapsam Disi

- Production deploy.
- VM SSH veya runtime dosyalarina elle mudahale.
- Runtime `state/`, `logs/`, `reports/`, `workspaces/` mutasyonu.
- Secret/env/token/private key degeri okuma, yazma veya gosterme.
- IAM, billing, DNS/firewall, destructive database veya reklam platformu live-write islemi.

## Rapor Sozlesmesi

`supervisor/worker_runner.py` repo apply raporu su bolumleri uretir:

- `Controlled Apply Checklist`
- `Controlled Apply Stage Plan`
- `Rollback Note`

Stage plan, proposal review, patch plan, diff review, secret scan, local tests, report, rollback note ve production deploy durumlarini sirasiyla yazmalidir.
