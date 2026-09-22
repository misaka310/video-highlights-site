from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib import error, request

import headline_pipeline as hlp
import headline_scoring as hls


@dataclass(frozen=True)
class HeadlineGenerationSettings:
    headline_source_config: dict[str, Any]
    headline_max_attempts: int
    gemini_timeout_sec: int
    groq_timeout_sec: int
    groq_responses_url: str
    nvidia_timeout_sec: int
    nvidia_api_url: str
    local_headline_model: str


@dataclass(frozen=True)
class HeadlineGenerationCallbacks:
    build_headline_source_text: Callable[..., str]
    build_remote_headline_prompt: Callable[..., tuple[str, str]]
    parse_headline_candidates_output: Callable[..., list[Any]]
    choose_best_headline: Callable[..., Any]
    ensure_usable_remote_headline: Callable[..., str]
    score_headline_candidate_with_source: Callable[..., Any]
    build_headline_response_schema: Callable[..., dict[str, Any]]
    build_extractive_headline: Callable[..., str]
    validate_headline_result: Callable[..., Any]
    choose_best_remote_headline: Callable[..., tuple[Any, dict[str, Any]]]
    make_headline_result: Callable[..., Any]
    is_publishable_headline: Callable[..., bool] | None = None


HEADLINE_PROVIDER_ERROR_MAX_RETRIES = 3
HEADLINE_RETRY_FALLBACK_BASE_SEC = 2.0
HEADLINE_RETRY_BUFFER_SEC = 0.5
HEADLINE_RETRY_MAX_WAIT_SEC = 60.0
_GROQ_RETRY_AFTER_RE = re.compile(
    r"please try again in\s+([0-9]+(?:\.[0-9]+)?)s",
    re.IGNORECASE,
)


def _parse_retry_after_value(value: Any) -> float | None:
    raw = str(value or "").strip().lower()
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*s?", raw)
    if not match:
        return None
    return min(max(0.0, float(match.group(1))), HEADLINE_RETRY_MAX_WAIT_SEC)


def extract_response_output_text(payload: dict[str, Any]) -> str:
    output_text = str(payload.get("output_text") or "").strip()
    if output_text:
        return output_text

    parts: list[str] = []
    for output in payload.get("output") or []:
        if not isinstance(output, dict):
            continue
        for content in output.get("content") or []:
            if not isinstance(content, dict) or content.get("type") != "output_text":
                continue
            value = str(content.get("text") or "").strip()
            if value:
                parts.append(value)
    return " ".join(parts).strip()


