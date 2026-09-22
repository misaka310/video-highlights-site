from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import headline_candidate_selection as hcs
import headline_generation as hg
import headline_validation as hlv


def _accepted(text: str, *, transcript: str) -> hlv.ValidationResult:
    del transcript
    return hlv.ValidationResult(
        headline=text,
        issues=[],
        info_items=[],
        tokenized=[],
        tokenizer_name="test",
        tokenizer_is_fallback=True,
    )


class PublishableRetryTests(unittest.TestCase):
    def build_generator(self, is_publishable) -> hg.ResilientHeadlineGenerator:
        callbacks = SimpleNamespace(
            validate_headline_result=_accepted,
            is_publishable_headline=is_publishable,
            choose_best_remote_headline=lambda pool, *, transcript: (pool[0], {"pool": [c.text for c in pool]}),
        )
        return hg.ResilientHeadlineGenerator(
            gemini=None,
            groq=None,
            nvidia=None,
            fallback=mock.Mock(),
            settings=SimpleNamespace(headline_max_attempts=2),
            callbacks=callbacks,
        )

    def test_unpublishable_attempt_is_retried_and_excluded(self) -> None:
        bad = SimpleNamespace(text="どういうこと？」が連呼", metadata={}, source="groq")
        good = SimpleNamespace(text="助けるか見守るかの選択", metadata={}, source="groq")
        provider = mock.Mock()
        provider.generate.side_effect = [bad, good]
        generator = self.build_generator(lambda text, *, source_text: text == good.text)
        generator.groq = provider

        selected = generator.generate(video_title="t", start_time="0", end_time="1", transcript="x")

        self.assertEqual(provider.generate.call_count, 2)
        self.assertIs(selected, good)
        self.assertEqual(selected.metadata["comparison"]["pool"], [good.text])

    def test_publishable_first_attempt_does_not_retry(self) -> None:
        good = SimpleNamespace(text="助けるか見守るかの選択", metadata={}, source="groq")
        provider = mock.Mock()
        provider.generate.side_effect = [good]
        generator = self.build_generator(lambda text, *, source_text: True)
        generator.groq = provider

        generator.generate(video_title="t", start_time="0", end_time="1", transcript="x")

        self.assertEqual(provider.generate.call_count, 1)


class ChooseBestHeadlineTests(unittest.TestCase):
    def test_publishable_candidate_beats_higher_scored_unpublishable(self) -> None:
        source = "どういうこと？そうだよね。近いから助けるか見てるけど大丈夫かな"
        candidates = [
            hcs.HeadlineCandidate(headline="どういうこと？」が連呼", used_terms=[], confidence=1.0, reason="r", can_publish=True),
            hcs.HeadlineCandidate(headline="近づく危険、助けるか見守るかの選択", used_terms=[], confidence=0.5, reason="r", can_publish=True),
        ]
        self.assertFalse(hcs.is_publishable_headline(candidates[0].headline, source_text=source))
        self.assertTrue(hcs.is_publishable_headline(candidates[1].headline, source_text=source))

        best = hcs.choose_best_headline(candidates, source)

        self.assertEqual(best.headline, candidates[1].headline)


if __name__ == "__main__":
    unittest.main()
