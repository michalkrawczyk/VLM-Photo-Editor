"""Diff two eval result files written by ``harness.write_results``.

    python -m tests.eval.compare .tmp_scripts/eval_results/baseline.json \
        .tmp_scripts/eval_results/with_report.json

Prints deltas (pass-rate, steps, repairs, latency) and every per-case pass/fail flip, so a
prompt or model change is judged by numbers, not by feel. Synthetic cases only: this says
whether the wiring and metrics improved, not whether the photographs look better.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _mean(rows: list[dict], key: str) -> float:
    return sum(r.get(key) or 0 for r in rows) / max(1, len(rows))


def compare(a: dict, b: dict) -> str:
    ra = {r["case"]: r for r in a["results"]}
    rb = {r["case"]: r for r in b["results"]}
    shared = sorted(ra.keys() & rb.keys())
    lines = [
        f"A: {a['label']} (prompt {a.get('prompt_sha', '?')})   "
        f"B: {b['label']} (prompt {b.get('prompt_sha', '?')})   cases compared: {len(shared)}",
        f"pass-rate  {a['pass_rate']:.2f} -> {b['pass_rate']:.2f}",
    ]
    for key in ("n_steps", "repairs", "latency_s"):
        lines.append(
            f"{key:<10} {_mean(list(ra.values()), key):.2f} -> {_mean(list(rb.values()), key):.2f}"
        )
    flips = [
        (c, ra[c]["passed"], rb[c]["passed"]) for c in shared if ra[c]["passed"] != rb[c]["passed"]
    ]
    lines.append("flips: " + ("none" if not flips else ""))
    lines += [f"  {c}: {'pass' if x else 'FAIL'} -> {'pass' if y else 'FAIL'}" for c, x, y in flips]
    only = sorted(ra.keys() ^ rb.keys())
    if only:
        lines.append(f"not in both files: {', '.join(only)}")
    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    print(compare(_load(sys.argv[1]), _load(sys.argv[2])))
