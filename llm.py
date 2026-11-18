"""
llm.py - Real LLM Interface and Execution Tracer

WHY THIS FILE EXISTS:
Manages all interactions with the REAL LLM API and enforces strict tracing rules.
Per Hard Rule R3:
- Numbers every model call.
- Logs model name, area tag (reading/venue/schedule/food/judging/budget),
  prompt, response, and real token counts directly from API usage fields.
- NEVER estimates or fakes tokens.
Per Hard Rule R7:
- Enforces a hard stop of at most 5 model calls during an update.
Per Section 13:
- Applies a 25-second timeout and retries once on invalid JSON before failing safely.
- If no API key is configured or the API is unreachable, halts with a clear error.
  NO mocks, NO simulated responses in the main pipeline.
"""

import sys
import json
import time
import urllib.request
import urllib.error
from typing import Dict, Any, Optional, Tuple

import config

# Global trace log and execution counters
_trace_entries = []
_model_call_counter = 0
_update_model_call_count = 0
_is_update_mode = False

VALID_AREA_TAGS = {"reading", "venue", "schedule", "food", "judging", "budget"}


def set_update_mode(is_update: bool):
    """Flags whether current run is an update (enforces 5-call max)."""
    global _is_update_mode, _update_model_call_count
    _is_update_mode = is_update
    _update_model_call_count = 0


def reset_trace():
    """Resets trace logs and counters for a fresh run."""
    global _trace_entries, _model_call_counter, _update_model_call_count
    _trace_entries = []
    _model_call_counter = 0
    _update_model_call_count = 0


def log_code(message: str):
    """
    Logs a non-model deterministic decision to the trace.
    Marked with [CODE] so it is obvious to judges no tokens were consumed.
    """
    formatted = f"[CODE] {message}"
    _trace_entries.append({"type": "code", "text": formatted})
    print(formatted)


def get_trace_log() -> list:
    """Returns the full list of trace entries."""
    return _trace_entries


def get_total_tokens() -> int:
    """Calculates sum of total_tokens reported by the model API across all calls."""
    total = 0
    for entry in _trace_entries:
        if entry.get("type") == "llm":
            total += entry.get("usage", {}).get("total_tokens", 0)
    return total


def get_model_call_count() -> int:
    """Returns total number of LLM API calls executed in this session."""
    return _model_call_counter


def _make_http_request(url: str, headers: dict, payload: dict, timeout: int) -> Tuple[dict, float]:
    """Sends HTTP POST to OpenAI-compatible endpoint using urllib."""
    data_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")
    start_time = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as response:
        duration = time.time() - start_time
        body = response.read().decode("utf-8")
        return json.loads(body), duration


