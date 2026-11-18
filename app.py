"""
app.py - User Interface for Hackathon Planner

WHY THIS FILE EXISTS:
Implements Hard Rule R8 and Section 14.
Provides a clean, intuitive UI for organizers and judges.
Supports TWO runtime modes:
1. 'streamlit run app.py' (when Streamlit is installed)
2. 'python app.py' (built-in zero-dependency local web dashboard on port 8501)
Both modes use the exact same logic and data from main.py, state.py, and checker.py.
"""

import sys
import os
import json
import time
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config
import state as state_mgr
import checker
import main as main_orchestrator
import reader

# Try importing Streamlit
try:
    import streamlit as st
    HAS_STREAMLIT = True
except ImportError:
    HAS_STREAMLIT = False


# ==============================================================================
# MODE 1: STREAMLIT DASHBOARD (Run via `streamlit run app.py`)
# ==============================================================================
def render_streamlit():
    st.set_page_config(page_title="Hackathon Planner Agent", layout="wide", page_icon="⚡")

    current_pack_file = config.PROJECT_ROOT / "messages.txt"

    def run_pipeline(filepath: str):
        with st.spinner("Processing messages through Planner Agent..."):
            main_orchestrator.run(filepath)
        st.rerun()

    # Sidebar
    st.sidebar.title("⚡ Hackathon Planner")
    st.sidebar.markdown("**Single-Command Autonomous Agent**")

    uploaded_pack = st.sidebar.file_uploader("Upload New Message Pack (.txt)", type=["txt"])
    if uploaded_pack is not None:
        if st.sidebar.button("Load Pack & Run Full Planning", use_container_width=True):
            content = uploaded_pack.getvalue().decode("utf-8")
            with open(current_pack_file, "w", encoding="utf-8") as f:
                f.write(content)
            state_mgr.reset_state()
            run_pipeline(str(current_pack_file))

    st.sidebar.markdown("---")
    st.sidebar.subheader("📩 Append New Message (Update)")
    new_msg_text = st.sidebar.text_area("Paste new email / WhatsApp / notice:", height=130)
    if st.sidebar.button("Add & Update Plan", use_container_width=True):
        if new_msg_text.strip():
            with open(current_pack_file, "a", encoding="utf-8") as f:
                f.write(f"\n\n---\n{new_msg_text.strip()}\n")
            run_pipeline(str(current_pack_file))
        else:
            st.sidebar.warning("Please enter message text before submitting.")

    st.sidebar.markdown("---")
    if config.OUTPUT_REPORT_FILE.exists():
        with open(config.OUTPUT_REPORT_FILE, "r", encoding="utf-8") as rf:
            report_data = rf.read()
        st.sidebar.download_button(
            label="📥 Download Final Report (.md)",
            data=report_data,
            file_name="final_report.md",
            mime="text/markdown",
            use_container_width=True
        )

    # Load State
    state_data = state_mgr.load_state()
    if state_data is None or not state_data.get("plan"):
        st.info("👋 Welcome! Upload a message pack or run `python main.py messages.txt` in terminal to start.")
        st.stop()

    plan = state_data.get("plan", {})
    metrics = plan.get("metrics", {})
    constraints = state_data.get("constraints", [])
    checks = checker.run_all_checks(plan, constraints)
    all_checks_passed = all(c["passed"] for c in checks)

    # Top Bar
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Model", config.LLM_MODEL)
    total_tokens = 0
    if config.OUTPUT_TRACE_FILE.exists():
        with open(config.OUTPUT_TRACE_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if "TOTAL TOKENS:" in line:
                    for p in line.split("|"):
                        if "TOTAL TOKENS:" in p:
                            total_tokens = p.replace("TOTAL TOKENS:", "").strip()
    c2.metric("Total Tokens", total_tokens)
    c3.metric("Processed Messages", len(state_data.get("messages", [])))
    c4.metric("Rejected Messages", len(state_data.get("rejected_messages", [])))
    c5.metric("System Health", "✅ ALL PASS" if all_checks_passed else "❌ CHECKS FAILED")

    st.markdown("---")

    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📋 Plan (5 Areas)", "🕒 Timeline", "💰 Budget", "📬 Messages & Rejections", "🔍 Model Trace", "🔄 Changes & Dependencies"
    ])

    with tab1:
        st.subheader("Hackathon Master Plan")
        curr = plan.get("currency") or plan.get("budget", {}).get("currency")
        c = "Rs " if curr == "Rs" else ""

        col1, col2, col3 = st.columns(3)
        v = plan.get("venue", {})
        col1.markdown(f"### 🏛️ 1. Venue\n**{v.get('name')}** (Cap: {v.get('capacity')})\nCost: {c}{v.get('cost', 0):.2f}\n*Msg #{v.get('source_msg_id', 'N/A')}*")
        f = plan.get("food", {})
        col2.markdown(f"### 🍱 2. Food\n**{f.get('name')}** ({f.get('quantity')} heads)\nCost: {c}{f.get('total_cost', 0):.2f}\n*Msg #{f.get('source_msg_id', 'N/A')}*")
        j = plan.get("judging", {})
        col3.markdown(f"### ⚖️ 3. Judging\n**{j.get('judges_needed')} Judges** (Fee: {c}{j.get('judge_fee', 0):.2f})\nHonorarium: {c}{j.get('total_honorarium', 0):.2f}")

        col4, col5 = st.columns(2)
        s = plan.get("schedule", {})
        col4.markdown(f"### ⏱️ 4. Schedule\nDuration: {s.get('event_hours')}h ({s.get('total_minutes')}m)\nJudging: {s.get('judging_duration')}m")
        b = plan.get("budget", {})
        col5.markdown(f"### 💵 5. Budget\nTotal Spent: {c}{b.get('total_spent', 0):.2f} / {c}{b.get('budget_total', 0):.2f}\nRemaining: {c}{b.get('remaining', 0):.2f}")

        st.markdown("---")
        st.subheader("Integrity Checks")
        for chk in checks:
            badge = "🟢 PASS" if chk["passed"] else "🔴 FAIL"
            st.markdown(f"- **Check {chk['id']} ({chk['name']}):** {badge} — *{chk['detail']}*")

    with tab2:
        st.subheader("Event Schedule Blocks")
        blocks = plan.get("schedule", {}).get("blocks", [])
        if blocks:
            st.table([{"Name": bl["name"], "Start": bl["start_time"], "End": bl["end_time"], "Duration": f"{bl['duration']}m"} for bl in blocks])

    with tab3:
        st.subheader("Budget & Expenses")
        b = plan.get("budget", {})
        curr = plan.get("currency") or b.get("currency")
        c = "Rs " if curr == "Rs" else ""
        if b.get("budget_total", 0) > 0:
            st.progress(min(b.get("total_spent", 0) / b["budget_total"], 1.0))
        st.write(f"Total Spent: {c}{b.get('total_spent', 0):.2f} | Remaining: {c}{b.get('remaining', 0):.2f}")
        for fc in b.get("fixed_costs", []):
            st.write(f"- Fixed: {fc['item']}: {c}{fc['amount']:.2f}")

    with tab4:
        st.subheader("Message Audit Log")
        for m in state_data.get("messages", []):
            st.markdown(f"**Msg #{m['id']} [{m['status']}]:** {m.get('sender')} ({m.get('role')}) — *{m.get('reason')}*")
            st.caption(m.get("text", "")[:200])

    with tab5:
        st.subheader("Execution Trace Log")
        if config.OUTPUT_TRACE_FILE.exists():
            with open(config.OUTPUT_TRACE_FILE, "r", encoding="utf-8") as tf:
                st.text_area("Trace", tf.read(), height=400)

    with tab6:
        st.subheader("Dependency Map & Changes")
        st.markdown("- **Affected Areas:** " + ", ".join(state_data.get("affected_areas", ["None"])))
        for diff in state_data.get("diff", []):
            st.write(f"- 🔄 {diff}")


