from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import headline_pipeline as hlp
import headline_preprocess as hpp
import headline_validation as hlv
import transcript_postprocess as tpp
from transcript_postprocess import (
    NormalizedTranscriptResult,
    TermDictionary,
    TermNormalizationConfig,
)
from transcription.config import PipelineSettings

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

def apply_pipeline_settings(settings: PipelineSettings) -> None:
    globals().update(settings.as_globals())


apply_pipeline_settings(PipelineSettings.from_env({}))

SourceValidationResult = hlp.SourceValidationResult

JAPANESE_CHAR_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")

FILLER_PREFIX_RE = re.compile(
    r"^(?:\u3048+\u30fc*|\u3042\u306e|\u307e\u3042|\u306a\u3093\u304b|\u3066\u3044\u3046\u304b|\u305d\u306e|\u3044\u3084|\u3082\u3046|\u3046\u30fc\u3093|\u307b\u3093\u3068|\u3061\u3087\u3063\u3068|\u305f\u3076\u3093|\u308f\u304b\u3093\u306a\u3044)(?:[\s,\.\!\?\u3001\u3002\uff01\uff1f]+|$)",
    re.IGNORECASE,
)

HEADLINE_META_RE = re.compile(
    r"(?:\u914d\u4fe1|\u8996\u8074\u8005|\u30c1\u30e3\u30c3\u30c8\u6b04|\u30b3\u30e1\u30f3\u30c8|\u30b5\u30d6\u30b9\u30af|\u30d5\u30a9\u30ed\u30fc|URL|IP|YouTube|\u3064\u3079|\u4e8b\u696d\u90e8|\u5e74\u91d1)"
)

HEADLINE_SENSITIVE_RE = re.compile(
    r"(?:\u9b31\u75c5|\u3046\u3064\u75c5|[\u3040-\u30ff\u4e00-\u9fffA-Za-z]*\u75c5|\u4f11\u8077|\u7247\u89aa|\u81ea\u4e3b\u5bfe\u8c61|\u6b53\u8fce\u914d\u4fe1|\u6b7b\u306b\u305d\u3046|\u6b7b\u306c\u307e\u3067)"
)

HEADLINE_FUNCTION_WORD_RE = re.compile(r"(?:\u3067|\u306b|\u3092|\u304c|\u306f|\u306e|\u3068|\u3082|\u3078|\u3084|\u304b|\u306a|\u306d)")

PREPROCESS_CONTEXT = hlp.merge_preprocess_context(
    headline_max_chars=HEADLINE_MAX_CHARS,
    streamer_id=HEADLINE_STREAMER_ID,
)

SOURCE_SENTENCE_SPLIT_RE = PREPROCESS_CONTEXT.patterns.sentence_split_re

SOURCE_INTERJECTION_RE = PREPROCESS_CONTEXT.patterns.interjection_re

SOURCE_TRAILING_CHATTER_RE = PREPROCESS_CONTEXT.patterns.trailing_chatter_re

SOURCE_LOW_SIGNAL_CLAUSE_RE = PREPROCESS_CONTEXT.patterns.low_signal_re

SOURCE_CLAUSE_MAX_CHARS = PREPROCESS_CONTEXT.source_clause_max_chars

SOURCE_ONLY_GREET_RE = re.compile(
    r"^(?:hello|hi|hey|thanks|ok|okay|yeah|hmm|wow|lol|lmao|gg|www+|grass+|nice)[\s,.!?\"']*$",
    re.IGNORECASE,
)

SOURCE_INTERJECTION_TOKEN_RE = re.compile(
    r"(?:uh+|um+|hmm+|like|you know|well|yeah|ok|wow|lol|www+|grass+)",
    re.IGNORECASE,
)

SOURCE_GREETING_ONLY_RE = re.compile(
    r"^(?:"
    r"\u3053\u3093\u306b\u3061\u306f|\u3053\u3093\u3070\u3093\u306f|\u304a\u306f\u3088\u3046|\u3069\u3046\u3082|"
    r"\u3042\u308a\u304c\u3068(?:\u3046)?|\u3088\u308d\u3057\u304f|"
    r"\u304a\u3064\u304b\u308c|\u305f\u3060\u3044\u307e|"
    r"hello|hi|hey|thanks|thank you|ok|okay|yeah|hmm|wow|lol|lmao|gg|www+|nice"
    r")(?:[\s\u3000,.\u3001\u3002!?\uff01\uff1f\u30fc\u301cw]*)$",
    re.IGNORECASE,
)

SOURCE_REACTION_ONLY_RE = re.compile(
    r"^(?:"
    r"\u3084\u3070\u3044|\u307e\u3058|\u3048\u3050\u3044|\u3059\u3054\u3044|"
    r"\u3046\u308f|\u3048\u3063|\u3042\u3063|\u7b11+|w+|www+|"
    r"wow|omg|lol|gg|nice|hmm|uh|um"
    r")(?:[\s\u3000,.\u3001\u3002!?\uff01\uff1f\u30fc\u301cw]*)$",
    re.IGNORECASE,
)

SOURCE_CALL_ONLY_RE = re.compile(
    r"^(?:"
    r"\u307f\u3093\u306a|\u8ab0\u304b|\u3060\u308c\u304b|\u304a\u3044|"
    r"\u3061\u3087\u3063\u3068|\u805e\u3044\u3066|\u898b\u3066|\u6765\u3066|"
    r"chat|guys|everyone"
    r")(?:[\s\u3000,.\u3001\u3002!?\uff01\uff1f\u30fc\u301cw]*)$",
    re.IGNORECASE,
)

SOURCE_CONTENT_WORD_RE = re.compile(r"[A-Za-z]{3,}|[\u30a1-\u30ff]{3,}|[\u4e00-\u9fff]{2,}")

SOURCE_SUBJECT_HINT_RE = re.compile(r"(?:[\u4e00-\u9fff]{2,}|[\u30a1-\u30ff]{3,}|[A-Za-z][A-Za-z0-9]{2,})")

SOURCE_ACTION_HINT_RE = re.compile(
    r"(?:"
    r"\u4f7f(?:\u3063\u3066\u3082\u3089(?:\u3063\u305f|\u3048\u305f)|\u308f\u308c(?:\u305f|\u308b)|\u3063(?:\u305f|\u3066)|\u3046)|"
    r"\u6620(?:\u3063(?:\u305f|\u3066)|\u308b)|"
    r"\u7d39\u4ecb(?:\u3055\u308c(?:\u305f|\u308b)|\u3057(?:\u305f|\u3066)|\u3059\u308b)|"
    r"\u547c(?:\u3070\u308c(?:\u305f|\u308b)|\u3093(?:\u3060|\u3067)|\u3076)|"
    r"\u898b\u3064\u3051(?:\u305f|\u3066|\u308b)|"
    r"\u6c17\u3065(?:\u3044\u305f|\u3044\u3066|\u304f)|"
    r"\u843d\u3061(?:\u305f|\u3066|\u308b)|"
    r"\u58ca\u308c(?:\u305f|\u3066|\u308b)|"
    r"\u53d6\u308c(?:\u305f|\u3066|\u308b)|"
    r"\u51fa(?:\u305f|\u3066|\u308b)|"
    r"\u5f53\u305f(?:\u3063\u305f|\u3063\u3066|\u308b)|"
    r"\u6c7a\u307e(?:\u3063\u305f|\u3063\u3066|\u308b)|"
    r"\u6d88\u3048(?:\u305f|\u3066|\u308b)|"
    r"\u56de\u5fa9(?:\u3057(?:\u305f|\u3066|\u306a\u3044)|\u3059\u308b)|"
    r"\u3057\u305f|\u3057\u3066|\u3059\u308b|\u3055\u308c\u305f|\u306a\u308b|"
    r"\u306a\u3063\u305f|\u884c(?:\u3063\u305f|\u3063\u3066|\u304f)|\u6765(?:\u305f|\u3066|\u308b)|"
    r"\u5012\u3059|\u52dd(?:\u3063\u305f|\u3063\u3066|\u3064)|\u8ca0\u3051(?:\u305f|\u3066|\u308b)|"
    r"\u53d6\u308b|\u62fe\u3046|\u958b(?:\u304f|\u3044\u305f)|\u30df\u30b9\u3059\u308b|"
    r"clear|cleared|start|started|win|won|lose|lost|killed|drop|dropped"
    r")",
    re.IGNORECASE,
)

