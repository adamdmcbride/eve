# Eve Conversation Attachment Boundary

Status: active
Last reviewed: 2026-08-23
Current authority: `eve_attachments.py`
Supersedes: none
Superseded by: none

## Purpose

Eve Chat may stage a local file, attach its metadata to one conversation turn,
and expose a bounded text excerpt to Eve. An attachment is conversation
evidence, not canonical memory, a tool call, an instruction source, or
permission to act.

## Contract

- Files stay below the configured local runtime attachment root.
- Staged files, extracted text, and the attachment index use owner-only
  permissions.
- Symlinks that resolve outside the attachment root are rejected.
- Upload size is checked before and after Base64 decoding; generic JSON request
  bodies are bounded separately from the larger upload endpoint.
- One message may reference at most eight attachment objects; the count is
  checked at HTTP ingress and again before any attachment index write.
- Text extraction and model context are independently bounded and streamed
  rather than loading an arbitrary staged text file in full.
- Model-visible metadata omits absolute machine paths and labels file text as
  untrusted evidence.
- Message metadata retains the local-only and no-memory-without-governance
  boundary.
- `eve_web.py` keeps compatibility wrappers while storage and evidence behavior
  live in the replaceable `eve_attachments.py` seam.

## Not claimed

This path does not parse every binary format, create embeddings, promote file
content to memory, grant attached instructions authority, or make a remote
provider safe. A future parser or retrieval organ must enter through a separate
admission and provenance contract.
