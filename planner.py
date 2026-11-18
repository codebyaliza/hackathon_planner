"""
planner.py - Pure-Code Plan Builders

WHY THIS FILE EXISTS:
Per Core Design Principle (Section 3):
- Do ALL arithmetic, selection, scheduling, and budget calculations in pure Python.
- Keeps token usage close to zero and guarantees exact mathematical correctness.
- Area-tagged model calls (venue/schedule/food/judging/budget) are triggered ONLY
  when a constraint of type 'other' cannot be evaluated by deterministic rules.

Contains 5 builders:
1. build_judging
2. build_venue
3. build_food
4. build_schedule
5. build_budget
"""

import math
from typing import Dict, Any, List, Optional, Tuple

import config
import llm


def compute_derived_metrics(facts: Dict[str, Any]) -> Dict[str, int]:
    """
    WHY THIS EXISTS:
    Calculates fundamental hackathon numbers: teams, judges required, judging duration,
    and total on-site headcount. All 5 areas depend on these numbers.
    """
    students = int(facts.get("students", {}).get("value", 0))
    team_size = int(facts.get("team_size", {}).get("value", config.DESIGN_DEFAULT_TEAM_SIZE))
    if team_size <= 0:
        team_size = config.DESIGN_DEFAULT_TEAM_SIZE

    teams = math.ceil(students / team_size) if students > 0 else 0

    max_teams_per_judge = int(facts.get("max_teams_per_judge", {}).get("value", config.DESIGN_DEFAULT_MAX_TEAMS_PER_JUDGE))
    if max_teams_per_judge <= 0:
        max_teams_per_judge = config.DESIGN_DEFAULT_MAX_TEAMS_PER_JUDGE

    minutes_per_team = int(facts.get("minutes_per_team", {}).get("value", config.DESIGN_DEFAULT_MINUTES_PER_TEAM))
    if minutes_per_team <= 0:
        minutes_per_team = config.DESIGN_DEFAULT_MINUTES_PER_TEAM

    judges_available = int(facts.get("judges_available", {}).get("value", 0))
    judges_needed = math.ceil(teams / max_teams_per_judge) if teams > 0 else 0

    # Judging minutes: since judges evaluate their assigned batches in parallel
    judging_minutes = max_teams_per_judge * minutes_per_team

    staff_count = int(facts.get("staff_count", {}).get("value", config.DESIGN_DEFAULT_STAFF_COUNT))
    headcount_on_site = students + staff_count + judges_needed

    return {
        "students": students,
        "team_size": team_size,
        "teams": teams,
        "max_teams_per_judge": max_teams_per_judge,
        "minutes_per_team": minutes_per_team,
        "judges_available": judges_available,
        "judges_needed": judges_needed,
        "judging_minutes": judging_minutes,
        "staff_count": staff_count,
        "headcount_on_site": headcount_on_site
    }


def build_judging(metrics: Dict[str, int], facts: Dict[str, Any]) -> Dict[str, Any]:
    """
    WHY THIS EXISTS:
    Allocates judges, computes judge honorarium fees, and assigns team ranges.
    """
    judges_needed = metrics["judges_needed"]
    judges_available = metrics["judges_available"]
    teams = metrics["teams"]
    max_teams_per_judge = metrics["max_teams_per_judge"]

    fee_fact = facts.get("judge_fee", {})
    judge_fee = float(fee_fact.get("value", config.DESIGN_DEFAULT_JUDGE_FEE))
    total_honorarium = judges_needed * judge_fee

    # Assign team ranges to each judge (e.g., Judge 1: Teams 1-4)
    assignments = []
    current_team = 1
    for j in range(1, judges_needed + 1):
        end_team = min(current_team + max_teams_per_judge - 1, teams)
        if current_team <= teams:
            assignments.append({
                "judge_id": j,
                "team_range": f"Teams {current_team} to {end_team}",
                "team_count": (end_team - current_team + 1)
            })
            current_team = end_team + 1
        else:
            assignments.append({
                "judge_id": j,
                "team_range": "Standby / Reserve",
                "team_count": 0
            })

    status_ok = judges_needed <= judges_available
    llm.log_code(f"Judging planned: {judges_needed} judges needed (available: {judges_available}), honorarium: {total_honorarium}")

    return {
        "judges_needed": judges_needed,
        "judges_available": judges_available,
        "judge_fee": judge_fee,
        "total_honorarium": total_honorarium,
        "assignments": assignments,
        "sufficient_judges": status_ok,
        "source_msg_ids": [fee_fact.get("msg_id")] if fee_fact.get("msg_id") else []
    }