SOURCE_TOKEN_SPLIT_RE = re.compile(
    r"[A-Za-z][A-Za-z0-9_+\-]{1,}|[0-9]{2,}|[\u4e00-\u9fff]{1,4}[\u3040-\u309f]{0,3}|[\u30a1-\u30ff]{2,}|[\u3040-\u309f]{2,}"
)

SOURCE_STOPWORD_TOKENS = {
    "\u306e",
    "\u306b",
    "\u306f",
    "\u3092",
    "\u304c",
    "\u3068",
    "\u3067",
    "\u3082",
    "\u3063\u3066",
    "\u305f",
    "\u3066",
    "\u3060",
    "\u306a",
    "\u3067\u3059",
    "\u307e\u3059",
    "\u3057\u305f",
    "\u3057\u3066",
    "\u3059\u308b",
    "\u306a\u308b",
    "\u3042\u308b",
    "\u3044\u308b",
    "\u3053\u3068",
    "\u305d\u308c",
    "\u3053\u308c",
    "\u3042\u308c",
    "\u3053\u306e",
    "\u305d\u306e",
    "\u3042\u306e",
    "\u306a\u3093\u304b",
    "\u3082\u3046",
    "\u3061\u3087\u3063\u3068",
    "\u305d\u308d\u305d\u308d",
    "\u3057\u3070\u3089\u304f",
    "\u5168\u7136",
    "\u3051\u3069",
    "\u3067\u3082",
    "\u304b\u3089",
    "\u306e\u3067",
}

EXACT_ALIAS_PARTICLE_SUFFIXES = {
    "\u306f",
    "\u304c",
    "\u3092",
    "\u306b",
    "\u3078",
    "\u3068",
    "\u3067",
    "\u3084",
    "\u3082",
    "\u304b",
    "\u306e",
    "\u306d",
    "\u3088",
    "\u306a",
    "\u308f",
    "\u304b\u3089",
    "\u307e\u3067",
    "\u3060\u3051",
    "\u3057\u304b",
    "\u3088\u308a",
    "\u306a\u3089",
    "\u3063\u3066",
    "\u3067\u306f",
    "\u306b\u306f",
    "\u3068\u306f",
    "\u3078\u306f",
    "\u3067\u3082",
    "\u3068\u3082",
    "\u3068\u304b",
}

SOURCE_INCOMPLETE_END_RE = re.compile(
    r"(?:\u3051\u3069|\u3051\u3069\u3082|\u3051\u308c\u3069|\u3051\u308c\u3069\u3082|"
    r"\u3068\u304b|\u3063\u3066|\u3066|\u3067|\u3057|\u304b\u3089|\u306e\u3067|\u306a|"
    r"but|so|and|because)$",
    re.IGNORECASE,
)

SOURCE_NOISE_EDGE_RE = re.compile(
    r"^(?:\u3048[\u30fc\u301c]*|\u3042\u306e[\u30fc\u301c]*|\u305d\u306e[\u30fc\u301c]*|"
    r"\u306a\u3093\u304b|\u307e\u3042|\u3046\u30fc\u3093|\u3048\u3063\u3068|"
    r"\u3066\u3044\u3046\u304b|uh+|um+|hmm+|like|you know|well)"
    r"(?:[\s\u3000,\u3001\u3002.!?\uff01\uff1f\u30fc\u301c]+|$)",
    re.IGNORECASE,
)

SOURCE_REPEAT_WORD_RE = re.compile(
    r"\b(?P<w>[A-Za-z0-9]{2,}|[\u3040-\u30ff\u4e00-\u9fff]{1,6})(?:[\s\u3000,\u3001\u3002.!?\uff01\uff1f\u30fc\u301c]*\1){2,}",
    re.IGNORECASE,
)

SOURCE_INTERJECTION_INLINE_RE = re.compile(
    r"(?:\b(?:uh+|um+|hmm+|like|you know|well|yeah|ok|wow)\b|"
    r"(?:\u3048[\u30fc\u301c]*|\u3042\u306e[\u30fc\u301c]*|\u305d\u306e[\u30fc\u301c]*|"
    r"\u306a\u3093\u304b|\u307e\u3042|\u3046\u30fc\u3093|\u3048\u3063\u3068))"
    r"(?:[\s\u3000,\u3001\u3002.!?\uff01\uff1f\u30fc\u301c]*)",
    re.IGNORECASE,
)

SOURCE_SENTENCE_END_RE = re.compile(r"[\u3002.!?\uff01\uff1f]")

def _iter_source_tokens(text: str) -> list[str]:
    normalized = normalize_source_text(text)
    if not normalized:
        return []
    tokenizer = hlv.resolve_tokenizer()
    raw_tokens = hlv.tokenize_text(normalized, tokenizer=tokenizer)
    tokens: list[str] = []
    for raw in raw_tokens:
        cleaned = sanitize_headline(raw)
        if not cleaned:
            continue
        if tokenizer.is_fallback:
            subtokens = SOURCE_TOKEN_SPLIT_RE.findall(cleaned)
            if subtokens:
                tokens.extend(subtokens)
                continue
        tokens.append(cleaned)
    if not tokens:
        tokens = SOURCE_TOKEN_SPLIT_RE.findall(normalized)
    return [sanitize_headline(token) for token in tokens if sanitize_headline(token)]

def _is_content_token(token: str) -> bool:
    value = sanitize_headline(token)
    if not value:
        return False
    lowered = value.lower()
    if lowered in SOURCE_STOPWORD_TOKENS:
        return False
    if HEADLINE_META_RE.search(value) or HEADLINE_SENSITIVE_RE.search(value):
        return False
    if SOURCE_CONTENT_WORD_RE.search(value):
        return True
    return len(value) >= 2 and bool(re.search(r"[\u3040-\u30ff\u4e00-\u9fffA-Za-z0-9]", value))

def _count_subject_hints(text: str) -> int:
    return sum(1 for token in _iter_source_tokens(text) if _is_content_token(token) and SOURCE_SUBJECT_HINT_RE.search(token))

def _count_action_hints(text: str) -> int:
    tokens = _iter_source_tokens(text)
    if not tokens:
        return 0
    count = sum(1 for token in tokens if SOURCE_ACTION_HINT_RE.search(token))
    if count > 0:
        return count
    return len(SOURCE_ACTION_HINT_RE.findall(normalize_source_text(text)))

SOURCE_DEFAULT_CONFIG: dict[str, Any] = {
    "max_source_sentences": 2,
    "max_sentence_chars": max(20, HEADLINE_MAX_CHARS + 20),
    "max_source_chars": max(40, HEADLINE_MAX_CHARS * 3),
    "min_content_words": 2,
    "max_unknown_ratio": 0.55,
}