# ==============================================================================
# MODE 2: STANDALONE BUILT-IN WEB SERVER (Run via `python app.py`)
# ==============================================================================
def render_standalone():
    import http.server
    import socketserver
    import urllib.parse

    PORT = 8501

    class PlannerHTTPHandler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/download_report":
                if config.OUTPUT_REPORT_FILE.exists():
                    self.send_response(200)
                    self.send_header("Content-Type", "text/markdown; charset=utf-8")
                    self.send_header("Content-Disposition", "attachment; filename=final_report.md")
                    self.end_headers()
                    with open(config.OUTPUT_REPORT_FILE, "rb") as rf:
                        self.wfile.write(rf.read())
                    return
                else:
                    self.send_error(404, "Report not generated yet")
                    return

            state_data = state_mgr.load_state() or {}
            plan = state_data.get("plan", {})
            metrics = plan.get("metrics", {})
            constraints = state_data.get("constraints", [])
            checks = checker.run_all_checks(plan, constraints) if plan else []
            all_pass = all(c["passed"] for c in checks) if checks else False

            # Read trace
            trace_content = ""
            total_tokens = 0
            if config.OUTPUT_TRACE_FILE.exists():
                with open(config.OUTPUT_TRACE_FILE, "r", encoding="utf-8") as tf:
                    trace_content = tf.read()
                for line in trace_content.splitlines():
                    if "TOTAL TOKENS:" in line:
                        for part in line.split("|"):
                            if "TOTAL TOKENS:" in part:
                                total_tokens = part.replace("TOTAL TOKENS:", "").strip()

            v = plan.get("venue", {})
            f = plan.get("food", {})
            j = plan.get("judging", {})
            s = plan.get("schedule", {})
            b = plan.get("budget", {})
            curr = plan.get("currency") or b.get("currency")
            c = "Rs " if curr == "Rs" else ""

            html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Hackathon Planner Agent</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 0; background: #0f172a; color: #f8fafc; }}
  .container {{ display: flex; min-height: 100vh; }}
  .sidebar {{ width: 320px; background: #1e293b; padding: 24px; border-right: 1px solid #334155; }}
  .main {{ flex: 1; padding: 32px; overflow-y: auto; }}
  .top-bar {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 16px; margin-bottom: 24px; }}
  .metric-card {{ background: #1e293b; padding: 16px; border-radius: 8px; border: 1px solid #334155; }}
  .metric-card small {{ color: #94a3b8; font-size: 12px; text-transform: uppercase; }}
  .metric-card h3 {{ margin: 8px 0 0; font-size: 20px; }}
  .grid-3 {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-bottom: 16px; }}
  .grid-2 {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; margin-bottom: 16px; }}
  .card {{ background: #1e293b; padding: 20px; border-radius: 8px; border: 1px solid #334155; }}
  .badge {{ display: inline-block; padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 11px; }}
  .badge-pass {{ background: #065f46; color: #34d399; }}
  .badge-fail {{ background: #7f1d1d; color: #f87171; }}
  .badge-accept {{ background: #065f46; color: #34d399; }}
  .badge-reject {{ background: #7f1d1d; color: #f87171; }}
  .badge-super {{ background: #78350f; color: #fbbf24; }}
  .badge-ignore {{ background: #374151; color: #9ca3af; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 12px; }}
  th, td {{ padding: 10px 12px; text-align: left; border-bottom: 1px solid #334155; }}
  th {{ background: #0f172a; color: #94a3b8; font-size: 12px; text-transform: uppercase; }}
  textarea, button {{ width: 100%; padding: 10px; border-radius: 6px; font-family: inherit; margin-top: 8px; box-sizing: border-box; }}
  textarea {{ background: #0f172a; color: #fff; border: 1px solid #475569; }}
  button {{ background: #2563eb; color: #fff; border: none; font-weight: bold; cursor: pointer; }}
  button:hover {{ background: #1d4ed8; }}
  pre {{ background: #0f172a; padding: 16px; border-radius: 8px; overflow-x: auto; color: #38bdf8; font-size: 13px; }}
  .tabs {{ display: flex; gap: 8px; border-bottom: 1px solid #334155; margin-bottom: 20px; }}
  .tab {{ padding: 8px 16px; cursor: pointer; background: #1e293b; border-radius: 6px 6px 0 0; color: #94a3b8; }}
  .tab.active {{ background: #334155; color: #fff; font-weight: bold; }}
  .tab-content {{ display: none; }}
  .tab-content.active {{ display: block; }}
</style>
<script>
function showTab(id) {{
  document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  document.getElementById('btn-' + id).classList.add('active');
}}
</script>
</head>
<body>
<div class="container">
  <div class="sidebar">
    <h2>⚡ Planner Agent</h2>
    <p style="color:#94a3b8; font-size:13px;">Single-Command Autonomous Agent</p>
    <hr style="border-color:#334155; margin:20px 0;">
    <h3>📩 Append New Message</h3>
    <form method="POST" action="/update">
      <textarea name="message" rows="5" placeholder="e.g. Finance: Judge fee increased to 2500."></textarea>
      <button type="submit">Add & Update Plan</button>
    </form>
    <hr style="border-color:#334155; margin:20px 0;">
    <a href="/download_report" style="display:block; text-align:center; background:#334155; color:#fff; text-decoration:none; padding:10px; border-radius:6px; font-weight:bold;">📥 Download Final Report</a>
  </div>
  <div class="main">
    <div class="top-bar">
      <div class="metric-card"><small>Model</small><h3>{config.LLM_MODEL}</h3></div>
      <div class="metric-card"><small>Total Tokens</small><h3>{total_tokens}</h3></div>
      <div class="metric-card"><small>Messages</small><h3>{len(state_data.get('messages', []))}</h3></div>
      <div class="metric-card"><small>Rejections</small><h3>{len(state_data.get('rejected_messages', []))}</h3></div>
      <div class="metric-card"><small>Health</small><h3><span class="badge { 'badge-pass' if all_pass else 'badge-fail' }">{'ALL PASS' if all_pass else 'FAILED'}</span></h3></div>
    </div>

    <div class="tabs">
      <div class="tab active" id="btn-tab-plan" onclick="showTab('tab-plan')">📋 Plan</div>
      <div class="tab" id="btn-tab-timeline" onclick="showTab('tab-timeline')">🕒 Timeline</div>
      <div class="tab" id="btn-tab-budget" onclick="showTab('tab-budget')">💰 Budget</div>
      <div class="tab" id="btn-tab-messages" onclick="showTab('tab-messages')">📬 Messages & Rejections</div>
      <div class="tab" id="btn-tab-trace" onclick="showTab('tab-trace')">🔍 Trace</div>
      <div class="tab" id="btn-tab-changes" onclick="showTab('tab-changes')">🔄 Changes & Diff</div>
    </div>

    <!-- TAB 1: PLAN -->
    <div id="tab-plan" class="tab-content active">
      <div class="grid-3">
        <div class="card">
          <h4>🏛️ 1. Venue</h4>
          <p><strong>{v.get('name', 'N/A')}</strong></p>
          <p>Capacity: {v.get('capacity', 0)} (Required: {metrics.get('headcount_on_site', 0)})</p>
          <p>Cost: {c}{v.get('cost', 0):.2f}</p>
        </div>
        <div class="card">
          <h4>🍱 2. Food & Catering</h4>
          <p><strong>{f.get('name', 'N/A')}</strong></p>
          <p>Qty: {f.get('quantity', 0)} heads @ {c}{f.get('price_per_head', 0):.2f}</p>
          <p>Total: {c}{f.get('total_cost', 0):.2f}</p>
        </div>
        <div class="card">
          <h4>⚖️ 3. Judging</h4>
          <p><strong>{j.get('judges_needed', 0)} Judges Needed</strong> / {j.get('judges_available', 0)} Available</p>
          <p>Fee: {c}{j.get('judge_fee', 0):.2f} | Honorarium: {c}{j.get('total_honorarium', 0):.2f}</p>
        </div>
      </div>
      <div class="grid-2">
        <div class="card">
          <h4>⏱️ 4. Schedule</h4>
          <p>Duration: {s.get('event_hours', 4)} Hours ({s.get('total_minutes', 240)} mins)</p>
          <p>Judging Block: {s.get('judging_duration', 0)} mins</p>
        </div>
        <div class="card">
          <h4>💵 5. Budget Summary</h4>
          <p>Budget Cap: {c}{b.get('budget_total', 0):.2f}</p>
          <p>Total Spent: {c}{b.get('total_spent', 0):.2f} (Remaining: {c}{b.get('remaining', 0):.2f})</p>
        </div>
      </div>

      <div class="card">
        <h4>Integrity Checks (Judges' Verdict)</h4>
        <table>
          <thead><tr><th>Check</th><th>Verdict</th><th>Detail</th></tr></thead>
          <tbody>
            {''.join(f"<tr><td>Check {c['id']}: {c['name']}</td><td><span class='badge { 'badge-pass' if c['passed'] else 'badge-fail' }'>{'PASS' if c['passed'] else 'FAIL'}</span></td><td>{c['detail']}</td></tr>" for c in checks)}
          </tbody>
        </table>
      </div>
    </div>

    <!-- TAB 2: TIMELINE -->
    <div id="tab-timeline" class="tab-content">
      <div class="card">
        <h4>Event Timeline Blocks</h4>
        <table>
          <thead><tr><th>Time</th><th>Duration</th><th>Session Block</th><th>Category</th></tr></thead>
          <tbody>
            {''.join(f"<tr><td>{bl['start_time']} - {bl['end_time']}</td><td>{bl['duration']}m</td><td><strong>{bl['name']}</strong></td><td>{bl['type'].title()}</td></tr>" for bl in s.get('blocks', []))}
          </tbody>
        </table>
      </div>
    </div>

    <!-- TAB 3: BUDGET -->
    <div id="tab-budget" class="tab-content">
      <div class="card">
        <h4>Budget Breakdown</h4>
        <table>
          <thead><tr><th>Expense Item</th><th>Amount ({curr if curr else 'value'})</th></tr></thead>
          <tbody>
            <tr><td>Venue Rental</td><td>{c}{b.get('venue_cost', 0):.2f}</td></tr>
            <tr><td>Food & Catering</td><td>{c}{b.get('food_cost', 0):.2f}</td></tr>
            <tr><td>Judge Honorarium</td><td>{c}{b.get('judge_honorarium', 0):.2f}</td></tr>
            {''.join(f"<tr><td>Fixed: {fc['item']}</td><td>{c}{fc['amount']:.2f}</td></tr>" for fc in b.get('fixed_costs', []))}
            <tr style="font-weight:bold; background:#0f172a;"><td>TOTAL SPENT</td><td>{c}{b.get('total_spent', 0):.2f}</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- TAB 4: MESSAGES -->
    <div id="tab-messages" class="tab-content">
      <div class="card">
        <h4>Processed Messages & Audit Trail</h4>
        <table>
          <thead><tr><th>ID</th><th>Sender</th><th>Role</th><th>Status</th><th>Reason / Audit Note</th></tr></thead>
          <tbody>
            {''.join(f"<tr><td>#{m['id']}</td><td>{m.get('sender', 'Unknown')}</td><td>{m.get('role', 'unknown')}</td><td><span class='badge badge-{m['status'].lower()}'>{m['status']}</span></td><td>{m.get('reason', '')}</td></tr>" for m in state_data.get('messages', []))}
          </tbody>
        </table>
      </div>
    </div>

    <!-- TAB 5: TRACE -->
    <div id="tab-trace" class="tab-content">
      <div class="card">
        <h4>Execution Trace (API Usage & [CODE] Decisions)</h4>
        <pre>{trace_content}</pre>
      </div>
    </div>

    <!-- TAB 6: CHANGES -->
    <div id="tab-changes" class="tab-content">
      <div class="card">
        <h4>Dependency Map & Recent Updates</h4>
        <p><strong>Affected Areas:</strong> {', '.join(state_data.get('affected_areas', ['None']))}</p>
        <ul>
          {''.join(f"<li>🔄 {diff}</li>" for diff in state_data.get('diff', [])) if state_data.get('diff') else '<li>No plan changes recorded</li>'}
        </ul>
      </div>
    </div>

  </div>
</div>
</body>
</html>"""
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))

        def do_POST(self):
            if self.path == "/update":
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length).decode("utf-8")
                params = urllib.parse.parse_qs(body)
                new_msg = params.get("message", [""])[0].strip()
                if new_msg:
                    current_pack_file = config.PROJECT_ROOT / "messages.txt"
                    with open(current_pack_file, "a", encoding="utf-8") as f:
                        f.write(f"\n\n---\n{new_msg}\n")
                    main_orchestrator.run(str(current_pack_file))
                self.send_response(303)
                self.send_header("Location", "/")
                self.end_headers()

    print(f"\n🚀 Standalone Hackathon Planner Web UI running at http://localhost:{PORT}")
    print("Open http://localhost:8501 in your browser.")
    with socketserver.TCPServer(("", PORT), PlannerHTTPHandler) as httpd:
        httpd.serve_forever()


if __name__ == "__main__":
    if HAS_STREAMLIT and "streamlit" in sys.argv[0]:
        render_streamlit()
    else:
        # If user has streamlit and called `streamlit run app.py`
        try:
            import streamlit as st
            render_streamlit()
        except Exception:
            render_standalone()
