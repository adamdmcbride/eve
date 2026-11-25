#!/usr/bin/env python3
"""Measure isolated walking consequences of a qualified synaptic cue readout.

Use the existing flybody TensorFlow environment. Never calls the live organ,
opens a viewer, or records these controlled episodes as Eve's lived experience.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys


def run(receipt, fly_root):
    import numpy as np
    data = json.loads(receipt.read_text())
    if data.get("schema") != "eve.fly_synaptic_canary.v1" or data.get("passed") is not True:
        raise ValueError("Requires a passed full-connectome canary")
    # Inspect only the known candidate paths, not arbitrary paths in a receipt.
    eve = Path(__file__).resolve().parents[1]
    paths = [eve/"eve_synaptic_memory.py", fly_root/"fly_organ.py",
             fly_root/"fly_substrate.py", fly_root/"body_loop.py",
             fly_root/"graph/dopamine_classes.json"]
    hashes = lambda: {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    before = hashes()
    if data.get("source_sha256") != before:
        raise ValueError("Source differs from the supplied sensory learning experiment")
    sys.path.insert(0, str(fly_root))
    import body_loop as body
    body.R.register_legacy_tfp_type_specs()
    policy = body.R.Policy(str(Path(body.R.POLICIES)/"walking"))
    arms = data["arms"]
    probes = [("before", arms["intact"]["before"]), ("learned", arms["intact"]["after"]),
              ("frozen", arms["frozen"]["after"]), ("reversed", arms["intact"]["reversed"])]
    rows = []
    steps = 300
    for name, probe in probes:
        np.random.seed(724)
        env, _ = body.R.make_env("walk")
        try:
            behavior = body.behavior_from_signals(probe["signals"])
            qpos, qvel = body.constant_speed_trajectory(
                n_steps=steps+env.task._future_steps+2, speed=behavior["speed"],
                yaw_speed=behavior["yaw"], control_timestep=env.control_timestep())
            env.task._traj_generator.set_next_trajectory(qpos, qvel)
            ts = env.reset()
            p0 = env.physics.data.qpos.copy()
            count = 0
            for _ in range(steps):
                if ts.last():
                    break
                ts = env.step(body.canonical2real(policy(ts.observation), env.action_spec()))
                count += 1
            p1 = env.physics.data.qpos.copy()
            rows.append({"arm": name, "reference": behavior, "steps": count,
                "simulation_s": count*env.control_timestep(), "initial_qpos": p0.tolist(),
                "final_xyz": p1[:3].tolist(), "travel_cm": float(np.linalg.norm(p1[:2]-p0[:2]))})
        finally:
            env.close()
    checks = {
        "all_300_steps": all(r["steps"] == steps for r in rows),
        "matched_initial_pose": all(np.allclose(r["initial_qpos"], rows[0]["initial_qpos"], atol=1e-7, rtol=0) for r in rows),
        "frozen_matches_baseline": abs(rows[2]["travel_cm"]-rows[0]["travel_cm"]) < .005,
        "learned_moves_more": rows[1]["travel_cm"] > rows[0]["travel_cm"]*1.3,
        "reversal_reduces_aversion_speed": rows[3]["travel_cm"] < rows[1]["travel_cm"]*.8,
        "source_unchanged": before == hashes(),
    }
    return {"schema": "eve.fly_synaptic_body_canary.v1", "checks": checks,
        "passed": all(checks.values()), "rows": rows, "source_sha256": before,
        "source_canary_sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
        "evidence_class": "isolated_mujoco_trained_policy_measured_displacement",
        "limitations": ["Fixed cue readout, not continuously coupled live conditioning",
            "Low-level motion uses a pretrained flybody policy", "No LLM or autonomous Eve initiative",
            "No consciousness inference; motor-policy training and biological dynamics are not replicated"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fly-root", type=Path, default=Path.home()/"Documents/eve-fly")
    args = parser.parse_args()
    result = run(args.receipt, args.fly_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps({"passed": result["passed"], "checks": result["checks"],
                      "travel_cm": {r["arm"]: r["travel_cm"] for r in result["rows"]}}))
    raise SystemExit(0 if result["passed"] else 1)