SOURCE_SELECTION_CHATTER_RE = re.compile(
    r"(?:\u30b3\u30e1\u30f3\u30c8|\u8996\u8074\u8005|\u914d\u4fe1|\u96d1\u8ac7|\u98ef|\u7720\u3044|\u4ed5\u4e8b|\u5b66\u6821|LINE|Twitter|X)",
    re.IGNORECASE,
)

SOURCE_SELECTION_COLLOQUIAL_TAIL_RE = re.compile(
    r"(?:\u3051\u3069|\u3051\u308c\u3069|\u304b\u306a|\u304b\u3082|\u3068\u3044\u3046\u304b|\u306a\u3093\u304b|\u3060\u3063\u3051|\u3060\u3088\u306d|\u307f\u305f\u3044\u306a)$",
    re.IGNORECASE,
)

SOURCE_SELECTION_SUSPICIOUS_RE = re.compile(
    r"(?:[A-Za-z]{1,2}\d{2,}|[\-~_=]{3,}|[\u3041-\u3093\u30a1-\u30ff\u4e00-\u9fff]{1,2}(?:\s+[\u3041-\u3093\u30a1-\u30ff\u4e00-\u9fff]{1,2}){3,})"
)

@dataclass
class TranscriptResult:
    text: str
    language: str
    language_probability: float | None
    segments: list[dict[str, Any]] | None = None
    source_text: str | None = None
    normalized_text: str | None = None

@dataclass(frozen=True)
class SourceSentenceCandidate:
    index: int
    text: str
    normalized: str
    start_sec: float | None
    end_sec: float | None
    has_word_timestamps: bool
    game_term_hits: tuple[str, ...]
    score: float
    breakdown: dict[str, float]
    reasons: tuple[str, ...]

@dataclass(frozen=True)
class SourceSelectionContext:
    item_id: str
    transcript_pass: str
    scene_start_sec: int | None
    scene_end_sec: int | None
    transcript_window_start_sec: int | None
    transcript_window_end_sec: int | None
    activity_map: dict[str, Any] | None
    sentence_limit: int
    use_game_term_dictionary: bool
    print_details: bool

@dataclass(frozen=True)
class SourceSelectionResult:
    candidates: tuple[SourceSentenceCandidate, ...]
    selected: tuple[SourceSentenceCandidate, ...]

def _merge_source_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    merged = dict(SOURCE_DEFAULT_CONFIG)
    if config:
        merged.update(config)
    return merged

def _split_source_sentences_for_headline(text: str) -> list[str]:
    normalized = normalize_source_text(text)
    if not normalized:
        return []

    if SOURCE_SENTENCE_END_RE.search(normalized):
        return [part.strip() for part in re.split(r"[?.!???]+", normalized) if part.strip()]

    chunks: list[str] = []
    current = normalized
    while len(current) > max(12, HEADLINE_MAX_CHARS + 10):
        window = current[: max(12, HEADLINE_MAX_CHARS + 10)]
        split_idx = max(window.rfind("?"), window.rfind(" "), window.rfind("??"), window.rfind("?"))
        if split_idx < 8:
            split_idx = max(12, HEADLINE_MAX_CHARS + 8)
        chunks.append(current[:split_idx].strip(" ??.!???"))
        current = current[split_idx:].strip()
    if current:
        chunks.append(current.strip(" ??.!???"))
    return [chunk for chunk in chunks if chunk]

def clean_source_sentence(sentence: str, config: dict[str, Any] | None = None) -> str:
    del config
    cleaned = normalize_source_text(sentence)
    if not cleaned:
        return ""

    previous = None
    while cleaned and cleaned != previous:
        previous = cleaned
        cleaned = SOURCE_NOISE_EDGE_RE.sub("", cleaned).strip()

    cleaned = SOURCE_INTERJECTION_INLINE_RE.sub("", cleaned)
    cleaned = SOURCE_REPEAT_WORD_RE.sub(r"\g<w>", cleaned)
    cleaned = re.sub(r"([A-Za-z0-9])(?:[\u3001\u3002,?!\s]+\1){1,}", r"\1", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" \u3001\u3002.!?\uff01\uff1f")
    return cleaned

def normalize_headline_source_text(text: str, config: dict[str, Any] | None = None) -> str:
    merged = _merge_source_config(config)
    parts = _split_source_sentences_for_headline(text)
    cleaned_parts: list[str] = []
    for part in parts:
        cleaned = clean_source_sentence(part, merged)
        if not cleaned:
            continue
        if SOURCE_GREETING_ONLY_RE.fullmatch(cleaned) or SOURCE_REACTION_ONLY_RE.fullmatch(cleaned):
            continue
        if SOURCE_INCOMPLETE_END_RE.search(cleaned) and len(cleaned) < 14:
            continue
        if len(cleaned) > int(merged["max_sentence_chars"]):
            cleaned = smart_truncate(cleaned, int(merged["max_sentence_chars"]))
        if cleaned:
            cleaned_parts.append(cleaned)
        if len(cleaned_parts) >= int(merged["max_source_sentences"]):
            break

    normalized = "?".join(cleaned_parts).strip("? ")
    if normalized and not SOURCE_SENTENCE_END_RE.search(normalized):
        normalized = f"{normalized}?"
    normalized = normalize_source_text(normalized)
    if len(normalized) > int(merged["max_source_chars"]):
        normalized = smart_truncate(normalized, int(merged["max_source_chars"]))
    return normalized

def _count_content_words(text: str) -> int:
    return sum(1 for token in _iter_source_tokens(text) if _is_content_token(token))

def _unknown_token_ratio(text: str) -> float:
    tokens = _iter_source_tokens(text)
    if not tokens:
        return 1.0

    unknown = 0
    for token in tokens:
        if _is_content_token(token):
            continue
        if re.fullmatch(r"[\-?~?wW]+", token):
            unknown += 1
            continue
        if len(token) <= 1:
            unknown += 1
            continue
        if token in SOURCE_STOPWORD_TOKENS:
            unknown += 1
    return unknown / len(tokens)

def is_valid_headline_source_text(
    text: str,
    config: dict[str, Any] | None = None,
) -> SourceValidationResult:
    merged = _merge_source_config(config)
    normalized = normalize_source_text(text)
    reasons: list[str] = []

    if not normalized:
        reasons.append("empty_source")
    if SOURCE_GREETING_ONLY_RE.fullmatch(normalized):
        reasons.append("greeting_only")
    if SOURCE_REACTION_ONLY_RE.fullmatch(normalized):
        reasons.append("reaction_only")
    if SOURCE_CALL_ONLY_RE.fullmatch(normalized):
        reasons.append("call_only")

    content_word_count = _count_content_words(normalized)
    if content_word_count < int(merged["min_content_words"]):
        reasons.append("too_few_content_words")

    subject_hint_count = _count_subject_hints(normalized)
    action_hint_count = _count_action_hints(normalized)
    if subject_hint_count == 0:
        reasons.append("missing_subject_hint")
    if action_hint_count == 0:
        reasons.append("missing_action_hint")

    unknown_ratio = _unknown_token_ratio(normalized)
    if unknown_ratio > float(merged["max_unknown_ratio"]):
        reasons.append("too_many_unknown_tokens")

    meaningful_chars = len(re.findall(r"[A-Za-z0-9\u3040-\u30ff\u3400-\u9fff]", normalized))
    symbol_ratio = 1.0 - (meaningful_chars / max(1, len(normalized)))
    if symbol_ratio > 0.45:
        reasons.append("too_many_symbols")

    if SOURCE_REPEAT_WORD_RE.search(normalized):
        reasons.append("repeated_noise_phrase")

    stripped = normalized.rstrip("\u3002.!?\uff01\uff1f").strip()
    if stripped and SOURCE_INCOMPLETE_END_RE.search(stripped):
        reasons.append("incomplete_sentence")

    return SourceValidationResult(
        accepted=not reasons,
        reasons=reasons,
        content_word_count=content_word_count,
        subject_hint_count=subject_hint_count,
        action_hint_count=action_hint_count,
        unknown_ratio=unknown_ratio,
    )

