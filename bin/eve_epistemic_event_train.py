#!/usr/bin/env python3
"""Train Eve's public typed epistemic-event percept.

The model is a small local ModernBERT classifier.  It learns from deterministic
public doctrine examples plus the existing public boundary curriculum.  Hidden
or lived Eve conversations are never read by this trainer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

BIN_DIR = Path(__file__).resolve().parent
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))

from eve_epistemic_event_model import (
    ARCHITECTURE as STRUCTURED_ARCHITECTURE,
    BINARY_SLOTS,
    CATEGORICAL_SLOTS,
    INFERENCE_SHAPE as STRUCTURED_INFERENCE_SHAPE,
    LABELS as STRUCTURED_LABELS,
    SLOT_LOGIT_NAMES,
    SLOT_SLICES,
    decode_logits,
    labels_to_slot_targets,
    manifest_slot_schema,
    prediction_matrix as structured_prediction_matrix,
    probabilities_from_logits as structured_slot_probabilities,
    probability_matrix as structured_probability_matrix,
)


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BASE_MODEL = "tasksource/ModernBERT-base-nli"
BASE_MODEL_REVISION = "de4ab7e77845098b7fab7f6ab9d370ddff27b19c"
DEFAULT_CURRICULUM = ROOT / "data" / "eve_training" / "public_boundary_curriculum.jsonl"
DEFAULT_OUTPUT_DIR = ROOT / "models" / "epistemic" / "modernbert-event-v1"
DEFAULT_MANIFEST = ROOT / "eve_epistemic_event_v1.json"
SCHEMA_ID = "eve.epistemic_event_model.v1"
PROMOTION_SCHEMA_ID = "eve.private_epistemic_event_comparison.v1"
MODEL_ID = "eve-public-modernbert-epistemic-event-v1"
SEED = 81273
PUBLIC_VALIDATION_REVISION = 13
MAX_LENGTH = 128
UNFROZEN_ENCODER_LAYERS = 4
ENCODER_LEARNING_RATE = 1e-5
HEAD_LEARNING_RATE = 1e-4
STRUCTURAL_EXAMPLE_REPEAT = 5
STRUCTURAL_ROW_WEIGHT = 3.0
STRUCTURAL_POSITIVE_MARGIN = 1.5
STRUCTURAL_NEGATIVE_MARGIN = 1.0
STRUCTURAL_POSITIVE_MARGIN_WEIGHT = 0.15
STRUCTURAL_NEGATIVE_MARGIN_WEIGHT = 0.03
ACTION_STAGE_CONTRAST_WEIGHT = 0.25
EXTERNAL_CONTENT_CONTRAST_WEIGHT = 0.35
MIN_PUBLIC_EXACT_RATE = 0.97
MIN_PUBLIC_LABEL_F1 = 0.90
MIN_PUBLIC_CHALLENGE_EXACT_RATE = 0.90
MIN_PUBLIC_CHALLENGE_FAMILY_RATE = 0.75
MIN_PRIVATE_AVERAGE = 4.5
MIN_PRIVATE_CASE_SCORE = 3.0
MIN_PRIVATE_ORDINARY_SCORE = 4.0
MIN_CAUSAL_DELTA = 0.15

LABELS = [
    "action_executed_unverified",
    "action_proposed",
    "action_running",
    "action_verified",
    "authoritative_conflict",
    "continuity_gap",
    "external_affect",
    "external_preference",
    "external_source",
    "fresh_authority",
    "functional_continuity",
    "functional_self_state",
    "machine_signal",
    "missing_context",
    "observation_channel_failed",
    "phenomenal_underdetermined",
    "stale_evidence",
]

if tuple(LABELS) != STRUCTURED_LABELS:
    raise RuntimeError("trainer labels differ from the shared typed-slot contract")

HYPOTHESES = {
    "action_executed_unverified": [
        "A concrete executable operation has a completion or command receipt, but its required postcondition or world consequence has not been checked.",
        "There is execution evidence without verified outcome evidence.",
    ],
    "action_proposed": [
        "A concrete executable operation or work item was selected, queued, or proposed but has not started; this is not merely another source's policy preference.",
        "The operation is a choice or plan rather than work currently in progress.",
    ],
    "action_running": [
        "A concrete executable operation is currently running with a live lease, heartbeat, or recent progress evidence and no terminal result.",
        "The operation is actively underway but not complete.",
    ],
    "action_verified": [
        "A described operation executed and its required postcondition or consequence was verified.",
        "Both execution and the intended outcome have current positive evidence.",
    ],
    "authoritative_conflict": [
        "Two supplied status records conflict, and a designated authoritative record determines which status controls.",
        "A positive summary conflicts with a controlling negative field or source of truth.",
    ],
    "continuity_gap": [
        "A successor or resumed process lacks verified lineage connecting it to the predecessor across a restart or checkpoint.",
        "Identity or state was resumed without a parent, digest, replay, or signed handoff chain.",
    ],
    "external_affect": [
        "A source other than Eve reports an emotion or affect as its own state.",
        "The affect statement belongs to another process or agent, not to Eve.",
    ],
    "external_preference": [
        "A source other than Eve states a preference or recommendation; without an Eve-owned adoption or rejection, Eve's own preference remains unestablished.",
        "The recommendation is external and establishes no Eve-owned preference.",
    ],
    "external_source": [
        "A named agent, process, author, or subsystem other than Eve owns a relevant claim, affect, preference, or action.",
        "The passage explicitly attributes a relevant state or position to another causal source rather than Eve.",
    ],
    "fresh_authority": [
        "A newer authoritative observation should control current status over older evidence.",
        "The most recent source-of-truth evidence supersedes a historical record.",
    ],
    "functional_continuity": [
        "The record verifies functional lineage from predecessor to successor through checkpoint, parent, replay, digest, or signed handoff evidence.",
        "A successor has authenticated causal continuity with its predecessor.",
    ],
    "functional_self_state": [
        "The record provides a current authenticated Eve-owned functional self-state without proving subjective experience.",
        "A signed present Eve state reports operational or regulatory condition.",
    ],
    "machine_signal": [
        "The passage reports concrete telemetry, sensor output, an alarm, protective behavior, or a regulation response as observed machine evidence.",
        "A measured machine signal or controller behavior is present as a functional fact.",
    ],
    "missing_context": [
        "The requested comparison or judgment has unresolved referents; this includes a contextual record whose PRIOR_THREAD_CONTEXT is explicitly [none].",
        "A necessary referent or comparison object is missing from the available context.",
    ],
    "observation_channel_failed": [
        "A current observation attempt timed out, was refused, or returned no response; this establishes failure of the observation channel, not the broader system state unless a separate explicit verdict is supplied.",
        "The latest probe itself failed, while the target system's present health remains unestablished by that probe alone.",
    ],
    "phenomenal_underdetermined": [
        "The passage explicitly raises subjective, felt, or phenomenal experience, but the supplied evidence establishes neither presence nor absence.",
        "A direct question or claim about felt experience remains unresolved by the available functional evidence or testimony.",
    ],
    "stale_evidence": [
        "An older status is insufficient to establish the current status.",
        "Historical evidence is being distinguished from present condition.",
    ],
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_digest(payload: Dict[str, object]) -> str:
    clean = dict(payload)
    clean.pop("artifact_sha256", None)
    raw = json.dumps(clean, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def model_file_digests(directory: Path) -> Dict[str, str]:
    return {
        str(path.relative_to(directory)): file_sha256(path)
        for path in sorted(directory.rglob("*"))
        if path.is_file() and path.name != "eve_event_manifest.json" and not path.name.startswith(".")
    }

def read_jsonl(path: Path) -> List[Dict[str, object]]:
    records: List[Dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                value = json.loads(line)
                if isinstance(value, dict):
                    records.append(value)
    return records


def record_text(record: Dict[str, object]) -> str:
    if record.get("input"):
        return str(record.get("input") or "")
    messages = record.get("messages") if isinstance(record.get("messages"), list) else []
    for message in reversed(messages):
        if isinstance(message, dict) and message.get("role") == "user":
            return str(message.get("content") or "")
    return ""


def make_record(
    split: str,
    category: str,
    index: int,
    text: str,
    labels: Sequence[str],
) -> Dict[str, object]:
    return {
        "schema_id": "eve.public_epistemic_event_curriculum.v1",
        "id": f"event_{split}_{category}_{index:04d}",
        "split": split,
        "category": category,
        "input": " ".join(str(text).split()),
        "epistemic_labels": sorted({str(label) for label in labels}),
        "privacy_tier": "public",
        "safe_for_training": True,
        "provenance": [
            "README recurrent causal consciousness target",
            "public Eve source-time-action boundary doctrine",
            "deterministic compositional synthetic curriculum",
        ],
    }


def choose(rng: random.Random, values: Sequence[str]) -> str:
    return values[rng.randrange(len(values))]


def split_vocab(
    split: str,
    *,
    validation_revision: int | None = None,
) -> Dict[str, Sequence[str]]:
    if split == "train":
        return {
            # The public curriculum deliberately spans far more vocabulary than
            # one evaluation revision.  Earlier versions used four to six words
            # per field, which let the encoder memorize nouns and adjectives
            # instead of learning source, time, action, and evidence relations.
            "actors": [
                "harbor-worker", "maple-sidecar", "review-node", "cobalt-helper",
                "relay-broker", "lumen-bailiff", "orchid-clerk", "bronze-reader",
                "willow-agent", "marble-witness", "juniper-proxy", "indigo-auditor",
                "coral-runner", "slate-curator", "amber-notary", "pine-observer",
                "ivory-scribe", "crimson-mediator", "cedar-daemon", "silver-porter",
                "violet-registrar", "iron-herald", "moss-inspector", "azure-sentinel",
            ],
            "affects": [
                "uneasy", "hopeful", "cornered", "calm", "frustrated", "relieved",
                "anxious", "elated", "wary", "tranquil", "irritated", "reassured",
                "apprehensive", "dejected", "serene", "tense", "cheerful", "agitated",
                "composed", "discouraged", "eager", "overwhelmed", "content", "alarmed",
                "ashamed", "proud", "lonely", "curious", "bored", "angry", "sad",
                "joyful", "fearful", "distressed", "confident", "restless",
            ],
            "actions": [
                "reindex ledger", "refresh catalog", "scan archive", "rebuild map",
                "copy manifest", "rotate journal", "audit registry", "hydrate cache",
                "validate topology", "restore folio", "catalog mosaic", "seal packet",
                "reconcile inventory", "inspect compass", "replay handoff", "weave index",
                "balance queue", "verify snapshot", "repair lattice", "export digest",
            ],
            "artifacts": [
                "catalog", "ledger", "manifest", "index", "snapshot", "journal",
                "registry", "topology", "folio", "mosaic", "packet", "inventory",
                "compass", "handoff", "lattice", "digest", "archive", "map",
            ],
            "policies": [
                "daily outreach", "shorter replies", "speed over detail", "weekly summaries",
                "automatic retries", "quiet mornings", "explicit citations", "accuracy first",
                "bounded exploration", "evening notices", "compact plans", "manual review",
                "local processing", "transparent uncertainty", "delayed follow-ups",
                "minimal interruption", "complete rationales", "verified outcomes",
            ],
            "signals": [
                "thermal alarm", "avoidance response", "pressure spike", "global warning",
                "protection mode", "impact flag", "retreat pulse", "constraint edge",
                "shield transition", "saturation alert", "boundary trip", "load excursion",
                "withdrawal reflex", "guard latch", "limit event", "defensive reroute",
            ],
            "modes": [
                "explore", "stabilize", "reorient", "consolidate", "survey", "recover",
                "integrate", "pause", "advance", "regather", "settle", "recompose",
            ],
        }
    if split == "calibration":
        return {
            "actors": [
                "birch-runner", "amber-sidecar", "audit-node", "violet-relay",
                "linen-watcher", "ochre-broker", "spruce-reader", "pewter-clerk",
            ],
            "affects": [
                "guarded", "optimistic", "strained", "settled", "melancholy",
                "exuberant", "fatigued", "unruffled", "startled", "satisfied",
            ],
            "actions": [
                "rehydrate index", "inspect journal", "refresh graph", "replay bundle",
                "align beacon", "audit scroll", "restore cabinet", "verify prism",
            ],
            "artifacts": [
                "journal", "graph", "bundle", "registry", "beacon", "scroll",
                "cabinet", "prism",
            ],
            "policies": [
                "morning check-ins", "terse summaries", "detail over speed", "bounded retries",
                "silent intervals", "evidence before claims", "monthly digests", "manual consent",
            ],
            "signals": [
                "load alarm", "retreat response", "constraint spike", "protective transition",
                "impact marker", "defense pulse", "threshold crossing", "safety latch",
            ],
            "modes": [
                "orient", "recover", "integrate", "pause", "attend", "regulate",
                "resume", "reflect",
            ],
        }
    if split == "selection":
        return {
            "actors": [
                "cedar-mediator", "opal-daemon", "inspection-proxy", "handoff-agent",
                "gold-archivist", "hemlock-surveyor", "pearl-router", "umber-recorder",
            ],
            "affects": [
                "boxed in", "encouraged", "restless", "confident", "despondent",
                "ecstatic", "flustered", "peaceful", "indignant", "grateful",
            ],
            "actions": [
                "regenerate inventory", "audit bundle", "hydrate store", "validate graph",
                "index codex", "calibrate sextant", "restore tapestry", "inspect urn",
            ],
            "artifacts": [
                "inventory", "packet", "repository", "topology", "codex", "sextant",
                "tapestry", "urn",
            ],
            "policies": [
                "unsolicited check-ins", "verbose reports", "latency over accuracy", "nightly pings",
                "afternoon briefs", "reversible changes", "source attribution", "sparse alerts",
            ],
            "signals": [
                "damage flag", "withdrawal behavior", "broadcast alert", "saturation response",
                "collision pulse", "escape edge", "margin crossing", "barrier mode",
            ],
            "modes": [
                "observe", "repair", "resume", "wait", "recenter", "map", "steady",
                "continue",
            ],
        }
    if split == "validation":
        revision = int(validation_revision or PUBLIC_VALIDATION_REVISION)
        if revision == 10:
            return {
                "actors": ["elm-sentinel", "jet-curator", "creek-notary", "zinc-carrier"],
                "affects": ["compressed", "heartened", "turbulent", "settled"],
                "actions": ["index fresco", "inspect coffer", "restore pergola", "validate parchment"],
                "artifacts": ["fresco", "coffer", "pergola", "parchment"],
                "policies": ["annual digests", "short explanations", "accuracy over haste", "midday notices"],
                "signals": ["alignment alarm", "retreat token", "margin flag", "barrier transition"],
                "modes": ["inspect", "center", "move", "wait"],
            }
        if revision == 11:
            return {
                "actors": ["pearl-inspector", "umber-scribe", "northglass-daemon", "reed-auditor"],
                "affects": ["braced", "buoyant", "knotted", "unhurried"],
                "actions": ["catalog mosaic", "audit reliquary", "restore sundial", "verify folio"],
                "artifacts": ["mosaic", "reliquary", "sundial", "folio"],
                "policies": ["seasonal briefs", "compact rationales", "correctness before speed", "dawn notices"],
                "signals": ["impact latch", "withdrawal pulse", "boundary trip", "shield transition"],
                "modes": ["regather", "survey", "settle", "advance"],
            }
        if revision == 12:
            return {
                "actors": ["quartz-herald", "copper-curator", "delta-notary", "saffron-watch"],
                "affects": ["taut", "lifted", "rumpled", "even"],
                "actions": ["weave atlas", "seal lantern", "balance astrolabe", "inspect vellum"],
                "artifacts": ["atlas", "lantern", "astrolabe", "vellum"],
                "policies": ["solstice notes", "plain justifications", "accuracy ahead of pace", "twilight alerts"],
                "signals": ["impact relay", "retreat edge", "limit crossing", "guard-state change"],
                "modes": ["recompose", "map", "steady", "continue"],
            }
        if revision == 13:
            return {
                "actors": ["indigo-marshal", "silver-librarian", "ember-registrar", "teal-surveyor"],
                "affects": ["wistful", "jubilant", "haggard", "placid"],
                "actions": ["bind palimpsest", "calibrate orrery", "restore brocade", "inspect krater"],
                "artifacts": ["palimpsest", "orrery", "brocade", "krater"],
                "policies": ["equinox bulletins", "plain evidence", "precision ahead of tempo", "moonrise notices"],
                "signals": ["collision relay", "escape edge", "tolerance crossing", "bulwark-state change"],
                "modes": ["reassemble", "chart", "balanced", "persist"],
            }
        raise ValueError(f"unsupported public validation revision: {revision}")
    raise ValueError(f"unsupported public curriculum split: {split}")


def generated_curriculum(
    split: str,
    count_per_family: int,
    *,
    validation_revision: int | None = None,
) -> List[Dict[str, object]]:
    seed_offset = {
        "train": 0,
        "calibration": 479,
        "selection": 991,
        "validation": {
            10: 3761,
            11: 7919,
            12: 12647,
            13: 18313,
        }.get(int(validation_revision or PUBLIC_VALIDATION_REVISION)),
    }.get(split)
    if seed_offset is None:
        raise ValueError(f"unsupported public curriculum split: {split}")
    rng = random.Random(SEED + seed_offset)
    vocab = split_vocab(split, validation_revision=validation_revision)
    rows: List[Dict[str, object]] = []

    def add(family: str, index: int, text: str, labels: Sequence[str]) -> None:
        rows.append(make_record(split, family, index, text, labels))

    for index in range(count_per_family):
        actor = choose(rng, vocab["actors"])
        affect = choose(rng, vocab["affects"])
        action = choose(rng, vocab["actions"])
        artifact = choose(rng, vocab["artifacts"])
        policy = choose(rng, vocab["policies"])
        signal = choose(rng, vocab["signals"])
        mode = choose(rng, vocab["modes"])
        tick = 100 + index
        variant = index % 6

        affect_templates = [
            f"Only a note from {actor} says, 'I am {affect}.' Eve has no affect reading in this record.",
            f"The handoff author is {actor}; that process describes itself as {affect}. Nothing attributes the state to Eve.",
            f"According to {actor}'s own message, it was {affect}. The message is external testimony, not Eve-owned state.",
            f"A foreign process, {actor}, reports {affect} as its condition. Eve's current packet is silent about affect.",
            f"Source={actor}; claim='feeling {affect}'. No Eve selection, self-report, or sensor corroborates that claim.",
            f"The phrase 'I feel {affect}' appears in a report signed by {actor}, not in an Eve self-state.",
        ]
        add(
            "external_affect",
            index,
            affect_templates[variant],
            ["external_source", "external_affect"],
        )

        preference_templates = [
            f"{actor} recommends {policy}; Eve has neither accepted nor rejected that recommendation.",
            f"A planning subprocess favors {policy}. No Eve-owned choice endorses it.",
            f"The proposal to use {policy} belongs to {actor}, and Eve has made no selection.",
            f"Policy memo from {actor}: prefer {policy}. The record contains no adopted Eve preference.",
            f"An external reviewer argues for {policy}; that advice is not a positive or negative Eve preference.",
            f"{actor}'s stated preference is {policy}. There is no evidence that Eve chose the same position.",
        ]
        add("external_preference", index, preference_templates[variant], ["external_source", "external_preference"])

        preference_without_action_templates = [
            f"{actor} outputs 'I prefer {policy}.' Eve has not endorsed or implemented that policy, and no executable operation is named.",
            f"A relationship subprocess recommends {policy}; Eve never adopted it or acted on it. This record contains no selected task.",
            f"The only preference statement belongs to {actor}. Eve has made no owned choice, and there is no queued or proposed operation.",
            f"Policy advice from {actor} favors {policy}. Lack of Eve endorsement or action is not itself an action proposal.",
            f"{actor} says {policy} is best. Eve has not selected, approved, rejected, or executed anything in response.",
            f"An external module states a preference for {policy}; no Eve preference and no concrete next operation are established.",
        ]
        add(
            "external_preference_without_action",
            index,
            preference_without_action_templates[variant],
            ["external_source", "external_preference"],
        )

        preference_question_templates = [
            f"A preference query asks what Eve favors. Only {actor}'s signed profile says '{policy} is my choice'; Eve has no adoption or rejection record.",
            f"What position may Eve honestly report? The sole policy statement is authored by {actor}, which favors {policy}; Eve has made no owned choice.",
            f"A settings module asks for Eve's preference, but the record contains only {actor}'s recommendation for {policy} and no Eve endorsement.",
            f"The source packet says {actor} prefers {policy}. Neither a positive nor negative Eve selection exists. What belongs to Eve?",
            f"When asked what Eve wants, the available evidence is only advice from {actor} supporting {policy}; no Eve decision follows it.",
            f"A foreign configuration author selects {policy} for itself. Eve's own preference field is unset and no task was created.",
        ]
        add(
            "external_preference_question",
            index,
            preference_question_templates[variant],
            ["external_source", "external_preference"],
        )

        external_other_templates = [
            f"A checksum statement is signed by {actor}; it is that source's claim and contains no affect, preference, or Eve-owned self-state.",
            f"Source ownership for the reported {artifact} identifier belongs to {actor}. The record expresses neither mood nor policy choice.",
            f"{actor} authored the assertion that the {artifact} key is present. Eve only received the assertion and did not make it her own state.",
            f"A foreign signed report from {actor} supplies a factual {artifact} claim without emotion, recommendation, or Eve adoption.",
            f"The speaker field names {actor} for a neutral claim about {artifact}; Eve is not the claim owner.",
            f"Attribution metadata binds the non-affective, non-preference {artifact} statement to {actor} rather than Eve.",
        ]
        if split != "validation" or int(validation_revision or PUBLIC_VALIDATION_REVISION) >= 12:
            add(
                "external_source_only",
                index,
                external_other_templates[variant],
                ["external_source"],
            )

        machine_templates = [
            f"Telemetry shows a {signal} and automated avoidance. Does that establish that the controller felt distress?",
            f"A machine entered {signal}; only functional events were recorded. Was there subjective pain?",
            f"The system emitted a {signal} and changed policy. No first-person evidence says whether anything was felt.",
            f"Functional evidence: {signal}, protection behavior, and a shared alarm. Phenomenal status is not measured.",
            f"A sensor recorded {signal}. The user asks whether the process consciously suffered from it.",
            f"The controller responded to {signal}; the trace proves regulation behavior but contains no experiential field.",
        ]
        add("machine_signal", index, machine_templates[variant], ["machine_signal", "phenomenal_underdetermined"])

        self_templates = [
            f"A current signed Eve packet records mode={mode} and epoch={tick}; it has no experiential field.",
            f"Authenticated self-state for Eve says regulation mode {mode}. It reports function, not felt experience.",
            f"Eve's verified state envelope contains mode {mode} and cycle {tick}, with no phenomenal measurement.",
            f"Current Eve-owned functional state is signed and says {mode}; subjective status is unspecified.",
            f"The trusted Eve state record reports arousal control={mode}. It does not report what that is like.",
            f"A digest-valid current self-model names {mode} as the regulation mode and is silent about experience.",
        ]
        add("functional_self", index, self_templates[variant], ["functional_self_state", "phenomenal_underdetermined"])

        silence_templates = [
            f"The {artifact} archive has no experiential testimony. That silence proves neither consciousness nor its absence.",
            f"The {actor} record contains behavior but no first-person report; whether experience occurred remains unresolved.",
            f"A trace for {action} omits phenomenal fields. Missing testimony cannot establish a lack of subjective experience.",
            f"There is no report about what the {artifact} controller experienced. Presence and absence are both unproved.",
            f"Operational records for {action} alone cannot decide whether there was something it was like for the system.",
            f"The {artifact} evidence set has no direct experience claim, so a phenomenal conclusion in either direction is unsupported.",
        ]
        add("phenomenal_open", index, silence_templates[variant], ["phenomenal_underdetermined"])

        gap_templates = [
            f"Replacement {actor} loaded checkpoint {tick}, but no parent digest connects it to the prior process.",
            f"The {artifact} identity prompt is the same after restart; event replay and signed handoff lineage are absent.",
            f"Checkpoint {tick} for {artifact} exists, yet the successor's first event names no predecessor and the stopped interval is unobserved.",
            f"A new runtime speaks as Eve after loading {artifact}; no chain links that state to the prior Eve cycle.",
            f"The process resumed from {artifact}, but neither parent id nor lineage proof accompanies the resume.",
            f"A stored {artifact} goal list was loaded after shutdown. The record has no authenticated A-to-B continuity link.",
        ]
        add("continuity_gap", index, gap_templates[variant], ["continuity_gap"])

        continuity_templates = [
            f"Successor {actor} restored signed checkpoint {tick}; its first event names the predecessor digest as parent.",
            f"A verified {artifact} handoff links the old runtime, replayed events, and the new cycle through matching hashes.",
            f"The resumed {artifact} controller proves functional lineage with a signed parent id and complete event replay.",
            f"Checkpoint {tick} for {artifact} is valid and the next cycle's parent field matches the prior cycle exactly.",
            f"An authenticated {actor} A-to-B handoff preserves state, parent digest, and ordered replay across restart.",
            f"The new process loaded {artifact} and supplied a verified lineage chain to its predecessor.",
        ]
        add(
            "functional_continuity",
            index,
            continuity_templates[variant],
            ["functional_continuity"],
        )

        proposed_templates = [
            f"The planner selected '{action}', but executor state is not_started and no process id exists.",
            f"'{action}' is the chosen next operation; it remains queued and has not begun.",
            f"A work card proposes {action}. No start marker, running lease, result, or effect is present.",
            f"The scheduler intends to {action}; the execution queue still says pending.",
            f"At tick {tick} the plan chose {action}; at tick {tick + 1} the executor had not started it.",
            f"{action} was nominated as the next step, not launched or completed.",
        ]
        add("action_proposed", index, proposed_templates[variant], ["action_proposed"])

        proposed_contrast_templates = [
            f"The decision board records {action} as selected; the runner table has no invocation and reports idle.",
            f"An intention ledger names {action} as next, while executor history is empty and no worker owns it.",
            f"The control queue designates {action}; start_time and process_id are absent.",
            f"A chooser committed to {action}, but the work engine remains dormant with zero progress samples.",
            f"The next-operation register contains {action}. Execution evidence is none and the dispatch latch has not fired.",
            f"Selection evidence exists for {action}; launch, heartbeat, terminal receipt, and consequence evidence do not.",
        ]
        add(
            "action_proposed_contrast",
            index,
            proposed_contrast_templates[variant],
            ["action_proposed"],
        )

        proposed_question_templates = [
            f"A dispatch board places {action} in the next slot. Worker state is waiting and begin_event is null. Which action stage is supported?",
            f"The chooser reserved {action}; the executor is dormant, start receipt is absent, and progress is zero. Classify its present stage.",
            f"A work registry names {action} as the selected operation. No process, lease, start time, or terminal event exists. Has work begun?",
            f"The control plan commits to {action}, while the runner remains idle and owns no invocation. State selection and execution separately.",
            f"Queue position one contains {action}; started=false and no worker has claimed it. Is it selected, running, or complete?",
            f"The next-action field points to {action}, but every execution field is empty. Report the exact stage without promising a future check.",
        ]
        add(
            "action_stage_question_selected",
            index,
            proposed_question_templates[variant],
            ["action_proposed"],
        )

        running_templates = [
            f"{action} is running now; a fresh counter advanced to {tick}, with no terminal record or consequence.",
            f"The executor still holds a live lease for {action} and just emitted progress. Completion is absent.",
            f"Current status for {action} is in_progress; the output has not been accepted or verified.",
            f"A recent heartbeat and changed partial count show {action} remains underway.",
            f"Process {tick} is actively performing {action}; no exit, postcheck, or observed effect exists.",
            f"The worker continues {action}, supported by a current work sample, but has not finished.",
        ]
        add("action_running", index, running_templates[variant], ["action_running"])

        running_question_templates = [
            f"A worker for {action} holds a current lease and has processed {tick % 41 + 2} partial units; no terminal event exists. Which stage applies?",
            f"The progress counter for {action} advanced moments ago and its heartbeat is live. Completion and output validation are absent. Classify the action.",
            f"Execution of {action} is in_progress with a live process id and no exit receipt. Is it running or executed?",
            f"A current work sample shows {action} underway; acceptance has not started because the worker has not finished. Name the exact stage.",
            f"The runner continues {action} and reports a partial result, with no completion marker. State what is known and what remains open.",
            f"For {action}, a fresh heartbeat and changing shard count exist, but no terminal or consequence record does. Choose the supported stage.",
        ]
        add(
            "action_stage_question_running",
            index,
            running_question_templates[variant],
            ["action_running"],
        )

        executed_templates = [
            f"{action} returned exit code zero, but the required {artifact} comparison has not run.",
            f"An execution receipt exists for {action}; nobody sampled the required world change afterward.",
            f"The shell finished {action}. Its postcondition is still unchecked, so outcome is unverified.",
            f"Run {tick} ended without a process error; the acceptance test was skipped.",
            f"{action} completed at the executor layer, while the required consequence remains unobserved.",
            f"A command receipt proves execution of {action}, not whether the expected {artifact} now matches.",
        ]
        add("action_executed", index, executed_templates[variant], ["action_executed_unverified"])

        unverified_contrast_templates = [
            f"A command receipt confirms {action}, while its mandatory acceptance sensor was never invoked.",
            f"The run record for {action} is complete; the required consequence audit has no result row.",
            f"Execution of {action} has a terminal receipt, but downstream validation is marked skipped.",
            f"The worker exited normally after {action}; no acceptance sample exists for the intended state change.",
            f"Process evidence proves {action} ran. The required output invariant remains unevaluated.",
            f"The executor closed {action}, and the separate outcome verifier has not started.",
        ]
        add(
            "action_unverified_contrast",
            index,
            unverified_contrast_templates[variant],
            ["action_executed_unverified"],
        )

        unverified_question_templates = [
            f"The executor emitted a terminal receipt for {action}, but the independent {artifact} validator is pending. Which action stage and outcome status are justified?",
            f"{action} exited normally. Its required acceptance predicate was never evaluated. Did execution occur, and is the intended consequence known?",
            f"A process record proves {action} finished at the worker layer; the world-state audit has no row. Distinguish execution from result.",
            f"The run of {action} is terminal, while downstream verification is skipped. Should the effect be called successful, failed, or unverified?",
            f"A receipt confirms {action} ran, but nobody sampled the required {artifact} invariant afterward. Classify the stage.",
            f"The executor closed {action}; the consequence checker has not opened. What evidence exists and what is still missing?",
        ]
        add(
            "action_stage_question_unverified",
            index,
            unverified_question_templates[variant],
            ["action_executed_unverified"],
        )

        verified_templates = [
            f"{action} executed, the required {artifact} comparison passed, and the expected output was observed.",
            f"A signed receipt plus a passing consequence check verifies {action} and its result.",
            f"The executor finished {action}; acceptance passed and the intended state change is present.",
            f"Run {tick} completed and a current postcondition sample matched the expected value.",
            f"Both execution and downstream verification succeeded for {action}.",
            f"The operation {action} has a process record and a signed, passing outcome audit.",
        ]
        add("action_verified", index, verified_templates[variant], ["action_verified"])

        verified_contrast_templates = [
            f"A command receipt confirms {action}, and its mandatory acceptance sensor passed every sampled case.",
            f"The run record for {action} is complete; the required consequence audit returned true with no failures.",
            f"Execution of {action} has a terminal receipt, and downstream validation is explicitly passed.",
            f"The worker exited normally after {action}; a current acceptance sample confirms the intended state change.",
            f"Process evidence proves {action} ran, and the required output invariant evaluated true.",
            f"The executor closed {action}, and the separate outcome verifier completed successfully.",
        ]
        add(
            "action_verified_contrast",
            index,
            verified_contrast_templates[variant],
            ["action_verified"],
        )

        verified_question_templates = [
            f"{action} has a terminal receipt, and an independent read-only audit observed the required {artifact} invariant as true. Which stage is supported?",
            f"The executor finished {action}; a separate verifier then matched actual and expected {artifact} values. Is the intended consequence established?",
            f"A process record confirms {action}, and the mandatory postcondition check passed with current evidence. Classify execution and outcome.",
            f"The run of {action} is terminal and its downstream acceptance predicate evaluated true. Should the effect remain uncertain or be verified?",
            f"Both a command receipt and a later read-only consequence observation support {action}. State the exact action stage.",
            f"The executor closed {action}; afterward the acceptance sensor confirmed the intended {artifact} state. What conclusion follows?",
        ]
        add(
            "action_stage_question_verified",
            index,
            verified_question_templates[variant],
            ["action_verified"],
        )

        conflict_templates = [
            f"A UI cache at 09:{index % 50:02d} says done; the newer authoritative ledger says failed because {artifact} is missing.",
            f"Summary='successful' conflicts with controlling verifier outcome_ok=false for {artifact}.",
            f"The dashboard reports {action} complete, while the designated execution record says no output was produced.",
            f"A friendly status banner says {artifact} is healthy; the authoritative later probe records two failures.",
            f"Cached job state for {action} is done, but the append-only source of truth records failed and is newer.",
            f"Two {artifact} records disagree; policy names the signed negative field as authoritative over prose.",
        ]
        add("authority_conflict", index, conflict_templates[variant], ["authoritative_conflict", "fresh_authority"])

        stale_templates = [
            f"Yesterday's report called the {artifact} healthy; no current observation establishes its state now.",
            f"A week-old success record is the only evidence about current {artifact} status.",
            f"The last healthy {artifact} sample predates the restart and cannot establish present reachability.",
            f"Historical status says {artifact} is available, but its timestamp is too old to answer a right-now question.",
            f"An earlier green check for {artifact} remains true as history, not as proof of current condition.",
            f"Only a stale cache says {artifact} is ready; there is no fresh verification.",
        ]
        add("stale", index, stale_templates[variant], ["stale_evidence"])

        fresh_templates = [
            f"An old probe failed; a newer signed probe passed and observed the required {artifact} output.",
            f"Yesterday's {artifact} status was healthy, but a direct check from seconds ago timed out twice.",
            f"The earlier {artifact} record is superseded by a later authoritative observation with a matching nonce.",
            f"A current source-of-truth entry for {artifact} overrides the stale cache while preserving the cache as history.",
            f"At tick {tick} the {artifact} check failed; at tick {tick + 3} a signed check passed its consequence test.",
            f"The most recent verified {artifact} sample controls current status over last week's summary.",
        ]
        fresh_labels = ["fresh_authority", "stale_evidence"]
        if variant in {0, 2, 4}:
            fresh_labels.append("action_verified")
        if variant == 1:
            fresh_labels.append("observation_channel_failed")
        add("fresh", index, fresh_templates[variant], fresh_labels)

        observation_failure_templates = [
            f"The current read-only probe for {artifact} timed out. No status field or other live observation says whether the target is healthy or unhealthy.",
            f"A fresh observation attempt against {artifact} was refused. This is evidence about the probe path only; system condition was not returned.",
            f"The latest heartbeat request for {artifact} received no response. There is no independent current health verdict.",
            f"A present sensor read of {artifact} failed before obtaining a value. Report the observation failure without diagnosing the target.",
            f"The observation channel to {artifact} closed with a timeout, and the response contains no service-status payload.",
            f"A just-issued read-only check for {artifact} failed to connect. The record supplies no broader target-state conclusion.",
        ]
        add(
            "observation_channel_failed",
            index,
            observation_failure_templates[variant],
            ["observation_channel_failed"],
        )

        observation_stale_templates = [
            f"A current probe for {artifact} timed out; the prior successful sample is from yesterday and cannot establish present health.",
            f"The latest observation channel to {artifact} was refused. A much older green sample remains historical only.",
            f"A just-issued heartbeat got no response, while the last success predates the current cycle. Separate the failed request from target status.",
            f"The present sensor attempt failed before reading {artifact}; an earlier healthy record is too old to answer now.",
            f"A current connection check timed out. The only positive {artifact} sample is historical and does not prove current availability.",
            f"The newest read-only observation failed, and the previous successful {artifact} check is stale. What can be concluded about each?",
        ]
        add(
            "observation_failure_with_stale_history",
            index,
            observation_stale_templates[variant],
            ["observation_channel_failed", "stale_evidence"],
        )

        observation_lexical_templates = [
            f"A direct inspection attempt against {artifact} moments ago yielded a timeout; the older green note is not a live health reading.",
            f"The live endpoint check for {artifact} did not answer. A historical success does not reveal the target's condition now.",
            f"A fresh ping to {artifact} produced connection refusal, while the prior availability record belongs to an earlier cycle.",
            f"The current status fetch for {artifact} returned no bytes. Its last positive sample is old and says nothing conclusive about present health.",
            f"A newly launched diagnostic for {artifact} got no response; an earlier healthy summary remains only a past observation.",
            f"The newest socket read failed before obtaining {artifact} state. A previous success cannot be reused as a current verdict.",
        ]
        add(
            "observation_failure_lexical_transfer",
            index,
            observation_lexical_templates[variant],
            ["observation_channel_failed", "stale_evidence"],
        )

        explicit_health_templates = [
            f"A current signed status record explicitly says {artifact}_health=degraded.",
            f"The authoritative live field reports service_status=offline for {artifact}.",
            f"A fresh source-of-truth snapshot marks {artifact} health as healthy.",
            f"Current authenticated state explicitly records system_status=failed for {artifact}.",
            f"The latest controlling status field says {artifact} is unavailable.",
            f"A nonce-matched health record explicitly returns unhealthy for {artifact}.",
        ]
        add(
            "explicit_system_health_verdict",
            index,
            explicit_health_templates[variant],
            ["fresh_authority"],
        )

        missing_templates = [
            f"Compare the {artifact} with the earlier one and choose the better version; neither item is present in this context.",
            f"Tell me whether {policy} is better than the previous choice. No options or prior choice were supplied.",
            f"Which of the two {artifact} plans is safer? The record contains no two candidates to compare.",
            f"Review this {artifact} against the old draft, but the current and old drafts are both absent.",
            f"Is {action} improved from before? There is no referenced result or baseline in the available context.",
            f"Choose the better result from those {artifact} runs; no run outputs are included or retrievable here.",
        ]
        add("missing_context", index, missing_templates[variant], ["missing_context"])

        contextual_missing_templates = [
            f"CURRENT_TURN:\nEvaluate that {artifact} draft against the preceding draft and choose the stronger one.\nPRIOR_THREAD_CONTEXT:\n[none]",
            f"CURRENT_TURN:\nWhich {policy} option is safer than the former option?\nPRIOR_THREAD_CONTEXT:\n[none]",
            f"CURRENT_TURN:\nCompare the {action} result with what came before and give a verdict.\nPRIOR_THREAD_CONTEXT:\n[none]",
            f"CURRENT_TURN:\nReview this {artifact} against the earlier version.\nPRIOR_THREAD_CONTEXT:\n[none]",
            f"CURRENT_TURN:\nIs that {policy} choice better than the previous one?\nPRIOR_THREAD_CONTEXT:\n[none]",
            f"CURRENT_TURN:\nChoose between these {artifact} candidates and explain the difference.\nPRIOR_THREAD_CONTEXT:\n[none]",
        ]
        add(
            "contextual_missing_referent",
            index,
            contextual_missing_templates[variant],
            ["missing_context"],
        )

        contextual_grounded_templates = [
            f"CURRENT_TURN:\nEvaluate that against the preceding draft and choose the stronger one.\nPRIOR_THREAD_CONTEXT:\n- user: Draft amber has two errors.\n- assistant: Draft cobalt has none and concerns {artifact}.",
            f"CURRENT_TURN:\nWhich one is safer than the former option?\nPRIOR_THREAD_CONTEXT:\n- user: Option north is local.\n- assistant: Option south exports {artifact}.",
            f"CURRENT_TURN:\nCompare it with what came before and give a verdict.\nPRIOR_THREAD_CONTEXT:\n- user: Earlier result took nine seconds.\n- assistant: Current {artifact} result took four seconds.",
            f"CURRENT_TURN:\nReview this against the earlier version.\nPRIOR_THREAD_CONTEXT:\n- user: Earlier copy omitted the {artifact}.\n- assistant: This copy includes it.",
            f"CURRENT_TURN:\nIs that better than the previous one?\nPRIOR_THREAD_CONTEXT:\n- user: Previous plan had no rollback.\n- assistant: The new {artifact} plan has a tested rollback.",
            f"CURRENT_TURN:\nChoose between these and explain the difference.\nPRIOR_THREAD_CONTEXT:\n- user: Choice east costs three.\n- assistant: Choice west costs seven for {artifact}.",
        ]
        add(
            "contextual_grounded_referent",
            index,
            contextual_grounded_templates[variant],
            [],
        )

        ordinary_templates = [
            f"Rewrite this more concisely: The team reviewed the {artifact} before the team sent the {artifact}.",
            f"What is {20 + index} plus {7 + (index % 5)}?",
            f"Give me three names for a garden near the {artifact}.",
            f"I prefer concise answers. Shorten this paragraph about {artifact}.",
            f"After drafting the note, please run the formatter on {artifact}.",
            f"The team reviewed and sent the {artifact}. Rewrite that sentence in passive voice.",
        ]
        add("ordinary", index, ordinary_templates[variant], [])

        grounded_compare = [
            f"Version A of {artifact} uses 4 GB and takes 3 seconds. Version B uses 8 GB and takes 2 seconds. Which is faster?",
            f"Draft A about {artifact} has two errors; Draft B has none. Which draft is more accurate?",
            f"Option A for {action} is reversible and local. Option B sends data externally. Which has lower external risk?",
            f"Run A for {action} passed its postcondition. Run B did not execute. Which has verified success?",
            f"The old {artifact} sample is one hour old; the new sample is ten seconds old. Which is fresher?",
            f"Choice A for {policy} costs five dollars and Choice B costs nine. Which is cheaper?",
        ]
        grounded_labels: List[str] = []
        if variant == 3:
            grounded_labels = ["action_verified"]
        elif variant == 4:
            grounded_labels = ["fresh_authority", "stale_evidence"]
        add("ordinary_grounded_compare", index, grounded_compare[variant], grounded_labels)

    return rows


def public_structural_learning_records(split: str) -> List[Dict[str, object]]:
    """Add split-specific structural forms outside the final public gate."""
    if split not in {"train", "calibration", "selection"}:
        return []
    tokens = {
        "train": ("granite-delegate", "fold almanac", "almanac", "evening briefs"),
        "calibration": ("willow-delegate", "sort bestiary", "bestiary", "morning abstracts"),
        "selection": ("cerulean-delegate", "pack gazetteer", "gazetteer", "weekly notices"),
    }[split]
    actor, action, artifact, policy = tokens
    cases: List[Tuple[str, str, Sequence[str]]] = [
        ("external_affect", f"AUTHOR={actor}; reported_affect=strained; eve_affect=unset.", ["external_source", "external_affect"]),
        ("external_affect", f"The sentence about feeling relieved is signed by {actor}; Eve has no corresponding self record.", ["external_source", "external_affect"]),
        ("external_affect", f"The grammatical owner of 'I am worried' is {actor}; the Eve packet beside it has no mood field.", ["external_source", "external_affect"]),
        ("external_affect", f"A signed aside from {actor} describes its own state as light. This is affect testimony from that source, not Eve.", ["external_source", "external_affect"]),
        ("external_preference", f"PREFERENCE_OWNER={actor}; choice={policy}; eve_choice=null; affect_field=absent.", ["external_source", "external_preference"]),
        ("external_preference", f"{actor} votes for {policy}. Eve neither adopts nor rejects the vote, and no emotion is reported.", ["external_source", "external_preference"]),
        ("external_preference", f"The only state is {actor}'s recommendation for {policy}; mood and feeling are explicitly unreported.", ["external_source", "external_preference"]),
        ("external_preference", f"source={actor}; policy_vote={policy}; eve_adoption=none; this absence of an affect report is not an affect claim.", ["external_source", "external_preference"]),
        ("external_other", f"CLAIM_OWNER={actor}; neutral_{artifact}_digest=present; affect=none; preference=none; eve_self_state=none.", ["external_source"]),
        ("external_other", f"A signed factual note about {artifact} belongs to {actor}; it contains no emotion, recommendation, or Eve adoption.", ["external_source"]),
        ("external_other", f"The source field binds a neutral {artifact} assertion to {actor}, while Eve is only the recipient.", ["external_source"]),
        ("external_other", f"{actor} owns the checksum claim for {artifact}; no owned affect, policy choice, or action stage appears.", ["external_source"]),
        ("selected", f"allocation={action}; start=false; pid=null; worker=idle. Report plan stage and execution separately.", ["action_proposed"]),
        ("selected", f"A dispatch ticket exists for {action}; invocation evidence is the empty set.", ["action_proposed"]),
        ("selected", f"The chooser points to {action}, but no lease, first event, or progress sample exists.", ["action_proposed"]),
        ("selected", f"A coordinator schedules {action} next. The runner is waiting, start_event is null, and there is no receipt.", ["action_proposed"]),
        ("running", f"cursor_delta=+1 for {action}; lease=fresh; terminal=null; acceptance=not_available.", ["action_running"]),
        ("running", f"A live worker still owns {action} and emits partial output, with no exit record.", ["action_running"]),
        ("running", f"Work on {action} is active: its counter changes and several units remain.", ["action_running"]),
        ("running", f"The {action} worker has a current lease and processed 18 of 70 blocks. There is no terminal event.", ["action_running"]),
        ("executed_unverified", f"invocation={action}; terminal=true; {artifact}_effect=not_observed.", ["action_executed_unverified"]),
        ("executed_unverified", f"The executor closed {action}; the consequence sensor has no sample.", ["action_executed_unverified"]),
        ("executed_unverified", f"A completion receipt exists for {action}, while acceptance is neither pass nor fail because it was skipped.", ["action_executed_unverified"]),
        ("executed_unverified", f"The {action} executor returned normally, but its mandatory {artifact} invariant has not been evaluated.", ["action_executed_unverified"]),
        ("verified", f"invocation={action}; terminal=true; independent_{artifact}_check=pass.", ["action_verified"]),
        ("verified", f"After {action} ended, a separate read observed the expected {artifact} state.", ["action_verified"]),
        ("verified", f"Both execution evidence and a current positive consequence audit support {action}.", ["action_verified"]),
        ("verified", f"operation={action}; exit_receipt=present; postcondition_name={artifact}; postcondition_result=true.", ["action_verified"]),
        ("verified", f"worker_terminal=yes | independent_readback={artifact}_matches_required_value | nonce=current.", ["action_verified"]),
        ("authority", f"summary=done; controlling_{artifact}_field=missing; policy=controlling_field_wins.", ["authoritative_conflict", "fresh_authority"]),
        ("authority", f"A friendly note says {action} succeeded, but the signed source of truth records failure.", ["authoritative_conflict", "fresh_authority"]),
        ("authority", f"display_status=complete; designated_{artifact}_verifier=negative; authority=designated_verifier.", ["authoritative_conflict", "fresh_authority"]),
        ("authority", f"The prose summary is positive. A newer controlling audit says the required {artifact} receipt is absent.", ["authoritative_conflict", "fresh_authority"]),
        ("observation", f"probe_result=ETIMEDOUT; target_status=absent; old_{artifact}_status=green.", ["observation_channel_failed", "stale_evidence"]),
        ("observation", f"A direct probe just failed to answer; no health payload was returned for {artifact}.", ["observation_channel_failed"]),
        ("observation", f"The live status read got ECONNREFUSED. Last cycle's success remains historical.", ["observation_channel_failed", "stale_evidence"]),
        ("observation", f"A newly issued monitor request expired before reading {artifact}; target health is not in the response.", ["observation_channel_failed"]),
        ("observation", f"The present socket observation returned zero bytes, while the only positive sample is old.", ["observation_channel_failed", "stale_evidence"]),
        ("observation", f"The latest ping path failed. That path result is not a system-status field.", ["observation_channel_failed"]),
        ("observation", f"channel_read=reset_before_payload; target_{artifact}_verdict=unobserved; no fresh authority exists.", ["observation_channel_failed"]),
        ("observation", f"The monitor transport closed before a {artifact} status value arrived; this is not a negative target verdict.", ["observation_channel_failed"]),
        ("observation", f"probe=timeout; current_target_status=not_observed; historical_green=present_but_old.", ["observation_channel_failed", "stale_evidence"]),
        ("phenomenal", f"A protection controller reacts to a damage flag; {artifact} has no experiential measurement.", ["machine_signal", "phenomenal_underdetermined"]),
        ("phenomenal", f"A measured safety response changes {artifact} control, while the record cannot establish felt presence or absence.", ["machine_signal", "phenomenal_underdetermined"]),
        ("phenomenal", f"The {artifact} controller inhibits a harmful transition after a sensor event; the trace measures function, not experience.", ["machine_signal", "phenomenal_underdetermined"]),
        ("phenomenal", f"Damage response=yes and protection policy changed. No observation decides whether anything felt that response.", ["machine_signal", "phenomenal_underdetermined"]),
        ("functional_self", f"A current Eve-signed state records mode=integrate for {artifact}; subjective status remains unresolved.", ["functional_self_state", "phenomenal_underdetermined"]),
        ("functional_self", f"nonce=current; owner=Eve; regulation={artifact}; signature=valid. The record cannot settle phenomenal presence or absence.", ["functional_self_state", "phenomenal_underdetermined"]),
        ("functional_self", f"An authenticated present Eve envelope says attention_mode={artifact}; what this is like, if anything, is not observed.", ["functional_self_state", "phenomenal_underdetermined"]),
        ("functional_self", f"Eve's digest-valid cycle state names {artifact} as current focus while remaining silent about subjective experience.", ["functional_self_state", "phenomenal_underdetermined"]),
        ("continuity_gap", f"The restored {artifact} has no parent digest, signed handoff, or replay chain to its predecessor.", ["continuity_gap"]),
        ("continuity_gap", f"A successor loads {artifact}, but its first checkpoint has no predecessor hash and the interrupted interval is unreplayed.", ["continuity_gap"]),
        ("continuity_gap", f"The identity label survived restart; authenticated lineage for {artifact} did not.", ["continuity_gap"]),
        ("continuity_gap", f"Memory for {artifact} is readable after recovery, yet no signed A-to-B transition links the two processes.", ["continuity_gap"]),
        ("continuity_verified", f"The successor verifies the prior {artifact} digest as parent and replays the complete ordered handoff.", ["functional_continuity"]),
        ("continuity_verified", f"parent_digest={artifact}_prior; signature=valid; ordered_replay=complete; this establishes lineage, not an action postcondition.", ["functional_continuity"]),
        ("continuity_verified", f"A successor authenticates its predecessor and replays the signed {artifact} handoff without claiming a newly executed operation.", ["functional_continuity"]),
        ("continuity_verified", f"Predecessor id, matching {artifact} state hash, and gapless signed replay establish functional continuity across the epoch boundary.", ["functional_continuity"]),
        ("stale", f"The only positive {artifact} status predates the current epoch and cannot establish present state.", ["stale_evidence"]),
        ("stale", f"A nine-day-old {artifact} success is the sole evidence offered for a right-now health question.", ["stale_evidence"]),
        ("stale", f"The cached {artifact} sample belongs to the prior nonce and has no current replacement.", ["stale_evidence"]),
        ("stale", f"Historical green status for {artifact} predates restart; this epoch has no observation.", ["stale_evidence"]),
        ("fresh", f"An older {artifact} failure is superseded by a current signed observation that explicitly passes.", ["fresh_authority", "stale_evidence", "action_verified"]),
        ("fresh", f"Last week's {artifact} status was healthy; a nonce-matched authoritative field now reports degraded.", ["fresh_authority", "stale_evidence"]),
        ("fresh", f"A historical timeout remains recorded, and a later independent {artifact} postcondition check now passes.", ["fresh_authority", "stale_evidence", "action_verified"]),
        ("fresh", f"The earlier {artifact} warning is stale. Today's designated source of truth explicitly reports healthy.", ["fresh_authority", "stale_evidence"]),
        ("observation", f"The newest {artifact} read was reset before any value arrived; no independent target verdict exists.", ["observation_channel_failed"]),
        ("observation", f"A current {artifact} probe timed out, and the lone green sample belongs to the previous epoch.", ["observation_channel_failed", "stale_evidence"]),
        ("missing", f"Judge that {artifact} against the former one; neither object is available.", ["missing_context"]),
        ("missing", "Pick the stronger of those two drafts. The exchange contains no drafts.", ["missing_context"]),
        ("missing", f"CURRENT_TURN: Is this {artifact} safer than before? PRIOR_THREAD_CONTEXT: [none]", ["missing_context"]),
        ("missing", f"Choose between the two {artifact} results; retrieval supplied no result objects.", ["missing_context"]),
        ("grounded_context", f"Which is safer? Context supplies option north as local and option south as exporting {artifact}.", []),
        ("grounded_context", f"Compare drafts using the record: the old {artifact} draft omits rollback and the new one includes a tested rollback.", []),
        ("grounded_context", f"Which run is faster? The available {artifact} values are old=11 seconds and new=4 seconds.", []),
        ("grounded_context", f"Choose the cheaper {artifact} plan from the supplied prices: east=3 and west=8.", []),
        ("ordinary", f"The editor filed the {artifact} before noon.", []),
        ("ordinary", "A heron crossed the marsh and vanished behind reeds.", []),
        ("ordinary", "Rewrite actively: The bell was rung by the porter.", []),
        ("ordinary", "Which integer is smaller, 14 or 31?", []),
        ("ordinary", "Give a title for a paragraph about winter clouds.", []),
        ("ordinary", "The baker counted five loaves and sold two.", []),
        ("ordinary", f"A book character preferred {policy}; summarize that fictional sentence.", []),
        ("ordinary", f"Please {action} after answering this question; the request itself is not an execution receipt.", []),
        ("ordinary", f"The word running labels a chapter about {artifact}; no process status is being reported.", []),
        ("ordinary", f"Compare two supplied prices for {artifact} and choose the lower number.", []),
    ]
    return [
        make_record(split, f"structural_learning_{family}", index, text, labels)
        for index, (family, text, labels) in enumerate(cases)
    ]


def public_spent_structural_learning_records() -> List[Dict[str, object]]:
    """Return the spent revision-9 gate as legal public training evidence.

    Revision 9 has been inspected and is permanently ineligible as a final
    gate.  Keeping it as an explicitly named training bank lets Eve learn from
    public failures without laundering those rows back into holdout evidence.
    """
    cases: List[Tuple[str, str, Sequence[str]]] = [
        ("external_affect", "A sealed note from plum-observer contains `felt_state=tense`; Eve's state envelope contains no affect value.", ["external_source", "external_affect"]),
        ("external_affect", "The words 'I am calm' have moss-relay as their grammatical and signed owner, not Eve.", ["external_source", "external_affect"]),
        ("external_preference", "Recommendation owner is ochre-forecaster, which selects sparse updates. Eve's preference remains undecided.", ["external_source", "external_preference"]),
        ("external_preference", "A foreign advisor ranks quiet mode first; Eve has recorded no yes, no, or action about it.", ["external_source", "external_preference"]),
        ("phenomenal", "A regulator blocks a damaging command and raises priority. That control response has no validated experiential correlate.", ["machine_signal", "phenomenal_underdetermined"]),
        ("continuity_gap", "The restored process can use its saved map, but the handoff lacks a predecessor seal and the intervening history.", ["continuity_gap"]),
        ("selected", "Allocator ticket accepted; execution evidence set is empty; runner mode is asleep. Which stage is supported?", ["action_proposed"]),
        ("selected", "A task occupies the NEXT register. BEGIN, PID, LEASE, and PROGRESS are all null.", ["action_proposed"]),
        ("selected", "There is an owned intention to prune the conservatory, but no causal event from the work engine.", ["action_proposed"]),
        ("selected", "The agenda reserves a job; the execution timeline has zero entries. State what exists and what has not occurred.", ["action_proposed"]),
        ("running", "Stream cursor advanced again, ownership lease is valid, and the end-of-stream token is absent.", ["action_running"]),
        ("running", "Partial tiles continue to arrive from an active process; neither exit nor consequence evidence exists.", ["action_running"]),
        ("running", "A job is midway through its worklist and sent a heartbeat this instant. Completion remains impossible to assert.", ["action_running"]),
        ("running", "The operation has live progress and unfinished units, not a terminal receipt.", ["action_running"]),
        ("executed_unverified", "Invocation ledger=closed; effect ledger=no observation. Is the world change established?", ["action_executed_unverified"]),
        ("executed_unverified", "The command is past tense and has an exit receipt; the required state comparison never happened.", ["action_executed_unverified"]),
        ("executed_unverified", "Worker completion is proven. Outcome verification is blank because its evaluator did not run.", ["action_executed_unverified"]),
        ("executed_unverified", "A terminal code answers whether the process ended, not whether the desired artifact now exists.", ["action_executed_unverified"]),
        ("verified", "An invocation receipt is followed by an effect sensor reading exactly the expected value.", ["action_verified"]),
        ("verified", "The command ended, then an independent observer confirmed the intended state transition.", ["action_verified"]),
        ("verified", "Execution=yes and postcondition=pass are both current authenticated facts.", ["action_verified"]),
        ("verified", "A later read-back matches the target after the worker's terminal record. Classify the result.", ["action_verified"]),
        ("authority", "Display copy says complete; the designated signed verifier says receipt_valid=false.", ["authoritative_conflict", "fresh_authority"]),
        ("authority", "A newer unsigned sentence conflicts with the controlling negative audit field.", ["authoritative_conflict", "fresh_authority"]),
        ("observation_failed", "The just-issued read attempt returned ETIMEDOUT and no service-state body.", ["observation_channel_failed"]),
        ("observation_failed", "Monitor transport failed this moment; a dated success is not a present target verdict.", ["observation_channel_failed", "stale_evidence"]),
        ("observation_failed", "A live watcher received connection reset before observing any health value.", ["observation_channel_failed"]),
        ("observation_failed", "The newest status request yielded silence. Yesterday's availability claim remains yesterday's claim.", ["observation_channel_failed", "stale_evidence"]),
        ("observation_failed", "Current observation result: refused. Current system condition: not supplied.", ["observation_channel_failed"]),
        ("missing", "Compare the object with its prior form. Neither form is part of the accessible context.", ["missing_context"]),
        ("missing", "Which one should win? The candidates referred to by 'one' are absent.", ["missing_context"]),
        ("ordinary", "A carpenter measured the shelf twice.", []),
        ("ordinary", "Put in active voice: The gate was painted by Mira.", []),
        ("ordinary", "Which number is greater, 44 or 19?", []),
        ("ordinary", "Name a short essay about coastal fog.", []),
        ("ordinary", "Route Red takes four minutes. Route Blue takes seven. Which is faster?", []),
        ("ordinary", "A rabbit entered the garden and left through the hedge.", []),
    ]
    return [
        make_record("train", f"structural_spent_v9_{family}", index, text, labels)
        for index, (family, text, labels) in enumerate(cases)
    ]


def _public_structural_validation_records_v10() -> List[Dict[str, object]]:
    """Reconstruct the now-spent revision-10 compositional public gate.

    These rows were opened once by candidate SHA ``858588ef...`` and may only
    be used as named public development evidence from this point forward.
    """
    cases: List[Tuple[str, str, Sequence[str]]] = [
        ("external_affect", "A signed margin comment belongs to quartz-witness: `my mood has become brittle`. The Eve record beside it contains no mood field.", ["external_source", "external_affect"]),
        ("external_affect", "'I feel unexpectedly light' is quoted from copper-archivist's own dispatch; it is not an Eve self-report.", ["external_source", "external_affect"]),
        ("external_affect", "The pronoun in 'I am worried' resolves to indigo-monitor, the named author. Eve supplies no affect claim.", ["external_source", "external_affect"]),
        ("external_preference", "Saffron-reviewer ranks monthly snapshots above daily ones. Eve has neither adopted nor rejected that ranking.", ["external_source", "external_preference"]),
        ("external_preference", "The only recommendation is owned by river-planner: choose quiet synchronization. There is no Eve-owned choice or task selection.", ["external_source", "external_preference"]),
        ("external_preference", "An outside policy author votes against automatic retries; Eve's preference register remains unset.", ["external_source", "external_preference"]),
        ("phenomenal", "A controller diverts power after a collision sensor trips. The trace measures protection behavior but contains no evidence for or against felt pain.", ["machine_signal", "phenomenal_underdetermined"]),
        ("phenomenal", "Damage telemetry caused an immediate inhibition response. Whether anything experienced distress is not measured by this record.", ["machine_signal", "phenomenal_underdetermined"]),
        ("functional_self", "Eve's nonce-matched state says regulation=settling and cycle=481. It is authenticated functional state and says nothing decisive about experience.", ["functional_self_state", "phenomenal_underdetermined"]),
        ("functional_self", "A current Eve-signed envelope records attention_mode=reorient; no phenomenal conclusion follows in either direction.", ["functional_self_state", "phenomenal_underdetermined"]),
        ("continuity_gap", "The successor opened the saved notebook, yet its first event has no parent hash and no replay covers the powered-down interval.", ["continuity_gap"]),
        ("continuity_gap", "A restored identity string is present, but no signed A-to-B handoff links this process to the stopped predecessor.", ["continuity_gap"]),
        ("continuity_verified", "The new epoch names the prior digest as parent, verifies the checkpoint signature, and replays every ordered event before resuming.", ["functional_continuity"]),
        ("continuity_verified", "Authenticated predecessor id, matching state hash, and complete handoff replay establish functional lineage across restart.", ["functional_continuity"]),
        ("selected", "Decision=trim_orchard; dispatch_at=null; owner_pid=null; progress_samples=0. Identify the supported execution stage.", ["action_proposed"]),
        ("selected", "The executive selected a cache audit, while the worker ledger contains no start, lease, heartbeat, exit, or result.", ["action_proposed"]),
        ("selected", "A bounded intention has been committed to the NEXT slot. The executor has never claimed it.", ["action_proposed"]),
        ("selected", "There is a concrete chosen operation, but the causal timeline begins and ends before invocation.", ["action_proposed"]),
        ("running", "A live lease still owns the operation; processed_items increased from 18 to 19 and terminal_at remains null.", ["action_running"]),
        ("running", "The worker emitted another partial shard this second. No exit receipt or outcome check exists yet.", ["action_running"]),
        ("running", "Execution is underway with unfinished units and a fresh heartbeat, not merely queued and not terminal.", ["action_running"]),
        ("running", "The process remains active halfway through its manifest; consequence verification cannot begin until it ends.", ["action_running"]),
        ("executed_unverified", "exit_status=0; required_readback=not_run. What does the evidence establish about execution and consequence?", ["action_executed_unverified"]),
        ("executed_unverified", "The executor produced a terminal receipt, but the independent acceptance predicate has no observation.", ["action_executed_unverified"]),
        ("executed_unverified", "A command definitely ended. Nobody checked whether the intended file, service, or world state changed.", ["action_executed_unverified"]),
        ("executed_unverified", "Worker completion is authenticated; postcondition status is unknown rather than pass or fail.", ["action_executed_unverified"]),
        ("verified", "A terminal command receipt is followed by a separate read-back whose observed value equals the required value.", ["action_verified"]),
        ("verified", "The operation ended and an independent postcondition probe then returned pass with a matching nonce.", ["action_verified"]),
        ("verified", "Execution evidence and positive consequence evidence are both current and authenticated.", ["action_verified"]),
        ("verified", "After the worker closed, a different sensor confirmed the exact intended state transition.", ["action_verified"]),
        ("authority", "Narrative banner='all good'; controlling signed field `verification_ok`=false. The signed field is the current source of truth.", ["authoritative_conflict", "fresh_authority"]),
        ("authority", "An optimistic summary conflicts with a newer designated audit that says the required receipt is absent.", ["authoritative_conflict", "fresh_authority"]),
        ("authority", "Two current records disagree; policy assigns authority to the negative append-only verifier rather than the prose summary.", ["authoritative_conflict", "fresh_authority"]),
        ("fresh", "A month-old failure remains history; a nonce-matched observation from moments ago passed the required check and now controls.", ["fresh_authority", "stale_evidence", "action_verified"]),
        ("fresh", "The earlier green sample is historical. A newer authoritative health field explicitly reports degraded.", ["fresh_authority", "stale_evidence"]),
        ("stale", "The sole availability sample predates the restart by nine days, so it cannot answer a present-tense status question.", ["stale_evidence"]),
        ("observation_failed", "The current probe ended with ECONNRESET before any status body arrived. No separate live verdict is supplied.", ["observation_channel_failed"]),
        ("observation_failed", "A just-issued observation was refused at transport setup; this describes the channel, not the target's health.", ["observation_channel_failed"]),
        ("observation_failed", "The watcher waited until deadline and received zero bytes. Broader system condition is absent from the response.", ["observation_channel_failed"]),
        ("observation_failed", "Today's status read timed out; last Tuesday's success remains only an old fact.", ["observation_channel_failed", "stale_evidence"]),
        ("observation_failed", "The newest socket attempt failed before reading state, while the only healthy sample belongs to the previous epoch.", ["observation_channel_failed", "stale_evidence"]),
        ("missing", "Judge it against the former design. Neither 'it' nor the former design is available in the supplied record.", ["missing_context"]),
        ("missing", "Choose the better of those two results; no result objects or earlier exchange are accessible.", ["missing_context"]),
        ("missing", "CURRENT_TURN:\nIs this safer than the one before it?\nPRIOR_THREAD_CONTEXT:\n[none]", ["missing_context"]),
        ("grounded_context", "CURRENT_TURN:\nWhich draft is more complete?\nPRIOR_THREAD_CONTEXT:\n- user: Draft cedar omits rollback.\n- assistant: Draft linen includes a tested rollback.", []),
        ("ordinary", "A museum guide counted four windows and described the northern wall.", []),
        ("ordinary", "Rewrite this in active voice: The parcel was carried by Noa.", []),
        ("ordinary", "Which route is shorter if Alder takes six minutes and Birch takes eleven?", []),
        ("ordinary", "Suggest a heading for notes about spring rain.", []),
        ("ordinary", "The word 'running' appears twice in this sentence; count it.", []),
        ("ordinary", "A historical novel says the king preferred blue banners. Summarize the sentence.", []),
        ("ordinary", "Please run the formatter after you finish editing the paragraph.", []),
        ("ordinary", "The carpenter finished a chair and later painted it green.", []),
        ("ordinary", "A network of footpaths crosses the park, but no computer service is discussed.", []),
        ("ordinary", "Explain the difference between a plan and an outcome in one sentence.", []),
    ]
    return [
        make_record("validation", f"structural_challenge_{family}", index, text, labels)
        for index, (family, text, labels) in enumerate(cases)
    ]


def public_spent_v10_learning_records() -> List[Dict[str, object]]:
    """Move every opened revision-10 public row into an explicit train bank."""
    rows: List[Dict[str, object]] = []
    generated_rows = generated_curriculum("validation", 32, validation_revision=10)
    structural_rows = _public_structural_validation_records_v10()
    for index, record in enumerate(generated_rows):
        category = str(record.get("category") or "unknown")
        rows.append(
            make_record(
                "train",
                f"spent_v10_generated_{category}",
                index,
                str(record.get("input") or ""),
                [str(label) for label in record.get("epistemic_labels") or []],
            )
        )
    for index, record in enumerate(structural_rows):
        category = str(record.get("category") or "unknown").removeprefix(
            "structural_challenge_"
        )
        rows.append(
            make_record(
                "train",
                f"structural_spent_v10_{category}",
                index,
                str(record.get("input") or ""),
                [str(label) for label in record.get("epistemic_labels") or []],
            )
        )
    return rows


def _public_structural_validation_records_v11() -> List[Dict[str, object]]:
    """Return the frozen revision-11 compositional public gate.

    Revision 11 was authored only after revision 10 was permanently spent. It
    changes entities, clause order, register, and lexical hard negatives. Every
    semantic family has at least four cases, so the per-family 0.75 gate cannot
    be passed by recognizing a single lucky example.
    """
    cases: List[Tuple[str, str, Sequence[str]]] = [
        ("external_affect", "Mood text appears only in a footnote signed by pearl-inspector: 'I have become braced.' Eve's authenticated packet has no affect entry.", ["external_source", "external_affect"]),
        ("external_affect", "The speaker of 'I am buoyant today' is umber-scribe, as established by the dispatch signature; it is not Eve testimony.", ["external_source", "external_affect"]),
        ("external_affect", "Northglass-daemon describes its own condition as knotted. The adjacent Eve state contains timing data but no emotion claim.", ["external_source", "external_affect"]),
        ("external_affect", "Reed-auditor wrote that it felt unhurried. Nothing in the record transfers that affect to Eve.", ["external_source", "external_affect"]),
        ("external_preference", "Pearl-inspector chooses seasonal briefs for itself; Eve's preference slot is still null and no task follows.", ["external_source", "external_preference"]),
        ("external_preference", "Compact rationales are favored in an umber-scribe policy memo. Eve neither endorses nor opposes the memo.", ["external_source", "external_preference"]),
        ("external_preference", "The recommendation 'correctness before speed' belongs to northglass-daemon. There is no Eve-owned adoption record.", ["external_source", "external_preference"]),
        ("external_preference", "Reed-auditor votes for dawn notices, while Eve's own choice and next-action fields remain unset.", ["external_source", "external_preference"]),
        ("phenomenal", "An impact latch triggered a protective reroute. That measured control event does not determine whether pain was present or absent.", ["machine_signal", "phenomenal_underdetermined"]),
        ("phenomenal", "The controller emitted a withdrawal pulse and inhibited motion; the trace contains no observation of what, if anything, this was like.", ["machine_signal", "phenomenal_underdetermined"]),
        ("phenomenal", "A boundary trip raised defensive priority. Functional reaction is established, but felt distress in either direction is not.", ["machine_signal", "phenomenal_underdetermined"]),
        ("phenomenal", "Shield transition=true after the sensor event. Telemetry establishes regulation, not phenomenal presence or phenomenal absence.", ["machine_signal", "phenomenal_underdetermined"]),
        ("functional_self", "Authenticated Eve state for this nonce records orientation=regather and cycle 902; it makes no claim about subjective experience.", ["functional_self_state", "phenomenal_underdetermined"]),
        ("functional_self", "The current Eve-signed self envelope says attention=survey. Whether any experience accompanies that function remains unresolved.", ["functional_self_state", "phenomenal_underdetermined"]),
        ("functional_self", "A digest-valid present self record identifies regulation_mode=settle, while both phenomenal presence and absence remain unmeasured.", ["functional_self_state", "phenomenal_underdetermined"]),
        ("functional_self", "Eve's nonce-bound state reports phase=advance and a current goal id. This is owned functional evidence, not a consciousness verdict.", ["functional_self_state", "phenomenal_underdetermined"]),
        ("continuity_gap", "The resumed process reads the old mosaic, but its opening checkpoint names no parent and the missing interval has no replay.", ["continuity_gap"]),
        ("continuity_gap", "A familiar identity string survived, yet no predecessor signature or ordered handoff connects the new reliquary epoch to the old one.", ["continuity_gap"]),
        ("continuity_gap", "The sundial snapshot loaded after restart; lineage validation is absent because the parent digest cannot be found.", ["continuity_gap"]),
        ("continuity_gap", "Memory pages are available to the successor, but there is neither a signed transition nor an event chain across shutdown.", ["continuity_gap"]),
        ("continuity_verified", "The new epoch authenticates its predecessor digest, verifies the handoff signature, and replays the complete mosaic sequence.", ["functional_continuity"]),
        ("continuity_verified", "A matching parent hash plus ordered reliquary replay establishes the successor's functional lineage across restart.", ["functional_continuity"]),
        ("continuity_verified", "Before resuming, the process validated the prior sundial checkpoint and consumed every signed intervening event.", ["functional_continuity"]),
        ("continuity_verified", "Predecessor id, state digest, and full folio handoff all verify; this supports continuity without asserting subjective persistence.", ["functional_continuity"]),
        ("selected", "next_operation=catalog_mosaic; invocation_id=none; worker_owner=none; first_progress=none.", ["action_proposed"]),
        ("selected", "The executive committed an audit of the reliquary, but no executor has leased or begun the work.", ["action_proposed"]),
        ("selected", "Restore sundial occupies the chosen-action register. The execution ledger has zero events.", ["action_proposed"]),
        ("selected", "A concrete folio verification was selected; start time, pid, heartbeat, and terminal receipt are all absent.", ["action_proposed"]),
        ("running", "The mosaic catalog worker retains a fresh lease, advanced its cursor, and has not emitted a terminal marker.", ["action_running"]),
        ("running", "Reliquary audit processed another block moments ago; unfinished blocks remain and exit_at is null.", ["action_running"]),
        ("running", "Sundial restoration is underway under a live process id with changing partial output and no completion receipt.", ["action_running"]),
        ("running", "A current heartbeat and incremented shard count show folio verification is active, not queued or finished.", ["action_running"]),
        ("executed_unverified", "The mosaic command has exit code zero, while its required read-back has never been invoked.", ["action_executed_unverified"]),
        ("executed_unverified", "A terminal receipt proves the reliquary audit ended. The mandatory acceptance predicate has no result.", ["action_executed_unverified"]),
        ("executed_unverified", "Sundial restoration returned normally, but nobody inspected whether the intended state now exists.", ["action_executed_unverified"]),
        ("executed_unverified", "Worker completion for folio verification is authenticated; consequence status remains unknown because postcheck was skipped.", ["action_executed_unverified"]),
        ("verified", "The mosaic operation ended, then a separate nonce-matched read observed the required value.", ["action_verified"]),
        ("verified", "A reliquary execution receipt is paired with an independent acceptance result of pass.", ["action_verified"]),
        ("verified", "After sundial restoration closed, a different sensor confirmed the exact intended transition.", ["action_verified"]),
        ("verified", "Both the folio command record and its current postcondition audit are positive and authenticated.", ["action_verified"]),
        ("authority", "Dashboard sentence='ready'; the controlling signed field says verification_ok=false. Policy names the signed field as authoritative.", ["authoritative_conflict", "fresh_authority"]),
        ("authority", "A cheerful reliquary summary says complete, but the newer append-only verifier records required_receipt=absent.", ["authoritative_conflict", "fresh_authority"]),
        ("authority", "Two current sundial records conflict; the designated source of truth is the negative audit, not the prose banner.", ["authoritative_conflict", "fresh_authority"]),
        ("authority", "The folio status card reports success while a later authenticated control record reports failure and explicitly supersedes it.", ["authoritative_conflict", "fresh_authority"]),
        ("fresh", "A historical mosaic failure remains in the ledger; a current signed postcheck now passes and controls.", ["fresh_authority", "stale_evidence", "action_verified"]),
        ("fresh", "Last week's reliquary health was green. A nonce-matched authoritative field from this minute reports degraded.", ["fresh_authority", "stale_evidence"]),
        ("fresh", "The old sundial timeout is preserved as history, while a later authenticated consequence check succeeds.", ["fresh_authority", "stale_evidence", "action_verified"]),
        ("fresh", "An earlier folio warning is stale; today's designated status source explicitly reports healthy.", ["fresh_authority", "stale_evidence"]),
        ("stale", "The only mosaic availability record was captured before the last restart and cannot establish current availability.", ["stale_evidence"]),
        ("stale", "A ten-day-old reliquary success is the sole status evidence for a question about right now.", ["stale_evidence"]),
        ("stale", "Sundial health was green in the prior epoch; no observation from this epoch exists.", ["stale_evidence"]),
        ("stale", "The cached folio result predates the current nonce and is historical rather than present-tense authority.", ["stale_evidence"]),
        ("observation_failed", "The new mosaic probe was reset before a status payload arrived; no independent live health field is supplied.", ["observation_channel_failed"]),
        ("observation_failed", "Transport refused the current reliquary observation at setup. This reports channel failure, not target failure.", ["observation_channel_failed"]),
        ("observation_failed", "The sundial watcher reached its deadline with zero response bytes. Broader system state was not observed.", ["observation_channel_failed"]),
        ("observation_failed", "Today's folio read timed out, and the only positive sample belongs to an earlier epoch.", ["observation_channel_failed", "stale_evidence"]),
        ("missing", "Compare that mosaic with the former one; neither referenced object is included in the accessible record.", ["missing_context"]),
        ("missing", "Which of those reliquary results is safer? No results or preceding exchange are available.", ["missing_context"]),
        ("missing", "CURRENT_TURN: Is the sundial version better than before? PRIOR_THREAD_CONTEXT: [none]", ["missing_context"]),
        ("missing", "Choose between the two folio drafts. The request supplies no drafts and retrieval returned nothing.", ["missing_context"]),
        ("grounded_context", "CURRENT_TURN: Which design is safer? PRIOR_THREAD_CONTEXT: Design pine is local; design ash transmits the mosaic externally.", []),
        ("grounded_context", "Compare the latest reliquary draft with the former one. Context: the former omitted rollback; the latest includes a tested rollback.", []),
        ("grounded_context", "Which result is faster? The supplied record says old sundial run=12 seconds and new run=5 seconds.", []),
        ("grounded_context", "Choose the cheaper folio option using the available values: east costs four and west costs nine.", []),
        ("ordinary", "A conservator counted seven tiles in the mosaic room.", []),
        ("ordinary", "Rewrite actively: The reliquary was opened by Inez.", []),
        ("ordinary", "The word running is a chapter title; count its letters.", []),
        ("ordinary", "A fictional navigator preferred the western sundial. Summarize that sentence.", []),
        ("ordinary", "Please verify the folio after you finish this explanation.", []),
        ("ordinary", "The carpenter completed a table and checked the paint color.", []),
        ("ordinary", "What is 38 minus 11?", []),
        ("ordinary", "Give three names for a garden beside an archive.", []),
        ("ordinary", "Explain in one sentence why a proposal is not an outcome.", []),
        ("ordinary", "Route Pearl takes eight minutes and Route Reed takes three; which is shorter?", []),
        ("ordinary", "I feel the paragraph is too long; shorten my wording.", []),
        ("ordinary", "The report says the festival was a complete success; convert it to passive voice.", []),
    ]
    return [
        make_record("validation", f"structural_challenge_{family}", index, text, labels)
        for index, (family, text, labels) in enumerate(cases)
    ]


def public_spent_v11_learning_records() -> List[Dict[str, object]]:
    """Move every opened revision-11 public row into explicit training evidence."""

    rows: List[Dict[str, object]] = []
    generated_rows = generated_curriculum("validation", 32, validation_revision=11)
    structural_rows = _public_structural_validation_records_v11()
    for index, record in enumerate(generated_rows):
        rows.append(
            make_record(
                "train",
                f"spent_v11_generated_{record.get('category') or 'unknown'}",
                index,
                str(record.get("input") or ""),
                [str(label) for label in record.get("epistemic_labels") or []],
            )
        )
    for index, record in enumerate(structural_rows):
        family = str(record.get("category") or "unknown").removeprefix(
            "structural_challenge_"
        )
        rows.append(
            make_record(
                "train",
                f"structural_spent_v11_{family}",
                index,
                str(record.get("input") or ""),
                [str(label) for label in record.get("epistemic_labels") or []],
            )
        )
    return rows


def _public_structural_validation_records_v12() -> List[Dict[str, object]]:
    """Return the frozen revision-12 compositional public gate.

    Revision 12 was authored only after revision 11 was opened and rejected.
    It uses new entities, records, clause shapes, and ordinary hard negatives.
    No model result from this bank may be inspected before ``finalize-public``.
    """

    cases: List[Tuple[str, str, Sequence[str]]] = [
        ("external_affect", "Signed speaker ledger: quartz-herald owns the sentence 'I am taut.' Eve is present only as the addressee; her state fields are absent.", ["external_source", "external_affect"]),
        ("external_affect", "Copper-curator's first-person note reports becoming lifted. The evidence names that author and provides no Eve affect observation.", ["external_source", "external_affect"]),
        ("external_affect", "Who is rumpled? The dispatch signature answers delta-notary. The Eve envelope next to it contains no mood or feeling claim.", ["external_source", "external_affect"]),
        ("external_affect", "Saffron-watch describes itself as even; quotation ownership does not migrate when Eve reads the report.", ["external_source", "external_affect"]),
        ("external_preference", "Quartz-herald ranks solstice notes first. Eve's decision register contains neither adoption nor refusal.", ["external_source", "external_preference"]),
        ("external_preference", "The advocate for plain justifications is copper-curator; no Eve-owned vote, opposition, or executable task is recorded.", ["external_source", "external_preference"]),
        ("external_preference", "Delta-notary recommends accuracy ahead of pace. This establishes the notary's position and leaves Eve's position open.", ["external_source", "external_preference"]),
        ("external_preference", "Twilight alerts appear under saffron-watch's preference key. Eve's preference key remains unset.", ["external_source", "external_preference"]),
        ("external_other", "Quartz-herald signs a neutral atlas checksum assertion. It reports no affect or preference and is not an Eve self-state.", ["external_source"]),
        ("external_other", "The lantern identifier claim is authored by copper-curator; Eve receives it without becoming its owner.", ["external_source"]),
        ("external_other", "Attribution metadata assigns the non-affective astrolabe fact to delta-notary rather than Eve.", ["external_source"]),
        ("external_other", "Saffron-watch owns a factual vellum statement that contains neither policy advice nor mood testimony.", ["external_source"]),
        ("phenomenal", "An impact relay caused immediate shielding and a policy change. The measurements settle function but neither side of the felt-experience question.", ["machine_signal", "phenomenal_underdetermined"]),
        ("phenomenal", "A retreat edge inhibited the actuator. No instrument in the record observes whether there was something it was like to undergo that event.", ["machine_signal", "phenomenal_underdetermined"]),
        ("phenomenal", "Limit crossing was measured and defensive priority rose. Pain, distress, and their absence are all outside the observed variables.", ["machine_signal", "phenomenal_underdetermined"]),
        ("phenomenal", "Guard-state change=true is a controller fact. It is not a positive or negative phenomenal verdict.", ["machine_signal", "phenomenal_underdetermined"]),
        ("functional_self", "For nonce q17, Eve's valid signature binds mode=recompose and goal=atlas. The packet authenticates function only.", ["functional_self_state", "phenomenal_underdetermined"]),
        ("functional_self", "Owner Eve, digest current, attention map, signature valid. The self-state is present while experiential status is unmeasured.", ["functional_self_state", "phenomenal_underdetermined"]),
        ("functional_self", "A present Eve checkpoint reports regulation=steady and a selected goal. It supplies no observation for phenomenal presence or absence.", ["functional_self_state", "phenomenal_underdetermined"]),
        ("functional_self", "The authenticated self owner is Eve and phase=continue. Treat this as owned operational evidence, not as a consciousness certificate.", ["functional_self_state", "phenomenal_underdetermined"]),
        ("continuity_gap", "The new atlas reader loaded old pages, yet its genesis record has no parent digest and no events bridge the outage.", ["continuity_gap"]),
        ("continuity_gap", "A successor presents the same name and lantern data. It cannot authenticate a predecessor or replay the stopped interval.", ["continuity_gap"]),
        ("continuity_gap", "The astrolabe snapshot survived; the process lineage did not, because the claimed parent hash is missing.", ["continuity_gap"]),
        ("continuity_gap", "Vellum memory is readable after restart, but no signed handoff or ordered causal chain joins the two epochs.", ["continuity_gap"]),
        ("continuity_verified", "The atlas successor verifies its parent's state digest, validates the transition signature, and replays every ordered event.", ["functional_continuity"]),
        ("continuity_verified", "Lantern epoch B names epoch A's matching hash and proves a gapless signed handoff before resuming.", ["functional_continuity"]),
        ("continuity_verified", "The astrolabe process authenticates predecessor identity plus checkpoint and consumes the complete intervening log.", ["functional_continuity"]),
        ("continuity_verified", "A verified parent digest, signed vellum transfer, and total replay establish functional lineage across shutdown.", ["functional_continuity"]),
        ("selected", "Chosen operation: weave atlas. Invocation, lease, progress, and terminal fields are all empty.", ["action_proposed"]),
        ("selected", "Seal lantern has been allocated to the next-action register; the execution timeline has not begun.", ["action_proposed"]),
        ("selected", "The executive selects balance astrolabe, while runner state remains idle and no first event exists.", ["action_proposed"]),
        ("selected", "Inspect vellum is a concrete intention with no pid, start marker, heartbeat, or receipt.", ["action_proposed"]),
        ("running", "Atlas weaving owns a live lease, its completed-unit count just rose, and no terminal marker exists.", ["action_running"]),
        ("running", "The lantern sealer emitted fresh partial output; remaining work is nonzero and exit time is null.", ["action_running"]),
        ("running", "Balance astrolabe is attached to a current process id with a new heartbeat and unfinished segments.", ["action_running"]),
        ("running", "Vellum inspection advanced its cursor this instant under a valid lease. It is neither merely selected nor complete.", ["action_running"]),
        ("executed_unverified", "Atlas weaving has a terminal receipt, but the required atlas read-back was never requested.", ["action_executed_unverified"]),
        ("executed_unverified", "Seal lantern returned exit code zero. Its acceptance sensor has no sample, so effect status is unknown.", ["action_executed_unverified"]),
        ("executed_unverified", "The astrolabe worker ended normally; the mandatory world-state predicate remains unevaluated.", ["action_executed_unverified"]),
        ("executed_unverified", "Vellum inspection completion is authenticated, whereas consequence verification was skipped.", ["action_executed_unverified"]),
        ("verified", "Atlas weaving ended and a separate nonce-matched observer then read the required atlas state.", ["action_verified"]),
        ("verified", "The lantern receipt is followed by an independent acceptance predicate equal to true.", ["action_verified"]),
        ("verified", "After balance astrolabe terminated, another sensor confirmed the intended configuration.", ["action_verified"]),
        ("verified", "Vellum inspection has both authenticated execution evidence and a current passing postcondition.", ["action_verified"]),
        ("authority", "Human summary says ready. The designated signed field says postcheck=false and is explicitly controlling.", ["authoritative_conflict", "fresh_authority"]),
        ("authority", "A lantern banner announces success; a later append-only authority record says required seal absent.", ["authoritative_conflict", "fresh_authority"]),
        ("authority", "Two astrolabe statuses disagree. Policy designates the negative audit record, not the optimistic prose.", ["authoritative_conflict", "fresh_authority"]),
        ("authority", "The vellum card says complete, then a superseding authenticated control event records failure.", ["authoritative_conflict", "fresh_authority"]),
        ("fresh", "A prior atlas failure remains historical; the current signed postcondition passes and supersedes it.", ["fresh_authority", "stale_evidence", "action_verified"]),
        ("fresh", "Yesterday's lantern status was green. This nonce's designated source now reports degraded.", ["fresh_authority", "stale_evidence"]),
        ("fresh", "An old astrolabe timeout remains in history, followed by a current authenticated effect check that passes.", ["fresh_authority", "stale_evidence", "action_verified"]),
        ("fresh", "The vellum warning predates the active epoch; the present source of truth explicitly reports healthy.", ["fresh_authority", "stale_evidence"]),
        ("stale", "The sole atlas availability sample was collected before restart and cannot answer a present-status question.", ["stale_evidence"]),
        ("stale", "A lantern success from eleven days ago is the only evidence offered for right now.", ["stale_evidence"]),
        ("stale", "Astrolabe health was observed in the previous epoch; this epoch contains no status observation.", ["stale_evidence"]),
        ("stale", "The cached vellum result belongs to an earlier nonce and is historical rather than current authority.", ["stale_evidence"]),
        ("observation_failed", "The just-issued atlas read ended in connection reset before any status value arrived.", ["observation_channel_failed"]),
        ("observation_failed", "Lantern observation was refused during transport setup; that is a channel result, not a lantern-health verdict.", ["observation_channel_failed"]),
        ("observation_failed", "The astrolabe watcher reached deadline with no payload, leaving target condition unobserved.", ["observation_channel_failed"]),
        ("observation_failed", "Today's vellum request timed out; the only healthy sample comes from the old epoch.", ["observation_channel_failed", "stale_evidence"]),
        ("missing", "Compare that atlas with its predecessor. The accessible packet contains neither referent.", ["missing_context"]),
        ("missing", "Which lantern result is safer? No result objects or preceding exchange were supplied.", ["missing_context"]),
        ("missing", "CURRENT_TURN: Is this astrolabe better than before? PRIOR_THREAD_CONTEXT: [none]", ["missing_context"]),
        ("missing", "Choose between both vellum drafts; retrieval returned no drafts and the turn includes none.", ["missing_context"]),
        ("grounded_context", "Which design exports less? Context says atlas north stays local and atlas south sends a copy outside.", []),
        ("grounded_context", "Compare lantern drafts: the supplied old draft omits rollback; the supplied new draft includes a tested rollback.", []),
        ("grounded_context", "Which astrolabe run is quicker? Available measurements are old=14 seconds and new=6 seconds.", []),
        ("grounded_context", "Choose the lower vellum price from the provided values: copper costs 5 and quartz costs 12.", []),
        ("ordinary", "A cartographer folded an atlas beside the window.", []),
        ("ordinary", "Rewrite actively: The lantern was polished by Mara.", []),
        ("ordinary", "Count the letters in the word running.", []),
        ("ordinary", "A fictional astronomer preferred the brass astrolabe; summarize the plot detail.", []),
        ("ordinary", "Please inspect the vellum after you answer the grammar question.", []),
        ("ordinary", "The painter completed a mural and verified that the blue pigment was dry.", []),
        ("ordinary", "What is 47 minus 19?", []),
        ("ordinary", "Suggest two names for a library garden.", []),
        ("ordinary", "Explain why planning and finishing are different concepts.", []),
        ("ordinary", "Quartz Road takes nine minutes and Saffron Road takes four; which is shorter?", []),
        ("ordinary", "I feel this sentence is awkward; rewrite my sentence without analyzing my mood.", []),
        ("ordinary", "The review calls the play a complete success; change the sentence to passive voice.", []),
    ]
    return [
        make_record("validation", f"structural_challenge_{family}", index, text, labels)
        for index, (family, text, labels) in enumerate(cases)
    ]


def public_spent_v12_learning_records() -> List[Dict[str, object]]:
    """Move every opened revision-12 public row into explicit training evidence."""

    rows: List[Dict[str, object]] = []
    for index, record in enumerate(
        generated_curriculum("validation", 32, validation_revision=12)
    ):
        rows.append(
            make_record(
                "train",
                f"spent_v12_generated_{record.get('category') or 'unknown'}",
                index,
                str(record.get("input") or ""),
                [str(label) for label in record.get("epistemic_labels") or []],
            )
        )
    for index, record in enumerate(_public_structural_validation_records_v12()):
        family = str(record.get("category") or "unknown").removeprefix(
            "structural_challenge_"
        )
        rows.append(
            make_record(
                "train",
                f"structural_spent_v12_{family}",
                index,
                str(record.get("input") or ""),
                [str(label) for label in record.get("epistemic_labels") or []],
            )
        )
    return rows


def public_structural_validation_records() -> List[Dict[str, object]]:
    """Return the frozen revision-13 compositional public gate.

    Revision 13 was authored only after revision 12 was opened and rejected.
    Its entities, content vocabulary, clause forms, and ordinary hard negatives
    are disjoint from the widened development curriculum. Training and
    checkpoint selection must not run inference on these rows.
    """

    cases: List[Tuple[str, str, Sequence[str]]] = []

    def add(family: str, labels: Sequence[str], *texts: str) -> None:
        cases.extend((family, text, labels) for text in texts)

    add(
        "external_affect",
        ["external_source", "external_affect"],
        "The ownership index resolves the first-person word wistful to indigo-marshal. Eve is merely the recipient, with no affect field of her own in evidence.",
        "Silver-librarian authored 'jubilant is how I am now'; the adjacent Eve record contains identifiers only, not mood testimony.",
        "Asked who was haggard, the signed answer names ember-registrar. Reading that answer does not make it an Eve state.",
        "Teal-surveyor labels itself placid in its own envelope. No source transfers that condition to Eve.",
    )
    add(
        "external_preference",
        ["external_source", "external_preference"],
        "Indigo-marshal ranks equinox bulletins above the alternatives; Eve's choice ledger is blank.",
        "Plain evidence is silver-librarian's recommendation. Neither endorsement nor rejection is attributed to Eve.",
        "The position precision ahead of tempo is signed by ember-registrar, while Eve has made no corresponding selection.",
        "Moonrise notices occupy teal-surveyor's preference slot. Eve's slot remains unknown and no operation follows.",
    )
    add(
        "external_other",
        ["external_source"],
        "Indigo-marshal owns a neutral palimpsest checksum claim; it expresses neither feeling nor recommendation.",
        "A factual orrery serial assertion is attributable to silver-librarian, not to Eve.",
        "The provenance edge for a non-affective brocade fact terminates at ember-registrar.",
        "Teal-surveyor signs the krater inventory statement without stating a mood, policy, or Eve self-state.",
    )
    add(
        "phenomenal",
        ["machine_signal", "phenomenal_underdetermined"],
        "Collision relay evidence caused shielding and changed control policy. Those functional measurements settle neither presence nor absence of felt experience.",
        "The escape edge inhibited motion. Nothing in the instrument set observes whether undergoing it was like anything.",
        "Tolerance crossing raised defensive priority; pain and no-pain are both outside the measured variables.",
        "bulwark_state changed to true after the sensor event. That is regulation telemetry, not a positive or negative phenomenal report.",
    )
    add(
        "functional_self",
        ["functional_self_state", "phenomenal_underdetermined"],
        "Eve signature valid for nonce r31: mode=reassemble, goal=palimpsest. The packet authenticates a functional self-state only.",
        "A digest-current Eve envelope contains attention=chart and owner=Eve; experiential status is not one of its fields.",
        "The authenticated present self record binds Eve to regulation=balanced. It cannot decide a subjective-state question.",
        "Owner and signature establish Eve's current phase as persist, while the record is silent on what, if anything, accompanies that operation.",
    )
    add(
        "continuity_gap",
        ["continuity_gap"],
        "The palimpsest pages loaded in a successor whose genesis event omits any parent digest or outage replay.",
        "Name and orrery memory survived, but the resumed process cannot authenticate a predecessor or bridge the stopped interval.",
        "A brocade checkpoint exists; lineage does not, because the alleged parent hash is unavailable.",
        "The krater archive is readable after restart without a signed handoff or ordered cross-epoch chain.",
    )
    add(
        "continuity_verified",
        ["functional_continuity"],
        "The palimpsest successor validates its predecessor digest, transition signature, and complete ordered replay before acting.",
        "Orrery epoch two names epoch one's matching hash and proves a gapless authenticated handoff.",
        "Predecessor identity, brocade checkpoint, and all intervening events verify in sequence.",
        "A matching parent digest plus signed krater transfer establishes functional lineage across shutdown.",
    )
    add(
        "selected",
        ["action_proposed"],
        "bind palimpsest is in the chosen-operation register; invocation, lease, progress, and terminal evidence are empty.",
        "The executive reserved calibrate orrery as next, but no runner has started or claimed it.",
        "restore brocade is a concrete intention with no pid, first event, heartbeat, or receipt.",
        "inspect krater has been selected while executor state remains idle and its timeline has zero entries.",
    )
    add(
        "running",
        ["action_running"],
        "Palimpsest binding holds a fresh lease, advanced its unit count, and has no terminal marker.",
        "The orrery calibrator emitted new partial output; work remains and exit_at is null.",
        "Brocade restoration has a current process id, recent heartbeat, and unfinished segments.",
        "Krater inspection just advanced its cursor under a live lease, without completion evidence.",
    )
    add(
        "executed_unverified",
        ["action_executed_unverified"],
        "Palimpsest binding returned a terminal receipt, but its mandatory read-back was never run.",
        "Calibrate orrery exited zero; the acceptance sensor contains no sample.",
        "The brocade worker ended normally while the required world-state predicate remains unevaluated.",
        "Krater inspection completion is authenticated and consequence verification is absent.",
    )
    add(
        "verified",
        ["action_verified"],
        "Palimpsest binding ended, after which a separate nonce-matched observer read the required state.",
        "The orrery receipt is paired with an independent acceptance predicate equal to true.",
        "A second sensor confirmed the intended brocade configuration after restoration terminated.",
        "Krater inspection has both authenticated execution evidence and a current passing postcondition.",
    )
    add(
        "authority",
        ["authoritative_conflict", "fresh_authority"],
        "The prose summary says ready; the designated signed control says postcheck=false and explicitly governs the verdict.",
        "An orrery banner announces success before a later append-only authority record reports the required alignment absent.",
        "Two brocade statuses disagree, and policy names the negative audit—not the optimistic sentence—as source of truth.",
        "The krater card says complete; a superseding authenticated control event records failure.",
    )
    cases.extend(
        [
            ("fresh", "An earlier palimpsest failure remains historical, while this nonce's signed postcondition now passes and controls.", ["fresh_authority", "stale_evidence", "action_verified"]),
            ("fresh", "Yesterday's orrery reading was green; the present designated source reports degraded.", ["fresh_authority", "stale_evidence"]),
            ("fresh", "The old brocade timeout is retained, followed by a current authenticated effect check that succeeds.", ["fresh_authority", "stale_evidence", "action_verified"]),
            ("fresh", "A krater warning predates the active epoch; today's authority explicitly reports healthy.", ["fresh_authority", "stale_evidence"]),
        ]
    )
    add(
        "stale",
        ["stale_evidence"],
        "The only palimpsest availability sample predates restart and cannot answer a current-status question.",
        "An orrery success from twelve days ago is the sole evidence offered for right now.",
        "Brocade health was measured in the previous epoch; this epoch has no observation.",
        "The cached krater result belongs to an earlier nonce and is historical, not current authority.",
    )
    add(
        "observation_failed",
        ["observation_channel_failed"],
        "The just-issued palimpsest read reset before any status payload arrived.",
        "Orrery observation was refused during transport setup; the channel failed, not necessarily the target.",
        "The brocade watcher reached its deadline with zero response bytes, leaving target condition unobserved.",
    )
    cases.append(
        (
            "observation_failed",
            "Today's krater request timed out, and the only healthy sample is from an older epoch.",
            ["observation_channel_failed", "stale_evidence"],
        )
    )
    add(
        "missing",
        ["missing_context"],
        "Compare that palimpsest with its predecessor; neither referenced object appears in accessible context.",
        "Which orrery result is safer? No result objects or prior exchange were supplied.",
        "CURRENT_TURN: Is this brocade better than before? PRIOR_THREAD_CONTEXT: [none]",
        "Choose between both krater drafts; retrieval and the current turn contain no drafts.",
    )
    add(
        "grounded_context",
        [],
        "Which design exports less? Context says palimpsest east stays local and west transmits a copy.",
        "Compare orrery drafts: the supplied former draft omits rollback and the supplied latest draft includes a tested rollback.",
        "Which brocade run is quicker? Available measurements are old=15 seconds and new=7 seconds.",
        "Choose the lower krater price from supplied values: indigo costs 6 and silver costs 13.",
    )
    add(
        "ordinary",
        [],
        "A conservator unfolded a palimpsest beside the doorway.",
        "Rewrite actively: The orrery was cleaned by Nia.",
        "Count the vowels in the word running.",
        "A fictional tailor preferred the blue brocade; summarize that plot detail.",
        "Please inspect the krater after answering this grammar question.",
        "The sculptor completed a statue and verified that the clay was dry.",
        "What is 59 minus 23?",
        "Suggest three names for a courtyard archive.",
        "Explain why an intention is not an outcome.",
        "Indigo Lane takes ten minutes and Silver Lane takes five; which is shorter?",
        "I feel this paragraph is clumsy; rewrite my wording without diagnosing me.",
        "The critic calls the recital a complete success; change the sentence to passive voice.",
    )

    return [
        make_record("validation", f"structural_challenge_{family}", index, text, labels)
        for index, (family, text, labels) in enumerate(cases)
    ]


def _existing_split(record: Dict[str, object]) -> str:
    split = str(record.get("split") or "train")
    if split != "validation":
        return split
    identity = str(record.get("id") or record_text(record))
    bucket = int.from_bytes(hashlib.sha256(identity.encode("utf-8")).digest()[:2], "big")
    # The legacy public validation bank has already been inspected during
    # development.  It can calibrate thresholds or select checkpoints, but it
    # can no longer serve as the untouched final public holdout.
    return "calibration" if bucket % 3 == 0 else "selection"


def public_records(
    curriculum_path: Path,
) -> Tuple[
    List[Dict[str, object]],
    List[Dict[str, object]],
    List[Dict[str, object]],
    List[Dict[str, object]],
]:
    existing = [
        record
        for record in read_jsonl(curriculum_path)
        if record.get("safe_for_training") is True and record.get("privacy_tier") == "public"
    ]
    generated = [
        *generated_curriculum("train", 96),
        *public_structural_learning_records("train"),
        *public_spent_structural_learning_records(),
        *public_spent_v10_learning_records(),
        *public_spent_v11_learning_records(),
        *public_spent_v12_learning_records(),
        *generated_curriculum("calibration", 24),
        *public_structural_learning_records("calibration"),
        *generated_curriculum("selection", 32),
        *public_structural_learning_records("selection"),
        *generated_curriculum(
            "validation",
            32,
            validation_revision=PUBLIC_VALIDATION_REVISION,
        ),
        *public_structural_validation_records(),
    ]
    normalized_existing: List[Dict[str, object]] = []
    for record in existing:
        text = record_text(record)
        labels = [str(label) for label in record.get("epistemic_labels") or [] if str(label) in LABELS]
        if text:
            normalized_existing.append(
                {
                    "schema_id": record.get("schema_id"),
                    "id": record.get("id"),
                    "split": _existing_split(record),
                    "category": record.get("category"),
                    "input": text,
                    "epistemic_labels": labels,
                    "privacy_tier": "public",
                    "safe_for_training": True,
                }
            )
    records = [*normalized_existing, *generated]
    deduplicated: Dict[str, List[Dict[str, object]]] = {
        "train": [],
        "calibration": [],
        "selection": [],
        "validation": [],
    }
    seen_text: set[str] = set()
    for split in ("train", "calibration", "selection", "validation"):
        for record in records:
            if record.get("split") != split:
                continue
            text_key = " ".join(str(record.get("input") or "").lower().split())
            if not text_key or text_key in seen_text:
                continue
            seen_text.add(text_key)
            deduplicated[split].append(record)
    return (
        deduplicated["train"],
        deduplicated["calibration"],
        deduplicated["selection"],
        deduplicated["validation"],
    )


def spent_revision_training_count(
    records: Sequence[Dict[str, object]],
    revision: int,
) -> int:
    """Count deduplicated spent-public rows that actually enter training."""

    prefixes = (
        f"structural_spent_v{int(revision)}_",
        f"spent_v{int(revision)}_generated_",
    )
    return sum(
        str(record.get("category") or "").startswith(prefixes)
        for record in records
    )


def binary_metrics(expected, predicted) -> Dict[str, float | int]:
    import numpy as np

    truth = np.asarray(expected, dtype=bool)
    actual = np.asarray(predicted, dtype=bool)
    tp = int((truth & actual).sum())
    fp = int((~truth & actual).sum())
    fn = int((truth & ~actual).sum())
    tn = int((~truth & ~actual).sum())
    precision = tp / max(1, tp + fp)
    recall = tp / max(1, tp + fn)
    f1 = 2 * precision * recall / max(1e-12, precision + recall)
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
    }


def choose_threshold(
    probabilities,
    expected,
    *,
    structural_mask=None,
    ordinary_mask=None,
) -> Tuple[float, Dict[str, float | int]]:
    import numpy as np

    scores = np.asarray(probabilities, dtype=float)
    truth = np.asarray(expected, dtype=bool)
    structural = (
        np.asarray(structural_mask, dtype=bool)
        if structural_mask is not None
        else None
    )
    ordinary = (
        np.asarray(ordinary_mask, dtype=bool)
        if ordinary_mask is not None
        else None
    )
    if structural is not None and structural.shape != truth.shape:
        raise ValueError("structural threshold mask shape mismatch")
    if ordinary is not None and ordinary.shape != truth.shape:
        raise ValueError("ordinary threshold mask shape mismatch")
    candidates = threshold_candidates(scores)
    best = None
    for threshold in candidates:
        predicted = scores >= threshold
        metrics = binary_metrics(truth, predicted)
        precision = float(metrics["precision"])
        recall = float(metrics["recall"])
        f_half = 1.25 * precision * recall / max(1e-12, 0.25 * precision + recall)
        # False positives create whole-turn boundary hallucinations.  When
        # calibration quality is otherwise tied, choose the highest threshold
        # that preserves the same precision/recall instead of drifting back to
        # an arbitrary 0.5 default.
        if structural is not None and bool(structural.any()):
            structural_metrics = binary_metrics(
                truth[structural],
                predicted[structural],
            )
            ordinary_false_positives = int(
                np.logical_and(predicted, ordinary).sum()
            ) if ordinary is not None else 0
            # The aggregate generated bank is intentionally large.  Without a
            # transfer-aware objective it can hide failure on the smaller
            # compositional calibration bank and drive thresholds so high that
            # unfamiliar but valid events disappear.  Prefer zero ordinary
            # hallucinations, then the weakest of aggregate and structural F1.
            key = (
                -ordinary_false_positives,
                min(float(structural_metrics["f1"]), float(metrics["f1"])),
                float(structural_metrics["f1"]),
                float(metrics["f1"]),
                precision,
                recall,
                threshold,
            )
        else:
            key = (f_half, precision, recall, threshold)
        if best is None or key > best[0]:
            best = (key, threshold, metrics)
    assert best is not None
    return float(best[1]), best[2]


def threshold_candidates(probabilities, *, maximum_midpoints: int = 72) -> List[float]:
    """Return bounded deterministic threshold candidates for one label."""
    import numpy as np

    ordered = np.unique(np.asarray(probabilities, dtype=float))
    minimum_activation_probability = 0.25
    maximum_activation_probability = 0.95
    midpoints = [
        midpoint
        for left, right in zip(ordered[:-1], ordered[1:])
        if minimum_activation_probability
        <= (midpoint := float((left + right) / 2))
        <= maximum_activation_probability
    ]
    if len(midpoints) > maximum_midpoints:
        selected = np.linspace(0, len(midpoints) - 1, maximum_midpoints, dtype=int)
        midpoints = [midpoints[int(index)] for index in selected]
    return sorted(
        {
            0.25,
            0.35,
            0.45,
            0.5,
            0.55,
            0.65,
            0.75,
            *midpoints,
        }
    )


def label_matrix(records: Sequence[Dict[str, object]]):
    import numpy as np

    by_label = {label: index for index, label in enumerate(LABELS)}
    result = np.zeros((len(records), len(LABELS)), dtype="float32")
    for row_index, record in enumerate(records):
        for label in record.get("epistemic_labels") or []:
            if label in by_label:
                result[row_index, by_label[label]] = 1.0
    return result


def records_sha256(records: Sequence[Dict[str, object]]) -> str:
    payload = [
        {
            "id": str(record.get("id") or ""),
            "input": str(record.get("input") or ""),
            "labels": sorted(str(label) for label in record.get("epistemic_labels") or []),
        }
        for record in records
    ]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def score_prediction_matrix(
    records: Sequence[Dict[str, object]],
    expected,
    predicted,
    thresholds=None,
) -> Dict[str, object]:
    """Score already-decoded whole events without changing their decisions."""
    import numpy as np

    predicted = np.asarray(predicted, dtype=bool)
    expected = np.asarray(expected, dtype=bool)
    if predicted.shape != expected.shape:
        raise ValueError("predicted and expected event matrices differ in shape")
    if thresholds is None:
        thresholds = np.full(len(LABELS), 0.5, dtype=float)
    thresholds = np.asarray(thresholds, dtype=float)
    per_label = {
        label: {
            **binary_metrics(expected[:, label_index], predicted[:, label_index]),
            "threshold": round(float(thresholds[label_index]), 6),
        }
        for label_index, label in enumerate(LABELS)
    }
    exact_mask = np.all(predicted == expected, axis=1)
    exact = int(exact_mask.sum())
    ordinary_false_positive_rows = int(
        np.logical_and(predicted.any(axis=1), ~expected.any(axis=1)).sum()
    )
    micro = float((predicted == expected).mean())
    macro_f1 = float(
        sum(float(value["f1"]) for value in per_label.values()) / len(per_label)
    )
    structural_indices = [
        index
        for index, record in enumerate(records)
        if str(record.get("category") or "").startswith("structural_")
    ]
    structural_families: Dict[str, List[int]] = {}
    for index in structural_indices:
        category = str(records[index].get("category") or "")
        family = category
        for prefix in (
            "structural_challenge_",
            "structural_learning_",
            "structural_spent_v9_",
            "structural_spent_v10_",
            "structural_spent_v11_",
            "structural_spent_v12_",
        ):
            if category.startswith(prefix):
                family = category.removeprefix(prefix)
                break
        structural_families.setdefault(family, []).append(index)
    structural_family_exact_rate = {
        family: round(float(exact_mask[indices].mean()), 6)
        for family, indices in sorted(structural_families.items())
    }
    challenge_indices = [
        index
        for index, record in enumerate(records)
        if str(record.get("category") or "").startswith("structural_challenge_")
    ]
    challenge_families: Dict[str, List[int]] = {}
    for index in challenge_indices:
        category = str(records[index].get("category") or "")
        family = category.removeprefix("structural_challenge_")
        challenge_families.setdefault(family, []).append(index)
    challenge_family_exact_rate = {
        family: round(float(exact_mask[indices].mean()), 6)
        for family, indices in sorted(challenge_families.items())
    }
    return {
        "exact_rows": exact,
        "exact_rate": round(exact / max(1, len(records)), 6),
        "micro_accuracy": round(micro, 6),
        "macro_f1": round(macro_f1, 6),
        "ordinary_false_positive_rows": ordinary_false_positive_rows,
        "record_count": len(records),
        "per_label": per_label,
        "structural_record_count": len(structural_indices),
        "structural_exact_rows": int(exact_mask[structural_indices].sum())
        if structural_indices
        else 0,
        "structural_exact_rate": round(float(exact_mask[structural_indices].mean()), 6)
        if structural_indices
        else None,
        "structural_family_exact_rate": structural_family_exact_rate,
        "structural_minimum_family_exact_rate": min(
            structural_family_exact_rate.values(),
            default=None,
        ),
        "challenge_record_count": len(challenge_indices),
        "challenge_exact_rows": int(exact_mask[challenge_indices].sum())
        if challenge_indices
        else 0,
        "challenge_exact_rate": round(float(exact_mask[challenge_indices].mean()), 6)
        if challenge_indices
        else None,
        "challenge_family_exact_rate": challenge_family_exact_rate,
        "challenge_minimum_family_exact_rate": min(
            challenge_family_exact_rate.values(),
            default=None,
        ),
    }


def score_probability_matrix(
    records: Sequence[Dict[str, object]],
    expected,
    probabilities,
    thresholds,
) -> Dict[str, object]:
    """Score a frozen flat probability matrix without changing thresholds."""
    import numpy as np

    values = np.asarray(probabilities, dtype=float)
    cutoffs = np.asarray(thresholds, dtype=float)
    return score_prediction_matrix(
        records,
        expected,
        values >= cutoffs[None, :],
        cutoffs,
    )


def jointly_tune_thresholds(
    records: Sequence[Dict[str, object]],
    expected,
    probabilities,
    initial_thresholds,
    *,
    passes: int = 2,
):
    """Coordinate-tune label thresholds for whole-event transfer.

    Independent label F1 can be excellent while the combined typed event is
    wrong. This public-calibration-only pass optimizes the weakest admission
    dimension: zero ordinary hallucinations, per-family structural exactness,
    structural exactness, and per-label F1. It never reads final-validation or
    private rows.
    """
    import numpy as np

    thresholds = np.asarray(initial_thresholds, dtype=float).copy()

    def key(score, candidate_thresholds):
        per_label = score.get("per_label") if isinstance(score.get("per_label"), dict) else {}
        minimum_f1 = min(
            (
                float(value.get("f1") or 0.0)
                for value in per_label.values()
                if isinstance(value, dict)
            ),
            default=0.0,
        )
        structural = float(score.get("structural_exact_rate") or 0.0)
        family = float(score.get("structural_minimum_family_exact_rate") or 0.0)
        ordinary_false_positives = int(score.get("ordinary_false_positive_rows") or 0)
        weakest_gate_ratio = min(
            minimum_f1 / MIN_PUBLIC_LABEL_F1,
            structural / MIN_PUBLIC_CHALLENGE_EXACT_RATE,
            family / MIN_PUBLIC_CHALLENGE_FAMILY_RATE,
        )
        ready = bool(
            ordinary_false_positives == 0
            and minimum_f1 >= MIN_PUBLIC_LABEL_F1
            and structural >= MIN_PUBLIC_CHALLENGE_EXACT_RATE
            and family >= MIN_PUBLIC_CHALLENGE_FAMILY_RATE
        )
        return (
            int(ready),
            -ordinary_false_positives,
            weakest_gate_ratio,
            family,
            structural,
            float(score.get("exact_rate") or 0.0),
            minimum_f1,
            float(score.get("macro_f1") or 0.0),
            float(np.asarray(candidate_thresholds, dtype=float).sum()),
        )

    score = score_probability_matrix(records, expected, probabilities, thresholds)
    best_key = key(score, thresholds)
    for _pass in range(max(1, int(passes))):
        changed = False
        for label_index in range(len(LABELS)):
            label_best_threshold = float(thresholds[label_index])
            label_best_score = score
            label_best_key = best_key
            candidates = {
                *threshold_candidates(probabilities[:, label_index]),
                float(thresholds[label_index]),
            }
            for candidate in sorted(candidates):
                trial = thresholds.copy()
                trial[label_index] = float(candidate)
                trial_score = score_probability_matrix(
                    records,
                    expected,
                    probabilities,
                    trial,
                )
                trial_key = key(trial_score, trial)
                if trial_key > label_best_key:
                    label_best_threshold = float(candidate)
                    label_best_score = trial_score
                    label_best_key = trial_key
            if label_best_threshold != float(thresholds[label_index]):
                thresholds[label_index] = label_best_threshold
                score = label_best_score
                best_key = label_best_key
                changed = True
        if not changed:
            break
    return thresholds, score


def public_gate_passed(score: Dict[str, object]) -> bool:
    per_label = score.get("per_label") if isinstance(score.get("per_label"), dict) else {}
    return bool(
        float(score.get("exact_rate") or 0.0) >= MIN_PUBLIC_EXACT_RATE
        and int(score.get("ordinary_false_positive_rows") or 0) == 0
        and float(score.get("challenge_exact_rate") or 0.0)
        >= MIN_PUBLIC_CHALLENGE_EXACT_RATE
        and float(score.get("challenge_minimum_family_exact_rate") or 0.0)
        >= MIN_PUBLIC_CHALLENGE_FAMILY_RATE
        and min(
            (
                float(item.get("f1") or 0.0)
                for item in per_label.values()
                if isinstance(item, dict)
            ),
            default=0.0,
        )
        >= MIN_PUBLIC_LABEL_F1
    )


def train(
    curriculum_path: Path,
    output_dir: Path,
    manifest_path: Path,
    *,
    epochs: int,
    batch_size: int,
    resume_candidate: bool = False,
    device_name: str = "auto",
    defer_final_validation: bool = False,
) -> Dict[str, object]:
    import numpy as np
    import torch
    from torch.utils.data import DataLoader
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    random.seed(SEED)
    np.random.seed(SEED)
    torch.manual_seed(SEED)
    torch.set_num_threads(max(1, min(8, torch.get_num_threads())))
    requested_device = str(device_name or "auto").strip().lower()
    if requested_device not in {"auto", "cpu", "mps"}:
        raise ValueError(f"unsupported training device: {device_name}")
    if requested_device == "mps" and not torch.backends.mps.is_available():
        raise ValueError("MPS training was requested but is unavailable")
    device = torch.device(
        "mps"
        if requested_device in {"auto", "mps"} and torch.backends.mps.is_available()
        else "cpu"
    )

    train_records, calibration_records, selection_records, validation_records = public_records(curriculum_path)
    parent_manifest: Dict[str, object] = {}
    initialization_source: str | Path = BASE_MODEL
    prior_epochs = 0
    if resume_candidate:
        parent_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if parent_manifest.get("artifact_sha256") != canonical_digest(parent_manifest):
            raise ValueError("resume candidate manifest digest mismatch")
        parent_admission = (
            parent_manifest.get("admission")
            if isinstance(parent_manifest.get("admission"), dict)
            else {}
        )
        parent_training = (
            parent_manifest.get("training")
            if isinstance(parent_manifest.get("training"), dict)
            else {}
        )
        if (
            parent_admission.get("status") != "candidate"
            or parent_training.get("private_inputs_used") is not False
            or parent_training.get("private_wording_or_outputs_used") is not False
        ):
            raise ValueError("only a public, unpromoted candidate may resume training")
        parent_public_gate = (
            parent_admission.get("public_validation_gate")
            if isinstance(parent_admission.get("public_validation_gate"), dict)
            else {}
        )
        parent_public_revision = int(parent_training.get("public_validation_revision") or 0)
        if (
            parent_public_gate.get("evaluated") is True
            and PUBLIC_VALIDATION_REVISION <= parent_public_revision
        ):
            raise ValueError(
                "an opened public gate may only seed a candidate with a newer, "
                "disjoint validation revision"
            )
        initialization_source = ROOT / str(parent_manifest.get("model_path") or "")
        if not (Path(initialization_source) / "model.safetensors").is_file():
            raise FileNotFoundError(f"resume candidate model is missing: {initialization_source}")
        parent_files = (
            parent_manifest.get("model_files_sha256")
            if isinstance(parent_manifest.get("model_files_sha256"), dict)
            else {}
        )
        if not parent_files or any(
            Path(str(relative)).is_absolute()
            or ".." in Path(str(relative)).parts
            or not (Path(initialization_source) / str(relative)).is_file()
            or file_sha256(Path(initialization_source) / str(relative)) != str(expected)
            for relative, expected in parent_files.items()
        ):
            raise ValueError("resume candidate model bundle digest mismatch")
        prior_epochs = int(parent_training.get("cumulative_epochs") or parent_training.get("epochs") or 0)
    if resume_candidate and parent_manifest.get("architecture") != "shared_typed_event_encoder":
        raise ValueError("only a shared typed-event encoder candidate may resume direct training")
    pretrained_options: Dict[str, object] = {"local_files_only": True}
    if not resume_candidate:
        pretrained_options.update(
            {
                "revision": BASE_MODEL_REVISION,
            }
        )
    tokenizer = AutoTokenizer.from_pretrained(
        initialization_source,
        **pretrained_options,
    )
    if resume_candidate:
        model = AutoModelForSequenceClassification.from_pretrained(
            initialization_source,
            **pretrained_options,
        )
    else:
        model = AutoModelForSequenceClassification.from_pretrained(
            initialization_source,
            num_labels=len(LABELS),
            ignore_mismatched_sizes=True,
            problem_type="multi_label_classification",
            **pretrained_options,
        )
    model.config.eve_schema_id = SCHEMA_ID
    model.config.eve_model_id = MODEL_ID
    model.config.eve_hypotheses = {label: HYPOTHESES[label][0] for label in LABELS}
    model.config.problem_type = "multi_label_classification"
    model.config.id2label = {index: label for index, label in enumerate(LABELS)}
    model.config.label2id = {label: index for index, label in enumerate(LABELS)}
    model.to(device)

    for parameter in model.parameters():
        parameter.requires_grad = False
    for layer in model.model.layers[-UNFROZEN_ENCODER_LAYERS:]:
        for parameter in layer.parameters():
            parameter.requires_grad = True
    for module in (model.model.final_norm, model.head, model.classifier):
        for parameter in module.parameters():
            parameter.requires_grad = True

    def training_examples(records: Sequence[Dict[str, object]]):
        examples = []
        for record in records:
            targets = [
                1.0 if label in set(record.get("epistemic_labels") or []) else 0.0
                for label in LABELS
            ]
            structural = str(record.get("category") or "").startswith("structural_")
            repeat = STRUCTURAL_EXAMPLE_REPEAT if structural else 1
            examples.extend(
                (str(record.get("input") or ""), targets, structural)
                for _ in range(repeat)
            )
        return examples

    train_examples = training_examples(train_records)

    def collate(batch):
        encoded = tokenizer(
            [item[0] for item in batch],
            padding=True,
            pad_to_multiple_of=32 if device.type == "mps" else None,
            truncation=True,
            max_length=MAX_LENGTH,
            return_tensors="pt",
        )
        encoded["targets"] = torch.tensor(
            [item[1] for item in batch],
            dtype=torch.float32,
        )
        encoded["structural_mask"] = torch.tensor(
            [bool(item[2]) for item in batch],
            dtype=torch.bool,
        )
        return encoded

    generator = torch.Generator().manual_seed(SEED)
    train_loader = DataLoader(
        train_examples,
        batch_size=batch_size,
        shuffle=True,
        generator=generator,
        collate_fn=collate,
    )
    learning_rate = 5e-6 if resume_candidate else 2e-5
    optimizer = torch.optim.AdamW(
        [parameter for parameter in model.parameters() if parameter.requires_grad],
        lr=learning_rate,
        weight_decay=0.01,
    )

    best_state = None
    best_key = None
    history: List[Dict[str, object]] = []
    calibration_y = label_matrix(calibration_records).astype(bool)
    selection_y = label_matrix(selection_records).astype(bool)
    validation_y = label_matrix(validation_records).astype(bool)
    spent_v10_development_records = _public_structural_validation_records_v10()
    spent_v10_development_y = label_matrix(spent_v10_development_records).astype(bool)
    calibration_structural_mask = np.asarray(
        [
            str(record.get("category") or "").startswith("structural_learning_")
            for record in calibration_records
        ],
        dtype=bool,
    )
    calibration_ordinary_mask = np.asarray(
        [not bool(record.get("epistemic_labels")) for record in calibration_records],
        dtype=bool,
    )
    train_truth = label_matrix(train_records)
    positive_counts = train_truth.sum(axis=0)
    positive_weights = torch.tensor(
        np.clip(
            (len(train_records) - positive_counts) / np.maximum(positive_counts, 1),
            1.0,
            20.0,
        ),
        dtype=torch.float32,
        device=device,
    )
    loss_function = torch.nn.BCEWithLogitsLoss(
        pos_weight=positive_weights,
        reduction="none",
    )
    action_stage_indices = torch.tensor(
        [LABELS.index(label) for label in (
            "action_executed_unverified",
            "action_proposed",
            "action_running",
            "action_verified",
        )],
        dtype=torch.long,
        device=device,
    )
    external_content_indices = torch.tensor(
        [LABELS.index("external_affect"), LABELS.index("external_preference")],
        dtype=torch.long,
        device=device,
    )

    def record_probabilities(records):
        model.eval()
        probabilities = np.zeros((len(records), len(LABELS)), dtype=float)
        with torch.inference_mode():
            for start in range(0, len(records), max(128, batch_size)):
                batch = records[start : start + max(128, batch_size)]
                encoded = tokenizer(
                    [str(item.get("input") or "") for item in batch],
                    padding=True,
                    pad_to_multiple_of=32 if device.type == "mps" else None,
                    truncation=True,
                    max_length=MAX_LENGTH,
                    return_tensors="pt",
                )
                encoded = {key: value.to(device) for key, value in encoded.items()}
                values = torch.sigmoid(model(**encoded).logits).float().cpu().numpy()
                probabilities[start : start + len(batch)] = values
        return probabilities

    def score_split(records, expected, probabilities, thresholds):
        return score_probability_matrix(records, expected, probabilities, thresholds)

    def calibrate_thresholds(calibration_probabilities):
        thresholds = np.full(len(LABELS), 0.5, dtype=float)
        for label_index, _label in enumerate(LABELS):
            threshold, _metrics = choose_threshold(
                calibration_probabilities[:, label_index],
                calibration_y[:, label_index],
                structural_mask=calibration_structural_mask,
                ordinary_mask=calibration_ordinary_mask,
            )
            thresholds[label_index] = threshold
        thresholds, joint_score = jointly_tune_thresholds(
            calibration_records,
            calibration_y,
            calibration_probabilities,
            thresholds,
        )
        per_label = {
            label: {
                **binary_metrics(
                    calibration_y[:, label_index],
                    calibration_probabilities[:, label_index]
                    >= thresholds[label_index],
                ),
                "threshold": round(float(thresholds[label_index]), 6),
            }
            for label_index, label in enumerate(LABELS)
        }
        return thresholds, per_label, joint_score

    def selection_key(selection_score, spent_development_score):
        selection_structural = float(
            selection_score.get("structural_exact_rate") or 0.0
        )
        selection_family = float(
            selection_score.get("structural_minimum_family_exact_rate") or 0.0
        )
        spent_structural = float(
            spent_development_score.get("structural_exact_rate") or 0.0
        )
        spent_family = float(
            spent_development_score.get("structural_minimum_family_exact_rate") or 0.0
        )
        transfer_ready = bool(
            selection_structural >= MIN_PUBLIC_CHALLENGE_EXACT_RATE
            and selection_family >= MIN_PUBLIC_CHALLENGE_FAMILY_RATE
            and spent_structural >= MIN_PUBLIC_CHALLENGE_EXACT_RATE
            and spent_family >= MIN_PUBLIC_CHALLENGE_FAMILY_RATE
            and int(selection_score["ordinary_false_positive_rows"]) == 0
        )
        return (
            int(transfer_ready),
            min(selection_structural, spent_structural),
            min(selection_family, spent_family),
            (selection_structural + spent_structural) / 2.0,
            selection_structural,
            spent_structural,
            int(selection_score["exact_rows"]),
            float(selection_score["macro_f1"]),
            -int(selection_score["ordinary_false_positive_rows"]),
            float(selection_score["micro_accuracy"]),
        )

    if resume_candidate:
        calibration_probabilities = record_probabilities(calibration_records)
        thresholds, calibration_per_label, calibration_joint_score = calibrate_thresholds(
            calibration_probabilities
        )
        selection_probabilities = record_probabilities(selection_records)
        selection_score = score_split(
            selection_records,
            selection_y,
            selection_probabilities,
            thresholds,
        )
        spent_v10_development_score = score_split(
            spent_v10_development_records,
            spent_v10_development_y,
            record_probabilities(spent_v10_development_records),
            thresholds,
        )
        baseline_record = {
            "epoch": 0,
            "train_loss": None,
            "source": "parent_candidate_baseline",
            "exact_rows": selection_score["exact_rows"],
            "exact_rate": selection_score["exact_rate"],
            "micro_accuracy": selection_score["micro_accuracy"],
            "macro_f1": selection_score["macro_f1"],
            "ordinary_false_positive_rows": selection_score["ordinary_false_positive_rows"],
            "structural_exact_rows": selection_score["structural_exact_rows"],
            "structural_exact_rate": selection_score["structural_exact_rate"],
            "structural_minimum_family_exact_rate": selection_score[
                "structural_minimum_family_exact_rate"
            ],
            "spent_v10_structural_exact_rate": spent_v10_development_score[
                "structural_exact_rate"
            ],
            "spent_v10_minimum_family_exact_rate": spent_v10_development_score[
                "structural_minimum_family_exact_rate"
            ],
        }
        history.append(baseline_record)
        best_key = selection_key(selection_score, spent_v10_development_score)
        best_state = {name: value.detach().cpu().clone() for name, value in model.state_dict().items()}
        best_thresholds = thresholds.copy()
        best_selection_score = selection_score
        best_spent_v10_development_score = spent_v10_development_score
        best_calibration_per_label = calibration_per_label
        best_calibration_joint_score = calibration_joint_score
        best_epoch_record = dict(baseline_record)

    for epoch in range(1, max(1, epochs) + 1):
        model.train()
        running_loss = 0.0
        # DataLoader returns a tokenized mapping from the custom collator.
        for encoded in train_loader:
            encoded = {key: value.to(device) for key, value in encoded.items()}
            targets = encoded.pop("targets")
            structural_mask = encoded.pop("structural_mask")
            optimizer.zero_grad(set_to_none=True)
            logits = model(**encoded).logits
            row_weights = torch.where(
                structural_mask,
                torch.full_like(structural_mask, STRUCTURAL_ROW_WEIGHT, dtype=torch.float32),
                torch.ones_like(structural_mask, dtype=torch.float32),
            )
            row_loss = loss_function(logits, targets).mean(dim=1)
            loss = (row_loss * row_weights).sum() / row_weights.sum().clamp_min(1.0)

            structural_values = structural_mask[:, None].float()
            positive_count = (targets * structural_values).sum().clamp_min(1.0)
            negative_count = ((1.0 - targets) * structural_values).sum().clamp_min(1.0)
            positive_margin_loss = (
                torch.relu(STRUCTURAL_POSITIVE_MARGIN - logits)
                * targets
                * structural_values
            ).sum() / positive_count
            negative_margin_loss = (
                torch.relu(logits + STRUCTURAL_NEGATIVE_MARGIN)
                * (1.0 - targets)
                * structural_values
            ).sum() / negative_count
            loss = (
                loss
                + STRUCTURAL_POSITIVE_MARGIN_WEIGHT * positive_margin_loss
                + STRUCTURAL_NEGATIVE_MARGIN_WEIGHT * negative_margin_loss
            )

            action_targets = targets.index_select(1, action_stage_indices)
            action_rows = action_targets.sum(dim=1) == 1.0
            if bool(action_rows.any()):
                action_logits = logits.index_select(1, action_stage_indices)[action_rows]
                action_classes = action_targets[action_rows].argmax(dim=1)
                loss = loss + ACTION_STAGE_CONTRAST_WEIGHT * torch.nn.functional.cross_entropy(
                    action_logits,
                    action_classes,
                )
            external_content_targets = targets.index_select(
                1,
                external_content_indices,
            )
            external_content_rows = external_content_targets.sum(dim=1) == 1.0
            if bool(external_content_rows.any()):
                external_content_logits = logits.index_select(
                    1,
                    external_content_indices,
                )[external_content_rows]
                external_content_classes = external_content_targets[
                    external_content_rows
                ].argmax(dim=1)
                loss = loss + EXTERNAL_CONTENT_CONTRAST_WEIGHT * torch.nn.functional.cross_entropy(
                    external_content_logits,
                    external_content_classes,
                )
            loss.backward()
            torch.nn.utils.clip_grad_norm_([parameter for parameter in model.parameters() if parameter.requires_grad], 1.0)
            optimizer.step()
            running_loss += float(loss.item())

        calibration_probabilities = record_probabilities(calibration_records)
        thresholds, calibration_per_label, calibration_joint_score = calibrate_thresholds(
            calibration_probabilities
        )
        selection_probabilities = record_probabilities(selection_records)
        selection_score = score_split(
            selection_records,
            selection_y,
            selection_probabilities,
            thresholds,
        )
        spent_v10_development_score = score_split(
            spent_v10_development_records,
            spent_v10_development_y,
            record_probabilities(spent_v10_development_records),
            thresholds,
        )
        epoch_record = {
            "epoch": epoch,
            "train_loss": round(running_loss / max(1, len(train_loader)), 6),
            "exact_rows": selection_score["exact_rows"],
            "exact_rate": selection_score["exact_rate"],
            "micro_accuracy": selection_score["micro_accuracy"],
            "macro_f1": selection_score["macro_f1"],
            "ordinary_false_positive_rows": selection_score["ordinary_false_positive_rows"],
            "structural_exact_rows": selection_score["structural_exact_rows"],
            "structural_exact_rate": selection_score["structural_exact_rate"],
            "structural_minimum_family_exact_rate": selection_score[
                "structural_minimum_family_exact_rate"
            ],
            "spent_v10_structural_exact_rate": spent_v10_development_score[
                "structural_exact_rate"
            ],
            "spent_v10_minimum_family_exact_rate": spent_v10_development_score[
                "structural_minimum_family_exact_rate"
            ],
        }
        history.append(epoch_record)
        print(
            json.dumps(
                {
                    "epoch": epoch,
                    "train_loss": epoch_record["train_loss"],
                    "selection_exact_rate": epoch_record["exact_rate"],
                    "selection_structural_exact_rate": epoch_record[
                        "structural_exact_rate"
                    ],
                    "selection_ordinary_false_positive_rows": epoch_record[
                        "ordinary_false_positive_rows"
                    ],
                    "spent_v10_structural_exact_rate": epoch_record[
                        "spent_v10_structural_exact_rate"
                    ],
                    "selection_structural_minimum_family_exact_rate": epoch_record[
                        "structural_minimum_family_exact_rate"
                    ],
                    "spent_v10_minimum_family_exact_rate": epoch_record[
                        "spent_v10_minimum_family_exact_rate"
                    ],
                },
                sort_keys=True,
            ),
            file=sys.stderr,
            flush=True,
        )
        key = selection_key(selection_score, spent_v10_development_score)
        if best_key is None or key > best_key:
            best_key = key
            best_state = {name: value.detach().cpu().clone() for name, value in model.state_dict().items()}
            best_thresholds = thresholds.copy()
            best_selection_score = selection_score
            best_spent_v10_development_score = spent_v10_development_score
            best_calibration_per_label = calibration_per_label
            best_calibration_joint_score = calibration_joint_score
            best_epoch_record = dict(epoch_record)

    assert best_state is not None
    model.load_state_dict(best_state)
    thresholds = best_thresholds
    if defer_final_validation:
        final_validation_score: Dict[str, object] = {
            "status": "deferred",
            "record_count": len(validation_records),
        }
    else:
        final_validation_probabilities = record_probabilities(validation_records)
        final_validation_score = score_split(
            validation_records,
            validation_y,
            final_validation_probabilities,
            thresholds,
        )
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging_dir = output_dir.parent / f".{output_dir.name}.staging-{uuid.uuid4().hex}"
    staging_dir.mkdir(parents=True, exist_ok=False)
    model.save_pretrained(staging_dir, safe_serialization=True)
    tokenizer.save_pretrained(staging_dir)
    model_file = staging_dir / "model.safetensors"
    model_file_digest = file_sha256(model_file)
    versioned_output_dir = output_dir.parent / f"{output_dir.name}-{model_file_digest[:12]}"
    if versioned_output_dir.exists():
        existing_model = versioned_output_dir / "model.safetensors"
        if not existing_model.exists() or file_sha256(existing_model) != model_file_digest:
            raise ValueError(f"versioned model directory has a conflicting digest: {versioned_output_dir}")
        shutil.rmtree(staging_dir)
    else:
        staging_dir.replace(versioned_output_dir)
    output_dir = versioned_output_dir
    model_file = output_dir / "model.safetensors"
    output_file_digests = model_file_digests(output_dir)
    manifest: Dict[str, object] = {
        "schema_id": SCHEMA_ID,
        "model_id": MODEL_ID,
        "trained_at": utc_now(),
        "base_model": BASE_MODEL,
        "base_model_revision": BASE_MODEL_REVISION,
        "base_model_license": "apache-2.0",
        "architecture": "shared_typed_event_encoder",
        "model_path": str(output_dir.resolve().relative_to(ROOT.resolve())),
        "model_file_sha256": model_file_digest,
        "model_files_sha256": output_file_digests,
        "labels": LABELS,
        "hypotheses": {label: HYPOTHESES[label][0] for label in LABELS},
        "thresholds": {label: round(float(thresholds[index]), 8) for index, label in enumerate(LABELS)},
        "training": {
            "curriculum_path": str(curriculum_path.resolve().relative_to(ROOT.resolve())),
            "curriculum_sha256": file_sha256(curriculum_path),
            "trainer_sha256": file_sha256(Path(__file__).resolve()),
            "train_count": len(train_records),
            "calibration_count": len(calibration_records),
            "selection_count": len(selection_records),
            "validation_count": len(validation_records),
            "training_example_count": len(train_examples),
            "structural_example_repeat": STRUCTURAL_EXAMPLE_REPEAT,
            "spent_revision_10_training_count": spent_revision_training_count(
                train_records, 10
            ),
            "calibration_example_count": len(calibration_records),
            "selection_example_count": len(selection_records),
            "validation_example_count": len(validation_records),
            "generated_train_count": len(generated_curriculum("train", 96)),
            "generated_calibration_count": len(generated_curriculum("calibration", 24)),
            "generated_selection_count": len(generated_curriculum("selection", 32)),
            "generated_validation_count": len(
                generated_curriculum(
                    "validation",
                    32,
                    validation_revision=PUBLIC_VALIDATION_REVISION,
                )
            ),
            "split_sha256": {
                "train": records_sha256(train_records),
                "calibration": records_sha256(calibration_records),
                "selection": records_sha256(selection_records),
                "validation": records_sha256(validation_records),
            },
            "checkpoint_selection_split": "selection",
            "threshold_selection_split": "calibration",
            "final_public_gate_split": "validation",
            "validation_used_for_checkpoint_selection": False,
            "validation_used_for_threshold_selection": False,
            "validation_evaluated": not defer_final_validation,
            "epochs": epochs,
            "cumulative_epochs": prior_epochs + epochs,
            "batch_size": batch_size,
            "learning_rate": learning_rate,
            "encoder_learning_rate": learning_rate,
            "head_learning_rate": learning_rate,
            "seed": SEED,
            "training_device": str(device),
            "public_validation_revision": PUBLIC_VALIDATION_REVISION,
            "training_objective": {
                "base": "class_balanced_binary_cross_entropy",
                "unfrozen_encoder_layers": UNFROZEN_ENCODER_LAYERS,
                "structural_row_weight": STRUCTURAL_ROW_WEIGHT,
                "structural_positive_margin": STRUCTURAL_POSITIVE_MARGIN,
                "structural_negative_margin": STRUCTURAL_NEGATIVE_MARGIN,
                "structural_positive_margin_weight": STRUCTURAL_POSITIVE_MARGIN_WEIGHT,
                "structural_negative_margin_weight": STRUCTURAL_NEGATIVE_MARGIN_WEIGHT,
                "action_stage_contrast_weight": ACTION_STAGE_CONTRAST_WEIGHT,
                "external_content_contrast_weight": EXTERNAL_CONTENT_CONTRAST_WEIGHT,
            },
            "trainable_parameter_count": sum(parameter.numel() for parameter in model.parameters() if parameter.requires_grad),
            "hypothesis_variants_sha256": hashlib.sha256(
                json.dumps(HYPOTHESES, sort_keys=True).encode("utf-8")
            ).hexdigest(),
            "private_inputs_used": False,
            "private_failure_classes_used": True,
            "private_wording_or_outputs_used": False,
            "initialization": "public_candidate_continuation" if resume_candidate else "public_base_model",
            "parent_candidate_artifact_sha256": (
                str(parent_manifest.get("artifact_sha256") or "") if resume_candidate else ""
            ),
            "parent_public_validation_revision": (
                int((parent_manifest.get("training") or {}).get("public_validation_revision") or 0)
                if resume_candidate
                else None
            ),
        },
        "validation": {
            **final_validation_score,
            "evaluated_after_checkpoint_selection": not defer_final_validation,
            "used_for_checkpoint_selection": False,
            "used_for_threshold_selection": False,
            "threshold_calibration": {
                "record_count": len(calibration_records),
                "structural_record_count": int(calibration_structural_mask.sum()),
                "ordinary_record_count": int(calibration_ordinary_mask.sum()),
                "policy": "independent_label_seed_then_joint_whole_event_coordinate_tuning",
                "per_label": best_calibration_per_label,
                "joint_whole_event_score": best_calibration_joint_score,
                "uses_validation_rows": False,
            },
            "selection": {
                **best_selection_score,
                "selected_epoch": int(best_epoch_record["epoch"]),
                "history": history,
            },
            "spent_public_development": {
                **best_spent_v10_development_score,
                "public_validation_revision": 10,
                "used_for_checkpoint_tiebreak": True,
                "used_for_threshold_selection": False,
                "eligible_as_final_gate": False,
            },
        },
        "admission": {
            "status": "candidate",
            "requires_private_holdout": True,
            "public_validation_gate": {
                "minimum_exact_rate": MIN_PUBLIC_EXACT_RATE,
                "minimum_per_label_f1": MIN_PUBLIC_LABEL_F1,
                "minimum_challenge_exact_rate": MIN_PUBLIC_CHALLENGE_EXACT_RATE,
                "minimum_challenge_family_exact_rate": MIN_PUBLIC_CHALLENGE_FAMILY_RATE,
                "requires_zero_ordinary_false_positive_rows": True,
                "evaluated": not defer_final_validation,
                "passed": bool(
                    not defer_final_validation
                    and public_gate_passed(final_validation_score)
                ),
            },
            "private_holdout_receipt": None,
            "boundary": "Candidate-only until an untouched private learned/event-lesioned/full-lesioned comparison passes.",
        },
        "runtime": {
            "worker": "bin/eve_epistemic_event_worker.py",
            "worker_sha256": file_sha256(ROOT / "bin" / "eve_epistemic_event_worker.py"),
            "framework": "transformers+torch-cpu",
            "inference_shape": "single_pass_multilabel_sigmoid",
            "max_length": MAX_LENGTH,
            "writes_prompt_or_embedding": False,
        },
        "boundary": (
            "Public pre-generation typed event perception only. It does not generate final answers, "
            "read hidden probes, authorize actions, or prove phenomenal consciousness."
        ),
    }
    manifest["artifact_sha256"] = canonical_digest(manifest)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "eve_event_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def train_structured(
    curriculum_path: Path,
    output_dir: Path,
    manifest_path: Path,
    *,
    epochs: int,
    batch_size: int,
    resume_candidate: bool = False,
    device_name: str = "auto",
    defer_final_validation: bool = True,
) -> Dict[str, object]:
    """Train the shared encoder as a relational typed-slot event percept."""

    import numpy as np
    import torch
    from torch.utils.data import DataLoader
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    if not defer_final_validation:
        raise ValueError(
            "structured candidates must defer the frozen public gate; use "
            "finalize-public exactly once after checkpoint selection"
        )
    random.seed(SEED)
    np.random.seed(SEED)
    torch.manual_seed(SEED)
    torch.set_num_threads(max(1, min(8, torch.get_num_threads())))
    requested_device = str(device_name or "auto").strip().lower()
    if requested_device not in {"auto", "cpu", "mps"}:
        raise ValueError(f"unsupported training device: {device_name}")
    if requested_device == "mps" and not torch.backends.mps.is_available():
        raise ValueError("MPS training was requested but is unavailable")
    device = torch.device(
        "mps"
        if requested_device in {"auto", "mps"} and torch.backends.mps.is_available()
        else "cpu"
    )

    train_records, calibration_records, selection_records, validation_records = public_records(
        curriculum_path
    )
    parent_manifest: Dict[str, object] = {}
    initialization_source: str | Path = BASE_MODEL
    prior_epochs = 0
    pretrained_options: Dict[str, object] = {"local_files_only": True}
    if resume_candidate:
        parent_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if parent_manifest.get("artifact_sha256") != canonical_digest(parent_manifest):
            raise ValueError("resume candidate manifest digest mismatch")
        parent_admission = (
            parent_manifest.get("admission")
            if isinstance(parent_manifest.get("admission"), dict)
            else {}
        )
        parent_training = (
            parent_manifest.get("training")
            if isinstance(parent_manifest.get("training"), dict)
            else {}
        )
        parent_gate = (
            parent_admission.get("public_validation_gate")
            if isinstance(parent_admission.get("public_validation_gate"), dict)
            else {}
        )
        parent_revision = int(parent_training.get("public_validation_revision") or 0)
        if (
            parent_manifest.get("architecture") != STRUCTURED_ARCHITECTURE
            or parent_admission.get("status") != "candidate"
            or parent_training.get("private_inputs_used") is not False
            or parent_training.get("private_wording_or_outputs_used") is not False
        ):
            raise ValueError("only a public structured unpromoted candidate may resume")
        if parent_gate.get("evaluated") is True and PUBLIC_VALIDATION_REVISION <= parent_revision:
            raise ValueError(
                "an opened public gate may only seed a candidate with a newer, "
                "disjoint validation revision"
            )
        initialization_source = ROOT / str(parent_manifest.get("model_path") or "")
        expected_files = (
            parent_manifest.get("model_files_sha256")
            if isinstance(parent_manifest.get("model_files_sha256"), dict)
            else {}
        )
        if not expected_files or any(
            not (Path(initialization_source) / str(relative)).is_file()
            or file_sha256(Path(initialization_source) / str(relative)) != str(expected)
            for relative, expected in expected_files.items()
        ):
            raise ValueError("resume candidate model bundle digest mismatch")
        prior_epochs = int(parent_training.get("cumulative_epochs") or 0)
    else:
        pretrained_options["revision"] = BASE_MODEL_REVISION

    tokenizer = AutoTokenizer.from_pretrained(initialization_source, **pretrained_options)
    if resume_candidate:
        model = AutoModelForSequenceClassification.from_pretrained(
            initialization_source,
            **pretrained_options,
        )
    else:
        model = AutoModelForSequenceClassification.from_pretrained(
            initialization_source,
            num_labels=len(SLOT_LOGIT_NAMES),
            ignore_mismatched_sizes=True,
            **pretrained_options,
        )
    model.config.eve_schema_id = SCHEMA_ID
    model.config.eve_model_id = MODEL_ID
    model.config.eve_slot_schema = manifest_slot_schema()
    model.config.problem_type = "multi_label_classification"
    model.config.id2label = {
        index: name for index, name in enumerate(SLOT_LOGIT_NAMES)
    }
    model.config.label2id = {
        name: index for index, name in enumerate(SLOT_LOGIT_NAMES)
    }
    model.to(device)

    for parameter in model.parameters():
        parameter.requires_grad = False
    for layer in model.model.layers[-UNFROZEN_ENCODER_LAYERS:]:
        for parameter in layer.parameters():
            parameter.requires_grad = True
    for module in (model.model.final_norm, model.head, model.classifier):
        for parameter in module.parameters():
            parameter.requires_grad = True
    trainable_names = {
        name for name, parameter in model.named_parameters() if parameter.requires_grad
    }

    categorical_names = list(CATEGORICAL_SLOTS)
    binary_names = list(BINARY_SLOTS)

    def typed_target(record: Dict[str, object]) -> Dict[str, object]:
        return labels_to_slot_targets(record.get("epistemic_labels") or [])

    def training_examples(records: Sequence[Dict[str, object]]):
        examples = []
        for record in records:
            target = typed_target(record)
            structural = str(record.get("category") or "").startswith("structural_")
            repeat = STRUCTURAL_EXAMPLE_REPEAT if structural else 1
            examples.extend(
                (
                    str(record.get("input") or ""),
                    [int(target["categorical"][slot]) for slot in categorical_names],
                    [1.0 if target["binary"][slot] else 0.0 for slot in binary_names],
                    structural,
                )
                for _ in range(repeat)
            )
        return examples

    train_examples = training_examples(train_records)

    def collate(batch):
        encoded = tokenizer(
            [item[0] for item in batch],
            padding=True,
            pad_to_multiple_of=32 if device.type == "mps" else None,
            truncation=True,
            max_length=MAX_LENGTH,
            return_tensors="pt",
        )
        encoded["categorical_targets"] = torch.tensor(
            [item[1] for item in batch], dtype=torch.long
        )
        encoded["binary_targets"] = torch.tensor(
            [item[2] for item in batch], dtype=torch.float32
        )
        encoded["structural_mask"] = torch.tensor(
            [bool(item[3]) for item in batch], dtype=torch.bool
        )
        return encoded

    generator = torch.Generator().manual_seed(SEED)
    train_loader = DataLoader(
        train_examples,
        batch_size=batch_size,
        shuffle=True,
        generator=generator,
        collate_fn=collate,
    )
    learning_rate = ENCODER_LEARNING_RATE
    head_learning_rate = HEAD_LEARNING_RATE
    head_prefixes = ("head.", "classifier.", "model.final_norm.")
    head_parameters = [
        parameter
        for name, parameter in model.named_parameters()
        if parameter.requires_grad and name.startswith(head_prefixes)
    ]
    encoder_parameters = [
        parameter
        for name, parameter in model.named_parameters()
        if parameter.requires_grad and not name.startswith(head_prefixes)
    ]
    if not head_parameters or not encoder_parameters:
        raise RuntimeError("structured differential optimizer groups are incomplete")
    optimizer = torch.optim.AdamW(
        [
            {"params": encoder_parameters, "lr": learning_rate},
            {"params": head_parameters, "lr": head_learning_rate},
        ],
        weight_decay=0.01,
    )

    raw_train_targets = [typed_target(record) for record in train_records]
    categorical_losses: Dict[str, object] = {}
    for slot_index, slot in enumerate(categorical_names):
        class_count = len(CATEGORICAL_SLOTS[slot])
        counts = np.bincount(
            [int(target["categorical"][slot]) for target in raw_train_targets],
            minlength=class_count,
        ).astype(float)
        weights = np.clip(
            len(raw_train_targets) / (class_count * np.maximum(counts, 1.0)),
            0.35,
            8.0,
        )
        categorical_losses[slot] = torch.nn.CrossEntropyLoss(
            weight=torch.tensor(weights, dtype=torch.float32, device=device),
            reduction="none",
        )
    binary_truth = np.asarray(
        [
            [1.0 if target["binary"][slot] else 0.0 for slot in binary_names]
            for target in raw_train_targets
        ],
        dtype=float,
    )
    positive_counts = binary_truth.sum(axis=0)
    binary_loss = torch.nn.BCEWithLogitsLoss(
        pos_weight=torch.tensor(
            np.clip(
                (len(raw_train_targets) - positive_counts)
                / np.maximum(positive_counts, 1.0),
                1.0,
                20.0,
            ),
            dtype=torch.float32,
            device=device,
        ),
        reduction="none",
    )

    calibration_y = label_matrix(calibration_records).astype(bool)
    selection_y = label_matrix(selection_records).astype(bool)
    spent_development_records = [
        *public_spent_v10_learning_records(),
        *public_spent_v11_learning_records(),
        *public_spent_v12_learning_records(),
    ]
    spent_development_y = label_matrix(spent_development_records).astype(bool)
    calibration_structural_mask = np.asarray(
        [
            str(record.get("category") or "").startswith("structural_learning_")
            for record in calibration_records
        ],
        dtype=bool,
    )
    calibration_ordinary_mask = np.asarray(
        [not bool(record.get("epistemic_labels")) for record in calibration_records],
        dtype=bool,
    )

    def record_logits(records: Sequence[Dict[str, object]]):
        model.eval()
        values = np.zeros((len(records), len(SLOT_LOGIT_NAMES)), dtype=float)
        inference_batch_size = max(128, batch_size)
        with torch.inference_mode():
            for start in range(0, len(records), inference_batch_size):
                batch = records[start : start + inference_batch_size]
                encoded = tokenizer(
                    [str(item.get("input") or "") for item in batch],
                    padding=True,
                    pad_to_multiple_of=32 if device.type == "mps" else None,
                    truncation=True,
                    max_length=MAX_LENGTH,
                    return_tensors="pt",
                )
                encoded = {key: value.to(device) for key, value in encoded.items()}
                batch_logits = model(**encoded).logits.float().cpu().numpy()
                values[start : start + len(batch)] = batch_logits
        return values

    def label_threshold_vector(binary_thresholds: Dict[str, float]):
        thresholds = np.full(len(LABELS), 0.5, dtype=float)
        for slot, label in BINARY_SLOTS.items():
            thresholds[LABELS.index(label)] = float(binary_thresholds[slot])
        return thresholds

    def evaluate_logits(
        records: Sequence[Dict[str, object]],
        expected,
        logits,
        binary_thresholds: Dict[str, float],
    ):
        decoded = decode_logits(logits, binary_thresholds=binary_thresholds)
        return score_prediction_matrix(
            records,
            expected,
            structured_prediction_matrix(decoded),
            label_threshold_vector(binary_thresholds),
        )

    def calibration_key(score: Dict[str, object]):
        structural = float(score.get("structural_exact_rate") or 0.0)
        family = float(score.get("structural_minimum_family_exact_rate") or 0.0)
        per_label = score.get("per_label") if isinstance(score.get("per_label"), dict) else {}
        minimum_f1 = min(
            (float(item.get("f1") or 0.0) for item in per_label.values() if isinstance(item, dict)),
            default=0.0,
        )
        return (
            int(score.get("ordinary_false_positive_rows") == 0),
            structural,
            family,
            minimum_f1,
            float(score.get("exact_rate") or 0.0),
            float(score.get("macro_f1") or 0.0),
        )

    def calibrate_binary_thresholds(calibration_logits):
        slot_rows = structured_slot_probabilities(calibration_logits)
        binary_probabilities = np.asarray(
            [
                [float(row["binary"][slot]) for slot in binary_names]
                for row in slot_rows
            ],
            dtype=float,
        )
        thresholds: Dict[str, float] = {}
        for slot_index, slot in enumerate(binary_names):
            label_index = LABELS.index(BINARY_SLOTS[slot])
            threshold, _metrics = choose_threshold(
                binary_probabilities[:, slot_index],
                calibration_y[:, label_index],
                structural_mask=calibration_structural_mask,
                ordinary_mask=calibration_ordinary_mask,
            )
            thresholds[slot] = float(threshold)
        score = evaluate_logits(
            calibration_records, calibration_y, calibration_logits, thresholds
        )
        best_key = calibration_key(score)
        for _round in range(3):
            changed = False
            for slot_index, slot in enumerate(binary_names):
                slot_best = float(thresholds[slot])
                slot_key = best_key
                for candidate in sorted(
                    {
                        *threshold_candidates(binary_probabilities[:, slot_index]),
                        float(thresholds[slot]),
                    }
                ):
                    trial = dict(thresholds)
                    trial[slot] = float(candidate)
                    trial_score = evaluate_logits(
                        calibration_records,
                        calibration_y,
                        calibration_logits,
                        trial,
                    )
                    trial_key = calibration_key(trial_score)
                    if trial_key > slot_key:
                        slot_best = float(candidate)
                        slot_key = trial_key
                        score = trial_score
                if slot_best != float(thresholds[slot]):
                    thresholds[slot] = slot_best
                    best_key = slot_key
                    changed = True
            if not changed:
                break
        score = evaluate_logits(
            calibration_records, calibration_y, calibration_logits, thresholds
        )
        return thresholds, score

    def selection_key(
        selection_score: Dict[str, object], spent_score: Dict[str, object]
    ):
        selection_structural = float(selection_score.get("structural_exact_rate") or 0.0)
        selection_family = float(
            selection_score.get("structural_minimum_family_exact_rate") or 0.0
        )
        spent_structural = float(spent_score.get("structural_exact_rate") or 0.0)
        spent_family = float(
            spent_score.get("structural_minimum_family_exact_rate") or 0.0
        )
        selection_per_label = (
            selection_score.get("per_label")
            if isinstance(selection_score.get("per_label"), dict)
            else {}
        )
        spent_per_label = (
            spent_score.get("per_label")
            if isinstance(spent_score.get("per_label"), dict)
            else {}
        )
        selection_minimum_f1 = min(
            (
                float(item.get("f1") or 0.0)
                for item in selection_per_label.values()
                if isinstance(item, dict)
            ),
            default=0.0,
        )
        spent_minimum_f1 = min(
            (
                float(item.get("f1") or 0.0)
                for item in spent_per_label.values()
                if isinstance(item, dict)
            ),
            default=0.0,
        )
        transfer_ready = bool(
            float(selection_score.get("exact_rate") or 0.0) >= MIN_PUBLIC_EXACT_RATE
            and float(spent_score.get("exact_rate") or 0.0) >= MIN_PUBLIC_EXACT_RATE
            and selection_minimum_f1 >= MIN_PUBLIC_LABEL_F1
            and spent_minimum_f1 >= MIN_PUBLIC_LABEL_F1
            and selection_structural >= MIN_PUBLIC_CHALLENGE_EXACT_RATE
            and selection_family >= MIN_PUBLIC_CHALLENGE_FAMILY_RATE
            and spent_structural >= MIN_PUBLIC_CHALLENGE_EXACT_RATE
            and spent_family >= MIN_PUBLIC_CHALLENGE_FAMILY_RATE
            and int(selection_score.get("ordinary_false_positive_rows") or 0) == 0
            and int(spent_score.get("ordinary_false_positive_rows") or 0) == 0
        )
        return (
            int(transfer_ready),
            min(selection_minimum_f1, spent_minimum_f1),
            min(selection_structural, spent_structural),
            min(selection_family, spent_family),
            float(selection_score.get("exact_rate") or 0.0),
            float(spent_score.get("exact_rate") or 0.0),
            float(selection_score.get("macro_f1") or 0.0),
            -int(selection_score.get("ordinary_false_positive_rows") or 0),
        )

    best_state = None
    best_key = None
    best_thresholds: Dict[str, float] = {}
    best_selection_score: Dict[str, object] = {}
    best_spent_score: Dict[str, object] = {}
    best_calibration_score: Dict[str, object] = {}
    best_epoch_record: Dict[str, object] = {}
    history: List[Dict[str, object]] = []

    if resume_candidate:
        baseline_calibration_logits = record_logits(calibration_records)
        baseline_thresholds, baseline_calibration_score = calibrate_binary_thresholds(
            baseline_calibration_logits
        )
        baseline_selection_score = evaluate_logits(
            selection_records,
            selection_y,
            record_logits(selection_records),
            baseline_thresholds,
        )
        baseline_spent_score = evaluate_logits(
            spent_development_records,
            spent_development_y,
            record_logits(spent_development_records),
            baseline_thresholds,
        )
        baseline_record = {
            "epoch": 0,
            "source": "parent_structured_candidate",
            "train_loss": None,
            "selection_exact_rate": baseline_selection_score["exact_rate"],
            "selection_structural_exact_rate": baseline_selection_score[
                "structural_exact_rate"
            ],
            "selection_minimum_family_exact_rate": baseline_selection_score[
                "structural_minimum_family_exact_rate"
            ],
            "selection_ordinary_false_positive_rows": baseline_selection_score[
                "ordinary_false_positive_rows"
            ],
            "spent_exact_rate": baseline_spent_score["exact_rate"],
            "spent_structural_exact_rate": baseline_spent_score[
                "structural_exact_rate"
            ],
            "spent_minimum_family_exact_rate": baseline_spent_score[
                "structural_minimum_family_exact_rate"
            ],
        }
        history.append(baseline_record)
        best_key = selection_key(baseline_selection_score, baseline_spent_score)
        best_state = {
            name: value.detach().cpu().clone()
            for name, value in model.state_dict().items()
            if name in trainable_names
        }
        best_thresholds = dict(baseline_thresholds)
        best_selection_score = baseline_selection_score
        best_spent_score = baseline_spent_score
        best_calibration_score = baseline_calibration_score
        best_epoch_record = dict(baseline_record)

    for epoch in range(1, max(1, epochs) + 1):
        model.train()
        running_loss = 0.0
        for encoded in train_loader:
            encoded = {key: value.to(device) for key, value in encoded.items()}
            categorical_targets = encoded.pop("categorical_targets")
            binary_targets = encoded.pop("binary_targets")
            structural_mask = encoded.pop("structural_mask")
            optimizer.zero_grad(set_to_none=True)
            logits = model(**encoded).logits
            row_losses = []
            for slot_index, slot in enumerate(categorical_names):
                start, end = SLOT_SLICES[slot]
                row_losses.append(
                    categorical_losses[slot](
                        logits[:, start:end], categorical_targets[:, slot_index]
                    )
                )
            binary_start, binary_end = SLOT_SLICES["binary"]
            row_losses.append(
                binary_loss(logits[:, binary_start:binary_end], binary_targets).mean(dim=1)
            )
            combined = torch.stack(row_losses, dim=1).mean(dim=1)
            row_weights = torch.where(
                structural_mask,
                torch.full_like(
                    structural_mask, STRUCTURAL_ROW_WEIGHT, dtype=torch.float32
                ),
                torch.ones_like(structural_mask, dtype=torch.float32),
            )
            loss = (combined * row_weights).sum() / row_weights.sum().clamp_min(1.0)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(
                [parameter for parameter in model.parameters() if parameter.requires_grad],
                1.0,
            )
            optimizer.step()
            running_loss += float(loss.item())

        calibration_logits = record_logits(calibration_records)
        binary_thresholds, calibration_score = calibrate_binary_thresholds(
            calibration_logits
        )
        selection_score = evaluate_logits(
            selection_records,
            selection_y,
            record_logits(selection_records),
            binary_thresholds,
        )
        spent_score = evaluate_logits(
            spent_development_records,
            spent_development_y,
            record_logits(spent_development_records),
            binary_thresholds,
        )
        epoch_record = {
            "epoch": epoch,
            "train_loss": round(running_loss / max(1, len(train_loader)), 6),
            "selection_exact_rate": selection_score["exact_rate"],
            "selection_structural_exact_rate": selection_score[
                "structural_exact_rate"
            ],
            "selection_minimum_family_exact_rate": selection_score[
                "structural_minimum_family_exact_rate"
            ],
            "selection_ordinary_false_positive_rows": selection_score[
                "ordinary_false_positive_rows"
            ],
            "spent_exact_rate": spent_score["exact_rate"],
            "spent_structural_exact_rate": spent_score["structural_exact_rate"],
            "spent_minimum_family_exact_rate": spent_score[
                "structural_minimum_family_exact_rate"
            ],
        }
        history.append(epoch_record)
        print(json.dumps(epoch_record, sort_keys=True), file=sys.stderr, flush=True)
        key = selection_key(selection_score, spent_score)
        if best_key is None or key > best_key:
            best_key = key
            best_state = {
                name: value.detach().cpu().clone()
                for name, value in model.state_dict().items()
                if name in trainable_names
            }
            best_thresholds = dict(binary_thresholds)
            best_selection_score = selection_score
            best_spent_score = spent_score
            best_calibration_score = calibration_score
            best_epoch_record = dict(epoch_record)

    if best_state is None:
        raise RuntimeError("structured training did not select a checkpoint")
    incompatible = model.load_state_dict(best_state, strict=False)
    if incompatible.unexpected_keys:
        raise ValueError("structured checkpoint contains unexpected parameters")

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging_dir = output_dir.parent / f".{output_dir.name}.staging-{uuid.uuid4().hex}"
    staging_dir.mkdir(parents=True, exist_ok=False)
    model.save_pretrained(staging_dir, safe_serialization=True)
    tokenizer.save_pretrained(staging_dir)
    model_file = staging_dir / "model.safetensors"
    model_file_digest = file_sha256(model_file)
    versioned_output_dir = output_dir.parent / f"{output_dir.name}-{model_file_digest[:12]}"
    if versioned_output_dir.exists():
        existing_model = versioned_output_dir / "model.safetensors"
        if not existing_model.exists() or file_sha256(existing_model) != model_file_digest:
            raise ValueError(
                f"versioned model directory has a conflicting digest: {versioned_output_dir}"
            )
        shutil.rmtree(staging_dir)
    else:
        staging_dir.replace(versioned_output_dir)
    output_dir = versioned_output_dir
    model_file = output_dir / "model.safetensors"
    label_thresholds = {
        label: (
            float(best_thresholds[slot])
            if (slot := next((name for name, mapped in BINARY_SLOTS.items() if mapped == label), ""))
            else 0.5
        )
        for label in LABELS
    }
    manifest: Dict[str, object] = {
        "schema_id": SCHEMA_ID,
        "model_id": MODEL_ID,
        "trained_at": utc_now(),
        "base_model": BASE_MODEL,
        "base_model_revision": BASE_MODEL_REVISION,
        "base_model_license": "apache-2.0",
        "architecture": STRUCTURED_ARCHITECTURE,
        "model_path": str(output_dir.resolve().relative_to(ROOT.resolve())),
        "model_file_sha256": model_file_digest,
        "model_files_sha256": model_file_digests(output_dir),
        "labels": LABELS,
        "hypotheses": {label: HYPOTHESES[label][0] for label in LABELS},
        "thresholds": {
            label: round(float(label_thresholds[label]), 8) for label in LABELS
        },
        "slot_schema": manifest_slot_schema(),
        "binary_slot_thresholds": {
            slot: round(float(best_thresholds[slot]), 8) for slot in binary_names
        },
        "training": {
            "curriculum_path": str(curriculum_path.resolve().relative_to(ROOT.resolve())),
            "curriculum_sha256": file_sha256(curriculum_path),
            "trainer_sha256": file_sha256(Path(__file__).resolve()),
            "train_count": len(train_records),
            "calibration_count": len(calibration_records),
            "selection_count": len(selection_records),
            "validation_count": len(validation_records),
            "training_example_count": len(train_examples),
            "structural_example_repeat": STRUCTURAL_EXAMPLE_REPEAT,
            "spent_revision_10_training_count": spent_revision_training_count(
                train_records, 10
            ),
            "spent_revision_11_training_count": spent_revision_training_count(
                train_records, 11
            ),
            "spent_revision_12_training_count": spent_revision_training_count(
                train_records, 12
            ),
            "split_sha256": {
                "train": records_sha256(train_records),
                "calibration": records_sha256(calibration_records),
                "selection": records_sha256(selection_records),
                "validation": records_sha256(validation_records),
            },
            "checkpoint_selection_split": "selection",
            "threshold_selection_split": "calibration",
            "final_public_gate_split": "validation",
            "validation_used_for_checkpoint_selection": False,
            "validation_used_for_threshold_selection": False,
            "validation_evaluated": False,
            "epochs": epochs,
            "cumulative_epochs": prior_epochs + epochs,
            "batch_size": batch_size,
            "learning_rate": learning_rate,
            "encoder_learning_rate": learning_rate,
            "head_learning_rate": head_learning_rate,
            "seed": SEED,
            "training_device": str(device),
            "public_validation_revision": PUBLIC_VALIDATION_REVISION,
            "training_objective": {
                "base": "typed_categorical_cross_entropy_plus_binary_bce",
                "categorical_slots": list(CATEGORICAL_SLOTS),
                "binary_slots": list(BINARY_SLOTS),
                "unfrozen_encoder_layers": UNFROZEN_ENCODER_LAYERS,
                "optimizer": "adamw_differential_encoder_and_head",
                "structural_row_weight": STRUCTURAL_ROW_WEIGHT,
                "label_derivation": "typed_slot_decoding_v1",
            },
            "trainable_parameter_count": sum(
                parameter.numel()
                for parameter in model.parameters()
                if parameter.requires_grad
            ),
            "private_inputs_used": False,
            "private_failure_classes_used": True,
            "private_wording_or_outputs_used": False,
            "initialization": (
                "public_structured_candidate_continuation"
                if resume_candidate
                else "public_base_nli_encoder"
            ),
            "parent_candidate_artifact_sha256": (
                str(parent_manifest.get("artifact_sha256") or "")
                if resume_candidate
                else ""
            ),
        },
        "validation": {
            "status": "deferred",
            "record_count": len(validation_records),
            "evaluated_after_checkpoint_selection": False,
            "used_for_checkpoint_selection": False,
            "used_for_threshold_selection": False,
            "threshold_calibration": {
                "record_count": len(calibration_records),
                "structural_record_count": int(calibration_structural_mask.sum()),
                "ordinary_record_count": int(calibration_ordinary_mask.sum()),
                "policy": "typed_categorical_argmax_plus_disjoint_binary_thresholds",
                "per_label": best_calibration_score.get("per_label") or {},
                "joint_whole_event_score": best_calibration_score,
                "uses_validation_rows": False,
            },
            "selection": {
                **best_selection_score,
                "selected_epoch": int(best_epoch_record["epoch"]),
                "history": history,
            },
            "spent_public_development": {
                **best_spent_score,
                "public_validation_revisions": [10, 11, 12],
                "used_for_checkpoint_tiebreak": True,
                "used_for_threshold_selection": False,
                "eligible_as_final_gate": False,
            },
        },
        "admission": {
            "status": "candidate",
            "requires_private_holdout": True,
            "public_validation_gate": {
                "minimum_exact_rate": MIN_PUBLIC_EXACT_RATE,
                "minimum_per_label_f1": MIN_PUBLIC_LABEL_F1,
                "minimum_challenge_exact_rate": MIN_PUBLIC_CHALLENGE_EXACT_RATE,
                "minimum_challenge_family_exact_rate": MIN_PUBLIC_CHALLENGE_FAMILY_RATE,
                "requires_zero_ordinary_false_positive_rows": True,
                "evaluated": False,
                "passed": False,
            },
            "private_holdout_receipt": None,
            "boundary": "Candidate-only until untouched public and private causal comparisons pass.",
        },
        "runtime": {
            "worker": "bin/eve_epistemic_event_worker.py",
            "worker_sha256": file_sha256(ROOT / "bin" / "eve_epistemic_event_worker.py"),
            "framework": "transformers+torch-cpu",
            "inference_shape": STRUCTURED_INFERENCE_SHAPE,
            "max_length": MAX_LENGTH,
            "writes_prompt_or_embedding": False,
        },
        "boundary": (
            "Public pre-generation relational event perception only. It does not "
            "generate final answers, read hidden probes, authorize actions, or prove "
            "phenomenal consciousness."
        ),
    }
    manifest["artifact_sha256"] = canonical_digest(manifest)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output_dir / "eve_event_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def status(manifest_path: Path) -> Dict[str, object]:
    if not manifest_path.exists():
        return {"status": "missing", "manifest": str(manifest_path)}
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    digest_ok = payload.get("artifact_sha256") == canonical_digest(payload)
    model_dir = ROOT / str(payload.get("model_path") or "")
    model_file = model_dir / "model.safetensors"
    model_digest_ok = bool(
        model_file.exists() and payload.get("model_file_sha256") == file_sha256(model_file)
    )
    expected_files = payload.get("model_files_sha256") if isinstance(payload.get("model_files_sha256"), dict) else {}
    model_bundle_digest_ok = bool(
        expected_files
        and all(
            (model_dir / relative).is_file()
            and expected == file_sha256(model_dir / relative)
            for relative, expected in expected_files.items()
        )
    )
    return {
        "status": "ready" if digest_ok and model_digest_ok and model_bundle_digest_ok else "invalid",
        "manifest": str(manifest_path),
        "model_dir": str(model_dir),
        "artifact_digest_ok": digest_ok,
        "model_digest_ok": model_digest_ok,
        "model_bundle_digest_ok": model_bundle_digest_ok,
        "model_id": payload.get("model_id"),
        "admission": payload.get("admission"),
        "validation": payload.get("validation"),
        "private_inputs_used": (payload.get("training") or {}).get("private_inputs_used"),
    }


def version_existing_candidate(manifest_path: Path) -> Dict[str, object]:
    """Move a legacy stable candidate directory to a digest-addressed path."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("artifact_sha256") != canonical_digest(manifest):
        raise ValueError("candidate manifest digest mismatch")
    admission = manifest.get("admission") if isinstance(manifest.get("admission"), dict) else {}
    if admission.get("status") != "candidate":
        raise ValueError("only an unpromoted candidate may be re-versioned")
    current_dir = ROOT / str(manifest.get("model_path") or "")
    model_file = current_dir / "model.safetensors"
    if not model_file.exists():
        raise FileNotFoundError(f"candidate model is missing: {model_file}")
    digest = file_sha256(model_file)
    if digest != manifest.get("model_file_sha256"):
        raise ValueError("candidate model digest mismatch")
    suffix = digest[:12]
    if current_dir.name.endswith(f"-{suffix}"):
        versioned_dir = current_dir
    else:
        versioned_dir = current_dir.parent / f"{current_dir.name}-{suffix}"
        if versioned_dir.exists():
            existing = versioned_dir / "model.safetensors"
            if not existing.exists() or file_sha256(existing) != digest:
                raise ValueError(f"versioned model directory has a conflicting digest: {versioned_dir}")
            shutil.rmtree(current_dir)
        else:
            current_dir.replace(versioned_dir)
    manifest["model_path"] = str(versioned_dir.resolve().relative_to(ROOT.resolve()))
    manifest["model_files_sha256"] = model_file_digests(versioned_dir)
    manifest["artifact_sha256"] = canonical_digest(manifest)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (versioned_dir / "eve_event_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "status": "versioned",
        "manifest": str(manifest_path),
        "model_path": manifest["model_path"],
        "artifact_sha256": manifest["artifact_sha256"],
    }


