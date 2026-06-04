# Controlled Apply Pipeline v1

## Amac

Validated proposal ciktilarini repo degisikligine tasirken degisikligi izole branch/worktree, exact path allowlist, secret scan, local gate ve PR adimlariyla sinirlamak.

## Kapsam

- Proposal kanitinin okunmasi.
- Kucuk, test edilebilir ve geri alinabilir patch uygulanmasi.
- Degisen dosyalarin allowlist ve runtime/secret path blokaji ile incelenmesi.
- Secret pattern scan calistirilmasi.
- Local compile, unit test ve production readiness kapilarinin calistirilmasi.
- Apply raporunda patch kapsami, diff sonucu, test sonucu, kalan risk ve rollback notu yazilmasi.

## Kapsam Disi

- Production deploy.
- Runtime `state/`, `logs/`, `reports/` veya `workspaces/` dosyalarini PR degisikligi olarak almak.
- Secret/env/token/private key degeri okuma, yazma veya gostermek.
- IAM, billing, DNS, firewall, destructive database veya reklam platformu live-write islemleri.

## Zorunlu Kontrol Kapilari

1. Proposal tamamlanmis olmali.
2. Apply yalniz izole git worktree ve worker branch uzerinde calismali.
3. Degisen commit dosyalari exact allowlist icinde kalmali.
4. Runtime ve secret path bulgusunda apply fail veya approval-required olmali.
5. Secret scan bulgu vermemeli.
6. Local pipeline PASS olmali.
7. PR oncesi rapor patch scope, diff review, validation status, local pipeline ve rollback note icermeli.

## Rollback Sozlesmesi

- PR merge edilmeden once rollback branch silme veya PR commit revert ile yapilir.
- Merge sonrasi rollback merge commit revert veya listelenen dosyalari onceki committen geri alma ile yapilir.
- Bu apply akisi production deploy veya runtime state mutation yapmadigi icin runtime rollback gerektirmez.

