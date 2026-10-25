import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_public_build


class PublicBuildTests(unittest.TestCase):
    def test_vod_detail_output_rejects_stale_files_not_in_source(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "data" / "vods"
            published = root / "public" / "data" / "vods"
            source.mkdir(parents=True)
            published.mkdir(parents=True)
            (source / "current.json").write_text("{}", encoding="utf-8")
            (published / "current.json").write_text("{}", encoding="utf-8")
            (published / "stale-detail.json").write_text("{}", encoding="utf-8")

            with self.assertRaisesRegex(SystemExit, "unexpected public VOD detail JSON"):
                check_public_build.check_json_directory_matches_sources(source, published, "VOD detail")

    def test_permanently_excluded_ids_are_rejected_from_all_public_paths(self):
        excluded_id = "excluded-test-vod"
        forbidden_paths = (
            "data/vods.json",
            "data/vod_index.json",
            "public/data/vods.json",
            "public/data/vod_index.json",
            f"data/vods/{excluded_id}.json",
            f"public/data/vods/{excluded_id}.json",
            f"data/captions/{excluded_id}.json",
            f"public/data/captions/{excluded_id}.json",
        )

        for forbidden_relative in forbidden_paths:
            with self.subTest(path=forbidden_relative), tempfile.TemporaryDirectory() as temporary_directory:
                root = Path(temporary_directory)
                data = root / "data"
                public = root / "public"
                for aggregate in ("vods.json", "vod_index.json"):
                    (data / aggregate).parent.mkdir(parents=True, exist_ok=True)
                    (data / aggregate).write_text('{"videos": []}', encoding="utf-8")
                    (public / "data" / aggregate).parent.mkdir(parents=True, exist_ok=True)
                    (public / "data" / aggregate).write_text('{"videos": []}', encoding="utf-8")

                forbidden = root / forbidden_relative
                forbidden.parent.mkdir(parents=True, exist_ok=True)
                if forbidden.name in {"vods.json", "vod_index.json"}:
                    forbidden.write_text(
                        json.dumps({"videos": [{"vod_id": excluded_id}]}),
                        encoding="utf-8",
                    )
                else:
                    forbidden.write_text("{}", encoding="utf-8")

                with (
                    patch.object(check_public_build, "PERMANENTLY_EXCLUDED_PUBLIC_VOD_IDS", frozenset({excluded_id})),
                    patch.multiple(check_public_build, ROOT=root, DATA=data, PUBLIC=public),
                ):
                    with self.assertRaisesRegex(SystemExit, "permanently excluded VOD"):
                        check_public_build.check_permanently_excluded_public_vods()

    def test_build_script_uses_installed_react_frontend_and_whitelists_public_data(self):
        script = (ROOT / "scripts" / "build_public.sh").read_text(encoding="utf-8")
        self.assertIn("run npm run setup first", script)
        self.assertIn("node node_modules/typescript/bin/tsc -b", script)
        self.assertIn("node node_modules/vite/bin/vite.js build", script)
        self.assertNotIn("npm run build --prefix frontend", script)
        self.assertNotIn("npm ci --prefix frontend", script)
        self.assertIn("cp -R frontend/dist/. public/", script)
        self.assertNotIn("site/favicon.svg", script)
        self.assertTrue((ROOT / "frontend" / "public" / "favicon.svg").is_file())
        self.assertIn("public/data/vod_index.json", script)
        self.assertIn("public/data/vods/", script)
        self.assertIn("public/data/segment-thumbnails", script)
        self.assertIn("public/data/captions", script)
        self.assertNotIn("processed_vods.json public", script)
        self.assertNotIn("data/transcripts", script)

    def test_render_installs_dependencies_before_public_build(self):
        render = (ROOT / "render.yaml").read_text(encoding="utf-8")
        self.assertIn("npm ci && npm ci --prefix frontend && npm run build:public", render)
        self.assertIn("staticPublishPath: public", render)

    def test_operations_document_the_render_build_command(self):
        operations = (ROOT / "docs" / "OPERATIONS.md").read_text(encoding="utf-8")
        self.assertIn("npm ci && npm ci --prefix frontend && npm run build:public", operations)
        self.assertIn("Clear build cache", operations)
        self.assertIn("frontend/node_modules", operations)

    def test_generated_output_has_dedicated_checks(self):
        self.assertTrue((ROOT / "scripts" / "check_public_build.py").is_file())
        self.assertTrue((ROOT / "scripts" / "check_public_reproducibility.py").is_file())
        self.assertTrue((ROOT / "playwright.public.config.js").is_file())

    def test_production_verification_is_retained_without_repository_write_access(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("production-verification-${{ github.run_id }}", workflow)
        self.assertIn("path: production-verification.json", workflow)
        self.assertNotIn("automation/production-verification", workflow)
        self.assertNotIn("contents: write", workflow)


if __name__ == "__main__":
    unittest.main()
