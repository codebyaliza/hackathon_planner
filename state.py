"""
state.py - State Persistence (state.json)

WHY THIS FILE EXISTS:
Stores the accumulated knowledge base and plan across runs.
Per Hard Rule R4:
Enables the system to accept new messages after the first run and update
the existing plan without rebuilding everything from scratch.
Persists fact tables, accepted/rejected/superseded messages, plan, and message hashes.
"""

import json
from pathlib import Path
from typing import Dict, Any, Optional

import config


def get_empty_state() -> Dict[str, Any]:
    """Returns a fresh empty state dictionary."""
    return {
        "processed_hashes": [],
        "messages": [],           # Detailed metadata for each message
        "facts": {},              # Resolved facts: {key: {"value": val, "msg_id": id, "date": date}}
        "venues": [],             # Available venues
        "food_options": [],       # Available food options
        "fixed_costs": [],        # Known fixed costs
        "optional_requests": [],  # Optional requests
        "constraints": [],        # Active constraints
        "claims": [],             # Claims made by senders
        "plan": {},               # Computed plan (5 areas)
        "accepted_messages": [],  # Message IDs accepted
        "rejected_messages": [],  # [{"msg_id": id, "sender": sender, "reason": reason}]
        "ignored_messages": [],   # [{"msg_id": id, "sender": sender, "reason": reason}]
        "superseded_items": [],   # [{"key": key, "old": old, "new": new, "reason": reason}]
        "affected_areas": [],     # Areas touched in the most recent update
        "diff": []                # Key differences in the most recent update
    }


def load_state() -> Optional[Dict[str, Any]]:
    """Loads state from state.json if present and valid, else None."""
    if not config.STATE_FILE.exists():
        return None
    try:
        with open(config.STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data
    except Exception:
        return None


def save_state(state: Dict[str, Any]):
    """Saves state dictionary to state.json."""
    config.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(config.STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def reset_state() -> Dict[str, Any]:
    """Clears state.json and returns a fresh state."""
    state = get_empty_state()
    save_state(state)
    return state