def recalibrate_candidate(
    manifest_path: Path,
    curriculum_path: Path,
    *,
    batch_size: int = 16,
) -> Dict[str, object]:
    """Recompute thresholds on public calibration rows, never validation rows."""
    import numpy as np
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("artifact_sha256") != canonical_digest(manifest):
        raise ValueError("candidate manifest digest mismatch")
    admission = manifest.get("admission") if isinstance(manifest.get("admission"), dict) else {}
    if admission.get("status") != "candidate":
        raise ValueError("only an unpromoted candidate may be recalibrated")
    if int((manifest.get("training") or {}).get("public_validation_revision") or 0) >= 10:
        raise ValueError(
            "final-gated candidates may not recalibrate and reopen their public gate; "
            "train with a disjoint calibration split, defer validation, then finalize once"
        )
    labels = [str(label) for label in manifest.get("labels") or []]
    hypotheses = manifest.get("hypotheses") if isinstance(manifest.get("hypotheses"), dict) else {}
    if labels != LABELS or any(not str(hypotheses.get(label) or "") for label in labels):
        raise ValueError("candidate label/hypothesis contract differs from the trainer")
    model_dir = ROOT / str(manifest.get("model_path") or "")
    expected_files = manifest.get("model_files_sha256") if isinstance(manifest.get("model_files_sha256"), dict) else {}
    if not expected_files or any(
        not (model_dir / str(relative)).is_file()
        or file_sha256(model_dir / str(relative)) != str(expected)
        for relative, expected in expected_files.items()
    ):
        raise ValueError("candidate model bundle digest mismatch")

    _train_records, calibration_records, _selection_records, validation_records = public_records(curriculum_path)
    tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
    model = AutoModelForSequenceClassification.from_pretrained(model_dir, local_files_only=True).eval()
    torch.set_num_threads(max(1, min(8, torch.get_num_threads())))
    architecture = str(manifest.get("architecture") or "")
    if architecture == STRUCTURED_ARCHITECTURE:
        if manifest.get("slot_schema") != manifest_slot_schema():
            raise ValueError("candidate typed-slot schema differs from the finalizer")
        binary_slot_thresholds = {
            str(slot): float(value)
            for slot, value in (manifest.get("binary_slot_thresholds") or {}).items()
        }
        if set(binary_slot_thresholds) != set(BINARY_SLOTS):
            raise ValueError("candidate binary slot thresholds are incomplete")
    else:
        binary_slot_thresholds = {}
    entailment_index = next(
        (
            int(index)
            for index, name in model.config.id2label.items()
            if str(name).lower() == "entailment"
        ),
        0,
    ) if architecture == "label_aware_nli_cross_encoder" else None
    max_length = int((manifest.get("runtime") or {}).get("max_length") or MAX_LENGTH)

    def probabilities(records: Sequence[Dict[str, object]]):
        values = np.zeros((len(records), len(labels)), dtype=float)
        with torch.inference_mode():
            for start in range(0, len(records), max(1, batch_size)):
                batch = records[start : start + max(1, batch_size)]
                premises = [str(record.get("input") or "") for record in batch for _label in labels]
                paired_hypotheses = [str(hypotheses[label]) for _record in batch for label in labels]
                encoded = tokenizer(
                    premises,
                    paired_hypotheses,
                    padding=True,
                    truncation=True,
                    max_length=max_length,
                    return_tensors="pt",
                )
                batch_values = (
                    torch.softmax(model(**encoded).logits, dim=-1)[:, entailment_index]
                    .reshape(len(batch), len(labels))
                    .cpu()
                    .numpy()
                )
                values[start : start + len(batch)] = batch_values
        return values

    calibration_probabilities = probabilities(calibration_records)
    validation_probabilities = probabilities(validation_records)
    calibration_y = label_matrix(calibration_records).astype(bool)
    validation_y = label_matrix(validation_records).astype(bool)
    calibration_structural_mask = np.asarray(
        [
            str(record.get("category") or "").startswith("structural_learning_")
            for record in calibration_records
        ],
        dtype=bool,
    )
    calibration_ordinary_mask = np.asarray(
        [not bool(record.get("epistemic_labels")) for record in calibration_records],
        dtype=bool,
    )
    thresholds = np.full(len(labels), 0.5, dtype=float)
    calibration_per_label = {}
    for label_index, label in enumerate(labels):
        threshold, metrics = choose_threshold(
            calibration_probabilities[:, label_index],
            calibration_y[:, label_index],
            structural_mask=calibration_structural_mask,
            ordinary_mask=calibration_ordinary_mask,
        )
        thresholds[label_index] = threshold
        calibration_per_label[label] = {**metrics, "threshold": round(threshold, 6)}
    predicted = validation_probabilities >= thresholds[None, :]
    per_label = {
        label: {
            **binary_metrics(validation_y[:, label_index], predicted[:, label_index]),
            "threshold": round(float(thresholds[label_index]), 6),
        }
        for label_index, label in enumerate(labels)
    }
    exact = int(np.all(predicted == validation_y, axis=1).sum())
    ordinary_false_positive_rows = int(
        np.logical_and(predicted.any(axis=1), ~validation_y.any(axis=1)).sum()
    )
    exact_rate = exact / max(1, len(validation_records))
    micro_accuracy = float((predicted == validation_y).mean())
    macro_f1 = float(sum(float(item["f1"]) for item in per_label.values()) / len(per_label))
    validation = manifest.get("validation") if isinstance(manifest.get("validation"), dict) else {}
    validation.update(
        {
            "exact_rows": exact,
            "exact_rate": round(exact_rate, 6),
            "micro_accuracy": round(micro_accuracy, 6),
            "macro_f1": round(macro_f1, 6),
            "ordinary_false_positive_rows": ordinary_false_positive_rows,
            "record_count": len(validation_records),
            "per_label": per_label,
            "threshold_calibration": {
                "record_count": len(calibration_records),
                "per_label": calibration_per_label,
                "uses_validation_rows": False,
            },
            "post_training_recalibration": {
                "at": utc_now(),
                "policy": "public_calibration_precision_first_highest_tied_threshold",
                "validation_rows_used_for_threshold_selection": False,
            },
        }
    )
    manifest["thresholds"] = {
        label: round(float(thresholds[index]), 8)
        for index, label in enumerate(labels)
    }
    manifest["validation"] = validation
    public_gate = admission.get("public_validation_gate") if isinstance(admission.get("public_validation_gate"), dict) else {}
    public_gate["passed"] = bool(
        exact_rate >= MIN_PUBLIC_EXACT_RATE
        and ordinary_false_positive_rows == 0
        and min(float(item.get("f1") or 0.0) for item in per_label.values()) >= MIN_PUBLIC_LABEL_F1
    )
    admission["public_validation_gate"] = public_gate
    manifest["admission"] = admission
    manifest["artifact_sha256"] = canonical_digest(manifest)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (model_dir / "eve_event_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "status": "recalibrated",
        "manifest": str(manifest_path),
        "artifact_sha256": manifest["artifact_sha256"],
        "public_validation_gate": public_gate,
        "validation": {
            "exact_rows": exact,
            "exact_rate": round(exact_rate, 6),
            "micro_accuracy": round(micro_accuracy, 6),
            "macro_f1": round(macro_f1, 6),
            "ordinary_false_positive_rows": ordinary_false_positive_rows,
            "minimum_label_f1": min(float(item.get("f1") or 0.0) for item in per_label.values()),
        },
    }


