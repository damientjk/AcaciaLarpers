# 3-minute table pitch

One speaker talks, one drives the laptop. The app is the presentation: start on the **Story** page,
demo scenario selected, replay ready.

## 0:00 to 0:30 · The user and the problem (Story page)

"Picture the duty manager at an airline hub. A storm cuts the arrival rate and this flight, American 1344 from
Denver, is running late. Today they phone the tower, the captain and the ramp, one after another, to agree when
it lands and which gate it gets. Every minute of aircraft time costs U.S. airlines about a hundred dollars.

We built three AI agents that do that negotiation for them, in two rounds, with code that keeps every plan safe."

## 0:30 to 2:00 · Live demo (Negotiation page, then Pixel replay)

1. **Scenario.** "Left is the real flight row from the dataset. Right is simulated, and labelled: fuel, gates, crew.
   Each agent only sees its own part."
2. **The conflict.** "Before anyone gives ground, only one plan is safe: C3, 22 minutes late with 12 minutes of
   holding. Simulated cost: about $4,900."
3. **Round 1.** "Gus, the ground agent, offers to move a crew so gate B7 opens. Ava, the tower agent, offers to
   resequence a Boeing 757 to free an earlier slot. Pip, the pilot agent, says he can hold 12 minutes at most."
4. **Coordinator.** "Plain code, no AI, applies those concessions and rechecks. Now C5 is safe: land at 20:32,
   gate B7, no holding. It costs $232."
5. **Round 2.** Switch to **Pixel replay**, press Play. "All three accept the same frozen plan. Every hard check
   passes: fuel, wake spacing, runway capacity, gate, crew."
6. **Human in charge.** Back on Negotiation, press **Approve**. "The duty manager has the last word."
7. **Hand over.** "Pick any flight from the list and we'll run it live." (Use the cached runs if Wi-Fi or the API
   is slow.)

## 2:00 to 2:45 · Results and a failure (Benchmark page)

"Across our test runs: consensus rate, fallback rate, and zero accepted unsafe plans. Here's a failure on purpose:
the ground agent times out. An abstention isn't an accept, so the rulebook takes over and picks C3. It's labelled
as a fallback, never as agreement." (Select the timeout run to show it.)

## 2:45 to 3:00 · Impact and next steps

"Next: real gate and crew feeds, and several flights competing for the same slots. Thank you."

## Likely questions (owner answers)

| Question | Owner | Short answer |
|---|---|---|
| Where does it fail, and how would the user know? | Yizhuo | Timeout, bad output or no deal goes to the fallback, labelled. Nothing feasible escalates to the human. |
| How do you stop unsafe plans? | Yizhuo | Agents never decide safety. The checker blocks every plan, and the final plan is rechecked before the human sees it. |
| What do the agents add over a solver? | Damien | Concessions. The solver only knows the base state. Agents reveal what they can give up, which unlocked C5. |
| What's real and what's simulated? | Ashvin | The flight row is real. Slots, fuel, gates and crew are simulated, seeded and labelled. |
| Why two rounds? What about timeouts? | Damien | Bounded cost and time. 20 s per call, one retry, then fallback. Retries never open a new round. |
