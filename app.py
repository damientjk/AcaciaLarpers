"""Sky Huddle: Streamlit app for the Challenge 2 multi-agent negotiation.

Run:  streamlit run app.py

The UI reads audit logs (one JSON per run). Real runs go in logs/. Until the
pipeline exists it falls back to fixtures/sample_logs/. Log format: docs/LOG_FORMAT.md
"""
import json
import os
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

def _load_dotenv(path):
    """Read KEY=value lines from a local .env (gitignored, see .env.example) into the environment.
    Values already set in the environment win; the key never leaves this machine."""
    if path.exists():
        for line in path.read_text().splitlines():
            k, sep, v = line.strip().partition("=")
            if sep and k and not k.startswith("#") and v.strip():
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv(ROOT / ".env")

st.set_page_config(page_title="Sky Huddle", page_icon="✈️", layout="wide", initial_sidebar_state="collapsed")
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Jersey+15&family=Poppins:wght@400;500;600;700&display=swap');
html, body, [class*="css"], .stMarkdown, p, li, label {font-family: 'Poppins', sans-serif; font-weight: 500;}
label, [data-testid="stWidgetLabel"] p, .stMarkdown strong, b {font-weight: 700 !important;}
[data-testid="stCaptionContainer"] p {font-weight: 500; color: #3b4366;}
h1, h2, h3, h4 {font-family: 'Jersey 15', monospace !important; font-weight:400 !important; letter-spacing:.02em; line-height:1.15 !important;}
h1 {font-size:2.7rem !important;} h2 {font-size:2.1rem !important;} h3 {font-size:1.7rem !important;}
.stApp {background: linear-gradient(180deg, #b5e1fa 0%, #dcf0fc 30%, #eef7fd 60%) fixed;}
header[data-testid="stHeader"] {background: rgba(233,245,253,.92); border-bottom: 3px solid #1b1f3b;}
footer {display:none;}
section[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"] {display:none;}
.block-container {padding-top: 4.2rem; max-width: 1500px;}
[data-testid="InputInstructions"] {display:none;}
[data-testid="stImage"] img {image-rendering: pixelated;}
[data-testid="stMain"] .stButton button, [data-testid="stMain"] .stFormSubmitButton button, [data-testid="stPopover"] button {font-family:'Jersey 15',monospace; font-size:19px; font-weight:400; border:3px solid #1b1f3b; border-radius:4px; box-shadow:3px 3px 0 #1b1f3b; background:#fff; color:#1b1f3b;}
[data-testid="stMain"] button[data-testid="stBaseButton-primary"], [data-testid="stMain"] button[data-testid="stBaseButton-primaryFormSubmit"] {background:#ff8a3d; color:#1b1f3b;}
[data-testid="stMain"] .stButton button:hover {background:#ffd447; color:#1b1f3b;}
[data-testid="stMain"] .stButton button:disabled {background:#eef0f5; color:#5b6487; box-shadow:none;}
[data-testid="stMain"] input {border: 2px solid #1b1f3b !important; border-radius: 3px !important; background: #fff !important;}
.mo {border:3px solid #1b1f3b; background:#fff8e1; box-shadow:4px 4px 0 #1b1f3b; padding:12px 16px; margin:4px 0 12px;}
[data-testid="stMetric"] {background:#f3f8fd; border:3px solid #1b1f3b; box-shadow:3px 3px 0 #1b1f3b; padding:8px 12px;}
.badge {display:inline-block;padding:3px 8px;border:3px solid #1b1f3b;font-family:'Jersey 15',monospace;font-size:18px;box-shadow:3px 3px 0 #1b1f3b;}
.b-consensus {background:#bff0c8;} .b-fallback {background:#ffc2c4;} .b-escalation {background:#b42318;color:#fff;}
.card {border:3px solid #1b1f3b;padding:10px 12px;margin-bottom:8px;background:#fff;box-shadow:3px 3px 0 #1b1f3b;}
.ok {background:#e9f9ec;border-color:#1b1f3b;} .no {background:#ffecec;}
.sim {color:#6d28d9;font-weight:600;font-size:12px;} .real {color:#1e7d34;font-weight:600;font-size:12px;}
/* brand and boarding-pass incident bar (from the Sky Huddle design artifact) */
.brand {display:flex;align-items:center;gap:12px}
.brand img {height:96px;width:auto}
.brand h1 {font-size:46px !important;margin:0;padding:0;color:#1b1f3b}
.brand small {display:block;font-size:13px;color:#3b4366}
.incident {display:grid;grid-template-columns:auto auto 1fr auto;align-items:center;gap:12px 22px;padding:16px 20px;margin:4px 0 10px;background:#f3f8fd;border:3px solid #1b1f3b;box-shadow:4px 4px 0 #1b1f3b;border-radius:4px}
.incident .tag {font-family:'Jersey 15',monospace;background:#b42318;color:#fff;padding:2px 10px;border:2px solid #1b1f3b;font-size:19px}
.incident .facts {display:grid;grid-template-columns:repeat(2,max-content);gap:10px 12px}
.incident .facts .chip {font-size:15px;padding:5px 12px}
.incident .verdict {display:grid;justify-items:end;gap:8px;text-align:right}
.incident .verdict small {font-size:12px;color:#3b4366}
@media (max-width:1100px) {.incident {grid-template-columns:auto 1fr} .incident .verdict {justify-items:start;text-align:left}}
.chip {display:inline-flex;align-items:center;gap:6px;font-size:13px;padding:2px 8px;border:2px solid #1b1f3b;background:#fff;border-radius:3px}
.ticket {display:inline-flex;align-items:stretch;background:#fff;border:3px solid #1b1f3b;box-shadow:3px 3px 0 #1b1f3b;border-radius:6px}
.tk-body {display:flex;align-items:center;gap:12px;padding:4px 14px}
.tk-port small,.tk-port span {display:block;font-size:11px;color:#3b4366;line-height:1.15}
.tk-port b {display:block;font-family:'Jersey 15',monospace;font-size:34px;line-height:1}
.tk-fly {display:flex;flex-direction:column;align-items:center;gap:2px;font-size:12px;color:#3b4366;min-width:130px}
.tk-route {display:flex;align-items:center;width:100%;gap:5px}
.tk-route i {flex:1;border-top:3px dashed #1b1f3b}
.tk-route b {font-size:20px;line-height:1;color:#1b1f3b}
.tk-route s {width:0;height:0;border-top:7px solid transparent;border-bottom:7px solid transparent;border-left:11px solid #1b1f3b;text-decoration:none}
.tk-stub {border-left:3px dashed #1b1f3b;padding:4px 14px;background:#ffd447;display:grid;align-content:center;font-size:11px;line-height:1.3;border-radius:0 3px 3px 0}
.tk-stub b {font-family:'Jersey 15',monospace;font-size:24px;line-height:1.1}
/* agent pages */
.inv {display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}
.cell {border:3px solid #1b1f3b;padding:6px 8px;font-size:12.5px;line-height:1.3;position:relative;box-shadow:inset -3px -3px 0 rgba(0,0,0,.12)}
.cell b {font-family:'Jersey 15',monospace;font-size:21px;display:block;line-height:1}
.cell.like {background:#bff0c8}.cell.meh {background:#fff1b8}.cell.bad {background:#3a3f5c;color:#ffd0d2}
.cell.pref {outline:3px solid #ffd447;outline-offset:2px}
.cell.final::after {content:"FINAL";position:absolute;right:4px;top:3px;font-family:'Jersey 15',monospace;font-size:14px;background:#1b1f3b;color:#fff;padding:0 5px}
.thought {display:grid;grid-template-columns:62px 1fr;gap:8px;font-size:13px;margin-bottom:8px}
.thought .k {font-family:'Jersey 15',monospace;font-size:15px;padding:0;text-align:center;border:2px solid #1b1f3b;background:#ffd447;height:max-content}
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
    log.setdefault("escalation_assist", None)
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
    # Show the gap as total cost across runs (as the README does), not benchmark.py's mean of per-run
    # percentages, which one cheap-reference run can blow up (one run at +904% made the mean 114%).
    paired = [(r["final_cost_usd"], r["reference_optimum"]["total_usd"]) for r in b.get("agent_runs") or []
              if r.get("final_cost_usd") is not None and (r.get("reference_optimum") or {}).get("total_usd")]
    if paired:
        agent, solver = sum(x for x, _ in paired), sum(y for _, y in paired)
        b["cost_vs_solver_gap_pct"] = round((agent - solver) / solver * 100, 1)
        b["gap_label"] = f"Extra cost vs solver (total, {len(paired)} runs)"
    b.setdefault("gap_label", "Cost gap vs solver")
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



def try_pipeline_run(mode, flight=None, date=None, slot=None):
    """Run one negotiation. While it runs, the airport scene in `slot` shows who is thinking (live mode).
    Without a working key it runs with fake agents (random choices, real checker)."""
    if KEY_STATUS == "rejected":  # live calls would all 401 and look like a real escalation
        st.error("The server's API key was rejected, so the agents can't answer. Fix ANTHROPIC_API_KEY in the "
                 "server's .env and restart it, or remove it to run with fake agents.")
        return None
    try:
        import coordinator  # noqa: WPS433
        import scenario as sc
    except ImportError:
        st.info("The pipeline isn't in the repo yet. Showing saved runs only.")
        return None
    s = sc.random_scenario() if mode == "random" else sc.find_scenario(flight, date)
    if s is None:
        st.error(f"No qualifying delayed flight {flight} on {date}. Try AA1344 on 2015-01-01.")
        return None
    fake = not os.environ.get("ANTHROPIC_API_KEY")
    stub = {"scenario": {"scenario_id": s.scenario_id, "historical": json.loads(s.model_dump_json())["historical"],
                         "simulated": {}}, "candidates": [], "checks": {}, "costs": {}, "outcome": {}, "rounds": [],
            "stats": {}}
    lines = []

    def progress(msg):  # called by coordinator.negotiate at each stage; redraw the scene in live mode
        lines.append(msg)
        phase = (4 if msg.startswith("Final") else 3 if "Round 2" in msg else 2 if msg.startswith("Round 1 done")
                 else 1 if "Round 1" in msg else 0)
        if slot is not None:
            with slot.container():
                st.iframe(replay_html(stub, live={"phase": phase, "lines": lines, "fake": fake}, view="airport"))

    try:
        return coordinator.run(scenario_id=s.scenario_id, fake_agents=fake, progress=progress)
    except Exception as e:  # show the failure, never crash the demo
        st.error(f"Run failed: {e}. The saved runs still work.")
        return None


def open_new_run(res):
    """Show the new run and autoplay its replay (applied on the next script run)."""
    list_logs.clear()
    st.session_state["_goto_run"] = res["run_id"]
    st.rerun()


@st.cache_data(ttl=600, show_spinner=False)
def check_key(key):
    """'ok', 'rejected' or an error string. Listing models is free and needs a valid key. Kept in memory only."""
    import anthropic
    try:
        anthropic.Anthropic(api_key=key, max_retries=0, timeout=10).models.list(limit=1)
        return "ok"
    except anthropic.AuthenticationError:
        return "rejected"
    except Exception as e:  # network trouble etc.: say so rather than blame the key
        return f"could not check ({type(e).__name__})"




# ---------- shared pieces ----------
CITY = {"DEN": "Denver", "DFW": "Dallas/Fort Worth", "ORD": "Chicago O'Hare", "LAX": "Los Angeles", "SFO": "San Francisco",
        "JFK": "New York JFK", "LGA": "New York LaGuardia", "BOS": "Boston", "ATL": "Atlanta", "MIA": "Miami",
        "SEA": "Seattle", "PHX": "Phoenix", "LAS": "Las Vegas", "IAH": "Houston", "MSP": "Minneapolis",
        "DTW": "Detroit", "PHL": "Philadelphia", "EWR": "Newark", "CLT": "Charlotte", "MCO": "Orlando",
        "OAK": "Oakland", "SAN": "San Diego", "BWI": "Baltimore", "DCA": "Washington National", "SLC": "Salt Lake City"}
ROLE = {"atc": ("Ava", "Air traffic control", "Owns the runway: slots, wake spacing, taxi routes."),
        "pilot": ("Pip", "Pilot in command", "Owns the aircraft: fuel at landing."),
        "ground": ("Gus", "Ground operations", "Owns the ramp: gates, turnaround, crew."),
        "mod": ("Coco", "Coordinator", "Plain code, no AI: applies concessions, rechecks, freezes one plan.")}


def png(agent, scale=3):
    """Pixel sprite at an exact integer scale (20 x 27 grid), shown at that size so it stays crisp."""
    from ui.sprites import sprite_png
    return sprite_png(agent, scale)


@st.cache_data
def logo_b64(height=120):
    """The Sky Huddle logo (ui/assets/logo.png), resized once for the header."""
    import base64
    import io
    from PIL import Image
    im = Image.open(ROOT / "ui" / "assets" / "logo.png")
    im = im.resize((round(im.width * height * 2 / im.height), height * 2), Image.LANCZOS)  # 2x for sharp retina
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode()


def key_box():
    """Read-only key status. The key comes from ANTHROPIC_API_KEY in the server's .env; the page cannot change it."""
    k = os.environ.get("ANTHROPIC_API_KEY", "")
    if KEY_STATUS == "ok":
        st.badge(f"Live Claude agents · key …{k[-4:]}", icon=":material/check_circle:", color="green")
    elif KEY_STATUS == "rejected":
        st.badge(f"Key …{k[-4:]} rejected: fix .env on the server", icon=":material/error:", color="red")
    elif KEY_STATUS:
        st.badge(f"Key …{k[-4:]}: {KEY_STATUS}", icon=":material/warning:", color="orange")
    else:
        st.badge("No key in .env: fake agents", icon=":material/key_off:", color="gray")


def frame(ticket=True):
    """Brand, key status and the boarding-pass bar for the flight on screen: the same on every page."""
    import base64
    c1, c2 = st.columns([3, 2], vertical_alignment="center")
    img = f'<img src="data:image/png;base64,{logo_b64()}" alt="Sky Huddle logo">'
    c1.html(f'<div class="brand">{img}<div><h1>Sky Huddle</h1><small>Three AI agents settle one flight '
            f'disruption in two rounds. Coco coordinates. You make the call.</small></div></div>')
    with c2:
        key_box()
    if not ticket:
        return
    st.html(f"""<div class="incident"><span class="tag">Disruption</span>
<span class="ticket"><span class="tk-body">
 <span class="tk-port"><small>From</small><b>{H['origin']}</b><span>{CITY.get(H['origin'], '')}</span></span>
 <span class="tk-fly"><span class="tk-route"><i></i><b>✈</b><i></i><s></s></span>{H.get('distance_mi', '?')} mi</span>
 <span class="tk-port"><small>To</small><b>{H['destination']}</b><span>{CITY.get(H['destination'], '')}</span></span>
</span><span class="tk-stub"><span>Flight</span><b>{H['carrier']} {H['flight']}</b><span>Sched {H['scheduled_arrival']} · {H['date']}</span></span></span>
<div class="facts"><span class="chip">Arrived <b>{H.get('arrival_delay_min', '?')} min</b> late</span>
<span class="chip">Weather <b>{H.get('weather_delay_min', 0)} min</b></span>
<span class="chip">Late aircraft <b>{H.get('late_aircraft_delay_min', 0)} min</b></span>
<span class="chip">Tail <b>{H.get('tail', '?')}</b></span></div>
<div class="verdict">{outcome_badge(out) if out.get('type') else ''}<small>Real 2015 data · flights.csv</small></div></div>""")


def run_picker(label):
    names = list(logs)
    pick = st.selectbox(label, names, index=names.index(st.session_state["current_run"]))
    if pick != st.session_state["current_run"]:
        st.session_state["current_run"] = pick
        st.rerun()


def decision_buttons(fc, costly=None):
    key = f"decision-{log['run_id']}"
    saved = DECISIONS / f"{log['run_id']}.json"
    if saved.exists() and key not in st.session_state:
        st.session_state[key] = json.loads(saved.read_text())
    if key in st.session_state:
        dsn = st.session_state[key]
        (st.success if dsn["approved"] else st.error)(f"{'Approved' if dsn['approved'] else 'Rejected'} at {dsn['at']}. {dsn.get('note', '')}")
        return True
    x, y = st.columns(2)
    for btn, ok in [(x, True), (y, False)]:
        label = ("Approve costly plan" if costly else "Approve") if ok else "Reject"
        if btn.button(label, type="primary" if ok else "secondary", disabled=ok and not (fc or costly),
                      width="stretch"):
            plan = fc or (f"{costly['candidate']} + {' + '.join(costly['fixes'])}" if costly and ok else None)
            dsn = {"approved": ok, "at": datetime.now().strftime("%H:%M:%S"),
                   "note": "Safe-but-costly plan, outside the modelled options." if costly and ok and not fc else "",
                   "run_id": log["run_id"], "plan": plan, "costly": bool(costly and ok and not fc)}
            st.session_state[key] = dsn
            DECISIONS.mkdir(parents=True, exist_ok=True)
            saved.write_text(json.dumps(dsn, indent=2))
            st.rerun()
    return False


@st.cache_data(show_spinner=False)
def _assist_for(run_id, raw_json):
    import escalation
    try:
        return escalation.assist_from_log(json.loads(raw_json))
    except Exception as e:  # never break the page over the assist
        return {"error": f"{type(e).__name__}: {e}"}


def assist_for(lg):
    if (lg.get("outcome") or {}).get("type") != "escalation":
        return None
    return lg.get("escalation_assist") or _assist_for(lg["run_id"], json.dumps(lg, default=str))


def escalation_panel(a):
    """No normal plan is safe: the safe-but-costly option, the main blocker, the closest plans, what you could do."""
    if not a or a.get("error"):
        if a:
            st.caption(f"Escalation assist unavailable: {a['error']}")
        return None
    opt = a.get("costly_option")
    if opt:
        p = opt["plan"]
        st.markdown(f'<div class="mo" style="background:#e9f9ec"><b>Safe but costly: +${opt["extra_vs_cheapest_normal_usd"]:,.2f}</b> '
                    f'vs the cheapest normal plan.<br>Plan {opt["candidate"]} with <b>{" + ".join(opt["fix_labels"]).lower()}</b>: '
                    f'land {p["landing"]}, gate {p["gate"]}, {p["extra_holding_min"]} min extra holding. '
                    f'Total ${opt["total_usd"]:,.2f} (fees ${sum(opt["fees_usd"].values()):,.0f}, rough assumptions). '
                    f'All {len(opt["checks"])} safety checks pass.<br><small>{opt["label"]}</small></div>',
                    unsafe_allow_html=True)
    mb = a.get("main_blocker")
    if mb:
        st.markdown(f"**Main blocker:** {mb['rule_id']} {mb['title'].lower()} (fails in {mb['plans']} of {mb['of']} plans; "
                    f"{a['one_rule_away']} plan(s) are one rule away).")
    with st.expander("Closest plans and what blocks them"):
        st.dataframe(pd.DataFrame([{"plan": r["candidate"], "fails": ", ".join(r["failed_rules"]),
                                    "short by": "; ".join((f"{s['amount']} {s['unit']}: " if s["amount"] is not None else "")
                                                          + s["explanation"] for s in r["shortfalls"]),
                                    "cost $": r["total_usd"]} for r in a["closest"]]),
                     hide_index=True, width="stretch")
    with st.expander("What you could do (outside the modelled options)"):
        for s in a.get("suggestions", []):
            tag = "never relaxed" if not s["relaxable"] else "your decision"
            st.markdown(f"**{s['rule_id']} · {s['title']}** ({tag})  \n" + "  \n".join(f"- {x}" for x in s["actions"]))
    return opt


def show_replay(view):
    v = dict(log)
    key = f"decision-{log['run_id']}"
    if key in st.session_state:
        v["human_decision"] = {"approved": st.session_state[key]["approved"], "by": "duty manager",
                               "note": st.session_state[key].get("note", "")}
    autoplay = st.session_state.get("_autoplay") == log["run_id"]
    if autoplay:
        st.session_state.pop("_autoplay")
    v["escalation_assist"] = assist_for(log)
    st.iframe(replay_html(normalize_log(v), autoplay=autoplay, view=view))


def decision_panel():
    fc = out.get("final_candidate")
    st.markdown(f"**{H['carrier']} {H['flight']}** {H['origin']} → {H['destination']} on {H['date']}, "
                f"{H.get('arrival_delay_min', '?')} min late in real life &nbsp; " + outcome_badge(out),
                unsafe_allow_html=True)
    if log.get("fake_agents"):
        st.caption("This run used fake agents (no API key set), so the agents' choices are random. "
                   "The safety checks are real.")
    errs = [m["error"] for r in log.get("rounds", []) for m in r.get("offers", []) + r.get("votes", []) if m.get("error")]
    if errs:
        if any("401" in e or "authentication" in e.lower() for e in errs):
            made = log.get("created_at", "")[11:16]
            fix = ("Your current key works, so click **Run this flight** again." if KEY_STATUS == "ok"
                   else "Fix ANTHROPIC_API_KEY in the server's .env, restart it, then run the flight again.")
            st.error(f"This run (made at {made}) used an API key that was rejected (401), so the agents never "
                     f"answered. The outcome reflects the failed calls, not the flight. {fix}")
        else:
            st.warning(f"{len(errs)} agent call(s) failed ({errs[0][:80]}). The outcome below reflects that.")
    if fc:
        cd, k = cands[fc], costs[fc]
        lead = {"consensus": "Ava, Pip and Gus all agreed on this plan, and every safety check passed.",
                "fallback": "The agents did not agree, so the rulebook picked the cheapest plan that passes every "
                            "safety check."}.get(out["type"], "")
        st.markdown(f'<div class="mo"><b>Proposed plan {fc}:</b> land at <b>{cd["landing"]}</b>, gate '
                    f'<b>{cd["gate"]}</b>, <b>{cd["extra_holding_min"]} min</b> extra holding. Simulated cost '
                    f'<b>${k["total_usd"]:,.2f}</b>.<br>{lead}</div>', unsafe_allow_html=True)
    costly = None
    if not fc:
        st.markdown('<div class="mo"><b>No safe plan within the modelled options.</b> Escalated to you. Coco ranked '
                    'the closest plans and searched costlier fixes; nothing is applied unless you approve it.</div>',
                    unsafe_allow_html=True)
        costly = escalation_panel(assist_for(log))
    decision_buttons(fc, costly)



# ---------- pages ----------
def page_airport():
    frame()
    # One box: pick a saved run to open it, or type a new flight number to run it.
    names = list(logs)
    c = st.columns([3.2, 1.6, 1.4, 1.4], vertical_alignment="bottom")
    pick = c[0].selectbox("Flight", names, index=names.index(st.session_state["current_run"]),
                          accept_new_options=True, placeholder="Type a flight number, e.g. AA1090")
    saved = pick in logs
    if saved and pick != st.session_state["current_run"]:
        st.session_state["current_run"] = pick
        st.rerun()
    flight_in = f"{H['carrier']}{H['flight']}" if saved else (pick or "").strip().upper()
    date_in = c[1].text_input("Date", value=H["date"] if saved else "2015-01-01", key=f"date_in_{pick}")
    go = c[2].button("Run this flight", type="primary", width="stretch")
    rnd = c[3].button("Random flight", width="stretch")
    if KEY_STATUS != "ok":
        st.caption("No working key on the server: new runs use fake agents.")
    scene, desk = st.columns([1.75, 1])
    with scene:
        st.subheader("The huddle")
        slot = st.empty()
        new = None
        if go:
            new = try_pipeline_run("search", flight_in.strip().upper(), date_in.strip(), slot) if flight_in.strip() \
                else st.warning("Type a flight number first, for example AA1344.")
        if rnd:
            new = try_pipeline_run("random", slot=slot)
        if new:
            open_new_run(new)
        with slot.container():
            show_replay("airport")
    with desk:
        st.subheader("Your desk")
        decision_panel()
        st.page_link(HUDDLE, label="Every message and safety check", icon=":material/forum:")
    st.subheader("Meet the team")
    cols = st.columns(4)
    for col, aid in zip(cols, ["atc", "pilot", "ground", "mod"]):
        name, role, owns = ROLE[aid]
        with col.container(border=True):
            i, t = st.columns([1, 3], vertical_alignment="center")
            i.image(png(aid, 3), width=60)
            t.markdown(f"**{name}** · {role}  \n{owns}")
            if aid in AGENT_PAGES:
                st.page_link(AGENT_PAGES[aid], label=f"Open {name}'s brain", icon=":material/psychology:")
            else:
                st.page_link(HUDDLE, label="See Coco's log", icon=":material/forum:")
    with st.container(border=True):
        st.markdown("**How the huddle works**  \n1. A real delayed 2015 flight arrives.  \n2. Round 1: each agent "
                    "offers plans and a concession.  \n3. Coco (plain code) applies them, rechecks, freezes one plan.  \n"
                    "4. Round 2: the agents vote.  \n5. You approve, or the rulebook / escalation steps in.")


def agent_page(aid):
    def page():
        import agents as A
        frame()
        name, role, owns = ROLE[aid]
        o = next((x for x in (r1 or {}).get("offers", []) if x["agent"] == aid), None)
        v = next((x for x in (r2 or {}).get("votes", []) if x["agent"] == aid), None)
        fc = out.get("final_candidate")
        mine = A.OWN_RULES[aid]
        left, mid, right = st.columns([1, 2, 1.3])
        with left.container(border=True):
            st.image(png(aid, 6), width=120)
            st.subheader(name)
            st.caption(role)
            st.markdown(f"{owns}  \n**Checks it owns:** {', '.join(sorted(mine))}  \n"
                        f"**Its one concession:** `{A.OWN_CONCESSION[aid]}`")
            st.markdown('<span class="sim">PRIVATE STATE · simulated, only this agent sees it</span>',
                        unsafe_allow_html=True)
            st.json(SIM.get(aid, {}), expanded=False)
        with mid.container(border=True):
            st.subheader(f"{name}'s option inventory")
            before = (log.get("checks") or {}).get("before_concessions", {})
            acc = set(o["acceptable"]) if o else set()
            cells = []
            for cid, c in cands.items():
                fails = [r["rule_id"] for r in before.get(cid, []) if not r["passed"] and r["rule_id"] in mine]
                cls = "bad" if fails else "like" if cid in acc else "meh"
                cls += (" pref" if o and cid == o["preferred"] else "") + (" final" if cid == fc else "")
                why = f"breaks {', '.join(fails)}" if fails else "acceptable to " + name if cid in acc else "passes, not chosen"
                cells.append(f'<div class="cell {cls}"><b>{cid}</b>land {c["landing"]} · gate {c["gate"]}<br>'
                             f'+{c["extra_holding_min"]} min hold · ${costs.get(cid, {}).get("total_usd", 0):,.0f}<br>'
                             f'<small>{why}</small></div>')
            st.html('<div class="inv">' + "".join(cells) + "</div>")
            st.caption("Green: accepts · Yellow: passes, not chosen · Dark: breaks a check · FINAL: on your desk")
        with right.container(border=True):
            st.subheader("Thought stream")
            steps = [("READ", f"{len(cands)} candidate plans for {H['carrier']}{H['flight']}, each checked in code.")]
            if o:
                steps += [("RULES", f"Cites {', '.join(o['constraints_cited']) or 'nothing'}."),
                          ("OFFER", f"Prefers {o['preferred']}; accepts {', '.join(o['acceptable']) or 'none'}."),
                          ("CONCEDE", ", ".join(f"{c['id']} for {c['target']}" for c in o["concessions"]) or "Nothing to concede."),
                          ("WHY", o["rationale"])]
            elif r1:
                steps.append(("ERROR", "No valid offer in round 1."))
            else:
                steps.append(("SKIP", "Nothing passed the checks, so there were no rounds."))
            if v:
                steps.append(("VOTE", f"{v['vote'].upper()}: {v['rationale']}"))
            st.html("".join(f'<div class="thought"><span class="k">{k}</span><span>{t}</span></div>' for k, t in steps))
            st.markdown("**Outbox**")
            st.json({"round_1": o, "round_2": v}, expanded=False)
        with st.expander(f"{name}'s skill file: the prompt it runs on ({log.get('stats', {}).get('model') or 'model from config.yaml'})"):
            st.code(A.COMMON.format(role=A.ROLES[aid]) + "\n\n" + A.ROUND1 + "\n\n" + A.ROUND2, language="markdown")
    page.__name__ = f"page_{aid}"
    return page


def page_huddle():
    frame()
    run_picker("Run")
    show_replay("huddle")
    st.subheader("Final plan and every safety check")
    audit()


def page_mo():
    frame()
    st.subheader("Your desk · duty manager")
    st.markdown("The agents only propose. Coco, the coordinator, checks every plan in plain code. **You approve or reject it.**")
    a, b = st.columns([1.3, 1])
    with a.container(border=True):
        run_picker("Flight on your desk")
        decision_panel()
    with b.container(border=True):
        st.markdown("**What the agents are told to care about** (from `config.yaml`, read only)")
        try:
            import agents as A
            cfg = A.config()
            st.json({"cost_weights": cfg.get("costs"), "protocol": cfg.get("protocol")}, expanded=False)
        except Exception as e:  # config is optional for the UI
            st.caption(f"Config not available ({type(e).__name__}).")
        st.markdown("**Your decisions so far**")
        rows = [json.loads(p.read_text()) for p in sorted(DECISIONS.glob("*.json"))] if DECISIONS.exists() else []
        if rows:
            st.dataframe(pd.DataFrame(rows)[["run_id", "plan", "approved", "at"]], hide_index=True, width="stretch")
        else:
            st.caption("None yet.")


def audit():
    st.caption(f"run_id `{log['run_id']}`")

    # 2. Historical vs simulated
    st.subheader("Scenario")
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
    st.subheader("Round 1: offers and concessions")
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
        st.subheader("Round 2: final vote")
        cols = st.columns(3)
        for col, v in zip(cols, r2["votes"]):
            n, role = AGENTS[v["agent"]]
            icon = {"accept": "✅", "reject": "❌", "abstain": "⌛"}[v["vote"]]
            col.markdown(f'<div class="card {"ok" if v["vote"] == "accept" else "no"}">{icon} <b>{n}</b>: {v["vote"]} v{v["proposal_version"]}<br><i>{v["rationale"]}</i></div>',
                         unsafe_allow_html=True)

    # 4. Checks
    st.subheader("Hard checks")
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
    st.subheader("Final plan")
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

    s = log.get("stats", {})
    st.caption(f"API calls {s.get('api_calls')} · retries {s.get('retries')} · total {s.get('total_latency_s')} s")
    with st.expander("Raw audit log JSON"):
        st.json(log)


def page_metrics():
    import altair as alt

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


def page_benchmark():
    b, bp = benchmark()
    if not b:
        st.info("No benchmark yet. benchmark.py should write logs/benchmark.json.")
        return
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
    m[2].metric(b["gap_label"], f"{b['cost_vs_solver_gap_pct']}%")
    m[3].metric("Heuristic infeasible", f"{b['heuristic']['infeasible_rate_pct']}%")
    det = b["deterministic"]
    st.markdown(f"**Deterministic runs (all {det['runs']}):** rulebook found a feasible plan in {det['fallback_feasible']}, escalated {det['escalations']}.")
    st.subheader("Failure tests")
    st.dataframe(pd.DataFrame(b["failure_tests"]), hide_index=True, width="stretch")
    st.caption("Agents are not expected to beat a central solver that knows every constraint. "
               "We measure how well they coordinate within bounds, and how traceable the agreement is.")


def page_results():
    frame(ticket=False)
    st.title("Results")
    st.caption("Measured inside the simulation. Costs are USD-equivalent scores, not measured savings.")
    t1, t2 = st.tabs(["Benchmark: 51 scenarios and 10 live runs", "Charts across the saved runs"])
    with t1:
        page_benchmark()
    with t2:
        page_metrics()



# ---------- navigation and the run on screen ----------
AGENT_PAGES = {aid: st.Page(agent_page(aid), title=ROLE[aid][0], icon=":material/person:", url_path=ROLE[aid][0].lower())
               for aid in ["atc", "pilot", "ground"]}  # Coco is plain code, so it has no brain page
HUDDLE = st.Page(page_huddle, title="Huddle", icon=":material/forum:", url_path="huddle")
pg = st.navigation([st.Page(page_airport, title="Airport", icon=":material/flight_land:", url_path="airport", default=True),
                    *AGENT_PAGES.values(), HUDDLE,
                    st.Page(page_mo, title="Your desk", icon=":material/gavel:", url_path="desk"),
                    st.Page(page_results, title="Results", icon=":material/bar_chart:", url_path="results")],
                   position="top")

_key = os.environ.get("ANTHROPIC_API_KEY", "")
KEY_STATUS = check_key(_key) if _key else None

# Real runs first; sample runs (labelled SAMPLE) at the end of the same list.
all_logs = list_logs()
logs = {k: v[0] for k, v in all_logs.items() if not v[1]} | {k: v[0] for k, v in all_logs.items() if v[1]}
if not logs:
    st.error("No audit logs found. Run `python fixtures/make_sample_logs.py`.")
    st.stop()
_goto = st.session_state.pop("_goto_run", None)
if _goto:
    _match = next((k for k in logs if k.endswith(f", {_goto})")), None)
    if _match:
        st.session_state["current_run"] = _match
        st.session_state["_autoplay"] = _goto
if st.session_state.get("current_run") not in logs:
    st.session_state["current_run"] = next(iter(logs))
log = load(logs[st.session_state["current_run"]])
H = log["scenario"]["historical"]
SIM = log["scenario"].get("simulated", {})
out = log["outcome"]
cands = {c["id"]: c for c in log.get("candidates", [])}
costs = log.get("costs", {})
r1 = next((r for r in log.get("rounds", []) if r["round"] == 1), None)
r2 = next((r for r in log.get("rounds", []) if r["round"] == 2), None)
cp = log.get("compromise")
check_set = "before_concessions" if out["type"] == "fallback" else "after_concessions"

pg.run()
