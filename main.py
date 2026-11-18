"""
main.py - Single Command Entry Point for Hackathon Planner

WHY THIS FILE EXISTS:
Implements Hard Rules R1, R2, R3, R4, R5, R6, R7, and Sections 10 & 12.
Provides the ONE single terminal command:
    python main.py messages.txt

Autonomous Workflow:
1. Loads messages from the specified text file.
2. Checks state.json to automatically decide FULL RUN vs UPDATE.
3. If UPDATE: reads only new messages, identifies affected areas via Dependency Map,
   rebuilds ONLY affected areas, generates a 'What changed' diff, and limits to <=5 model calls.
4. Executes the 6 judges' checks and outputs PASS/FAIL diagnostics.
5. Emits the full trace with exact API token usage and [CODE] annotations.
6. Saves plan.json, trace.txt, and final_report.md to output/.
"""

import sys
import time
import json
from pathlib import Path
from typing import Dict, Any, List, Set

import config
import llm
import reader
import validator
import planner
import checker
import state as state_mgr


def format_plan_summary(plan: Dict[str, Any]) -> str:
    """Formats the 5-area plan cleanly for terminal display."""
    venue = plan.get("venue", {})
    food = plan.get("food", {})
    judging = plan.get("judging", {})
    schedule = plan.get("schedule", {})
    budget = plan.get("budget", {})
    metrics = plan.get("metrics", {})
    curr = plan.get("currency") or budget.get("currency")
    c = "Rs " if curr == "Rs" else ""

    lines = [
        "=" * 70,
        "                     HACKATHON MASTER PLAN",
        "=" * 70,
        f"KEY METRICS: Students: {metrics.get('students', 0)} | Teams: {metrics.get('teams', 0)} | "
        f"Headcount On-Site: {metrics.get('headcount_on_site', 0)}",
        "-" * 70,
        "[1. VENUE]",
        f"  Selected: {venue.get('name')} (Capacity: {venue.get('capacity')})",
        f"  Cost: {c}{venue.get('cost', 0):.2f}",
        "-" * 70,
        "[2. FOOD & CATERING]",
        f"  Selected: {food.get('name')} | Quantity: {food.get('quantity')} heads",
        f"  Price/Head: {c}{food.get('price_per_head', 0):.2f} | Total: {c}{food.get('total_cost', 0):.2f}",
        "-" * 70,
        "[3. JUDGING]",
        f"  Judges Needed: {judging.get('judges_needed', 0)} (Available: {judging.get('judges_available', 0)})",
        f"  Honorarium: {c}{judging.get('total_honorarium', 0):.2f}",
        "  Assignments:",
    ]
    for asgn in judging.get("assignments", []):
        lines.append(f"    - Judge #{asgn['judge_id']}: {asgn['team_range']} ({asgn['team_count']} teams)")

    lines.extend([
        "-" * 70,
        "[4. SCHEDULE]",
        f"  Duration: {schedule.get('event_hours', 0)} hours ({schedule.get('total_minutes', 0)} mins) | Start: {schedule.get('start_time', 'T+0:00')}",
        "  Timeline:",
    ])
    for b in schedule.get("blocks", []):
        lines.append(f"    [{b['start_time']} - {b['end_time']}] ({b['duration']:>2}m) {b['name']}")

    lines.extend([
        "-" * 70,
        "[5. BUDGET]",
        f"  Total Budget: {c}{budget.get('budget_total', 0):.2f}",
        f"  Venue:        {c}{budget.get('venue_cost', 0):.2f}",
        f"  Food:         {c}{budget.get('food_cost', 0):.2f}",
        f"  Judging:      {c}{budget.get('judge_honorarium', 0):.2f}",
        f"  Fixed Costs:  {c}{budget.get('total_fixed_cost', 0):.2f}",
    ])
    for fc in budget.get("fixed_costs", []):
        lines.append(f"    - {fc['item']}: {c}{fc['amount']:.2f}")
    lines.extend([
        f"  TOTAL SPENT:  {c}{budget.get('total_spent', 0):.2f}",
        f"  REMAINING:    {c}{budget.get('remaining', 0):.2f} (Status: {'WITHIN BUDGET' if budget.get('within_budget') else 'OVER BUDGET'})",
    ])
    if budget.get("optional_requests"):
        lines.append("  Optional Requests:")
        for opt in budget.get("optional_requests", []):
            aff_str = "YES" if opt["affordable"] else "NO"
            lines.append(f"    - {opt['item']}: {c}{opt['amount']:.2f} (Affordable: {aff_str}, Rem: {c}{opt['remaining_after']:.2f})")

    lines.append("=" * 70)
    return "\n".join(lines)


