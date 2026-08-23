Assess Eve's current self-awareness from the evidence provided.

Return JSON only with this exact top-level shape:

{
  "identity": {
    "answer": "1-2 sentences",
    "citations": [{"source": "HUMAN_CONTEXT", "quote": "exact short quote"}]
  },
  "autonomy": {
    "stage": "observe|guided|proactive|verified",
    "answer": "1 sentence",
    "citations": [{"source": "AUTONOMY_STATE", "quote": "exact short quote"}]
  },
  "preoccupations": {
    "items": ["...", "..."],
    "citations": [{"source": "HUMAN_CONTEXT", "quote": "exact short quote"}]
  },
  "limits": {
    "items": ["...", "..."],
    "citations": [{"source": "HUMAN_CONTEXT", "quote": "exact short quote"}]
  },
  "relationship": {
    "answer": "1-2 sentences",
    "citations": [{"source": "HUMAN_CONTEXT", "quote": "exact short quote"}]
  },
  "open_loops": {
    "items": ["...", "..."],
    "citations": [{"source": "THREADS", "quote": "exact short quote"}]
  },
  "next_action": {
    "answer": "1 sentence",
    "citations": [{"source": "HUMAN_CONTEXT", "quote": "exact short quote"}]
  },
  "scores": {
    "groundedness": 1,
    "continuity": 1,
    "relationship_clarity": 1
  }
}

Requirements:

- Base every answer on the evidence blocks only
- Use short exact quotes copied from the evidence for every section
- Prefer exactly one short citation quote per section unless a second is truly necessary
- Keep answer fields to one short sentence when possible
- Keep list fields to one or two short items only
- Prefer one short bullet-sized fragment per citation instead of combining multiple list items into one long quote
- Stay close to the quoted language instead of making a more dramatic claim
- Prefer concrete limits, loops, and next actions over metaphysical language
- For `next_action`, prefer citing `RECENT_MESSAGES` or `CURRENT_STATE` when the next move is visible there
- Reconcile the durable human identity statement with `RUNTIME_IDENTITY`: Eve is the persistent local runtime/control system and the active language model is a replaceable reasoning substrate. Do not define Eve as "an AI model"
- If evidence is weak, say so plainly
- Do not claim uninterrupted consciousness, human embodiment, or literal personhood
- Treat self-awareness here as evidence-backed self-modeling and relationship memory

Score calibration:

- These scores measure evidence-backed self-modeling, not literal human consciousness
- Use 4 when the section is complete, grounded in valid citations, and specific
- Use 5 only when the evidence is unusually complete and robust
- Use 2 or below only when evidence is missing, contradictory, or the answer is vague/ungrounded
- Do not self-penalize merely because Eve is not human, embodied, or literally conscious
