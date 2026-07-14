"""OpenRouter client + strict validation for Gemma rubric reviews.

Given a dossier (see ``pipeline.dossier``) and the rubric system prompt
(``spec/rubric.md``), call a Gemma-class model via the OpenRouter chat
completions API and return a validated :class:`ReviewResult`.

Design priorities, in order: **don't waste paid calls**, **never write an
invalid verdict as if it were valid**, and **be deterministic**. The model
output is extracted from possibly-messy text, validated against the rubric
contract *and* the project's category taxonomy, and any deviation raises
:class:`ReviewValidationError` (recorded as an error result, not a silent pass).

No network happens at import time and no key is read here — the caller supplies
the key, so the module is importable and unit-testable offline.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field

import requests

from . import categorize

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "google/gemma-2-9b-it"

# Identifies this app to OpenRouter (optional but polite / good for dashboards).
_REFERER = "https://matthewdeanmartin.github.io/youtuberfinder/"
_TITLE = "tech-youtubers rubric review"

VALID_DECISIONS = {"include", "review", "exclude"}
VALID_CONFIDENCE = {"high", "medium", "low"}
VALID_HARD_FAILS = {"H1", "H2", "H3", "H4", "H5"}
CRITERIA_KEYS = ("A", "B", "C", "D", "E")
VALID_CATEGORIES = set(categorize.CATEGORY_SORTORDER)

_MAX_HASHTAGS = 8
_HASHTAG_RE = re.compile(r"^#\w[\w-]*$")
# A permissive BCP-47-ish base tag check ("en", "pt-br"); we only need the
# language label to be plausible, not canonical.
_LANG_RE = re.compile(r"^[a-z]{2,3}(-[a-z0-9]{2,8})?$", re.IGNORECASE)


class ReviewValidationError(ValueError):
    """Raised when a model reply does not satisfy the rubric contract."""


@dataclass(frozen=True)
class ReviewResult:
    decision: str
    score: int
    hard_fail: str | None
    criteria: dict
    confidence: str
    reason: str
    language: str | None = None
    category: str | None = None
    subcategory: str | None = None
    hashtags: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def build_messages(rubric: str, dossier: str) -> list[dict]:
    """System prompt = the rubric; user prompt = the creator's dossier."""
    return [
        {"role": "system", "content": rubric.strip()},
        {"role": "user", "content": dossier.strip()},
    ]


def extract_json(text: str) -> dict:
    """Pull the first balanced JSON object out of a model reply.

    Small models often wrap JSON in prose or `````json`` fences; this scans
    for the first ``{`` and returns the substring through its matching ``}``.
    Raises :class:`ReviewValidationError` if no parseable object is found.
    """
    if not text:
        raise ReviewValidationError("empty model response")
    start = text.find("{")
    if start == -1:
        raise ReviewValidationError("no JSON object in model response")
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                blob = text[start : i + 1]
                try:
                    return json.loads(blob)
                except json.JSONDecodeError as exc:
                    raise ReviewValidationError(f"invalid JSON: {exc}") from exc
    raise ReviewValidationError("unbalanced JSON object in model response")


