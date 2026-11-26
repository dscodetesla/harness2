"""Validated model-profile routing; explicit denial overrides saved consent.

prefer_subscriptions is a coordinator hint, not automatic CLI reranking. Explicit
per-role CLI assignments belong to agent-roles.json and are resolved separately.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat

POLICY_PATH = Path.home() / ".config/harness2/routing.json"
MAX_BYTES = 4096
PROFILES = frozenset({"ollama_glm_cloud", "ollama_local"})
FIELDS = frozenset({"default_profile", "cloud_authorized", "prefer_subscriptions", "max_parallel"})
LEGACY = {"default_profile": "ollama_local", "cloud_authorized": False,
          "prefer_subscriptions": False, "max_parallel": 1}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Routing policy contains duplicate JSON keys")
        result[key] = value
    return result


def policy() -> dict:
    """Read bounded preferences from one non-symlink regular-file descriptor."""
    try:
        descriptor = os.open(POLICY_PATH, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    except FileNotFoundError:
        return {**LEGACY, "configured": False, "source": "legacy_default"}
    except OSError as exc:
        raise ValueError("Routing policy cannot be opened as a regular non-symlink file") from exc
    try:
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("Routing policy must be a regular file")
            raw = stream.read(MAX_BYTES + 1)
    except OSError as exc:
        raise ValueError("Routing policy cannot be read") from exc
    if len(raw) > MAX_BYTES:
        raise ValueError("Routing policy exceeds 4096 bytes")
    try:
        data = json.loads(raw, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ValueError("Routing policy contains malformed JSON") from exc
    if not isinstance(data, dict) or set(data) != FIELDS:
        raise ValueError("Routing policy requires exactly the supported preference fields")
    if not isinstance(data["default_profile"], str) or data["default_profile"] not in PROFILES:
        raise ValueError("Unknown default routing profile")
    if type(data["cloud_authorized"]) is not bool or type(data["prefer_subscriptions"]) is not bool:
        raise ValueError("Routing consent and subscription preference must be booleans")
    if type(data["max_parallel"]) is not int or not 1 <= data["max_parallel"] <= 4:
        raise ValueError("max_parallel must be an integer from 1 to 4")
    return {**data, "configured": True, "source": "configured_policy"}


def selection(profile=None, allow_cloud=None) -> dict:
    """Resolve omitted arguments against saved consent; preserve an explicit cloud denial."""
    if profile is not None and (not isinstance(profile, str) or profile not in PROFILES):
        raise ValueError("Unknown routing profile")
    if allow_cloud is not None and type(allow_cloud) is not bool:
        raise ValueError("allow_cloud must be boolean or omitted")
    saved = policy()
    source = saved["source"] if profile is None and allow_cloud is None else "explicit_request"
    if allow_cloud is False:
        if profile == "ollama_glm_cloud":
            raise ValueError("Explicit allow_cloud=False forbids the cloud profile")
        return {"profile": "ollama_local", "allow_cloud": False, "source": source}
    chosen = profile
    if chosen is None:
        chosen = "ollama_glm_cloud" if allow_cloud is True else saved["default_profile"]
    if chosen == "ollama_local":
        return {"profile": chosen, "allow_cloud": False, "source": source}
    if allow_cloud is not True and not saved["cloud_authorized"]:
        raise ValueError("Cloud profile requires explicit or saved cloud authorization")
    return {"profile": chosen, "allow_cloud": True, "source": source}
