import json
import logging
import time
from typing import Any
import httpx

from . import settings

logger = logging.getLogger(__name__)


def repair_json(text: str) -> str:
    """Escapes control characters ONLY inside string literals.

    Models emit real newlines inside generated text (forbidden in JSON strings)
    and also pretty-print tokens (where escaping newlines would create syntax errors).
    Tracking quotes and backslashes ensures control characters are escaped only within strings.
    """
    out = []
    in_string = False
    escaped = False
    for ch in text:
        if escaped:
            out.append(ch)
            escaped = False
            continue
        if in_string and ch == "\\":
            out.append(ch)
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string
            out.append(ch)
            continue
        if in_string and ch <= "\x1f":
            if ch == "\n":
                out.append("\\n")
            elif ch == "\r":
                out.append("\\r")
            elif ch == "\t":
                out.append("\\t")
            continue
        out.append(ch)
    return "".join(out)


def parse_llm_json(raw: str) -> Any:
    """Strips markdown code blocks, repairs unescaped string control characters, and parses JSON."""
    text = raw.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    repaired = repair_json(text)
    return json.loads(repaired)


def call_llm(messages: list[dict], *, temperature: float = 0.0) -> str:
    """Calls an OpenAI-compatible /chat/completions endpoint with 5 retries and 120s timeout."""
    url = settings.get_llm_url()
    model = settings.get_llm_model()
    api_key = settings.get_llm_api_key()

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }

    max_tries = 5
    wait_seconds = 3

    last_error: Exception | None = None
    with httpx.Client(timeout=120.0) as client:
        for attempt in range(1, max_tries + 1):
            try:
                response = client.post(url, headers=headers, json=payload)
                if response.status_code == 200:
                    data = response.json()
                    return data["choices"][0]["message"]["content"]
                
                # If non-200, record error
                last_error = RuntimeError(
                    f"LLM API returned HTTP {response.status_code}: {response.text[:500]}"
                )
                logger.warning(
                    f"LLM call attempt {attempt}/{max_tries} failed (HTTP {response.status_code})."
                )
            except Exception as e:
                last_error = e
                logger.warning(f"LLM call attempt {attempt}/{max_tries} raised {e}")

            if attempt < max_tries:
                time.sleep(wait_seconds)

    raise RuntimeError(f"LLM call failed after {max_tries} attempts: {last_error}") from last_error
