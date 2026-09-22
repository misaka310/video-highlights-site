from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import headline_pipeline as hlp
import headline_preprocess as hpp
import headline_scoring as hls
import headline_validation as hlv
import headline_generation as hlg
import headline_candidate_selection as hss
import transcript_io as tio
import transcript_validation as tv
from transcription import audio_extraction as tx_audio
from transcription import screenshot as tx_screenshot
from transcription import segment_persistence as tx_persistence
from transcription import target_selection as tx_targets
from transcription import whisper_runner as tx_whisper
from transcription.orchestration import PipelineSteps, run_pipeline
from transcription.cli import RunOptions, build_run_options, parse_cli_args
from transcription.config import PipelineSettings

from transcript_postprocess import (
    TermDictionary,
    TermNormalizationConfig,
)

from update_vods import (
    ENV_PATH,
    CACHE_PATH,
    OUT_PATH,
    build_segment_screenshot_file_path,
    build_segment_screenshot_public_path,
    configure_runtime_environment,
    load_local_env,
    write_processed_cache,
    write_public_data,
)

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

ACTIVE_TERM_DICTIONARY = hss.ACTIVE_TERM_DICTIONARY
BASE_TERM_DICTIONARY = hss.BASE_TERM_DICTIONARY
EXACT_ALIAS_PARTICLE_SUFFIXES = hss.EXACT_ALIAS_PARTICLE_SUFFIXES
FILLER_PREFIX_RE = hss.FILLER_PREFIX_RE
GAME_TERM_DICTIONARY = hss.GAME_TERM_DICTIONARY
HEADLINE_FUNCTION_WORD_RE = hss.HEADLINE_FUNCTION_WORD_RE
HEADLINE_META_RE = hss.HEADLINE_META_RE
HEADLINE_SENSITIVE_RE = hss.HEADLINE_SENSITIVE_RE
JAPANESE_CHAR_RE = hss.JAPANESE_CHAR_RE
PREPROCESS_CONTEXT = hss.PREPROCESS_CONTEXT
SOURCE_ACTION_HINT_RE = hss.SOURCE_ACTION_HINT_RE
SOURCE_CALL_ONLY_RE = hss.SOURCE_CALL_ONLY_RE
SOURCE_CLAUSE_MAX_CHARS = hss.SOURCE_CLAUSE_MAX_CHARS
SOURCE_CONTENT_WORD_RE = hss.SOURCE_CONTENT_WORD_RE
SOURCE_DEFAULT_CONFIG = hss.SOURCE_DEFAULT_CONFIG
SOURCE_GREETING_ONLY_RE = hss.SOURCE_GREETING_ONLY_RE
SOURCE_INCOMPLETE_END_RE = hss.SOURCE_INCOMPLETE_END_RE
SOURCE_INTERJECTION_INLINE_RE = hss.SOURCE_INTERJECTION_INLINE_RE
SOURCE_INTERJECTION_RE = hss.SOURCE_INTERJECTION_RE
SOURCE_INTERJECTION_TOKEN_RE = hss.SOURCE_INTERJECTION_TOKEN_RE
SOURCE_LOW_SIGNAL_CLAUSE_RE = hss.SOURCE_LOW_SIGNAL_CLAUSE_RE
SOURCE_NOISE_EDGE_RE = hss.SOURCE_NOISE_EDGE_RE
SOURCE_ONLY_GREET_RE = hss.SOURCE_ONLY_GREET_RE
SOURCE_REACTION_ONLY_RE = hss.SOURCE_REACTION_ONLY_RE
SOURCE_REPEAT_WORD_RE = hss.SOURCE_REPEAT_WORD_RE
SOURCE_SELECTION_CHATTER_RE = hss.SOURCE_SELECTION_CHATTER_RE
SOURCE_SELECTION_COLLOQUIAL_TAIL_RE = hss.SOURCE_SELECTION_COLLOQUIAL_TAIL_RE
SOURCE_SELECTION_SUSPICIOUS_RE = hss.SOURCE_SELECTION_SUSPICIOUS_RE
SOURCE_SENTENCE_END_RE = hss.SOURCE_SENTENCE_END_RE
SOURCE_SENTENCE_SPLIT_RE = hss.SOURCE_SENTENCE_SPLIT_RE
SOURCE_STOPWORD_TOKENS = hss.SOURCE_STOPWORD_TOKENS
SOURCE_SUBJECT_HINT_RE = hss.SOURCE_SUBJECT_HINT_RE
SOURCE_TOKEN_SPLIT_RE = hss.SOURCE_TOKEN_SPLIT_RE
SOURCE_TRAILING_CHATTER_RE = hss.SOURCE_TRAILING_CHATTER_RE
SourceSelectionContext = hss.SourceSelectionContext
SourceSelectionResult = hss.SourceSelectionResult
SourceSentenceCandidate = hss.SourceSentenceCandidate
SourceValidationResult = hss.SourceValidationResult
TranscriptResult = hss.TranscriptResult
_build_source_selection_result = hss._build_source_selection_result
_candidate_midpoint_abs_sec = hss._candidate_midpoint_abs_sec
_collect_game_term_match_info = hss._collect_game_term_match_info
_collect_optional_alias_hits = hss._collect_optional_alias_hits
_collect_source_sentence_candidates = hss._collect_source_sentence_candidates
_contains_dictionary_term = hss._contains_dictionary_term
_contains_exact_alias_token = hss._contains_exact_alias_token
_content_token_count = hss._content_token_count
_count_action_hints = hss._count_action_hints
_count_content_words = hss._count_content_words
_count_subject_hints = hss._count_subject_hints
_interjection_ratio = hss._interjection_ratio
_is_content_token = hss._is_content_token
_is_greeting_or_reaction_clause = hss._is_greeting_or_reaction_clause
_iter_source_tokens = hss._iter_source_tokens
_log_source_selection = hss._log_source_selection
_merge_source_config = hss._merge_source_config
_score_activity_peak = hss._score_activity_peak
_score_center_proximity = hss._score_center_proximity
_score_source_sentence_candidate = hss._score_source_sentence_candidate
_segment_sentence_candidates = hss._segment_sentence_candidates
_select_source_sentences = hss._select_source_sentences
_split_source_sentences_for_headline = hss._split_source_sentences_for_headline
_strip_reaction_prefix = hss._strip_reaction_prefix
_to_optional_float = hss._to_optional_float
_unknown_token_ratio = hss._unknown_token_ratio
build_headline_source_config = hss.build_headline_source_config
build_headline_source_text = hss.build_headline_source_text
clean_source_sentence = hss.clean_source_sentence
cleanup_source_clause = hss.cleanup_source_clause
collapse_japanese_spacing = hss.collapse_japanese_spacing
collect_game_term_hits = hss.collect_game_term_hits
collect_source_term_counts = hss.collect_source_term_counts
collect_source_terms_for_headline = hss.collect_source_terms_for_headline
extract_candidate_clauses = hss.extract_candidate_clauses
is_low_signal_clause = hss.is_low_signal_clause
is_valid_headline_source_text = hss.is_valid_headline_source_text
load_term_dictionary = hss.load_term_dictionary
merge_term_dictionaries = hss.merge_term_dictionaries
normalize_headline_source_text = hss.normalize_headline_source_text
normalize_source_clause = hss.normalize_source_clause
normalize_source_text = hss.normalize_source_text
normalize_transcript_terms = hss.normalize_transcript_terms
resolve_active_term_dictionary = hss.resolve_active_term_dictionary
sanitize_headline = hss.sanitize_headline
smart_truncate = hss.smart_truncate
split_source_clauses = hss.split_source_clauses
split_source_text = hss.split_source_text
text_similarity = hss.text_similarity
trim_unsupported_trailing_token = hss.trim_unsupported_trailing_token
DEFAULT_HEADLINE_TEXT = hss.DEFAULT_HEADLINE_TEXT
FINAL_HEADLINE_SOFT_REASONS = hss.FINAL_HEADLINE_SOFT_REASONS
HEADLINE_ALLOWED_CHARS_RE = hss.HEADLINE_ALLOWED_CHARS_RE
HEADLINE_BROKEN_PHRASE_RE = hss.HEADLINE_BROKEN_PHRASE_RE
HEADLINE_CHANGE_HINT_RE = hss.HEADLINE_CHANGE_HINT_RE
HEADLINE_CONVERSATIONAL_END_RE = hss.HEADLINE_CONVERSATIONAL_END_RE
HEADLINE_CONVERSATIONAL_FRAGMENT_RE = hss.HEADLINE_CONVERSATIONAL_FRAGMENT_RE
HEADLINE_CONVERSATIONAL_PHRASE_RE = hss.HEADLINE_CONVERSATIONAL_PHRASE_RE
HEADLINE_EVENT_SUMMARY_RE = hss.HEADLINE_EVENT_SUMMARY_RE
HEADLINE_FIRST_PERSON_PRONOUN_RE = hss.HEADLINE_FIRST_PERSON_PRONOUN_RE
HEADLINE_IMPRESSION_FRAGMENT_RE = hss.HEADLINE_IMPRESSION_FRAGMENT_RE
HEADLINE_KEYWORD_RE = hss.HEADLINE_KEYWORD_RE
HEADLINE_LOW_SIGNAL_RE = hss.HEADLINE_LOW_SIGNAL_RE
HEADLINE_SOURCE_CONFIG = hss.HEADLINE_SOURCE_CONFIG
HeadlineCandidate = hss.HeadlineCandidate
HeadlineProviderError = hss.HeadlineProviderError
HeadlineResult = hss.HeadlineResult
HeadlineScore = hss.HeadlineScore
LOCAL_HEADLINE_MODEL = hss.LOCAL_HEADLINE_MODEL
PUBLISH_BLOCKING_HEADLINE_REASONS = hss.PUBLISH_BLOCKING_HEADLINE_REASONS
PUBLISH_CONVERSATIONAL_EDGE_RE = hss.PUBLISH_CONVERSATIONAL_EDGE_RE
SOFT_DROP_HEADLINE_TOKENS = hss.SOFT_DROP_HEADLINE_TOKENS
SOFT_HEADLINE_ISSUES = hss.SOFT_HEADLINE_ISSUES
TITLE_ENDING_FUNCTION_RE = hss.TITLE_ENDING_FUNCTION_RE
WEAK_HEADLINE_RE = hss.WEAK_HEADLINE_RE
_build_remote_comparison_pool = hss._build_remote_comparison_pool
_candidate_confidence_from_metadata = hss._candidate_confidence_from_metadata
_collect_used_terms = hss._collect_used_terms
_headline_title_structure_bonus = hss._headline_title_structure_bonus
_normalized_provider_name = hss._normalized_provider_name
_to_candidate_confidence = hss._to_candidate_confidence
_to_int = hss._to_int
build_extractive_headline = hss.build_extractive_headline
build_fallback_extractive_result = hss.build_fallback_extractive_result
build_headline_response_schema = hss.build_headline_response_schema
build_headline_retry_prompt = hss.build_headline_retry_prompt
build_natural_fallback_headline = hss.build_natural_fallback_headline
build_pattern_fallback_headline = hss.build_pattern_fallback_headline
build_remote_headline_prompt = hss.build_remote_headline_prompt
build_rule_based_headline = hss.build_rule_based_headline
build_safe_fallback_headline = hss.build_safe_fallback_headline
build_tag_based_fallback_headline = hss.build_tag_based_fallback_headline
choose_best_headline = hss.choose_best_headline
choose_best_remote_headline = hss.choose_best_remote_headline
cleanup_headline_candidate = hss.cleanup_headline_candidate
collect_headline_candidates = hss.collect_headline_candidates
compare_tokenizer_function_detection = hss.compare_tokenizer_function_detection
compute_source_quality_penalty = hss.compute_source_quality_penalty
contains_emoji = hss.contains_emoji
ensure_usable_remote_headline = hss.ensure_usable_remote_headline
explain_headline_issues = hss.explain_headline_issues
extract_json_like_fragment = hss.extract_json_like_fragment
finalize_headline = hss.finalize_headline
find_unusable_headline_reason = hss.find_unusable_headline_reason
generate_headline_candidates = hss.generate_headline_candidates
has_excessive_symbols = hss.has_excessive_symbols
headline_reuses_source_terms = hss.headline_reuses_source_terms
is_acceptable_headline = hss.is_acceptable_headline
is_publishable_headline = hss.is_publishable_headline
is_safe_extractive_headline_candidate = hss.is_safe_extractive_headline_candidate
normalize_headline_output = hss.normalize_headline_output
now_iso = hss.now_iso
parse_headline_candidates_output = hss.parse_headline_candidates_output
rank_headline_candidate = hss.rank_headline_candidate
score_headline_candidate = hss.score_headline_candidate
score_headline_candidate_with_source = hss.score_headline_candidate_with_source
split_headline_issues = hss.split_headline_issues
strip_stream_title = hss.strip_stream_title
validate_final_headline_japanese = hss.validate_final_headline_japanese
validate_headline_result = hss.validate_headline_result