def _resolve_other_constraint_with_llm(area: str, constraint: Dict[str, Any], options: List[Dict[str, Any]]) -> List[str]:
    """
    WHY THIS EXISTS:
    Per Core Design Principle (Section 3):
    An area-tagged model call is made ONLY when an area has a constraint the code
    cannot handle (constraint type 'other'). This keeps area tags honest.
    """
    system_prompt = f"""You are evaluating a {area} constraint for a hackathon.
Given the constraint text and candidate options, decide which option names are ALLOWED.
Return strictly valid JSON:
{{"allowed_options": ["option_name_1", ...]}}
"""
    user_prompt = f"""Constraint: "{constraint.get('text', '')}" (value: {constraint.get('value', '')})
Candidate options:
{options}
Which options satisfy this constraint?
"""
    result = llm.call_llm(area=area, system_prompt=system_prompt, user_prompt=user_prompt)
    if result and isinstance(result.get("allowed_options"), list):
        return result["allowed_options"]
    # Fallback if model fails: allow all
    return [opt.get("name") for opt in options if "name" in opt]


def build_venue(metrics: Dict[str, int], venues: List[Dict[str, Any]], constraints: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    WHY THIS EXISTS:
    Selects the cheapest valid venue that accommodates the headcount and satisfies
    all venue constraints (features, capacity, exclusions, or 'other').
    """
    headcount = metrics["headcount_on_site"]
    venue_constraints = [c for c in constraints if c.get("area") == "venue"]

    valid_venues = []
    rejection_notes = []

    for v in venues:
        name = v.get("name", "Unknown")
        capacity = int(v.get("capacity", 0))
        price = float(v.get("price", 0))
        features = [f.lower() for f in v.get("features", [])]
        msg_id = v.get("msg_id")

        # Check capacity
        if capacity < headcount:
            rejection_notes.append(f"Venue '{name}' (cap {capacity}) too small for headcount {headcount}")
            continue

        # Check standard constraints
        disqualified = False
        for c in venue_constraints:
            ctype = c.get("type", "")
            cval = str(c.get("value", "")).lower()

            if ctype == "min_capacity" and capacity < int(c.get("value", 0)):
                disqualified = True
                rejection_notes.append(f"Venue '{name}' does not meet min_capacity {cval}")
                break
            elif ctype == "requires_feature" and not any(cval in f for f in features):
                disqualified = True
                rejection_notes.append(f"Venue '{name}' lacks required feature '{cval}'")
                break
            elif ctype == "exclude_option" and cval in name.lower():
                disqualified = True
                rejection_notes.append(f"Venue '{name}' is explicitly excluded by constraint")
                break
            elif ctype == "max_cost" and price > float(c.get("value", 0)):
                disqualified = True
                rejection_notes.append(f"Venue '{name}' exceeds max_cost {cval}")
                break

        if not disqualified:
            valid_venues.append(v)

    # If any constraint is 'other', use targeted model call
    other_constraints = [c for c in venue_constraints if c.get("type") == "other"]
    for oc in other_constraints:
        if valid_venues:
            allowed_names = _resolve_other_constraint_with_llm("venue", oc, valid_venues)
            valid_venues = [v for v in valid_venues if v.get("name") in allowed_names]

    if not valid_venues:
        llm.log_code(f"No suitable venue found for headcount {headcount}. Rejections: {rejection_notes}")
        return {
            "selected": None,
            "name": "None (No valid venue)",
            "capacity": 0,
            "cost": 0.0,
            "headcount_required": headcount,
            "valid": False,
            "notes": rejection_notes,
            "source_msg_id": None
        }

    # Pick the cheapest valid venue
    valid_venues.sort(key=lambda x: float(x.get("price", 0)))
    chosen = valid_venues[0]
    llm.log_code(f"Selected venue '{chosen.get('name')}' (cap {chosen.get('capacity')}) at cost {chosen.get('price')}")

    return {
        "selected": chosen,
        "name": chosen.get("name"),
        "capacity": chosen.get("capacity"),
        "cost": float(chosen.get("price", 0)),
        "headcount_required": headcount,
        "valid": True,
        "candidates_evaluated": len(venues),
        "source_msg_id": chosen.get("msg_id")
    }


def build_food(metrics: Dict[str, int], food_options: List[Dict[str, Any]], constraints: List[Dict[str, Any]], prefer_cheapest: bool = False) -> Dict[str, Any]:
    """
    WHY THIS EXISTS:
    Calculates catering requirements: quantity = headcount_on_site.
    Picks standard/preferred option at latest price, or adapts to cheaper option
    if budget adaptation is requested.
    """
    headcount = metrics["headcount_on_site"]
    food_constraints = [c for c in constraints if c.get("area") == "food"]

    valid_options = list(food_options)

    # Filter out excluded options
    for c in food_constraints:
        if c.get("type") == "exclude_option":
            target = str(c.get("value", "")).lower()
            valid_options = [opt for opt in valid_options if target not in opt.get("name", "").lower()]

    # If constraint is 'other', call LLM tagged 'food'
    other_food_constraints = [c for c in food_constraints if c.get("type") == "other"]
    for oc in other_food_constraints:
        if valid_options:
            allowed = _resolve_other_constraint_with_llm("food", oc, valid_options)
            valid_options = [opt for opt in valid_options if opt.get("name") in allowed]

    if not valid_options:
        llm.log_code(f"No food option available for headcount {headcount}")
        return {
            "selected": None,
            "name": "None",
            "price_per_head": 0.0,
            "quantity": headcount,
            "total_cost": 0.0,
            "valid": False,
            "source_msg_id": None
        }

    # Sort options: if prefer_cheapest, lowest price first; else standard order (or latest in pack)
    if prefer_cheapest:
        valid_options.sort(key=lambda x: float(x.get("price_per_head", 0)))
    else:
        # Default policy: prefer the first valid standard option, or latest
        pass

    chosen = valid_options[0]
    price_per_head = float(chosen.get("price_per_head", 0))
    total_cost = headcount * price_per_head

    llm.log_code(f"Selected food '{chosen.get('name')}' for {headcount} heads @ {price_per_head} = {total_cost}")

    return {
        "selected": chosen,
        "name": chosen.get("name"),
        "price_per_head": price_per_head,
        "quantity": headcount,
        "total_cost": total_cost,
        "valid": True,
        "source_msg_id": chosen.get("msg_id")
    }


def format_minutes(mins: int, start_time_str: Optional[str] = None) -> str:
    """Formats relative minutes (T+1:30) or clock time (10:30) if start_time given."""
    if not start_time_str:
        h = mins // 60
        m = mins % 60
        return f"T+{h:02d}:{m:02d}"
    try:
        parts = start_time_str.strip().split(":")
        base_h = int(parts[0])
        base_m = int(parts[1]) if len(parts) > 1 else 0
        total_m = base_h * 60 + base_m + mins
        fin_h = (total_m // 60) % 24
        fin_m = total_m % 60
        return f"{fin_h:02d}:{fin_m:02d}"
    except Exception:
        return f"T+{mins // 60:02d}:{mins % 60:02d}"


def build_schedule(metrics: Dict[str, int], facts: Dict[str, Any], constraints: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    WHY THIS EXISTS:
    Constructs a conflict-free chronological schedule that matches event_hours exactly.
    Includes:
    - Opening (design default)
    - Build time
    - Lunch / Breaks (including mandatory prayer/break constraints)
    - Code Freeze / Submission
    - Buffer before judging (design default to absorb delays)
    - Judging (>= judging_minutes, strictly after freeze)
    - Closing (design default)
    """
    event_hours = float(facts.get("event_hours", {}).get("value", 4.0))
    total_minutes = int(event_hours * 60)

    start_time_fact = facts.get("start_time", {})
    start_time = str(start_time_fact.get("value", "")).strip() or None

    judging_minutes = metrics["judging_minutes"]
    opening_minutes = config.DESIGN_DEFAULT_OPENING_MINUTES
    closing_minutes = config.DESIGN_DEFAULT_CLOSING_MINUTES
    buffer_minutes = config.DESIGN_DEFAULT_BUFFER_MINUTES
    freeze_minutes = 15  # 15 mins for submission / setup

    # Check break constraints (e.g. prayer break, coffee break)
    break_constraints = [c for c in constraints if c.get("area") == "schedule" and c.get("type") == "break_minutes"]
    custom_breaks = []
    for bc in break_constraints:
        try:
            b_mins = int(bc.get("value", 15))
            b_title = bc.get("text", "Break")
            custom_breaks.append({"name": b_title, "minutes": b_mins})
        except Exception:
            pass

    total_custom_breaks = sum(b["minutes"] for b in custom_breaks)

    # Lunch break policy: if total hackathon time >= 4 hours, include lunch if space permits
    lunch_minutes = config.DESIGN_DEFAULT_LUNCH_MINUTES if total_minutes >= 240 else 0

    # Fixed overhead total
    overhead = (opening_minutes + closing_minutes + buffer_minutes +
                freeze_minutes + judging_minutes + lunch_minutes + total_custom_breaks)

    # Build time is whatever remains of the event duration
    build_minutes = total_minutes - overhead
    if build_minutes < 30:
        # If schedule is too tight, compress buffer and lunch
        shortfall = 30 - build_minutes
        if buffer_minutes > 5:
            reduction = min(buffer_minutes - 5, shortfall)
            buffer_minutes -= reduction
            shortfall -= reduction
        if shortfall > 0 and lunch_minutes > 15:
            reduction = min(lunch_minutes - 15, shortfall)
            lunch_minutes -= reduction
            shortfall -= reduction
        build_minutes = total_minutes - (opening_minutes + closing_minutes + buffer_minutes +
                                         freeze_minutes + judging_minutes + lunch_minutes + total_custom_breaks)

    # Assemble chronological blocks
    blocks = []
    current_min = 0

    def add_block(name: str, duration: int, block_type: str):
        nonlocal current_min
        start_str = format_minutes(current_min, start_time)
        end_min = current_min + duration
        end_str = format_minutes(end_min, start_time)
        blocks.append({
            "name": name,
            "type": block_type,
            "start_minute": current_min,
            "end_minute": end_min,
            "duration": duration,
            "start_time": start_str,
            "end_time": end_str
        })
        current_min = end_min

    add_block("Opening Ceremony & Rules", opening_minutes, "ceremony")

    # If custom break falls early, place it, or split build time for lunch
    if lunch_minutes > 0:
        half_build = build_minutes // 2
        add_block("Hacking Session 1", half_build, "hacking")
        add_block("Lunch & Networking", lunch_minutes, "food")
        for cb in custom_breaks:
            add_block(cb["name"], cb["minutes"], "break")
        add_block("Hacking Session 2", build_minutes - half_build, "hacking")
    else:
        for cb in custom_breaks:
            add_block(cb["name"], cb["minutes"], "break")
        add_block("Hacking Session", build_minutes, "hacking")

    add_block("Code Freeze & Project Submission", freeze_minutes, "submission")
    add_block("Judging Buffer & Setup", buffer_minutes, "buffer")
    add_block("Team Pitches & Judging", judging_minutes, "judging")
    add_block("Closing & Awards Ceremony", closing_minutes, "ceremony")

    total_scheduled = current_min
    valid = (total_scheduled == total_minutes)

    llm.log_code(f"Schedule built: {len(blocks)} blocks totaling {total_scheduled}m (Target: {total_minutes}m)")

    return {
        "event_hours": event_hours,
        "total_minutes": total_minutes,
        "scheduled_minutes": total_scheduled,
        "blocks": blocks,
        "valid": valid,
        "start_time": start_time,
        "judging_duration": judging_minutes
    }


def format_currency_amount(amount: float, currency: Optional[str] = None) -> str:
    """
    WHY THIS EXISTS:
    Per requirement: Remove hardcoded currency symbol like '$'.
    Show 'Rs' only if the messages use Rs, otherwise plain numbers.
    """
    formatted = f"{amount:.2f}"
    if currency == "Rs":
        return f"Rs {formatted}"
    return formatted


def build_budget(
    facts: Dict[str, Any],
    venue_plan: Dict[str, Any],
    food_plan: Dict[str, Any],
    judging_plan: Dict[str, Any],
    fixed_costs: List[Dict[str, Any]],
    optional_requests: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    WHY THIS EXISTS:
    Aggregates all cost components:
    Total = Venue + Food + Judge Honorarium + All Fixed Costs.
    Compares against budget_total and evaluates affordability of optional requests.
    """
    budget_fact = facts.get("budget_total", {})
    budget_total = float(budget_fact.get("value", 0))

    curr_fact = facts.get("currency", {})
    currency = curr_fact.get("value")

    venue_cost = float(venue_plan.get("cost", 0))
    food_cost = float(food_plan.get("total_cost", 0))
    honorarium_cost = float(judging_plan.get("total_honorarium", 0))

    fixed_cost_items = []
    total_fixed_cost = 0.0
    for fc in fixed_costs:
        amt = float(fc.get("amount", 0))
        item = fc.get("item", "Miscellaneous")
        fixed_cost_items.append({"item": item, "amount": amt, "msg_id": fc.get("msg_id")})
        total_fixed_cost += amt

    total_spent = venue_cost + food_cost + honorarium_cost + total_fixed_cost
    remaining = budget_total - total_spent
    within_budget = (total_spent <= budget_total) if budget_total > 0 else True

    # Evaluate optional requests (Hard Rule: do NOT automatically add them)
    optional_evaluated = []
    running_remaining = remaining
    for opt in optional_requests:
        item = opt.get("item", "Optional Item")
        amt = float(opt.get("amount", 0))
        affordable = (running_remaining >= amt)
        rem_after = running_remaining - amt if affordable else running_remaining
        optional_evaluated.append({
            "item": item,
            "amount": amt,
            "affordable": affordable,
            "remaining_after": rem_after,
            "msg_id": opt.get("msg_id")
        })

    llm.log_code(f"Budget calculated: Total Spent {total_spent} / Limit {budget_total} (Remaining: {remaining})")

    return {
        "budget_total": budget_total,
        "currency": currency,
        "venue_cost": venue_cost,
        "food_cost": food_cost,
        "judge_honorarium": honorarium_cost,
        "fixed_costs": fixed_cost_items,
        "total_fixed_cost": total_fixed_cost,
        "total_spent": total_spent,
        "remaining": remaining,
        "within_budget": within_budget,
        "optional_requests": optional_evaluated,
        "source_msg_ids": [budget_fact.get("msg_id")] if budget_fact.get("msg_id") else []
    }


def build_full_plan(
    facts: Dict[str, Any],
    venues: List[Dict[str, Any]],
    food_options: List[Dict[str, Any]],
    fixed_costs: List[Dict[str, Any]],
    optional_requests: List[Dict[str, Any]],
    constraints: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    WHY THIS EXISTS:
    Assembles the complete 5-area plan with adaptive fallback if over budget.
    """
    metrics = compute_derived_metrics(facts)
    judging = build_judging(metrics, facts)
    venue = build_venue(metrics, venues, constraints)
    food = build_food(metrics, food_options, constraints, prefer_cheapest=False)
    schedule = build_schedule(metrics, facts, constraints)
    budget = build_budget(facts, venue, food, judging, fixed_costs, optional_requests)

    # Adaptive fallback: if over budget, try cheaper food option first
    if not budget["within_budget"] and len(food_options) > 1:
        llm.log_code("Initial plan exceeds budget. Attempting adaptive switch to cheaper food option...")
        food_alt = build_food(metrics, food_options, constraints, prefer_cheapest=True)
        budget_alt = build_budget(facts, venue, food_alt, judging, fixed_costs, optional_requests)
        if budget_alt["within_budget"] or budget_alt["total_spent"] < budget["total_spent"]:
            food = food_alt
            budget = budget_alt
            llm.log_code(f"Adapted to cheaper food: '{food['name']}', new total: {budget['total_spent']}")

    return {
        "metrics": metrics,
        "currency": budget.get("currency"),
        "venue": venue,
        "schedule": schedule,
        "food": food,
        "judging": judging,
        "budget": budget
    }
