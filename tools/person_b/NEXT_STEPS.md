# Person B: checks, costs, fallback and benchmark

The shared schemas have been agreed by the team but were not on GitHub when this checkout was prepared. Implement against that exact `models.py` when it arrives. This note proposes calculation semantics, not replacement schemas or frozen function signatures.

## First integration target

One scenario and up to eight candidates go through checks, cost calculation and deterministic selection without an LLM. Return every check result for the UI and agents. Choose only a fully feasible candidate. If none is feasible, return an explicit escalation outcome.

Implement in this order:

1. Confirm names and units in `models.py`, including time zone, baseline ETA, fuel at baseline ETA, gate occupancy interval and concession state version.
2. `checker.py`: eight checks below and one passing/failing boundary test per check.
3. `costs.py`: raw costs, weights and weighted total. Label units.
4. `fallback.py`: enumerate all supplied candidates, check them, choose minimum weighted cost, then candidate ID. Empty feasible set means escalation.
5. `benchmark.py`: run Person A's seeded fixtures, then connect Person C's coordinator for agent runs. Report only completed runs and observed results.

## Check table

| Rule | Calculation / predicate | Units and boundary | Basis |
|---|---|---|---|
| F-1 | Fuel at baseline landing minus extra holding times holding burn is at least the scenario reserve | kg, min, kg/min. Equality passes. Define the baseline before doing arithmetic. | Simplified simulation. A reserve parameter does not establish FAA compliance. |
| W-1 | Gap behind the preceding aircraft is at least the configured requirement for the supported category pair | Seconds. Equality passes. Unsupported or missing profiles do not pass. | A declared simulation profile informed by wake-separation concepts. No universal real-airport value. |
| R-1 | Candidate is within an available slot and does not exceed the modelled runway resource capacity | UTC instants and declared interval boundaries. Count the focal candidate once. | Simulated runway resource model. |
| T-1 | Candidate route has no segment in the closed-taxiway set | Explicit route/segment identifiers. | Simulated topology. |
| G-1 | The selected gate supports the candidate aircraft's modelled compatibility class | Explicit classes, not guessed from tail number. | Simulated compatibility. |
| G-2 | Full gate occupancy including the configured buffer does not overlap another booking | Half-open intervals [start, end). Exact adjacency passes. Exclude a replaced self-booking only by explicit ID. | Simulated gate schedule. |
| G-3 | Service duration is at least the configured turnaround minimum and all coupled times are consistent | Minutes. Equality passes. Derive gate arrival and release from the authoritative candidate fields. | Explicit simulation assumption. |
| C-1 | An assigned crew covers the required service interval and has no overlapping assignment | UTC intervals. Reassignment cannot silently remove crew from another active job. | Simulated crew schedule. |

Use the team's agreed CheckResult with rule ID, basis, actual inputs, passed and explanation. Missing required information must not silently pass. Reject non-finite values, negative durations, unknown IDs and stale versions before accepting an option. Keep source state immutable; concessions create a new version that is checked again.

## Costs and fairness

Compute delay relative to the simulated baseline ETA, holding fuel in kg, overtime in minutes and simulated missed connections as a count. Keep raw values and weighted values separate. `config.yaml` must state each weight and its resulting score units. The team should agree the numeric weights. Do not add the historical recorded delay twice or claim these scores are real monetary savings.

Compare agent and deterministic outcomes on the same candidate set, objective and concession-adjusted state. The all-information deterministic solver is a reference optimum within those options. A fully valid agent result can have higher cost, but cannot legitimately beat that optimum on the same problem. Report heuristic infeasibility separately from heuristic cost.

## Benchmark outputs

- Per-scenario: seed, disruption category, state version, selected candidate, feasible count, outcome type, all rule results, cost components and execution time.
- Agent runs: final votes, consensus/fallback/escalation, completed rounds, call count, retries, token usage and API latency.
- Aggregate: completed run count, consensus/fallback/escalation rates, accepted constraint violations, cost gap versus solver and latency.
- Failure checks: infeasible case, injected invalid candidate, malformed agent response, timeout. The last two require the coordinator's injection hooks.
- Solver timeouts/errors are not proof of infeasibility. A bounded enumeration over at most eight options can be exhaustively evaluated.

## Claude connection check

The helper uses a key from ANTHROPIC_API_KEY or a hidden interactive prompt. It never writes or prints the key. A real invocation makes one small paid API request; the dry run sends nothing.

From the repository root, using the project's Python environment:

```sh
python tools/person_b/check_claude.py --dry-run
python tools/person_b/check_claude.py --prompt-key
```

Default model: `claude-haiku-5-5`. Change with `--model` or ANTHROPIC_MODEL if the credited workspace uses a different available model. For the real agents, set max_retries=0 in the SDK if the wrapper implements its own single retry. Do not multiply automatic SDK retries by wrapper retries.

Person C owns the runtime API wrapper. Person B's deterministic checks, costs and fallback require no API credits.

## Regulatory notes

14 CFR 121.639 concerns dispatch/takeoff fuel supply for domestic operations. Its 45-minute provision is at normal cruising consumption, after destination and required alternate fuel. Do not describe it as a universal 45-minute holding allowance or full landing-fuel compliance check.

- Fuel source: https://www.ecfr.gov/current/title-14/chapter-I/subchapter-G/part-121/subpart-U/section-121.639
- Wake concepts: https://www.faa.gov/air_traffic/publications/atpubs/atc_html/chap2_section_1.html
- Claude quickstart: https://platform.claude.com/docs/en/get-started
- Haiku model: https://platform.claude.com/docs/en/models/haiku-5-5/overview
- Thinking settings: https://platform.claude.com/docs/en/build-with-claude/effort

No real API call, benchmark result or operational compliance certification is established by this setup note.
