import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from supervisor.telegram_asset_manifest import (  # noqa: E402
    MAX_TELEGRAM_DOWNLOAD_BYTES,
    assert_valid_manifest,
    validate_manifest,
)


FIXTURES = ROOT / "tests" / "fixtures" / "telegram_asset_manifest"


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class TelegramAssetManifestContractTest(unittest.TestCase):
    def test_schema_fixture_declares_manifest_v1_required_fields(self):
        schema = fixture("manifest_schema_v1.json")

        self.assertEqual(schema["title"], "Telegram Asset Manifest v1")
        self.assertEqual(schema["properties"]["schema_version"]["const"], 1)
        self.assertEqual(schema["properties"]["source"]["const"], "telegram")
        self.assertEqual(schema["properties"]["policy"]["properties"]["max_bytes"]["maximum"], 20971520)
        self.assertEqual(
            schema["required"],
            [
                "schema_version",
                "asset_id",
                "source",
                "received_at",
                "telegram",
                "original",
                "storage",
                "policy",
            ],
        )

    def test_valid_manifest_fixture_passes_without_network_or_runtime_storage(self):
        manifest = fixture("valid_manifest_v1.json")

        self.assertEqual(validate_manifest(manifest), [])
        self.assertEqual(assert_valid_manifest(manifest), manifest)

    def test_boundary_fixture_allows_exact_telegram_20mb_limit(self):
        manifest = fixture("boundary_manifest_v1.json")

        self.assertEqual(MAX_TELEGRAM_DOWNLOAD_BYTES, 20971520)
        self.assertEqual(manifest["policy"]["max_bytes"], MAX_TELEGRAM_DOWNLOAD_BYTES)
        self.assertEqual(manifest["telegram"]["file_size"], MAX_TELEGRAM_DOWNLOAD_BYTES)
        self.assertEqual(manifest["original"]["size_bytes"], MAX_TELEGRAM_DOWNLOAD_BYTES)
        self.assertEqual(validate_manifest(manifest), [])

    def test_manifest_rejects_download_limit_above_20mb(self):
        manifest = fixture("invalid_exceeds_limit_manifest_v1.json")

        errors = validate_manifest(manifest)

        self.assertIn("manifest.policy.max_bytes: must be <= 20971520", errors)
        self.assertIn("manifest.telegram.file_size: must be <= 20971520", errors)
        self.assertIn("manifest.original.size_bytes: must be <= 20971520", errors)

    def test_manifest_rejects_forbidden_raw_url_and_sensitive_fields(self):
        manifest = fixture("invalid_forbidden_fields_manifest_v1.json")

        errors = validate_manifest(manifest)

        self.assertIn("manifest.raw: forbidden manifest key", errors)
        self.assertIn("manifest.telegram.file_url: forbidden manifest key", errors)
        self.assertIn("manifest.telegram.token: forbidden manifest key", errors)

    def test_manifest_rejects_missing_required_storage_block(self):
        manifest = fixture("valid_manifest_v1.json")
        invalid = copy.deepcopy(manifest)
        invalid.pop("storage")

        errors = validate_manifest(invalid)

        self.assertIn("manifest.storage: required", errors)
        self.assertIn("manifest.storage: must be an object", errors)


if __name__ == "__main__":
    unittest.main()