def extract_gemini_output_text(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    for candidate in payload.get("candidates") or []:
        if not isinstance(candidate, dict):
            continue
        content = candidate.get("content") or {}
        if not isinstance(content, dict):
            continue
        for part in content.get("parts") or []:
            if not isinstance(part, dict):
                continue
            value = str(part.get("text") or "").strip()
            if value:
                parts.append(value)
    return " ".join(parts).strip()


def read_http_error_detail(exc: error.HTTPError) -> str:
    if not hasattr(exc, "read"):
        return ""
    try:
        return exc.read().decode("utf-8", errors="ignore")
    except Exception:
        return ""


def classify_gemini_http_error(code: int, detail: str) -> tuple[str, bool]:
    payload_status = ""
    payload_message = ""
    try:
        payload = json.loads(detail) if detail else {}
    except json.JSONDecodeError:
        payload = {}
    if isinstance(payload, dict):
        error_payload = payload.get("error") or {}
        if isinstance(error_payload, dict):
            payload_status = str(error_payload.get("status") or "").strip()
            payload_message = str(error_payload.get("message") or "").strip()

    detail_text = " ".join(part for part in (payload_status, payload_message, detail[:200]) if part).strip()
    normalized = detail_text.lower()
    retryable = code in {408, 409, 429, 500, 502, 503, 504}
    if code == 429 or "resource_exhausted" in normalized:
        return ("RESOURCE_EXHAUSTED / HTTP 429", True)
    if "unavailable" in normalized or code == 503:
        return (f"temporary unavailable (HTTP {code})", True)
    if "deadline_exceeded" in normalized or "timeout" in normalized or "timed out" in normalized:
        return (f"request timed out (HTTP {code})", True)
    if retryable:
        return (f"temporary API error (HTTP {code})", True)
    message = payload_message or detail[:200] or f"HTTP {code}"
    return (f"HTTP {code}: {message}", False)


def is_temporary_transport_error(reason: str) -> bool:
    normalized = str(reason or "").lower()
    return any(
        keyword in normalized
        for keyword in (
            "timed out",
            "timeout",
            "temporary",
            "temporarily unavailable",
            "connection reset",
            "connection aborted",
            "connection refused",
            "service unavailable",
        )
    )


def resolve_http_retry_after_seconds(exc: Any, detail: str) -> float | None:
    headers = getattr(exc, "headers", None)
    if headers is None:
        response = getattr(exc, "response", None)
        headers = getattr(response, "headers", None)
    if headers is not None:
        for name in ("Retry-After", "X-RateLimit-Reset-Tokens"):
            parsed = _parse_retry_after_value(headers.get(name))
            if parsed is not None:
                return parsed
    match = _GROQ_RETRY_AFTER_RE.search(str(detail or ""))
    if match:
        return min(max(0.0, float(match.group(1))), HEADLINE_RETRY_MAX_WAIT_SEC)
    return None


class HeadlineProviderError(RuntimeError):
    def __init__(
        self,
        provider: str,
        reason: str,
        *,
        retryable: bool = False,
        retry_after_sec: float | None = None,
    ) -> None:
        self.provider = provider
        self.reason = reason
        self.retryable = retryable
        self.retry_after_sec = retry_after_sec
        super().__init__(f"{provider} {reason}")


class GeminiHeadlineGenerator:
    def __init__(
        self,
        api_key: str,
        model: str,
        api_url: str,
        *,
        settings: HeadlineGenerationSettings,
        callbacks: HeadlineGenerationCallbacks,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.api_url = api_url
        self.settings = settings
        self.callbacks = callbacks

    def generate(
        self,
        *,
        video_title: str,
        start_time: str,
        end_time: str,
        transcript: str,
        prepared_transcript: str | None = None,
        source_validation: Any | None = None,
    ) -> Any:
        source_text = prepared_transcript or self.callbacks.build_headline_source_text(
            transcript,
            self.settings.headline_source_config,
        )
        instructions, prompt = self.callbacks.build_remote_headline_prompt(
            provider="gemini",
            video_title=video_title,
            start_time=start_time,
            end_time=end_time,
            transcript=transcript,
            prepared_transcript=source_text,
        )
        raw_output = str(self._request_headline(instructions=instructions, prompt=prompt) or "").strip()
        candidates = self.callbacks.parse_headline_candidates_output(raw_output, source_text)
        print(f"debug: llm candidates provider=Gemini count={len(candidates)} items={[c.headline for c in candidates]}")
        chosen = self.callbacks.choose_best_headline(candidates, source_text, config={"source_validation": source_validation})
        if not chosen.can_publish or chosen.headline.upper() == "SKIP":
            raise HeadlineProviderError("Gemini", f"model returned skip candidate: {chosen.reason}")
        finalized = self.callbacks.ensure_usable_remote_headline(
            text=chosen.headline,
            video_title=video_title,
            provider="Gemini",
            transcript=source_text,
        )
        chosen_score = self.callbacks.score_headline_candidate_with_source(
            chosen,
            source_text,
            config={"source_validation": source_validation},
        )
        confidence = hls.headline_confidence_label(
            score_total=chosen_score.total,
            candidate_confidence=chosen.confidence,
            penalty=hlp.compute_source_quality_penalty(source_validation) if source_validation else 0.0,
        )
        return self.callbacks.make_headline_result(
            text=finalized,
            model=self.model,
            source="gemini",
            generation_mode=chosen.generation_mode or "llm_ranked",
            confidence=confidence,
            notes=chosen.notes,
            metadata={
                "provider": "Gemini",
                "provider_candidates": [
                    {
                        "headline": candidate.headline,
                        "confidence": round(candidate.confidence, 3),
                        "reason": candidate.reason,
                        "generation_mode": candidate.generation_mode,
                        "can_publish": candidate.can_publish,
                    }
                    for candidate in candidates
                ],
                "provider_selected": {
                    "headline": chosen.headline,
                    "score_total": round(chosen_score.total, 3),
                    "reason": chosen.reason,
                    "generation_mode": chosen.generation_mode,
                    "used_terms": chosen.used_terms,
                },
            },
        )

    def _request_headline(self, *, instructions: str, prompt: str) -> str:
        body = {
            "systemInstruction": {
                "parts": [{"text": instructions}],
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
                "responseJsonSchema": self.callbacks.build_headline_response_schema(),
            },
        }
        endpoint = f"{self.api_url.format(model=self.model)}?key={self.api_key}"
        req = request.Request(
            endpoint,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.settings.gemini_timeout_sec) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = read_http_error_detail(exc)
            reason, retryable = classify_gemini_http_error(exc.code, detail)
            raise HeadlineProviderError("Gemini", reason, retryable=retryable) from exc
        except error.URLError as exc:
            reason = str(exc.reason)
            retryable = is_temporary_transport_error(reason)
            label = "request timed out" if retryable and "tim" in reason.lower() else f"request failed: {reason}"
            raise HeadlineProviderError("Gemini", label, retryable=retryable) from exc
        except TimeoutError as exc:
            raise HeadlineProviderError("Gemini", "request timed out", retryable=True) from exc
        return extract_gemini_output_text(payload)


class GroqHeadlineGenerator:
    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        settings: HeadlineGenerationSettings,
        callbacks: HeadlineGenerationCallbacks,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.settings = settings
        self.callbacks = callbacks

    def generate(
        self,
        *,
        video_title: str,
        start_time: str,
        end_time: str,
        transcript: str,
        prepared_transcript: str | None = None,
        source_validation: Any | None = None,
    ) -> Any:
        source_text = prepared_transcript or self.callbacks.build_headline_source_text(
            transcript,
            self.settings.headline_source_config,
        )
        instructions, prompt = self.callbacks.build_remote_headline_prompt(
            provider="groq",
            video_title=video_title,
            start_time=start_time,
            end_time=end_time,
            transcript=transcript,
            prepared_transcript=source_text,
        )
        raw_output = str(self._request_headline(instructions=instructions, prompt=prompt) or "").strip()
        candidates = self.callbacks.parse_headline_candidates_output(raw_output, source_text)
        print(f"debug: llm candidates provider=Groq count={len(candidates)} items={[c.headline for c in candidates]}")
        chosen = self.callbacks.choose_best_headline(candidates, source_text, config={"source_validation": source_validation})
        if not chosen.can_publish or chosen.headline.upper() == "SKIP":
            raise HeadlineProviderError("Groq", f"model returned skip candidate: {chosen.reason}")
        finalized = self.callbacks.ensure_usable_remote_headline(
            text=chosen.headline,
            video_title=video_title,
            provider="Groq",
            transcript=source_text,
        )
        chosen_score = self.callbacks.score_headline_candidate_with_source(
            chosen,
            source_text,
            config={"source_validation": source_validation},
        )
        confidence = hls.headline_confidence_label(
            score_total=chosen_score.total,
            candidate_confidence=chosen.confidence,
            penalty=hlp.compute_source_quality_penalty(source_validation) if source_validation else 0.0,
        )
        return self.callbacks.make_headline_result(
            text=finalized,
            model=self.model,
            source="groq",
            generation_mode=chosen.generation_mode or "llm_ranked",
            confidence=confidence,
            notes=chosen.notes,
            metadata={
                "provider": "Groq",
                "provider_candidates": [
                    {
                        "headline": candidate.headline,
                        "confidence": round(candidate.confidence, 3),
                        "reason": candidate.reason,
                        "generation_mode": candidate.generation_mode,
                        "can_publish": candidate.can_publish,
                    }
                    for candidate in candidates
                ],
                "provider_selected": {
                    "headline": chosen.headline,
                    "score_total": round(chosen_score.total, 3),
                    "reason": chosen.reason,
                    "generation_mode": chosen.generation_mode,
                    "used_terms": chosen.used_terms,
                },
            },
        )

    def _request_headline(self, *, instructions: str, prompt: str) -> str:
        try:
            import groq as groq_sdk
        except ImportError as exc:
            raise HeadlineProviderError("Groq", "official Groq SDK is not installed") from exc

        client = groq_sdk.Groq(
            api_key=self.api_key,
            timeout=float(self.settings.groq_timeout_sec),
        )
        request_options: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
        }
        if self.model.startswith("qwen/"):
            request_options["reasoning_effort"] = "none"

        try:
            completion = client.chat.completions.create(**request_options)
        except Exception as exc:
            status_code = int(getattr(exc, "status_code", 0) or 0)
            body = getattr(exc, "body", None)
            if isinstance(body, (dict, list)):
                detail = json.dumps(body, ensure_ascii=False)
            else:
                detail = str(body or exc)
            retryable = status_code == 429 or 500 <= status_code < 600
            retry_after_sec = resolve_http_retry_after_seconds(exc, detail) if retryable else None
            if status_code:
                reason = f"HTTP {status_code}: {detail[:300] or 'request failed'}"
            else:
                error_name = type(exc).__name__.lower()
                retryable = "timeout" in error_name or "connection" in error_name
                reason = "request timed out" if "timeout" in error_name else f"request failed: {detail[:300]}"
            raise HeadlineProviderError(
                "Groq",
                reason,
                retryable=retryable,
                retry_after_sec=retry_after_sec,
            ) from exc

        choices = list(getattr(completion, "choices", None) or [])
        if not choices:
            raise HeadlineProviderError("Groq", "response did not include a choice")
        message = getattr(choices[0], "message", None)
        content = str(getattr(message, "content", "") or "").strip()
        if not content:
            raise HeadlineProviderError("Groq", "response did not include message content")
        return content


class NvidiaHeadlineGenerator:
    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        settings: HeadlineGenerationSettings,
        callbacks: HeadlineGenerationCallbacks,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.settings = settings
        self.callbacks = callbacks

    def generate(
        self,
        *,
        video_title: str,
        start_time: str,
        end_time: str,
        transcript: str,
        prepared_transcript: str | None = None,
        source_validation: Any | None = None,
    ) -> Any:
        source_text = prepared_transcript or self.callbacks.build_headline_source_text(
            transcript,
            self.settings.headline_source_config,
        )
        instructions, prompt = self.callbacks.build_remote_headline_prompt(
            provider="nvidia",
            video_title=video_title,
            start_time=start_time,
            end_time=end_time,
            transcript=transcript,
            prepared_transcript=source_text,
        )
        raw_output = str(self._request_headline(instructions=instructions, prompt=prompt) or "").strip()
        candidates = self.callbacks.parse_headline_candidates_output(raw_output, source_text)
        print(f"debug: llm candidates provider=NVIDIA count={len(candidates)} items={[c.headline for c in candidates]}")
        chosen = self.callbacks.choose_best_headline(candidates, source_text, config={"source_validation": source_validation})
        if not chosen.can_publish or chosen.headline.upper() == "SKIP":
            raise HeadlineProviderError("NVIDIA", f"model returned skip candidate: {chosen.reason}")
        finalized = self.callbacks.ensure_usable_remote_headline(
            text=chosen.headline,
            video_title=video_title,
            provider="NVIDIA",
            transcript=source_text,
        )
        chosen_score = self.callbacks.score_headline_candidate_with_source(
            chosen,
            source_text,
            config={"source_validation": source_validation},
        )
        confidence = hls.headline_confidence_label(
            score_total=chosen_score.total,
            candidate_confidence=chosen.confidence,
            penalty=hlp.compute_source_quality_penalty(source_validation) if source_validation else 0.0,
        )
        return self.callbacks.make_headline_result(
            text=finalized,
            model=self.model,
            source="nvidia",
            generation_mode=chosen.generation_mode or "llm_ranked",
            confidence=confidence,
            notes=chosen.notes,
            metadata={
                "provider": "NVIDIA",
                "provider_candidates": [
                    {
                        "headline": candidate.headline,
                        "confidence": round(candidate.confidence, 3),
                        "reason": candidate.reason,
                        "generation_mode": candidate.generation_mode,
                        "can_publish": candidate.can_publish,
                    }
                    for candidate in candidates
                ],
                "provider_selected": {
                    "headline": chosen.headline,
                    "score_total": round(chosen_score.total, 3),
                    "reason": chosen.reason,
                    "generation_mode": chosen.generation_mode,
                    "used_terms": chosen.used_terms,
                },
            },
        )

    def _request_headline(self, *, instructions: str, prompt: str) -> str:
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
        }
        req = request.Request(
            self.settings.nvidia_api_url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.settings.nvidia_timeout_sec) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = read_http_error_detail(exc)
            raise HeadlineProviderError("NVIDIA", f"HTTP {exc.code}: {detail[:300] or 'request failed'}") from exc
        except error.URLError as exc:
            reason = str(exc.reason)
            retryable = is_temporary_transport_error(reason)
            label = "request timed out" if retryable and "tim" in reason.lower() else f"request failed: {reason}"
            raise HeadlineProviderError("NVIDIA", label, retryable=retryable) from exc
        except TimeoutError as exc:
            raise HeadlineProviderError("NVIDIA", "request timed out", retryable=True) from exc
        except ValueError as exc:
            raise HeadlineProviderError("NVIDIA", "invalid JSON response") from exc

        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise HeadlineProviderError("NVIDIA", "invalid response: missing choices")
        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise HeadlineProviderError("NVIDIA", "invalid response: malformed choice")
        message = first_choice.get("message")
        if not isinstance(message, dict):
            raise HeadlineProviderError("NVIDIA", "invalid response: missing message")
        content = message.get("content")
        if isinstance(content, str):
            text = content.strip()
            if text:
                return text
        if isinstance(content, list):
            parts: list[str] = []
            for row in content:
                if isinstance(row, dict):
                    value = row.get("text")
                    if isinstance(value, str) and value.strip():
                        parts.append(value.strip())
            text = "\n".join(parts).strip()
            if text:
                return text
        raise HeadlineProviderError("NVIDIA", "invalid response: empty message content")


