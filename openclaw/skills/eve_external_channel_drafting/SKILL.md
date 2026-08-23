---
name: eve_external_channel_drafting
description: Draft and preflight OpenClaw external-channel messages without sending; require exact approval before any send.
---

# Eve External Channel Drafting

Use this skill when Eve needs to inventory external channels, draft a message, or decide whether a send is allowed.

## Boundaries

- Inventory is read-only.
- Drafting records a local artifact only; it does not send.
- Sending requires an exact current approval, configured channel/account/target, and evidence.
- Never infer recipient, account, channel, or message body.
- Never treat a draft as delivered.
- Personal iMessage DMs are not an Eve inbox. Keep OpenClaw `channels.imessage.dmPolicy=disabled`; do not approve pairing codes or enable DM pairing unless the user explicitly grants that exact sender Eve access.

## Commands

```bash
python3 $HOME/.eve_runtime/eve.py openclaw channels inventory --full
python3 $HOME/.eve_runtime/eve.py openclaw channels draft --channel slack --target channel:C123 --message "Draft text" --full
python3 $HOME/.eve_runtime/eve.py openclaw channels events --limit 10 --full
```

The send path exists but is gated:

```bash
python3 $HOME/.eve_runtime/eve.py openclaw channels send --channel slack --target channel:C123 --message "Approved text" --permission-request-id <id> --confirm-approved-send --full
```

Use `--use-trusted-directive` only when the user's current instruction names the exact channel, recipient, and message and `trusted_operator_directive` is active.

## Completion Rule

Say `drafted` only after an `openclaw_channel_draft` event exists.
Say `sent` only after an `openclaw_channel_send` event shows `ok=true` and `external_send_attempted=true`.
Say `blocked` when approval, channel configuration, target, or delivery evidence is missing.
