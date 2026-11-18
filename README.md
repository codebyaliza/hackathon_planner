# ⚡ Hackathon Master Planner Agent

An autonomous, token-efficient AI agent system that reads unstructured message packs (emails, WhatsApp texts, notices in English and Roman Urdu) and produces a mathematically verified 4-hour hackathon master plan across **5 areas**:
1. **VENUE**
2. **FOOD & CATERING**
3. **JUDGING**
4. **SCHEDULE**
5. **BUDGET**

Built for hackathon judging: **Plain Python**, **few files**, **zero unnecessary abstractions**, and a clear mathematical architecture that team members can explain line-by-line.

---

## 🚀 The One Command

Per Hard Rule **R2**, run everything with a single command without flags or manual hints:

```bash
python main.py messages.txt
```

To launch the interactive judges' dashboard:
```bash
streamlit run app.py
```

---

## 🏗️ Architecture Diagram

```
                 [ messages.txt ] (English + Roman Urdu)
                        │
                        ▼
            ┌───────────────────────┐
            │  reader.py (Pure Code) │  <-- Deterministic message splitting
            └───────────┬───────────┘
                        │
                        ▼
            ┌───────────────────────┐
            │   Reading Call (#1)   │  <-- Area: "reading" (LLM extraction)
            └───────────┬───────────┘
                        │
                        ▼
            ┌───────────────────────┐
            │  validator.py (Code)  │  <-- Catch wrong messages (Claims, Authority, Dates)
            └───────────┬───────────┘
                        │
                        ▼
            ┌───────────────────────┐
            │  planner.py (Code)    │  <-- Exact math, selection, timetable builder
            └───────────┬───────────┘
                        │
                        ▼
            ┌───────────────────────┐
            │  checker.py (Code)    │  <-- The 6 Judges' Checks (PASS / FAIL)
            └───────────┬───────────┘
                        │
        ┌───────────────┴───────────────┐
        ▼                               ▼
[ Terminal Output + Trace ]     [ output/ & Streamlit UI ]
- Token accounting (API exact)  - plan.json
- [CODE] audit lines            - trace.txt
- 6 check verdicts              - final_report.md
```

---

## 📁 File Structure: Purpose & What Breaks Without It

| File | Purpose | What Breaks If Removed? |
| :--- | :--- | :--- |
| `main.py` | Single command runner. Automates full run vs update detection, calls builders, prints trace, and saves artifacts. | The user would have no single command entry point. Update detection and output generation would not execute. |
| `llm.py` | LLM API caller with real token tracking, 25s timeout, 1 retry on invalid JSON, and a 5-call update ceiling. | Real token usage reporting (Rule R3) would fail; model call timeouts and update call limits would not be enforced. |
| `reader.py` | Splits raw text into messages using pure code pattern matching; formats JSON extraction prompts. | Unseen message pack formats would fail to parse, or tokens would be wasted using an LLM to split text lines. |
| `validator.py`| Enforces authority rules, detects contradictory claims, and resolves newest vs outdated dates. | Bad messages (unauthorized budget cuts, vendor box shortages) would slip into the plan, causing disqualification. |
| `planner.py` | Deterministic builders for derived metrics, venue selection, food pricing, timeline blocks, and budget. | Mathematical errors, scheduling overlaps, and unverified costs would occur if delegated to a probabilistic LLM. |
| `checker.py` | The 6 independent integrity checks (totals, budget cap, venue size, schedule duration, judge count, areas). | No automated verification that the plan satisfies all hackathon judging criteria. |
| `state.py` | Persists facts, messages, plan, and processed hashes to `state.json`. | Incremental updates (Rule R4) would be impossible; every run would wipe previous context and rebuild from scratch. |
| `config.py` | Model settings and organizer design defaults (buffers, opening/closing lengths, timeouts). | Hardcoded constants would clutter code; switching between Groq, OpenRouter, and Ollama would require code edits. |
| `app.py` | Clean Streamlit dashboard for visualizing the 5 plan cards, timeline, audit badges, trace, and diffs. | Judges would have no interactive UI to inspect the plan, timeline, and rejected message logs (Rule R8). |

---

## 🧠 Core Design Principle: Model Only for Reading