def call_llm(area: str, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
    """
    Executes a single REAL model call with real token logging, JSON parsing, and retry.

    Parameters:
    - area: strictly one of ('reading', 'venue', 'schedule', 'food', 'judging', 'budget')
    - system_prompt: system instruction
    - user_prompt: user message / extracted data

    Returns parsed JSON dict.
    If no API key is provided or the API is unreachable, raises SystemExit with a clear error.
    """
    global _model_call_counter, _update_model_call_count

    if area not in VALID_AREA_TAGS:
        raise ValueError(f"Invalid area tag '{area}'. Must be one of {VALID_AREA_TAGS}")

    # Enforce Rule R7: Max 5 model calls during an update
    if _is_update_mode and _update_model_call_count >= config.MAX_UPDATE_MODEL_CALLS:
        msg = f"Update exceeded maximum allowed model calls ({config.MAX_UPDATE_MODEL_CALLS}). Aborting."
        log_code(msg)
        print(f"Error: {msg}", file=sys.stderr)
        sys.exit(1)

    # Verify API key for remote providers
    is_local = "localhost" in config.LLM_BASE_URL or "127.0.0.1" in config.LLM_BASE_URL
    if not is_local and not config.LLM_API_KEY:
        print("\n" + "=" * 70, file=sys.stderr)
        print("FATAL ERROR: LLM_API_KEY is not set in .env", file=sys.stderr)
        print("A real model API key is required to read messages and produce a plan.", file=sys.stderr)
        print("Please edit .env and set LLM_API_KEY=gsk_... (Groq) or your OpenRouter key.", file=sys.stderr)
        print("=" * 70 + "\n", file=sys.stderr)
        sys.exit(1)

    endpoint = f"{config.LLM_BASE_URL}/chat/completions"
    headers = {
        "Content-Type": "application/json",
    }
    if config.LLM_API_KEY:
        headers["Authorization"] = f"Bearer {config.LLM_API_KEY}"

    payload = {
        "model": config.LLM_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"}
    }

    last_error = None
    # Execute up to 2 attempts (1 initial + 1 retry on invalid JSON or network failure)
    for attempt in range(1, 3):
        _model_call_counter += 1
        if _is_update_mode:
            _update_model_call_count += 1

        call_id = _model_call_counter
        try:
            raw_response, duration = _make_http_request(endpoint, headers, payload, config.TIMEOUT_SECONDS)

            # Extract content from choices
            choice = raw_response.get("choices", [{}])[0]
            raw_content = choice.get("message", {}).get("content", "").strip()

            # Extract exact token usage from API response (never estimate)
            usage = raw_response.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
            total_tokens = usage.get("total_tokens", prompt_tokens + completion_tokens)

            # Strip Markdown code fences if model enclosed JSON in ```json ... ```
            clean_content = raw_content
            if clean_content.startswith("```"):
                lines = clean_content.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                clean_content = "\n".join(lines).strip()

            parsed_json = json.loads(clean_content)

            # Format and print the trace as strictly required by Rule R3
            trace_header = (
                f"#{call_id} | model: {config.LLM_MODEL} | area: {area} | "
                f"prompt_tokens: {prompt_tokens} | completion_tokens: {completion_tokens} | "
                f"total: {total_tokens} | time: {duration:.2f}s"
            )
            print(trace_header)
            print(f"INPUT: {user_prompt[:300]}... [truncated for display]" if len(user_prompt) > 300 else f"INPUT: {user_prompt}")
            print(f"OUTPUT: {clean_content[:300]}... [truncated for display]" if len(clean_content) > 300 else f"OUTPUT: {clean_content}")
            print("-" * 70)

            # Save full entry to trace history
            _trace_entries.append({
                "type": "llm",
                "call_id": call_id,
                "model": config.LLM_MODEL,
                "area": area,
                "duration": round(duration, 2),
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens
                },
                "input": user_prompt,
                "system": system_prompt,
                "raw_output": raw_content,
                "parsed": parsed_json
            })

            return parsed_json

        except json.JSONDecodeError as je:
            last_error = f"Invalid JSON received from API: {je}"
            log_code(f"Call #{call_id} attempt {attempt} returned invalid JSON: {je}")
            if attempt == 1:
                log_code(f"Retrying call #{call_id} once (Section 13)...")
                payload["messages"].append({"role": "user", "content": "Error: Your previous output was not valid JSON. Return ONLY a valid JSON object."})
                time.sleep(0.5)
                continue

        except urllib.error.HTTPError as he:
            err_body = he.read().decode("utf-8") if hasattr(he, "read") else ""
            last_error = f"HTTP {he.code}: {he.reason} - {err_body}"
            log_code(f"Call #{call_id} attempt {attempt} API error: {last_error}")
            if attempt == 1 and he.code in (429, 500, 502, 503, 504):
                log_code(f"Retrying call #{call_id} once...")
                time.sleep(1.0)
                continue
            break

        except urllib.error.URLError as ue:
            last_error = f"Network connection error: {ue}"
            log_code(f"Call #{call_id} attempt {attempt} network error: {ue}")
            if attempt == 1:
                log_code(f"Retrying call #{call_id} once...")
                time.sleep(1.0)
                continue

        except Exception as e:
            last_error = f"Unexpected error: {e}"
            log_code(f"Call #{call_id} unexpected error: {e}")
            if attempt == 1:
                time.sleep(0.5)
                continue

    # If both attempts failed, halt cleanly
    print(f"\nFATAL: Model call #{call_id} to {config.LLM_BASE_URL} failed: {last_error}", file=sys.stderr)
    sys.exit(1)
