"""VLM eval tier: real planner, real API calls, opt-in (costs money).

    EVAL_VLM=1 EVAL_OUT=.tmp_scripts/eval_results pytest -m eval tests/eval/test_vlm_eval.py -s

Runs every synthetic case twice -- planner without and with the MEASUREMENTS block -- so
the Image Report is judged by pass-rate / #steps / latency deltas rather than by feel.
It records, it does not gate: a pass-rate drop is a finding to read, not a red build.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from vlm_photo_editor.analysis import compute_report
from vlm_photo_editor.config.settings import get_settings

from .cases import CASES
from .harness import run_case, write_results

pytestmark = [
    pytest.mark.eval,
    pytest.mark.slow,
    pytest.mark.skipif(os.environ.get("EVAL_VLM") != "1", reason="set EVAL_VLM=1 (paid API calls)"),
]


@pytest.mark.parametrize("use_report", [False, True], ids=["baseline", "with_report"])
def test_vlm_planner_pass_rate(use_report: bool, tmp_path: Path) -> None:
    from vlm_photo_editor.agents.planner import Planner

    planner = Planner()

    def planner_fn(container, intent):
        report = compute_report(container) if use_report else None
        return planner.plan(container, intent, image_report=report)

    def revise_fn(container, plan, error):
        report = compute_report(container) if use_report else None
        return planner.revise(container, plan, error, image_report=report)

    max_repairs = get_settings().max_crop_retries
    results = [run_case(case, planner_fn, revise_fn, max_repairs) for case in CASES]

    label = "with_report" if use_report else "baseline"
    out_dir = Path(os.environ.get("EVAL_OUT") or tmp_path)
    write_results(results, out_dir / f"{label}.json", label=label)
    for r in results:
        print(
            f"[{label}] {r.case}: passed={r.passed} steps={r.n_steps} repairs={r.repairs} "
            f"{r.latency_s}s {r.error or ''}"
        )
    assert len(results) == len(CASES)
