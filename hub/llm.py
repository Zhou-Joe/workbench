"""Thin client for the LM Studio local server (OpenAI-compatible API).

The app never assumes a specific model or vendor: base URL and model name
come from AppSettings, so pointing this at any OpenAI-compatible endpoint
is a configuration change.
"""

import json
import re

import requests

FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)
REQUEST_TIMEOUT = 240


class LLMError(Exception):
    """The LLM answered but the answer could not be used."""


class LLMUnavailable(LLMError):
    """No server at the configured endpoint."""


def chat(settings, messages):
    if not settings.lm_model:
        raise LLMUnavailable(
            "No model configured — set the model name on the Settings screen."
        )
    url = settings.lm_base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": settings.lm_model,
        "messages": messages,
        "temperature": settings.lm_temperature,
        "max_tokens": settings.lm_max_tokens,
    }
    try:
        resp = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        raise LLMUnavailable(f"LM Studio not reachable at {settings.lm_base_url}: {exc}") from exc
    if resp.status_code != 200:
        raise LLMError(f"LM Studio returned HTTP {resp.status_code}: {resp.text[:500]}")
    try:
        return resp.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError) as exc:
        raise LLMError(f"Unexpected LM Studio response shape: {exc}") from exc


def chat_stream(settings, messages):
    """Yield text deltas from a streaming chat completion (SSE deltas).

    Lazy like chat(): connection errors raise LLMUnavailable on first
    iteration, malformed chunks raise LLMError mid-stream.
    """
    if not settings.lm_model:
        raise LLMUnavailable(
            "No model configured — set the model name on the Settings screen."
        )
    url = settings.lm_base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": settings.lm_model,
        "messages": messages,
        "temperature": settings.lm_temperature,
        "max_tokens": settings.lm_max_tokens,
        "stream": True,
    }
    try:
        resp = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT, stream=True)
    except requests.RequestException as exc:
        raise LLMUnavailable(f"LM Studio not reachable at {settings.lm_base_url}: {exc}") from exc
    if resp.status_code != 200:
        raise LLMError(f"LM Studio returned HTTP {resp.status_code}: {resp.text[:500]}")
    try:
        for line in resp.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if data == "[DONE]":
                return
            chunk = json.loads(data)
            delta = chunk["choices"][0].get("delta", {}).get("content")
            if delta:
                yield delta
    except (KeyError, IndexError, ValueError) as exc:
        raise LLMError(f"Unexpected LM Studio stream chunk: {exc}") from exc


def extract_json(content):
    """Parse a JSON object out of a model reply, tolerating code fences."""
    text = (content or "").strip()
    m = FENCE_RE.search(text)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError(f"Model did not return valid JSON: {exc}\n{content[:500]}") from exc


def check_connection(settings):
    """Probe the endpoint; returns (ok, detail) for the status pill."""
    if not settings.lm_base_url:
        return False, "no base URL configured"
    url = settings.lm_base_url.rstrip("/") + "/models"
    try:
        resp = requests.get(url, timeout=5)
    except requests.RequestException as exc:
        return False, f"unreachable: {exc.__class__.__name__}"
    if resp.status_code != 200:
        return False, f"HTTP {resp.status_code}"
    try:
        models = [m.get("id", "?") for m in resp.json().get("data", [])]
    except ValueError:
        return False, "bad JSON from endpoint"
    return True, f"{len(models)} model(s) available"
