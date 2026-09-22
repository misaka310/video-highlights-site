from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import headline_generation as hlg
import headline_pipeline as hlp
import headline_scoring as hls
import headline_validation as hlv
from transcript_postprocess import (
    TermDictionary,
)
from transcription.config import PipelineSettings

import headline_source_selection as source_selection

_INITIAL_PIPELINE_GLOBALS = PipelineSettings.from_env({}).as_globals()
FORCE_HEADLINE_REFRESH = _INITIAL_PIPELINE_GLOBALS['FORCE_HEADLINE_REFRESH']
FORCE_TRANSCRIPT_REFRESH = _INITIAL_PIPELINE_GLOBALS['FORCE_TRANSCRIPT_REFRESH']
GAME_TERM_DICTIONARY_PATH = _INITIAL_PIPELINE_GLOBALS['GAME_TERM_DICTIONARY_PATH']
GEMINI_API_KEY = _INITIAL_PIPELINE_GLOBALS['GEMINI_API_KEY']
GEMINI_API_URL = _INITIAL_PIPELINE_GLOBALS['GEMINI_API_URL']
GEMINI_MODEL = _INITIAL_PIPELINE_GLOBALS['GEMINI_MODEL']
GEMINI_TIMEOUT_SEC = _INITIAL_PIPELINE_GLOBALS['GEMINI_TIMEOUT_SEC']
GROQ_API_KEY = _INITIAL_PIPELINE_GLOBALS['GROQ_API_KEY']
GROQ_MODEL = _INITIAL_PIPELINE_GLOBALS['GROQ_MODEL']
GROQ_RESPONSES_URL = _INITIAL_PIPELINE_GLOBALS['GROQ_RESPONSES_URL']
GROQ_TIMEOUT_SEC = _INITIAL_PIPELINE_GLOBALS['GROQ_TIMEOUT_SEC']
HEADLINE_MAX_ATTEMPTS = _INITIAL_PIPELINE_GLOBALS['HEADLINE_MAX_ATTEMPTS']
HEADLINE_MAX_CHARS = _INITIAL_PIPELINE_GLOBALS['HEADLINE_MAX_CHARS']
HEADLINE_RETRY_ERRORS = _INITIAL_PIPELINE_GLOBALS['HEADLINE_RETRY_ERRORS']
HEADLINE_STREAMER_ID = _INITIAL_PIPELINE_GLOBALS['HEADLINE_STREAMER_ID']
NVIDIA_API_KEY = _INITIAL_PIPELINE_GLOBALS['NVIDIA_API_KEY']
NVIDIA_API_URL = _INITIAL_PIPELINE_GLOBALS['NVIDIA_API_URL']
NVIDIA_MODEL = _INITIAL_PIPELINE_GLOBALS['NVIDIA_MODEL']
NVIDIA_TIMEOUT_SEC = _INITIAL_PIPELINE_GLOBALS['NVIDIA_TIMEOUT_SEC']
PRINT_SOURCE_SELECTION_DEFAULT = _INITIAL_PIPELINE_GLOBALS['PRINT_SOURCE_SELECTION_DEFAULT']
SEGMENT_SCREENSHOT_GENERATION_ENABLED = _INITIAL_PIPELINE_GLOBALS['SEGMENT_SCREENSHOT_GENERATION_ENABLED']
SOURCE_SENTENCE_LIMIT_DEFAULT = _INITIAL_PIPELINE_GLOBALS['SOURCE_SENTENCE_LIMIT_DEFAULT']
TERM_DICTIONARY_PATH = _INITIAL_PIPELINE_GLOBALS['TERM_DICTIONARY_PATH']
TERM_NORMALIZATION_ENABLED = _INITIAL_PIPELINE_GLOBALS['TERM_NORMALIZATION_ENABLED']
TERM_NORMALIZATION_MIN_TERM_LEN = _INITIAL_PIPELINE_GLOBALS['TERM_NORMALIZATION_MIN_TERM_LEN']
TERM_NORMALIZATION_MIN_TOKEN_LEN = _INITIAL_PIPELINE_GLOBALS['TERM_NORMALIZATION_MIN_TOKEN_LEN']
TERM_NORMALIZATION_SIMILARITY = _INITIAL_PIPELINE_GLOBALS['TERM_NORMALIZATION_SIMILARITY']
TRANSCRIPT_BEAM_SIZE = _INITIAL_PIPELINE_GLOBALS['TRANSCRIPT_BEAM_SIZE']
TRANSCRIPT_COMPUTE_TYPE = _INITIAL_PIPELINE_GLOBALS['TRANSCRIPT_COMPUTE_TYPE']
TRANSCRIPT_CONDITION_ON_PREVIOUS_TEXT = _INITIAL_PIPELINE_GLOBALS['TRANSCRIPT_CONDITION_ON_PREVIOUS_TEXT']
TRANSCRIPT_DEVICE = _INITIAL_PIPELINE_GLOBALS['TRANSCRIPT_DEVICE']
TRANSCRIPT_DOWNLOAD_TIMEOUT_SEC = _INITIAL_PIPELINE_GLOBALS['TRANSCRIPT_DOWNLOAD_TIMEOUT_SEC']
TRANSCRIPT_DRY_RUN = _INITIAL_PIPELINE_GLOBALS['TRANSCRIPT_DRY_RUN']
TRANSCRIPT_LOW_INFO_TOKEN_THRESHOLD = _INITIAL_PIPELINE_GLOBALS['TRANSCRIPT_LOW_INFO_TOKEN_THRESHOLD']
TRANSCRIPT_MAX_DURATION_SEC = _INITIAL_PIPELINE_GLOBALS['TRANSCRIPT_MAX_DURATION_SEC']
TRANSCRIPT_MAX_SEGMENTS = _INITIAL_PIPELINE_GLOBALS['TRANSCRIPT_MAX_SEGMENTS']
TRANSCRIPT_MODEL = _INITIAL_PIPELINE_GLOBALS['TRANSCRIPT_MODEL']
TRANSCRIPT_PADDING_SEC = _INITIAL_PIPELINE_GLOBALS['TRANSCRIPT_PADDING_SEC']
TRANSCRIPT_PREPROCESS_DENOISE_STRENGTH = _INITIAL_PIPELINE_GLOBALS['TRANSCRIPT_PREPROCESS_DENOISE_STRENGTH']
TRANSCRIPT_PREPROCESS_PROFILE = _INITIAL_PIPELINE_GLOBALS['TRANSCRIPT_PREPROCESS_PROFILE']
TRANSCRIPT_RECENT_ANALYZED_WINDOW_HOURS = _INITIAL_PIPELINE_GLOBALS['TRANSCRIPT_RECENT_ANALYZED_WINDOW_HOURS']
TRANSCRIPT_RETRY_ERRORS = _INITIAL_PIPELINE_GLOBALS['TRANSCRIPT_RETRY_ERRORS']
TRANSCRIPT_SECOND_PASS_ENABLED = _INITIAL_PIPELINE_GLOBALS['TRANSCRIPT_SECOND_PASS_ENABLED']
TRANSCRIPT_SECOND_PASS_EXTRA_PADDING_SEC = _INITIAL_PIPELINE_GLOBALS['TRANSCRIPT_SECOND_PASS_EXTRA_PADDING_SEC']
TRANSCRIPT_SECOND_PASS_MODEL = _INITIAL_PIPELINE_GLOBALS['TRANSCRIPT_SECOND_PASS_MODEL']
TRANSCRIPT_SECOND_PASS_PREPROCESS_PROFILE = _INITIAL_PIPELINE_GLOBALS['TRANSCRIPT_SECOND_PASS_PREPROCESS_PROFILE']
TRANSCRIPT_SECOND_PASS_SELECTION_MODE = _INITIAL_PIPELINE_GLOBALS['TRANSCRIPT_SECOND_PASS_SELECTION_MODE']
TRANSCRIPT_SECOND_PASS_TOP_N = _INITIAL_PIPELINE_GLOBALS['TRANSCRIPT_SECOND_PASS_TOP_N']
TRANSCRIPT_SECOND_PASS_WORD_TIMESTAMPS = _INITIAL_PIPELINE_GLOBALS['TRANSCRIPT_SECOND_PASS_WORD_TIMESTAMPS']
TRANSCRIPT_SUSPICIOUS_RATIO_THRESHOLD = _INITIAL_PIPELINE_GLOBALS['TRANSCRIPT_SUSPICIOUS_RATIO_THRESHOLD']
TRANSCRIPT_TARGET_SCOPE = _INITIAL_PIPELINE_GLOBALS['TRANSCRIPT_TARGET_SCOPE']
TRANSCRIPT_VAD_FILTER = _INITIAL_PIPELINE_GLOBALS['TRANSCRIPT_VAD_FILTER']
TRANSCRIPT_VAD_MIN_SILENCE_DURATION_MS = _INITIAL_PIPELINE_GLOBALS['TRANSCRIPT_VAD_MIN_SILENCE_DURATION_MS']
USE_GAME_TERM_DICTIONARY_DEFAULT = _INITIAL_PIPELINE_GLOBALS['USE_GAME_TERM_DICTIONARY_DEFAULT']

