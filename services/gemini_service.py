import json
import logging
import os
import re
import time
from typing import Iterator

import requests

logger = logging.getLogger(__name__)

class ProviderError(ValueError):
    def __init__(self, code, status):
        self.code, self.status = code, status
        super().__init__(code)


GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
DEFAULT_MODEL = GEMINI_MODEL
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_STREAM_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent"

# Transient Gemini failures should not immediately surface as a lender-facing 502.
# 503 = temporary model unavailability/high demand; 429/5xx can also be transient.
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
MAX_RETRIES = min(2, max(0, int(os.getenv("GEMINI_MAX_RETRIES", "1"))))
BASE_RETRY_DELAY = max(0.5, float(os.getenv("GEMINI_RETRY_BASE_DELAY", "1.5")))

_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _api_key() -> str:
    """Return a Gemini API key, never an OAuth access token."""
    source = "GEMINI_API_KEY"
    value = os.getenv("GEMINI_API_KEY", "").strip()

    if not value:
        source = "GOOGLE_API_KEY"
        value = os.getenv("GOOGLE_API_KEY", "").strip()

    if not value:
        raise ProviderError("provider_configuration", 503)

    lowered = value.lower()
    if (
        value.startswith("ya29.")
        or value.startswith("1//")
        or lowered.startswith("bearer ")
    ):
        raise ProviderError("provider_configuration", 503)

    return value


def _model_name(model: str | None) -> str:
    value = (model or DEFAULT_MODEL).strip()
    if value.startswith("models/"):
        value = value[len("models/"):]
    if not re.fullmatch(r"[A-Za-z0-9._-]+", value):
        raise ProviderError("provider_configuration", 503)
    return value


def _retry_delay(response: requests.Response | None, attempt: int) -> float:
    """Return a bounded retry delay, honoring Retry-After when supplied."""
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return min(3.0, max(0.5, float(retry_after)))
            except ValueError:
                pass

    # 1.5s, 3s, 6s... with a small cap.
    return min(3.0, BASE_RETRY_DELAY * (2 ** attempt))


def _post_with_retries(
    url: str,
    *,
    headers: dict,
    json_payload: dict,
    timeout_seconds: int,
    stream: bool = False,
    params: dict | None = None,
) -> requests.Response:
    """POST to Gemini and retry temporary service/rate-limit failures."""

    for attempt in range(MAX_RETRIES + 1):
        try:
            response = requests.post(
                url,
                params=params,
                headers=headers,
                json=json_payload,
                stream=stream,
                allow_redirects=False,
                timeout=(4, min(timeout_seconds, 20)),
            )
        except requests.RequestException as exc:
            # Network-level failures are transient in many local/deployed cases.
            if attempt >= MAX_RETRIES:
                raise ProviderError("provider_timeout" if isinstance(exc, requests.Timeout) else "provider_unavailable", 504 if isinstance(exc, requests.Timeout) else 503) from None
            delay = _retry_delay(None, attempt)
            logger.warning(
                "Gemini network error on attempt %d/%d: %s; retrying in %.1fs",
                attempt + 1,
                MAX_RETRIES + 1,
                type(exc).__name__,
                delay,
            )
            time.sleep(delay)
            continue

        if 200 <= response.status_code < 300:
            return response

        if response.status_code not in RETRYABLE_STATUS_CODES or attempt >= MAX_RETRIES:
            status = response.status_code
            response.close()
            logger.warning("Gemini upstream HTTP %d", status)
            raise ProviderError("provider_configuration" if status in {400, 401, 403, 404} else "provider_unavailable", 503 if status in {400, 401, 403, 404, 429, 503} else 502)

        delay = _retry_delay(response, attempt)
        logger.warning(
            "Gemini returned HTTP %d on attempt %d/%d; retrying in %.1fs",
            response.status_code,
            attempt + 1,
            MAX_RETRIES + 1,
            delay,
        )
        response.close()
        time.sleep(delay)

    raise ProviderError("provider_unavailable", 503)