### Why Not Let the Model Plan Everything?
1. **Token Efficiency:** A full run uses **exactly 1 model call** (reading). A standard update uses **1 model call**. Token cost stays minimal.
2. **Mathematical Accuracy:** LLMs are notoriously prone to arithmetic mistakes, halluncinating capacity numbers, or causing 15-minute timetable drift. Plain Python code performs exact math ($40 \text{ students} / 4 = 10 \text{ teams}$).
3. **Honest Area Tags:** Per Rule R3, area-tagged calls (`venue`, `food`, etc.) are made **only** when an area encounters a novel constraint of type `other` that deterministic rules cannot evaluate.

---

## 🛡️ Catching the Wrong Message (Validator)

The validator audits every message using 4 generic code rules:

1. **Contradictory Claims (Section 9a):**
   - If a vendor says: *"We rounded down the order to 25 food boxes"*, but on-site headcount is 49 ($40 \text{ students} + 6 \text{ staff} + 3 \text{ judges}$), the validator rejects:
   > `REJECTED msg #5 (catering@delightfoods.com): Quantity claim (25 boxes) is below headcount (49); would leave 24 people without food`

2. **Role Authority (Section 9b):**
   - **Vendors & Venues** may only change their own prices and options. If a vendor tries to alter budget total or student headcount, it is rejected immediately.
   - **Students & Unknown Senders** can only submit optional requests (e.g. Red Bull drinks). If they attempt to slash the event budget, it is rejected.
   - Only **organizers, finance, and judge coordinators** can modify budget, headcount, or schedule constraints.

3. **Outdated Dates (Section 9c):**
   - If a message dated `2026-11-19` attempts to set a price that was already updated on `2026-11-24`, it is rejected as outdated.

4. **Feasibility Gate (Section 9d):**
   - If an authorized message causes the plan to become infeasible (e.g. costs exceed budget even after adapting to cheaper food options), the change is rejected with the exact failing check.

---

## 🔄 Dependency Map & Update Flow (Rules R4 & R7)

When new messages are appended to `messages.txt`:
1. `main.py` detects unseen message hashes.
2. Only the new message is processed (using compact known fact keys to save prompt tokens).
3. The Dependency Map activates:
   - `students / team_size / staff / judging` ➔ **Judging, Venue, Food, Budget, Schedule**
   - `venue options / prices` ➔ **Venue, Budget**
   - `food options / prices` ➔ **Food, Budget**
   - `fixed_costs / budget_total` ➔ **Budget**
   - `schedule constraints / event_hours` ➔ **Schedule**
4. Only the **affected areas** are recomputed; untouched areas preserve their state.
5. The system emits a **What Changed Diff** (e.g., `Fixed Cost: 150 -> 220`).
6. Maximum **5 model calls** allowed during an update (enforced by a hard counter).

---

## ⚖️ The 6 Judges' Integrity Checks

1. **Correct Figures:** Independently recalculates on-site headcount, catering totals, and budget arithmetic to verify they match the plan.
2. **Within Budget:** Total expenditure $\le$ approved budget limit.
3. **Venue Fits:** Chosen venue capacity $\ge$ headcount on site, and all required features are present.
4. **Schedule Valid:** Blocks sum to exactly `event_hours`, no overlapping times, code freeze strictly precedes judging, and judging duration $\ge$ required minutes.
5. **Enough Judges:** Available judges $\ge$ required judges, and team load per judge $\le$ maximum allowed.
6. **All Areas Covered:** Confirms Venue, Food, Judging, Schedule, and Budget are all generated.

---

## ⚙️ Setup & Configuration

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
2. **Configure environment:**
   Create `.env` (or copy `.env.example`):
   ```ini
   LLM_BASE_URL=https://api.groq.com/openai/v1
   LLM_API_KEY=your_api_key_here
   LLM_MODEL=llama-3.3-70b-versatile
   ```
   *Compatible with Groq, OpenRouter, or local Ollama (`http://localhost:11434/v1`).*

3. **Run unit tests (no model calls needed):**
   ```bash
   python tests/test_planner.py
   ```

4. **Run a test pack:**
   ```bash
   python main.py samples/pack_basic.txt
   ```