ACTIVE_TERM_DICTIONARY = source_selection.ACTIVE_TERM_DICTIONARY
BASE_TERM_DICTIONARY = source_selection.BASE_TERM_DICTIONARY
EXACT_ALIAS_PARTICLE_SUFFIXES = source_selection.EXACT_ALIAS_PARTICLE_SUFFIXES
FILLER_PREFIX_RE = source_selection.FILLER_PREFIX_RE
GAME_TERM_DICTIONARY = source_selection.GAME_TERM_DICTIONARY
HEADLINE_FUNCTION_WORD_RE = source_selection.HEADLINE_FUNCTION_WORD_RE
HEADLINE_META_RE = source_selection.HEADLINE_META_RE
HEADLINE_SENSITIVE_RE = source_selection.HEADLINE_SENSITIVE_RE
JAPANESE_CHAR_RE = source_selection.JAPANESE_CHAR_RE
PREPROCESS_CONTEXT = source_selection.PREPROCESS_CONTEXT
SOURCE_ACTION_HINT_RE = source_selection.SOURCE_ACTION_HINT_RE
SOURCE_CALL_ONLY_RE = source_selection.SOURCE_CALL_ONLY_RE
SOURCE_CLAUSE_MAX_CHARS = source_selection.SOURCE_CLAUSE_MAX_CHARS
SOURCE_CONTENT_WORD_RE = source_selection.SOURCE_CONTENT_WORD_RE
SOURCE_DEFAULT_CONFIG = source_selection.SOURCE_DEFAULT_CONFIG
SOURCE_GREETING_ONLY_RE = source_selection.SOURCE_GREETING_ONLY_RE
SOURCE_INCOMPLETE_END_RE = source_selection.SOURCE_INCOMPLETE_END_RE
SOURCE_INTERJECTION_INLINE_RE = source_selection.SOURCE_INTERJECTION_INLINE_RE
SOURCE_INTERJECTION_RE = source_selection.SOURCE_INTERJECTION_RE
SOURCE_INTERJECTION_TOKEN_RE = source_selection.SOURCE_INTERJECTION_TOKEN_RE
SOURCE_LOW_SIGNAL_CLAUSE_RE = source_selection.SOURCE_LOW_SIGNAL_CLAUSE_RE
SOURCE_NOISE_EDGE_RE = source_selection.SOURCE_NOISE_EDGE_RE
SOURCE_ONLY_GREET_RE = source_selection.SOURCE_ONLY_GREET_RE
SOURCE_REACTION_ONLY_RE = source_selection.SOURCE_REACTION_ONLY_RE
SOURCE_REPEAT_WORD_RE = source_selection.SOURCE_REPEAT_WORD_RE
SOURCE_SELECTION_CHATTER_RE = source_selection.SOURCE_SELECTION_CHATTER_RE
SOURCE_SELECTION_COLLOQUIAL_TAIL_RE = source_selection.SOURCE_SELECTION_COLLOQUIAL_TAIL_RE
SOURCE_SELECTION_SUSPICIOUS_RE = source_selection.SOURCE_SELECTION_SUSPICIOUS_RE
SOURCE_SENTENCE_END_RE = source_selection.SOURCE_SENTENCE_END_RE
SOURCE_SENTENCE_SPLIT_RE = source_selection.SOURCE_SENTENCE_SPLIT_RE
SOURCE_STOPWORD_TOKENS = source_selection.SOURCE_STOPWORD_TOKENS
SOURCE_SUBJECT_HINT_RE = source_selection.SOURCE_SUBJECT_HINT_RE
SOURCE_TOKEN_SPLIT_RE = source_selection.SOURCE_TOKEN_SPLIT_RE
SOURCE_TRAILING_CHATTER_RE = source_selection.SOURCE_TRAILING_CHATTER_RE
SourceSelectionContext = source_selection.SourceSelectionContext
SourceSelectionResult = source_selection.SourceSelectionResult
SourceSentenceCandidate = source_selection.SourceSentenceCandidate
SourceValidationResult = source_selection.SourceValidationResult
TranscriptResult = source_selection.TranscriptResult
_build_source_selection_result = source_selection._build_source_selection_result
_candidate_midpoint_abs_sec = source_selection._candidate_midpoint_abs_sec
_collect_game_term_match_info = source_selection._collect_game_term_match_info
_collect_optional_alias_hits = source_selection._collect_optional_alias_hits
_collect_source_sentence_candidates = source_selection._collect_source_sentence_candidates
_contains_dictionary_term = source_selection._contains_dictionary_term
_contains_exact_alias_token = source_selection._contains_exact_alias_token
_content_token_count = source_selection._content_token_count
_count_action_hints = source_selection._count_action_hints
_count_content_words = source_selection._count_content_words
_count_subject_hints = source_selection._count_subject_hints
_interjection_ratio = source_selection._interjection_ratio
_is_content_token = source_selection._is_content_token
_is_greeting_or_reaction_clause = source_selection._is_greeting_or_reaction_clause
_iter_source_tokens = source_selection._iter_source_tokens
_log_source_selection = source_selection._log_source_selection
_merge_source_config = source_selection._merge_source_config
_score_activity_peak = source_selection._score_activity_peak
_score_center_proximity = source_selection._score_center_proximity
_score_source_sentence_candidate = source_selection._score_source_sentence_candidate
_segment_sentence_candidates = source_selection._segment_sentence_candidates
_select_source_sentences = source_selection._select_source_sentences
_split_source_sentences_for_headline = source_selection._split_source_sentences_for_headline
_strip_reaction_prefix = source_selection._strip_reaction_prefix
_to_optional_float = source_selection._to_optional_float
_unknown_token_ratio = source_selection._unknown_token_ratio
build_headline_source_config = source_selection.build_headline_source_config
build_headline_source_text = source_selection.build_headline_source_text
clean_source_sentence = source_selection.clean_source_sentence
cleanup_source_clause = source_selection.cleanup_source_clause
collapse_japanese_spacing = source_selection.collapse_japanese_spacing
collect_game_term_hits = source_selection.collect_game_term_hits
collect_source_term_counts = source_selection.collect_source_term_counts
collect_source_terms_for_headline = source_selection.collect_source_terms_for_headline
extract_candidate_clauses = source_selection.extract_candidate_clauses
is_low_signal_clause = source_selection.is_low_signal_clause
is_valid_headline_source_text = source_selection.is_valid_headline_source_text
load_term_dictionary = source_selection.load_term_dictionary
merge_term_dictionaries = source_selection.merge_term_dictionaries
normalize_headline_source_text = source_selection.normalize_headline_source_text
normalize_source_clause = source_selection.normalize_source_clause
normalize_source_text = source_selection.normalize_source_text
normalize_transcript_terms = source_selection.normalize_transcript_terms
resolve_active_term_dictionary = source_selection.resolve_active_term_dictionary
sanitize_headline = source_selection.sanitize_headline
smart_truncate = source_selection.smart_truncate
split_source_clauses = source_selection.split_source_clauses
split_source_text = source_selection.split_source_text
text_similarity = source_selection.text_similarity
trim_unsupported_trailing_token = source_selection.trim_unsupported_trailing_token


def _sync_source_exports() -> None:
    for name in source_selection.EXPORTED_NAMES:
        globals()[name] = getattr(source_selection, name)


def apply_pipeline_settings(settings: PipelineSettings) -> None:
    globals().update(settings.as_globals())
    source_selection.apply_pipeline_settings(settings)
    source_selection.refresh_runtime_configuration()
    _sync_source_exports()


def refresh_runtime_configuration() -> None:
    source_selection.refresh_runtime_configuration()
    _sync_source_exports()


def set_active_term_dictionary(use_game_term_dictionary: bool) -> TermDictionary:
    result = source_selection.set_active_term_dictionary(use_game_term_dictionary)
    _sync_source_exports()
    return result


apply_pipeline_settings(PipelineSettings.from_env({}))

HeadlineProviderError = hlg.HeadlineProviderError

LOCAL_HEADLINE_MODEL = "extractive-ja-v1"

DEFAULT_HEADLINE_TEXT = "\u898b\u3069\u3053\u308d\u30af\u30ea\u30c3\u30d7"

WEAK_HEADLINE_RE = re.compile(
    r"^(?:\u5927\u4e08\u592b|\u3084\u3070\u3044|\u307e\u3058|\u306a\u3093\u304b|\u3042\u306e|\u305d\u306e|\u3042\u308c|\u3082\u3046|\u307b\u3093\u3068)(?:[\s\!\?\u3001\u3002\uff01\uff1f]+)?$"
)

HEADLINE_KEYWORD_RE = re.compile(
    r"(?:\u3084\u3070|\u307e\u3058|\u795e|\u7b11|\u7206\u7b11|\u885d\u6483|\u30db\u30e9\u30fc|\u6016|\u3059\u3054|\u5f37|\u4e0a\u624b|\u3069\u3046\u3057\u3066|\u306a\u3093\u3067)"
)

HEADLINE_LOW_SIGNAL_RE = re.compile(
    r"^(?:\u3053\u3053|\u305d\u3053|\u3053\u308c|\u305d\u308c|\u3042\u308c|\u306a\u3093\u304b|\u307f\u3093\u306a|\u3061\u3087\u3063\u3068)"
)

HEADLINE_BROKEN_PHRASE_RE = re.compile(
    r"(?:\u306e\u3059\u3054\u3055$|\u306e\u3059\u3054\u3044\u306a$|\u30bf\u30a4\u30e1\u30f3\u30c8|\u751f\u6d3b\u611f$|\u6c17\u6301\u3061\u304c\u751f\u307e\u308c\u307e\u3059$)"
)

HEADLINE_ALLOWED_CHARS_RE = hlv.HEADLINE_ALLOWED_CHARS_RE

SOFT_DROP_HEADLINE_TOKENS = hlv.SOFT_DROP_HEADLINE_TOKENS

SOFT_HEADLINE_ISSUES = hlv.SOFT_HEADLINE_ISSUES

TITLE_ENDING_FUNCTION_RE = re.compile(
    r"(?:\u3060|\u3067\u3059|\u3059\u308b|\u3057\u305f|\u3067|\u306b|\u3092|\u304c|\u306f|\u306e|\u3068)$"
)