extract_response_output_text = hlg.extract_response_output_text
extract_gemini_output_text = hlg.extract_gemini_output_text
read_http_error_detail = hlg.read_http_error_detail
classify_gemini_http_error = hlg.classify_gemini_http_error
is_temporary_transport_error = hlg.is_temporary_transport_error


def _sync_headline_exports() -> None:
    for name in hss.EXPORTED_NAMES:
        if name not in {"refresh_runtime_configuration", "set_active_term_dictionary"}:
            globals()[name] = getattr(hss, name)


def apply_pipeline_settings(settings: PipelineSettings) -> None:
    globals().update(settings.as_globals())
    hss.apply_pipeline_settings(settings)
    hss.refresh_runtime_configuration()
    _sync_headline_exports()


def refresh_runtime_configuration() -> None:
    hss.refresh_runtime_configuration()
    _sync_headline_exports()


def set_active_term_dictionary(use_game_term_dictionary: bool) -> TermDictionary:
    result = hss.set_active_term_dictionary(use_game_term_dictionary)
    _sync_headline_exports()
    return result


apply_pipeline_settings(PipelineSettings.from_env({}))

SEGMENT_SCREENSHOT_WIDTH = 192
SEGMENT_SCREENSHOT_HEIGHT = 108
SEGMENT_SCREENSHOT_CAPTURE_OFFSET_SEC = 1.0
SEGMENT_SCREENSHOT_TIMEOUT_SEC = 30
SEGMENT_SCREENSHOT_QUALITY = 72
HEADLINE_NOUN_LIST_ONLY_RE = HEADLINE_ALLOWED_CHARS_RE
REFLECTIVE_HEADLINE_TOKENS = hlv.REFLECTIVE_HEADLINE_TOKENS
SOURCE_CLAUSE_EXTRA_CHARS = hpp.SOURCE_CLAUSE_EXTRA_CHARS
SOURCE_CONTENT_TOKEN_RE = re.compile(r"[A-Za-z0-9]{3,}|[\u30a1-\u30ff]{3,}|[\u4e00-\u9fff]{2,}")


@dataclass
class SegmentTarget:
    video: dict[str, Any]
    item: dict[str, Any]
    start_sec: int
    end_sec: int
    needs_transcript: bool
    needs_headline: bool


def make_source_selection_context(
    target: SegmentTarget,
    *,
    options: RunOptions,
    transcript_pass: str,
    print_details: bool,
) -> SourceSelectionContext:
    activity_map = target.video.get("activity_map")
    return SourceSelectionContext(
        item_id=str(target.item.get("id") or "").strip(),
        transcript_pass=str(transcript_pass or "unknown").strip() or "unknown",
        scene_start_sec=_to_int(target.item.get("start_sec")),
        scene_end_sec=_to_int(target.item.get("end_sec")),
        transcript_window_start_sec=int(target.start_sec),
        transcript_window_end_sec=int(target.end_sec),
        activity_map=activity_map if isinstance(activity_map, dict) else None,
        sentence_limit=max(1, min(2, int(options.source_sentence_limit))),
        use_game_term_dictionary=bool(options.use_game_term_dictionary),
        print_details=bool(print_details),
    )


@dataclass(frozen=True)
class TranscribePassConfig:
    model: str
    preprocess_profile: str
    vad_filter: bool
    word_timestamps: bool
    condition_on_previous_text: bool = False
    beam_size: int = 1
    vad_parameters: dict[str, Any] | None = None
    extra_padding_sec: int = 0


@dataclass(frozen=True)
class RetranscribeConfig:
    enabled: bool
    selection_mode: str
    top_n: int
    low_info_token_threshold: int
    suspicious_ratio_threshold: float


@dataclass
class RunSummary:
    transcript_success: int = 0
    transcript_skipped: int = 0
    headline_success: int = 0
    headline_skipped: int = 0


class WhisperTranscriber:
    def __init__(self) -> None:
        self._model_cache = tx_whisper.FasterWhisperModelCache(
            device=TRANSCRIPT_DEVICE,
            compute_type=TRANSCRIPT_COMPUTE_TYPE,
        )

    def transcribe(
        self,
        media_path: Path,
        *,
        model_name: str | None = None,
        vad_filter: bool = True,
        word_timestamps: bool = False,
        condition_on_previous_text: bool = False,
        beam_size: int = 1,
        vad_parameters: dict[str, Any] | None = None,
    ) -> TranscriptResult:
        return tx_whisper.transcribe_media(
            media_path,
            model_cache=self._model_cache,
            model_name=(model_name or TRANSCRIPT_MODEL).strip() or TRANSCRIPT_MODEL,
            result_factory=TranscriptResult,
            optional_float=_to_optional_float,
            vad_filter=vad_filter,
            word_timestamps=word_timestamps,
            condition_on_previous_text=condition_on_previous_text,
            beam_size=beam_size,
            vad_parameters=vad_parameters,
        )


