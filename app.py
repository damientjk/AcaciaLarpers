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
LOG_DIRS = [ROOT / "fixtures" / "cached", ROOT / "logs", ROOT / "fixtures" / "sample_logs"]
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
header[data-testid="stHeader"] {display:none;} footer {display:none;}
.block-container {padding-top: 1.6rem; max-width: 1500px;}
section[data-testid="stSidebar"] {border-right: 3px solid #1b1f3b;}
section[data-testid="stSidebar"] input {border: 2px solid #1b1f3b !important; border-radius: 3px !important; background: #fff !important;}
section[data-testid="stSidebar"] .stButton button {font-family:'Pixelify Sans',monospace; font-weight:700; border:3px solid #1b1f3b; border-radius:4px; box-shadow:3px 3px 0 #1b1f3b; background:#fff; color:#1b1f3b;}
section[data-testid="stSidebar"] .stButton button:hover {background:#ffd447; color:#1b1f3b;}
section[data-testid="stSidebar"] .stButton button:active {transform:translate(2px,2px); box-shadow:1px 1px 0 #1b1f3b;}
[data-testid="stMetric"] {background:#f3f8fd; border:3px solid #1b1f3b; box-shadow:3px 3px 0 #1b1f3b; padding:8px 12px;}
.badge {display:inline-block;padding:2px 10px;border:3px solid #1b1f3b;font-family:'Pixelify Sans',monospace;font-size:16px;box-shadow:3px 3px 0 #1b1f3b;}
.b-consensus {background:#bff0c8;} .b-fallback {background:#ffc2c4;} .b-escalation {background:#e5484d;color:#fff;}
.card {border:3px solid #1b1f3b;padding:10px 12px;margin-bottom:8px;background:#fff;box-shadow:3px 3px 0 #1b1f3b;}
.ok {background:#e9f9ec;border-color:#1b1f3b;} .no {background:#ffecec;}
.sim {color:#7c3aed;font-weight:600;font-size:12px;} .real {color:#1e7d34;font-weight:600;font-size:12px;}
</style>
""", unsafe_allow_html=True)



# ---------- adapters: team format -> shape the UI and ui/replay.py expect ----------
def _as_list(x):
    return list(x) if isinstance(x, (list, tuple)) else ([] if x is None else [x])


def _by_id(x):
    """Accept {id: item} or [item with id]; return {id: item}."""
    if isinstance(x, dict):
        return x
    return {i["id"]: i for i in _as_list(x)}


def _concession(c):
    if isinstance(c, str):
        return {"id": c, "target": ""}
    c = dict(c)
    c["target"] = c.get("target") or ""
    return c


def normalize_log(raw):
    """Make a coordinator log (docs/LOG_FORMAT.md) safe for the UI. Tolerates missing optional
    fields, models dumped with None, candidates/costs given as lists, and string concessions."""
    log = dict(raw)
    log.setdefault("run_id", "unknown")
    log.setdefault("sample", False)
    sc = dict(log.get("scenario") or {})
    sc.setdefault("historical", {})
    sc.setdefault("simulated", {})
    log["scenario"] = sc
    cands = _by_id(log.get("candidates"))
    log["candidates"] = list(cands.values())
    log["costs"] = _by_id(log.get("costs")) if isinstance(log.get("costs"), list) else dict(log.get("costs") or {})
    chk = log.get("checks") or {}
    if isinstance(chk, dict) and not ({"before_concessions", "after_concessions"} & set(chk)):
        chk = {"before_concessions": chk, "after_concessions": chk}  # single check set
    chk = {k: dict(chk.get(k) or {}) for k in ("before_concessions", "after_concessions")}
    log["checks"] = chk
    rounds = []
    for r in _as_list(log.get("rounds")):
        r = dict(r)
        if "offers" in r:
            r["offers"] = [dict(o, concessions=[_concession(c) for c in _as_list(o.get("concessions"))],
                                acceptable=_as_list(o.get("acceptable")),
                                constraints_cited=_as_list(o.get("constraints_cited")),
                                rationale=o.get("rationale", ""), valid=o.get("valid", True))
                           for o in r["offers"]]
        if "votes" in r:
            r["votes"] = [dict(v, rationale=v.get("rationale", "")) for v in r["votes"]]
        rounds.append(r)
    log["rounds"] = rounds
    cp = log.get("compromise")
    if cp:
        cp = dict(cp)
        for k in ("feasible_before", "feasible_after", "in_all_acceptable"):
            cp[k] = _as_list(cp.get(k))
        cp["concessions_applied"] = [dict(_concession(c), agent=c.get("agent", "") if isinstance(c, dict) else "")
                                     for c in _as_list(cp.get("concessions_applied"))]
        cp.setdefault("rule", "")
        cp.setdefault("proposal", {"version": 1, "candidate": ""})
    log["compromise"] = cp or None
    out = dict(log.get("outcome") or {"type": "escalation", "final_candidate": None, "reason": "No outcome recorded."})
    out.setdefault("final_candidate", None)
    out.setdefault("reason", "")
    out["concessions_that_unlocked"] = _as_list(out.get("concessions_that_unlocked"))
    log["outcome"] = out
    log.setdefault("fallback", None)
    log.setdefault("baselines", {})
    log.setdefault("human_decision", None)
    log.setdefault("stats", {})
    return log


def normalize_benchmark(raw):
    """Fill gaps so the Benchmark and Story pages never KeyError on a partial benchmark.json."""
    b = dict(raw)
    a = dict(b.get("agents") or {})
    for k in ("completed", "consensus", "fallback", "escalation", "accepted_violations", "mean_api_calls", "mean_latency_s"):
        a.setdefault(k, 0)
    b["agents"] = a
    b.setdefault("scenarios", {})
    for k in ("total", "weather_only", "late_aircraft_only", "both"):
        b["scenarios"].setdefault(k, 0)
    b.setdefault("cost_vs_solver_gap_pct", 0)
    b["heuristic"] = dict(b.get("heuristic") or {}); b["heuristic"].setdefault("infeasible_rate_pct", 0)
    b["deterministic"] = dict(b.get("deterministic") or {})
    for k in ("runs", "fallback_feasible", "escalations"):
        b["deterministic"].setdefault(k, 0)
    b.setdefault("failure_tests", [])
    return b


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
                if isinstance(log, dict) and "run_id" in log and "scenario" in log:
                    log = normalize_log(log)
                    is_sample = bool(log.get("sample")) or d.name == "sample_logs"
                    tag = "SAMPLE · " if is_sample else ""
                    h = log.get("scenario", {}).get("historical", {})
                    auto = f"{h.get('carrier', '')}{h.get('flight', '')} {h.get('origin', '?')}→{h.get('destination', '?')} · {log['outcome']['type']}"
                    if log.get("fake_agents"):
                        auto += " · fake agents"
                    found[f"{tag}{log.get('label') or auto}  ({p.parent.name}, {log['run_id']})"] = (str(p), is_sample)
    return found


def load(path):
    return normalize_log(json.loads(Path(path).read_text()))


def benchmark():
    for p in [ROOT / "logs" / "benchmark.json", ROOT / "fixtures" / "cached" / "benchmark.json",
              ROOT / "fixtures" / "sample_benchmark.json"]:
        if p.exists():
            return normalize_benchmark(json.loads(p.read_text())), p
    return None, None


def outcome_badge(out):
    t = out["type"]
    text = {"consensus": "Agent consensus", "fallback": "Fallback (not consensus)", "escalation": "Escalated to human"}[t]
    return f'<span class="badge b-{t}">{text}</span>'


def try_pipeline_run(mode, flight=None, date=None):
    """Calls Damien's coordinator.run(random, flight, date, scenario_id, fake_agents).
    Without ANTHROPIC_API_KEY it runs with fake_agents=True (random agents, real checker)."""
    import os
    try:
        import coordinator  # noqa: WPS433
    except ImportError:
        st.info("The pipeline isn't in the repo yet (no coordinator.py). Showing saved runs only.")
        return None
    fake = not os.environ.get("ANTHROPIC_API_KEY")
    with st.status("Starting the negotiation…", expanded=True) as status:
        def progress(msg):  # called by coordinator.negotiate at each stage
            status.update(label=msg)
            st.write(msg)

        try:
            if mode == "random":
                res = coordinator.run(random=True, fake_agents=fake, progress=progress)
            else:
                res = coordinator.run(flight=flight, date=date, fake_agents=fake, progress=progress)
        except NotImplementedError:
            status.update(label="Pipeline is still a stub", state="error")
            st.warning("coordinator.run is still a stub. Showing saved runs only.")
            return None
        except Exception as e:  # show the failure, never crash the demo
            status.update(label="Run failed", state="error")
            st.error(f"Run failed: {e}. The saved runs below still work.")
            return None
        status.update(label=f"Done: {res['run_id']} ({res['outcome']['type']}). Opening the replay…",
                      state="complete", expanded=False)
    if fake:
        st.sidebar.caption("No API key: ran with fake (random) agents.")
    return res


def open_new_run(res):
    """Jump to the new run's replay and autoplay it (applied at the top of the next script run)."""
    list_logs.clear()
    st.session_state["_goto_run"] = res["run_id"]
    st.rerun()


# ---------- sidebar ----------
st.sidebar.title("Sky Huddle")
st.session_state.setdefault("page", "Negotiation")
if "_goto_run" in st.session_state:
    st.session_state["page"] = "Pixel replay"
page = st.sidebar.radio("Page", ["Story", "Negotiation", "Pixel replay", "Metrics", "Benchmark"], key="page")
all_logs = list_logs()
has_real = any(not smp for _, smp in all_logs.values())
show_samples = st.sidebar.checkbox("Show sample and toy runs", value=not has_real,
                                   help="Hidden automatically once real runs exist, so judges only see real ones.")
logs = {k: v[0] for k, v in all_logs.items() if show_samples or not v[1]}
if not logs:
    st.error("No audit logs found. Run `python fixtures/make_sample_logs.py`.")
    st.stop()
_goto = st.session_state.pop("_goto_run", None)
if _goto:
    _match = next((k for k in logs if k.endswith(f", {_goto})")), None)
    if _match:
        st.session_state["run_choice"] = _match
        st.session_state["_autoplay"] = _goto
choice = st.sidebar.selectbox("Run to show", list(logs), key="run_choice")
log = load(logs[choice])
st.sidebar.caption(f"run_id `{log['run_id']}`")
if log.get("sample"):
    st.sidebar.warning("Sample log for UI development. Not a real agent run.")

st.sidebar.divider()
st.sidebar.subheader("New run")
if st.sidebar.button("Run a random qualifying row"):
    new = try_pipeline_run("random")
    if new:
        open_new_run(new)
st.sidebar.caption("Run one flight from the 2015 data")
flight_in = st.sidebar.text_input("Flight", placeholder="AA1344", key="flight_in")
date_in = st.sidebar.text_input("Date", value="2015-01-01", placeholder="YYYY-MM-DD", key="date_in")
if st.sidebar.button("Run this flight"):
    new = try_pipeline_run("search", flight_in.strip().upper(), date_in.strip())
    if new:
        open_new_run(new)

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
        dt = b["deterministic"]
        if dt.get("runs"):
            base, after = dt.get("feasible_on_base_state", 0), dt.get("fallback_feasible", 0)
            t = st.columns(3)
            t[0].metric("Safe plan before concessions", f"{base}/{dt['runs']}")
            t[1].metric("Safe plan after agent concessions", f"{after}/{dt['runs']}", f"+{after - base} rescued")
            t[2].metric("No safe plan: escalated to human", dt.get("escalations", 0))
        if a.get("fake_agents"):
            st.caption("Agent-run numbers below come from fake agents. Run `python benchmark.py --agents 10 --live` for live Claude runs.")
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
        st.dataframe(pd.DataFrame(H.items(), columns=["field", "value"]).astype(str), hide_index=True, width="stretch")
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
                conc = ", ".join(f"{c['id']} ({c['target']})" if c['target'] else c['id'] for c in o["concessions"]) or "none"
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
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

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
    autoplay = st.session_state.get("_autoplay") == log["run_id"]
    if autoplay:
        st.session_state.pop("_autoplay")
    components.html(replay_html(normalize_log(view), autoplay=autoplay), height=1060, scrolling=True)

elif page == "Metrics":
    import altair as alt

    st.title("Metrics")
    runs = [load(p) for p in logs.values()]
    n_sample = sum(1 for r in runs if r.get("sample"))
    st.caption(f"Computed live from {len(runs)} audit logs in the run picker.")
    if n_sample:
        st.warning(f"{n_sample} of {len(runs)} logs are sample or toy runs. Numbers become real once the pipeline writes logs.")
    INK, COLS = "#1b1f3b", {"consensus": "#3fae54", "fallback": "#e5484d", "escalation": "#7a1f1f"}

    # 1. Outcome mix
    st.subheader("1. How runs end")
    oc = pd.DataFrame([{"outcome": r["outcome"]["type"]} for r in runs]).value_counts().reset_index(name="runs")
    st.altair_chart(alt.Chart(oc).mark_bar(stroke=INK, strokeWidth=2).encode(
        x=alt.X("runs:Q", title="Runs", axis=alt.Axis(tickMinStep=1)), y=alt.Y("outcome:N", title=None, sort="-x"),
        color=alt.Color("outcome:N", scale=alt.Scale(domain=list(COLS), range=list(COLS.values())), legend=None),
        tooltip=["outcome", "runs"]).properties(height=140), width="stretch")

    # 2. Funnel for the selected run
    st.subheader("2. How the negotiation narrows the options (selected run)")
    cpx = log.get("compromise") or {}
    fc = log["outcome"].get("final_candidate")
    funnel = pd.DataFrame([
        {"stage": "1 All candidates", "plans": len(log.get("candidates", []))},
        {"stage": "2 Pass every check (no concessions)", "plans": len(cpx.get("feasible_before", []) or [])},
        {"stage": "3 Pass after concessions", "plans": len(cpx.get("feasible_after", []) or [])},
        {"stage": "4 Acceptable to all three agents", "plans": len(cpx.get("in_all_acceptable", []) or [])},
        {"stage": "5 Final plan", "plans": 1 if fc else 0}])
    st.altair_chart(alt.Chart(funnel).mark_bar(stroke=INK, strokeWidth=2, color="#4f8cff").encode(
        x=alt.X("plans:Q", title="Plans", axis=alt.Axis(tickMinStep=1)), y=alt.Y("stage:N", title=None, sort=None),
        tooltip=["stage", "plans"]).properties(height=200), width="stretch")
    st.caption("If step 3 is bigger than step 2, the agents' concessions opened up plans the rulebook alone could not use.")

    # 3. Cost: agreed plan vs rulebook without concessions
    st.subheader("3. Cost of the agreed plan vs the rulebook alone")
    rows = []
    for r in runs:
        c = r.get("costs", {})
        cp_ = r.get("compromise") or {}
        name = r.get("label") or r["run_id"]
        fin = r["outcome"].get("final_candidate")
        base = [i for i in (cp_.get("feasible_before") or []) if i in c]
        if fin in c:
            rows.append({"run": name, "plan": "Final plan", "usd": c[fin]["total_usd"]})
        if base:
            rows.append({"run": name, "plan": "Rulebook, no concessions", "usd": min(c[i]["total_usd"] for i in base)})
    if rows:
        cd = pd.DataFrame(rows)
        st.altair_chart(alt.Chart(cd).mark_bar(stroke=INK, strokeWidth=2).encode(
            y=alt.Y("run:N", title=None), x=alt.X("usd:Q", title="Simulated cost (USD)"),
            yOffset="plan:N", color=alt.Color("plan:N", scale=alt.Scale(range=["#ffd447", "#9aa3c2"]), title=None),
            tooltip=["run", "plan", alt.Tooltip("usd:Q", format="$,.0f")]).properties(height=60 * len(cd["run"].unique()) + 40),
            width="stretch")
    else:
        st.info("No runs with costs yet.")

    # 4. Which checks block plans
    st.subheader("4. Which hard checks block plans")
    chk = []
    for r in runs:
        for state in ("before_concessions", "after_concessions"):
            for cid, rs in (r.get("checks", {}).get(state) or {}).items():
                for x in rs:
                    chk.append({"rule": x["rule_id"], "state": "before" if state.startswith("before") else "after",
                                "failed": 0 if x["passed"] else 1})
    if chk:
        cf = pd.DataFrame(chk).groupby(["rule", "state"], as_index=False)["failed"].sum()
        st.altair_chart(alt.Chart(cf).mark_bar(stroke=INK, strokeWidth=2).encode(
            x=alt.X("rule:N", title="Check"), y=alt.Y("failed:Q", title="Plans blocked", axis=alt.Axis(tickMinStep=1)),
            xOffset=alt.XOffset("state:N", sort=["before", "after"]),
            color=alt.Color("state:N", sort=["before", "after"], scale=alt.Scale(range=["#e5484d", "#f2a51a"]), title="Concessions"),
            tooltip=["rule", "state", "failed"]).properties(height=260), width="stretch")
        st.caption("A drop from red to amber shows a concession unblocking that check.")

    # 5. Agent response time
    st.subheader("5. Agent response time per round")
    lat = []
    for r in runs:
        for rd in r.get("rounds", []):
            for m in rd.get("offers", []) + rd.get("votes", []):
                if m.get("latency_s") is not None:
                    lat.append({"agent": AGENTS.get(m["agent"], (m["agent"],))[0], "round": f"Round {rd['round']}",
                                "seconds": float(m["latency_s"])})
    if lat:
        ld = pd.DataFrame(lat)
        st.altair_chart(alt.Chart(ld).mark_circle(size=140, stroke=INK, strokeWidth=1.5, opacity=.85).encode(
            x=alt.X("seconds:Q", title="Seconds"), y=alt.Y("agent:N", title=None), color=alt.Color("round:N", title=None,
            scale=alt.Scale(range=["#4f8cff", "#ff8a3d"])), tooltip=["agent", "round", "seconds"]).properties(height=170),
            width="stretch")
        st.caption("The per-call timeout from config.yaml is the ceiling; anything at the ceiling became an abstention.")
    else:
        st.info("No agent timings yet (fake agents report none).")

    # 6. Concessions
    st.subheader("6. Concessions offered and the ones that unlocked agreement")
    cc = []
    for r in runs:
        unlocked = set(r["outcome"].get("concessions_that_unlocked") or [])
        for c in (r.get("compromise") or {}).get("concessions_applied", []) or []:
            cc.append({"concession": c["id"], "unlocked": "Unlocked a deal" if c["id"] in unlocked else "Offered only"})
    if cc:
        ccd = pd.DataFrame(cc).value_counts().reset_index(name="count")
        st.altair_chart(alt.Chart(ccd).mark_bar(stroke=INK, strokeWidth=2).encode(
            x=alt.X("count:Q", title="Times", axis=alt.Axis(tickMinStep=1)), y=alt.Y("concession:N", title=None),
            color=alt.Color("unlocked:N", scale=alt.Scale(domain=["Unlocked a deal", "Offered only"], range=["#3fae54", "#c5cbe0"]), title=None),
            tooltip=["concession", "unlocked", "count"]).properties(height=160), width="stretch")
    else:
        st.info("No concessions in these runs.")


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
    st.dataframe(pd.DataFrame(b["failure_tests"]), hide_index=True, width="stretch")
    st.caption("Agents are not expected to beat a central solver that knows every constraint. "
               "We measure how well they coordinate within bounds, and how traceable the agreement is.")