HEADLINE_CONVERSATIONAL_END_RE = re.compile(
    r"(?:\u3093\u3060\u3051\u3069|\u3051\u3069|\u3068\u601d\u3063\u3066\u305f\u3089|\u3063\u307d\u3044|\u304b\u306a|\u304b\u3082|\u3068\u3044\u3046\u304b|\u306a\u3093\u304b|\u3060\u3063\u305f\u3093\u3060\u306a)(?:[\s\u3001\u3002!\uff01?\uff1f\u2026\u301c\uff5e]*)$"
)

HEADLINE_CONVERSATIONAL_PHRASE_RE = re.compile(
    r"(?:\u3093\u3060\u3051\u3069|\u3051\u3069|\u3068\u601d\u3063\u3066\u305f\u3089|\u3063\u307d\u3044|\u304b\u306a|\u304b\u3082|\u3068\u3044\u3046\u304b|\u306a\u3093\u304b|\u3060\u3063\u305f\u3093\u3060\u306a)"
)

HEADLINE_CONVERSATIONAL_FRAGMENT_RE = re.compile(
    r"(?:^|[\s\u3001\u3002])(\u3068\u3044\u3046\u304b|\u306a\u3093\u304b)(?:[\s\u3001\u3002]|$)"
)

HEADLINE_IMPRESSION_FRAGMENT_RE = re.compile(
    r"(?:\u9762\u767d\u304b\u3063\u305f|\u308f\u304b\u3089\u306a\u3044|\u3069\u3046\u3068\u304b|\u306a\u3093\u3060\u308d\u3046)"
)

HEADLINE_FIRST_PERSON_PRONOUN_RE = re.compile(
    r"(?:^|[\s\u3001\u3002])(\u79c1|\u308f\u305f\u3057|\u4ffa|\u50d5|\u3046\u3061)(?:\u306f|\u304c|\u3082|\u3063\u3066)?"
)

HEADLINE_CHANGE_HINT_RE = re.compile(
    r"(?:\u5909\u308f(?:\u308b|\u3063\u305f)|\u5897\u3048(?:\u308b|\u305f)|\u6e1b(?:\u308b|\u3063\u305f)|\u58ca\u308c(?:\u308b|\u305f)|\u843d\u3061(?:\u308b|\u305f)|\u6c7a\u307e(?:\u308b|\u3063\u305f)|\u6210\u9577(?:\u3059\u308b|\u3057\u305f|\u3057\u3066)|"
    r"\u4e0a\u304c(?:\u308b|\u3063\u305f)|\u4e0b\u304c(?:\u308b|\u3063\u305f)|\u5fa9\u6d3b|\u5fa9\u5e30|\u6d88\u3048(?:\u308b|\u305f)|\u51fa\u73fe|\u899a\u9192|\u9006\u8ee2|"
    r"\u9014\u5207\u308c(?:\u308b|\u305f)|\u518d\u958b(?:\u3059\u308b|\u3057\u305f)|\u623b(?:\u308b|\u3063\u305f)|\u6b62(?:\u307e\u308b|\u307e\u3063\u305f)|\u5d29\u308c(?:\u308b|\u305f))"
)

HEADLINE_EVENT_SUMMARY_RE = re.compile(
    r"(?:\u3092|\u304c|\u3067|\u306b).*(?:\u3057\u305f|\u3059\u308b|\u306a\u308b|\u306a\u3063\u305f|\u767a\u751f|\u5224\u660e|\u6210\u529f|\u5931\u6557|\u958b\u59cb|\u7d42\u4e86|\u5fa9\u6d3b|\u6483\u7834|\u7a81\u7834|\u5230\u9054)"
)

@dataclass
class HeadlineResult:
    text: str
    model: str
    source: str
    generation_mode: str = "llm_ranked"
    confidence: str = "medium"
    notes: str = ""
    metadata: dict[str, Any] | None = None

@dataclass(frozen=True)
class HeadlineCandidate:
    headline: str
    used_terms: list[str]
    confidence: float
    reason: str
    can_publish: bool = True
    generation_mode: str = ""
    notes: str = ""

@dataclass(frozen=True)
class HeadlineScore:
    total: float
    breakdown: dict[str, float]
    reasons: list[str]

FINAL_HEADLINE_SOFT_REASONS = {
    "missing_function_word",
    "too_abstract",
    "literal_or_awkward_predicate",
    "missing_topic_hint",
    "weak_predicate_link",
}

compute_source_quality_penalty = hlp.compute_source_quality_penalty

def _collect_used_terms(headline: str, source_text: str) -> list[str]:
    terms = collect_source_terms_for_headline(source_text)
    return [term for term in terms if term in headline][:6]

def _headline_title_structure_bonus(
    headline: str,
    *,
    content_word_count: int,
    subject_hint_count: int,
    action_hint_count: int,
) -> tuple[float, list[str]]:
    bonus = 0.0
    reasons: list[str] = []

    has_change_hint = bool(HEADLINE_CHANGE_HINT_RE.search(headline))
    has_event_summary = bool(HEADLINE_EVENT_SUMMARY_RE.search(headline))

    if subject_hint_count >= 1 and action_hint_count >= 1:
        bonus += 2.4
        reasons.append("title_noun_action")
    elif subject_hint_count >= 1 and has_change_hint:
        bonus += 1.9
        reasons.append("title_noun_change")

    if has_event_summary:
        bonus += 1.2
        reasons.append("event_summary_shape")
    elif content_word_count >= 3 and action_hint_count >= 1:
        bonus += 0.8
        reasons.append("event_summary_hint")

    if content_word_count >= 2 and len(headline) <= HEADLINE_MAX_CHARS and not HEADLINE_CONVERSATIONAL_END_RE.search(headline):
        bonus += 0.5
        reasons.append("title_compact_shape")

    return bonus, reasons

def validate_final_headline_japanese(
    headline: str,
    *,
    source_text: str | None = None,
    config: dict[str, Any] | None = None,
) -> SourceValidationResult:
    del config
    value = cleanup_headline_candidate(headline)
    reasons: list[str] = []
    if not value:
        reasons.append("empty_or_cleanup_failed")

    content_word_count = _count_content_words(value)
    subject_hint_count = _count_subject_hints(value)
    action_hint_count = _count_action_hints(value)
    unknown_ratio = _unknown_token_ratio(value)

    if re.search(r"([\u3040-\u30ff\u4e00-\u9fffA-Za-z0-9])(?:\1){2,}", value):
        reasons.append("unnatural_repetition")
    if re.search(r"(?:\u3059\u308b\u3059\u308b|\u306a\u308b\u306a\u308b|\u7684\u306a\u611f\u3058|\u3053\u3068\u306b\u3064\u3044\u3066)$", value):
        reasons.append("literal_or_awkward_predicate")
    if HEADLINE_LOW_SIGNAL_RE.search(value) and content_word_count < 2:
        reasons.append("too_abstract")
    if not hlv.contains_function_like_tokens(value, function_word_re=HEADLINE_FUNCTION_WORD_RE):
        reasons.append("missing_function_word")
    if re.search(r"(?:\u3051\u3069|\u3051\u308c\u3069|\u3051\u308c\u3069\u3082|\u304b\u3089|\u306e\u3067|\u3063\u3066|\u3068\u304b|and|but|so)$", value, re.IGNORECASE):
        reasons.append("incomplete_tail")
    if HEADLINE_CONVERSATIONAL_PHRASE_RE.search(value):
        reasons.append("conversational_phrase")
    if HEADLINE_CONVERSATIONAL_END_RE.search(value):
        reasons.append("conversational_tail")
    if HEADLINE_CONVERSATIONAL_FRAGMENT_RE.search(value):
        reasons.append("conversation_fragment")
    if HEADLINE_IMPRESSION_FRAGMENT_RE.search(value):
        reasons.append("reflective_impression_fragment")
    if HEADLINE_FIRST_PERSON_PRONOUN_RE.search(value) and (
        HEADLINE_IMPRESSION_FRAGMENT_RE.search(value) or HEADLINE_CONVERSATIONAL_PHRASE_RE.search(value) or content_word_count <= 3
    ):
        reasons.append("first_person_casual_fragment")
    if re.search(r"(?:\u3067|\u306b|\u3092|\u304c|\u306f|\u306e|\u3068)$", value):
        reasons.append("dangling_particle")
    if len(value) > max(24, HEADLINE_MAX_CHARS):
        reasons.append("too_long_for_title")
    if subject_hint_count == 0 and content_word_count < 2:
        reasons.append("missing_topic_hint")
    if not TITLE_ENDING_FUNCTION_RE.search(value) and action_hint_count == 0 and content_word_count >= 3:
        reasons.append("weak_predicate_link")

    normalized_source = normalize_source_text(source_text or "")
    if normalized_source:
        similarity = text_similarity(normalize_source_text(value), normalized_source)
        source_len = max(1, len(normalized_source))
        length_ratio = len(value) / source_len
        if similarity >= 0.92:
            reasons.append("near_source_copy")
        elif similarity >= 0.84 and length_ratio >= 0.78:
            reasons.append("insufficient_compression")

    hard_reasons = [reason for reason in reasons if reason not in FINAL_HEADLINE_SOFT_REASONS]
    return SourceValidationResult(
        accepted=not hard_reasons,
        reasons=reasons,
        content_word_count=content_word_count,
        subject_hint_count=subject_hint_count,
        action_hint_count=action_hint_count,
        unknown_ratio=unknown_ratio,
    )

