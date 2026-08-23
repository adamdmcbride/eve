# Security Policy

Eve can access local models, files, tools, and optional device or channel
adapters. Treat authority, privacy, and evidence failures as security issues,
even when the service remains bound to loopback.

## Supported versions

Security fixes target the latest tagged release and the default branch. The
project is pre-alpha and has no tagged supported release yet. The default branch
receives best-effort security fixes but should not be treated as a stable
distribution.

## Reporting a vulnerability

Do not open a public issue for a vulnerability or include secrets, private
conversations, logs, or personal data in an issue.

Use GitHub's **Report a vulnerability** flow under the repository's Security
tab. Include:

- affected revision and platform;
- the smallest reproduction that does not expose private data;
- likely impact and authority boundary crossed;
- any safe mitigation you already tested.

The maintainer will acknowledge a complete report as soon as practical,
coordinate remediation privately, and credit reporters who want attribution.

## High-priority scope

- credential, token, model, or private-memory disclosure;
- unauthenticated access beyond the intended loopback boundary;
- path traversal or writes outside Eve-owned roots;
- bypass of action admission, permission, approval, or verification gates;
- prompt/tool injection that gains unintended authority;
- update, plugin, model, MCP, or release supply-chain compromise;
- cross-user data leakage or persistence of raw sensory content;
- false health evidence that can cause unsafe repair or destructive action.

Local-only deployment reduces exposure; it does not remove the need for these
controls.

## Local data at rest

Eve's continuity store contains conversations, evidence, and runtime state in
local plaintext files. The store creates and replaces those files with
owner-only permissions (`0600`), but it is **not** a credential vault and does
not provide application-level encryption at rest. Do not put passwords, API
keys, access tokens, recovery codes, or other credentials into Eve's prompts,
configuration, logs, or state files. Use the operating system keychain or the
secret facility owned by an admitted integration instead.

Full-disk encryption and a locked user session provide additional host-level
protection but do not change this application boundary. Application-level
encrypted continuity is future work and must include migration, recovery, and
data-loss tests before it can replace the current format.
