"""Sky Huddle: Streamlit app for the Challenge 2 multi-agent negotiation.

Run:  streamlit run app.py

The UI reads audit logs (one JSON per run). Real runs go in logs/. Until the
pipeline exists it falls back to fixtures/sample_logs/. Log format: docs/LOG_FORMAT.md
"""
import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from ui.replay import replay_html

ROOT = Path(__file__).parent
LOG_DIRS = [ROOT / "logs", ROOT / "fixtures" / "sample_logs"]
DECISIONS = ROOT / "logs" / "decisions"
AGENTS = {"atc": ("Ava", "ATC"), "pilot": ("Pip", "Pilot"), "ground": ("Gus", "Ground ops")}
COST_PER_MIN_SOURCE = ("Airlines for America: U.S. Passenger Carrier Delay Costs",
                       "https://www.airlines.org/dataset/u-s-passenger-carrier-delay-costs/")

st.set_page_config(page_title="Sky Huddle", page_icon="✈️", layout="wide")
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Pixelify+Sans:wght@500;700&family=Poppins:wght@400;500;600&display=swap');
html, body, [class*="css"], .stMarkdown, p, li, label {font-family: 'Poppins', sans-serif;}
h1, h2, h3 {font-family: 'Pixelify Sans', monospace !important; letter-spacing: .02em;}
.badge {display:inline-block;padding:2px 10px;border:3px solid #1b1f3b;font-family:'Pixelify Sans',monospace;font-size:16px;box-shadow:3px 3px 0 #1b1f3b;}
.b-consensus {background:#bff0c8;} .b-fallback {background:#ffc2c4;} .b-escalation {background:#e5484d;color:#fff;}
.card {border:3px solid #1b1f3b;padding:10px 12px;margin-bottom:8px;background:#fff;box-shadow:3px 3px 0 #1b1f3b;}
.ok {background:#e9f9ec;border-color:#1b1f3b;} .no {background:#ffecec;}
.sim {color:#7c3aed;font-weight:600;font-size:12px;} .real {color:#1e7d34;font-weight:600;font-size:12px;}
</style>
""", unsafe_allow_html=True)


# ---------- data ----------
@st.cache_data(ttl=5)
def list_logs():
    found = {}
    for d in LOG_DIRS:
        if d.exists():
            for p in sorted(d.glob("*.json")):
                try:
                    log = json.loads(p.read_text())
                except json.JSONDecodeError:
                    continue
                if "run_id" in log and "scenario" in log:
                    found[f"{log.get('label') or log['run_id']}  ({p.parent.name})"] = str(p)
    return found


def load(path):
    return json.loads(Path(path).read_text())


def benchmark():
    for p in [ROOT / "logs" / "benchmark.json", ROOT / "fixtures" / "sample_benchmark.json"]:
        if p.exists():
            return json.loads(p.read_text()), p
    return None, None


def outcome_badge(out):
    t = out["type"]
    text = {"consensus": "Agent consensus", "fallback": "Fallback (not consensus)", "escalation": "Escalated to human"}[t]
    return f'<span class="badge b-{t}">{text}</span>'


def try_pipeline_run(mode, flight=None, date=None):
    """Calls Damien's coordinator if it exists. Contract in docs/LOG_FORMAT.md."""
    try:
        import coordinator  # noqa: WPS433
    except ImportError:
        st.info("The pipeline isn't in the repo yet (no coordinator.py). Showing saved runs only.")
        return None
    try:
        if mode == "random":
            return coordinator.run(random=True)
        return coordinator.run(flight=flight, date=date)
    except Exception as e:  # show the failure, never crash the demo
        st.error(f"Run failed: {e}. The saved runs below still work.")
        return None


# ---------- sidebar ----------
st.sidebar.title("Sky Huddle")
page = st.sidebar.radio("Page", ["Story", "Negotiation", "Pixel replay", "Benchmark"], index=1)
logs = list_logs()
if not logs:
    st.error("No audit logs found. Run `python fixtures/make_sample_logs.py`.")
    st.stop()
choice = st.sidebar.selectbox("Run to show", list(logs))
log = load(logs[choice])
st.sidebar.caption(f"run_id `{log['run_id']}`")
if log.get("sample"):
    st.sidebar.warning("Sample log for UI development. Not a real agent run.")

st.sidebar.divider()
st.sidebar.subheader("New run")
if st.sidebar.button("Run a random qualifying row"):
    new = try_pipeline_run("random")
    if new:
        list_logs.clear()
        st.sidebar.success(f"Done: {new.get('run_id')}. Pick it above.")
with st.sidebar.form("search"):
    f = st.text_input("Flight (e.g. AA1344)")
    d = st.text_input("Date (YYYY-MM-DD)", "2015-01-01")
    if st.form_submit_button("Run this flight"):
        new = try_pipeline_run("search", f, d)
        if new:
            list_logs.clear()
            st.success(f"Done: {new.get('run_id')}. Pick it in the list.")

H = log["scenario"]["historical"]
SIM = log["scenario"].get("simulated", {})
out = log["outcome"]
cands = {c["id"]: c for c in log.get("candidates", [])}
costs = log.get("costs", {})
r1 = next((r for r in log.get("rounds", []) if r["round"] == 1), None)
r2 = next((r for r in log.get("rounds", []) if r["round"] == 2), None)
cp = log.get("compromise")
check_set = "before_concessions" if out["type"] == "fallback" else "after_concessions"


# ---------- pages ----------
if page == "Story":
    st.title("Sky Huddle")
    st.subheader("Three AI agents settle a flight disruption in two rounds. Code keeps it safe.")
    c1, c2 = st.columns([3, 2])
    with c1:
        st.markdown(f"""
**Who it's for.** The airline hub duty manager. Today, when weather or a late aircraft hits, they phone the
tower, the crew and ramp control one by one to agree a landing slot, holding and a gate.

**Why it matters.** Every minute of aircraft time costs U.S. airlines about **$100.76** (2024 average for taxi plus
airborne time), per [{COST_PER_MIN_SOURCE[0]}]({COST_PER_MIN_SOURCE[1]}). Slow phone calls mean more holding and knock-on delays.

**What we built.** ATC, Pilot and Ground agents each get their own prompt and private state. They offer plans and
concessions in round 1. A plain-code coordinator applies the concessions and freezes one proposal. They vote in round 2.
A deterministic checker blocks anything unsafe, a rulebook decides if they don't agree, and the duty manager approves.
""")
    with c2:
        st.graphviz_chart("""
digraph G { rankdir=LR; node [shape=box, style="filled", fontname="Helvetica", fillcolor="#f3f8fd"];
 data [label="flights.csv row\\n(real)", fillcolor="#bff0c8"]; sim [label="Simulated state\\n(gates, fuel, crew)", fillcolor="#e9d5ff"];
 cand [label="Candidates (max 8)"]; chk [label="Checker\\n(hard rules)", fillcolor="#ffe2a8"];
 atc [label="ATC agent"]; pil [label="Pilot agent"]; gnd [label="Ground agent"];
 coord [label="Coordinator\\n2 rounds", fillcolor="#ffe2a8"]; fb [label="Rulebook\\nfallback", fillcolor="#ffc2c4"]; hum [label="Duty manager\\napproves", fillcolor="#bff0c8"];
 data -> cand; sim -> cand; cand -> chk; chk -> atc; chk -> pil; chk -> gnd; atc -> coord; pil -> coord; gnd -> coord;
 coord -> chk [style=dashed, label="recheck"]; coord -> hum; coord -> fb [label="no deal"]; fb -> hum; }
""")
    b, bp = benchmark()
    if b:
        st.subheader("Results")
        if b.get("sample"):
            st.warning(b.get("note", "Sample numbers"))
        a = b["agents"]
        m = st.columns(5)
        m[0].metric("Consensus in 2 rounds", f"{a['consensus']}/{a['completed']}")
        m[1].metric("Fallback", a["fallback"])
        m[2].metric("Accepted unsafe plans", a["accepted_violations"])
        m[3].metric("Cost gap vs solver", f"{b['cost_vs_solver_gap_pct']}%")
        m[4].metric("Simple heuristic infeasible", f"{b['heuristic']['infeasible_rate_pct']}%")
    st.caption("Real: the flight row from flights.csv. Simulated and labelled: gates, fuel, crew, slots. "
               "Checks are simplified and are not full FAA compliance.")

elif page == "Negotiation":
    st.title(f"{H['carrier']} {H['flight']}  {H['origin']} → {H['destination']}")
    st.markdown(outcome_badge(out), unsafe_allow_html=True)
    st.write("")

    # 2. Historical vs simulated
    st.header("1. Scenario")
    a, b = st.columns(2)
    with a:
        st.markdown('<span class="real">REAL DATA · flights.csv</span>', unsafe_allow_html=True)
        st.dataframe(pd.DataFrame(H.items(), columns=["field", "value"]).astype(str), hide_index=True, use_container_width=True)
    with b:
        st.markdown('<span class="sim">SIMULATED · seeded by scenario ID</span>', unsafe_allow_html=True)
        for k, v in SIM.items():
            name = AGENTS.get(k, (k, ""))[0]
            st.markdown(f"**{name}** (private to this agent)")
            st.json(v, expanded=False)

    # 3. Rounds
    st.header("2. Round 1: offers and concessions")
    if r1:
        cols = st.columns(3)
        for col, o in zip(cols, r1["offers"]):
            n, role = AGENTS[o["agent"]]
            with col:
                conc = ", ".join(f"{c['id']} ({c['target']})" for c in o["concessions"]) or "none"
                st.markdown(f"""<div class="card"><b>{n} · {role}</b><br>
Prefers <b>{o['preferred']}</b> · accepts {", ".join(o['acceptable'])}<br>
Cites: {", ".join(o['constraints_cited'])}<br>Concession: <b>{conc}</b><br>
<i>{o['rationale']}</i><br><small>{o.get('latency_s', '?')} s</small></div>""", unsafe_allow_html=True)
    else:
        st.info("No agent rounds: nothing passed the checker, so the run escalated straight to the duty manager.")

    if cp:
        st.subheader("Coordinator compromise (plain code)")
        st.markdown(
            f"Feasible before concessions: **{', '.join(cp['feasible_before']) or 'none'}** · "
            f"after: **{', '.join(cp['feasible_after'])}** · in all three acceptable sets: **{', '.join(cp['in_all_acceptable']) or 'none'}**  \n"
            f"Rule: {cp['rule']}. Frozen proposal **v{cp['proposal']['version']} = {cp['proposal']['candidate']}**.")
        if out.get("concessions_that_unlocked"):
            st.success("Unlocked by: " + " + ".join(out["concessions_that_unlocked"]))

    if r2:
        st.header("3. Round 2: final vote")
        cols = st.columns(3)
        for col, v in zip(cols, r2["votes"]):
            n, role = AGENTS[v["agent"]]
            icon = {"accept": "✅", "reject": "❌", "abstain": "⌛"}[v["vote"]]
            col.markdown(f'<div class="card {"ok" if v["vote"] == "accept" else "no"}">{icon} <b>{n}</b>: {v["vote"]} v{v["proposal_version"]}<br><i>{v["rationale"]}</i></div>',
                         unsafe_allow_html=True)

    # 4. Checks
    st.header("4. Hard checks")
    fc = out.get("final_candidate")
    if fc:
        st.caption(f"On the final plan {fc} ({'base state, no unconfirmed concessions' if out['type'] == 'fallback' else 'with agreed concessions'})")
        cc = st.columns(4)
        for i, r in enumerate(log["checks"][check_set][fc]):
            cc[i % 4].markdown(f'<div class="card {"ok" if r["passed"] else "no"}"><b>{"✓" if r["passed"] else "✗"} {r["rule_id"]}</b><br>{r["explanation"]}<br><small>{r["basis"]}</small></div>',
                               unsafe_allow_html=True)
    with st.expander("All candidates × all checks"):
        which = st.radio("State", ["before_concessions", "after_concessions"], horizontal=True)
        rows = []
        for cid, rs in log["checks"][which].items():
            c = cands[cid]
            row = {"id": cid, "land": c["landing"], "gate": c["gate"], "hold": c["extra_holding_min"]}
            row.update({r["rule_id"]: "✓" if r["passed"] else "✗" for r in rs})
            row["cost $"] = costs[cid]["total_usd"]
            rows.append(row)
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

    # 5. Final
    st.header("5. Final plan")
    if fc:
        c, k = cands[fc], costs[fc]
        m = st.columns(5)
        m[0].metric("Plan", fc)
        m[1].metric("Land", c["landing"])
        m[2].metric("Gate", c["gate"])
        m[3].metric("Extra holding", f"{c['extra_holding_min']} min")
        m[4].metric("Simulated cost", f"${k['total_usd']:,}")
        st.dataframe(pd.DataFrame([k]), hide_index=True)
        bl = log.get("baselines", {})
        if bl:
            h = bl.get("heuristic", {})
            st.caption(f"Solver on the same options: {bl.get('solver', {}).get('candidate')} · "
                       f"Simple heuristic ({h.get('plan', '')}): {'feasible' if h.get('feasible') else 'infeasible, fails ' + ', '.join(h.get('failed', []))}")
    st.markdown(f"**Why:** {out['reason']}")

    st.subheader("Duty manager decision")
    key = f"decision-{log['run_id']}"
    saved = DECISIONS / f"{log['run_id']}.json"
    if saved.exists() and key not in st.session_state:
        st.session_state[key] = json.loads(saved.read_text())
    if key in st.session_state:
        dsn = st.session_state[key]
        (st.success if dsn["approved"] else st.error)(f"{'Approved' if dsn['approved'] else 'Rejected'} at {dsn['at']}. {dsn.get('note', '')}")
    else:
        note = st.text_input("Note (optional)")
        x, y, _ = st.columns([1, 1, 4])
        for btn, ok in [(x, True), (y, False)]:
            if btn.button("Approve" if ok else "Reject", type="primary" if ok else "secondary", disabled=not fc and ok):
                dsn = {"approved": ok, "at": datetime.now().strftime("%H:%M:%S"), "note": note,
                       "run_id": log["run_id"], "plan": fc}
                st.session_state[key] = dsn
                DECISIONS.mkdir(parents=True, exist_ok=True)
                saved.write_text(json.dumps(dsn, indent=2))
                st.rerun()
        st.caption("Rejecting ends this run. A rerun gets a new run ID.")
    s = log.get("stats", {})
    st.caption(f"API calls {s.get('api_calls')} · retries {s.get('retries')} · total {s.get('total_latency_s')} s")
    with st.expander("Raw audit log JSON"):
        st.json(log)

elif page == "Pixel replay":
    st.title("Pixel replay")
    st.caption("Same audit log, played back as the agents talking. Press Play inside the panel.")
    view = dict(log)
    key = f"decision-{log['run_id']}"
    if key in st.session_state:
        view["human_decision"] = {"approved": st.session_state[key]["approved"], "by": "duty manager",
                                  "note": st.session_state[key].get("note", "")}
    components.html(replay_html(view), height=1250, scrolling=True)

else:
    st.title("Benchmark")
    b, bp = benchmark()
    if not b:
        st.info("No benchmark yet. benchmark.py should write logs/benchmark.json.")
        st.stop()
    if b.get("sample"):
        st.warning(b.get("note"))
    st.caption(f"Source: {bp.relative_to(ROOT)}")
    s = b["scenarios"]
    st.markdown(f"**Scenario set:** {s['total']} seeded scenarios: {s['weather_only']} weather only, "
                f"{s['late_aircraft_only']} late aircraft only, {s['both']} both.")
    a = b["agents"]
    m = st.columns(4)
    m[0].metric("Agent runs completed", a["completed"])
    m[1].metric("Consensus", f"{a['consensus']} ({a['consensus'] / max(a['completed'], 1):.0%})")
    m[2].metric("Fallback / escalation", f"{a['fallback']} / {a['escalation']}")
    m[3].metric("Accepted unsafe plans", a["accepted_violations"])
    m = st.columns(4)
    m[0].metric("Mean latency", f"{a['mean_latency_s']} s")
    m[1].metric("Mean API calls", a["mean_api_calls"])
    m[2].metric("Cost gap vs solver", f"{b['cost_vs_solver_gap_pct']}%")
    m[3].metric("Heuristic infeasible", f"{b['heuristic']['infeasible_rate_pct']}%")
    det = b["deterministic"]
    st.markdown(f"**Deterministic runs (all {det['runs']}):** rulebook found a feasible plan in {det['fallback_feasible']}, escalated {det['escalations']}.")
    st.subheader("Failure tests")
    st.dataframe(pd.DataFrame(b["failure_tests"]), hide_index=True, use_container_width=True)
    st.caption("Agents are not expected to beat a central solver that knows every constraint. "
               "We measure how well they coordinate within bounds, and how traceable the agreement is.")