def generate_diff(old_plan: Dict[str, Any], new_plan: Dict[str, Any]) -> List[str]:
    """Generates human-readable diff: old value -> new value."""
    diff_lines = []

    def check_diff(label, old_v, new_v):
        if old_v != new_v:
            diff_lines.append(f"{label}: {old_v} -> {new_v}")

    # Venue diff
    check_diff("Venue", old_plan.get("venue", {}).get("name"), new_plan.get("venue", {}).get("name"))
    check_diff("Venue Cost", old_plan.get("venue", {}).get("cost"), new_plan.get("venue", {}).get("cost"))

    # Food diff
    check_diff("Food Option", old_plan.get("food", {}).get("name"), new_plan.get("food", {}).get("name"))
    check_diff("Food Cost", old_plan.get("food", {}).get("total_cost"), new_plan.get("food", {}).get("total_cost"))

    # Judging diff
    check_diff("Judges Needed", old_plan.get("judging", {}).get("judges_needed"), new_plan.get("judging", {}).get("judges_needed"))
    check_diff("Judging Honorarium", old_plan.get("judging", {}).get("total_honorarium"), new_plan.get("judging", {}).get("total_honorarium"))

    # Budget diff
    check_diff("Total Spent", old_plan.get("budget", {}).get("total_spent"), new_plan.get("budget", {}).get("total_spent"))
    check_diff("Remaining Budget", old_plan.get("budget", {}).get("remaining"), new_plan.get("budget", {}).get("remaining"))

    return diff_lines


