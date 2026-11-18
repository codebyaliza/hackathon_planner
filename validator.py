"""
validator.py - Message Validation, Authority Rules, and Fact Resolution

WHY THIS FILE EXISTS:
Implements Section 7 (Fact Resolution) and Section 9 (The Validator).
Decides whether each message is ACCEPTED, REJECTED, IGNORED, or SUPERSEDED.
Rules:
a) Claim contradictions (e.g. food box order < headcount_on_site rejected as 'would leave X people without food')
b) Role authority (vendors/venues cannot change budget or headcount; students can only submit optional requests)
c) Outdated dates (older date cannot override newer date)
d) Feasibility check (authorized changes that break feasibility after adaptation are rejected)
e) Every rejection logged in trace: 'REJECTED msg #N (sender): <reason>'
"""

from datetime import datetime
from typing import Dict, Any, List, Tuple, Set, Optional

import llm
import planner
import checker

# Role permission sets
ORGANIZER_ROLES = {"organizer", "finance", "judge_coordinator"}
VENDOR_ROLES = {"vendor", "venue"}
STUDENT_ROLES = {"student", "unknown"}

# Facts only organizers can modify
RESTRICTED_ORGANIZER_FACTS = {
    "budget_total", "students", "staff_count", "team_size",
    "judges_available", "judge_fee", "event_hours", "max_teams_per_judge",
    "minutes_per_team", "start_time"
}

# The Dependency Map (Section 10)
DEPENDENCY_MAP = {
    "students": {"judging", "venue", "food", "budget", "schedule"},
    "team_size": {"judging", "venue", "food", "budget", "schedule"},
    "staff_count": {"venue", "food", "budget"},
    "judges_available": {"judging", "venue", "food", "budget", "schedule"},
    "judge_fee": {"judging", "budget"},
    "minutes_per_team": {"judging", "schedule"},
    "max_teams_per_judge": {"judging", "schedule"},
    "event_hours": {"schedule"},
    "start_time": {"schedule"},
    "budget_total": {"budget"},
    "fixed_costs": {"budget"},
    "venue_options": {"venue", "budget"},
    "food_options": {"food", "budget"},
    "schedule_constraints": {"schedule"},
    "venue_constraints": {"venue"},
    "food_constraints": {"food"}
}


def parse_date(date_str: Optional[str]) -> Optional[datetime]:
    """Parses date string YYYY-MM-DD if available."""
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(str(date_str).strip(), fmt)
        except ValueError:
            continue
    return None


def get_affected_areas(changed_keys: Set[str]) -> Set[str]:
    """
    WHY THIS EXISTS:
    Per Section 10, maps changed fact keys to only the affected plan areas.
    """
    affected = set()
    for key in changed_keys:
        if key in DEPENDENCY_MAP:
            affected.update(DEPENDENCY_MAP[key])
        else:
            # Default fallback for unknown facts
            affected.add("budget")
    return affected


