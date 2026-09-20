import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import transcribe_segments as ts
import headline_source_selection as hss


class HeadlineFallbackTests(unittest.TestCase):
    def test_source_sentence_strips_japanese_sentence_punctuation(self):
        self.assertEqual(hss.clean_source_sentence("  迷路。  "), "迷路")

    def test_tag_fallbacks_are_not_used_as_publishable_content(self):
        cases = {
            "好プレー": "好プレーで盛り上がる",
            "おめ": "祝福コメントが集まる",
            "ホラー": "緊張の展開にざわつく",
            "まずい": "予想外の展開に驚く",
            "ww": "笑いが一気に広がる",
        }
        for tag, fallback in cases.items():
            with self.subTest(tag=tag):
                self.assertEqual(ts.build_tag_based_fallback_headline([tag]), "")

    def test_broken_or_verbatim_headlines_are_not_publishable(self):
        rejected = (
            "いや",
            "すすみませ",
            "アドレス",
            "はい",
            "起点ってい",
            "100万回感謝をするっていう",
            "昨日はちょっと老犬の介護に行ってましたいやまぁ結構ね長生",
            "あーもうなんでフルリモート終わったのこの世界勘弁して",
            "いやに注目が集まる",
            "すすみませに注目が集まる",
            "アドレスに注目が集まる",
            "はいに注目が集まる",
            "起点っていに注目が集まる",
            "なんで?商人がある",
            "はい?エンジェルナンバー",
        )
        for headline in rejected:
            with self.subTest(headline=headline):
                self.assertFalse(ts.is_publishable_headline(headline))

    def test_invalid_content_headline_is_not_replaced_by_tag_fallback(self):
        target = ts.SegmentTarget(
            video={"title": ""},
            item={"tags": ["ホラー"]},
            start_sec=0,
            end_sec=60,
            needs_transcript=False,
            needs_headline=True,
        )
        outcome = ts.HeadlineGenerationOutcome(
            headline=ts.HeadlineResult(
                text="いや",
                model="test",
                source="test",
            ),
            generation_reason="test",
        )

        result = ts._apply_headline_post_filter_fallback(
            target,
            label="test",
            outcome=outcome,
            headline_source_config=ts.HEADLINE_SOURCE_CONFIG,
            transcript_text="",
            prepared_source_text="",
        )

        self.assertEqual(result.headline.text, "")
        self.assertEqual(result.headline.generation_mode, "skipped_content_validation")
        self.assertEqual(result.generation_reason, "content_headline_unavailable")

    def test_tag_fallback_is_not_a_publishable_headline(self):
        for tag in ("好プレー", "おめ", "ホラー", "まずい", "ww"):
            with self.subTest(tag=tag):
                self.assertFalse(ts.is_publishable_headline(ts.build_tag_based_fallback_headline([tag])))

    def test_content_headline_uses_an_action_from_transcript(self):
        transcript = "窓の外がうるさくて集中できない。迷路をまっすぐにクリアしてバナナにたどり着くのに。"
        headline = ts.hss.build_content_headline(transcript=transcript)
        self.assertTrue(headline)
        self.assertIn("迷路", headline)
        self.assertIn("バナナ", headline)
        self.assertNotIn("コメント", headline)
        self.assertTrue(ts.is_publishable_headline(headline, source_text=transcript))

    def test_transcript_pattern_headline_is_not_a_reaction_label(self):
        headline = ts.hss.build_content_headline(
            transcript="実質これ一個しか浮かんでない、滑り止まよけてない",
            video_title="配信タイトル",
        )
        self.assertEqual(headline, "一個だけ浮かんでいることに気づく")
        self.assertNotIn("盛り上がる", headline)


if __name__ == "__main__":
    unittest.main()