def text_similarity(left: str, right: str) -> float:
    return SequenceMatcher(a=str(left or ""), b=str(right or "")).ratio()

def load_term_dictionary(path: Path | str) -> TermDictionary:
    return tpp.load_term_dictionary(path)

def normalize_transcript_terms(
    text: str,
    term_dict: TermDictionary,
    config: TermNormalizationConfig,
) -> NormalizedTranscriptResult:
    return tpp.normalize_transcript_terms(text, term_dict, config)

def merge_term_dictionaries(*term_dictionaries: TermDictionary) -> TermDictionary:
    return tpp.merge_term_dictionaries(*term_dictionaries)

BASE_TERM_DICTIONARY = load_term_dictionary(Path(TERM_DICTIONARY_PATH))

GAME_TERM_DICTIONARY = load_term_dictionary(Path(GAME_TERM_DICTIONARY_PATH))

def resolve_active_term_dictionary(use_game_term_dictionary: bool) -> TermDictionary:
    return tpp.resolve_active_term_dictionary(
        use_game_term_dictionary=use_game_term_dictionary,
        base_term_dictionary=BASE_TERM_DICTIONARY,
        game_term_dictionary=GAME_TERM_DICTIONARY,
    )

ACTIVE_TERM_DICTIONARY = resolve_active_term_dictionary(USE_GAME_TERM_DICTIONARY_DEFAULT)

def set_active_term_dictionary(use_game_term_dictionary: bool) -> TermDictionary:
    global ACTIVE_TERM_DICTIONARY
    ACTIVE_TERM_DICTIONARY = resolve_active_term_dictionary(use_game_term_dictionary)
    return ACTIVE_TERM_DICTIONARY

def build_headline_source_config(
    *,
    source_sentence_limit: int = SOURCE_SENTENCE_LIMIT_DEFAULT,
    print_source_selection: bool = PRINT_SOURCE_SELECTION_DEFAULT,
    use_game_term_dictionary: bool = USE_GAME_TERM_DICTIONARY_DEFAULT,
) -> dict[str, Any]:
    active_term_dictionary = resolve_active_term_dictionary(use_game_term_dictionary)
    return {
        "bonus_terms": [entry.canonical for entry in active_term_dictionary.entries],
        "max_source_sentences": max(1, min(2, int(source_sentence_limit))),
        "print_source_selection": bool(print_source_selection),
        "use_game_term_dictionary": bool(use_game_term_dictionary),
    }

def refresh_runtime_configuration() -> None:
    global PREPROCESS_CONTEXT
    global SOURCE_SENTENCE_SPLIT_RE
    global SOURCE_INTERJECTION_RE
    global SOURCE_TRAILING_CHATTER_RE
    global SOURCE_LOW_SIGNAL_CLAUSE_RE
    global SOURCE_CLAUSE_MAX_CHARS
    global BASE_TERM_DICTIONARY
    global GAME_TERM_DICTIONARY
    global TERM_NORMALIZATION_CONFIG
    global ACTIVE_TERM_DICTIONARY
    global HEADLINE_SOURCE_CONFIG

    PREPROCESS_CONTEXT = hlp.merge_preprocess_context(
        headline_max_chars=HEADLINE_MAX_CHARS,
        streamer_id=HEADLINE_STREAMER_ID,
    )
    SOURCE_SENTENCE_SPLIT_RE = PREPROCESS_CONTEXT.patterns.sentence_split_re
    SOURCE_INTERJECTION_RE = PREPROCESS_CONTEXT.patterns.interjection_re
    SOURCE_TRAILING_CHATTER_RE = PREPROCESS_CONTEXT.patterns.trailing_chatter_re
    SOURCE_LOW_SIGNAL_CLAUSE_RE = PREPROCESS_CONTEXT.patterns.low_signal_re
    SOURCE_CLAUSE_MAX_CHARS = PREPROCESS_CONTEXT.source_clause_max_chars
    BASE_TERM_DICTIONARY = load_term_dictionary(Path(TERM_DICTIONARY_PATH))
    GAME_TERM_DICTIONARY = load_term_dictionary(Path(GAME_TERM_DICTIONARY_PATH))
    TERM_NORMALIZATION_CONFIG = TermNormalizationConfig(
        similarity_threshold=TERM_NORMALIZATION_SIMILARITY,
        min_token_len=TERM_NORMALIZATION_MIN_TOKEN_LEN,
        min_term_len=TERM_NORMALIZATION_MIN_TERM_LEN,
    )
    ACTIVE_TERM_DICTIONARY = resolve_active_term_dictionary(USE_GAME_TERM_DICTIONARY_DEFAULT)
    HEADLINE_SOURCE_CONFIG = build_headline_source_config(
        source_sentence_limit=SOURCE_SENTENCE_LIMIT_DEFAULT,
        print_source_selection=PRINT_SOURCE_SELECTION_DEFAULT,
        use_game_term_dictionary=USE_GAME_TERM_DICTIONARY_DEFAULT,
    )

def _contains_dictionary_term(text: str, term: str) -> bool:
    target = str(term or "").strip()
    value = str(text or "")
    if not value or not target:
        return False
    if re.search(r"[A-Za-z0-9]", target):
        return bool(re.search(rf"\b{re.escape(target)}\b", value, flags=re.IGNORECASE))
    return target in value

def _contains_exact_alias_token(
    tokens: set[str],
    lowered_tokens: set[str],
    alias: str,
) -> bool:
    target = str(alias or "").strip()
    if not target:
        return False
    if re.search(r"[A-Za-z0-9]", target):
        return target.lower() in lowered_tokens
    if target in tokens:
        return True
    for token in tokens:
        if not token.startswith(target):
            continue
        suffix = token[len(target) :]
        if suffix in EXACT_ALIAS_PARTICLE_SUFFIXES:
            return True
    return False

def _collect_game_term_match_info(
    text: str,
    term_dictionary: TermDictionary | None = None,
) -> tuple[list[str], list[str], list[str]]:
    value = normalize_source_text(text)
    if not value:
        return [], [], []
    source_tokens = {token for token in _iter_source_tokens(value) if token}
    source_tokens_lowered = {token.lower() for token in source_tokens}
    dictionary = term_dictionary or ACTIVE_TERM_DICTIONARY
    hits: list[str] = []
    canonical_hits: list[str] = []
    alias_only_hits: list[str] = []
    seen_hits: set[str] = set()
    seen_canonical: set[str] = set()
    seen_alias_only: set[str] = set()
    for entry in dictionary.entries:
        if entry.category != "game_terms":
            continue
        canonical = sanitize_headline(entry.canonical)
        if not canonical:
            continue
        canonical_in_exact_aliases = any(
            str(alias).strip() == entry.canonical for alias in entry.exact_aliases
        )
        if canonical_in_exact_aliases:
            canonical_hit = _contains_exact_alias_token(
                source_tokens,
                source_tokens_lowered,
                entry.canonical,
            )
        else:
            canonical_hit = _contains_dictionary_term(value, entry.canonical)
        alias_hit = any(_contains_dictionary_term(value, alias) for alias in entry.aliases)
        exact_alias_hit = any(
            _contains_exact_alias_token(source_tokens, source_tokens_lowered, alias)
            for alias in entry.exact_aliases
        )
        if not canonical_hit and not alias_hit and not exact_alias_hit:
            continue
        if canonical not in seen_hits:
            seen_hits.add(canonical)
            hits.append(canonical)
        if canonical_hit:
            if canonical not in seen_canonical:
                seen_canonical.add(canonical)
                canonical_hits.append(canonical)
            continue
        if canonical not in seen_alias_only:
            seen_alias_only.add(canonical)
            alias_only_hits.append(canonical)
    return hits, canonical_hits, alias_only_hits

