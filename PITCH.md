# 3-minute table pitch

One speaker talks, one drives the laptop. The app is the presentation. Before judges arrive: open the
**Story** page, pick **AA1344 DEN→DFW** in the run picker, and have **Pixel replay** ready to press Play.
If Wi-Fi or the API is down, everything below works from the cached runs.

## 0:00 to 0:30 · The user and the problem (Story page)

"Picture the duty manager at an airline hub. A storm and a late inbound aircraft hit American 1344 from Denver
to Dallas. Today they phone the tower, the captain and the ramp one by one to agree when it lands and which gate
it gets. Every minute of aircraft time costs U.S. airlines about a hundred dollars.

We built three AI agents that do that negotiation in two rounds, with plain code that keeps every plan safe."

## 0:30 to 2:00 · Live demo (Negotiation, then Pixel replay)

1. **Scenario.** "Left is the real 2015 flight row. Right is simulated and labelled: slots, fuel, gates, crew.
   Each agent only sees its own part."
2. **The deadlock.** "We generated six landing plans. Before anyone gives ground, all six break a safety rule:
   the runway slot is taken, the gate is busy, the fuel reserve is too thin, or there's no crew."
3. **Round 1.** "Each agent is its own Claude call. Ava, the tower, frees an earlier slot by resequencing
   another arrival. Pip, the pilot, accepts holding, but only up to his fuel-safe nine minutes. Gus, ground ops,
   moves a crew from B9 to B7."
4. **Coordinator.** "Plain code, no AI, applies those concessions and rechecks everything. One plan is now safe:
   C2, land at 22:24, gate B7. Cost score: $943."
5. **Round 2.** Switch to **Pixel replay**, press Play. "All three accept the same frozen plan. Every hard check
   passes."
6. **Compare.** "The obvious fix, just delay it and keep the planned gate, fails three safety checks and would
   cost over $11,000."
7. **Human in charge.** Back on Negotiation, press **Approve**. "The duty manager has the last word."
8. **Hand over.** "Pick any flight and we'll run it live." (Sidebar: flight and date, or "random qualifying row".)

## 2:00 to 2:45 · Results and a failure (Metrics, then Benchmark)

"We ran 51 seeded scenarios. Before concessions, 26 had a safe plan. After the agents' concessions, 40 did:
the negotiation rescued 14. Zero unsafe plans were ever accepted, and all four failure tests pass: an invalid
proposal is blocked, a garbled reply or an API timeout falls back to the rulebook, and an impossible scenario
escalates.

The other 11 have no safe plan in the options we model. We don't guess: we escalate to the duty manager with the
reasons." (Point at the option funnel on Metrics, then the failure tests on Benchmark.)

## 2:45 to 3:00 · Impact and next steps

"Next: real gate and crew feeds, and several flights competing for the same slots. Thank you."

## Likely questions (owner answers)

| Question | Owner | Short answer |
|---|---|---|
| Where does it fail, and how would the user know? | Yizhuo | Timeout, bad output or no deal goes to the rulebook, labelled fallback. If nothing is safe, it escalates to the human with reasons. |
| How do you stop unsafe plans? | Yizhuo | Agents never decide safety. Eight coded checks run on every plan, and the final plan is rechecked before the human sees it. 0 unsafe plans accepted. |
| What do the agents add over a solver? | Damien | Concessions. The solver only knows the base state. The agents reveal what they can give up, which made 14 more scenarios solvable. On the same options, 6 of 7 live consensus runs matched the solver's cost; one picked a dearer safe plan (mean gap 42.9%). |
| Why do 11 of 51 escalate? | Ashvin | We model up to 8 plans per flight. In these 11, none passes every hard check, mostly because the gate is still occupied at arrival or a taxiway is closed. Refusing is correct, and the duty manager gets the reasons. |
| What's real and what's simulated? | Ashvin | The flight row is real 2015 DOT data. Slots, fuel, gates and crew are simulated, seeded and labelled. Checks are simplified, not FAA compliance. |
| Why two rounds? What about timeouts? | Damien | Bounded time and cost. Per-call timeout and one retry, then fallback. Retries never open a new round. |

Agent-run numbers come from a live benchmark of 10 Claude runs (7 consensus, 3 escalation, 0 unsafe plans accepted, about $0.05 in API cost).
Say "in our simulation" for every number.
