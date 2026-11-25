# Eve Loopback HTTP Mutation Boundary

Status: active
Last reviewed: 2026-08-23
Current authority: `eve_http_security.py`, `eve_http_headers.py`, `eve_http_body.py`, `eve_http_json.py`, `eve_http_path.py`, `eve_http_query.py`, `eve_http_server.py`, and `eve_agui.py`
Supersedes: scattered CORS-only mutation assumptions
Superseded by: none

## Problem

Binding a service to loopback prevents a remote host from connecting directly,
but it does not stop a web page open on the same Mac from submitting a request
to that local port. CORS normally controls whether the attacking page can read
the response; it does not prevent a CORS-safelisted request from reaching the
server. A JSON parser that also accepts JSON bytes labeled as `text/plain` can
therefore turn a normal cross-site form or simple `fetch` into a state change.

Eve has two state-changing local HTTP surfaces:

- `eve_web.py`, the runtime/OpenAI-compatible API;
- `bin/eve_app_server.py`, the canonical Eve.app proxy.

They must apply one policy rather than drift into two definitions of a trusted
browser request.

The runtime reports local API version `7`; that version also includes the
independent Eve.app snapshot read contract.

## Contract

Before any POST route dispatch, both servers call the pure
`evaluate_json_mutation_request` policy. It:

1. rejects `Sec-Fetch-Site: cross-site` with `403`;
2. when an Origin is present, accepts only canonical `http` loopback origins
   for the listening port plus Eve's declared loopback app origins;
3. requires `application/json` or an `application/*+json` media type, including
   normal parameters such as `charset=utf-8`, and otherwise returns `415`;
4. closes the connection on rejection instead of consuming an untrusted body
   or leaving unread bytes on a persistent connection.

The runtime's sensory routes retain their narrower local-app Origin gate after
the shared policy. Existing web, WebKit, Swift, backend proxy, OpenAI-compatible,
and CLI mutation callers send JSON. The app proxy now also preserves the JSON
media type when forwarding an empty follow-up acknowledgement.

## Consumed headers and transport metadata

`eve_http_headers.py` owns the values that either server actually consumes.
It preserves all occurrences instead of trusting a mapping's first value,
rejects ambiguous duplicates, strips only outer HTTP whitespace, and requires
bounded printable ASCII. The mutation boundary admits at most 512 characters
for `Origin`, 32 for `Sec-Fetch-Site`, and 256 for `Content-Type`. A duplicate,
control-bearing, non-ASCII, or over-budget consumed mutation header returns
`400` and closes before the untrusted body is read. Request-body framing uses
the same duplicate-preserving extraction for `Content-Length` and
`Transfer-Encoding`.

OpenAI-compatible correlation metadata has a separate bounded schema:

- each `X-OpenWebUI-*` chat or message ID is printable ASCII and at most 160
  characters before it enters the request payload;
- conflicting values across the two supported assistant-message aliases are
  rejected instead of silently selecting one;
- JSON OpenWebUI, client-request, AG-UI thread/run, and event-correlation IDs
  are printable text capped at 160 characters before hashing, persistence, or
  event construction;
- the OpenAI-compatible model selector is capped at 80 characters and the
  visible messages array at 128 entries; per-message and final context budgets
  remain independently enforced.

Header metadata that fails after a correctly framed JSON body is consumed can
return `400` without orphaning bytes on keep-alive. These limits prevent
ambiguity and metadata-driven allocation/persistence amplification. They do
not turn correlation IDs into identity, authorization, or trusted memory.

## Decoded JSON-field contract

`eve_http_json.py` owns the smaller application values inside an admitted,
decoded JSON object. It validates raw string length before trimming, requires
the declared JSON type instead of applying `str(...)` or truthiness coercion,
rejects hidden controls, and gives arrays a finite count before any element can
enter persistence or model work. Ordinary tabs and line breaks are admitted
only for explicitly multiline message fields.

The current conversation-mutation schema is:

- runtime message body: at most 32,000 characters;
- runtime subject and message/thread resource IDs: at most 512 characters;
- client-request/correlation ID: at most 160 characters;
- attachments: at most eight JSON objects per message;
- capture tags: at most 32 printable strings, each at most 64 characters;
- OpenAI `stream` and personal-message `allow_none`/`notify`: actual JSON
  Booleans only;