def main(argv: list[str] | None = None) -> None:
    run_pipeline(
        argv,
        steps=PipelineSteps(
            setup_execution=_setup_execution,
            collect_targets=_collect_targets_and_check_preconditions,
            print_run_options=_print_run_options,
            print_dry_run_targets=_print_dry_run_targets,
            setup_transcription_components=_setup_transcription_components,
            create_summary=RunSummary,
            run_first_pass=_run_first_pass_transcription_loop,
            run_second_pass=_run_second_pass_retranscription_loop,
            run_headlines=_run_headline_generation_loop,
            finalize_outputs=_finalize_and_save_outputs,
            print_summary=_print_summary,
        ),
    )


def _setup_execution(argv: list[str] | None = None) -> tuple[RunOptions, dict[str, Any]]:
    load_local_env(ENV_PATH)
    configure_runtime_environment(os.environ)
    settings = PipelineSettings.from_env(os.environ)
    apply_pipeline_settings(settings)
    refresh_runtime_configuration()
    options = build_run_options(parse_cli_args(argv), settings)
    set_active_term_dictionary(options.use_game_term_dictionary)
    headline_source_config = build_headline_source_config(
        source_sentence_limit=options.source_sentence_limit,
        print_source_selection=options.print_source_selection,
        use_game_term_dictionary=options.use_game_term_dictionary,
    )
    return options, headline_source_config


def _collect_targets_and_check_preconditions(
    *,
    options: RunOptions,
) -> tuple[list[dict[str, Any]], hlg.ResilientHeadlineGenerator | None, list[SegmentTarget]] | None:
    if not CACHE_PATH.exists():
        print(f"warn: no processed cache found at {CACHE_PATH}")
        return None

    videos = load_processed_videos()
    headline_generator = build_headline_generator()
    target_vod_ids = resolve_target_vod_ids(videos, options=options)
    if options.only_vod_id:
        print(f"info: transcript target vod scope=explicit vod_id={options.only_vod_id}")
    elif target_vod_ids is None:
        print("info: transcript target vod scope=all")
    else:
        joined_vod_ids = ",".join(target_vod_ids) if target_vod_ids else "none"
        print(f"info: transcript target vod scope=recent_public vod_ids={joined_vod_ids}")
    targets = collect_targets(
        videos,
        headline_enabled=headline_generator is not None,
        options=options,
        target_vod_ids=target_vod_ids,
    )
    if not targets:
        print("No transcript/headline work items found.")
        return None
    return videos, headline_generator, targets


def _print_run_options(options: RunOptions) -> None:
    print(
        "info: run options "
        f"headline_only={options.headline_only} force_transcript_refresh={options.force_transcript_refresh} "
        f"force_headline_refresh={options.force_headline_refresh} max_segments={options.max_segments} "
        f"item_id={options.only_item_id or 'all'} vod_id={options.only_vod_id or 'all'} "
        f"print_headline_results={options.print_headline_results} print_source_selection={options.print_source_selection} "
        f"source_sentence_limit={options.source_sentence_limit} use_game_term_dictionary={options.use_game_term_dictionary} "
        f"second_pass_selection_mode={options.second_pass_selection_mode} second_pass_top_n={options.second_pass_top_n} "
        f"second_pass_extra_padding_sec={options.second_pass_extra_padding_sec} second_pass_word_timestamps={options.second_pass_word_timestamps} "
        f"second_pass_preprocess_profile={options.second_pass_preprocess_profile} "
        f"target_scope={TRANSCRIPT_TARGET_SCOPE} recent_analyzed_window_hours={TRANSCRIPT_RECENT_ANALYZED_WINDOW_HOURS}"
    )


def _print_dry_run_targets(targets: list[SegmentTarget], *, options: RunOptions) -> bool:
    if not options.dry_run:
        return False
    print(f"dry-run: {len(targets)} segments would be processed")
    for target in targets:
        print(
            "dry-run target "
            f"{target.video.get('vod_id', 'unknown')}:{target.item.get('id', 'segment')} "
            f"transcript={target.needs_transcript} headline={target.needs_headline}"
        )
    return True


def _setup_transcription_components(
    targets: list[SegmentTarget],
    *,
    options: RunOptions,
) -> tuple[
    WhisperTranscriber | None,
    str | None,
    TranscribePassConfig,
    TranscribePassConfig,
    RetranscribeConfig,
]:
    transcriber: WhisperTranscriber | None = None
    transcript_prereq_error = detect_transcription_prerequisite_error(targets)
    if transcript_prereq_error:
        print(f"warn: {transcript_prereq_error}")
    elif any(target.needs_transcript for target in targets):
        transcriber = WhisperTranscriber()

    return (
        transcriber,
        transcript_prereq_error,
        build_first_pass_config(),
        build_second_pass_config(options=options),
        build_retranscribe_config(options=options),
    )


def _run_first_pass_transcription_loop(
    targets: list[SegmentTarget],
    *,
    transcriber: WhisperTranscriber | None,
    transcript_prereq_error: str | None,
    first_pass_config: TranscribePassConfig,
    headline_source_config: dict[str, Any],
    options: RunOptions,
    summary: RunSummary,
) -> dict[str, TranscriptResult]:
    first_pass_results: dict[str, TranscriptResult] = {}

    for index, target in enumerate(targets, start=1):
        label = f'{target.video.get("vod_id", "unknown")}:{target.item.get("id", "segment")}'
        if not target.needs_transcript:
            continue
        print(f"transcribe-pass1 {index}/{len(targets)} {label}")
        log_item_snapshot("before_transcript", label, target.item)
        if transcript_prereq_error or transcriber is None:
            reason = transcript_prereq_error or "transcriber is not available"
            has_existing_transcript = bool(str(target.item.get("transcript") or "").strip())
            has_existing_segments = bool(target.item.get("transcript_segments"))
            if has_existing_transcript or has_existing_segments:
                print(
                    f"warn: transcript failed for {label} ({reason}); "
                    "preserving existing transcript/transcript_segments"
                )
                summary.transcript_skipped += 1
                log_item_snapshot("after_transcript_error", label, target.item)
                continue
            clear_transcript_artifacts(target.item)
            cleared_headline = clear_headline_artifacts(target.item)
            target.item["transcript_status"] = "error"
            target.item["transcript_error"] = reason[:300]
            target.item["transcript_generated_at"] = now_iso()
            summary.transcript_skipped += 1
            print(f"warn: transcript failed for {label} ({reason})")
            if cleared_headline:
                print(f"info: cleared stale headline fields label={label} fields={cleared_headline}")
            log_item_snapshot("after_transcript_error", label, target.item)
            continue
        try:
            result = transcribe_target(target, transcriber, config=first_pass_config)
        except Exception as exc:
            has_existing_transcript = bool(str(target.item.get("transcript") or "").strip())
            has_existing_segments = bool(target.item.get("transcript_segments"))
            if has_existing_transcript or has_existing_segments:
                print(
                    f"warn: transcript failed for {label} ({exc}); "
                    "preserving existing transcript/transcript_segments"
                )
                summary.transcript_skipped += 1
                log_item_snapshot("after_transcript_error", label, target.item)
                continue
            clear_transcript_artifacts(target.item)
            cleared_headline = clear_headline_artifacts(target.item)
            target.item["transcript_status"] = "error"
            target.item["transcript_error"] = str(exc)[:300]
            target.item["transcript_generated_at"] = now_iso()
            summary.transcript_skipped += 1
            print(f"warn: transcript failed for {label} ({exc})")
            if cleared_headline:
                print(f"info: cleared stale headline fields label={label} fields={cleared_headline}")
            log_item_snapshot("after_transcript_error", label, target.item)
            continue

        if TERM_NORMALIZATION_ENABLED:
            normalized = normalize_transcript_terms(result.text, ACTIVE_TERM_DICTIONARY, TERM_NORMALIZATION_CONFIG)
            result.normalized_text = normalized.text
            if normalized.replacements:
                for row in normalized.replacements[:20]:
                    print(
                        "debug: term normalization "
                        f"item={target.item.get('id')} category={row.category} "
                        f"from={row.original} to={row.replacement} sim={row.similarity:.1f}"
                    )
            result.text = normalized.text

        item_id = str(target.item.get("id") or "")
        first_pass_results[item_id] = result
        target.item["_active_transcript_model"] = first_pass_config.model
        apply_transcript_result(target.item, target, result)
        target.item["transcript_pass"] = "first"
        if target.item.get("transcript_status") == "ok":
            first_pass_context = make_source_selection_context(
                target,
                options=options,
                transcript_pass="first",
                print_details=False,
            )
            target.item["transcript_source_text"] = build_headline_source_text(
                result,
                headline_source_config,
                selection_context=first_pass_context,
            )
        else:
            target.item.pop("transcript_source_text", None)
        if result.text:
            summary.transcript_success += 1
        else:
            summary.transcript_skipped += 1
        log_item_snapshot("after_transcript", label, target.item)

    return first_pass_results