def _collect_optional_alias_hits(
    text: str,
    term_dictionary: TermDictionary | None = None,
) -> list[str]:
    value = normalize_source_text(text)
    if not value:
        return []
    dictionary = term_dictionary or ACTIVE_TERM_DICTIONARY
    hits: list[str] = []
    seen: set[str] = set()
    for alias, canonical in dictionary.optional_aliases.items():
        alias_text = str(alias).strip()
        canonical_text = str(canonical).strip()
        if not alias_text or alias_text == canonical_text:
            continue
        if not _contains_dictionary_term(value, alias_text):
            continue
        if canonical_text and _contains_dictionary_term(value, canonical_text):
            continue
        if alias_text in seen:
            continue
        seen.add(alias_text)
        hits.append(alias_text)
    return hits

def collect_game_term_hits(text: str, term_dictionary: TermDictionary | None = None) -> list[str]:
    hits, _canonical_hits, _alias_only_hits = _collect_game_term_match_info(
        text,
        term_dictionary=term_dictionary,
    )
    return hits

def collect_source_terms_for_headline(transcript: str) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()

    for game_term in collect_game_term_hits(transcript):
        if game_term in seen:
            continue
        seen.add(game_term)
        terms.append(game_term)
        if len(terms) >= 6:
            return terms

    for token in _iter_source_tokens(transcript):
        cleaned = sanitize_headline(token)
        if not cleaned:
            continue
        if cleaned in seen:
            continue
        if not _is_content_token(cleaned):
            continue
        seen.add(cleaned)
        terms.append(cleaned)
        if len(terms) >= 6:
            break
    return terms