def _post_json(
    model: str,
    contents: list[dict],
    *,
    generation_config: dict | None = None,
    timeout_seconds: int = 30,
) -> dict:
    key = _api_key()
    payload: dict = {"contents": contents}
    if generation_config:
        payload["generationConfig"] = generation_config

    response = _post_with_retries(
        GEMINI_API_URL.format(model=_model_name(model)),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": key,
        },
        json_payload=payload,
        timeout_seconds=timeout_seconds,
    )

    try:
        return response.json()
    except ValueError as exc:
        raise ValueError("Gemini API returned invalid JSON") from exc
    finally:
        response.close()


def _extract_text(payload: dict) -> str:
    candidates = payload.get("candidates") or []
    if not candidates:
        return ""
    content = candidates[0].get("content") or {}
    parts = content.get("parts") or []
    return "".join(
        part.get("text", "")
        for part in parts
        if isinstance(part, dict) and not part.get("thought") and isinstance(part.get("text"), str)
    )


def stream_chat(messages, model=None, **kwargs) -> Iterator[str]:
    prompt = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        prompt.append(
            f"System: {content}" if role == "system" else
            f"Assistant: {content}" if role == "assistant" else
            f"User: {content}"
        )

    key = _api_key()
    timeout = int(kwargs.get("timeout_seconds", 15))
    response = _post_with_retries(
        GEMINI_STREAM_URL.format(model=_model_name(model)),
        params={"alt": "sse"},
        headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "x-goog-api-key": key,
        },
        json_payload={"contents": [{"parts": [{"text": "\n".join(prompt)}]}]},
        stream=True,
        timeout_seconds=timeout,
    )

    try:
        # Gemini sends UTF-8 SSE data. Keep the response as bytes and
        # decode each complete SSE line explicitly as UTF-8. Using
        # iter_lines(decode_unicode=True) lets requests guess the encoding
        # from the Content-Type and can turn characters such as ₹ into
        # mojibake (â‚¹).
        deadline = time.monotonic() + 35
        finished = False
        for raw_line in response.iter_lines(decode_unicode=False):
            if time.monotonic() > deadline:
                raise ProviderError("provider_timeout", 504)
            if not raw_line:
                continue
            try:
                line = raw_line.decode("utf-8").strip()
            except UnicodeDecodeError:
                # A malformed/incomplete line should not crash the stream.
                line = raw_line.decode("utf-8", errors="replace").strip()

            if not line.startswith("data:"):
                continue
            line = line[5:].strip()
            if line == "[DONE]":
                finished = True
                break
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict) or payload.get("error"):
                raise ProviderError("provider_response", 502)
            text = _extract_text(payload)
            if text:
                yield text
            candidates = payload.get("candidates") or []
            if candidates and candidates[0].get("finishReason"):
                if candidates[0]["finishReason"] not in {"STOP", "MAX_TOKENS"}:
                    raise ProviderError("provider_response", 502)
                finished = True
                break
        if not finished:
            raise ProviderError("provider_response", 502)
    finally:
        response.close()


def generate_json(
    system_instruction: str,
    user_payload: dict,
    model: str = None,
    timeout_seconds: int = 30,
) -> dict:
    prompt = (
        f"{system_instruction}\n\n"
        f"Input data (JSON):\n{json.dumps(user_payload, ensure_ascii=False, default=str)}\n\n"
        "Respond with ONLY a single JSON object. No markdown fences, no preamble."
    )

    try:
        payload = _post_json(
            model or DEFAULT_MODEL,
            [{"role": "user", "parts": [{"text": prompt}]}],
            generation_config={
                "responseMimeType": "application/json",
                "temperature": 0.2,
            },
            timeout_seconds=timeout_seconds,
        )
        text = _extract_text(payload).strip()
    except Exception as exc:
        raise ValueError("Gemini call failed") from None

    if not text:
        raise ValueError("Gemini returned an empty response")

    cleaned = _JSON_FENCE_RE.sub("", text).strip()
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning("Gemini returned non-JSON response")
        raise ValueError("Gemini returned a malformed response") from exc