def _run_second_pass_retranscription_loop(
    targets: list[SegmentTarget],
    *,
    first_pass_results: dict[str, TranscriptResult],
    transcriber: WhisperTranscriber | None,
    second_pass_config: TranscribePassConfig,
    retranscribe_config: RetranscribeConfig,
    headline_source_config: dict[str, Any],
    options: RunOptions,
) -> dict[str, TranscriptResult]:
    if transcriber is None:
        return first_pass_results

    first_pass_results = maybe_retranscribe_top_candidates(
        targets,
        first_pass_results,
        transcriber,
        retranscribe_config,
        options=options,
    )
    for target in targets:
        item_id = str(target.item.get("id") or "")
        result = first_pass_results.get(item_id)
        if not result or not target.needs_transcript:
            continue
        if target.item.get("_second_pass_applied"):
            target.item["_active_transcript_model"] = second_pass_config.model
            target.item["transcript_pass"] = "second"
        apply_transcript_result(target.item, target, result)
        if target.item.get("transcript_status") == "ok":
            transcript_pass = str(target.item.get("transcript_pass") or "second")
            second_pass_context = make_source_selection_context(
                target,
                options=options,
                transcript_pass=transcript_pass,
                print_details=False,
            )
            target.item["transcript_source_text"] = build_headline_source_text(
                result,
                headline_source_config,
                selection_context=second_pass_context,
            )
        else:
            target.item.pop("transcript_source_text", None)

    return first_pass_results


@dataclass(frozen=True)
class HeadlineLoopInputs:
    transcript_status: str
    transcript_text_raw: str


@dataclass(frozen=True)
class HeadlinePreparedInputs:
    transcript_text: str
    prepared_source_text: str
    source_selection_debug: dict[str, Any]


@dataclass(frozen=True)
class HeadlineSourceStrategy:
    source_validation: SourceValidationResult
    initial_mode: str
    default_confidence: str
    quality_penalty: float


@dataclass(frozen=True)
class HeadlineGenerationOutcome:
    headline: HeadlineResult
    generation_reason: str


def _collect_headline_loop_inputs(target: SegmentTarget, *, label: str) -> HeadlineLoopInputs:
    transcript_status = str(target.item.get("transcript_status") or "").strip().lower()
    transcript_text_raw = str(target.item.get("transcript") or "").strip()
    print(
        "debug: headline gate check "
        f"label={label} needs_headline={target.needs_headline} transcript_status={transcript_status or 'none'} "
        f"has_transcript={bool(transcript_text_raw)}"
    )
    return HeadlineLoopInputs(
        transcript_status=transcript_status,
        transcript_text_raw=transcript_text_raw,
    )


def _is_headline_generation_ready(target: SegmentTarget, inputs: HeadlineLoopInputs) -> bool:
    return bool(target.needs_headline and inputs.transcript_status == "ok" and inputs.transcript_text_raw)


def _normalize_transcript_for_headline_generation(
    target: SegmentTarget,
    *,
    transcript_text_raw: str,
) -> str:
    transcript_text = transcript_text_raw
    if TERM_NORMALIZATION_ENABLED:
        normalized_cached = normalize_transcript_terms(
            transcript_text,
            ACTIVE_TERM_DICTIONARY,
            TERM_NORMALIZATION_CONFIG,
        )
        if normalized_cached.replacements:
            for row in normalized_cached.replacements[:20]:
                print(
                    "debug: term normalization (headline-only cached) "
                    f"item={target.item.get('id')} category={row.category} "
                    f"from={row.original} to={row.replacement} sim={row.similarity:.1f}"
                )
        transcript_text = normalized_cached.text
    return transcript_text


def _build_headline_source_text_inputs(
    target: SegmentTarget,
    *,
    first_pass_results: dict[str, TranscriptResult],
    headline_source_config: dict[str, Any],
    options: RunOptions,
    transcript_text: str,
) -> tuple[str, dict[str, Any]]:
    source_result = TranscriptResult(
        text=transcript_text,
        language=str(target.item.get("transcript_language") or ""),
        language_probability=_to_optional_float(target.item.get("transcript_language_probability")),
        segments=(first_pass_results.get(str(target.item.get("id") or "")) or TranscriptResult("", "", None)).segments,
    )
    source_result.normalized_text = transcript_text
    source_selection_context = make_source_selection_context(
        target,
        options=options,
        transcript_pass=str(target.item.get("transcript_pass") or "cached"),
        print_details=bool(options.print_headline_results or options.print_source_selection),
    )
    source_selection_debug: dict[str, Any] = {}
    prepared_source_text = build_headline_source_text(
        source_result,
        headline_source_config,
        selection_context=source_selection_context,
        selection_result_out=source_selection_debug,
    )
    target.item["headline_source_text"] = prepared_source_text
    return prepared_source_text, source_selection_debug


def _prepare_headline_generation_inputs(
    target: SegmentTarget,
    *,
    first_pass_results: dict[str, TranscriptResult],
    headline_source_config: dict[str, Any],
    options: RunOptions,
    transcript_text_raw: str,
) -> HeadlinePreparedInputs:
    transcript_text = _normalize_transcript_for_headline_generation(
        target,
        transcript_text_raw=transcript_text_raw,
    )
    prepared_source_text, source_selection_debug = _build_headline_source_text_inputs(
        target,
        first_pass_results=first_pass_results,
        headline_source_config=headline_source_config,
        options=options,
        transcript_text=transcript_text,
    )
    return HeadlinePreparedInputs(
        transcript_text=transcript_text,
        prepared_source_text=prepared_source_text,
        source_selection_debug=source_selection_debug,
    )


def _validate_headline_source_and_decide_mode(
    item: dict[str, Any],
    *,
    prepared_source_text: str,
    headline_source_config: dict[str, Any],
) -> HeadlineSourceStrategy:
    source_validation = is_valid_headline_source_text(prepared_source_text, headline_source_config)
    initial_mode, default_confidence, quality_penalty = decide_headline_generation_strategy(source_validation)
    item["headline_source_validation"] = {
        "accepted": source_validation.accepted,
        "reasons": source_validation.reasons,
        "content_word_count": source_validation.content_word_count,
        "subject_hint_count": source_validation.subject_hint_count,
        "action_hint_count": source_validation.action_hint_count,
        "unknown_ratio": round(source_validation.unknown_ratio, 3),
        "headline_quality_penalty": round(quality_penalty, 3),
        "recommended_mode": initial_mode,
    }
    item["headline_quality_penalty"] = round(quality_penalty, 3)
    return HeadlineSourceStrategy(
        source_validation=source_validation,
        initial_mode=initial_mode,
        default_confidence=default_confidence,
        quality_penalty=quality_penalty,
    )


def _execute_headline_generator(
    target: SegmentTarget,
    *,
    label: str,
    headline_generator: hlg.ResilientHeadlineGenerator | None,
    headline_source_config: dict[str, Any],
    transcript_text: str,
    prepared_source_text: str,
    source_validation: SourceValidationResult,
    initial_mode: str,
) -> HeadlineGenerationOutcome:
    video_title = str(target.video.get("title") or "").strip()
    if initial_mode == "fallback_extractive":
        headline = build_fallback_extractive_result(
            prepared_source_text=prepared_source_text,
            transcript=transcript_text,
            video_title=video_title,
            reason="source_too_weak_for_llm",
            source_config=headline_source_config,
        )
        return HeadlineGenerationOutcome(
            headline=headline,
            generation_reason="fallback_by_source_strategy",
        )

    try:
        headline = headline_generator.generate(
            video_title=video_title,
            start_time=str(target.item.get("start_time") or format_section_time(target.start_sec)).strip(),
            end_time=str(target.item.get("end_time") or format_section_time(target.end_sec)).strip(),
            transcript=transcript_text,
            prepared_transcript=prepared_source_text,
            source_validation=source_validation,
        )
    except Exception as exc:
        print(f"warn: headline generation failed; using fallback label={label} reason={exc}")
        headline = build_fallback_extractive_result(
            prepared_source_text=prepared_source_text,
            transcript=transcript_text,
            video_title=video_title,
            reason=f"llm_error:{exc}",
            source_config=headline_source_config,
        )
        return HeadlineGenerationOutcome(
            headline=headline,
            generation_reason="fallback_after_llm_error",
        )

    if initial_mode == "weak_llm" and headline.generation_mode == "llm_ranked":
        headline.generation_mode = "weak_llm"
        if headline.confidence == "high":
            headline.confidence = "medium"
    return HeadlineGenerationOutcome(
        headline=headline,
        generation_reason=f"llm_mode={headline.generation_mode}",
    )