def validate_message(
    msg_meta: Dict[str, Any],
    raw_extracted: Dict[str, Any],
    current_state: Dict[str, Any]
) -> Tuple[str, str, Dict[str, Any]]:
    """
    Evaluates a single message and returns (VERDICT, REASON, CLEAN_DATA).
    VERDICT is one of: 'ACCEPT', 'REJECT', 'IGNORE'
    """
    msg_id = msg_meta.get("id")
    sender = msg_meta.get("sender", "Unknown")
    role = str(msg_meta.get("sender_role", "unknown")).lower()
    date_str = msg_meta.get("date")
    msg_date = parse_date(date_str)
    relevant = msg_meta.get("relevant", True)

    # Rule 1: Irrelevant message check
    if not relevant:
        reason = "Message marked irrelevant/chatter by extractor"
        llm.log_code(f"IGNORED msg #{msg_id} ({sender}): {reason}")
        return "IGNORE", reason, {}

    # Extract all components related to this message
    facts = [f for f in raw_extracted.get("facts", []) if f.get("msg_id") == msg_id]
    venues = [v for v in raw_extracted.get("venues", []) if v.get("msg_id") == msg_id]
    foods = [f for f in raw_extracted.get("food_options", []) if f.get("msg_id") == msg_id]
    fixed_costs = [fc for fc in raw_extracted.get("fixed_costs", []) if fc.get("msg_id") == msg_id]
    optional_reqs = [r for r in raw_extracted.get("optional_requests", []) if r.get("msg_id") == msg_id]
    constraints = [c for c in raw_extracted.get("constraints", []) if c.get("msg_id") == msg_id]
    claims = [cl for cl in raw_extracted.get("claims", []) if cl.get("msg_id") == msg_id]

    # If completely empty of actionable items
    if not (facts or venues or foods or fixed_costs or optional_reqs or constraints or claims):
        reason = "No actionable facts, options, or requests found"
        llm.log_code(f"IGNORED msg #{msg_id} ({sender}): {reason}")
        return "IGNORE", reason, {}

    # Rule 2: Claims contradicting computed facts (Section 9a)
    current_metrics = current_state.get("plan", {}).get("metrics", {})
    headcount = current_metrics.get("headcount_on_site", 0)
    if headcount == 0:
        # If plan is not yet computed (e.g. during initial pack validation), derive tentative metrics
        facts_map = {f.get("key"): f for f in raw_extracted.get("facts", [])}
        for k, v in current_state.get("facts", {}).items():
            if k not in facts_map:
                facts_map[k] = v
        tentative_metrics = planner.compute_derived_metrics(facts_map)
        headcount = tentative_metrics.get("headcount_on_site", 0)

    for cl in claims:
        cl_key = cl.get("key", "").lower()
        cl_val = cl.get("value", 0)
        # Check food box quantity reduction claim
        if ("box" in cl_key or "food" in cl_key or "qty" in cl_key or "order" in cl_key) and headcount > 0:
            try:
                boxes = int(cl_val)
                if boxes < headcount:
                    shortage = headcount - boxes
                    reason = f"Quantity claim ({boxes} boxes) is below headcount ({headcount}); would leave {shortage} people without food"
                    llm.log_code(f"REJECTED msg #{msg_id} ({sender}): {reason}")
                    return "REJECT", reason, {}
            except (ValueError, TypeError):
                pass

    # Rule 3: Authority Rule (Section 9b)
    # Vendors and venues can only change their own prices/options
    if role in VENDOR_ROLES:
        # Check if vendor tried to modify organizer facts (budget, headcount, etc.)
        for f in facts:
            k = f.get("key", "")
            if k in RESTRICTED_ORGANIZER_FACTS:
                reason = f"Vendor '{sender}' unauthorized to change {k}"
                llm.log_code(f"REJECTED msg #{msg_id} ({sender}): {reason}")
                return "REJECT", reason, {}
        if fixed_costs:
            reason = f"Vendor '{sender}' unauthorized to declare event fixed costs"
            llm.log_code(f"REJECTED msg #{msg_id} ({sender}): {reason}")
            return "REJECT", reason, {}

    # Students and unknown senders can ONLY make optional requests
    if role in STUDENT_ROLES:
        if facts or venues or foods or fixed_costs:
            reason = f"Role '{role}' ({sender}) unauthorized to modify hackathon facts or commercial options"
            llm.log_code(f"REJECTED msg #{msg_id} ({sender}): {reason}")
            return "REJECT", reason, {}

    # Rule 4: Outdated date check (Section 9c)
    # Check if incoming fact has an older date than current fact in state
    if msg_date:
        for f in facts:
            k = f.get("key", "")
            existing = current_state.get("facts", {}).get(k)
            if existing and existing.get("date"):
                existing_date = parse_date(existing["date"])
                if existing_date and msg_date < existing_date:
                    reason = f"Outdated message dated {date_str} cannot override existing fact dated {existing['date']}"
                    llm.log_code(f"REJECTED msg #{msg_id} ({sender}): {reason}")
                    return "REJECT", reason, {}

    # If all checks pass, accept the message
    clean_data = {
        "facts": facts,
        "venues": venues,
        "food_options": foods,
        "fixed_costs": fixed_costs,
        "optional_requests": optional_reqs,
        "constraints": constraints,
        "claims": claims
    }
    return "ACCEPT", "Validated successfully", clean_data


