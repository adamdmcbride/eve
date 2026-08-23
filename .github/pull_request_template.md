## What changed

<!-- Describe the user-visible problem and the smallest fix. -->

## Verification

<!-- List exact tests, commands, and observed results. -->

## Risk and rollback

<!-- Note state migrations, permissions, model/runtime impact, and rollback. -->

## Checklist

- [ ] The change is focused and does not include unrelated cleanup.
- [ ] Tests cover the changed behavior.
- [ ] I did not add secrets, personal data, runtime state, model weights, or generated memory.
- [ ] I preserved Eve's identity, lane, organ, authority, and evidence boundaries.
- [ ] I ran `python3 bin/eve_public_release_audit.py --root . --include-untracked`.
- [ ] I identified adapted third-party source and preserved required attribution.

