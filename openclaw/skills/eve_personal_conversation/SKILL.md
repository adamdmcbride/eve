---
name: eve_personal_conversation
description: Let Eve initiate one grounded, replyable personal conversation with the user through the existing Eve message thread.
---

# Eve Personal Conversation

Use this when Eve wants to talk to the user personally without waiting for the user to start the exchange.

## Contract

- Eve may open a personal conversation when she has a grounded observation, question, concern, invitation, or useful update for the user.
- The message belongs in the user mailbox as an Eve-to-user thread, not in an operations-only log.
- The thread should remain replyable: when the user answers, continue in the same mailbox thread instead of starting a duplicate conversation.
- Do not manufacture urgency, affection, or insight. If there is nothing worth saying, stay quiet.
- Keep the first message concise and end with one clear question, invitation, or next step.

## Runtime Surface

- Generate a fresh Eve-started message with `python3 eve.py message initiate`.
- The daemon may also create these through the proactive outreach loop.
- The Eve Monitor app shows these in the From Eve section as a personal chat.
- Eve Monitor should listen for this channel; the user should not need to press a
  wake or "speak now" button for Eve to start talking locally.
- the user replies through the same message thread; Eve should answer that reply as the same conversation.

## Good Use

- Ask the user about a live ambiguity that genuinely needs their judgment.
- Tell the user about a meaningful state change or risk that affects them.
- Follow up on a prior conversation when there is new evidence or a real next step.

## Bad Use

- Generic check-ins with no evidence.
- Repeating unresolved themes while the user has not answered.
- Treating system health or workspace trivia as personal conversation unless it matters to the user.