class ExtractiveHeadlineGenerator:
    def __init__(
        self,
        *,
        settings: HeadlineGenerationSettings,
        callbacks: HeadlineGenerationCallbacks,
    ) -> None:
        self.settings = settings
        self.callbacks = callbacks

    def generate(
        self,
        *,
        video_title: str,
        start_time: str,
        end_time: str,
        transcript: str,
        prepared_transcript: str | None = None,
        source_validation: Any | None = None,
    ) -> Any:
        del start_time, end_time, source_validation
        source_text = prepared_transcript or self.callbacks.build_headline_source_text(
            transcript,
            self.settings.headline_source_config,
        )
        headline = self.callbacks.build_extractive_headline(transcript=source_text, video_title=video_title)
        return self.callbacks.make_headline_result(
            text=headline,
            model=self.settings.local_headline_model,
            source="extractive",
            generation_mode="fallback_extractive",
            confidence="low",
            notes="extractive_fallback",
        )


class ResilientHeadlineGenerator:
    def __init__(
        self,
        gemini: GeminiHeadlineGenerator | None,
        groq: GroqHeadlineGenerator | None,
        nvidia: NvidiaHeadlineGenerator | None,
        fallback: ExtractiveHeadlineGenerator,
        *,
        settings: HeadlineGenerationSettings,
        callbacks: HeadlineGenerationCallbacks,
    ) -> None:
        self.gemini = gemini
        self.groq = groq
        self.nvidia = nvidia
        self.fallback = fallback
        self.settings = settings
        self.callbacks = callbacks

    def _collect_provider_candidates(
        self,
        *,
        provider_name: str,
        provider: Any,
        video_title: str,
        start_time: str,
        end_time: str,
        transcript: str,
        prepared_transcript: str | None = None,
        source_validation: Any | None = None,
    ) -> list[Any]:
        collected: list[Any] = []
        attempt = 1
        provider_error_retries = 0
        while attempt <= self.settings.headline_max_attempts:
            context = hlp.HeadlineLogContext(
                provider=provider_name,
                attempt=attempt,
                max_attempts=self.settings.headline_max_attempts,
            )
            try:
                result = provider.generate(
                    video_title=video_title,
                    start_time=start_time,
                    end_time=end_time,
                    transcript=transcript,
                    prepared_transcript=prepared_transcript,
                    source_validation=source_validation,
                )
            except Exception as exc:
                reason = exc.reason if isinstance(exc, HeadlineProviderError) else str(exc)
                hlp.log_provider_error(context=context, reason=reason, logger=print)
                retryable = isinstance(exc, HeadlineProviderError) and exc.retryable
                if retryable and provider_error_retries < HEADLINE_PROVIDER_ERROR_MAX_RETRIES:
                    base_wait = (
                        exc.retry_after_sec
                        if exc.retry_after_sec is not None
                        else HEADLINE_RETRY_FALLBACK_BASE_SEC * (2 ** provider_error_retries)
                    )
                    wait_sec = min(
                        HEADLINE_RETRY_MAX_WAIT_SEC,
                        max(0.0, base_wait) + HEADLINE_RETRY_BUFFER_SEC,
                    )
                    provider_error_retries += 1
                    print(
                        "info: headline provider retry delay "
                        f"provider={provider_name} attempt={attempt}/{self.settings.headline_max_attempts} "
                        f"retry={provider_error_retries}/{HEADLINE_PROVIDER_ERROR_MAX_RETRIES} "
                        f"wait_sec={wait_sec:.2f}"
                    )
                    time.sleep(wait_sec)
                    continue
                if retryable:
                    print(
                        "warn: headline provider retry budget exhausted "
                        f"provider={provider_name} retries={provider_error_retries}"
                    )
                    break
                attempt += 1
                continue

            provider_error_retries = 0
            validation = self.callbacks.validate_headline_result(result.text, transcript=transcript)
            metadata = dict(result.metadata or {})
            metadata["provider"] = provider_name
            metadata["attempt"] = attempt
            metadata["attempt_validation"] = {
                "hard_issues": list(validation.hard_issues),
                "soft_issues": list(validation.soft_issues),
                "flags": list(validation.info_flags),
            }
            result.metadata = metadata
            hlp.log_provider_attempt(
                context=context,
                headline=result.text,
                validation_result=validation,
                logger=print,
            )
            publishable = self._is_publishable(result.text, prepared_transcript or transcript)
            metadata["publishable"] = publishable
            collected.append(result)
            if publishable and not hlp.should_retry_attempt(validation):
                break
            attempt += 1
        return collected

    def _is_publishable(self, headline: str, source_text: str) -> bool:
        check = getattr(self.callbacks, "is_publishable_headline", None)
        return check is None or bool(check(headline, source_text=source_text))

    def generate(
        self,
        *,
        video_title: str,
        start_time: str,
        end_time: str,
        transcript: str,
        prepared_transcript: str | None = None,
        source_validation: Any | None = None,
    ) -> Any:
        candidates: list[Any] = []

        if self.gemini is not None:
            gemini_candidates = self._collect_provider_candidates(
                provider_name="Gemini",
                provider=self.gemini,
                video_title=video_title,
                start_time=start_time,
                end_time=end_time,
                transcript=transcript,
                prepared_transcript=prepared_transcript,
                source_validation=source_validation,
            )
            candidates.extend(gemini_candidates)
            if not gemini_candidates:
                if self.groq is not None or self.nvidia is not None:
                    print("warn: headline Gemini failed; trying other providers")
                else:
                    print("warn: headline Gemini failed; using local fallback")

        if self.groq is not None:
            groq_candidates = self._collect_provider_candidates(
                provider_name="Groq",
                provider=self.groq,
                video_title=video_title,
                start_time=start_time,
                end_time=end_time,
                transcript=transcript,
                prepared_transcript=prepared_transcript,
                source_validation=source_validation,
            )
            candidates.extend(groq_candidates)
            if not groq_candidates:
                if self.nvidia is not None:
                    print("warn: headline Groq failed; trying NVIDIA")
                elif candidates:
                    print("warn: headline Groq failed after another provider candidate")
                else:
                    print("warn: headline Groq failed; using local fallback")

        if self.nvidia is not None:
            nvidia_candidates = self._collect_provider_candidates(
                provider_name="NVIDIA",
                provider=self.nvidia,
                video_title=video_title,
                start_time=start_time,
                end_time=end_time,
                transcript=transcript,
                prepared_transcript=prepared_transcript,
                source_validation=source_validation,
            )
            candidates.extend(nvidia_candidates)
            if not nvidia_candidates:
                if candidates:
                    print("warn: headline NVIDIA failed after other provider candidate")
                else:
                    print("warn: headline NVIDIA failed; using local fallback")

        if candidates:
            publishable = [item for item in candidates if (item.metadata or {}).get("publishable", True)]
            pool = publishable or candidates
            selected, comparison = self.callbacks.choose_best_remote_headline(pool, transcript=transcript)
            selected_metadata = dict(selected.metadata or {})
            selected_metadata["comparison"] = comparison
            selected.metadata = selected_metadata
            if len(candidates) > 1:
                print(f"info: compared remote headlines and selected {selected.source}")
            return selected

        return self.fallback.generate(
            video_title=video_title,
            start_time=start_time,
            end_time=end_time,
            transcript=transcript,
            prepared_transcript=prepared_transcript,
            source_validation=source_validation,
        )


