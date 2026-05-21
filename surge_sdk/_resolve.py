"""
_resolve.py — Model override resolution shared by all provider wrappers.

The SDK lets callers redirect AI calls to a different model than the
one declared at the call site, via two mechanisms:

1. Per-request `surge_model` kwarg — wins outright.
2. Global `model_overrides={"opus": "sonnet", ...}` map set in `configure()`.

Both are pure substitution: the override model name is passed directly
to the provider; the SDK does not validate it.
"""

import logging
from typing import Optional, Tuple

from surge_sdk._config import get_config

logger = logging.getLogger("surge_sdk")


def resolve_model(
    requested_model: str,
    surge_model: Optional[str],
) -> Tuple[str, Optional[str]]:
    """Resolve a (possibly overridden) model name.

    Returns (actual_model, requested_model_if_overridden). The second value
    is None when no override occurred — callers use it as the flag to
    decide whether to include `requested_model` in the event payload.
    """
    if surge_model and surge_model != requested_model:
        logger.debug("Model overridden: %s -> %s (per-request)", requested_model, surge_model)
        return surge_model, requested_model

    overrides = get_config().model_overrides_dict
    mapped = overrides.get(requested_model)
    if mapped and mapped != requested_model:
        logger.debug("Model overridden: %s -> %s (global rule)", requested_model, mapped)
        return mapped, requested_model

    return requested_model, None
