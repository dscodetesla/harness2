#!/usr/bin/env python3
"""Fail-closed metadata preflight for the loopback Ollama model; no inference."""
import argparse
import json
import re
import urllib.error
import urllib.request

MODEL = "llama3.2-harness:3b"
BASE_URL = "http://127.0.0.1:11434"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("Ollama metadata endpoint must not redirect")


def _request(path, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(BASE_URL + path, data=data,
                                 headers={"Content-Type": "application/json"})
    # Ignore inherited HTTP proxies: the endpoint must remain loopback.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(req, timeout=5) as response:
            result = json.load(response)
    except (OSError, ValueError, urllib.error.URLError) as exc:
        raise RuntimeError(f"Ollama metadata unavailable at {path}: {exc}") from exc
    if not isinstance(result, dict) or result.get("error"):
        raise RuntimeError(f"Ollama metadata error at {path}: {result.get('error') if isinstance(result, dict) else 'not an object'}")
    return result


def validate_metadata(model, metadata, required_context, loaded=None):
    if not isinstance(required_context, int) or required_context < 1:
        raise RuntimeError("required_context must be a positive integer")
    if ":cloud" in model.lower() or metadata.get("remote_host") or metadata.get("remote_model"):
        raise RuntimeError("Cloud/remote model is not permitted")
    if not metadata.get("details", {}).get("format") == "gguf":
        raise RuntimeError("Expected a locally stored GGUF model")
    capabilities = set(metadata.get("capabilities", []))
    if not {"completion", "tools"} <= capabilities:
        raise RuntimeError("Model must advertise completion and tools capabilities")
    parameters = metadata.get("parameters", "")
    if not isinstance(parameters, str):
        raise RuntimeError("Missing Ollama parameters")
    values = re.findall(r"(?m)^num_ctx\s+(\d+)\s*$", parameters)
    if len(values) != 1:
        raise RuntimeError("Model must have one explicit num_ctx parameter; create the local alias first")
    context = int(values[0])
    if context < required_context:
        raise RuntimeError(f"Model num_ctx={context} is below required {required_context}")
    architecture_contexts = [v for k, v in metadata.get("model_info", {}).items()
                             if k.endswith(".context_length") and isinstance(v, int)]
    if architecture_contexts and max(architecture_contexts) < required_context:
        raise RuntimeError("Requested context exceeds model architecture context")
    runtime = None
    if loaded:
        for item in loaded.get("models", []):
            if item.get("name") != model and item.get("model") != model:
                continue
            if item.get("remote_host") or item.get("remote_model"):
                raise RuntimeError("Loaded model is remote")
            runtime = item.get("context_length")
            if not isinstance(runtime, int) or runtime < required_context:
                raise RuntimeError(f"Loaded runtime context={runtime} is below required {required_context}; unload/reload alias")
    return {"model": model, "configured_num_ctx": context,
            "required_context": required_context, "loaded_context_length": runtime,
            "local_only": True, "inference_performed": False}


def check_local_model(model=MODEL, required_context=16384):
    if model != MODEL:
        raise RuntimeError(f"Only the fixed local alias {MODEL} is permitted")
    metadata = _request("/api/show", {"model": model})
    loaded = _request("/api/ps")
    return validate_metadata(model, metadata, required_context, loaded)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--required-context", type=int, default=16384)
    args = parser.parse_args()
    try:
        print(json.dumps(check_local_model(required_context=args.required_context), indent=2))
        return 0
    except RuntimeError as exc:
        parser.exit(1, f"Local model preflight failed: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