def _apply_headline_post_filter_fallback(
    target: SegmentTarget,
    *,
    label: str,
    outcome: HeadlineGenerationOutcome,
    headline_source_config: dict[str, Any],
    transcript_text: str,
    prepared_source_text: str,
) -> HeadlineGenerationOutcome:
    final_validation = validate_final_headline_japanese(
        outcome.headline.text,
        source_text=prepared_source_text or transcript_text,
    )
    if is_publishable_headline(outcome.headline.text, source_text=prepared_source_text or transcript_text):
        return outcome

    print(
        "info: post-filter rejected headline; using fallback extractive "
        f"label={label} reasons={final_validation.reasons} headline={outcome.headline.text}"
    )
    headline = build_fallback_extractive_result(
        prepared_source_text=prepared_source_text,
        transcript=transcript_text,
        video_title=str(target.video.get("title") or "").strip(),
        reason=f"post_filter:{','.join(final_validation.reasons)}",
        source_config=headline_source_config,
    )
    fallback_validation = validate_final_headline_japanese(
        headline.text,
        source_text=prepared_source_text or transcript_text,
    )
    if is_publishable_headline(headline.text, source_text=prepared_source_text or transcript_text) and headline.text != DEFAULT_HEADLINE_TEXT:
        return HeadlineGenerationOutcome(
            headline=headline,
            generation_reason="fallback_after_post_filter",
        )

    print(
        "info: content headline unavailable; leaving headline empty "
        f"label={label} reasons={fallback_validation.reasons} headline={headline.text} "
        "reason=content_headline_unavailable"
    )
    return HeadlineGenerationOutcome(
        headline=HeadlineResult(
            text="",
            model=LOCAL_HEADLINE_MODEL,
            source="none",
            generation_mode="skipped_content_validation",
            confidence="low",
            notes=f"extractive_post_filter:{','.join(fallback_validation.reasons)}",
        ),
        generation_reason="content_headline_unavailable",
    )


def _resolve_headline_status(headline: HeadlineResult, source_validation: SourceValidationResult) -> str:
    if headline.generation_mode == "fallback_extractive":
        return headline.generation_mode
    if headline.generation_mode == "skipped_content_validation":
        return "skipped_content_validation"
    if not source_validation.accepted or headline.generation_mode in {"weak_llm", "weak_generated"}:
        return "weak_generated"
    return "ok"


def _apply_generated_headline_to_item(
    item: dict[str, Any],
    *,
    headline: HeadlineResult,
    status: str,
    default_confidence: str,
) -> str:
    item["headline"] = headline.text
    item["headline_source"] = headline.source
    item["headline_model"] = headline.model
    item["headline_status"] = status
    item["headline_generation_mode"] = headline.generation_mode
    item["headline_confidence"] = headline.confidence or default_confidence
    item["headline_generated_at"] = now_iso()
    item.pop("headline_error", None)
    item.pop("headline_skip_reason", None)
    return str(item.get("headline_confidence") or default_confidence)


def _apply_skipped_headline_to_item(
    target: SegmentTarget,
    *,
    label: str,
    transcript_status: str,
    options: RunOptions,
) -> None:
    if not target.needs_headline:
        return

    cleared = clear_headline_artifacts(target.item)
    if cleared:
        print(f"info: cleared stale headline fields label={label} fields={cleared}")
    if transcript_status == "error":
        reason = str(target.item.get("transcript_error") or "transcript_status_error").strip() or "transcript_status_error"
        target.item["headline_status"] = "skipped_transcript_error"
        target.item["headline_skip_reason"] = reason[:300]
        print(f"info: skipped headline due to transcript error label={label} reason={reason}")
    else:
        target.item["headline_status"] = "skipped_no_transcript"
        if transcript_status:
            target.item["headline_skip_reason"] = f"transcript_status={transcript_status}"[:300]
        else:
            target.item["headline_skip_reason"] = "missing_transcript"
        print(
            "info: skipped headline due to missing transcript "
            f"label={label} transcript_status={transcript_status or 'none'}"
        )
    target.item["headline_generated_at"] = now_iso()
    if options.print_headline_results:
        print_headline_result(
            label=label,
            item=target.item,
            source_text=str(target.item.get("headline_source_text") or "").strip(),
            source_validation=None,
            headline_result=None,
            generation_reason=str(target.item.get("headline_skip_reason") or "skipped").strip() or "skipped",
        )


def _log_headline_success_and_update_summary(
    target: SegmentTarget,
    *,
    label: str,
    status: str,
    final_confidence: str,
    strategy: HeadlineSourceStrategy,
    outcome: HeadlineGenerationOutcome,
    prepared_inputs: HeadlinePreparedInputs,
    options: RunOptions,
    summary: RunSummary,
) -> None:
    print(
        "info: headline finalized "
        f"label={label} status={status} mode={outcome.headline.generation_mode} confidence={final_confidence} "
        f"reason={outcome.generation_reason} source_validation_reasons={strategy.source_validation.reasons or 'none'}"
    )
    if options.print_headline_results:
        print_headline_result(
            label=label,
            item=target.item,
            source_text=prepared_inputs.prepared_source_text,
            source_validation=strategy.source_validation,
            headline_result=outcome.headline,
            generation_reason=outcome.generation_reason,
            source_selection=prepared_inputs.source_selection_debug.get("selection")
            if prepared_inputs.source_selection_debug
            else None,
        )
    summary.headline_success += 1


def _update_headline_skip_summary(target: SegmentTarget, summary: RunSummary) -> None:
    summary.headline_skipped += 1 if target.needs_headline else 0


def _run_headline_generation_loop(
    targets: list[SegmentTarget],
    *,
    first_pass_results: dict[str, TranscriptResult],
    headline_generator: hlg.ResilientHeadlineGenerator | None,
    headline_source_config: dict[str, Any],
    options: RunOptions,
    summary: RunSummary,
) -> None:
    for index, target in enumerate(targets, start=1):
        label = f'{target.video.get("vod_id", "unknown")}:{target.item.get("id", "segment")}'
        started = time.perf_counter()
        inputs = _collect_headline_loop_inputs(target, label=label)

        if not target.needs_transcript:
            summary.transcript_skipped += 1

        if _is_headline_generation_ready(target, inputs):
            prepared_inputs = _prepare_headline_generation_inputs(
                target,
                first_pass_results=first_pass_results,
                headline_source_config=headline_source_config,
                options=options,
                transcript_text_raw=inputs.transcript_text_raw,
            )
            strategy = _validate_headline_source_and_decide_mode(
                target.item,
                prepared_source_text=prepared_inputs.prepared_source_text,
                headline_source_config=headline_source_config,
            )
            print(f"headline {index}/{len(targets)} {label}")
            if not strategy.source_validation.accepted:
                print(
                    "info: source validation accepted=false but continue headline generation "
                    f"label={label} reasons={strategy.source_validation.reasons} mode={strategy.initial_mode} "
                    f"penalty={strategy.quality_penalty:.2f}"
                )

            outcome = _execute_headline_generator(
                target,
                label=label,
                headline_generator=headline_generator,
                headline_source_config=headline_source_config,
                transcript_text=prepared_inputs.transcript_text,
                prepared_source_text=prepared_inputs.prepared_source_text,
                source_validation=strategy.source_validation,
                initial_mode=strategy.initial_mode,
            )
            outcome = _apply_headline_post_filter_fallback(
                target,
                label=label,
                outcome=outcome,
                headline_source_config=headline_source_config,
                transcript_text=prepared_inputs.transcript_text,
                prepared_source_text=prepared_inputs.prepared_source_text,
            )
            status = _resolve_headline_status(outcome.headline, strategy.source_validation)
            final_confidence = _apply_generated_headline_to_item(
                target.item,
                headline=outcome.headline,
                status=status,
                default_confidence=strategy.default_confidence,
            )
            _log_headline_success_and_update_summary(
                target,
                label=label,
                status=status,
                final_confidence=final_confidence,
                strategy=strategy,
                outcome=outcome,
                prepared_inputs=prepared_inputs,
                options=options,
                summary=summary,
            )
        else:
            _apply_skipped_headline_to_item(
                target,
                label=label,
                transcript_status=inputs.transcript_status,
                options=options,
            )
            _update_headline_skip_summary(target, summary)

        elapsed = time.perf_counter() - started
        print(f"done {label} ({elapsed:.1f}s)")


def _finalize_and_save_outputs(videos: list[dict[str, Any]], targets: list[SegmentTarget]) -> None:
    for target in targets:
        target.item.pop("_second_pass_zscore_rank", None)
        target.item.pop("_second_pass_applied", None)
        target.item.pop("_active_transcript_model", None)
    now = datetime.now().astimezone()
    write_processed_cache(videos, now)
    write_public_data(videos, now)


def _print_summary(summary: RunSummary) -> None:
    print(
        "summary: "
        f"transcript_success={summary.transcript_success} transcript_skipped={summary.transcript_skipped} "
        f"headline_success={summary.headline_success} headline_skipped={summary.headline_skipped}"
    )