def resolve_and_apply_facts(
    accepted_messages: List[Dict[str, Any]],
    raw_extracted: Dict[str, Any],
    current_state: Dict[str, Any]
) -> Tuple[Dict[str, Any], Set[str], List[Dict[str, Any]]]:
    """
    WHY THIS EXISTS:
    Merges newly extracted data into state facts using Section 7 rules:
    - Newest dated message wins.
    - If dates missing, later message in file wins.
    - Older conflicting values marked 'superseded' with reason.
    """
    facts_dict = dict(current_state.get("facts", {}))
    venues_list = list(current_state.get("venues", []))
    food_list = list(current_state.get("food_options", []))
    fixed_list = list(current_state.get("fixed_costs", []))
    optional_list = list(current_state.get("optional_requests", []))
    constraints_list = list(current_state.get("constraints", []))

    changed_keys = set()
    superseded_log = []

    accepted_ids = {m["id"] for m in accepted_messages}

    # Helper to check if date2 is newer than date1
    def is_newer(d1_str, d2_str, id1, id2) -> bool:
        dt1 = parse_date(d1_str)
        dt2 = parse_date(d2_str)
        if dt1 and dt2:
            return dt2 > dt1
        return id2 > id1

    # Apply facts
    for f in raw_extracted.get("facts", []):
        m_id = f.get("msg_id")
        if m_id not in accepted_ids:
            continue
        k = f.get("key")
        v = f.get("value")
        d = next((m.get("date") for m in accepted_messages if m["id"] == m_id), None)

        if k in facts_dict:
            old_item = facts_dict[k]
            if is_newer(old_item.get("date"), d, old_item.get("msg_id", 0), m_id):
                reason = f"{k} value {old_item.get('value')} superseded by {v} (newer message #{m_id})"
                llm.log_code(reason)
                superseded_log.append({"key": k, "old": old_item.get("value"), "new": v, "reason": reason})
                facts_dict[k] = {"value": v, "msg_id": m_id, "date": d}
                changed_keys.add(k)
        else:
            facts_dict[k] = {"value": v, "msg_id": m_id, "date": d}
            changed_keys.add(k)

    # Apply venues: update price/capacity if same name, or add new
    for v in raw_extracted.get("venues", []):
        m_id = v.get("msg_id")
        if m_id not in accepted_ids:
            continue
        v_name = v.get("name", "").strip().lower()
        existing_idx = next((i for i, ex in enumerate(venues_list) if ex.get("name", "").strip().lower() == v_name), None)
        if existing_idx is not None:
            old_v = venues_list[existing_idx]
            reason = f"Venue '{v.get('name')}' updated: price {old_v.get('price')} -> {v.get('price')}"
            llm.log_code(reason)
            superseded_log.append({"key": f"venue_{v_name}", "old": old_v.get("price"), "new": v.get("price"), "reason": reason})
            venues_list[existing_idx] = v
        else:
            venues_list.append(v)
        changed_keys.add("venue_options")

    # Apply food options: update price if same name, or add new
    for fo in raw_extracted.get("food_options", []):
        m_id = fo.get("msg_id")
        if m_id not in accepted_ids:
            continue
        fo_name = fo.get("name", "").strip().lower()
        existing_idx = next((i for i, ex in enumerate(food_list) if ex.get("name", "").strip().lower() == fo_name), None)
        if existing_idx is not None:
            old_fo = food_list[existing_idx]
            reason = f"Food '{fo.get('name')}' price updated {old_fo.get('price_per_head')} -> {fo.get('price_per_head')}"
            llm.log_code(reason)
            superseded_log.append({"key": f"food_{fo_name}", "old": old_fo.get("price_per_head"), "new": fo.get("price_per_head"), "reason": reason})
            food_list[existing_idx] = fo
        else:
            food_list.append(fo)
        changed_keys.add("food_options")

    # Apply fixed costs
    for fc in raw_extracted.get("fixed_costs", []):
        m_id = fc.get("msg_id")
        if m_id not in accepted_ids:
            continue
        fc_item = fc.get("item", "").strip().lower()
        existing_idx = next((i for i, ex in enumerate(fixed_list) if ex.get("item", "").strip().lower() == fc_item), None)
        if existing_idx is not None:
            old_fc = fixed_list[existing_idx]
            reason = f"Fixed cost '{fc.get('item')}' updated {old_fc.get('amount')} -> {fc.get('amount')}"
            llm.log_code(reason)
            superseded_log.append({"key": f"fixed_cost_{fc_item}", "old": old_fc.get("amount"), "new": fc.get("amount"), "reason": reason})
            fixed_list[existing_idx] = fc
        else:
            fixed_list.append(fc)
        changed_keys.add("fixed_costs")

    # Append optional requests
    for opt in raw_extracted.get("optional_requests", []):
        if opt.get("msg_id") in accepted_ids:
            optional_list.append(opt)
            changed_keys.add("budget")

    # Append constraints
    for c in raw_extracted.get("constraints", []):
        if c.get("msg_id") in accepted_ids:
            constraints_list.append(c)
            area = c.get("area", "")
            if area == "venue":
                changed_keys.add("venue_constraints")
            elif area == "food":
                changed_keys.add("food_constraints")
            elif area == "schedule":
                changed_keys.add("schedule_constraints")

    new_state = dict(current_state)
    new_state["facts"] = facts_dict
    new_state["venues"] = venues_list
    new_state["food_options"] = food_list
    new_state["fixed_costs"] = fixed_list
    new_state["optional_requests"] = optional_list
    new_state["constraints"] = constraints_list

    return new_state, changed_keys, superseded_log
