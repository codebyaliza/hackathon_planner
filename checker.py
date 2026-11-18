"""
checker.py - Plan Integrity and Feasibility Verifier

WHY THIS FILE EXISTS:
Implements the 6 rigorous judges' validation checks defined in Section 11.
Executed after every full run and every update to certify plan validity.
Returns PASS / FAIL with clear, specific diagnostic details for each check.
"""

from typing import Dict, Any, List, Tuple


def check_correct_figures(plan: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Check 1: Correct Figures
    Independently recomputes all mathematical totals and verifies they match the plan.
    """
    metrics = plan.get("metrics", {})
    venue = plan.get("venue", {})
    food = plan.get("food", {})
    judging = plan.get("judging", {})
    budget = plan.get("budget", {})

    # Recompute headcount
    students = metrics.get("students", 0)
    staff = metrics.get("staff_count", 0)
    judges = metrics.get("judges_needed", 0)
    expected_headcount = students + staff + judges
    actual_headcount = metrics.get("headcount_on_site", 0)

    if expected_headcount != actual_headcount:
        return False, f"Headcount mismatch: {students}s + {staff}st + {judges}j = {expected_headcount}, got {actual_headcount}"

    # Recompute food total
    qty = food.get("quantity", 0)
    rate = food.get("price_per_head", 0.0)
    expected_food_cost = qty * rate
    actual_food_cost = food.get("total_cost", 0.0)
    if abs(expected_food_cost - actual_food_cost) > 0.01:
        return False, f"Food total mismatch: {qty} * {rate} = {expected_food_cost}, got {actual_food_cost}"

    # Recompute budget total
    v_cost = venue.get("cost", 0.0)
    f_cost = food.get("total_cost", 0.0)
    j_cost = judging.get("total_honorarium", 0.0)
    fixed_sum = sum(item.get("amount", 0.0) for item in budget.get("fixed_costs", []))
    expected_spent = v_cost + f_cost + j_cost + fixed_sum
    actual_spent = budget.get("total_spent", 0.0)

    if abs(expected_spent - actual_spent) > 0.01:
        return False, f"Budget math mismatch: recomputed {expected_spent} != reported {actual_spent}"

    curr = plan.get("currency") or budget.get("currency")
    c = "Rs " if curr == "Rs" else ""
    return True, f"All figures verified: headcount {actual_headcount}, food {c}{actual_food_cost:.2f}, total spent {c}{actual_spent:.2f}"


def check_within_budget(plan: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Check 2: Within Budget
    Verifies that total spent does not exceed budget_total.
    """
    budget = plan.get("budget", {})
    budget_total = budget.get("budget_total", 0.0)
    total_spent = budget.get("total_spent", 0.0)
    remaining = budget.get("remaining", 0.0)

    curr = plan.get("currency") or budget.get("currency")
    c = "Rs " if curr == "Rs" else ""

    if budget_total <= 0:
        return True, f"Budget limit not specified (spent: {c}{total_spent:.2f})"

    if total_spent <= budget_total:
        return True, f"Within budget: spent {c}{total_spent:.2f} of {c}{budget_total:.2f} (Remaining: {c}{remaining:.2f})"
    else:
        over = total_spent - budget_total
        return False, f"Budget exceeded by {c}{over:.2f} (spent {c}{total_spent:.2f} > limit {c}{budget_total:.2f})"


def check_venue_fits(plan: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Check 3: Venue Fits
    Verifies venue is selected, capacity >= headcount_on_site, and valid flag is true.
    """
    venue = plan.get("venue", {})
    metrics = plan.get("metrics", {})
    headcount = metrics.get("headcount_on_site", 0)

    if not venue.get("valid", False) or not venue.get("selected"):
        notes = "; ".join(venue.get("notes", ["No valid venue available"]))
        return False, f"Venue invalid: {notes}"

    capacity = venue.get("capacity", 0)
    if capacity < headcount:
        return False, f"Venue '{venue.get('name')}' capacity {capacity} is less than headcount {headcount}"

    return True, f"Venue '{venue.get('name')}' fits: capacity {capacity} >= headcount {headcount}"


def check_schedule_valid(plan: Dict[str, Any], constraints: List[Dict[str, Any]]) -> Tuple[bool, str]:
    """
    Check 4: Schedule Valid
    Verifies:
    - Duration matches event_hours exactly
    - Blocks are non-overlapping and contiguous
    - Code freeze occurs before judging
    - Judging duration >= judging_minutes
    - Schedule constraints (like end_before) are respected
    """
    schedule = plan.get("schedule", {})
    blocks = schedule.get("blocks", [])
    total_min = schedule.get("total_minutes", 0)
    scheduled_min = schedule.get("scheduled_minutes", 0)

    if not blocks:
        return False, "No schedule blocks generated"

    if scheduled_min != total_min:
        return False, f"Schedule total {scheduled_min}m does not match event_hours {total_min}m"

    # Check contiguous timing and freeze before judging
    freeze_end = None
    judging_start = None
    judging_duration = 0

    for i in range(len(blocks)):
        b = blocks[i]
        # Contiguity check with next block
        if i + 1 < len(blocks):
            if b["end_minute"] != blocks[i + 1]["start_minute"]:
                return False, f"Gap/overlap between '{b['name']}' ({b['end_minute']}) and '{blocks[i+1]['name']}' ({blocks[i+1]['start_minute']})"

        if b.get("type") == "submission":
            freeze_end = b["end_minute"]
        if b.get("type") == "judging":
            judging_start = b["start_minute"]
            judging_duration += b["duration"]

    if freeze_end is not None and judging_start is not None:
        if freeze_end > judging_start:
            return False, f"Code freeze ends at minute {freeze_end}, after judging starts at {judging_start}"

    min_judging_req = schedule.get("judging_duration", 0)
    if judging_duration < min_judging_req:
        return False, f"Judging allocated {judging_duration}m is less than required {min_judging_req}m"

    # Verify schedule constraints such as end_before
    for c in constraints:
        if c.get("area") == "schedule" and c.get("type") == "end_before":
            limit_val = str(c.get("value", "")).strip()
            # If start_time was provided, verify closing block finishes before limit
            start_time = schedule.get("start_time")
            if start_time and limit_val and len(blocks) > 0:
                last_block = blocks[-1]
                end_time_str = last_block.get("end_time", "")
                if end_time_str > limit_val:
                    return False, f"Schedule ends at {end_time_str}, violating end_before constraint {limit_val}"

    return True, f"Schedule valid: {len(blocks)} blocks span {scheduled_min}m with freeze before judging"


def check_enough_judges(plan: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Check 5: Enough Judges
    Verifies judges_needed <= judges_available and judge workload within limits.
    """
    metrics = plan.get("metrics", {})
    needed = metrics.get("judges_needed", 0)
    available = metrics.get("judges_available", 0)
    max_per_judge = metrics.get("max_teams_per_judge", 4)
    teams = metrics.get("teams", 0)

    if needed > available:
        return False, f"Insufficient judges: need {needed}, but only {available} available"

    if needed > 0 and (teams / needed) > max_per_judge:
        return False, f"Judge overload: {teams} teams / {needed} judges exceeds limit of {max_per_judge}"

    return True, f"Judges sufficient: {needed} needed <= {available} available ({teams} teams, max {max_per_judge}/judge)"


def check_all_areas_covered(plan: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Check 6: All Areas Covered
    Verifies venue, schedule, food, judging, and budget are all present in the plan.
    """
    required = ["venue", "schedule", "food", "judging", "budget"]
    missing = [area for area in required if area not in plan or not plan[area]]

    if missing:
        return False, f"Plan is missing areas: {', '.join(missing)}"

    return True, "All 5 areas covered: Venue, Schedule, Food, Judging, Budget"


def run_all_checks(plan: Dict[str, Any], constraints: List[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """
    WHY THIS EXISTS:
    Executes all 6 checks and returns their structured PASS/FAIL verdicts.
    """
    if constraints is None:
        constraints = []

    results = []

    c1_pass, c1_detail = check_correct_figures(plan)
    results.append({"id": 1, "name": "Correct figures", "passed": c1_pass, "detail": c1_detail})

    c2_pass, c2_detail = check_within_budget(plan)
    results.append({"id": 2, "name": "Within budget", "passed": c2_pass, "detail": c2_detail})

    c3_pass, c3_detail = check_venue_fits(plan)
    results.append({"id": 3, "name": "Venue fits", "passed": c3_pass, "detail": c3_detail})

    c4_pass, c4_detail = check_schedule_valid(plan, constraints)
    results.append({"id": 4, "name": "Schedule valid", "passed": c4_pass, "detail": c4_detail})

    c5_pass, c5_detail = check_enough_judges(plan)
    results.append({"id": 5, "name": "Enough judges", "passed": c5_pass, "detail": c5_detail})

    c6_pass, c6_detail = check_all_areas_covered(plan)
    results.append({"id": 6, "name": "All areas covered", "passed": c6_pass, "detail": c6_detail})

    return results