- Eve.app personal reply: at most 8,000 body characters and 160 characters for
  the message and client-request IDs.

The runtime handler validates these values before service dispatch, and the
service validates persisted conversation calls again for non-HTTP callers.
Eve.app rejects an over-budget personal reply rather than silently forwarding
a truncated ID or body. An attachment-only runtime message retains its existing
bounded fallback prompt. Well-formed unknown JSON fields remain compatibility
no-ops.

This contract bounds ambiguity and persistence/model amplification. It does
not authenticate a local caller, sanitize model meaning, authorize attached
content, or replace the byte-level request-body budget.

## CopilotKit/AG-UI adapter

`eve_agui.py` owns AG-UI protocol translation while `eve_web.py` remains the
HTTP/SSE transport and service dispatcher. The adapter admits either the normal
messages array or the documented top-level/nested prompt compatibility shape;
it no longer converts arrays, numbers, or objects into accidental prompt/model
strings. Fallback prompt text is multiline printable text capped at 8,000
characters and the model selector is printable text capped at 80. Message
roles, plain content, and text content-parts keep their declared JSON types;
each message's projected visible content must fit the same 8,000-character
limit before the shared OpenAI adapter runs. AG-UI therefore does not rely on
that compatibility adapter's historical slicing behavior for request bounds.

Thread, run, and client-request aliases are individually bounded at 160
characters. Multiple aliases may repeat the same value, but conflicting values
fail before SSE headers or model dispatch. Generated activity and text-message
IDs are also capped at 160 characters; an over-budget prefixed value retains a
bounded source prefix plus a deterministic SHA-256 suffix rather than colliding
through plain truncation. Event types are required printable text capped at 64.

The module re-exports through `eve_web.py` for source compatibility. It creates
no new route or cognition policy: admitted runs still call the same
`EveRuntimeService.openai_chat_completion`, executive scheduler, and five
logical lane contracts. AG-UI remains a UI protocol adapter, not Eve identity,
memory authority, a sixth lane, or permission to act.

## Request-body framing

Both servers also use `read_bounded_request_body` before JSON decoding. The
shared framing rule:

1. requires exactly one ASCII-decimal `Content-Length`;
2. rejects `Transfer-Encoding`, which Python's `BaseHTTPRequestHandler` does
   not decode;
3. rejects the declaration before reading when it exceeds the endpoint budget;
4. reads until the exact declared byte count and rejects premature EOF rather
   than parsing a valid-looking prefix;
5. closes the persistent connection after ambiguous, oversized, or incomplete
   framing so unread bytes cannot become another request.

The runtime limit is 2 MiB for ordinary JSON, 128 KiB for sensory requests, and
a separately calculated base64 envelope for one admitted 25 MiB attachment.
The Eve.app proxy accepts at most 256 KiB. Explicit zero-byte bodies remain
compatible only on routes whose existing contract allows an empty JSON object
or discards the body. This is an allocation and request-boundary guarantee; it
does not impose an absolute wall-clock body deadline.

## Query-string contract

`eve_http_query.py` replaces route-specific `parse_qs` and permissive `int` or
truthiness coercion on the runtime API. One parse occurs before route dispatch:

- the encoded request query is limited to 8,192 characters and 32 fields;
- malformed fields, invalid UTF-8, empty/overlong/control-bearing consumed
  values, and overlong/control-bearing field names fail as `400`;
- a consumed field may occur once; duplicate known values are rejected instead
  of silently choosing the first value;
- integers are ASCII decimal only and route-bounded: ordinary list reads are at
  most 500, reply/follow-up views have smaller 200-item ceilings, model health
  is at most 100, lookback is at most 3,650 days, and monitor streaming accepts
  250 through 10,000 milliseconds;
- Booleans use one case-insensitive vocabulary: `1|true|yes|on` and
  `0|false|no|off`;
- text filters and identifiers are trimmed, printable, and capped according to
  their role rather than entering downstream state or database reads
  unbounded.

