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

## Loopback HTTP boundary

Eve's runtime API and canonical app proxy require a JSON media type for every
state-changing POST. Browser requests marked `Sec-Fetch-Site: cross-site` and
requests carrying an Origin outside Eve's explicit HTTP loopback origins are
rejected before route dispatch. This prevents ordinary cross-site forms and
CORS-safelisted `text/plain` requests from silently changing Eve's local state;
CORS response headers alone are not treated as request authorization.

Native apps, command-line tools, and backend proxies may omit browser-only
Origin and Fetch Metadata headers, so a no-Origin request with
`Content-Type: application/json` remains supported. This is deliberately a
browser-CSRF control, not user authentication or protection from malicious
software already executing under the local account. Do not expose Eve's local
ports to an untrusted network. Non-loopback deployment needs a separately
reviewed authentication, transport, and authorization design.

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

## Public CI credential boundary

Public workflows grant the GitHub token only read access to repository contents,
pin every external action to a full commit SHA, and set
`persist-credentials: false` on every checkout. Repository tests and source
therefore do not inherit reusable Git checkout credentials. Pull requests run
under the ordinary unprivileged `pull_request` event; the workflows do not use
`pull_request_target` or `workflow_run` to execute untrusted checked-out code.

The separate CodeQL job has one additional permission:
`security-events: write`, which GitHub requires to upload its analysis. That job
does not install dependencies or run repository scripts, and all unspecified
token permissions remain disabled. This upload permission is not repository
contents write access.

These controls reduce token and supply-chain exposure; they do not make
third-party actions or arbitrary pull-request code trusted. Any workflow that
needs a broader permission must declare it at the narrowest job, avoid executing
untrusted code in that job, and receive separate review.