PUBLISH_BLOCKING_HEADLINE_REASONS = {
    "missing_function_word",
    "too_abstract",
    "literal_or_awkward_predicate",
    "missing_topic_hint",
}

PUBLISH_CONVERSATIONAL_EDGE_RE = re.compile(
    r"^(?:あー|えー|いや|まあ|なんか|はい|なんで)|(?:っていう|ってい|というか|して|まして|ませ)$"
)

PUBLISH_HEADLINE_MIN_CHARS = 8
PUBLISH_HEADLINE_MAX_CHARS = 24

def is_publishable_headline(headline: str, *, source_text: str | None = None) -> bool:
    value = cleanup_headline_candidate(headline)
    if len(value) < PUBLISH_HEADLINE_MIN_CHARS or len(value) > PUBLISH_HEADLINE_MAX_CHARS:
        return False
    validation = validate_final_headline_japanese(value, source_text=source_text)
    if not validation.accepted:
        return False
    if any(reason in PUBLISH_BLOCKING_HEADLINE_REASONS for reason in validation.reasons):
        return False
    if PUBLISH_CONVERSATIONAL_EDGE_RE.search(value):
        return False
    if "?" in value or "？" in value:
        return False
    if value.endswith("に注目が集まる"):
        return False
    return value != DEFAULT_HEADLINE_TEXT

def score_headline_candidate_with_source(
    candidate: HeadlineCandidate,
    source_text: str,
    config: dict[str, Any] | None = None,
) -> HeadlineScore:
    active_config = config or {}
    source_validation = active_config.get("source_validation")
    source_penalty = compute_source_quality_penalty(source_validation) if isinstance(source_validation, SourceValidationResult) else 0.0

    headline = cleanup_headline_candidate(candidate.headline)
    if not headline or headline.upper() == "SKIP":
        return HeadlineScore(total=-100.0, breakdown={"skip": -100.0}, reasons=["skip_candidate"])
    if not candidate.can_publish:
        return HeadlineScore(total=-80.0, breakdown={"blocked": -80.0}, reasons=["candidate_not_publishable"])

    source_terms = collect_source_terms_for_headline(source_text)
    used_terms = [term for term in source_terms if term in headline]
    source_game_terms = collect_game_term_hits(source_text)
    headline_game_terms = collect_game_term_hits(headline)
    content_word_count = _count_content_words(headline)
    base = score_headline_candidate(headline)

    reused_term_score = min(5.0, len(used_terms) * 1.3)
    specific_word_score = min(3.5, content_word_count * 0.7)
    game_term_bonus = min(2.8, len(headline_game_terms) * 1.4)
    missing_game_term_penalty = 1.4 if source_game_terms and not headline_game_terms else 0.0
    headline_validation = validate_final_headline_japanese(headline, source_text=source_text)
    naturalness_penalty = float(len([reason for reason in headline_validation.reasons if reason not in FINAL_HEADLINE_SOFT_REASONS])) * 2.2
    soft_naturalness_penalty = float(len([reason for reason in headline_validation.reasons if reason in FINAL_HEADLINE_SOFT_REASONS])) * 0.4
    abstract_penalty = 2.6 if HEADLINE_LOW_SIGNAL_RE.search(headline) and content_word_count < 2 else 0.0
    conversational_tail_penalty = 4.2 if HEADLINE_CONVERSATIONAL_END_RE.search(headline) else 0.0
    conversational_phrase_penalty = 3.0 if HEADLINE_CONVERSATIONAL_PHRASE_RE.search(headline) else 0.0
    conversational_fragment_penalty = 2.2 if HEADLINE_CONVERSATIONAL_FRAGMENT_RE.search(headline) else 0.0
    impression_fragment_penalty = 2.8 if HEADLINE_IMPRESSION_FRAGMENT_RE.search(headline) else 0.0
    first_person_penalty = 2.5 if HEADLINE_FIRST_PERSON_PRONOUN_RE.search(headline) else 0.0

    title_structure_bonus, title_structure_reasons = _headline_title_structure_bonus(
        headline,
        content_word_count=content_word_count,
        subject_hint_count=headline_validation.subject_hint_count,
        action_hint_count=headline_validation.action_hint_count,
    )

    source_similarity = text_similarity(normalize_source_text(headline), normalize_source_text(source_text))
    copied_source_penalty = 3.4 if source_similarity >= 0.93 else (1.2 if source_similarity >= 0.82 else 0.0)

    hallucination_penalty = 0.0
    for token in collect_source_terms_for_headline(headline):
        if token not in source_text and token not in source_terms and len(token) >= 3:
            hallucination_penalty += 0.8

    if 10 <= len(headline) <= min(20, HEADLINE_MAX_CHARS):
        length_score = 1.8
    elif 8 <= len(headline) <= HEADLINE_MAX_CHARS:
        length_score = 0.5
    elif 6 <= len(headline) <= HEADLINE_MAX_CHARS + 4:
        length_score = -0.8
    elif len(headline) < 6:
        length_score = -1.4
    else:
        length_score = -2.0 - ((len(headline) - HEADLINE_MAX_CHARS) * 0.35)

    confidence_bonus = max(0.0, min(1.0, candidate.confidence)) * 1.1
    source_quality_penalty = source_penalty * 0.35

    total = (
        base
        + reused_term_score
        + specific_word_score
        + length_score
        + title_structure_bonus
        + confidence_bonus
        + game_term_bonus
        - missing_game_term_penalty
        - abstract_penalty
        - naturalness_penalty
        - soft_naturalness_penalty
        - conversational_tail_penalty
        - conversational_phrase_penalty
        - conversational_fragment_penalty
        - impression_fragment_penalty
        - first_person_penalty
        - copied_source_penalty
        - hallucination_penalty
        - source_quality_penalty
    )
    return HeadlineScore(
        total=total,
        breakdown={
            "base": base,
            "reuse_terms": reused_term_score,
            "specific_words": specific_word_score,
            "length": length_score,
            "candidate_confidence": confidence_bonus,
            "copy_penalty": -copied_source_penalty,
            "abstract_penalty": -abstract_penalty,
            "naturalness_penalty": -naturalness_penalty,
            "soft_naturalness_penalty": -soft_naturalness_penalty,
            "title_structure_bonus": title_structure_bonus,
            "game_term_bonus": game_term_bonus,
            "missing_game_term_penalty": -missing_game_term_penalty,
            "conversational_tail_penalty": -conversational_tail_penalty,
            "conversational_phrase_penalty": -conversational_phrase_penalty,
            "conversational_fragment_penalty": -conversational_fragment_penalty,
            "impression_fragment_penalty": -impression_fragment_penalty,
            "first_person_penalty": -first_person_penalty,
            "hallucination_penalty": -hallucination_penalty,
            "source_quality_penalty": -source_quality_penalty,
            "source_similarity": source_similarity,
        },
        reasons=[
            f"used_terms={len(used_terms)}",
            f"content_words={content_word_count}",
            f"source_similarity={source_similarity:.2f}",
            f"candidate_mode={candidate.generation_mode or 'unspecified'}",
            f"headline_game_terms={headline_game_terms or []}",
            f"title_structure={','.join(title_structure_reasons) if title_structure_reasons else 'none'}",
        ],
    )

def choose_best_headline(
    candidates: list[HeadlineCandidate],
    source_text: str,
    config: dict[str, Any] | None = None,
) -> HeadlineCandidate:
    if not candidates:
        return HeadlineCandidate(headline="SKIP", used_terms=[], confidence=0.0, reason="no_candidates", can_publish=False)

    scored_rows: list[tuple[HeadlineCandidate, HeadlineScore]] = []
    for candidate in candidates:
        score = score_headline_candidate_with_source(candidate, source_text, config)
        scored_rows.append((candidate, score))
        print(
            "debug: headline candidate scored "
            f"headline={candidate.headline} score={score.total:.2f} breakdown={score.breakdown} reasons={score.reasons}"
        )

    scored_rows.sort(
        key=lambda row: (is_publishable_headline(row[0].headline, source_text=source_text), row[1].total),
        reverse=True,
    )
    best, best_score = scored_rows[0]
    print(
        "info: headline selected "
        f"headline={best.headline} score={best_score.total:.2f} used_terms={best.used_terms} "
        f"candidate_reason={best.reason} candidate_mode={best.generation_mode or 'unspecified'}"
    )
    return best

def generate_headline_candidates(source_text: str, config: dict[str, Any] | None = None) -> list[HeadlineCandidate]:
    del config
    raw_candidates = collect_headline_candidates(source_text)[:12]
    generated: list[HeadlineCandidate] = []
    seen: set[str] = set()
    flavors = ("summary_lean", "extractive_lean", "safe_lean")

    for idx, text in enumerate(raw_candidates):
        cleaned = cleanup_headline_candidate(text)
        if not cleaned:
            continue
        if cleaned in seen:
            continue
        seen.add(cleaned)
        used_terms = _collect_used_terms(cleaned, source_text)
        generated.append(
            HeadlineCandidate(
                headline=cleaned,
                used_terms=used_terms,
                confidence=0.42 + min(0.5, len(used_terms) * 0.12),
                reason="heuristic_source_window",
                can_publish=True,
                generation_mode=flavors[min(idx, len(flavors) - 1)],
                notes="local_candidate",
            )
        )
        if len(generated) >= 3:
            break
    return generated

