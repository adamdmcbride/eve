#!/usr/bin/env python3
"""Public isolated sensory->synapse->motor-reference experiment.

Run in the existing fly numpy/scipy environment. No HTTP, resident organ,
personal memory, model calls, or live learning checkpoint is touched. This
tests the actual connectome and source decoder, not physical locomotion.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time

EVE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVE))


def run(fly_root, *, seed=19):
    import numpy as np
    from eve_synaptic_memory import conditioned_motor_reference
    sys.path.insert(0, str(fly_root))
    from fly_organ import FlyOrgan
    paths = [EVE/"eve_synaptic_memory.py", fly_root/"fly_organ.py", fly_root/"fly_substrate.py",
             fly_root/"body_loop.py", fly_root/"graph/dopamine_classes.json"]
    hashes = lambda: {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    before = hashes()
    tree = ast.parse((fly_root/"body_loop.py").read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "behavior_from_signals")
    ns = {"np": np, "conditioned_motor_reference": conditioned_motor_reference}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(fly_root/"body_loop.py"), "exec"), ns)
    decode = ns[fn.name]
    now = [0.0]
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="eve-synaptic-canary-") as directory:
        organ = FlyOrgan(state_dir=directory, clock=lambda: now[0])
        try:
            if organ.synaptic_error:
                raise RuntimeError(organ.synaptic_error)
            rng = np.random.default_rng(seed)
            sensory = rng.permutation(organ.fs.ports["olfactory"])
            size = len(sensory)//10
            # Existing channel names are merely injection ports in this
            # isolated process. Neither learner nor decoder knows odor labels.
            organ.inputs["olfaction"] = sensory[:size]
            organ.inputs["threat_odor"] = sensory[size:2*size]
            def drive(channels, ticks):
                organ.set_channels(channels, source="body_senses", source_epoch="public-canary",
                    command_id=str(now[0]), ttl_s=20, expected_epoch=organ.arbiter.epoch)
                for _ in range(ticks):
                    if time.monotonic()-started > 480: raise TimeoutError("Canary exceeded eight minutes")
                    now[0] += 0.05
                    organ.step()
            def probe(channel):
                organ.reset()
                drive({channel: 1.0}, 40)
                signals = organ.status()["signals"]
                return {"signals": signals, "behavior": decode(signals), "updates": organ.synapses.updates}
            def condition(gate, *, unpaired=False):
                for _ in range(8):
                    organ.reset()
                    drive({"olfaction": 1.0}, 60)
                    # Advance the actual recurrent dynamics during a delay;
                    # jumping only the clock would leave an artificial cue echo.
                    drive({}, 260 if unpaired else 10)
                    drive({gate: 1.0}, 20)
            arms = {}
            for arm in ("intact", "frozen", "unpaired"):
                organ.forget(); organ.reset(); organ.set_plasticity(arm != "frozen")
                pre = probe("olfaction")
                condition("dopamine_punish", unpaired=arm == "unpaired")
                after = probe("olfaction"); novel = probe("threat_odor")
                arms[arm] = {"before": pre, "after": after, "novel": novel}
                if arm == "intact":
                    organ.checkpoint_synapses()
                    learned = organ.synapses.factors.copy()
                    organ.synapses.forget()
                    restored = organ.synapses.restore(organ.checkpoint)
                    organ.fs.W.data[organ.kc_mbon_pos] = organ.synapses.weights()
                    arms[arm]["restart_weights_equal"] = bool(restored and np.array_equal(learned, organ.synapses.factors))
                    arms[arm]["restart_probe"] = probe("olfaction")
                    condition("dopamine_reward")
                    arms[arm]["reversed"] = probe("olfaction")
            name = lambda row: row["behavior"]["name"]
            checks = {
                "paired_cue_changes_motor_reference": name(arms["intact"]["after"]) == "conditioned_aversion",
                "novel_cue_not_conditioned": name(arms["intact"]["novel"]) != "conditioned_aversion",
                "frozen_control_unchanged": arms["frozen"]["after"]["updates"] == 0 and name(arms["frozen"]["after"]) != "conditioned_aversion",
                "unpaired_control_not_conditioned": name(arms["unpaired"]["after"]) != "conditioned_aversion",
                "restart_retains_behavior": arms["intact"]["restart_weights_equal"] and name(arms["intact"]["restart_probe"]) == "conditioned_aversion",
                "opposite_feedback_reverses_behavior": name(arms["intact"]["reversed"]) == "conditioned_appetitive_search",
                "source_unchanged": hashes() == before,
            }
            return {"schema": "eve.fly_synaptic_canary.v1", "seed": seed, "checks": checks,
                    "passed": all(checks.values()), "arms": arms, "source_sha256": before,
                    "synaptic_fingerprint": organ.synapses.fingerprint,
                    "seconds": round(time.monotonic()-started, 2),
                    "evidence_class": "isolated_connectome_and_motor_reference",
                    "limitations": ["Public same-author experiment, not private holdout",
                        "No live resident weights or autobiographical training", "No physical locomotion or LLM result",
                        "No consciousness inference", "Reconstruction checks weights, not uninterrupted subjective continuity"]}
        finally:
            organ.ledger.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fly-root", type=Path, default=Path.home()/"Documents/eve-fly")
    ap.add_argument("--seed", type=int, default=19)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    result = run(args.fly_root, seed=args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps({k: result[k] for k in ("passed", "seed", "checks", "seconds")}))
    raise SystemExit(0 if result["passed"] else 1)
