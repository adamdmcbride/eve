# Upstream Mirrors

This directory is Eve's local staging area for upstream source mirrors.

Use:

```bash
python3 eve.py updates mirror --component openclaw
python3 eve.py updates mirror --component hermes-agent
python3 eve.py updates mirror --component llama-cpp
python3 eve.py updates mirror --component karpathy-skills
```

The mirrors are bare Git repositories and are intentionally ignored by Eve's own Git repo. They let Eve compare upstream code, create review branches or worktrees, and test updates before anything touches the live runtime.

Use upstream remotes for original-project truth. Fork remotes are local operator
configuration and must never be assumed by the public source tree.