def parse_headline_candidates_output(text: str, source_text: str) -> list[HeadlineCandidate]:
    value = str(text or "").strip()
    if not value:
        return generate_headline_candidates(source_text)
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\s*```$", "", value).strip()

    candidate_payloads: list[dict[str, Any]] = []
    for raw in (value, extract_json_like_fragment(value)):
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows = payload.get("candidates")
            if isinstance(rows, list):
                candidate_payloads.extend(row for row in rows if isinstance(row, dict))
            headline = str(payload.get("headline") or "").strip()
            if headline:
                candidate_payloads.append({"headline": headline, "reason": "legacy_single_headline"})

    parsed: list[HeadlineCandidate] = []
    for row in candidate_payloads:
        headline = cleanup_headline_candidate(str(row.get("headline") or ""))
        if not headline:
            continue
        used_terms_raw = row.get("used_terms") or []
        used_terms = [str(term).strip() for term in used_terms_raw if str(term).strip()]
        if not used_terms:
            used_terms = _collect_used_terms(headline, source_text)
        confidence = _to_optional_float(row.get("confidence"))
        if confidence is None:
            confidence = 0.5
        reason = str(row.get("reason") or row.get("notes") or "llm_candidate").strip() or "llm_candidate"
        generation_mode = str(row.get("generation_mode") or "llm_ranked").strip() or "llm_ranked"
        notes = str(row.get("notes") or "").strip()
        can_publish = bool(row.get("can_publish", True))
        parsed.append(
            HeadlineCandidate(
                headline=headline,
                used_terms=used_terms,
                confidence=max(0.0, min(1.0, confidence)),
                reason=reason,
                can_publish=can_publish,
                generation_mode=generation_mode,
                notes=notes,
            )
        )

    if not parsed:
        parsed = generate_headline_candidates(source_text)

    return parsed[:3]

def build_remote_headline_prompt(
    *,
    provider: str,
    video_title: str,
    start_time: str,
    end_time: str,
    transcript: str,
    prepared_transcript: str | None = None,
) -> tuple[str, str]:
    del provider
    prepared_transcript = prepared_transcript or build_headline_source_text(transcript, HEADLINE_SOURCE_CONFIG)
    instructions = (
        "You create concise Japanese headlines for Twitch highlight clips. "
        "Return a JSON object with a field named candidates. "
        "Generate exactly 3 candidates in one response. "
        "Each candidate must contain headline, used_terms, confidence, reason, can_publish. "
        "generation_mode and notes are optional. "
        "Use only facts explicitly present in the source text. "
        "Do not add names, events, or details that are not in the source text. "
        f"Keep each headline natural Japanese and {PUBLISH_HEADLINE_MIN_CHARS} to {PUBLISH_HEADLINE_MAX_CHARS} characters. "
        "Reuse concrete source terms when possible, but do not copy the source sentence verbatim. "
        "When source is weak, still output short readable headlines (safe/extractive allowed). "
        "Never return SKIP if source text is non-empty."
    )
    prompt = (
        f"Stream title: {video_title}\n"
        f"Clip range: {start_time} - {end_time}\n"
        "Rules:\n"
        "- Source faithful: no hallucination.\n"
        "- Prefer concise title-like event summaries over conversational phrasing.\n"
        "- Keep concrete nouns/actions from source.\n"
        "- Provide three quality variants: summary-lean, extractive-lean, safe-lean.\n"
        "- Avoid conversational tails/fragments like 「〜けど」「〜かな」「〜かも」「というか」「なんか」。\n"
        "- Prefer event summaries that read well as a list headline.\n"
        "- Avoid plain transcript copy/paste.\n"
        f"- Each headline must be {PUBLISH_HEADLINE_MIN_CHARS} to {PUBLISH_HEADLINE_MAX_CHARS} characters.\n"
        "- Do not use question marks (? or ？). Rephrase a question as a statement.\n"
        "- Do not include quote brackets such as 「」『』 or any unmatched bracket copied from the source.\n"
        f"Source text (already normalized): {prepared_transcript}\n"
        "Return JSON only."
    )
    return instructions, prompt

def build_headline_response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "candidates": {
                "type": "array",
                "minItems": 1,
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "properties": {
                        "headline": {"type": "string"},
                        "used_terms": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "confidence": {"type": "number"},
                        "reason": {"type": "string"},
                        "can_publish": {"type": "boolean"},
                    },
                    "required": ["headline", "used_terms", "confidence", "reason", "can_publish"],
                    "additionalProperties": False,
                },
            },
            "headline": {
                "type": "string",
                "description": "Backward-compatible single headline field.",
            },
        },
        "required": ["candidates"],
        "additionalProperties": False,
    }

def build_headline_retry_prompt(
    *,
    provider: str,
    video_title: str,
    start_time: str,
    end_time: str,
    transcript: str,
    previous_headline: str,
    issues: list[str],
) -> tuple[str, str]:
    instructions, prompt = build_remote_headline_prompt(
        provider=provider,
        video_title=video_title,
        start_time=start_time,
        end_time=end_time,
        transcript=transcript,
        prepared_transcript=None,
    )
    repair_prompt = (
        f"{prompt}\n"
        f"Previous headline: {previous_headline}\n"
        "That headline was rejected. Write one better alternative.\n"
        "Issues to fix:\n"
        + "\n".join(f"- {issue}" for issue in issues)
        + "\nReturn JSON with candidates only."
    )
    return instructions, repair_prompt

HEADLINE_SOURCE_CONFIG = build_headline_source_config()

def contains_emoji(text: str) -> bool:
    return any(0x1F300 <= ord(char) <= 0x1FAFF for char in text)

def has_excessive_symbols(text: str) -> bool:
    symbol_count = len(re.findall(r"[!???#*~|/\\]+", text))
    return symbol_count >= 3

def headline_reuses_source_terms(headline: str, transcript: str) -> bool:
    terms = collect_source_terms_for_headline(transcript)
    if not terms:
        return True
    return any(term in headline for term in terms[:4])

def validate_headline_result(headline: str, *, transcript: str) -> hlv.ValidationResult:
    source_terms = collect_source_terms_for_headline(transcript)
    return hlv.validate_headline(
        headline,
        source_terms,
        sanitize_headline=sanitize_headline,
        meta_re=HEADLINE_META_RE,
        sensitive_re=HEADLINE_SENSITIVE_RE,
        low_signal_re=HEADLINE_LOW_SIGNAL_RE,
        broken_phrase_re=HEADLINE_BROKEN_PHRASE_RE,
        function_word_re=HEADLINE_FUNCTION_WORD_RE,
        contains_emoji=contains_emoji,
        has_excessive_symbols=has_excessive_symbols,
        allowed_chars_re=HEADLINE_ALLOWED_CHARS_RE,
    )

def compare_tokenizer_function_detection(headlines: list[str]) -> list[dict[str, Any]]:
    active_tokenizer = hlv.resolve_tokenizer()
    fallback_tokenizer = hlv.RegexFallbackTokenizer()
    rows: list[dict[str, Any]] = []
    for headline in headlines:
        rows.append(
            {
                "headline": headline,
                "active_tokenizer": active_tokenizer.name,
                "active_detected": hlv.contains_function_like_tokens(
                    headline,
                    function_word_re=HEADLINE_FUNCTION_WORD_RE,
                    tokenizer=active_tokenizer,
                ),
                "fallback_tokenizer": fallback_tokenizer.name,
                "fallback_detected": hlv.contains_function_like_tokens(
                    headline,
                    function_word_re=HEADLINE_FUNCTION_WORD_RE,
                    tokenizer=fallback_tokenizer,
                ),
            }
        )
    return rows

def explain_headline_issues(headline: str, *, transcript: str) -> list[str]:
    return validate_headline_result(headline, transcript=transcript).issue_messages

def split_headline_issues(issues: list[str]) -> tuple[list[str], list[str]]:
    return hlv.split_headline_issues(issues, soft_issue_set=SOFT_HEADLINE_ISSUES)

def rank_headline_candidate(text: str, *, transcript: str) -> tuple[int, int, float]:
    validation = validate_headline_result(text, transcript=transcript)
    source_terms = collect_source_terms_for_headline(transcript)
    score = hls.score_headline(
        headline=text,
        source_terms=source_terms,
        base_score=score_headline_candidate(text),
        validation_result=validation,
    )
    return (-len(validation.hard_issues), -len(validation.soft_issues), score.total)

def _normalized_provider_name(candidate: HeadlineResult) -> str:
    metadata = dict(candidate.metadata or {})
    return str(metadata.get("provider") or candidate.source or "unknown").strip().lower() or "unknown"

def _to_candidate_confidence(value: Any) -> float:
    confidence = _to_optional_float(value)
    if confidence is None:
        confidence = 0.5
    return max(0.0, min(1.0, confidence))

def _candidate_confidence_from_metadata(metadata: dict[str, Any]) -> float:
    confidence = _to_optional_float(metadata.get("candidate_confidence"))
    if confidence is None:
        confidence = 0.5
    return max(0.0, min(1.0, confidence))

def _build_remote_comparison_pool(candidates: list[HeadlineResult]) -> list[HeadlineResult]:
    provider_pool: dict[str, list[HeadlineResult]] = defaultdict(list)
    provider_seen: dict[str, set[str]] = defaultdict(set)
    provider_order: list[str] = []

    def _append_candidate(
        *,
        provider: str,
        headline: str,
        model: str,
        generation_mode: str,
        notes: str,
        metadata: dict[str, Any],
    ) -> None:
        cleaned = cleanup_headline_candidate(headline)
        if not cleaned:
            return
        if cleaned in provider_seen[provider]:
            return
        if len(provider_pool[provider]) >= 3:
            return
        provider_seen[provider].add(cleaned)
        row_metadata = dict(metadata)
        row_metadata["provider"] = provider
        provider_pool[provider].append(
            HeadlineResult(
                text=cleaned,
                model=model,
                source=provider,
                generation_mode=generation_mode,
                confidence="medium",
                notes=notes,
                metadata=row_metadata,
            )
        )

    for candidate in candidates:
        metadata = dict(candidate.metadata or {})
        provider = _normalized_provider_name(candidate)
        if provider not in provider_order:
            provider_order.append(provider)

        raw_provider_candidates = metadata.get("provider_candidates") or []
        for rank, row in enumerate(raw_provider_candidates, start=1):
            if not isinstance(row, dict):
                continue
            if not bool(row.get("can_publish", True)):
                continue
            _append_candidate(
                provider=provider,
                headline=str(row.get("headline") or "").strip(),
                model=candidate.model,
                generation_mode=str(row.get("generation_mode") or candidate.generation_mode or "llm_ranked").strip() or "llm_ranked",
                notes=str(row.get("reason") or row.get("notes") or "provider_candidate_pool").strip() or "provider_candidate_pool",
                metadata={
                    "attempt": metadata.get("attempt"),
                    "origin": "provider_candidate",
                    "provider_candidate_rank": rank,
                    "candidate_confidence": _to_candidate_confidence(row.get("confidence")),
                    "provider_candidate_reason": str(row.get("reason") or "provider_candidate").strip() or "provider_candidate",
                },
            )

        selected_meta = metadata.get("provider_selected") or {}
        _append_candidate(
            provider=provider,
            headline=candidate.text,
            model=candidate.model,
            generation_mode=str(candidate.generation_mode or selected_meta.get("generation_mode") or "llm_ranked").strip() or "llm_ranked",
            notes=str(candidate.notes or selected_meta.get("reason") or "provider_selected").strip() or "provider_selected",
            metadata={
                "attempt": metadata.get("attempt"),
                "origin": "provider_selected",
                "candidate_confidence": _to_candidate_confidence(selected_meta.get("confidence")),
                "provider_candidate_reason": str(selected_meta.get("reason") or "provider_selected").strip() or "provider_selected",
            },
        )

    pool: list[HeadlineResult] = []
    for provider in provider_order:
        pool.extend(provider_pool.get(provider) or [])

    if pool:
        return pool
    return candidates

def choose_best_remote_headline(candidates: list[HeadlineResult], *, transcript: str) -> tuple[HeadlineResult, dict[str, Any]]:
    pool = _build_remote_comparison_pool(candidates)
    evaluations: list[hls.CandidateEvaluation] = []
    source_terms = collect_source_terms_for_headline(transcript)

    for candidate in pool:
        metadata = dict(candidate.metadata or {})
        candidate_confidence = _candidate_confidence_from_metadata(metadata)
        source_score = score_headline_candidate_with_source(
            HeadlineCandidate(
                headline=candidate.text,
                used_terms=_collect_used_terms(candidate.text, transcript),
                confidence=candidate_confidence,
                reason=str(metadata.get("provider_candidate_reason") or "remote_pool").strip() or "remote_pool",
                can_publish=True,
                generation_mode=str(candidate.generation_mode or "llm_ranked").strip() or "llm_ranked",
                notes=str(candidate.notes or "").strip(),
            ),
            transcript,
        )
        validation = validate_headline_result(candidate.text, transcript=transcript)
        score = hls.score_headline(
            headline=candidate.text,
            source_terms=source_terms,
            base_score=source_score.total,
            validation_result=validation,
        )
        evaluations.append(hls.CandidateEvaluation(text=candidate.text, validation=validation, score=score))

    hlp.summarize_candidate_evaluations(evaluations, logger=print)
    winner = hlp.choose_best_candidate(evaluations, logger=print)

    provider_candidates: dict[str, list[str]] = {}
    provider_pool_counts: dict[str, int] = {}
    pool_candidates: list[dict[str, Any]] = []
    selected: HeadlineResult | None = None
    selected_score = 0.0

    for index, candidate in enumerate(pool):
        metadata = dict(candidate.metadata or {})
        provider_name = _normalized_provider_name(candidate)
        provider_rows = provider_candidates.setdefault(provider_name, [])
        if candidate.text not in provider_rows:
            provider_rows.append(candidate.text)
        provider_pool_counts[provider_name] = provider_pool_counts.get(provider_name, 0) + 1

        evaluation = evaluations[index]
        if candidate.text == winner.text and selected is None:
            selected = candidate
            selected_score = evaluation.score.total

        pool_candidates.append(
            {
                "provider": provider_name,
                "attempt": metadata.get("attempt"),
                "origin": metadata.get("origin") or "unknown",
                "headline": candidate.text,
                "model": candidate.model,
                "score_total": round(evaluation.score.total, 3),
                "hard_issues": list(evaluation.validation.hard_issues),
                "soft_issues": list(evaluation.validation.soft_issues),
            }
        )

    if selected is None:
        selected = pool[0]

    summary = {
        "selected_headline": selected.text,
        "selected_source": selected.source,
        "selected_score": round(selected_score, 3),
        "provider_candidates": provider_candidates,
        "provider_pool_counts": provider_pool_counts,
        "comparison_pool_size": len(pool),
        "pool_candidates": pool_candidates,
    }
    return selected, summary

def build_natural_fallback_headline(*, transcript: str, video_title: str) -> str:
    terms = [term for term in collect_source_terms_for_headline(transcript) if term not in SOFT_DROP_HEADLINE_TOKENS]
    if len(terms) >= 3:
        candidate = finalize_headline(f"{terms[0]}?{terms[1]}???")
        if not explain_headline_issues(candidate, transcript=transcript):
            return candidate
    if len(terms) >= 2:
        candidate = finalize_headline(f"{terms[0]}?{terms[1]}")
        if not explain_headline_issues(candidate, transcript=transcript):
            return candidate
    heuristic = build_rule_based_headline(transcript=transcript)
    if heuristic and not explain_headline_issues(heuristic, transcript=transcript):
        return finalize_headline(heuristic)
    fallback_title = strip_stream_title(video_title)
    if fallback_title and not explain_headline_issues(fallback_title, transcript=transcript):
        return finalize_headline(fallback_title)
    return ""

def find_unusable_headline_reason(text: str, *, video_title: str) -> str | None:
    value = sanitize_headline(text)
    if not value:
        return "empty headline"
    lowered = value.lower()
    if lowered in {"headline", "json", "1", "5"}:
        return "placeholder-like headline"
    if re.fullmatch(r"\d{2}:\d{2}:\d{2}\s*[-~]\s*\d{2}:\d{2}:\d{2}\)?", value):
        return "time range only"
    broken_markers = (
        "json",
        "headline",
        "stream title:",
        "clip range:",
        "transcript notes:",
        "bad examples:",
        "good style:",
        "return only json",
        '{"headline"',
    )
    if any(marker in lowered for marker in broken_markers):
        return "meta explanation leaked into headline"
    if lowered.startswith(("stream title:", "clip range:", "transcript notes:", "bad examples:", "good style:")):
        return "prompt field leaked into headline"
    stripped_title = strip_stream_title(video_title)
    if stripped_title and sanitize_headline(stripped_title) == value:
        return "stream title copied as headline"
    return None

def ensure_usable_remote_headline(*, text: str, video_title: str, provider: str, transcript: str) -> str:
    raw_value = sanitize_headline(text)
    if raw_value and HEADLINE_ALLOWED_CHARS_RE.fullmatch(raw_value) and re.search(r"[\s\u3001,\u30fb]", raw_value):
        raise HeadlineProviderError(
            provider,
            "returned low-quality headline: looks like a noun list instead of a natural phrase",
        )
    finalized = finalize_headline(cleanup_headline_candidate(text) or text)
    reason = find_unusable_headline_reason(finalized, video_title=video_title)
    if reason:
        raise HeadlineProviderError(provider, f"returned unusable headline: {reason}")
    validation = validate_headline_result(finalized, transcript=transcript)
    final_japanese_validation = validate_final_headline_japanese(finalized, source_text=transcript)
    print(
        "debug: headline validation "
        f"provider={provider} headline={finalized} "
        f"hard={validation.hard_issues or 'none'} soft={validation.soft_issues or 'none'} "
        f"flags={validation.info_flags or 'none'} final_reasons={final_japanese_validation.reasons or 'none'}"
    )
    if validation.hard_issues:
        raise HeadlineProviderError(
            provider,
            f"returned low-quality headline: {hlp.format_rejection_summary(validation)}",
        )
    if not final_japanese_validation.accepted:
        raise HeadlineProviderError(
            provider,
            f"returned low-quality headline: final_japanese_filter={','.join(final_japanese_validation.reasons)}",
        )
    return finalized

def normalize_headline_output(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\s*```$", "", value).strip()
    for candidate in (value, extract_json_like_fragment(value)):
        if not candidate:
            continue
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows = payload.get("candidates")
            if isinstance(rows, list) and rows:
                first = rows[0] if isinstance(rows[0], dict) else {}
                first_headline = str(first.get("headline") or "").strip()
                if first_headline:
                    return first_headline
            headline = str(payload.get("headline") or "").strip()
            if headline:
                return headline
    return value