def build_headline_generator() -> hlg.ResilientHeadlineGenerator:
    settings = hlg.HeadlineGenerationSettings(
        headline_source_config=HEADLINE_SOURCE_CONFIG,
        headline_max_attempts=HEADLINE_MAX_ATTEMPTS,
        gemini_timeout_sec=GEMINI_TIMEOUT_SEC,
        groq_timeout_sec=GROQ_TIMEOUT_SEC,
        groq_responses_url=GROQ_RESPONSES_URL,
        nvidia_timeout_sec=NVIDIA_TIMEOUT_SEC,
        nvidia_api_url=NVIDIA_API_URL,
        local_headline_model=LOCAL_HEADLINE_MODEL,
    )
    callbacks = hlg.HeadlineGenerationCallbacks(
        build_headline_source_text=build_headline_source_text,
        build_remote_headline_prompt=build_remote_headline_prompt,
        parse_headline_candidates_output=parse_headline_candidates_output,
        choose_best_headline=choose_best_headline,
        ensure_usable_remote_headline=ensure_usable_remote_headline,
        score_headline_candidate_with_source=score_headline_candidate_with_source,
        build_headline_response_schema=build_headline_response_schema,
        build_extractive_headline=build_extractive_headline,
        validate_headline_result=validate_headline_result,
        choose_best_remote_headline=choose_best_remote_headline,
        make_headline_result=HeadlineResult,
        is_publishable_headline=is_publishable_headline,
    )
    return hlg.build_headline_generator(
        gemini_api_key=GEMINI_API_KEY,
        gemini_model=GEMINI_MODEL,
        gemini_api_url=GEMINI_API_URL,
        groq_api_key=GROQ_API_KEY,
        groq_model=GROQ_MODEL,
        nvidia_api_key=NVIDIA_API_KEY,
        nvidia_model=NVIDIA_MODEL,
        settings=settings,
        callbacks=callbacks,
    )


def detect_transcription_prerequisite_error(targets: list[SegmentTarget]) -> str | None:
    if not any(target.needs_transcript for target in targets):
        return None
    if shutil.which("ffmpeg") is None:
        return "ffmpeg is not installed; skipping transcript generation"
    if not yt_dlp_available():
        return "yt-dlp is not installed; skipping transcript generation"
    return None


def apply_transcript_result(item: dict[str, Any], target: SegmentTarget, result: TranscriptResult) -> None:
    tx_persistence.apply_transcript_result(
        item,
        target,
        result,
        transcript_model=TRANSCRIPT_MODEL,
        now_iso=now_iso,
    )


def clear_transcript_artifacts(item: dict[str, Any]) -> list[str]:
    return tx_persistence.clear_transcript_artifacts(item)


def clear_headline_artifacts(item: dict[str, Any]) -> list[str]:
    return tx_persistence.clear_headline_artifacts(item)


def log_item_snapshot(stage: str, label: str, item: dict[str, Any]) -> None:
    tx_persistence.log_item_snapshot(stage, label, item)

def print_headline_result(
    *,
    label: str,
    item: dict[str, Any],
    source_text: str,
    source_validation: SourceValidationResult | None,
    headline_result: HeadlineResult | None,
    generation_reason: str,
    source_selection: SourceSelectionResult | None = None,
) -> None:
    metadata = dict((headline_result.metadata or {}) if headline_result else {})
    comparison = metadata.get("comparison") if isinstance(metadata.get("comparison"), dict) else {}
    provider_candidates = comparison.get("provider_candidates") if isinstance(comparison, dict) else {}

    if not provider_candidates:
        raw_provider = str(metadata.get("provider") or (headline_result.source if headline_result else "")).strip().lower()
        raw_rows = metadata.get("provider_candidates") or []
        if raw_provider and raw_rows:
            provider_candidates = {
                raw_provider: [
                    str((row or {}).get("headline") or "").strip()
                    for row in raw_rows
                    if str((row or {}).get("headline") or "").strip()
                ]
            }

    source_validation_info = source_validation
    if source_validation_info is None:
        row = item.get("headline_source_validation") or {}
        if isinstance(row, dict):
            source_validation_info = SourceValidationResult(
                accepted=bool(row.get("accepted", False)),
                reasons=[str(reason) for reason in (row.get("reasons") or [])],
                content_word_count=int(row.get("content_word_count") or 0),
                subject_hint_count=int(row.get("subject_hint_count") or 0),
                action_hint_count=int(row.get("action_hint_count") or 0),
                unknown_ratio=float(row.get("unknown_ratio") or 0.0),
            )

    selected_score = "n/a"
    if isinstance(comparison, dict) and comparison.get("selected_score") is not None:
        selected_score = str(comparison.get("selected_score"))

    print("headline-result ----------------------------------------")
    print(f"item_id: {item.get('id', 'unknown')} label: {label}")
    print(f"transcript_pass: {item.get('transcript_pass') or 'unknown'}")
    print(f"headline_source_text: {source_text or 'none'}")
    if source_selection is not None:
        selected_sentences = [row.normalized for row in source_selection.selected]
        print(f"selected_source_sentences: {selected_sentences or 'none'}")
        print(f"source_candidate_count: {len(source_selection.candidates)}")
    if source_validation_info is not None:
        print(
            "source_validation: "
            f"accepted={source_validation_info.accepted} reasons={source_validation_info.reasons or 'none'} "
            f"content_words={source_validation_info.content_word_count} "
            f"subject_hints={source_validation_info.subject_hint_count} "
            f"action_hints={source_validation_info.action_hint_count} "
            f"unknown_ratio={source_validation_info.unknown_ratio:.3f}"
        )
    else:
        print("source_validation: none")

    if isinstance(provider_candidates, dict) and provider_candidates:
        for provider, rows in provider_candidates.items():
            printable = [str(row) for row in rows if str(row).strip()]
            print(f"provider_candidates[{provider}]: {printable or 'none'}")
    else:
        print("provider_candidates: none")

    print(f"final_headline: {item.get('headline') or (headline_result.text if headline_result else '') or 'none'}")
    print(f"selection_reason: {generation_reason} selected_score={selected_score}")
    print(f"headline_status: {item.get('headline_status') or 'none'}")
    print(f"headline_generation_mode: {item.get('headline_generation_mode') or (headline_result.generation_mode if headline_result else 'none')}")
    print(f"headline_confidence: {item.get('headline_confidence') or (headline_result.confidence if headline_result else 'none')}")
    print(f"headline_source: {item.get('headline_source') or (headline_result.source if headline_result else 'none')}")
    print(f"headline_model: {item.get('headline_model') or (headline_result.model if headline_result else 'none')}")
    fallback_reason = ''
    if headline_result is None:
        fallback_reason = str(item.get('headline_skip_reason') or '').strip()
    elif (item.get('headline_generation_mode') or headline_result.generation_mode) == 'fallback_extractive':
        fallback_reason = str(headline_result.notes or '').strip()
    if fallback_reason:
        print(f"fallback_reason: {fallback_reason}")
    print("--------------------------------------------------------")


def load_processed_videos() -> list[dict[str, Any]]:
    return tio.load_processed_videos(CACHE_PATH)


def parse_timezone_aware_iso_datetime(value: Any) -> datetime | None:
    return tx_targets.parse_timezone_aware_iso_datetime(value)


def load_latest_public_vod_ids(limit: int = 1) -> list[str]:
    if limit <= 0 or not OUT_PATH.exists():
        return []
    try:
        payload = json.loads(OUT_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return []

    public_vod_ids: list[str] = []
    for video in payload.get("videos") or []:
        vod_id = str(video.get("vod_id") or video.get("id") or "").strip()
        if not vod_id or vod_id in public_vod_ids:
            continue
        public_vod_ids.append(vod_id)
        if len(public_vod_ids) >= limit:
            break
    return public_vod_ids


def collect_recently_analyzed_vod_ids(videos: list[dict[str, Any]], *, now: datetime) -> list[str]:
    return tx_targets.collect_recently_analyzed_vod_ids(
        videos,
        now=now,
        window_hours=TRANSCRIPT_RECENT_ANALYZED_WINDOW_HOURS,
    )


def dedupe_preserving_order(values: list[str]) -> list[str]:
    return tx_targets.dedupe_preserving_order(values)


def resolve_target_vod_ids(videos: list[dict[str, Any]], *, options: RunOptions) -> list[str] | None:
    if options.only_vod_id:
        return [options.only_vod_id]

    if TRANSCRIPT_TARGET_SCOPE in {"all", "full"}:
        return None

    now = datetime.now().astimezone()
    target_vod_ids = dedupe_preserving_order(
        load_latest_public_vod_ids(limit=1) + collect_recently_analyzed_vod_ids(videos, now=now)
    )
    if target_vod_ids:
        return target_vod_ids

    for video in videos:
        vod_id = str(video.get("vod_id") or "").strip()
        if vod_id:
            return [vod_id]
    return []


def collect_targets(
    videos: list[dict[str, Any]],
    *,
    headline_enabled: bool,
    options: RunOptions,
    target_vod_ids: list[str] | None = None,
) -> list[SegmentTarget]:
    target_vod_id_set = set(target_vod_ids) if target_vod_ids is not None else None
    targets: list[SegmentTarget] = []
    for video in videos:
        vod_id = str(video.get("vod_id") or "").strip()
        if target_vod_id_set is not None and vod_id not in target_vod_id_set:
            continue
        if options.only_vod_id and vod_id != options.only_vod_id:
            continue
        vod_url = str(video.get("vod_url") or "").strip()
        for item in video.get("items") or []:
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("id") or "").strip()
            if options.only_item_id and item_id != options.only_item_id:
                continue
            needs_screenshot = should_generate_segment_screenshot(item, vod_id=vod_id)
            needs_transcript = False
            if not options.headline_only:
                needs_transcript = bool(vod_url) and (
                    should_generate_transcript(item, options=options) or needs_screenshot
                )
            needs_headline = should_generate_headline(
                item,
                headline_enabled=headline_enabled,
                needs_transcript=needs_transcript,
                options=options,
            )
            if not needs_transcript and not needs_headline:
                continue
            base_start = _to_int(item.get("start_sec"))
            base_end = _to_int(item.get("end_sec"))
            if base_start is None or base_end is None:
                continue
            start_sec = max(0, base_start - TRANSCRIPT_PADDING_SEC)
            end_sec = max(base_end + TRANSCRIPT_PADDING_SEC, start_sec + 30)
            if end_sec - start_sec > TRANSCRIPT_MAX_DURATION_SEC:
                end_sec = start_sec + TRANSCRIPT_MAX_DURATION_SEC
            targets.append(
                SegmentTarget(
                    video=video,
                    item=item,
                    start_sec=start_sec,
                    end_sec=end_sec,
                    needs_transcript=needs_transcript,
                    needs_headline=needs_headline,
                )
            )
            if len(targets) >= options.max_segments:
                return targets
    return targets


