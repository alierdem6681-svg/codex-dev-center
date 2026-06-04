# Telegram Asset Manifest v1

Tarih: 2026-06-04

Bu sözleşme Telegram üzerinden gelen dosya, fotoğraf ve benzeri assetlerin repo içine yazılmadan runtime-only inbox dizinine alınması içindir. Canlı Telegram polling davranışı bu paketle açılmaz; modül sonraki intake katmanı tarafından çağrılacak güvenli storage temelini sağlar.

## Runtime Inbox

Varsayılan kök:

```text
${RUNTIME_ASSET_INBOX_DIR}/telegram/YYYY/MM/DD/<asset_id>/
  blob
  manifest.json
```

`RUNTIME_ASSET_INBOX_DIR` tanımlı değilse uygulama runtime state alanı kullanılır: `state/telegram_assets/inbox`. Bu dizin repo artefact'i değildir; ham Telegram dosyası commit edilmez.

Storage path sadece sistemin ürettiği `asset_id` ile kurulur. Kullanıcı dosya adı, Telegram `file_path` veya MIME uzantısı yerel path kararı için kullanılmaz.

## Limitler

- `TELEGRAM_ASSET_MAX_BYTES` varsayılanı: `20971520`.
- Bu değer Telegram Bot API public `getFile` indirme üst sınırı olan 20 MB üzerine çıkarılsa bile modül 20 MB ile sınırlar.
- `file_size` biliniyorsa `getFile` çağrısından önce kontrol edilir.
- HTTP `Content-Length` biliniyorsa stream başlamadan kontrol edilir.
- Stream sırasında sayaç limit üstüne çıkarsa `.part` dosyası ve manifest temizlenir.

## Manifest

Minimum başarılı manifest:

```json
{
  "schema_version": 1,
  "asset_id": "uuid-or-ulid",
  "source": "telegram",
  "received_at": "2026-06-04T10:22:55Z",
  "telegram": {
    "file_id": "telegram-file-id",
    "file_unique_id": "telegram-unique-id",
    "chat_id": "sha256:...",
    "message_id": 123,
    "file_path_present": true
  },
  "original": {
    "file_name": "optional-name.ext",
    "declared_mime": "application/pdf",
    "detected_mime": "application/pdf",
    "size_bytes": 12345,
    "sha256": "hex"
  },
  "storage": {
    "relative_blob_path": "blob",
    "manifest_path": "manifest.json"
  },
  "policy": {
    "max_bytes": 20971520,
    "accepted": true,
    "rejection_reason": null
  }
}
```

Manifestte bot token, Telegram download URL'i, raw dosya byte'ları, raw kullanıcı mesajı veya Telegram `file_path` değeri tutulmaz. `chat_id` hashlenir.

## Hata Davranışı

Red nedenleri örnekleri:

- `file_size_limit_exceeded`
- `content_length_limit_exceeded`
- `stream_size_limit_exceeded`
- `mime_not_allowed`
- `telegram_file_path_missing`
- `no_supported_asset`

Başarısız durumda manifest yazılmaz. Geçici `.part` dosyaları ve kısmi blob temizlenir.

## Test Sözleşmesi

`tests/test_runtime_status_model.py` şu davranışları sabitler:

- Başarılı PDF fixture için blob ve manifest birlikte oluşur.
- Storage path içinde kullanıcı dosya adı kullanılmaz.
- Manifestte `file_path` yoktur, sadece `file_path_present` vardır.
- `chat_id` hashlenir.
- Declared MIME ve detected MIME ayrı saklanır.
- Declared size, `Content-Length` ve stream limit aşımı manifest bırakmadan reddedilir.
- Telegram file URL'i ve bot token benzeri değerler sanitizer ile gizlenir.