def extract_json_like_fragment(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return ""
    return text[start : end + 1].strip()

def build_fallback_extractive_result(
    *,
    prepared_source_text: str,
    transcript: str,
    video_title: str,
    reason: str,
    source_config: dict[str, Any] | None = None,
) -> HeadlineResult:
    active_source_config = source_config or HEADLINE_SOURCE_CONFIG
    source_text = prepared_source_text or build_headline_source_text(transcript, active_source_config)
    headline = build_extractive_headline(transcript=source_text, video_title=video_title, source_config=active_source_config)
    return HeadlineResult(
        text=headline,
        model=LOCAL_HEADLINE_MODEL,
        source="extractive",
        generation_mode="fallback_extractive",
        confidence="low",
        notes=reason,
    )

def build_tag_based_fallback_headline(tags: Any) -> str:
    """Return no title: tags describe reactions, not the scene itself.

    Kept as a compatibility symbol for older callers, but deliberately
    disabled so reaction tags can never become a viewer-facing headline.
    Content-derived titles must come from transcript/headline enrichment.
    """
    return ""

def build_safe_fallback_headline(*, transcript: str, video_title: str) -> str:
    heuristic = build_pattern_fallback_headline(transcript=transcript, video_title=video_title)
    if heuristic and is_publishable_headline(heuristic):
        return heuristic
    return DEFAULT_HEADLINE_TEXT

def is_safe_extractive_headline_candidate(headline: str, *, source_text: str) -> bool:
    cleaned = cleanup_headline_candidate(headline)
    if not cleaned:
        return False
    if len(cleaned) > HEADLINE_MAX_CHARS:
        return False
    if HEADLINE_CONVERSATIONAL_END_RE.search(cleaned) or HEADLINE_CONVERSATIONAL_PHRASE_RE.search(cleaned):
        return False
    if SOURCE_SELECTION_SUSPICIOUS_RE.search(cleaned):
        return False

    validation = validate_final_headline_japanese(cleaned, source_text=source_text)
    if not validation.accepted:
        return False

    source_similarity = text_similarity(normalize_source_text(cleaned), normalize_source_text(source_text))
    if source_similarity >= 0.78 and len(cleaned) >= 16:
        return False

    if _count_action_hints(cleaned) == 0 and not collect_game_term_hits(cleaned):
        return False

    return True

def build_extractive_headline(
    *,
    transcript: str,
    video_title: str,
    source_config: dict[str, Any] | None = None,
) -> str:
    preferred = build_rule_based_headline(transcript=transcript)
    if preferred and not explain_headline_issues(preferred, transcript=transcript):
        return finalize_headline(preferred)

    active_source_config = source_config or HEADLINE_SOURCE_CONFIG
    source_text = build_headline_source_text(transcript, active_source_config)
    candidates = collect_headline_candidates(source_text)
    if not candidates:
        return build_safe_fallback_headline(transcript=source_text or transcript, video_title=video_title)

    best = ""
    best_score = float("-inf")
    for candidate in candidates:
        cleaned = cleanup_headline_candidate(candidate)
        if not cleaned:
            continue
        if not is_safe_extractive_headline_candidate(cleaned, source_text=source_text or transcript):
            continue
        if explain_headline_issues(cleaned, transcript=source_text or transcript):
            continue
        score = score_headline_candidate(cleaned) + (_count_action_hints(cleaned) * 0.6)
        if collect_game_term_hits(cleaned):
            score += 1.1
        if score > best_score:
            best = cleaned
            best_score = score

    if not best:
        return build_safe_fallback_headline(transcript=source_text or transcript, video_title=video_title)
    return finalize_headline(best)


def _compact_content_headline_candidates(text: str) -> list[str]:
    """Reduce one transcript clause without inventing facts."""

    value = cleanup_headline_candidate(text)
    if not value:
        return []
    chunks = [
        part.strip()
        for part in re.split(r"[?？、,]|(?:だから|なので|だけど|けど|から|で、|そして|それで)", value)
        if part.strip()
    ]
    ranked_chunks = sorted(
        chunks,
        key=lambda part: (
            bool(SOURCE_ACTION_HINT_RE.search(part) or HEADLINE_CHANGE_HINT_RE.search(part)),
            len(part),
        ),
        reverse=True,
    )
    candidates = list(ranked_chunks[:2])
    tokens = [token for token in re.split(r"\s+", value) if token]
    action_indexes = [
        index
        for index, token in enumerate(tokens)
        if SOURCE_ACTION_HINT_RE.search(token) or HEADLINE_CHANGE_HINT_RE.search(token)
    ]
    for index in action_indexes:
        for width in (4, 3, 2):
            start = max(0, index - width + 1)
            candidates.append("".join(tokens[start : index + 1]))
    for match in SOURCE_ACTION_HINT_RE.finditer(value):
        left = max(0, match.start() - 12)
        right = min(len(value), match.end() + 8)
        candidates.append(value[left:right])

    normalized: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        compacted = re.sub(r"^(?:そしたら|それで|そして|だから|なんか|ここで|あの|えっと|え、|あ、)", "", candidate).strip()
        compacted = re.sub(r"(?:のに|けど|かな|よね|っていう|というか|だよね|だな)$", "", compacted).strip()
        compacted = cleanup_headline_candidate(compacted)
        if not compacted or len(compacted) > 24 or compacted in seen:
            continue
        seen.add(compacted)
        normalized.append(compacted)
    return normalized


def build_content_headline(
    *,
    transcript: str,
    video_title: str = "",
    source_config: dict[str, Any] | None = None,
) -> str:
    """Build a short headline from spoken content only.

    Reaction tags and the stream title are intentionally excluded.  Returning
    an empty string is safer than publishing a generic label when the audio
    does not contain enough reliable content.
    """

    active_source_config = source_config or HEADLINE_SOURCE_CONFIG
    source_text = build_headline_source_text(transcript, active_source_config)
    if not source_text:
        source_text = normalize_source_text(transcript)
    if not source_text:
        return ""

    pattern_headline = build_transcript_pattern_headline(transcript)
    if pattern_headline and is_publishable_headline(pattern_headline):
        return pattern_headline

    candidates: list[str] = []
    candidates.extend(collect_headline_candidates(source_text))
    candidates.extend(
        clause
        for clause in split_source_clauses(source_text)
        if clause and clause not in candidates
    )
    ranked: list[tuple[float, str]] = []
    for raw_candidate in candidates:
        for candidate in _compact_content_headline_candidates(raw_candidate):
            if not is_publishable_headline(candidate, source_text=source_text):
                continue
            validation = validate_final_headline_japanese(candidate, source_text=source_text)
            if not validation.accepted:
                continue
            score = score_headline_candidate(candidate)
            score += validation.action_hint_count * 2.0
            score += validation.subject_hint_count * 0.7
            score += len(collect_game_term_hits(candidate)) * 1.4
            score -= max(0, len(candidate) - 20) * 0.25
            ranked.append((score, candidate))
    if not ranked:
        return ""
    ranked.sort(key=lambda row: (row[0], len(row[1])), reverse=True)
    return ranked[0][1]


def build_transcript_pattern_headline(transcript: str) -> str:
    """Use a conservative paraphrase for high-signal spoken events."""

    text = normalize_source_text(transcript)
    patterns = (
        (r"(?:パリ[ィー]|パリー|parry).{0,40}決ま", "パリィが決まる瞬間"),
        (r"(?:上手くな|上達|成長)", "上達を実感するプレー"),
        (r"(?:1|一)個しか浮かんでない.{0,24}滑り止", "一個だけ浮かんでいることに気づく"),
        (r"黄金の木の根元", "黄金の木の根元を確かめる"),
        (r"カリスマに押し上げ", "カリスマに押し上げた理由"),
        (r"おっさん.{0,24}ポロリ", "おっさんの発言がポロリ"),
        (r"フリーレンコス.{0,45}(?:合体|2人)", "フリーレンコスの2人が合体"),
        (r"今のは.{0,60}ごめん", "今のプレーを思わず謝る"),
        (r"パリ.{0,18}取らない", "エルデン勢がパリィを使わない理由"),
        (r"蛇女", "蛇女キャラの見た目に驚く"),
        (r"キノコ.{0,30}(?:止まれ|止まる|立つ)", "キノコの前で立ち止まる"),
        (r"プレイヤースキル.{0,20}ゴリ", "プレイヤースキルでゴリ押しする"),
        (r"報酬配布.{0,40}(?:あたり|当たり|ギャンブル)", "報酬配布で当たりを引く"),
        (r"(?:スイッチ|Switch)2.{0,35}(?:大人向け|ワイルズ)", "Switch2の大人向け新作に驚く"),
        (r"お母さん.{0,30}優し", "お母さんの優しさに気づく"),
        (r"迷路.{0,40}(?:バナナ|たどり着)", "迷路を突破してバナナに到達"),
        (r"バナナ.{0,35}(?:真っ直ぐ|まっすぐ|クリア|たどり着)", "バナナを目指してクリアする"),
        (r"(?:ボス|モーゴット).{0,30}(?:倒|撃破|勝)", "ボスを撃破する展開"),
        (r"(?:武器|ビルド).{0,30}(?:完成|整|育て)", "ビルドが整う瞬間"),
    )
    for pattern, headline in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return headline
    return ""

def build_rule_based_headline(*, transcript: str) -> str:
    text = normalize_source_text(transcript)
    rules = (
        ("\u5149\u308b\u9053\u306e\u898b\u843d\u3068\u3057\u306b\u6c17\u3065\u304f", (r"\u5149\u3063\u3066\u306a\u304b\u3063\u305f|\u898b\u3048\u3066\u305f", r"\u3053\u3053\u306a\u3093\u3060|\u9003\u304c\u3057\u3066|\u8f2a\u90ed")),
        ("\u7d42\u308f\u3089\u306a\u3044\u6df1\u591c\u30c8\u30fc\u30af", (r"\u6c38\u9060", r"\u6642\u9593|\u3084\u308d\u3046")),
        ("\u8db3\u9996\u306e\u30bf\u30c8\u30a5\u30fc\u306b\u61a7\u308c\u305f\u8a71", (r"\u8db3\u9996", r"\u5148\u751f|\u5973\u306e\u5b50", r"\u30bf\u30c8\u30a5\u30fc|\u305f\u3068\u3044\u3046|\u304a\u82b1")),
        ("\u597d\u304d\u304c\u7dda\u3067\u3064\u306a\u304c\u308b\u611f\u899a", (r"\u30d4\u30fc\u30b9", r"\u7dda|\u661f\u5ea7|\u5f62\u306b\u306a\u308b")),
        ("\u3057\u3093\u3069\u3055\u3092\u7b11\u3044\u8a71\u306b\u5909\u3048\u308b", (r"\u3042\u308b\u3042\u308b|\u5927\u5909", r"\u4f11|\u75c5|\u6b7b\u306c\u3089")),
        ("\u53ef\u611b\u3044\u5973\u306e\u5b50\u3092\u63cf\u304f\u96e3\u3057\u3055", (r"\u304b\u308f\u3086\u3046|\u304b\u308f\u3044\u3044|\u5973\u306e\u5b50", r"\u63cf\u304f|\u66f8\u304f", r"\u96e3")),
        ("\u602a\u3057\u3044URL\u306b\u8b66\u6212\u3059\u308b", (r"URL|IP|\u30ab\u30e2\u30d5\u30e9",)),
        ("\u30c8\u30e9\u30d6\u30eb\u4e2d\u306b\u30e2\u30f3\u30af\u6483\u6c88", (r"YouTube|\u3084\u3064\u3079|\u67a0", r"\u30e2\u30f3\u30af|\u3084\u3089\u308c\u305f", r"\u6b7b\u3093\u3060|\u30af\u30e9\u30c3\u30b7\u30e5")),
        ("\u6016\u3044\u90e8\u5c4b\u3092\u307f\u3093\u306a\u3067\u78ba\u8a8d", (r"\u6016\u3044", r"\u307f\u3093\u306a\u3067", r"\u78ba\u8a8d|\u958b\u304b\u306a\u3044|\u5965")),
        ("\u30e9\u30b9\u30dc\u30b9\u6226\u3078\u306e\u624b\u5fdc\u3048", (r"\u30e9\u30b9\u30dc\u30b9", r"\u30ef\u30f3\u30d1\u30f3|\u30a2\u30a4\u30c6\u30e0|\u307e\u3060\u3044\u308b")),
    )
    for headline, patterns in rules:
        if all(re.search(pattern, text, re.IGNORECASE) for pattern in patterns):
            return headline
    return ""

def build_pattern_fallback_headline(*, transcript: str, video_title: str) -> str:
    natural = build_natural_fallback_headline(transcript=transcript, video_title=video_title)
    if natural:
        return natural
    heuristic = build_rule_based_headline(transcript=transcript)
    if heuristic and not explain_headline_issues(heuristic, transcript=transcript):
        return finalize_headline(heuristic)
    fallback_title = strip_stream_title(video_title)
    if fallback_title and not explain_headline_issues(fallback_title, transcript=transcript):
        return finalize_headline(fallback_title)
    return ""

def collect_headline_candidates(text: str) -> list[str]:

    normalized = normalize_source_text(text)
    if not normalized:
        return []

    candidates: list[str] = []
    candidates.extend(part.strip() for part in re.split(r"[\r\n\u3002\uff01\uff1f!?]+", normalized) if part.strip())

    words = [word for word in normalized.split(" ") if word.strip()]
    for window_size in (1, 2, 3, 4, 5):
        if len(words) < window_size:
            continue
        max_start = min(len(words) - window_size, 4)
        for start in range(max_start + 1):
            candidates.append(" ".join(words[start : start + window_size]))

    for start in (0, 8, 16):
        if start < len(normalized):
            candidates.append(normalized[start : start + HEADLINE_MAX_CHARS + 12])

    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = candidate.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(key)
    return deduped

def cleanup_headline_candidate(text: str) -> str:
    cleaned = sanitize_headline(text)
    cleaned = strip_stream_title(cleaned)
    previous = None
    while cleaned and cleaned != previous:
        previous = cleaned
        cleaned = FILLER_PREFIX_RE.sub("", cleaned).strip()
        cleaned = sanitize_headline(cleaned)
    cleaned = collapse_japanese_spacing(cleaned)
    cleaned = re.sub(r"\b(?:w{2,}|www)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = sanitize_headline(cleaned)
    if not cleaned:
        return ""
    if WEAK_HEADLINE_RE.fullmatch(cleaned):
        return ""
    if len(JAPANESE_CHAR_RE.findall(cleaned)) < 2:
        return ""
    return cleaned

def strip_stream_title(text: str) -> str:
    value = sanitize_headline(text)
    if not value:
        return ""
    value = re.sub(r"^[\[\(\{\u3010].*?[\]\)\}\u3011]\s*", "", value)
    value = re.sub(r"\s*[|/].*$", "", value)
    return value.strip()

def score_headline_candidate(text: str) -> float:
    length = len(text)
    if length == 0:
        return float("-inf")

    score = 0.0
    if 10 <= length <= HEADLINE_MAX_CHARS:
        score += 8.0
    elif 6 <= length < 10:
        score += 5.0
    elif length > HEADLINE_MAX_CHARS:
        score += max(0.0, 6.0 - (length - HEADLINE_MAX_CHARS) * 0.35)
    else:
        score += length * 0.35

    score += len(re.findall(r"[\u4e00-\u9fff]", text)) * 0.35
    score += len(re.findall(r"[\u3040-\u30ff]", text)) * 0.12
    score -= text.count(" ") * 0.75

    phrase_count = len([part for part in text.split(" ") if part.strip()])
    if phrase_count > 2:
        score -= (phrase_count - 2) * 1.8

    if HEADLINE_KEYWORD_RE.search(text):
        score += 2.5
    if re.search(r"\d", text):
        score += 0.6
    if re.search(r"[\u300c\u300d\u300e\u300f]", text):
        score += 0.5
    if HEADLINE_META_RE.search(text):
        score -= 4.0
    if HEADLINE_SENSITIVE_RE.search(text):
        score -= 10.0
    return score

def finalize_headline(text: str) -> str:
    headline = collapse_japanese_spacing(text)
    headline = sanitize_headline(headline)
    if len(headline) > HEADLINE_MAX_CHARS:
        headline = smart_truncate(headline, HEADLINE_MAX_CHARS)
    headline = sanitize_headline(headline)
    return headline or DEFAULT_HEADLINE_TEXT

def is_acceptable_headline(text: str) -> bool:
    validation = validate_headline_result(text, transcript=text)
    return validation.accepted

def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")

def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

OWN_EXPORTED_NAMES = (
    'DEFAULT_HEADLINE_TEXT',
    'FINAL_HEADLINE_SOFT_REASONS',
    'HEADLINE_ALLOWED_CHARS_RE',
    'HEADLINE_BROKEN_PHRASE_RE',
    'HEADLINE_CHANGE_HINT_RE',
    'HEADLINE_CONVERSATIONAL_END_RE',
    'HEADLINE_CONVERSATIONAL_FRAGMENT_RE',
    'HEADLINE_CONVERSATIONAL_PHRASE_RE',
    'HEADLINE_EVENT_SUMMARY_RE',
    'HEADLINE_FIRST_PERSON_PRONOUN_RE',
    'HEADLINE_IMPRESSION_FRAGMENT_RE',
    'HEADLINE_KEYWORD_RE',
    'HEADLINE_LOW_SIGNAL_RE',
    'HEADLINE_SOURCE_CONFIG',
    'HeadlineCandidate',
    'HeadlineProviderError',
    'HeadlineResult',
    'HeadlineScore',
    'LOCAL_HEADLINE_MODEL',
    'PUBLISH_BLOCKING_HEADLINE_REASONS',
    'PUBLISH_CONVERSATIONAL_EDGE_RE',
    'SOFT_DROP_HEADLINE_TOKENS',
    'SOFT_HEADLINE_ISSUES',
    'TITLE_ENDING_FUNCTION_RE',
    'WEAK_HEADLINE_RE',
    '_build_remote_comparison_pool',
    '_candidate_confidence_from_metadata',
    '_collect_used_terms',
    '_headline_title_structure_bonus',
    '_normalized_provider_name',
    '_to_candidate_confidence',
    '_to_int',
    'build_extractive_headline',
    'build_content_headline',
    'build_transcript_pattern_headline',
    'build_fallback_extractive_result',
    'build_headline_response_schema',
    'build_headline_retry_prompt',
    'build_natural_fallback_headline',
    'build_pattern_fallback_headline',
    'build_remote_headline_prompt',
    'build_rule_based_headline',
    'build_safe_fallback_headline',
    'build_tag_based_fallback_headline',
    'choose_best_headline',
    'choose_best_remote_headline',
    'cleanup_headline_candidate',
    'collect_headline_candidates',
    'compare_tokenizer_function_detection',
    'compute_source_quality_penalty',
    'contains_emoji',
    'ensure_usable_remote_headline',
    'explain_headline_issues',
    'extract_json_like_fragment',
    'finalize_headline',
    'find_unusable_headline_reason',
    'generate_headline_candidates',
    'has_excessive_symbols',
    'headline_reuses_source_terms',
    'is_acceptable_headline',
    'is_publishable_headline',
    'is_safe_extractive_headline_candidate',
    'normalize_headline_output',
    'now_iso',
    'parse_headline_candidates_output',
    'rank_headline_candidate',
    'score_headline_candidate',
    'score_headline_candidate_with_source',
    'split_headline_issues',
    'strip_stream_title',
    'validate_final_headline_japanese',
    'validate_headline_result',
)
EXPORTED_NAMES = tuple(dict.fromkeys((*source_selection.EXPORTED_NAMES, *OWN_EXPORTED_NAMES)))