def should_generate_transcript(item: dict[str, Any], *, options: RunOptions) -> bool:
    if options.force_transcript_refresh:
        return True
    transcript = str(item.get("transcript") or "").strip()
    status = str(item.get("transcript_status") or "").strip().lower()
    if transcript and status in {"ok", "empty"}:
        return False
    if status == "error" and not TRANSCRIPT_RETRY_ERRORS:
        return False
    return True


def should_generate_segment_screenshot(item: dict[str, Any], *, vod_id: str) -> bool:
    if not SEGMENT_SCREENSHOT_GENERATION_ENABLED:
        return False
    segment_id = str(item.get("id") or "").strip()
    if not vod_id or not segment_id:
        return False
    screenshot_url = str(item.get("screenshot_url") or "").strip()
    if not screenshot_url:
        screenshot_url = build_segment_screenshot_public_path(vod_id, segment_id)
        item["screenshot_url"] = screenshot_url
    if not screenshot_url.startswith("/data/segment-thumbnails/"):
        return False

    output_path = build_segment_screenshot_file_path(vod_id, segment_id)
    if not output_path.exists():
        return True
    try:
        return output_path.stat().st_size <= 0
    except OSError:
        return True


def should_generate_headline(
    item: dict[str, Any],
    *,
    headline_enabled: bool,
    needs_transcript: bool,
    options: RunOptions,
) -> bool:
    if not headline_enabled:
        return False
    transcript = str(item.get("transcript") or "").strip()
    if options.force_headline_refresh:
        return needs_transcript or bool(transcript)
    headline = str(item.get("headline") or "").strip()
    status = str(item.get("headline_status") or "").strip().lower()
    if headline and status == "ok":
        return False
    if status == "error" and not HEADLINE_RETRY_ERRORS:
        return False
    return needs_transcript or bool(transcript)


def build_first_pass_config() -> TranscribePassConfig:
    vad_parameters: dict[str, Any] | None = None
    if TRANSCRIPT_VAD_MIN_SILENCE_DURATION_MS is not None:
        vad_parameters = {"min_silence_duration_ms": TRANSCRIPT_VAD_MIN_SILENCE_DURATION_MS}
    return TranscribePassConfig(
        model=TRANSCRIPT_MODEL,
        preprocess_profile=TRANSCRIPT_PREPROCESS_PROFILE,
        vad_filter=TRANSCRIPT_VAD_FILTER,
        word_timestamps=False,
        condition_on_previous_text=TRANSCRIPT_CONDITION_ON_PREVIOUS_TEXT,
        beam_size=TRANSCRIPT_BEAM_SIZE,
        vad_parameters=vad_parameters,
        extra_padding_sec=0,
    )


def build_second_pass_config(*, options: RunOptions | None = None) -> TranscribePassConfig:
    preprocess_profile = TRANSCRIPT_SECOND_PASS_PREPROCESS_PROFILE
    word_timestamps = TRANSCRIPT_SECOND_PASS_WORD_TIMESTAMPS
    extra_padding_sec = TRANSCRIPT_SECOND_PASS_EXTRA_PADDING_SEC
    if options is not None:
        preprocess_profile = options.second_pass_preprocess_profile
        word_timestamps = options.second_pass_word_timestamps
        extra_padding_sec = options.second_pass_extra_padding_sec
    return TranscribePassConfig(
        model=TRANSCRIPT_SECOND_PASS_MODEL,
        preprocess_profile=preprocess_profile,
        vad_filter=True,
        word_timestamps=word_timestamps,
        beam_size=1,
        extra_padding_sec=extra_padding_sec,
    )


def build_retranscribe_config(*, options: RunOptions | None = None) -> RetranscribeConfig:
    selection_mode = TRANSCRIPT_SECOND_PASS_SELECTION_MODE
    top_n = max(0, TRANSCRIPT_SECOND_PASS_TOP_N)
    if options is not None:
        selection_mode = options.second_pass_selection_mode
        top_n = max(0, options.second_pass_top_n)
    return RetranscribeConfig(
        enabled=TRANSCRIPT_SECOND_PASS_ENABLED and top_n > 0,
        selection_mode=selection_mode,
        top_n=top_n,
        low_info_token_threshold=TRANSCRIPT_LOW_INFO_TOKEN_THRESHOLD,
        suspicious_ratio_threshold=TRANSCRIPT_SUSPICIOUS_RATIO_THRESHOLD,
    )


def build_audio_preprocess_filters(profile: str) -> str:
    normalized = (profile or "none").strip().lower()
    if normalized == "none":
        return ""
    filters = ["highpass=f=80", "lowpass=f=7600", "loudnorm=I=-16:LRA=11:TP=-1.5"]
    if normalized == "light_denoise":
        filters.append(f"afftdn=nf={TRANSCRIPT_PREPROCESS_DENOISE_STRENGTH}:tn=1")
    return ",".join(filters)


def build_preprocess_ffmpeg_command(input_path: Path, output_path: Path, *, profile: str) -> list[str]:
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-vn",
        "-sn",
        "-dn",
        "-ac",
        "1",
        "-ar",
        "16000",
    ]
    filters = build_audio_preprocess_filters(profile)
    if filters:
        command.extend(["-af", filters])
    command.append(str(output_path))
    return command


def preprocess_clip_audio(input_path: Path, output_path: Path, profile: str = "light") -> Path:
    command = build_preprocess_ffmpeg_command(input_path, output_path, profile=profile)
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        stderr = (completed.stderr or completed.stdout or "ffmpeg failed").strip()
        raise RuntimeError(f"ffmpeg preprocess failed ({profile}): {stderr[:300]}")
    return output_path


def _prepare_audio_for_transcribe(media_path: Path, *, profile: str) -> Path:
    if (profile or "none").strip().lower() == "none":
        return media_path
    output_path = media_path.with_name(f"preprocessed_{profile}.wav")
    print(f"debug: transcript preprocess enabled profile={profile} input={media_path.name}")
    return preprocess_clip_audio(media_path, output_path, profile=profile)


def transcribe_clip_first_pass(
    clip_audio_path: Path,
    config: TranscribePassConfig,
    transcriber: WhisperTranscriber,
) -> TranscriptResult:
    prepared_path = _prepare_audio_for_transcribe(clip_audio_path, profile=config.preprocess_profile)
    return transcriber.transcribe(
        prepared_path,
        model_name=config.model,
        vad_filter=config.vad_filter,
        word_timestamps=config.word_timestamps,
        condition_on_previous_text=config.condition_on_previous_text,
        beam_size=config.beam_size,
        vad_parameters=config.vad_parameters,
    )


def transcribe_clip_second_pass(
    clip_audio_path: Path,
    config: TranscribePassConfig,
    transcriber: WhisperTranscriber,
) -> TranscriptResult:
    prepared_path = _prepare_audio_for_transcribe(clip_audio_path, profile=config.preprocess_profile)
    return transcriber.transcribe(
        prepared_path,
        model_name=config.model,
        vad_filter=config.vad_filter,
        word_timestamps=config.word_timestamps,
        beam_size=config.beam_size,
    )


def transcript_quality_metrics(text: str) -> dict[str, float]:
    return tv.transcript_quality_metrics(
        text,
        content_token_re=SOURCE_CONTENT_TOKEN_RE,
        interjection_token_re=SOURCE_INTERJECTION_TOKEN_RE,
    )


def _score_retranscribe_priority(item: dict[str, Any], transcript_result: TranscriptResult, config: RetranscribeConfig) -> float:
    return tv.score_retranscribe_priority(
        item,
        transcript_result.text,
        config,
        to_int=_to_int,
        to_optional_float=_to_optional_float,
        content_token_re=SOURCE_CONTENT_TOKEN_RE,
        interjection_token_re=SOURCE_INTERJECTION_TOKEN_RE,
    )


