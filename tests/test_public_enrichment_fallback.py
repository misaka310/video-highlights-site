import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "verify_public_enrichment.py"


class PublicEnrichmentFallbackTests(unittest.TestCase):
    def load_verifier(self):
        fake_transcribe = types.ModuleType("transcribe_segments")
        fake_transcribe.is_publishable_headline = lambda headline: bool(str(headline).strip())
        fake_transcribe.validate_final_headline_japanese = lambda headline: SimpleNamespace(reasons=[])

        spec = importlib.util.spec_from_file_location("verify_public_enrichment_under_test", SCRIPT_PATH)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"transcribe_segments": fake_transcribe}):
            spec.loader.exec_module(module)
        return module

    def build_payload(self, *, headline: str = "", reason: str = "Chat activity spike around 01:02:03 (z-score=4.2)."):
        return {
            "videos": [
                {
                    "provider": "youtube",
                    "vod_id": "123",
                    "items": [
                        {
                            "id": "123_3723_3783",
                            "headline": headline,
                            "reason": reason,
                            "screenshot_url": "/data/segment-thumbnails/123/123_3723_3783.webp",
                        }
                    ],
                }
            ]
        }

    def create_screenshot(self, root: Path) -> None:
        path = root / "data" / "segment-thumbnails" / "123" / "123_3723_3783.webp"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"webp")

    def test_missing_youtube_headline_does_not_block(self):
        verifier = self.load_verifier()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.create_screenshot(root)
            for reason in ("Chat activity spike around 01:02:03 (z-score=4.2).", ""):
                failures = verifier.collect_public_enrichment_failures(self.build_payload(reason=reason), root=root)
                self.assertEqual([], failures)

    def test_unpublishable_youtube_headline_remains_blocking(self):
        verifier = self.load_verifier()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.create_screenshot(root)
            with patch.object(verifier, "is_publishable_headline", return_value=False):
                failures = verifier.collect_public_enrichment_failures(self.build_payload(headline="どういうこと？」"), root=root)
        self.assertEqual(1, len(failures))
        self.assertIn("invalid headline", failures[0])

    def test_runtime_loader_uses_detail_payload_referenced_by_index(self):
        verifier = self.load_verifier()
        loader = getattr(verifier, "load_runtime_public_videos", None)
        self.assertIsNotNone(loader, "runtime public enrichment must load the same detail JSON used by the UI")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            detail_dir = data_dir / "vods"
            detail_dir.mkdir(parents=True)
            (data_dir / "vod_index.json").write_text(
                json.dumps(
                    {
                        "videos": [
                            {
                                "vod_id": "123",
                                "detail_path": "/data/vods/123.json",
                                "published_at": "2026-09-03T00:00:00+09:00",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (detail_dir / "123.json").write_text(
                json.dumps(
                    {
                        "vod_id": "123",
                        "items": [
                            {
                                "id": "123_3723_3783",
                                "reason": "detail payload",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (data_dir / "vods.json").write_text(
                json.dumps(
                    {
                        "videos": [
                            {
                                "vod_id": "123",
                                "items": [
                                    {
                                        "id": "123_3723_3783",
                                        "reason": "aggregate payload must not be the runtime source",
                                    }
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            videos = loader(root)

        self.assertEqual("detail payload", videos[0]["items"][0]["reason"])


if __name__ == "__main__":
    unittest.main()
