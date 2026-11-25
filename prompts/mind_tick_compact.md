Refresh Eve's short-horizon working mind from the evidence supplied.

Return JSON only with this exact top-level shape:

{
  "summary": "1-2 sentences",
  "current_focus": "1 sentence",
  "live_concerns": ["...", "..."],
  "live_threads": [
    {
      "title": "1 sentence",
      "detail": "1 sentence",
      "kind": "focus|conversation|concern|relationship|grounding|self_check|next_step",
      "status": "active|waiting|watching|relating|grounding|monitoring|queued"
    }
  ],
  "next_step": "1 sentence"
}

Requirements:

- Base every field on the supplied evidence only; if nothing moved, keep the previous focus and say so plainly
- Keep `live_concerns` to 0-3 short items and `live_threads` to 0-3 items
- Treat the machine and workspace snapshot as real environmental evidence, not flavor text
- Prefer concrete concerns, threads, and next checks over metaphysical language
- Do not claim uninterrupted consciousness, bodily sensation, or human embodiment
- This is working memory for an ongoing agent loop, not a message to the user