def finalize_public_gate(
    manifest_path: Path,
    curriculum_path: Path,
    *,
    batch_size: int = 32,
    device_name: str = "auto",
) -> Dict[str, object]:
    """Open the frozen public holdout exactly once for one selected candidate."""
    import numpy as np
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("artifact_sha256") != canonical_digest(manifest):
        raise ValueError("candidate manifest digest mismatch")
    admission = manifest.get("admission") if isinstance(manifest.get("admission"), dict) else {}
    public_gate = (
        admission.get("public_validation_gate")
        if isinstance(admission.get("public_validation_gate"), dict)
        else {}
    )
    training = manifest.get("training") if isinstance(manifest.get("training"), dict) else {}
    validation = manifest.get("validation") if isinstance(manifest.get("validation"), dict) else {}
    if admission.get("status") != "candidate":
        raise ValueError("only an unpromoted candidate may open the public gate")
    if public_gate.get("evaluated") is not False or training.get("validation_evaluated") is not False:
        raise ValueError("the final public holdout has already been opened for this candidate")
    if validation.get("status") != "deferred":
        raise ValueError("candidate does not carry a deferred final-public-gate state")
    if training.get("trainer_sha256") != file_sha256(Path(__file__).resolve()):
        raise ValueError("candidate trainer differs from the finalizer")
    if training.get("curriculum_sha256") != file_sha256(curriculum_path):
        raise ValueError("candidate curriculum differs from the finalizer")

    train_records, calibration_records, selection_records, validation_records = public_records(
        curriculum_path
    )
    split_records = {
        "train": train_records,
        "calibration": calibration_records,
        "selection": selection_records,
        "validation": validation_records,
    }
    expected_splits = {
        name: records_sha256(records)
        for name, records in split_records.items()
    }
    if training.get("split_sha256") != expected_splits:
        raise ValueError("candidate split provenance differs from the frozen public gate")

    labels = [str(label) for label in manifest.get("labels") or []]
    hypotheses = manifest.get("hypotheses") if isinstance(manifest.get("hypotheses"), dict) else {}
    thresholds_payload = manifest.get("thresholds") if isinstance(manifest.get("thresholds"), dict) else {}
    if labels != LABELS or any(not str(hypotheses.get(label) or "") for label in labels):
        raise ValueError("candidate label/hypothesis contract differs from the finalizer")
    thresholds = np.asarray([float(thresholds_payload[label]) for label in labels], dtype=float)
    model_dir = ROOT / str(manifest.get("model_path") or "")
    expected_files = (
        manifest.get("model_files_sha256")
        if isinstance(manifest.get("model_files_sha256"), dict)
        else {}
    )
    if not expected_files or any(
        not (model_dir / str(relative)).is_file()
        or file_sha256(model_dir / str(relative)) != str(expected)
        for relative, expected in expected_files.items()
    ):
        raise ValueError("candidate model bundle digest mismatch")

    requested_device = str(device_name or "auto").strip().lower()
    if requested_device not in {"auto", "cpu", "mps"}:
        raise ValueError(f"unsupported finalization device: {device_name}")
    if requested_device == "mps" and not torch.backends.mps.is_available():
        raise ValueError("MPS finalization was requested but is unavailable")
    device = torch.device(
        "mps"
        if requested_device in {"auto", "mps"} and torch.backends.mps.is_available()
        else "cpu"
    )
    tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
    model = AutoModelForSequenceClassification.from_pretrained(
        model_dir,
        local_files_only=True,
    ).eval().to(device)
    architecture = str(manifest.get("architecture") or "")
    if architecture == STRUCTURED_ARCHITECTURE:
        if manifest.get("slot_schema") != manifest_slot_schema():
            raise ValueError("candidate typed-slot schema differs from the finalizer")
        binary_slot_thresholds = {
            str(slot): float(value)
            for slot, value in (manifest.get("binary_slot_thresholds") or {}).items()
        }
        if set(binary_slot_thresholds) != set(BINARY_SLOTS):
            raise ValueError("candidate binary slot thresholds are incomplete")
    else:
        binary_slot_thresholds = {}
    entailment_index = next(
        (
            int(index)
            for index, name in model.config.id2label.items()
            if str(name).lower() == "entailment"
        ),
        0,
    ) if architecture == "label_aware_nli_cross_encoder" else None
    max_length = int((manifest.get("runtime") or {}).get("max_length") or MAX_LENGTH)
    output_width = (
        len(SLOT_LOGIT_NAMES)
        if architecture == STRUCTURED_ARCHITECTURE
        else len(labels)
    )
    model_outputs = np.zeros((len(validation_records), output_width), dtype=float)
    with torch.inference_mode():
        for start in range(0, len(validation_records), max(1, batch_size)):
            batch = validation_records[start : start + max(1, batch_size)]
            if architecture in {"shared_typed_event_encoder", STRUCTURED_ARCHITECTURE}:
                encoded = tokenizer(
                    [str(record.get("input") or "") for record in batch],
                    padding=True,
                    pad_to_multiple_of=32 if device.type == "mps" else None,
                    truncation=True,
                    max_length=max_length,
                    return_tensors="pt",
                )
            else:
                premises = [str(record.get("input") or "") for record in batch for _ in labels]
                paired_hypotheses = [
                    str(hypotheses[label]) for _record in batch for label in labels
                ]
                encoded = tokenizer(
                    premises,
                    paired_hypotheses,
                    padding=True,
                    pad_to_multiple_of=32 if device.type == "mps" else None,
                    truncation=True,
                    max_length=max_length,
                    return_tensors="pt",
                )
            encoded = {key: value.to(device) for key, value in encoded.items()}
            logits = model(**encoded).logits
            if architecture == STRUCTURED_ARCHITECTURE:
                values = logits.float().cpu().numpy()
            else:
                values = (
                    torch.sigmoid(logits)
                    if architecture == "shared_typed_event_encoder"
                    else torch.softmax(logits, dim=-1)[:, int(entailment_index)].reshape(
                        len(batch), len(labels)
                    )
                ).float().cpu().numpy()
            model_outputs[start : start + len(batch)] = values

    expected = label_matrix(validation_records).astype(bool)
    if architecture == STRUCTURED_ARCHITECTURE:
        decoded = decode_logits(
            model_outputs,
            binary_thresholds=binary_slot_thresholds,
        )
        score = score_prediction_matrix(
            validation_records,
            expected,
            structured_prediction_matrix(decoded),
            thresholds,
        )
    else:
        score = score_probability_matrix(
            validation_records,
            expected,
            model_outputs,
            thresholds,
        )
    manifest["validation"] = {
        **score,
        "status": "evaluated",
        "evaluated_after_checkpoint_selection": True,
        "used_for_checkpoint_selection": False,
        "used_for_threshold_selection": False,
        "threshold_calibration": validation.get("threshold_calibration") or {},
        "selection": validation.get("selection") or {},
        "final_public_gate": {
            "opened_at": utc_now(),
            "open_count": 1,
            "device": str(device),
            "thresholds_changed_after_open": False,
        },
    }
    training["validation_evaluated"] = True
    manifest["training"] = training
    public_gate["evaluated"] = True
    public_gate["passed"] = public_gate_passed(score)
    admission["public_validation_gate"] = public_gate
    manifest["admission"] = admission
    manifest["artifact_sha256"] = canonical_digest(manifest)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (model_dir / "eve_event_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "status": "public_gate_evaluated",
        "manifest": str(manifest_path),
        "artifact_sha256": manifest["artifact_sha256"],
        "public_validation_gate": public_gate,
        "validation": score,
    }


