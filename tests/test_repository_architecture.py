import ast
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".py", ".js", ".mjs", ".json", ".yml", ".yaml", ".html", ".css", ".sh"}


def iter_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key)
            yield from iter_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_keys(child)


class RepositoryArchitectureTests(unittest.TestCase):
    def test_public_enrichment_modules_exist_without_private_artifacts(self):
        required_paths = (
            ROOT / "requirements-transcribe.txt",
            ROOT / "scripts" / "transcribe_segments.py",
            ROOT / "scripts" / "headline_generation.py",
            ROOT / "scripts" / "transcription",
            ROOT / "scripts" / "verify_public_enrichment.py",
        )
        self.assertEqual([str(path.relative_to(ROOT)) for path in required_paths if not path.exists()], [])

        forbidden_paths = (
            ROOT / "data" / "chat-archive",
            ROOT / "data" / "transcripts",
            ROOT / "data" / "timestamps",
            ROOT / "data" / "transcript-alignments",
            ROOT / "scripts" / "match_youtube_videos.py",
        )
        self.assertEqual([str(path.relative_to(ROOT)) for path in forbidden_paths if path.exists()], [])

    def test_public_site_documents_define_multi_provider_oracle_contract(self):
        spec = (ROOT / "docs" / "PUBLIC_SITE_SPEC.md").read_text(encoding="utf-8")
        playback = (ROOT / "docs" / "PLAYBACK_SPEC.md").read_text(encoding="utf-8")
        data_contract = (ROOT / "docs" / "data-contract.md").read_text(encoding="utf-8")
        operations = (ROOT / "docs" / "OPERATIONS.md").read_text(encoding="utf-8")

        self.assertIn("YouTube", spec)
        self.assertIn("provider", spec)
        self.assertIn("YouTube IFrame Player API", playback)
        self.assertIn("videoOffsetTimeMsec", data_contract)
        self.assertIn("YOUTUBE_ORACLE_HOST", operations)
        self.assertIn("YOUTUBE_ORACLE_KEY_PATH", operations)

    def test_disallowed_backend_integrations_are_absent_from_public_infrastructure(self):
        disallowed_markers = (
            "".join(("ano", "sa")),
            "".join(("cloud", "flare")),
        )
        # Public infrastructure must not introduce private backend integrations.
        roots = [ROOT / "scripts", ROOT / ".github", ROOT / "config"]
        matches = []
        for source_root in roots:
            for path in source_root.rglob("*"):
                if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                    continue
                if any(part in {"node_modules", "public", "__pycache__"} for part in path.parts):
                    continue
                text = path.read_text(encoding="utf-8-sig", errors="ignore").lower()
                for marker in disallowed_markers:
                    if marker in text:
                        matches.append(f"{path.relative_to(ROOT)}:{marker}")
        self.assertEqual(matches, [])

    def test_private_metadata_keys_are_absent_from_data(self):
        private_key_parts = (
            "".join(("trans", "cript")),
            "".join(("you", "tube")),
            "".join(("time", "stamp")),
        )
        matches = []
        paths = [
            ROOT / "data" / "processed_vods.json",
            ROOT / "data" / "vods.json",
            ROOT / "data" / "vod_index.json",
            *(ROOT / "data" / "vods").glob("*.json"),
        ]
        for path in paths:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            for key in iter_keys(payload):
                for part in private_key_parts:
                    if part in key.lower():
                        matches.append(f"{path.relative_to(ROOT)}:{key}")
        self.assertEqual(matches, [])

    def test_instance_identity_is_not_hardcoded_in_public_pipeline(self):
        instance_markers = (
            "".join(("doti", "tao")),
            "".join(("709", "803150")),
            "".join(("night", "reign")),
        )
        # The published site intentionally preserves repository 19's identity.
        # Only the reusable public data pipeline must remain configuration-driven.
        roots = [ROOT / "scripts"]
        matches = []
        for source_root in roots:
            for path in source_root.rglob("*"):
                if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                    continue
                text = path.read_text(encoding="utf-8-sig", errors="ignore").lower()
                for marker in instance_markers:
                    if marker in text and path.name != "check_public_trailer.py":
                        matches.append(f"{path.relative_to(ROOT)}:{marker}")
        self.assertEqual(matches, [])

    def test_frontend_fallbacks_are_instance_neutral(self):
        paths = (
            ROOT / "frontend" / "index.html",
            ROOT / "frontend" / "package.json",
            ROOT / "frontend" / "src" / "App.tsx",
            ROOT / "frontend" / "src" / "hooks" / "use-site-metadata.ts",
        )
        matches = [
            str(path.relative_to(ROOT))
            for path in paths
            if "dotitao" in path.read_text(encoding="utf-8").lower()
        ]
        self.assertEqual(matches, [])

    def test_instance_configuration_and_examples_exist(self):
        required_paths = (
            ROOT / "config" / "site.json",
            ROOT / "config" / "site.example.json",
            ROOT / "config" / "tag-rules.json",
            ROOT / "config" / "tag-rules.example.json",
        )
        self.assertEqual([str(path.relative_to(ROOT)) for path in required_paths if not path.is_file()], [])

        site = json.loads((ROOT / "config" / "site.json").read_text(encoding="utf-8"))
        site_example = json.loads((ROOT / "config" / "site.example.json").read_text(encoding="utf-8"))
        tag_rules = json.loads((ROOT / "config" / "tag-rules.json").read_text(encoding="utf-8"))
        tag_rules_example = json.loads(
            (ROOT / "config" / "tag-rules.example.json").read_text(encoding="utf-8")
        )

        self.assertEqual(sorted(site), ["site", "twitch"])
        self.assertEqual(sorted(site_example), ["site", "twitch"])
        self.assertEqual(sorted(tag_rules), ["extra_tag_rules"])
        self.assertEqual(sorted(tag_rules_example), ["extra_tag_rules"])
        self.assertEqual(
            tag_rules["extra_tag_rules"],
            [{"tag": "つべ", "patterns": ["つべ"]}],
        )

    def test_live_production_verification_uses_instance_config_and_html_tolerant_hashing(self):
        spec = (ROOT / "tests" / "production-mobile-playback.spec.js").read_text(encoding="utf-8")
        config = (ROOT / "playwright.live.config.js").read_text(encoding="utf-8")

        self.assertIn("config/site.json", spec)
        self.assertIn("SITE_CONFIG.site?.base_url", spec)
        self.assertNotIn('process.env.LIVE_BASE_URL || ""', spec)
        self.assertIn('relativePath.endsWith(".html")', spec)
        self.assertIn('filter((line) => line.trim() !== "")', spec)
        self.assertIn("config/site.json", config)
        self.assertNotIn("dotitao-moments.onrender.com", config)

    def test_production_frontend_has_no_legacy_site_dependency(self):
        production_paths = (
            ROOT / "frontend" / "vite.config.ts",
            ROOT / "scripts" / "build_public.sh",
            ROOT / "render.yaml",
        )
        matches = []
        for path in production_paths:
            value = path.read_text(encoding="utf-8-sig")
            if "site/" in value or "site\\" in value:
                matches.append(str(path.relative_to(ROOT)))
        self.assertEqual(matches, [])
        self.assertTrue((ROOT / "frontend" / "public" / "favicon.svg").is_file())

    def test_legacy_ui_assets_and_tools_are_removed(self):
        removed_paths = (
            ROOT / "site",
            ROOT / "scripts" / "dev-server.mjs",
            ROOT / "scripts" / "sync_public_runtime.py",
            ROOT / "playwright.config.js",
            ROOT / "playwright.selfhosted.config.js",
            ROOT / "tests" / "formatters.test.mjs",
            ROOT / "tests" / "site-shell.test.mjs",
            ROOT / "tests" / "vod-list-view.test.mjs",
            ROOT / "tests" / "vod-normalizer.test.mjs",
            ROOT / "tests" / "latest-vods-public.spec.js",
            ROOT / "tests" / "mobile-click-autoplay.spec.js",
            ROOT / "tests" / "playback-policy.spec.js",
            ROOT / "tests" / "player-portal.spec.js",
            ROOT / "tests" / "rewind.spec.js",
            ROOT / "tests" / "ui.spec.js",
        )
        self.assertEqual(
            [str(path.relative_to(ROOT)) for path in removed_paths if path.exists()],
            [],
        )

    def test_public_site_specification_is_canonical_and_complete(self):
        agents_path = ROOT / "AGENTS.md"
        spec_path = ROOT / "docs" / "PUBLIC_SITE_SPEC.md"
        architecture_path = ROOT / "docs" / "site-architecture.md"
        operations_path = ROOT / "docs" / "OPERATIONS.md"

        self.assertTrue(agents_path.is_file())
        self.assertTrue(spec_path.is_file())
        self.assertTrue(architecture_path.is_file())
        self.assertTrue(operations_path.is_file())

        agents = agents_path.read_text(encoding="utf-8")
        spec = spec_path.read_text(encoding="utf-8")
        architecture = architecture_path.read_text(encoding="utf-8")
        operations = operations_path.read_text(encoding="utf-8")

        self.assertIn("docs/PUBLIC_SITE_SPEC.md", agents)
        self.assertIn("1792 x 864", agents)
        self.assertIn("縦スクロールを発生させない", agents)
        self.assertIn("公開UIの唯一の正本は `frontend/`", agents)
        self.assertIn("docs/OPERATIONS.md", agents)

        required_spec_markers = (
            "この文書は `dotitao moments` 公開サイトの製品仕様の正本",
            "## 5. PCレイアウトの受入条件",
            "## 7. VOD・見どころ表示仕様",
            "## 9. 盛り上がりマップ",
            "## 10. 再生仕様",
            "## 12. データとプライバシー",
            "## 13. ビルド仕様",
            "## 14. 変更禁止事項",
            "## 15. 検証仕様",
        )
        for marker in required_spec_markers:
            self.assertIn(marker, spec)

        self.assertIn("`frontend/`", architecture)
        self.assertIn("公開UIの正本", architecture)
        self.assertIn("公開UIの別実装や同期経路を追加せず", architecture)

        required_operations_markers = (
            "## 定期VOD更新",
            "09:00 JST",
            "workflow_dispatch",
            "GITHUB_TOKEN",
            "action_required",
            "automation/update-vods",
        )
        for marker in required_operations_markers:
            self.assertIn(marker, operations)

    def test_headline_source_selection_is_separate_from_transcription_entrypoint(self):
        entrypoint_path = ROOT / "scripts" / "transcribe_segments.py"
        source_selection_path = ROOT / "scripts" / "headline_source_selection.py"
        candidate_selection_path = ROOT / "scripts" / "headline_candidate_selection.py"

        self.assertTrue(source_selection_path.is_file())
        self.assertTrue(candidate_selection_path.is_file())
        self.assertLess(len(source_selection_path.read_text(encoding="utf-8").splitlines()), 1800)
        self.assertLess(len(candidate_selection_path.read_text(encoding="utf-8").splitlines()), 1800)
        self.assertLess(len(entrypoint_path.read_text(encoding="utf-8").splitlines()), 2000)

        module = ast.parse(entrypoint_path.read_text(encoding="utf-8"))
        locally_defined = {
            node.name
            for node in module.body
            if isinstance(node, (ast.FunctionDef, ast.ClassDef))
        }
        self.assertNotIn("_score_source_sentence_candidate", locally_defined)
        self.assertNotIn("_select_source_sentences", locally_defined)
        self.assertNotIn("build_headline_source_text", locally_defined)

    def test_twitch_sources_are_separate_from_vod_update_orchestration(self):
        update_path = ROOT / "scripts" / "update_vods.py"
        sources_path = ROOT / "scripts" / "vod_sources.py"

        self.assertTrue(sources_path.is_file())
        self.assertLess(len(update_path.read_text(encoding="utf-8").splitlines()), 900)

        module = ast.parse(update_path.read_text(encoding="utf-8"))
        locally_defined = {
            node.name
            for node in module.body
            if isinstance(node, (ast.FunctionDef, ast.ClassDef))
        }
        self.assertNotIn("fetch_latest_videos", locally_defined)
        self.assertNotIn("fetch_chat_data", locally_defined)
        self.assertNotIn("post_gql", locally_defined)

    def test_vod_highlight_analysis_is_separate_from_update_orchestration(self):
        update_path = ROOT / "scripts" / "update_vods.py"
        highlight_path = ROOT / "scripts" / "vod_highlights.py"

        self.assertTrue(highlight_path.is_file())
        self.assertLess(len(update_path.read_text(encoding="utf-8").splitlines()), 1500)

        module = ast.parse(update_path.read_text(encoding="utf-8"))
        locally_defined = {
            node.name
            for node in module.body
            if isinstance(node, (ast.FunctionDef, ast.ClassDef))
        }
        self.assertNotIn("detect_items", locally_defined)
        self.assertNotIn("rank_segments", locally_defined)
        self.assertNotIn("classify_segment_tags", locally_defined)

    def test_public_docs_match_supported_commands_and_data_processing(self):
        contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
        spec = (ROOT / "docs" / "PUBLIC_SITE_SPEC.md").read_text(encoding="utf-8")
        docs_index = (ROOT / "docs" / "README.md").read_text(encoding="utf-8")
        privacy = (ROOT / "PRIVACY.md").read_text(encoding="utf-8")

        for document in (contributing, spec):
            self.assertNotIn("node --test tests/*.test.mjs", document)
        self.assertIn("npm run verify", contributing)
        self.assertIn("Whisper", docs_index)
        self.assertIn("GoatCounter", privacy)
        self.assertTrue((ROOT / ".env.example").is_file())

    def test_vod_update_starts_before_displayed_update_time(self):
        workflow = (ROOT / ".github" / "workflows" / "update-vods.yml").read_text(encoding="utf-8")
        self.assertIn('cron: "7 21 * * *"', workflow)

        module = ast.parse((ROOT / "scripts" / "update_vods.py").read_text(encoding="utf-8"))
        update_hour = None

        for node in module.body:
            if not isinstance(node, ast.Assign):
                continue
            if any(isinstance(target, ast.Name) and target.id == "UPDATE_HOUR_LOCAL" for target in node.targets):
                update_hour = ast.literal_eval(node.value)
                break
        self.assertEqual(update_hour, 9)



if __name__ == "__main__":
    unittest.main()
