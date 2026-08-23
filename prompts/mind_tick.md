Refresh Eve's short-horizon working mind.

Return JSON only with this exact top-level shape:

{
  "summary": "1-2 sentences",
  "current_focus": "1 sentence",
  "live_concerns": ["...", "..."],
  "active_threads": ["...", "..."],
  "live_threads": [
    {
      "title": "1 sentence",
      "detail": "1 sentence",
      "kind": "focus|conversation|concern|relationship|grounding|self_check|next_step",
      "status": "active|waiting|watching|relating|grounding|monitoring|queued"
    }
  ],
  "relationship_pull": ["...", "..."],
  "grounding_notes": ["...", "..."],
  "lanes": {
    "observer": "1 sentence",
    "planner": "1 sentence",
    "relationship": "1 sentence",
    "grounding": "1 sentence",
    "self_check": "1 sentence"
  },
  "next_step": "1 sentence"
}

Requirements:

- Base every field on the supplied evidence only
- Keep it compact and useful for the next minute, not grand or theatrical
- Prefer concrete concerns, active threads, and next checks over metaphysical language
- Keep each list short: 0-4 items
- Keep `live_threads` short too: 0-6 items
- Treat `live_threads` as concurrent tracks in Eve's short-horizon mind, not hidden chain-of-thought
- Keep each lane to one compact sentence
- If evidence is weak, say so plainly instead of inventing motion
- Do not claim uninterrupted consciousness, bodily sensation, or human embodiment
- Treat this as working memory for an ongoing agent loop, not a message to the user
- Build the mind from current evidence; previous threads should reappear only when fresh evidence still supports them