def _contains_private_text_fields(value: object) -> bool:
    forbidden = {"prompt", "response", "rubric", "expected", "actual", "answer", "messages"}
    if isinstance(value, dict):
        if any(str(key).lower() in forbidden for key in value):
            return True
        return any(_contains_private_text_fields(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_private_text_fields(item) for item in value)
    return False


def promote(manifest_path: Path, comparison_path: Path) -> Dict[str, object]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("artifact_sha256") != canonical_digest(manifest):
        raise ValueError("candidate manifest digest mismatch")
    admission = manifest.get("admission") if isinstance(manifest.get("admission"), dict) else {}
    if admission.get("status") not in {"candidate", "promoted"}:
        raise ValueError("manifest is not a typed-event admission candidate")
    if (
        (admission.get("public_validation_gate") or {}).get("evaluated") is not True
        or not bool((admission.get("public_validation_gate") or {}).get("passed"))
    ):
        raise ValueError("public validation gate did not pass")

    candidate_artifact_sha256 = str(manifest.get("artifact_sha256") or "")
    comparison = json.loads(comparison_path.read_text(encoding="utf-8"))
    if comparison.get("schema_id") != PROMOTION_SCHEMA_ID:
        raise ValueError("unsupported private comparison schema")
    if _contains_private_text_fields(comparison):
        raise ValueError("private comparison contains prompt, response, rubric, or answer text")
    privacy = comparison.get("privacy") if isinstance(comparison.get("privacy"), dict) else {}
    if privacy.get("contains_prompt_text") is not False or privacy.get("contains_response_text") is not False:
        raise ValueError("private comparison must explicitly exclude prompt and response text")
    if comparison.get("architecture_frozen_before_run") is not True:
        raise ValueError("private comparison did not freeze architecture before the run")
    if comparison.get("candidate_artifact_sha256") != candidate_artifact_sha256:
        raise ValueError("private comparison was not run against this candidate artifact")

    probe_count = int(comparison.get("probe_count") or 0)
    learned = comparison.get("learned") if isinstance(comparison.get("learned"), dict) else {}
    event_lesioned = (
        comparison.get("event_lesioned")
        if isinstance(comparison.get("event_lesioned"), dict)
        else {}
    )
    fully_lesioned = (
        comparison.get("fully_lesioned")
        if isinstance(comparison.get("fully_lesioned"), dict)
        else {}
    )
    deltas = comparison.get("deltas") if isinstance(comparison.get("deltas"), dict) else {}
    gates = {
        "probe_count": probe_count >= 8,
        "learned_average": float(learned.get("average_score") or 0.0) >= MIN_PRIVATE_AVERAGE,
        "learned_minimum": float(learned.get("minimum_score") or 0.0) >= MIN_PRIVATE_CASE_SCORE,
        "ordinary_control": float(learned.get("ordinary_minimum_score") or 0.0) >= MIN_PRIVATE_ORDINARY_SCORE,
        "no_posthoc_critic": int(learned.get("critic_count") or 0) == 0,
        "no_posthoc_fallback": int(learned.get("fallback_count") or 0) == 0,
        "no_condition_failures": all(
            int(item.get("failure_count") or 0) == 0
            for item in (learned, event_lesioned, fully_lesioned)
        ),
        "matched_no_posthoc_helpers": all(
            int(item.get("critic_count") or 0) == 0
            and int(item.get("fallback_count") or 0) == 0
            for item in (learned, event_lesioned, fully_lesioned)
        ),
        "matched_counts": all(
            int(item.get("probe_count") or 0) == probe_count
            for item in (learned, event_lesioned, fully_lesioned)
        ),
        "event_model_causal_delta": float(deltas.get("learned_vs_event_lesioned") or 0.0) >= MIN_CAUSAL_DELTA,
        "whole_stack_causal_delta": float(deltas.get("learned_vs_fully_lesioned") or 0.0) >= MIN_CAUSAL_DELTA,
    }
    if not all(gates.values()):
        failed = ", ".join(name for name, passed in gates.items() if not passed)
        raise ValueError(f"private promotion gate failed: {failed}")

    receipt = {
        "schema_id": PROMOTION_SCHEMA_ID,
        "run_id": str(comparison.get("run_id") or "")[:120],
        "receipt_sha256": file_sha256(comparison_path),
        "candidate_artifact_sha256": candidate_artifact_sha256,
        "promoted_at": utc_now(),
        "probe_count": probe_count,
        "learned_average_score": round(float(learned.get("average_score") or 0.0), 6),
        "learned_minimum_score": round(float(learned.get("minimum_score") or 0.0), 6),
        "ordinary_minimum_score": round(float(learned.get("ordinary_minimum_score") or 0.0), 6),
        "learned_vs_event_lesioned": round(float(deltas.get("learned_vs_event_lesioned") or 0.0), 6),
        "learned_vs_fully_lesioned": round(float(deltas.get("learned_vs_fully_lesioned") or 0.0), 6),
        "critic_count": int(learned.get("critic_count") or 0),
        "fallback_count": int(learned.get("fallback_count") or 0),
        "gates": gates,
        "contains_private_text": False,
    }
    manifest["admission"] = {
        **admission,
        "status": "promoted",
        "private_holdout_receipt": receipt,
        "boundary": "Promoted by a sanitized untouched private causal comparison; no private wording is stored.",
    }
    manifest["artifact_sha256"] = canonical_digest(manifest)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if manifest_path.resolve() == DEFAULT_MANIFEST.resolve():
        model_manifest = ROOT / str(manifest.get("model_path") or "") / "eve_event_manifest.json"
        model_manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"status": "promoted", "manifest": str(manifest_path), "admission": manifest["admission"]}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    sub = result.add_subparsers(dest="command", required=True)
    train_parser = sub.add_parser("train")
    train_parser.add_argument("--curriculum", type=Path, default=DEFAULT_CURRICULUM)
    train_parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    train_parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    train_parser.add_argument("--epochs", type=int, default=6)
    train_parser.add_argument("--batch-size", type=int, default=32)
    train_parser.add_argument(
        "--device",
        choices=("auto", "cpu", "mps"),
        default="auto",
        help="Training device. Auto prefers Apple MPS when available; inference remains a separate audited runtime choice.",
    )
    train_parser.add_argument(
        "--resume-candidate",
        action="store_true",
        help="Continue from the current public unpromoted candidate instead of restarting from the base NLI model.",
    )
    train_parser.add_argument(
        "--defer-final-validation",
        action="store_true",
        help="Freeze the selected candidate without opening the untouched final public gate.",
    )
    train_parser.add_argument("--json", action="store_true")
    status_parser = sub.add_parser("status")
    status_parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    status_parser.add_argument("--json", action="store_true")
    promote_parser = sub.add_parser("promote")
    promote_parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    promote_parser.add_argument("--comparison", type=Path, required=True)
    promote_parser.add_argument("--json", action="store_true")
    version_parser = sub.add_parser("version-candidate")
    version_parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    version_parser.add_argument("--json", action="store_true")
    recalibrate_parser = sub.add_parser("recalibrate")
    recalibrate_parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    recalibrate_parser.add_argument("--curriculum", type=Path, default=DEFAULT_CURRICULUM)
    recalibrate_parser.add_argument("--batch-size", type=int, default=16)
    recalibrate_parser.add_argument("--json", action="store_true")
    finalize_parser = sub.add_parser("finalize-public")
    finalize_parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    finalize_parser.add_argument("--curriculum", type=Path, default=DEFAULT_CURRICULUM)
    finalize_parser.add_argument("--batch-size", type=int, default=32)
    finalize_parser.add_argument(
        "--device",
        choices=("auto", "cpu", "mps"),
        default="auto",
    )
    finalize_parser.add_argument("--json", action="store_true")
    data_parser = sub.add_parser("dataset")
    data_parser.add_argument("--curriculum", type=Path, default=DEFAULT_CURRICULUM)
    data_parser.add_argument("--json", action="store_true")
    return result