def should_retranscribe_clip(
    item: dict[str, Any],
    transcript_result: TranscriptResult,
    config: RetranscribeConfig,
) -> bool:
    return tv.should_retranscribe_clip(
        item,
        transcript_result.text,
        config,
        to_int=_to_int,
        to_optional_float=_to_optional_float,
        content_token_re=SOURCE_CONTENT_TOKEN_RE,
        interjection_token_re=SOURCE_INTERJECTION_TOKEN_RE,
    )


def _annotate_zscore_rank(targets: list[SegmentTarget]) -> None:
    tv.annotate_zscore_rank(targets, to_optional_float=_to_optional_float)


def _maybe_extend_window(target: SegmentTarget, extra_padding_sec: int) -> tuple[int, int]:
    if extra_padding_sec <= 0:
        return target.start_sec, target.end_sec
    start_sec = max(0, target.start_sec - extra_padding_sec)
    end_sec = target.end_sec + extra_padding_sec
    if end_sec - start_sec > TRANSCRIPT_MAX_DURATION_SEC:
        end_sec = start_sec + TRANSCRIPT_MAX_DURATION_SEC
    return start_sec, end_sec


def _resolve_segment_screenshot_seek_sec(*, item: dict[str, Any], clip_start_sec: int, clip_end_sec: int) -> float:
    segment_start = _to_int(item.get("start_sec"))
    seek_sec = 0.0
    if segment_start is not None:
        seek_sec = max(0.0, float(segment_start - clip_start_sec) + SEGMENT_SCREENSHOT_CAPTURE_OFFSET_SEC)
    clip_duration = max(0.0, float(clip_end_sec - clip_start_sec))
    max_seek_sec = max(0.0, clip_duration - 0.5)
    return min(seek_sec, max_seek_sec)


def _capture_segment_screenshot(
    *,
    output_path: Path,
    media_path: Path,
    seek_sec: float,
) -> None:
    tx_screenshot.capture_segment_screenshot(
        output_path=output_path,
        media_path=media_path,
        seek_sec=seek_sec,
        width=SEGMENT_SCREENSHOT_WIDTH,
        height=SEGMENT_SCREENSHOT_HEIGHT,
        quality=SEGMENT_SCREENSHOT_QUALITY,
        timeout_sec=SEGMENT_SCREENSHOT_TIMEOUT_SEC,
    )


def maybe_generate_segment_screenshot(
    target: SegmentTarget,
    *,
    media_path: Path,
    clip_start_sec: int,
    clip_end_sec: int,
) -> None:
    if shutil.which("ffmpeg") is None:
        return

    item = target.item
    video = target.video
    vod_id = str(video.get("vod_id") or "").strip()
    segment_id = str(item.get("id") or "").strip()
    if not vod_id or not segment_id:
        return

    screenshot_url = str(item.get("screenshot_url") or "").strip()
    if not screenshot_url:
        screenshot_url = build_segment_screenshot_public_path(vod_id, segment_id)
        item["screenshot_url"] = screenshot_url

    if not screenshot_url.startswith("/data/segment-thumbnails/"):
        return

    output_path = build_segment_screenshot_file_path(vod_id, segment_id)
    if output_path.exists() and output_path.stat().st_size > 0:
        return
    if not SEGMENT_SCREENSHOT_GENERATION_ENABLED:
        return

    seek_sec = _resolve_segment_screenshot_seek_sec(
        item=item,
        clip_start_sec=clip_start_sec,
        clip_end_sec=clip_end_sec,
    )
    _capture_segment_screenshot(output_path=output_path, media_path=media_path, seek_sec=seek_sec)
    item["screenshot_url"] = build_segment_screenshot_public_path(vod_id, segment_id)
    print(f"info: screenshot generated item={segment_id} path={output_path}")


def transcribe_target(
    target: SegmentTarget,
    transcriber: WhisperTranscriber,
    *,
    config: TranscribePassConfig | None = None,
) -> TranscriptResult:
    vod_url = str(target.video.get("vod_url") or "").strip()
    if not vod_url:
        raise RuntimeError("missing vod_url")

    active_config = config or build_first_pass_config()
    start_sec, end_sec = _maybe_extend_window(target, active_config.extra_padding_sec)
    with tempfile.TemporaryDirectory(prefix="vod-segment-") as tmp_dir:
        media_path = download_segment_media(vod_url, start_sec, end_sec, Path(tmp_dir))
        try:
            maybe_generate_segment_screenshot(
                target,
                media_path=media_path,
                clip_start_sec=start_sec,
                clip_end_sec=end_sec,
            )
        except Exception as exc:
            segment_id = str(target.item.get("id") or "segment")
            print(f"warn: screenshot generation failed for {segment_id} ({exc})")
        if active_config.word_timestamps:
            result = transcribe_clip_second_pass(media_path, active_config, transcriber)
        else:
            result = transcribe_clip_first_pass(media_path, active_config, transcriber)
        result.source_text = result.source_text or result.text
        return result


def maybe_retranscribe_top_candidates(
    targets: list[SegmentTarget],
    first_pass_results: dict[str, TranscriptResult],
    transcriber: WhisperTranscriber,
    config: RetranscribeConfig,
    *,
    options: RunOptions | None = None,
) -> dict[str, TranscriptResult]:
    if not config.enabled:
        print("debug: second-pass retranscribe disabled")
        return first_pass_results

    _annotate_zscore_rank(targets)
    eligible: list[tuple[float, SegmentTarget]] = []
    for target in targets:
        label = str(target.item.get("id") or "")
        result = first_pass_results.get(label)
        if not result or not result.text:
            continue
        if not should_retranscribe_clip(target.item, result, config):
            continue
        priority = _score_retranscribe_priority(target.item, result, config)
        eligible.append((priority, target))

    selected = [target for _, target in sorted(eligible, key=lambda row: row[0], reverse=True)[: config.top_n]]
    if not selected:
        print("debug: second-pass retranscribe no targets selected")
        return first_pass_results

    second_pass_config = build_second_pass_config(options=options)
    for target in selected:
        label = f'{target.video.get("vod_id", "unknown")}:{target.item.get("id", "segment")}'
        item_id = str(target.item.get("id") or "")
        before = first_pass_results.get(item_id)
        print(
            "info: second-pass target "
            f"label={label} mode={config.selection_mode} rank={target.item.get('rank')} "
            f"zrank={target.item.get('_second_pass_zscore_rank')} profile={second_pass_config.preprocess_profile}"
        )
        try:
            after = transcribe_target(target, transcriber, config=second_pass_config)
        except Exception as exc:
            print(f"warn: second-pass failed for {label} ({exc})")
            continue

        if TERM_NORMALIZATION_ENABLED:
            normalized = normalize_transcript_terms(after.text, ACTIVE_TERM_DICTIONARY, TERM_NORMALIZATION_CONFIG)
            after.normalized_text = normalized.text
            after.text = normalized.text
            for row in normalized.replacements[:20]:
                print(
                    "debug: second-pass term normalization "
                    f"item={target.item.get('id')} category={row.category} "
                    f"from={row.original} to={row.replacement} sim={row.similarity:.1f}"
                )

        if after.text:
            first_pass_results[item_id] = after
            target.item["_second_pass_applied"] = True
            similarity = text_similarity(before.text if before else "", after.text)
            print(
                "info: second-pass transcript updated "
                f"label={label} similarity={similarity:.2f} "
                f"before_len={len((before.text if before else '').strip())} after_len={len(after.text.strip())}"
            )

    return first_pass_results


def download_segment_media(vod_url: str, start_sec: int, end_sec: int, work_dir: Path) -> Path:
    return tx_audio.download_segment_media(
        vod_url=vod_url,
        start_label=format_section_time(start_sec),
        end_label=format_section_time(end_sec),
        work_dir=work_dir,
        python_executable=sys.executable,
        timeout_sec=TRANSCRIPT_DOWNLOAD_TIMEOUT_SEC,
        video_required=SEGMENT_SCREENSHOT_GENERATION_ENABLED,
    )


def yt_dlp_available() -> bool:
    completed = subprocess.run(
        [sys.executable, "-m", "yt_dlp", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode == 0


def format_section_time(value: int) -> str:
    hours = value // 3600
    minutes = (value % 3600) // 60
    seconds = value % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


decide_headline_generation_strategy = hlp.decide_headline_generation_strategy
should_skip_headline_generation = hlp.should_skip_headline_generation


headline_confidence_label = hls.headline_confidence_label


TERM_NORMALIZATION_CONFIG = TermNormalizationConfig(
    similarity_threshold=TERM_NORMALIZATION_SIMILARITY,
    min_token_len=TERM_NORMALIZATION_MIN_TOKEN_LEN,
    min_term_len=TERM_NORMALIZATION_MIN_TERM_LEN,
)


if __name__ == "__main__":
    main()