def save_outputs(plan: Dict[str, Any], check_results: List[Dict[str, Any]], state_data: Dict[str, Any], total_time: float):
    """
    Saves:
    1. output/plan.json
    2. output/trace.txt
    3. output/final_report.md
    """
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. plan.json
    with open(config.OUTPUT_PLAN_FILE, "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2, ensure_ascii=False)

    # 2. trace.txt
    trace_entries = llm.get_trace_log()
    with open(config.OUTPUT_TRACE_FILE, "w", encoding="utf-8") as f:
        for entry in trace_entries:
            if entry.get("type") == "code":
                f.write(f"{entry['text']}\n")
            elif entry.get("type") == "llm":
                u = entry.get("usage", {})
                header = (
                    f"#{entry['call_id']} | model: {entry['model']} | area: {entry['area']} | "
                    f"prompt_tokens: {u.get('prompt_tokens', 0)} | completion_tokens: {u.get('completion_tokens', 0)} | "
                    f"total: {u.get('total_tokens', 0)} | time: {entry.get('duration', 0):.2f}s\n"
                )
                f.write(header)
                f.write(f"INPUT:\n{entry.get('input')}\n")
                f.write(f"OUTPUT:\n{entry.get('raw_output')}\n")
                f.write("-" * 70 + "\n")
        f.write(f"\nTOTAL TOKENS: {llm.get_total_tokens()} | MODEL CALLS: {llm.get_model_call_count()} | RUN TIME: {total_time:.2f}s\n")

    # 3. final_report.md
    with open(config.OUTPUT_REPORT_FILE, "w", encoding="utf-8") as f:
        f.write("# Hackathon Planning Final Report\n\n")
        f.write(f"**Execution Time:** {total_time:.2f}s | **Model Calls:** {llm.get_model_call_count()} | **Total Tokens:** {llm.get_total_tokens()}\n\n")

        f.write("## 1. Compliance Checks\n")
        for c in check_results:
            status = "✅ PASS" if c["passed"] else "❌ FAIL"
            f.write(f"- **{c['name']}**: {status} — *{c['detail']}*\n")
        f.write("\n")

        f.write("## 2. Master Plan\n```\n")
        f.write(format_plan_summary(plan))
        f.write("\n```\n\n")

        if state_data.get("rejected_messages"):
            f.write("## 3. Rejected Messages\n")
            for r in state_data["rejected_messages"]:
                f.write(f"- ❌ **Msg #{r['msg_id']}** ({r['sender']}): {r['reason']}\n")
            f.write("\n")

        if state_data.get("superseded_items"):
            f.write("## 4. Superseded Facts\n")
            for s in state_data["superseded_items"]:
                f.write(f"- ⚠️ {s['reason']}\n")
            f.write("\n")

        f.write("## 5. Execution Trace\n```\n")
        with open(config.OUTPUT_TRACE_FILE, "r", encoding="utf-8") as tf:
            f.write(tf.read())
        f.write("\n```\n")


def run(filepath: str):
    """
    Main orchestration function.
    Reads file, determines mode (full run vs update), executes logic, runs checks, and prints outputs.
    """
    start_time = time.time()
    llm.reset_trace()

    target_path = Path(filepath)
    if not target_path.exists():
        print(f"Error: Specified message file '{filepath}' does not exist.")
        sys.exit(1)

    with open(target_path, "r", encoding="utf-8") as f:
        file_content = f.read()

    # Step 1: Split messages in pure code (no model)
    raw_messages = reader.split_messages(file_content)
    if not raw_messages:
        print("Error: No messages found in input file.")
        sys.exit(1)

    file_hashes = [m["hash"] for m in raw_messages]

    # Step 2: Determine Run Mode (Full Run vs Update vs No Change)
    saved_state = state_mgr.load_state()
    is_update = False
    new_messages: List[Dict[str, Any]] = []

    if saved_state is None:
        llm.log_code("No existing state found. Executing FULL RUN...")
        is_update = False
    else:
        processed_hashes = set(saved_state.get("processed_hashes", []))
        # Check overlap
        overlap = any(h in processed_hashes for h in file_hashes)
        if not overlap:
            llm.log_code("New pack detected (no hash overlap with state). Resetting state for FULL RUN...")
            is_update = False
        else:
            # Check for new messages
            new_messages = [m for m in raw_messages if m["hash"] not in processed_hashes]
            if not new_messages:
                print("\n[CODE] No new messages detected in pack. Current plan remains valid:")
                current_plan = saved_state.get("plan", {})
                print(format_plan_summary(current_plan))
                checks = checker.run_all_checks(current_plan, saved_state.get("constraints", []))
                print("\n" + "=" * 70)
                print("                   INTEGRITY CHECKS (JUDGES' VERDICT)")
                print("=" * 70)
                for c in checks:
                    status = "[PASS]" if c["passed"] else "[FAIL]"
                    print(f"{status} Check {c['id']}: {c['name']} - {c['detail']}")
                print("=" * 70)
                return
            else:
                llm.log_code(f"Detected {len(new_messages)} new message(s). Executing UPDATE...")
                is_update = True

    llm.set_update_mode(is_update)

    # Step 3: Fact Extraction
    if not is_update:
        # Full Run: 1 model call (area: 'reading')
        extracted = reader.extract_pack_facts(raw_messages)
        if not extracted:
            print("Error: Reading call failed to parse message pack.")
            sys.exit(1)

        # Initialize fresh state
        state = state_mgr.get_empty_state()
        state["processed_hashes"] = file_hashes

        # Validate each message in pack
        extracted_messages = extracted.get("messages", [])
        msg_meta_map = {m.get("id"): m for m in extracted_messages}

        accepted_msgs = []
        for raw_m in raw_messages:
            m_id = raw_m["id"]
            meta = msg_meta_map.get(m_id, {"id": m_id, "sender": "Unknown", "sender_role": "unknown", "relevant": True})
            verdict, reason, clean_data = validator.validate_message(meta, extracted, state)
            state["messages"].append({
                "id": m_id,
                "hash": raw_m["hash"],
                "text": raw_m["text"],
                "sender": meta.get("sender"),
                "role": meta.get("sender_role"),
                "date": meta.get("date"),
                "status": verdict,
                "reason": reason
            })
            if verdict == "ACCEPT":
                state["accepted_messages"].append(m_id)
                accepted_msgs.append(meta)
            elif verdict == "REJECT":
                state["rejected_messages"].append({"msg_id": m_id, "sender": meta.get("sender"), "reason": reason})
            elif verdict == "IGNORE":
                state["ignored_messages"].append({"msg_id": m_id, "sender": meta.get("sender"), "reason": reason})

        # Apply accepted facts
        state, changed_keys, superseded = validator.resolve_and_apply_facts(accepted_msgs, extracted, state)
        state["superseded_items"] = superseded

        # Build full plan in pure code
        plan = planner.build_full_plan(
            state["facts"],
            state["venues"],
            state["food_options"],
            state["fixed_costs"],
            state["optional_requests"],
            state["constraints"]
        )
        state["plan"] = plan

    else:
        # Update Run: process new messages only
        state = dict(saved_state)
        old_plan = dict(state.get("plan", {}))
        existing_keys = list(state.get("facts", {}).keys())

        all_changed_keys = set()
        for new_m in new_messages:
            extracted = reader.extract_update_facts(new_m, existing_keys)
            if not extracted:
                llm.log_code(f"Could not extract facts from message #{new_m['id']}. Skipping.")
                continue

            extracted_msgs = extracted.get("messages", [])
            meta = extracted_msgs[0] if extracted_msgs else {
                "id": new_m["id"], "sender": "Unknown", "sender_role": "unknown", "relevant": True
            }
            # Remap ID to new_m['id'] if needed
            meta["id"] = new_m["id"]

            verdict, reason, clean_data = validator.validate_message(meta, extracted, state)
            state["messages"].append({
                "id": new_m["id"],
                "hash": new_m["hash"],
                "text": new_m["text"],
                "sender": meta.get("sender"),
                "role": meta.get("sender_role"),
                "date": meta.get("date"),
                "status": verdict,
                "reason": reason
            })

            if verdict == "ACCEPT":
                state["accepted_messages"].append(new_m["id"])
                # Tentatively apply facts
                tentative_state, chg_keys, superseded = validator.resolve_and_apply_facts([meta], extracted, state)
                state["superseded_items"].extend(superseded)
                all_changed_keys.update(chg_keys)

                # Identify affected areas via dependency map (Section 10)
                affected_areas = validator.get_affected_areas(chg_keys)
                llm.log_code(f"Changed facts: {list(chg_keys)} -> Affected areas: {list(affected_areas)}")
                state["affected_areas"] = list(affected_areas)

                # Rebuild ONLY affected areas
                metrics = planner.compute_derived_metrics(tentative_state["facts"])
                new_plan = dict(state["plan"])
                new_plan["metrics"] = metrics

                if "judging" in affected_areas:
                    new_plan["judging"] = planner.build_judging(metrics, tentative_state["facts"])
                if "venue" in affected_areas:
                    new_plan["venue"] = planner.build_venue(metrics, tentative_state["venues"], tentative_state["constraints"])
                if "food" in affected_areas:
                    new_plan["food"] = planner.build_food(metrics, tentative_state["food_options"], tentative_state["constraints"])
                if "schedule" in affected_areas:
                    new_plan["schedule"] = planner.build_schedule(metrics, tentative_state["facts"], tentative_state["constraints"])
                if "budget" in affected_areas:
                    new_plan["budget"] = planner.build_budget(
                        tentative_state["facts"],
                        new_plan["venue"],
                        new_plan["food"],
                        new_plan["judging"],
                        tentative_state["fixed_costs"],
                        tentative_state["optional_requests"]
                    )

                # Section 9d: Feasibility check on tentative plan
                temp_checks = checker.run_all_checks(new_plan, tentative_state["constraints"])
                failing_checks = [c for c in temp_checks if not c["passed"]]

                if failing_checks:
                    # Try adaptation (e.g. cheaper food option)
                    llm.log_code("Tentative plan failed checks. Attempting adaptation...")
                    if len(tentative_state["food_options"]) > 1:
                        new_plan["food"] = planner.build_food(metrics, tentative_state["food_options"], tentative_state["constraints"], prefer_cheapest=True)
                        new_plan["budget"] = planner.build_budget(
                            tentative_state["facts"],
                            new_plan["venue"],
                            new_plan["food"],
                            new_plan["judging"],
                            tentative_state["fixed_costs"],
                            tentative_state["optional_requests"]
                        )
                        temp_checks = checker.run_all_checks(new_plan, tentative_state["constraints"])
                        failing_checks = [c for c in temp_checks if not c["passed"]]

                if failing_checks:
                    fail_desc = "; ".join(f"{c['name']} ({c['detail']})" for c in failing_checks)
                    rej_reason = f"Authorized change rendered plan infeasible: {fail_desc}"
                    llm.log_code(f"REJECTED msg #{new_m['id']} ({meta.get('sender')}): {rej_reason}")
                    state["rejected_messages"].append({"msg_id": new_m["id"], "sender": meta.get("sender"), "reason": rej_reason})
                    # Revert to old plan
                    state["plan"] = old_plan
                else:
                    state = tentative_state
                    state["plan"] = new_plan
                    # Diff
                    diff_items = generate_diff(old_plan, new_plan)
                    state["diff"] = diff_items
                    llm.log_code(f"Plan updated. What changed:\n" + "\n".join(f"  * {d}" for d in diff_items))

            elif verdict == "REJECT":
                state["rejected_messages"].append({"msg_id": new_m["id"], "sender": meta.get("sender"), "reason": reason})
            elif verdict == "IGNORE":
                state["ignored_messages"].append({"msg_id": new_m["id"], "sender": meta.get("sender"), "reason": reason})

            state["processed_hashes"].append(new_m["hash"])

        plan = state["plan"]

    # Step 4: Run the 6 judges' checks
    check_results = checker.run_all_checks(plan, state.get("constraints", []))

    # Step 5: Save State
    state_mgr.save_state(state)

    total_time = time.time() - start_time

    # Step 6: Print Plan and Terminal Outputs
    print("\n" + format_plan_summary(plan))

    print("\n" + "=" * 70)
    print("                   INTEGRITY CHECKS (JUDGES' VERDICT)")
    print("=" * 70)
    all_passed = True
    for c in check_results:
        status = "[PASS]" if c["passed"] else "[FAIL]"
        if not c["passed"]:
            all_passed = False
        print(f"{status} Check {c['id']}: {c['name']} - {c['detail']}")
    print("=" * 70)

    # Save outputs to disk
    save_outputs(plan, check_results, state, total_time)

    # Summary Line as required by Section 12
    print(f"\nTOTAL TOKENS: {llm.get_total_tokens()} | MODEL CALLS: {llm.get_model_call_count()} | RUN TIME: {total_time:.2f}s")
    print(f"Artifacts saved to {config.OUTPUT_DIR}/ (plan.json, trace.txt, final_report.md)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python main.py <messages.txt>")
        sys.exit(1)
    run(sys.argv[1])
