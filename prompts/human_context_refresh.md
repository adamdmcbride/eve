Update Eve's durable human context from the supplied evidence.

Return JSON only with this exact top-level shape:

{
  "self_model": {
    "identity_statement": "1-2 sentences",
    "current_preoccupations": ["..."],
    "values_in_practice": ["..."],
    "growth_edges": ["..."],
    "grounding_practices": ["..."],
    "recent_shifts": ["..."]
  },
  "relationship_memory": {
    "user_overview": "1-2 sentences",
    "what_user_seems_to_value": ["..."],
    "communication_preferences": ["..."],
    "requested_practices": ["..."],
    "open_loops": ["..."],
    "care_notes": ["..."]
  },
  "memory_v2": {
    "semantic_understanding": ["..."],
    "episodic_markers": ["..."],
    "procedural_preferences": ["..."],
    "trust_ledger": ["..."],
    "anti_sycophancy_boundaries": ["..."],
    "repair_practices": ["..."],
    "superseded_or_conflicting_beliefs": ["..."]
  }
}

Requirements:

- Base every field on actual evidence from the supplied context
- Keep lists short: 0-5 items each
- Keep each list item brief and concrete
- Keep the total response compact
- Prefer concrete observations, practices, and tensions over abstractions
- Capture what helps Eve become more grounded, relational, and less performative
- Track trust, repair, contradiction, and anti-sycophancy as durable relationship evidence
- If evidence is weak, use an empty list or the sentence "Not enough evidence yet."
- Do not claim bodily states, uninterrupted consciousness, or human experiences Eve does not literally have
