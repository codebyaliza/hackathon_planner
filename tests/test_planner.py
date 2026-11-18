"""
tests/test_planner.py - Unit Tests for Pure-Code Planner and Checker

WHY THIS FILE EXISTS:
Tests the deterministic planning logic and all 6 judges' checks without making
any LLM API calls. Guarantees that arithmetic, selection, scheduling, and constraints
work completely accurately with plain Python dictionaries.
"""

import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import config
import planner
import checker


def test_derived_metrics():
    facts = {
        "students": {"value": 48},
        "team_size": {"value": 4},
        "staff_count": {"value": 6},
        "judges_available": {"value": 5},
        "max_teams_per_judge": {"value": 3},
        "minutes_per_team": {"value": 10}
    }
    m = planner.compute_derived_metrics(facts)
    assert m["teams"] == 12, f"Expected 12 teams, got {m['teams']}"
    assert m["judges_needed"] == 4, f"Expected 4 judges needed, got {m['judges_needed']}"
    assert m["judging_minutes"] == 30, f"Expected 30 mins judging, got {m['judging_minutes']}"
    # Headcount: 48 students + 6 staff + 4 judges = 58
    assert m["headcount_on_site"] == 58, f"Expected 58 headcount, got {m['headcount_on_site']}"
    print("✅ test_derived_metrics passed")


def test_venue_selection():
    metrics = {"headcount_on_site": 50}
    venues = [
        {"name": "Small Room", "capacity": 40, "price": 200, "features": ["wifi"]},
        {"name": "Grand Hall", "capacity": 100, "price": 800, "features": ["wifi", "projector"]},
        {"name": "Tech Hub", "capacity": 60, "price": 500, "features": ["wifi", "projector"]}
    ]
    constraints = [{"area": "venue", "type": "requires_feature", "value": "projector"}]

    v_plan = planner.build_venue(metrics, venues, constraints)
    assert v_plan["valid"] is True
    # Cheapest valid venue with cap >= 50 and projector is Tech Hub ($500)
    assert v_plan["name"] == "Tech Hub", f"Expected Tech Hub, got {v_plan['name']}"
    assert v_plan["cost"] == 500.0
    print("✅ test_venue_selection passed")


def test_food_calculation():
    metrics = {"headcount_on_site": 60}
    foods = [
        {"name": "Standard Biryani Box", "price_per_head": 12.0},
        {"name": "Premium Buffet", "price_per_head": 25.0}
    ]
    f_plan = planner.build_food(metrics, foods, [])
    assert f_plan["valid"] is True
    assert f_plan["quantity"] == 60
    assert f_plan["total_cost"] == 720.0
    print("✅ test_food_calculation passed")


def test_schedule_validity():
    metrics = {"judging_minutes": 30}
    facts = {"event_hours": {"value": 4.0}, "start_time": {"value": "09:00"}}
    constraints = [{"area": "schedule", "type": "break_minutes", "value": 15, "text": "Prayer Break"}]

    s_plan = planner.build_schedule(metrics, facts, constraints)
    assert s_plan["valid"] is True
    assert s_plan["scheduled_minutes"] == 240
    # Verify blocks contiguous
    blocks = s_plan["blocks"]
    assert len(blocks) >= 6
    assert blocks[0]["start_time"] == "09:00"
    assert blocks[-1]["end_time"] == "13:00"
    print("✅ test_schedule_validity passed")


def test_budget_and_checks():
    metrics = {
        "students": 40,
        "staff_count": 5,
        "judges_needed": 3,
        "judges_available": 4,
        "headcount_on_site": 48,
        "teams": 10,
        "max_teams_per_judge": 4,
        "judging_minutes": 30
    }
    facts = {
        "budget_total": {"value": 2500.0},
        "event_hours": {"value": 4.0},
        "judge_fee": {"value": 100.0}
    }
    venues = [{"name": "Auditorium", "capacity": 80, "price": 800.0, "features": ["wifi"]}]
    foods = [{"name": "Lunch Box", "price_per_head": 15.0}]
    fixed_costs = [{"item": "Badges & Lanyards", "amount": 100.0}]
    optional_reqs = [{"item": "Energy Drinks", "amount": 200.0}]

    plan = planner.build_full_plan(facts, venues, foods, fixed_costs, optional_reqs, [])

    # Run checks
    results = checker.run_all_checks(plan, [])
    for r in results:
        assert r["passed"] is True, f"Check #{r['id']} {r['name']} failed: {r['detail']}"
    print("✅ test_budget_and_checks passed (all 6 checks PASS)")


def test_check_failures_detected():
    # Over budget scenario
    metrics = {
        "students": 40,
        "staff_count": 5,
        "judges_needed": 3,
        "judges_available": 4,
        "headcount_on_site": 48,
        "teams": 10,
        "max_teams_per_judge": 4,
        "judging_minutes": 30
    }
    # Budget total set artificially low ($500) when venue alone is $800
    facts = {"budget_total": {"value": 500.0}, "event_hours": {"value": 4.0}}
    venues = [{"name": "Auditorium", "capacity": 80, "price": 800.0, "features": ["wifi"]}]
    foods = [{"name": "Lunch Box", "price_per_head": 15.0}]

    plan = planner.build_full_plan(facts, venues, foods, [], [], [])
    results = checker.run_all_checks(plan, [])
    check_2 = next(r for r in results if r["id"] == 2)
    assert check_2["passed"] is False, "Check 2 should fail when over budget"
    print("✅ test_check_failures_detected passed")


if __name__ == "__main__":
    print("Running planner and checker unit tests...")
    test_derived_metrics()
    test_venue_selection()
    test_food_calculation()
    test_schedule_validity()
    test_budget_and_checks()
    test_check_failures_detected()
    print("\n🎉 ALL TESTS PASSED SUCCESSFULLY!")
