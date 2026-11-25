# Contributing to Eve

Thank you for helping improve Eve. Eve is a local-first AI counterpart with one
coherent identity, five logical attention modes, governed memory, and bounded
tool/action organs.

## Before opening a change

1. Search existing issues and documentation for the behavior you want to
   change.
2. Prefer the smallest change that fixes a demonstrated problem.
3. Keep Eve's boundaries intact:
   - lanes are attention modes, not independent personalities;
   - runtime processes and model count do not define identity;
   - OpenClaw acts through admitted contracts and is not a second mind;
   - Hermes proposes learning changes and cannot write canonical memory;
   - tools, models, and accelerators do not grant themselves authority.
4. Never commit model weights, credentials, personal conversations, user
   profiles, runtime databases, generated memory, logs, or machine-specific
   state.

## Development setup

Eve currently targets Python 3.12 through 3.14. The native application and
resident llama.cpp runtime require macOS; the release audit and most unit tests
are platform-independent.

```bash
python3 bin/eve_bootstrap.py check
python3 bin/eve_bootstrap.py install --extra dev --skip-runtime-sync
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run python -m pytest -q
python3 bin/eve_public_release_audit.py --root . --candidate-only --include-untracked
```

Omit `--skip-runtime-sync` only when you intentionally want this checkout to
replace your local `~/.eve_runtime` code mirror. The bootstrap never installs a
daemon, downloads a model, or enables a hosted provider by itself.

Some integration tests require local models or optional organs. Keep those
tests explicitly marked and make their absence a skip, not a false pass.

## Maintainers: handing off a clean source tree

The private development checkout is not the GitHub repository. Do not add a
public remote to it or push its branches, tags, history, or ignored files.
Prepare the candidate from a reviewed revision. Review any untracked source
explicitly; an untracked module on one machine is not part of a Git backup.

From the source root, choose a **new destination outside the checkout**. Keep
the manifest outside both trees. Only proceed if every command succeeds:

```sh
handoff=$(mktemp -d) &&
python3 bin/eve_public_release_audit.py --root . --candidate-only --include-untracked \
  --export "$handoff/tree" --write-manifest "$handoff/source.manifest.json" &&
python3 bin/eve_public_release_audit.py --root "$handoff/tree" \
  --verify-manifest "$handoff/source.manifest.json" --exact-tree
```

Review that tree against a fresh clone of the configured GitHub repository;
preserve its existing public history and submit the reviewed changes through
a branch and pull request. Do not initialize Git in the private checkout for
this handoff, force-push, or treat an older public revision as the latest local
work. After merge, verify a fresh archive of the **merged commit** against the
same manifest and run the documented bootstrap and tests from the restored
source. A passing manifest verifies paths and file bytes, not a working
runtime. Private state, weights, backups, and unpublished development work
need separate verified recovery before retiring a machine or checkout.

## Pull requests

A useful pull request includes:

- the user-visible problem and the narrow fix;
- tests that fail before the change and pass afterward;
- evidence for any runtime, routing, permission, memory, or model claim;
- privacy and rollback notes when state or tools are involved;
- no unrelated cleanup.

Run the focused tests and the public-release audit before requesting review.
Large architectural changes should first land characterization tests and a
sequenced migration plan; avoid big-bang rewrites of the live runtime.

## Licensing contributions

Unless explicitly stated otherwise, contributions submitted to this repository
are provided under the Apache License 2.0, consistent with Section 5 of that
license. Do not submit code that you cannot legally contribute. Preserve all
required third-party attribution and identify adapted source in the pull
request.
