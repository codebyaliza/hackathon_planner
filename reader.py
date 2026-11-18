"""
reader.py - Message Splitting and LLM Reading Call Builder

WHY THIS FILE EXISTS:
Splits raw text message packs using deterministic code (NO model used for splitting).
Builds the extraction prompts for the reading call (area tag: 'reading').
Understands English and Roman Urdu without hallucinating facts.
On updates, sends only the new message and existing fact keys to minimize token usage.
Always uses the real LLM API call.
"""

import hashlib
import re
from typing import List, Dict, Any, Optional

import llm


def compute_message_hash(text: str) -> str:
    """Computes a stable SHA-256 hash of a message's stripped content."""
    normalized = " ".join(text.strip().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def split_messages(file_content: str) -> List[Dict[str, Any]]:
    """
    Splits text file into distinct messages using pure Python pattern matching.
    Handles delimiters:
      - '---' or '===' separator lines
      - '### Message ...' or 'Message N:' or 'Msg N'
      - Double or triple blank lines
    Assigns sequential 1-based IDs and content hashes.
    """
    raw_lines = file_content.splitlines()
    messages: List[Dict[str, Any]] = []
    current_block: List[str] = []

    def flush_block():
        text = "\n".join(current_block).strip()
        if text:
            msg_id = len(messages) + 1
            messages.append({
                "id": msg_id,
                "text": text,
                "hash": compute_message_hash(text)
            })
        current_block.clear()

    # Pattern for explicit message headers
    header_pattern = re.compile(
        r"^(?:[-=_*]{3,}|\#{1,3}\s*(?:message|msg|pack|\d+)|\b(?:message|msg)\s+\d+[:\-]|\b\[\d+\])",
        re.IGNORECASE
    )

    blank_count = 0
    for line in raw_lines:
        stripped = line.strip()

        # Check explicit delimiter line
        if header_pattern.match(stripped):
            flush_block()
            remainder = re.sub(r"^(?:[-=_*]{3,}|\#{1,3}\s*)", "", stripped).strip()
            if remainder and not re.match(r"^(?:message|msg)\s+\d+[:\-]?$", remainder, re.IGNORECASE):
                current_block.append(remainder)
            blank_count = 0
            continue

        if not stripped:
            blank_count += 1
            if blank_count >= 2:
                flush_block()
                blank_count = 0
            continue

        blank_count = 0
        current_block.append(line)

    flush_block()

    # Fallback: if splitting produced only 1 message but text has multiple blank blocks
    if len(messages) <= 1 and "\n\n" in file_content:
        chunks = [c.strip() for c in file_content.split("\n\n") if c.strip()]
        if len(chunks) > 1:
            messages = []
            for idx, c in enumerate(chunks, 1):
                messages.append({
                    "id": idx,
                    "text": c,
                    "hash": compute_message_hash(c)
                })

    llm.log_code(f"Reader parsed {len(messages)} message(s) from input text.")
    return messages


# ==============================================================================
# PROMPT DEFINITIONS FOR THE READING CALL (Area Tag: "reading")
# ==============================================================================

READING_SYSTEM_PROMPT = """You are an accurate factual data extractor for a hackathon planning system.
Read the provided pack of messages (emails, WhatsApp texts, notices).
Messages may be in English, Roman Urdu (e.g., 'khana', 'paisa', 'kamra', 'taqreeb', 'musalsal', 'biryani', 'masla'), or mixed.

CRITICAL EXTRACTION RULES:
1. Extract facts ONLY from the text. NEVER invent, assume, or hallucinate numbers, names, or options.
2. Return strictly valid JSON with no markdown wrapping or extra commentary.
3. Classify sender_role as one of:
   organizer | finance | vendor | venue | judge_coordinator | judge | student | unknown
4. If a message is irrelevant chat or spam, set "relevant": false.
5. If a sender states an action or ordered quantity (e.g. 'I placed order for 20 boxes', 'booked hall for 30'), put it in "claims".
6. Extract constraints accurately with their type:
   break_minutes | min_capacity | requires_feature | end_before | start_at | max_cost | must_include | exclude_option | other
7. Currency rule: If any message explicitly uses 'Rs', 'PKR', or 'rupees', record currency as "Rs" in facts (key: "currency", value: "Rs"). Otherwise do not invent currency symbols.

JSON SCHEMA:
{
  "messages": [
    {"id": 1, "sender": "...", "sender_role": "organizer|finance|vendor|venue|judge_coordinator|judge|student|unknown", "date": "YYYY-MM-DD or null", "relevant": true, "summary": "short"}
  ],
  "facts": [
    {"key": "event_hours|students|team_size|budget_total|staff_count|judges_available|judge_fee|minutes_per_team|max_teams_per_judge|start_time|currency|<other_snake_case_key>", "value": 0, "msg_id": 1}
  ],
  "venues": [{"name": "...", "capacity": 0, "price": 0, "features": ["..."], "msg_id": 2}],
  "food_options": [{"name": "...", "price_per_head": 0, "msg_id": 4}],
  "fixed_costs": [{"item": "...", "amount": 0, "msg_id": 6}],
  "optional_requests": [{"item": "...", "amount": 0, "msg_id": 7}],
  "constraints": [
    {"area": "venue|schedule|food|judging|budget", "type": "break_minutes|min_capacity|requires_feature|end_before|start_at|max_cost|must_include|exclude_option|other", "value": "...", "text": "original wording", "msg_id": 1}
  ],
  "claims": [
    {"area": "food|venue|judging|budget|schedule", "key": "e.g. boxes_ordered", "value": 0, "text": "original wording", "msg_id": 9}
  ]
}
"""

UPDATE_READING_SYSTEM_PROMPT = """You are an accurate factual data extractor updating an existing hackathon plan.
Read the NEW message provided below. You are also given a compact list of known existing fact keys.
Extract ONLY the new or updated facts, constraints, claims, or requests from this new message.
Do not invent anything. Return strictly valid JSON matching the same schema."""


def build_reading_prompt(messages: List[Dict[str, Any]]) -> str:
    """Builds user prompt for initial full extraction."""
    lines = ["Here is the full pack of messages to read:"]
    for m in messages:
        lines.append(f"--- [Message #{m['id']}] ---")
        lines.append(m["text"])
        lines.append("")
    return "\n".join(lines)


def build_update_prompt(new_message: Dict[str, Any], existing_keys: List[str]) -> str:
    """Builds token-efficient prompt for an update run with only the new message."""
    keys_str = ", ".join(existing_keys) if existing_keys else "none"
    return f"""Current known fact keys: [{keys_str}]

NEW MESSAGE TO PROCESS:
--- [Message #{new_message['id']}] ---
{new_message['text']}
"""


def detect_currency_in_text(messages: List[Dict[str, Any]]) -> Optional[str]:
    """Inspects messages for explicit 'Rs', 'PKR', or 'rupees' usage."""
    for m in messages:
        t = m.get("text", "").lower()
        if re.search(r"\b(?:rs\.?|pkr|rupees?)\b", t):
            return "Rs"
    return None


def extract_pack_facts(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Executes the single Reading Call for a full run.
    Uses Area Tag: 'reading' (Rule R3).
    ALWAYS calls the real LLM API.
    """
    llm.log_code(f"Initiating real model reading call for {len(messages)} messages...")
    user_prompt = build_reading_prompt(messages)
    result = llm.call_llm(area="reading", system_prompt=READING_SYSTEM_PROMPT, user_prompt=user_prompt)

    # Detect currency if not captured
    detected_curr = detect_currency_in_text(messages)
    if detected_curr:
        has_curr_fact = any(f.get("key") == "currency" for f in result.get("facts", []))
        if not has_curr_fact:
            result.setdefault("facts", []).append({"key": "currency", "value": "Rs", "msg_id": 1})

    return result


def extract_update_facts(new_message: Dict[str, Any], existing_keys: List[str]) -> Dict[str, Any]:
    """
    Executes the single Reading Call for an update.
    Uses Area Tag: 'reading'.
    ALWAYS calls the real LLM API.
    """
    llm.log_code(f"Initiating real model update reading call for Message #{new_message['id']}...")
    user_prompt = build_update_prompt(new_message, existing_keys)
    result = llm.call_llm(area="reading", system_prompt=UPDATE_READING_SYSTEM_PROMPT, user_prompt=user_prompt)

    # Detect currency
    detected_curr = detect_currency_in_text([new_message])
    if detected_curr:
        has_curr_fact = any(f.get("key") == "currency" for f in result.get("facts", []))
        if not has_curr_fact:
            result.setdefault("facts", []).append({"key": "currency", "value": "Rs", "msg_id": new_message["id"]})

    return result
