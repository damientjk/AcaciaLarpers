"""100 live agent runs, balanced across the three delay types, without touching the official benchmark.

Builds scenario IDs with the same logic as scenario.fixture_ids() (same seed, load_flights, disruption_type,
scenario_id_for) but draws 34 weather, 33 late-aircraft and 33 both, then interleaves them
(weather, late, both, ...) so any prefix is balanced. Writes logs/benchmark_100.json, never
fixtures/cached/benchmark.json.

    python tools/bench100.py            # all 100 (live, needs ANTHROPIC_API_KEY)
    python tools/bench100.py --first 6  # smoke test on the first 6 IDs
    python tools/bench100.py --ids-only # print the IDs and stop
"""
import argparse
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import benchmark  # noqa: E402
import scenario as S  # noqa: E402

COUNTS = {"weather": 34, "late_aircraft": 33, "both": 33}


def balanced_ids(seed: int | None = None) -> list[str]:
    seed = S.config()["evaluation"]["seed"] if seed is None else seed
    df = S.load_flights()
    per_type = {}
    for dtype, n in COUNTS.items():
        idx = df.index[df.disruption_type == dtype]
        rng = random.Random(f"{seed}-{dtype}")  # the same RNG stream fixture_ids() uses for this type
        per_type[dtype] = [S.scenario_id_for(int(i)) for i in sorted(rng.sample(list(idx), n))]
    ids = []
    for k in range(max(COUNTS.values())):
        ids += [per_type[t][k] for t in ("weather", "late_aircraft", "both") if k < len(per_type[t])]
    assert len(ids) == sum(COUNTS.values()) == len(set(ids)) and S.DEMO_ID not in ids
    return ids


def main(argv: list[str] | None = None) -> dict | None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--first", type=int, default=100, help="run only the first N IDs (smoke test)")
    ap.add_argument("--out", default="logs/benchmark_100.json")
    ap.add_argument("--ids-only", action="store_true")
    a = ap.parse_args(argv)
    ids = balanced_ids()[: a.first]
    if a.ids_only:
        print(",".join(ids))
        return None
    return benchmark.main(["--ids", ",".join(ids), "--agents", str(len(ids)), "--live", "--out", a.out, "--quiet"])


if __name__ == "__main__":
    main()