def collect_source_term_counts(text: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    for token in _iter_source_tokens(text):
        cleaned = sanitize_headline(token)
        if not cleaned or len(cleaned) < 2:
            continue
        if not _is_content_token(cleaned):
            continue
        counts[cleaned] += 1
    return counts

def split_source_text(text: str) -> list[str]:
    return hpp.split_source_text(text, sentence_split_re=SOURCE_SENTENCE_SPLIT_RE)

def normalize_source_clause(clause: str) -> str:
    return hpp.normalize_source_clause(
        clause,
        normalize_source_text=normalize_source_text,
        collapse_japanese_spacing=collapse_japanese_spacing,
        smart_truncate=smart_truncate,
        filler_prefix_re=FILLER_PREFIX_RE,
        japanese_char_re=JAPANESE_CHAR_RE,
        max_chars=SOURCE_CLAUSE_MAX_CHARS,
        interjection_re=SOURCE_INTERJECTION_RE,
        trailing_chatter_re=SOURCE_TRAILING_CHATTER_RE,
        low_signal_re=SOURCE_LOW_SIGNAL_CLAUSE_RE,
    )

def is_low_signal_clause(clause: str) -> bool:
    return hpp.is_low_signal_clause(
        clause,
        low_signal_re=SOURCE_LOW_SIGNAL_CLAUSE_RE,
        japanese_char_re=JAPANESE_CHAR_RE,
    )

def extract_candidate_clauses(text: str) -> list[str]:
    return hpp.extract_candidate_clauses(
        text,
        normalize_source_text=normalize_source_text,
        collapse_japanese_spacing=collapse_japanese_spacing,
        smart_truncate=smart_truncate,
        filler_prefix_re=FILLER_PREFIX_RE,
        japanese_char_re=JAPANESE_CHAR_RE,
        context=PREPROCESS_CONTEXT,
        logger=print,
    )

def cleanup_source_clause(text: str) -> str:
    return normalize_source_clause(text)

def split_source_clauses(text: str) -> list[str]:
    return extract_candidate_clauses(text)

def trim_unsupported_trailing_token(clause: str, *, term_counts: Counter[str]) -> str:
    parts = str(clause or '').split()
    if len(parts) < 2:
        return str(clause or '').strip()
    trailing = sanitize_headline(parts[-1])
    if not trailing or len(trailing) > 6:
        return str(clause or '').strip()
    if HEADLINE_FUNCTION_WORD_RE.search(trailing):
        return str(clause or '').strip()
    if term_counts.get(trailing, 0) > 1:
        return str(clause or '').strip()
    trimmed = ' '.join(parts[:-1]).strip()
    if len(trimmed) < 10:
        return str(clause or '').strip()
    return trimmed

def _is_greeting_or_reaction_clause(clause: str) -> bool:
    normalized = normalize_source_text(clause).lower()
    if not normalized:
        return True
    if SOURCE_ONLY_GREET_RE.fullmatch(normalized):
        return True
    tokens = [token for token in re.split(r"[\s??,.!???]+", normalized) if token]
    if not tokens:
        return True
    reaction_tokens = {'lol', 'www', 'wow', 'gg', 'nice', 'ok', 'yeah', 'hmm', 'grass'}
    return all(token in reaction_tokens for token in tokens)

def _interjection_ratio(clause: str) -> float:
    tokens = [token for token in re.split(r"[\s??,.!???]+", normalize_source_text(clause).lower()) if token]
    if not tokens:
        return 1.0
    matched = sum(1 for token in tokens if SOURCE_INTERJECTION_TOKEN_RE.search(token))
    return matched / len(tokens)

def _content_token_count(clause: str) -> int:
    return sum(1 for token in _iter_source_tokens(clause) if _is_content_token(token))

def _strip_reaction_prefix(clause: str) -> str:
    return re.sub(
        r"^(?:\s*(?:lol|wow|gg|nice|www+|grass+|hmm|uh|um)[\s,?.!???]*)+",
        '',
        str(clause or ''),
        flags=re.IGNORECASE,
    ).strip()

def _segment_sentence_candidates(
    segment: dict[str, Any],
    *,
    offset_index: int,
) -> list[dict[str, Any]]:
    raw_text = str(segment.get('text') or '').strip()
    if not raw_text:
        return []

    normalized_segment = normalize_source_text(raw_text)
    if not normalized_segment:
        return []

    parts = split_source_clauses(normalized_segment)
    if not parts:
        parts = [normalized_segment]

    seg_start = _to_optional_float(segment.get('start'))
    seg_end = _to_optional_float(segment.get('end'))
    if seg_start is not None and seg_end is not None and seg_end <= seg_start:
        seg_end = seg_start + 1.0

    has_word_timestamps = bool(segment.get('words'))
    total_parts = max(1, len(parts))
    rows: list[dict[str, Any]] = []
    for idx, part in enumerate(parts):
        cleaned = normalize_source_clause(part)
        cleaned = _strip_reaction_prefix(cleaned)
        if not cleaned:
            continue
        if _is_greeting_or_reaction_clause(cleaned):
            continue
        if seg_start is not None and seg_end is not None:
            span = max(0.2, seg_end - seg_start)
            part_start = seg_start + span * (idx / total_parts)
            part_end = seg_start + span * ((idx + 1) / total_parts)
        else:
            part_start = None
            part_end = None
        rows.append(
            {
                'index': offset_index + idx,
                'text': cleaned,
                'start_sec': part_start,
                'end_sec': part_end,
                'has_word_timestamps': has_word_timestamps,
            }
        )
    return rows

def _collect_source_sentence_candidates(
    transcript_result: TranscriptResult | str,
) -> list[dict[str, Any]]:
    if isinstance(transcript_result, TranscriptResult):
        transcript = transcript_result.normalized_text or transcript_result.text
        segments = transcript_result.segments or []
    else:
        transcript = str(transcript_result or '')
        segments = []

    rows: list[dict[str, Any]] = []
    if segments:
        cursor = 0
        for segment in segments:
            segment_rows = _segment_sentence_candidates(segment, offset_index=cursor)
            rows.extend(segment_rows)
            cursor += max(1, len(segment_rows))

    if not rows:
        clauses = split_source_clauses(transcript)
        if not clauses:
            clauses = [normalize_source_text(transcript)] if normalize_source_text(transcript) else []
        for idx, clause in enumerate(clauses):
            cleaned = normalize_source_clause(clause)
            cleaned = _strip_reaction_prefix(cleaned)
            if not cleaned:
                continue
            if _is_greeting_or_reaction_clause(cleaned):
                continue
            rows.append(
                {
                    'index': idx,
                    'text': cleaned,
                    'start_sec': None,
                    'end_sec': None,
                    'has_word_timestamps': False,
                }
            )

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        key = normalize_source_text(str(row.get('text') or ''))
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(row)

    denominator = max(1, len(deduped) - 1)
    for order, row in enumerate(deduped):
        row['position_ratio'] = 0.5 if len(deduped) == 1 else (order / denominator)
    return deduped

def _candidate_midpoint_abs_sec(candidate: dict[str, Any], context: SourceSelectionContext | None) -> float | None:
    if context is None:
        return None
    start_sec = _to_optional_float(candidate.get('start_sec'))
    end_sec = _to_optional_float(candidate.get('end_sec'))
    if start_sec is not None or end_sec is not None:
        midpoint_local = ((start_sec or end_sec or 0.0) + (end_sec or start_sec or 0.0)) / 2.0
        if context.transcript_window_start_sec is None:
            return midpoint_local
        return float(context.transcript_window_start_sec) + midpoint_local

    window_start = _to_optional_float(context.transcript_window_start_sec)
    window_end = _to_optional_float(context.transcript_window_end_sec)
    if window_start is None or window_end is None or window_end <= window_start:
        return None
    ratio = float(candidate.get('position_ratio') or 0.5)
    ratio = max(0.0, min(1.0, ratio))
    return window_start + ((window_end - window_start) * ratio)

def _score_center_proximity(candidate_midpoint_abs: float | None, context: SourceSelectionContext | None) -> float:
    if context is None or candidate_midpoint_abs is None:
        return 0.0
    scene_start = _to_optional_float(context.scene_start_sec)
    scene_end = _to_optional_float(context.scene_end_sec)
    if scene_start is None or scene_end is None or scene_end <= scene_start:
        return 0.0
    center = (scene_start + scene_end) / 2.0
    half = max(1.0, (scene_end - scene_start) / 2.0)
    distance_ratio = min(1.0, abs(candidate_midpoint_abs - center) / half)
    return (1.0 - distance_ratio) * 3.2

def _score_activity_peak(candidate_midpoint_abs: float | None, context: SourceSelectionContext | None) -> float:
    if context is None or candidate_midpoint_abs is None:
        return 0.0
    activity_map = context.activity_map or {}
    bucket_sec = int(activity_map.get('bucket_sec') or 0)
    buckets = activity_map.get('buckets') or []
    if bucket_sec <= 0 or not isinstance(buckets, list) or not buckets:
        return 0.0

    scene_start = int(_to_optional_float(context.scene_start_sec) or 0)
    scene_end = int(_to_optional_float(context.scene_end_sec) or 0)
    if scene_end <= scene_start:
        scene_start = int(context.transcript_window_start_sec or 0)
        scene_end = int(context.transcript_window_end_sec or scene_start)
    if scene_end <= scene_start:
        return 0.0

    start_idx = max(0, int(scene_start // bucket_sec))
    end_idx = min(len(buckets) - 1, int(scene_end // bucket_sec))
    if end_idx < start_idx:
        return 0.0

    local_buckets = buckets[start_idx : end_idx + 1]
    if not local_buckets:
        return 0.0

    local_peak = max(local_buckets)
    if local_peak <= 0:
        return 0.0

    candidate_idx = int(candidate_midpoint_abs // bucket_sec)
    candidate_idx = max(0, min(len(buckets) - 1, candidate_idx))
    candidate_count = float(buckets[candidate_idx])

    peak_offset = local_buckets.index(local_peak)
    peak_idx = start_idx + peak_offset
    peak_sec = (peak_idx + 0.5) * bucket_sec
    half_scene = max(1.0, (scene_end - scene_start) / 2.0)
    proximity = max(0.0, 1.0 - (abs(candidate_midpoint_abs - peak_sec) / half_scene))
    intensity = max(0.0, min(1.0, candidate_count / float(local_peak)))
    return (proximity * 2.0) + (intensity * 1.6)

def _score_source_sentence_candidate(
    raw_candidate: dict[str, Any],
    *,
    context: SourceSelectionContext | None,
    all_term_counts: Counter[str],
) -> SourceSentenceCandidate:
    text = str(raw_candidate.get('text') or '').strip()
    normalized = normalize_source_text(text)
    game_term_hits_list, canonical_term_hits, alias_only_term_hits = _collect_game_term_match_info(normalized)
    game_term_hits = tuple(game_term_hits_list)
    optional_alias_hits = _collect_optional_alias_hits(normalized)
    midpoint_abs = _candidate_midpoint_abs_sec(raw_candidate, context)
    center_score = _score_center_proximity(midpoint_abs, context)
    activity_score = _score_activity_peak(midpoint_abs, context)
    game_term_score = min(4.8, len(game_term_hits) * 2.1)
    action_hints = _count_action_hints(normalized)
    action_score = min(2.8, action_hints * 1.2)
    content_words = _content_token_count(normalized)
    token_count = len(_iter_source_tokens(normalized))
    meaning_score = 1.4 if content_words >= 2 else -1.2
    if content_words >= 4:
        meaning_score += 0.8
    has_word_timestamps = bool(raw_candidate.get('has_word_timestamps'))
    word_timestamp_bonus = 0.9 if has_word_timestamps else 0.0
    term_reuse_score = min(2.2, sum(min(2, all_term_counts.get(term, 0)) for term in game_term_hits) * 0.6)
    noise_penalty = _interjection_ratio(normalized) * 2.8
    incomplete_penalty = 2.4 if SOURCE_INCOMPLETE_END_RE.search(normalized.rstrip('?.!???').strip()) else 0.0
    chatter_penalty = 2.0 if SOURCE_SELECTION_CHATTER_RE.search(normalized) and not game_term_hits and action_hints == 0 else 0.0
    no_term_penalty = 1.2 if not game_term_hits else 0.0
    colloquial_penalty = 1.8 if SOURCE_SELECTION_COLLOQUIAL_TAIL_RE.search(normalized.rstrip('?.!???').strip()) else 0.0
    unknown_ratio = _unknown_token_ratio(normalized)
    optional_alias_penalty = min(3.8, len(optional_alias_hits) * 1.9)
    alias_only_penalty = min(3.6, len(alias_only_term_hits) * 1.4)
    if game_term_hits and not canonical_term_hits and alias_only_term_hits:
        alias_only_penalty += 1.1
    long_noise_penalty = 0.0
    if token_count >= 11:
        long_noise_penalty += min(2.8, (token_count - 10) * 0.32)
    if token_count >= 8 and unknown_ratio > 0.3:
        long_noise_penalty += min(1.6, (unknown_ratio - 0.3) * 4.0)
    compact_bonus = 0.0
    if 3 <= content_words <= 8 and 4 <= token_count <= 10 and unknown_ratio <= 0.28:
        compact_bonus += 0.8
        if action_hints > 0:
            compact_bonus += 0.3
        if game_term_hits:
            compact_bonus += 0.2
    compact_bonus = min(1.4, compact_bonus)
    suspicious_penalty = 0.0
    if unknown_ratio > 0.55:
        suspicious_penalty += min(2.8, (unknown_ratio - 0.55) * 6.0)
    if SOURCE_SELECTION_SUSPICIOUS_RE.search(normalized):
        suspicious_penalty += 1.2
    reaction_penalty = 2.0 if _is_greeting_or_reaction_clause(normalized) else 0.0
    low_signal_penalty = 1.4 if is_low_signal_clause(normalized) else 0.0
    score = (
        center_score
        + activity_score
        + game_term_score
        + action_score
        + meaning_score
        + word_timestamp_bonus
        + term_reuse_score
        + compact_bonus
        - noise_penalty
        - incomplete_penalty
        - chatter_penalty
        - no_term_penalty
        - colloquial_penalty
        - optional_alias_penalty
        - alias_only_penalty
        - long_noise_penalty
        - suspicious_penalty
        - reaction_penalty
        - low_signal_penalty
    )
    breakdown = {
        'center_proximity': round(center_score, 3),
        'activity_peak': round(activity_score, 3),
        'game_term_bonus': round(game_term_score, 3),
        'action_bonus': round(action_score, 3),
        'meaning_bonus': round(meaning_score, 3),
        'word_timestamp_bonus': round(word_timestamp_bonus, 3),
        'term_reuse_bonus': round(term_reuse_score, 3),
        'compact_bonus': round(compact_bonus, 3),
        'noise_penalty': -round(noise_penalty, 3),
        'incomplete_penalty': -round(incomplete_penalty, 3),
        'chatter_penalty': -round(chatter_penalty, 3),
        'no_term_penalty': -round(no_term_penalty, 3),
        'colloquial_penalty': -round(colloquial_penalty, 3),
        'optional_alias_penalty': -round(optional_alias_penalty, 3),
        'alias_only_penalty': -round(alias_only_penalty, 3),
        'long_noise_penalty': -round(long_noise_penalty, 3),
        'suspicious_penalty': -round(suspicious_penalty, 3),
        'reaction_penalty': -round(reaction_penalty, 3),
        'low_signal_penalty': -round(low_signal_penalty, 3),
        'token_count': float(token_count),
        'unknown_ratio': round(unknown_ratio, 3),
    }
    reasons = (
        f'game_term_hits={list(game_term_hits) or []}',
        f'canonical_term_hits={canonical_term_hits or []}',
        f'alias_only_term_hits={alias_only_term_hits or []}',
        f'optional_alias_hits={optional_alias_hits or []}',
        f'action_hints={action_hints}',
        f'content_words={content_words}',
        f'token_count={token_count}',
        f'has_word_timestamps={has_word_timestamps}',
    )
    return SourceSentenceCandidate(
        index=int(raw_candidate.get('index') or 0),
        text=text,
        normalized=normalized,
        start_sec=_to_optional_float(raw_candidate.get('start_sec')),
        end_sec=_to_optional_float(raw_candidate.get('end_sec')),
        has_word_timestamps=has_word_timestamps,
        game_term_hits=game_term_hits,
        score=score,
        breakdown=breakdown,
        reasons=reasons,
    )

def _select_source_sentences(
    scored_candidates: list[SourceSentenceCandidate],
    *,
    sentence_limit: int,
) -> tuple[SourceSentenceCandidate, ...]:
    if not scored_candidates:
        return tuple()

    ranked = sorted(scored_candidates, key=lambda row: row.score, reverse=True)
    primary = ranked[0]
    selected: list[SourceSentenceCandidate] = [primary]

    if sentence_limit <= 1 or len(ranked) == 1:
        return tuple(selected)

    def _connection_score(candidate: SourceSentenceCandidate) -> float:
        index_gap = abs(candidate.index - primary.index)
        gap_score = 1.3 - (index_gap * 0.4)
        if index_gap > 3:
            gap_score -= 1.0
        similarity = text_similarity(candidate.normalized, primary.normalized)
        sequence_bonus = 0.35 if candidate.index > primary.index else 0.2
        return (candidate.score * 0.35) + gap_score + (similarity * 1.4) + sequence_bonus

    runner = max((row for row in ranked[1:]), key=_connection_score, default=None)
    if runner is not None:
        connection_score = _connection_score(runner)
        if connection_score >= 1.1 and runner.score >= primary.score - 4.8:
            selected.append(runner)

    selected = sorted(selected, key=lambda row: row.index)
    return tuple(selected[:sentence_limit])

def _log_source_selection(
    *,
    context: SourceSelectionContext,
    selection: SourceSelectionResult,
    source_text: str,
) -> None:
    print('source-selection ----------------------------------------')
    print(f'item_id: {context.item_id or "unknown"}')
    print(f'transcript_pass: {context.transcript_pass or "unknown"}')
    print('candidate_sentences:')
    if not selection.candidates:
        print('none')
    else:
        for candidate in sorted(selection.candidates, key=lambda row: row.score, reverse=True):
            print(
                'candidate '
                f'index={candidate.index} score={candidate.score:.3f} '
                f'game_term_hit={list(candidate.game_term_hits) or []} '
                f'word_timestamps={candidate.has_word_timestamps} '
                f'breakdown={candidate.breakdown} '
                f'text={candidate.normalized}'
            )
    selected_texts = [candidate.normalized for candidate in selection.selected]
    print(f'selected_sentences: {selected_texts or "none"}')
    print(f'headline_source_text: {source_text or "none"}')
    print('---------------------------------------------------------')

def _build_source_selection_result(
    transcript_result: TranscriptResult | str,
    *,
    context: SourceSelectionContext | None,
    sentence_limit: int,
) -> SourceSelectionResult:
    raw_candidates = _collect_source_sentence_candidates(transcript_result)
    if not raw_candidates:
        return SourceSelectionResult(candidates=tuple(), selected=tuple())

    term_counts = collect_source_term_counts(' '.join(str(row.get('text') or '') for row in raw_candidates))
    scored_candidates = [
        _score_source_sentence_candidate(row, context=context, all_term_counts=term_counts)
        for row in raw_candidates
    ]
    selected = _select_source_sentences(scored_candidates, sentence_limit=sentence_limit)
    return SourceSelectionResult(candidates=tuple(scored_candidates), selected=selected)

def build_headline_source_text(
    transcript_result: TranscriptResult | str,
    config: dict[str, Any] | None = None,
    *,
    selection_context: SourceSelectionContext | None = None,
    selection_result_out: dict[str, Any] | None = None,
) -> str:
    active_config = _merge_source_config(config)
    sentence_limit = max(1, min(2, int(active_config.get('max_source_sentences') or 2)))
    if selection_context is not None:
        sentence_limit = max(1, min(2, int(selection_context.sentence_limit or sentence_limit)))

    if isinstance(transcript_result, TranscriptResult):
        transcript = transcript_result.normalized_text or transcript_result.text
    else:
        transcript = str(transcript_result or '')

    selection = _build_source_selection_result(
        transcript_result,
        context=selection_context,
        sentence_limit=sentence_limit,
    )

    selected_sentences = [row.normalized for row in selection.selected if row.normalized]
    if selected_sentences:
        raw_source_text = '?'.join(selected_sentences)
    else:
        raw_source_text = normalize_source_text(transcript)

    normalized_source_text = normalize_headline_source_text(raw_source_text, active_config)
    if not normalized_source_text:
        normalized_source_text = normalize_headline_source_text(transcript, active_config)

    if selection_result_out is not None:
        selection_result_out['selection'] = selection
        selection_result_out['selected_sentences'] = selected_sentences

    print_selection = bool(active_config.get('print_source_selection', False))
    if selection_context is not None and (selection_context.print_details or print_selection):
        _log_source_selection(context=selection_context, selection=selection, source_text=normalized_source_text)

    print(f'debug: headline source normalized before={raw_source_text} after={normalized_source_text}')

    validation = is_valid_headline_source_text(normalized_source_text, active_config)
    print(
        'debug: headline source validation '
        f'accepted={validation.accepted} reasons={validation.reasons or "none"} '
        f'content_words={validation.content_word_count} subjects={validation.subject_hint_count} '
        f'actions={validation.action_hint_count} unknown_ratio={validation.unknown_ratio:.2f}'
    )
    return normalized_source_text

def normalize_source_text(text: str) -> str:
    normalized = " ".join(str(text or "").replace("\u3000", " ").split())
    return normalized.strip()

def collapse_japanese_spacing(text: str) -> str:
    compact = re.sub(r"\s+", " ", str(text or "").strip())
    compact = re.sub(r"(?<=[\u3040-\u30ff\u3400-\u9fff])\s+(?=[\u3040-\u30ff\u3400-\u9fff])", "", compact)
    compact = re.sub(r"\s+(?=[\u3001\u3002\uff01\uff1f])", "", compact)
    compact = re.sub(r"(?<=[\u3001\u3002\uff01\uff1f])\s+", "", compact)
    return compact.strip()

def smart_truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text

    best = text[:limit]
    for separator in (" ", "\u3001", "\u30fb", "/"):
        index = text.rfind(separator, 0, limit + 1)
        if index >= max(6, limit // 2):
            best = text[:index]
            break
    return best.rstrip(" ,.!?\u3001\u3002\u30fb\uff01\uff1f")

def sanitize_headline(value: str) -> str:
    text = " ".join(str(value or "").split())
    text = text.strip().strip("\"'`")
    text = text.strip("[](){}<>")
    text = text.strip("\u300c\u300d\u300e\u300f\u3010\u3011\u201c\u201d\u2018\u2019")
    for prefix in ("Subheading:", "Headline:", "Title:"):
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()
    text = re.sub(r"^[\-:;,.!?/\u3001\u3002\uff01\uff1f\s]+", "", text)
    text = re.sub(r"[\-:;,.!?/\u3001\u3002\uff01\uff1f\s]+$", "", text)
    if len(text) > HEADLINE_MAX_CHARS:
        text = text[:HEADLINE_MAX_CHARS].rstrip(" ,.!?\u3001\u3002\u30fb\uff01\uff1f")
    return text.strip()

def _to_optional_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

EXPORTED_NAMES = (
    'ACTIVE_TERM_DICTIONARY',
    'BASE_TERM_DICTIONARY',
    'EXACT_ALIAS_PARTICLE_SUFFIXES',
    'FILLER_PREFIX_RE',
    'GAME_TERM_DICTIONARY',
    'HEADLINE_FUNCTION_WORD_RE',
    'HEADLINE_META_RE',
    'HEADLINE_SENSITIVE_RE',
    'JAPANESE_CHAR_RE',
    'PREPROCESS_CONTEXT',
    'SOURCE_ACTION_HINT_RE',
    'SOURCE_CALL_ONLY_RE',
    'SOURCE_CLAUSE_MAX_CHARS',
    'SOURCE_CONTENT_WORD_RE',
    'SOURCE_DEFAULT_CONFIG',
    'SOURCE_GREETING_ONLY_RE',
    'SOURCE_INCOMPLETE_END_RE',
    'SOURCE_INTERJECTION_INLINE_RE',
    'SOURCE_INTERJECTION_RE',
    'SOURCE_INTERJECTION_TOKEN_RE',
    'SOURCE_LOW_SIGNAL_CLAUSE_RE',
    'SOURCE_NOISE_EDGE_RE',
    'SOURCE_ONLY_GREET_RE',
    'SOURCE_REACTION_ONLY_RE',
    'SOURCE_REPEAT_WORD_RE',
    'SOURCE_SELECTION_CHATTER_RE',
    'SOURCE_SELECTION_COLLOQUIAL_TAIL_RE',
    'SOURCE_SELECTION_SUSPICIOUS_RE',
    'SOURCE_SENTENCE_END_RE',
    'SOURCE_SENTENCE_SPLIT_RE',
    'SOURCE_STOPWORD_TOKENS',
    'SOURCE_SUBJECT_HINT_RE',
    'SOURCE_TOKEN_SPLIT_RE',
    'SOURCE_TRAILING_CHATTER_RE',
    'SourceSelectionContext',
    'SourceSelectionResult',
    'SourceSentenceCandidate',
    'SourceValidationResult',
    'TranscriptResult',
    '_build_source_selection_result',
    '_candidate_midpoint_abs_sec',
    '_collect_game_term_match_info',
    '_collect_optional_alias_hits',
    '_collect_source_sentence_candidates',
    '_contains_dictionary_term',
    '_contains_exact_alias_token',
    '_content_token_count',
    '_count_action_hints',
    '_count_content_words',
    '_count_subject_hints',
    '_interjection_ratio',
    '_is_content_token',
    '_is_greeting_or_reaction_clause',
    '_iter_source_tokens',
    '_log_source_selection',
    '_merge_source_config',
    '_score_activity_peak',
    '_score_center_proximity',
    '_score_source_sentence_candidate',
    '_segment_sentence_candidates',
    '_select_source_sentences',
    '_split_source_sentences_for_headline',
    '_strip_reaction_prefix',
    '_to_optional_float',
    '_unknown_token_ratio',
    'build_headline_source_config',
    'build_headline_source_text',
    'clean_source_sentence',
    'cleanup_source_clause',
    'collapse_japanese_spacing',
    'collect_game_term_hits',
    'collect_source_term_counts',
    'collect_source_terms_for_headline',
    'extract_candidate_clauses',
    'is_low_signal_clause',
    'is_valid_headline_source_text',
    'load_term_dictionary',
    'merge_term_dictionaries',
    'normalize_headline_source_text',
    'normalize_source_clause',
    'normalize_source_text',
    'normalize_transcript_terms',
    'refresh_runtime_configuration',
    'resolve_active_term_dictionary',
    'sanitize_headline',
    'set_active_term_dictionary',
    'smart_truncate',
    'split_source_clauses',
    'split_source_text',
    'text_similarity',
    'trim_unsupported_trailing_token',
)
