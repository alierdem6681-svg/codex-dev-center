import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from supervisor import telegram_asset_safety


class TelegramAssetSafetyTest(unittest.TestCase):
    def valid_manifest(self, data: bytes | None = None) -> tuple[dict, dict[str, bytes]]:
        content = data or b"small deterministic image payload"
        digest = hashlib.sha256(content).hexdigest()
        contract = telegram_asset_safety.asset_safety_contract()
        manifest = {
            "schema_version": contract["manifest_schema_version"],
            "batch_id": "batch-1",
            "asset_count": 1,
            "caption": "safe caption",
            "assets": [
                {
                    "id": "asset-1",
                    "filename": "photo.jpg",
                    "mime_type": "image/jpeg",
                    "size_bytes": len(content),
                    "sha256": digest,
                }
            ],
        }
        return manifest, {"asset-1": content}

    def error_codes(self, result: dict) -> set[str]:
        return {error["code"] for error in result["errors"]}

    def test_valid_manifest_accepts_asset_and_checksum(self):
        manifest, asset_bytes = self.valid_manifest()

        result = telegram_asset_safety.validate_asset_manifest(manifest, asset_bytes)

        self.assertTrue(result["ok"])
        self.assertEqual(result["accepted_asset_count"], 1)
        self.assertEqual(result["total_size_bytes"], len(asset_bytes["asset-1"]))
        self.assertFalse(result["real_telegram_fallback_allowed"])

    def test_rejects_path_traversal_dangerous_extension_and_mime_mismatch(self):
        manifest, asset_bytes = self.valid_manifest()
        manifest["assets"][0]["filename"] = "../photo.jpg.exe"
        manifest["assets"][0]["mime_type"] = "image/jpeg"

        result = telegram_asset_safety.validate_asset_manifest(manifest, asset_bytes)

        self.assertFalse(result["ok"])
        codes = self.error_codes(result)
        self.assertIn("unsafe_filename", codes)
        self.assertIn("dangerous_extension", codes)
        self.assertIn("mime_extension_mismatch", codes)

    def test_rejects_manifest_limit_violations_from_contract(self):
        contract = telegram_asset_safety.asset_safety_contract()
        manifest, _asset_bytes = self.valid_manifest(b"x")
        assets = []
        for index in range(contract["max_asset_count"] + 1):
            assets.append(
                {
                    "id": f"asset-{index}",
                    "filename": f"asset-{index}.txt",
                    "mime_type": "text/plain",
                    "size_bytes": 1,
                    "sha256": hashlib.sha256(f"asset-{index}".encode("utf-8")).hexdigest(),
                }
            )
        manifest["asset_count"] = len(assets) + 1
        manifest["caption"] = "x" * (contract["max_caption_length"] + 1)
        manifest["assets"] = assets
        manifest["assets"][0]["size_bytes"] = contract["max_asset_bytes"] + 1

        result = telegram_asset_safety.validate_asset_manifest(manifest)

        self.assertFalse(result["ok"])
        codes = self.error_codes(result)
        self.assertIn("asset_count_limit_exceeded", codes)
        self.assertIn("manifest_asset_count_mismatch", codes)
        self.assertIn("caption_limit_exceeded", codes)
        self.assertIn("asset_size_limit_exceeded", codes)

    def test_rejects_duplicate_id_checksum_mismatch_and_unknown_fields(self):
        manifest, asset_bytes = self.valid_manifest()
        manifest["unexpected"] = "value"
        duplicate = dict(manifest["assets"][0])
        duplicate["filename"] = "copy.jpg"
        manifest["assets"].append(duplicate)
        manifest["asset_count"] = 2
        manifest["assets"][0]["sha256"] = hashlib.sha256(b"different").hexdigest()
        manifest["assets"][0]["extra"] = "value"

        result = telegram_asset_safety.validate_asset_manifest(manifest, asset_bytes)

        self.assertFalse(result["ok"])
        codes = self.error_codes(result)
        self.assertIn("unknown_manifest_field", codes)
        self.assertIn("unknown_asset_field", codes)
        self.assertIn("duplicate_asset_id", codes)
        self.assertIn("checksum_mismatch", codes)

    def test_redaction_masks_secret_like_values_without_masking_checksum(self):
        digest = hashlib.sha256(b"asset").hexdigest()
        payload = {
            "error": f"Authorization: Bearer fakebearervalue123456 and bot_token=SHOULD_HIDE digest={digest}",
        }

        snapshot = telegram_asset_safety.build_dashboard_asset_snapshot(
            {
                "ok": False,
                "accepted_asset_count": 0,
                "errors": [{"code": "simulated", "message": payload["error"]}],
            }
        )
        encoded = json.dumps(snapshot, sort_keys=True)

        self.assertNotIn("fakebearervalue123456", encoded)
        self.assertNotIn("SHOULD_HIDE", encoded)
        self.assertIn("[REDACTED_SECRET]", encoded)
        self.assertIn(digest, encoded)

    def test_simulator_is_non_network_retry_scoped_and_idempotent(self):
        simulator = telegram_asset_safety.TelegramAssetSendSimulator()
        payload = {"media": [{"asset_id": "asset-1"}]}

        success = simulator.send_media_group(payload, scenario="success", idempotency_key="idem-1")
        duplicate = simulator.send_media_group(payload, scenario="success", idempotency_key="idem-1")
        unauthorized = simulator.send_media_group(payload, scenario="unauthorized")
        rate_limit = simulator.send_media_group(payload, scenario="rate_limit", retry_after_seconds=7)

        self.assertTrue(success["ok"])
        self.assertFalse(success["network_performed"])
        self.assertTrue(duplicate["duplicate_suppressed"])
        self.assertEqual(len(simulator.calls), 3)
        self.assertFalse(unauthorized["retryable"])
        self.assertTrue(rate_limit["retryable"])
        self.assertEqual(rate_limit["retry_after_seconds"], 7)
        self.assertFalse(rate_limit["real_telegram_fallback_allowed"])

    def test_contract_can_be_loaded_from_module_settings_without_hardcoded_test_limits(self):
        custom = {
            "contract": {
                "max_asset_count": 2,
                "max_asset_bytes": 8,
                "max_total_bytes": 16,
                "max_caption_length": 4,
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(json.dumps(custom), encoding="utf-8")
            contract = telegram_asset_safety.asset_safety_contract(path)

        self.assertEqual(contract["max_asset_count"], custom["contract"]["max_asset_count"])
        self.assertEqual(contract["max_asset_bytes"], custom["contract"]["max_asset_bytes"])
        self.assertEqual(contract["max_total_bytes"], custom["contract"]["max_total_bytes"])
        self.assertEqual(contract["max_caption_length"], custom["contract"]["max_caption_length"])


if __name__ == "__main__":
    unittest.main()