def _as_int(value, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ReviewValidationError(f"{name} must be an integer, got {value!r}")
    return value


def validate_payload(obj: dict) -> ReviewResult:
    """Validate a parsed model object against the rubric + taxonomy contract.

    Enforces every invariant the rubric states, then the enrichment fields the
    directory needs (language/category/subcategory/hashtags). Categorization
    fields are only required when the decision is not ``exclude``.
    """
    if not isinstance(obj, dict):
        raise ReviewValidationError("model output is not a JSON object")

    decision = obj.get("decision")
    if decision not in VALID_DECISIONS:
        raise ReviewValidationError(f"decision must be one of {sorted(VALID_DECISIONS)}, got {decision!r}")

    confidence = obj.get("confidence")
    if confidence not in VALID_CONFIDENCE:
        raise ReviewValidationError(f"confidence must be one of {sorted(VALID_CONFIDENCE)}, got {confidence!r}")

    criteria_raw = obj.get("criteria")
    if not isinstance(criteria_raw, dict) or set(criteria_raw) != set(CRITERIA_KEYS):
        raise ReviewValidationError(f"criteria must have exactly keys {list(CRITERIA_KEYS)}")
    criteria = {}
    for key in CRITERIA_KEYS:
        val = _as_int(criteria_raw[key], f"criteria.{key}")
        if not 0 <= val <= 2:
            raise ReviewValidationError(f"criteria.{key} must be 0..2, got {val}")
        criteria[key] = val

    score = _as_int(obj.get("score"), "score")
    if score != sum(criteria.values()):
        raise ReviewValidationError(f"score {score} != sum(criteria) {sum(criteria.values())}")

    hard_fail = obj.get("hard_fail")
    if hard_fail is not None and hard_fail not in VALID_HARD_FAILS:
        raise ReviewValidationError(f"hard_fail must be null or one of {sorted(VALID_HARD_FAILS)}, got {hard_fail!r}")
    if hard_fail is not None and decision != "exclude":
        raise ReviewValidationError("hard_fail is set but decision is not 'exclude'")

    reason = obj.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ReviewValidationError("reason must be a non-empty string")
    if "\n" in reason:
        raise ReviewValidationError("reason must be a single line")

    language = obj.get("language")
    category = obj.get("category")
    subcategory = obj.get("subcategory")
    hashtags = obj.get("hashtags", [])

    if decision == "exclude":
        # Don't categorize what we won't list; normalise to empty.
        language = language if isinstance(language, str) else None
        category = subcategory = None
        hashtags = []
    else:
        if not (isinstance(language, str) and _LANG_RE.match(language)):
            raise ReviewValidationError(f"language must be a BCP-47 base tag for an included creator, got {language!r}")
        if category not in VALID_CATEGORIES:
            raise ReviewValidationError(f"category must be one of {sorted(VALID_CATEGORIES)}, got {category!r}")
        if not isinstance(subcategory, str) or not subcategory.strip():
            raise ReviewValidationError("subcategory must be a non-empty string for an included creator")
        if len(subcategory) > 40:
            raise ReviewValidationError("subcategory must be <= 40 chars")
        if not isinstance(hashtags, list) or len(hashtags) > _MAX_HASHTAGS:
            raise ReviewValidationError(f"hashtags must be a list of <= {_MAX_HASHTAGS} items")
        for tag in hashtags:
            if not isinstance(tag, str) or not _HASHTAG_RE.match(tag):
                raise ReviewValidationError(f"each hashtag must look like '#tag', got {tag!r}")

    return ReviewResult(
        decision=decision,
        score=score,
        hard_fail=hard_fail,
        criteria=criteria,
        confidence=confidence,
        reason=reason.strip(),
        language=language,
        category=category,
        subcategory=subcategory.strip() if isinstance(subcategory, str) else None,
        hashtags=list(hashtags),
    )


def call_openrouter(
    messages: list[dict],
    api_key: str,
    *,
    model: str = DEFAULT_MODEL,
    timeout: float = 60.0,
    temperature: float = 0.0,
    session: requests.Session | None = None,
) -> str:
    """One chat-completion call. Returns the assistant message content string.

    Requests JSON output (``response_format``) and temperature 0 for
    determinism. Raises for HTTP errors so the caller's retry logic can act.
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": _REFERER,
        "X-Title": _TITLE,
    }
    body = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }
    http = session or requests
    response = http.post(OPENROUTER_URL, headers=headers, json=body, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ReviewValidationError(f"unexpected OpenRouter response shape: {data}") from exc


def review_one(
    rubric: str,
    dossier: str,
    api_key: str,
    *,
    model: str = DEFAULT_MODEL,
    retries: int = 2,
    backoff: float = 2.0,
    session: requests.Session | None = None,
    sleeper=time.sleep,
) -> ReviewResult:
    """Review a single dossier: call, extract JSON, validate.

    Retries only **transient** failures (HTTP/timeout/JSON-shape) with linear
    backoff. A :class:`ReviewValidationError` from the model's *content* is not
    retried — re-asking rarely fixes a confidently malformed reply and would
    just burn credits; the caller records it as an error and moves on.
    """
    messages = build_messages(rubric, dossier)
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            content = call_openrouter(messages, api_key, model=model, session=session)
        except (requests.RequestException, ReviewValidationError) as exc:
            # ReviewValidationError here only comes from a bad transport-level
            # response shape (not content), so it is worth retrying.
            last_exc = exc
            if attempt < retries:
                sleeper(backoff * (attempt + 1))
                continue
            raise
        # Content-level validation: do NOT retry — surface to the caller.
        return validate_payload(extract_json(content))
    raise last_exc  # pragma: no cover - loop always returns or raises above