Well-formed unknown fields remain ignored for compatibility, but they still
count against the total query budget. Eve.app validates the same syntax, UTF-8,
length, and field-count boundary before forwarding any GET. A rejected app POST
and a rejected runtime POST both close their connection so an unread body
cannot cross keep-alive framing; the runtime remains authoritative for
route-specific typed values.

This bounds parsing and read amplification. It is not a rate limiter, identity
check, database authorization layer, or absolute request deadline.

## Request-target and dynamic-route contract

`eve_http_path.py` makes the request target and dynamic resource routes one
shared contract rather than a collection of `startswith`, `endswith`, and
partial `split` checks:

- the target must use HTTP origin form; absolute proxy-form URLs, network-path
  authorities, and fragments are rejected rather than being reinterpreted as
  a local route;
- the complete target is capped at 12,289 characters and its path at 4,096;
- raw targets use printable ASCII, percent escapes must be complete, decoded
  text must be valid UTF-8, and encoded control characters fail before route
  or static-file dispatch;
- a dynamic model, message, thread, proposal, or follow-up route matches exactly
  one raw slash-delimited segment and its exact suffix; a missing segment or
  extra structural segment is another route and returns `404`;
- decoded IDs are non-empty, printable, free of surrounding whitespace and dot
  segments, and capped at 512 characters (128 for model names);
- a percent-encoded slash may remain opaque ID data, but never becomes routing
  syntax; Eve.app decodes and rebuilds the canonical percent-encoded route
  before proxying it;
- canonical and legacy web clients plus native monitor/operator clients encode
  dynamic IDs with an unreserved segment allowlist rather than interpolating
  them as path syntax.

POST dispatch also has explicit body ownership. Routes with no semantic input
still read one exact JSON object before executing. An unknown POST, invalid
target, invalid dynamic ID, or malformed query closes with its body unread;
there is no persistent-connection path where bytes from a rejected request can
be parsed as the next request. Compatibility fields in a no-argument JSON
object remain ignored for now; body consumption is not an endorsement that
those fields have meaning.

These rules remove partial route matches, proxy-form confusion, and orphaned
POST bodies. They do not authenticate a local process, authorize a resource,
or make an opaque ID safe for filesystem use.

## Connection resource budget

Both surfaces now inherit `EveBoundedThreadingHTTPServer` and
`EveBoundedHTTPRequestHandler`:

- no more than 32 accepted requests may own worker threads at once;
- the kernel listen backlog is explicitly 32 rather than an implicit
  platform/default value;
- excess accepted connections close before a request thread is created;
- every client socket operation has a 30-second inactivity timeout, including
  header/body reads and writes to clients that stop consuming a stream;
- active and rejected counts are process-local accounting for tests and future
  diagnostics, not a new health claim.

The socket timeout does not interrupt a long model calculation while no client
I/O is occurring, so existing reply behavior and backend timeouts remain owned
by their current contracts. It is an inactivity bound, not an absolute request
deadline: a client that continually makes progress may live longer. The worker
cap bounds that residual risk. This remains a local pre-alpha server, not a
general internet-facing deployment architecture.

## Response privacy and document policy

The same base handler now owns response defaults instead of letting the two
surfaces drift:

