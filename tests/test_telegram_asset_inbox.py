import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB_PANEL = ROOT / "web_panel"
FIXTURES = ROOT / "tests" / "fixtures" / "telegram_asset_manifest"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(WEB_PANEL))

from telegram_asset_inbox import build_telegram_asset_detail, build_telegram_asset_list  # noqa: E402


def write_inbox(root: Path, payload: dict) -> None:
    state = root / "state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "telegram_asset_inbox.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_panel_module(filename: str, module_name: str, root: Path):
    previous_home = os.environ.get("CODEX_DEV_CENTER_HOME")
    os.environ["CODEX_DEV_CENTER_HOME"] = str(root)
    try:
        spec = importlib.util.spec_from_file_location(module_name, WEB_PANEL / filename)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        return module
    finally:
        if previous_home is None:
            os.environ.pop("CODEX_DEV_CENTER_HOME", None)
        else:
            os.environ["CODEX_DEV_CENTER_HOME"] = previous_home


class TelegramAssetInboxTest(unittest.TestCase):
    def test_list_and_detail_dto_redact_raw_identifiers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_inbox(
                root,
                {
                    "items": [
                        {
                            "asset_id": "ast_123",
                            "received_at": "2026-06-04T10:00:00Z",
                            "source_type": "channel",
                            "media_type": "image",
                            "file_name": "example.jpg",
                            "mime_type": "image/jpeg",
                            "size_bytes": 123456,
                            "caption_text": "<script>alert(1)</script>\u0000 caption",
                            "status": "indexed",
                            "safe_reference": "tgref_SAFE123",
                            "file_id": "RAW_FILE_ID",
                            "chat_id": "RAW_CHAT_ID",
                            "bot_token": "RAW_BOT_TOKEN",
                            "signed_url": "https://signed.example.invalid/file",
                            "storage_path": "gs://private-bucket/raw.jpg",
                        }
                    ]
                },
            )

            payload = build_telegram_asset_list(root, "limit=10")
            detail, code = build_telegram_asset_detail(root, "ast_123")

        self.assertEqual(code, 200)
        self.assertEqual(payload["items"][0]["asset_id"], "ast_123")
        self.assertEqual(payload["items"][0]["safe_reference"], "tgref_SAFE123")
        self.assertNotIn("caption_full", payload["items"][0])
        response_text = json.dumps({"list": payload, "detail": detail}, ensure_ascii=False)
        self.assertNotIn("RAW_FILE_ID", response_text)
        self.assertNotIn("RAW_CHAT_ID", response_text)
        self.assertNotIn("RAW_BOT_TOKEN", response_text)
        self.assertNotIn("signed.example.invalid", response_text)
        self.assertNotIn("private-bucket", response_text)
        self.assertIn("raw_telegram_fields_redacted", detail["item"]["redaction_flags"])
        self.assertIn("storage_reference_redacted", detail["item"]["redaction_flags"])
        self.assertFalse(payload["security"]["raw_telegram_fields_returned"])
        self.assertEqual(payload["security"]["mutating_actions"], [])

    def test_filters_cursor_and_single_manifest_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_inbox(
                root,
                {
                    "items": [
                        {
                            "asset_id": "ast_old_image",
                            "received_at": "2026-06-04T09:00:00Z",
                            "source_type": "direct",
                            "media_type": "image",
                            "file_name": "old.png",
                            "mime_type": "image/png",
                            "status": "received",
                        },
                        {
                            "asset_id": "ast_new_doc",
                            "received_at": "2026-06-04T11:00:00Z",
                            "source_type": "group",
                            "media_type": "document",
                            "file_name": "brief.pdf",
                            "mime_type": "application/pdf",
                            "status": "quarantined",
                        },
                    ]
                },
            )

            first_page = build_telegram_asset_list(root, "limit=1")
            second_page = build_telegram_asset_list(root, f"limit=1&cursor={first_page['next_cursor']}")
            filtered = build_telegram_asset_list(root, "media_type=document&status=quarantined&q=brief")

            manifest_root = Path(tmp) / "manifest_root"
            state = manifest_root / "state"
            state.mkdir(parents=True)
            manifest = json.loads((FIXTURES / "valid_manifest_v1.json").read_text(encoding="utf-8"))
            (state / "telegram_asset_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            manifest_payload = build_telegram_asset_list(manifest_root)

        self.assertEqual([item["asset_id"] for item in first_page["items"]], ["ast_new_doc"])
        self.assertEqual(first_page["next_cursor"], "offset_1")
        self.assertEqual([item["asset_id"] for item in second_page["items"]], ["ast_old_image"])
        self.assertIsNone(second_page["next_cursor"])
        self.assertEqual([item["asset_id"] for item in filtered["items"]], ["ast_new_doc"])
        self.assertEqual(manifest_payload["items"][0]["asset_id"], "tg_20260604_105113_photo_001")
        self.assertEqual(manifest_payload["items"][0]["media_type"], "image")
        manifest_text = json.dumps(manifest_payload)
        self.assertNotIn("telegram-assets/2026/06/04", manifest_text)
        self.assertNotIn("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", manifest_text)

    def test_missing_asset_source_returns_read_only_empty_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = build_telegram_asset_list(root)
            detail, code = build_telegram_asset_detail(root, "missing")

        self.assertTrue(payload["ok"])
        self.assertTrue(payload["read_only"])
        self.assertEqual(payload["items"], [])
        self.assertEqual(payload["source"], None)
        self.assertEqual(code, 404)
        self.assertTrue(detail["read_only"])

    def test_panel_servers_expose_same_read_only_payload_wrappers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_inbox(root, {"items": [{"asset_id": "ast_panel", "received_at": "2026-06-04T12:00:00Z"}]})

            panel_server = load_panel_module("panel_server.py", "panel_server_asset_inbox_test", root)
            legacy_server = load_panel_module("server.py", "legacy_server_asset_inbox_test", root)

            for module in (panel_server, legacy_server):
                payload = module.telegram_asset_list_payload("limit=1")
                detail, code = module.telegram_asset_detail_payload("ast_panel")
                self.assertTrue(payload["read_only"])
                self.assertEqual(payload["items"][0]["asset_id"], "ast_panel")
                self.assertEqual(code, 200)
                self.assertEqual(detail["item"]["asset_id"], "ast_panel")
                self.assertEqual(payload["security"]["mutating_actions"], [])


if __name__ == "__main__":
    unittest.main()
