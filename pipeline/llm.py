"""The single model call the audit makes.

Only `pipeline/ideas.py` uses this, and only once per report: reading the
captions of the posts that did well against the ones that did badly, and turning
that into patterns and content ideas.

CLAUDE ONLY

An earlier version could switch between Claude and an OpenAI-compatible endpoint
via an env var, which was worth having while comparing the two. It is not worth
having now: a code path nobody exercises is a code path nobody notices breaking,
and the branch survived here only as a dependency on a package this project no
longer installs. Someone setting LLM_BACKEND=openai would have got an import
error rather than an explanation.

THE SALVAGE STEP IS NOT OPTIONAL

Models routinely emit unescaped double quotes inside string values when quoting
a caption — people say, "what happened to you?" — and that breaks the whole
document even though the rest of it is fine. Rather than lose ten good ideas to
one bad one, `_salvage` walks the text and decodes each object independently.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .config import config

JSON_ONLY_SUFFIX = (
    "\n\nRespond with the JSON object and nothing else. Do not write any "
    "explanation before or after it. Start your reply with { and end it with }."
)


def _strip_fences(text: str) -> str:
    """Pull the JSON out of a reply that may be wrapped or prefaced with prose."""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    first, last = text.find("{"), text.rfind("}")
    if first != -1 and last > first:
        return text[first: last + 1]
    return text


def _salvage(raw: str, required_field: str) -> list[dict[str, Any]]:
    """Whatever complete objects can be recovered from broken JSON."""
    decoder = json.JSONDecoder()
    found: list[dict[str, Any]] = []
    i = 0
    while True:
        i = raw.find("{", i)
        if i == -1:
            return found
        try:
            obj, end = decoder.raw_decode(raw, i)
        except ValueError:
            i += 1
            continue
        if isinstance(obj, dict) and required_field in obj:
            found.append(obj)
            i = end
        else:
            i += 1


def _call_claude(
    system: str,
    user: "str | list[dict[str, Any]]",
    model: str | None,
    temperature: float,
    max_tokens: int,
    schema: dict[str, Any] | None = None,
    effort: str | None = None,
) -> str:
    from anthropic import Anthropic

    if not config.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    client = Anthropic(api_key=config.anthropic_api_key)

    kwargs: dict[str, Any] = {
        "model": model or config.anthropic_model,
        "max_tokens": max_tokens,
        "system": system,
        # Prefilling the assistant turn with "{" used to force JSON here, and
        # newer models reject it outright. So the instruction goes in the prompt
        # and _strip_fences handles any preamble that arrives anyway.
        # A list is content blocks — text and images — for the steps that look
        # at the posts themselves.
        "messages": [{"role": "user", "content": (
            user + [{"type": "text", "text": JSON_ONLY_SUFFIX}]
            if isinstance(user, list) else user + JSON_ONLY_SUFFIX)}],
    }

    # Structured outputs replaced prefill. Unlike prompting, this is validated
    # by the API, so malformed JSON stops being possible rather than unlikely.
    output_config: dict[str, Any] = {}
    if schema is not None:
        output_config["format"] = {"type": "json_schema", "schema": schema}
    if effort:
        output_config["effort"] = effort
    if output_config:
        kwargs["output_config"] = output_config

    # Newer models reject `temperature` outright, so send it only when asking
    # for something other than the default.
    if temperature is not None and abs(temperature - 1.0) > 1e-9:
        kwargs["temperature"] = temperature

    # Peel off parameters the model rejects rather than assuming a fixed
    # capability set — several have been removed across recent releases, and
    # each removal broke this until it stopped guessing.
    for _ in range(4):
        try:
            msg = client.messages.create(**kwargs)
            break
        except Exception as e:
            err = str(e)
            dropped = False
            for param in ("temperature", "top_p", "top_k"):
                if param in err and param in kwargs:
                    kwargs.pop(param)
                    dropped = True
            if not dropped and "output_config" in kwargs and (
                "output_config" in err or "output_format" in err
                or "json_schema" in err
            ):
                kwargs.pop("output_config")
                dropped = True
            if not dropped:
                raise
    else:
        raise RuntimeError("Could not find an accepted parameter set for Claude")

    return "".join(
        b.text for b in msg.content if getattr(b, "type", "") == "text"
    )


def complete_json(
    system: str,
    user: "str | list[dict[str, Any]]",
    *,
    schema: dict[str, Any] | None = None,
    list_key: str = "items",
    required_field: str = "idea",
    backend: str | None = None,      # accepted and ignored; Claude only now
    model: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 16000,
    effort: str | None = None,
) -> dict[str, Any]:
    """Send a prompt — text, or content blocks with images — get JSON back."""
    raw = _call_claude(system, user, model, temperature, max_tokens, schema,
                       effort)
    text = _strip_fences(raw)

    try:
        got = json.loads(text)
        if isinstance(got, dict):
            return got
        if isinstance(got, list):
            return {list_key: got}
    except ValueError:
        pass

    rescued = _salvage(text, required_field)
    if rescued:
        return {list_key: rescued}

    raise RuntimeError(
        f"Model did not return valid JSON and nothing could be salvaged. "
        f"First 500 chars:\n{text[:500]}"
    )


def describe_backend(backend: str | None = None) -> str:
    return f"anthropic/{config.anthropic_model}"