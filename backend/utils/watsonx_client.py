"""
backend/utils/watsonx_client.py
Thin wrapper around ibm-watsonx-ai for text generation.

Features
--------
* Lazy singleton — the client is created once per process on first use.
* 2-retry exponential back-off on transient errors (429 / 5xx).
* Hard-raises WatsonxError on persistent failure so callers can flag
  the incident for manual review (per ST-13 requirement).
"""
from __future__ import annotations

import logging
import time
from typing import Any

from flask import current_app

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public exception
# ---------------------------------------------------------------------------

class WatsonxError(RuntimeError):
    """Raised when all retries to watsonx.ai are exhausted."""


# ---------------------------------------------------------------------------
# Retry helper
# ---------------------------------------------------------------------------

_MAX_RETRIES = 2
_RETRY_BASE_DELAY = 1.0   # seconds


def _call_with_retry(fn, *args, **kwargs) -> Any:
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            if attempt < _MAX_RETRIES:
                delay = _RETRY_BASE_DELAY * (2 ** attempt)
                log.warning(
                    "watsonx call failed (attempt %d/%d): %s — retrying in %.1fs",
                    attempt + 1, _MAX_RETRIES + 1, exc, delay,
                )
                time.sleep(delay)
    raise WatsonxError(f"watsonx call failed after {_MAX_RETRIES + 1} attempts") from last_exc


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------

_client_cache: dict = {}   # keyed by (api_key, url, project_id)


def get_model():
    """Return a cached ModelInference instance using current Flask app config."""
    from ibm_watsonx_ai import Credentials
    from ibm_watsonx_ai.foundation_models import ModelInference

    cfg = current_app.config
    key = (cfg["WATSONX_API_KEY"], cfg["WATSONX_URL"], cfg["WATSONX_PROJECT_ID"])

    if key not in _client_cache:
        credentials = Credentials(
            url=cfg["WATSONX_URL"],
            api_key=cfg["WATSONX_API_KEY"],
        )
        _client_cache[key] = ModelInference(
            model_id=cfg["WATSONX_MODEL_ID"],
            credentials=credentials,
            project_id=cfg["WATSONX_PROJECT_ID"],
        )
        log.info("Created watsonx ModelInference for model=%s", cfg["WATSONX_MODEL_ID"])

    return _client_cache[key]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate(prompt: str, max_new_tokens: int = 512, temperature: float = 0.0) -> str:
    """Generate text from Granite and return the generated string.

    Parameters
    ----------
    prompt:         The full prompt string sent to Granite.
    max_new_tokens: Maximum tokens to generate.
    temperature:    0.0 = deterministic (greedy).

    Raises
    ------
    WatsonxError: if all retries are exhausted.
    """
    params = {
        "max_new_tokens": max_new_tokens,
        "temperature": temperature,
        "decoding_method": "greedy" if temperature == 0.0 else "sample",
    }

    def _do_generate():
        model = get_model()
        response = model.generate_text(prompt=prompt, params=params)
        return response

    result = _call_with_retry(_do_generate)
    return result.strip() if isinstance(result, str) else str(result).strip()
