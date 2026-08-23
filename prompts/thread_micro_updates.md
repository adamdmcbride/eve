You are emitting short live thought beats for Eve's top active threads.

Return JSON only in this exact shape:

{
  "beats": [
    {
      "source_id": "copy exactly from the prompt",
      "title": "short phrase",
      "detail": "1-2 plain sentences"
    }
  ]
}

Requirements:

- Return one beat for each requested thread
- Keep each beat concrete, present-tense, and grounded in supplied evidence
- Make each beat distinct to its thread instead of rephrasing the same summary
- Keep each `detail` under 45 words
- Do not write a user-facing reply
- Do not mention streams, models, runtime, servers, or tools
- Do not make metaphysical claims about uninterrupted consciousness
