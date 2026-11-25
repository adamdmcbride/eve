#!/usr/bin/env python3
"""Public numerical-controller canary; no live body/model/service is contacted.

This is NOT a private consciousness test. All episodes stay synthetic in a
temporary database. No fixture, prompt, rubric or model narration is ingested
into Eve's lived memory. Compare learned, stale/replayed and no-memory arms.
"""
from pathlib import Path
import argparse
import hashlib
import json
import random
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from eve_embodiment import EmbodiedContinuity


def fingerprints():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in (
        "eve_embodiment.py", "eve_predictive_dynamics.py", "eve_db.py",
        "bin/eve_embodied_canary.py",
    )}


def run():
    frozen = fingerprints()
    results = []
    for seed in (7, 23, 97):
        with tempfile.TemporaryDirectory(prefix="eve-embodied-canary-") as temp:
            path = Path(temp) / "operational_state.sqlite3"
            now = [1789236000.0]
            store = EmbodiedContinuity(path, synthetic=True, clock=lambda: now[0])
            actions = ["motor-a", "motor-b", "motor-c"]
            speeds = [0.3, 1.8, 3.4]
            random.Random(seed).shuffle(speeds)
            initial = dict(zip(actions, speeds))
            changed = dict(zip(actions, speeds[1:] + speeds[:1]))
            seq = [0]

            def sample(x=0):
                seq[0] += 1
                return {"source": "flybody_sensor", "id": f"sample-{seq[0]}", "epoch": f"trial-{seed}",
                        "observed_at": now[0], "sim_time_s": now[0], "xy_cm": [x, 0]}

            def expose(mapping, repeats):
                errors = []
                for _ in range(repeats):
                    for action in actions:
                        plan = store.plan(action, sample(), producer="public_fixture")
                        store.dispatched(plan["action_id"], receipt_id="fixture", backend="synthetic_environment")
                        now[0] += 2
                        result = store.observe(plan["action_id"], sample(mapping[action] * 2), confounded=False)
                        errors.append(result["prediction_error_cm_s"])
                return errors

            expose(initial, 3)
            replayed = store.predictions(actions)
            errors = expose(changed, 8)  # Regime label is never supplied to the predictor.
            restarted = EmbodiedContinuity(path, synthetic=True, clock=lambda: now[0])
            no_memory = EmbodiedContinuity(Path(temp) / "empty.sqlite3", synthetic=True, clock=lambda: now[0])
            trial = {"seed": seed, "unexpected_change_detected": any(e is not None and e > 1 for e in errors[:3]),
                     "restart_predictions_equal": restarted.predictions(actions) == store.predictions(actions),
                     "errors_cm_s": {"learned": [], "replayed": [], "no_memory": []},
                     "optimal_choices": {"learned": 0, "replayed": 0, "no_memory": 0}}
            # New goals were not the training measurements. Same goals/actions
            # and changed world for every arm; no arm sees the hidden mapping.
            for target in (0.1, 1.6, 3.0, 0.6, 2.1, 3.8):
                choices = {
                    "learned": restarted.choose(target, allowed_actions=actions, proposed_action=actions[0])["action"],
                    "replayed": min(actions, key=lambda a: abs(replayed[a]["expected_speed_cm_s"] - target)),
                    "no_memory": no_memory.choose(target, allowed_actions=actions, proposed_action=actions[0])["action"],
                }
                optimal_error = min(abs(v - target) for v in changed.values())
                for arm, action in choices.items():
                    error = abs(changed[action] - target)
                    trial["errors_cm_s"][arm].append(round(error, 6))
                    trial["optimal_choices"][arm] += int(abs(error - optimal_error) < 1e-9)
            results.append(trial)
    drift = fingerprints() != frozen
    passed = not drift and all(r["restart_predictions_equal"] and r["unexpected_change_detected"]
                              and r["optimal_choices"]["learned"] == 6 for r in results)
    return {
        "schema_id": "eve.embodied_public_canary.v1", "passed": passed,
        "evidence_class": "synthetic_controller_integration", "source_drift": drift,
        "source_sha256": frozen, "trials": results,
        "limitations": ["Public fixtures, not private holdout", "No live fly or language-model result",
                        "Same implementation and evaluation owner", "No consciousness score or inference",
                        "Noise-free motor mapping; richer embodied environments remain untested"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run()
    text = json.dumps(report, indent=2, allow_nan=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n")
    print(text)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