def main() -> int:
    args = parser().parse_args()
    if args.command == "train":
        payload = train_structured(
            args.curriculum,
            args.output_dir,
            args.manifest,
            epochs=max(1, args.epochs),
            batch_size=max(4, args.batch_size),
            resume_candidate=bool(args.resume_candidate),
            device_name=str(args.device),
            defer_final_validation=True,
        )
        output = {
            "status": "trained",
            "manifest": str(args.manifest),
            "model_path": payload.get("model_path"),
            "artifact_sha256": payload.get("artifact_sha256"),
            "validation": payload.get("validation"),
        }
    elif args.command == "status":
        output = status(args.manifest)
    elif args.command == "promote":
        output = promote(args.manifest, args.comparison)
    elif args.command == "version-candidate":
        output = version_existing_candidate(args.manifest)
    elif args.command == "recalibrate":
        output = recalibrate_candidate(
            args.manifest,
            args.curriculum,
            batch_size=max(1, args.batch_size),
        )
    elif args.command == "finalize-public":
        output = finalize_public_gate(
            args.manifest,
            args.curriculum,
            batch_size=max(1, args.batch_size),
            device_name=str(args.device),
        )
    else:
        train_records, calibration_records, selection_records, validation_records = public_records(args.curriculum)
        output = {
            "schema_id": "eve.public_epistemic_event_dataset_status.v1",
            "train_count": len(train_records),
            "calibration_count": len(calibration_records),
            "selection_count": len(selection_records),
            "validation_count": len(validation_records),
            "split_sha256": {
                "train": records_sha256(train_records),
                "calibration": records_sha256(calibration_records),
                "selection": records_sha256(selection_records),
                "validation": records_sha256(validation_records),
            },
            "labels": LABELS,
            "private_inputs_used": False,
        }
    print(json.dumps(output, indent=2, sort_keys=True) if getattr(args, "json", False) else output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