def build_headline_generator(
    *,
    gemini_api_key: str,
    gemini_model: str,
    gemini_api_url: str,
    groq_api_key: str,
    groq_model: str,
    nvidia_api_key: str,
    nvidia_model: str,
    settings: HeadlineGenerationSettings,
    callbacks: HeadlineGenerationCallbacks,
) -> ResilientHeadlineGenerator:
    gemini = (
        GeminiHeadlineGenerator(
            gemini_api_key,
            gemini_model,
            gemini_api_url,
            settings=settings,
            callbacks=callbacks,
        )
        if gemini_api_key
        else None
    )
    groq = (
        GroqHeadlineGenerator(
            groq_api_key,
            groq_model,
            settings=settings,
            callbacks=callbacks,
        )
        if groq_api_key and groq_model
        else None
    )
    nvidia = (
        NvidiaHeadlineGenerator(
            nvidia_api_key,
            nvidia_model,
            settings=settings,
            callbacks=callbacks,
        )
        if nvidia_api_key and nvidia_model
        else None
    )
    if nvidia is not None:
        print(f"info: headline provider NVIDIA enabled model={nvidia_model}")
    return ResilientHeadlineGenerator(
        gemini=gemini,
        groq=groq,
        nvidia=nvidia,
        fallback=ExtractiveHeadlineGenerator(settings=settings, callbacks=callbacks),
        settings=settings,
        callbacks=callbacks,
    )