- state, JSON, streams, downloads, and static content send
  `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, and
  `Referrer-Policy: no-referrer`;
- static Eve documents additionally use same-origin resource policy,
  `X-Frame-Options: DENY`, a CSP limited to Eve-owned local resources with no
  frames/base override and self-only form submission, and an explicit device
  policy;
- the runtime web shell denies camera, microphone, and geolocation; Eve.app
  retains same-origin camera/microphone only because those modalities remain
  user-started behind its existing permission contract;
- API responses deliberately do not add same-origin CORP, preserving the
  separately admitted loopback CORS clients;
- the `Server` header retains an Eve product label but no longer discloses the
  host Python version.

Eve.app's request log no longer formats BaseHTTPRequestHandler's raw request
line. It records only bounded JSON-escaped loopback address, method, URL path,
and status. Query strings, bodies, conversation text, formatter arguments, and
literal terminal-control characters do not enter that log.

## Internal error disclosure

Expected request failures remain useful: bounded `4xx` responses may explain
which typed field, framing rule, media type, origin, or supported operation the
client must correct. An unexpected implementation or upstream failure is a
different trust boundary and must not serialize its diagnostic content.

For an unexpected `5xx` failure:

- the runtime and Eve.app return a fixed generic client message plus one opaque
  16-hex-character error ID;
- the shared server records one JSON line containing only that ID, a fixed
  surface and operation label, and the exception type;
- exception messages, tracebacks, machine paths, request paths and queries,
  bodies, conversation text, and upstream response content are not logged or
  returned;
- monitor SSE and AG-UI runs emit one generic terminal error carrying the same
  kind of ID rather than exposing worker exception text;
- Eve.app consumes and closes an upstream `5xx` body but substitutes its own
  generic `502`; transport reasons and incomplete-body diagnostics receive the
  same treatment;
- bounded upstream `4xx` bodies remain relayable so a legitimate client error
  does not become an opaque operational failure.

The shared threading server also replaces the standard library's default
unhandled-request traceback with the same content-free record. Broken-pipe,
connection-reset, and connection-aborted disconnects remain expected client
departures and are not promoted into internal errors.

An error ID permits an operator to correlate a response with one local metadata
record. It does not contain recovery material, prove that a retry is safe, or
imply that the failed action completed.

## Advertised installer and update endpoint

The HTTP `Host` field is client-provided routing metadata. It is not authority
to rewrite executables, scripts, download links, bootstrap state, or update
metadata. Runtime download and artifact handlers therefore use only the
server-owned `advertised_host` plus the actual listening port; changing a
request's `Host` header cannot change generated output.

The endpoint contract is deliberately small:

- an explicit host may be supplied through `bin/eve_server.py
  --advertised-host` or `EVE_ADVERTISED_HOST`;
- without an explicit value, a safe DNS/IPv4 bind host is reused and wildcard
  or unsupported bind forms fall back to `localhost`;
- advertised hosts accept canonical ASCII DNS names or IPv4 only, rejecting
  whitespace, controls, URI syntax, userinfo, shell metacharacters, wildcard
  addresses, numeric lookalikes, Unicode, and IPv6 literals;
- ports are one ASCII-decimal integer from 1 through 65535; Boolean, signed,
  Unicode-digit, overlong, zero, and out-of-range forms fail closed;
- `/api/bootstrap` and `/api/update-manifest` tolerate legacy query copies of
  the host/API port only when each occurs at most once and canonically matches
  the server-owned endpoint; a request cannot select a different authority;
- the separate numeric model-port query remains configurable but must occur at
  most once and pass the same strict port validation before the service runs;
- every artifact builder revalidates its endpoint, so a future non-HTTP caller
  cannot bypass the handler boundary and interpolate shell text.

IPv6 is intentionally not advertised yet. The existing Windows, macOS, and
Linux generated scripts do not all serialize bracketed IPv6 URL authorities
correctly; silently accepting one would create broken installers. This does not
prevent the API from being bound according to its existing socket behavior,
but a generated cross-machine endpoint must currently be DNS or IPv4.

This prevents request-host poisoning and script/URL injection. It is not DNS
authentication, TLS, authorization for non-loopback clients, or proof that a
configured hostname resolves from another device.

## Deliberate compatibility boundary

Origin and Fetch Metadata are browser headers. Local native clients, CLI tools,
and server-to-server proxies may omit them, so no-Origin JSON requests remain
allowed. This preserves local integrations without inventing a static bearer
secret in source.

Consequently, this policy is **CSRF resistance, not authentication**. It does
not protect Eve from a malicious process already running as the same user, a
compromised trusted UI, XSS in an allowed origin, or an operator who exposes
the service on an untrusted interface. Those threats require host controls and,
for any non-loopback deployment, a separately designed authenticated transport
and authorization layer.

## Verification

- pure policy tests cover canonical origins, JSON media types, foreign Origin,
  Fetch Metadata, simple content types, and no-Origin compatibility;
- pure body tests cover duplicate/missing/invalid lengths, transfer encoding,
  byte budgets, fragmented reads, exact completion, and premature EOF;
- pure header tests cover duplicate preservation, single-value admission,
  outer-whitespace normalization, ASCII/control/length limits, and programmer
  argument validation;
- pure JSON-field tests cover raw-before-trim length checks, strict types and
  Booleans, multiline/control policy, bounded object/string lists, and invalid
  programmer limits;
- pure AG-UI tests cover top-level/nested message compatibility, prompt/model
  and message/content types and limits, alias conflicts, bounded hashed event
  IDs, event types, and progress/completion projection compatibility;
- pure query tests cover immutable parsing, malformed UTF-8/fields, character
  and field budgets, duplicate values, controls, strict integers/ranges, and
  the shared Boolean vocabulary;
- pure path tests cover origin-form enforcement, target/path budgets, strict
  percent/UTF-8 decoding, exact segment/suffix matching, decoded-ID bounds, and
  canonical route round trips;
- pure server tests cover finite admission, excess-connection close, slot
  release after completion/start failure, queue size, client I/O timeout,
  response headers, device-policy variants, version suppression, and
  content-free structured internal-error records;
- advertised-endpoint tests cover DNS/IPv4 canonicalization, wildcard/IPv6/
  metacharacter rejection, strict ports, configured fallback, duplicate query
  rejection, different-authority rejection, hostile request-host independence,
  and builder revalidation;
- runtime-handler tests prove rejection occurs before an Eve mutation method;
- runtime-handler tests prove invalid list, Boolean, malformed, duplicate, and
  over-budget queries fail before a read service method; app-proxy tests prove
  an over-budget GET is not forwarded, and both surfaces prove malformed POST
  queries close before mutation dispatch;
- runtime and app tests prove encoded IDs arrive as one decoded opaque value,
  extra route segments do not partially dispatch, bodyless mutations consume
  their framed JSON, and unknown/absolute-form POSTs close before unread bytes
  can cross keep-alive;
- runtime and app tests prove duplicate consumed mutation headers fail before
  dispatch, app-forwarded IDs are header-safe, and OpenWebUI/AG-UI correlation
  metadata is bounded before service dispatch or persistence;
- runtime and app tests prove string/numeric pseudo-Booleans, over-budget
  message metadata, invalid attachment/tag arrays, and silent app-proxy
  truncation fail before mutation or forwarding;
- runtime, OpenAI-compatible, monitor-SSE, AG-UI, and app-proxy tests inject
  secret-bearing failures and prove only a generic message plus correlatable
  opaque ID crosses the client/log boundary; app tests also prove upstream 5xx
  content is not relayed;
- app-proxy tests prove the policy runs before chat dispatch and exercise the
  real HTTP boundary in the pinned macOS CI job;
- the public workflow includes the pure/runtime tests on Linux and the complete
  app-server contract suite on macOS.

## Research basis

- [OWASP CSRF Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)
  recommends treating cross-site Fetch Metadata as untrusted, retaining Origin
  fallback checks, and disallowing simple content types for JSON APIs.
- [MDN CORS guide](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CORS)
  explains that simple `POST` requests—including `text/plain`, form-encoded,
  and multipart requests—reach the server without preflight even when the
  browser later withholds the response.
- [MDN Sec-Fetch-Site reference](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Sec-Fetch-Site)
  defines `same-origin`, `same-site`, `cross-site`, and `none` request context.
- [Python 3.12 `http.server` documentation](https://docs.python.org/3.12/library/http.server.html)
  documents that `ThreadingHTTPServer` uses a thread per request and warns that
  the module implements only basic security checks.
- [Python `socketserver` documentation](https://docs.python.org/3/library/socketserver.html)
  documents daemon-thread behavior and the finite listen backlog controlled by
  `request_queue_size`.
- [MDN Cache-Control](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Cache-Control)
  distinguishes `no-store` from `no-cache` and defines it as a request not to
  retain the response in private or shared caches.
- [MDN X-Content-Type-Options](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/X-Content-Type-Options)
  documents `nosniff` as requiring the declared content type to be respected.
- [MDN Referrer Policy guidance](https://developer.mozilla.org/en-US/docs/Web/Security/Practical_implementation_guides/Referrer_policy)
  documents `no-referrer` as suppressing URL/referrer disclosure.
- [MDN CSP guidance](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CSP)
  documents `frame-ancestors 'none'` as a clickjacking boundary.
