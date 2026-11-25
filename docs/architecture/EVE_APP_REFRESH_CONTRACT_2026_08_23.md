# Eve.app low-wakeup refresh contract

Status: active  
Last reviewed: 2026-08-23  
Current authority: source-verified app refresh contract  
Supersedes: independent per-ledger Eve.app polling  
Superseded by: none

Runtime deployment remains pending the coordinated atomic source/runtime sync.

## Purpose

Eve.app is a conversation surface, not a dashboard that should continuously
wake the Mac to re-read each ledger independently. The app still needs to show
Eve-initiated messages, recent thought/action/reflection cards, personal-chat
state, completed follow-ups, and current presence with useful latency.

The browser previously issued six sequential live-data GETs, one follow-up GET,
and a separate status GET every 30 seconds. At the normal ten-second visible
cadence that was about 44 browser GETs per minute. Hidden windows still made
about nine GETs per minute.

The normal loop now issues:

1. `GET /api/eve-app/snapshot` for the bounded conversation read model; and
2. `GET /api/presence` for the small derived presence projection.

That is about 12 browser GETs per visible minute and two per hidden minute: a
73% and 78% reduction respectively. These are deterministic request-count
reductions, not measured claims about CPU time, battery life, or network energy.

The native Swift shell separately used to probe `/health` every 15 seconds in
both foreground and background. It now checks every 30 seconds while the app is
active and every 120 seconds while inactive, with an immediate check whenever
the scene becomes active. The existing two-consecutive-failure threshold remains
the self-healing gate. At requested cadence, browser plus native surface GETs
therefore fall from about 48 to 14 per active minute and from 13 to 2.5 per
inactive minute. This count excludes explicit mutations, failure fallbacks, and
the app server's own bounded backend checks.

The app proxy also keeps an instance-local, lock-protected reachability hint.
Any successful real proxy response records backend availability for at most 12
seconds; a transport failure records unavailability for at most one second.
Within those windows `/health` reuses the observed result instead of opening a
redundant `/v1/models` probe. Expired or absent evidence always causes the
bounded live probe. The asymmetric expiry prevents a failure hint from masking
quick recovery and bounds a positive hint's staleness. Only a Boolean and
monotonic observation time are cached—never payload, message, model output, or
user data.

## Snapshot contract

`/api/eve-app/snapshot` returns `eve_app_snapshot.v1` under the normal
`{"ok": true, "data": ...}` envelope. The read model contains:

- `api_version` and `generated_at`;
- `personal_messages`: up to 30 Eve-to-user personal messages;
- `thoughts`: up to 24 recent thought entries;
- `activity`: up to 50 recent activity entries;
- `reflections`: up to five recent reflection entries;
- `personal_status`: the existing personal-conversation status projection; and
- `followups`: up to 12 unseen delivered or failed Eve Chat follow-ups for the
  `eve_chat_ui` surface.

The endpoint composes the existing service reads. It does not create a new
ledger, change ordering/filter semantics, mark anything read or seen, write
memory, select a model lane, or execute an action. Message-read and follow-up
seen transitions remain explicit POST mutations through their existing guarded
routes.

`API_VERSION` advances from 6 to 7 because this is a new public local-interface
contract. Eve.app rejects a missing or incompatible snapshot schema and keeps
its last good rendered state rather than presenting a partial snapshot as
current truth.

## Scheduling and failure behavior

- Visible requested cadence remains ten seconds so proactive messages retain
  the existing discovery behavior.
- Hidden requested cadence remains 60 seconds; the Page Visibility event
  triggers an immediate refresh when the window becomes visible again. These
  are not hard real-time guarantees: macOS and WebKit may coalesce background
  timers.
- Only one live refresh may be in flight. The next refresh is scheduled after
  the current one settles, so slow reads cannot accumulate overlapping timers.
- Exponential backoff remains capped at 120 seconds after failures.
- A successful snapshot is the ordinary backend-readiness signal. The old
  recurring 30-second status timer is removed.
- If the snapshot fails, Eve.app performs the narrow status check and legacy
  follow-up poll as a compatibility/recovery fallback. Ordinary chat remains
  usable from the last good local state.
- Presence remains independently optional. A temporary presence failure keeps
  the last good presence while the conversation snapshot can still succeed.
- Native health checks request a 30-second cadence only while the app is active
  and a 120-second cadence while inactive. Foregrounding performs one immediate
  check. The ordinary two-failure restart gate remains, but an active app retries
  two seconds after the first failure instead of waiting for another periodic
  interval. A generation token prevents a canceled background monitor from
  overwriting its newer foreground replacement.
- Recent successful app traffic may satisfy a native health check for 12
  seconds. Transport failures invalidate that proof immediately and expire
  after one second; stale or missing proof falls through to `/v1/models`.

## Bounded upstream ingestion

Eve.app's proxy treats live reply streaming separately from bounded state
reads. Streaming replies remain chunked at 64 KiB so the app does not buffer a
whole model response before showing it. Every non-stream proxy response is
limited to 8 MiB, compact presence input to 2 MiB, and proxied backend error
detail to 64 KiB. Both declared `Content-Length` and the bytes actually read are
checked; a missing length does not disable the limit, and an incomplete declared
body is rejected rather than forwarded as a successful response.

An oversized but otherwise reachable response leaves backend reachability true
while returning a bounded 502 to that app route. An incomplete or unreadable
response invalidates the short health hint. Response headers are not sent to the
WebView until a non-stream body passes these checks, so the proxy can still
return one truthful JSON failure instead of dropping a partially committed HTTP
response. No rejected backend body is included in that failure.

## Startup truth and process ownership

The native app uses `/health` to decide whether to uncover the conversation.
That endpoint is healthy only when both the local app surface and Eve's local
conversation backend are reachable. It returns HTTP 503 with `ok=false` and
`backend_ok=false` when the proxy process exists but the backend does not. The
launcher checks the same `backend_ok=true` evidence, so an orphaned surface can
no longer make startup exit early while Eve's backend remains offline.

The launcher's PID file is a hint, not process authority. Before sending a
signal it now requires a positive numeric PID other than PID 1 and verifies
that `ps` identifies the process as `eve_app_server.py`. Invalid contents or a
PID reused by another process are reported and discarded without signalling
that process. A process actually listening on the app port is handled
separately: only recognized Eve UI server commands may be retired; an unrelated
listener still blocks startup with an explicit error.

The app builder follows the same ownership rule when retiring an old surface
before a rebuild. A dead, invalid, or foreign PID-file hint is not trusted; the
builder falls back to the actual port listener and signals it only when its
command is the Eve app server. An unrelated listener is left untouched and
reported.

The Swift app starts the selected executable launcher directly with
`Foundation.Process`. It no longer interpolates the launcher path into a
`zsh -lc` command or backgrounds the launcher before learning its result. The
launcher itself remains responsible for detaching the long-lived local
services. Swift receives the real launcher exit status and bounded diagnostic
output, writes that output to the local launch log, and can show a truthful
failure immediately instead of waiting for a background shell that already
reported success.

Launcher output now goes straight to a newly truncated file instead of through
an unread `Pipe` while Swift waits for process exit. That removes the pipe-buffer
backpressure path that could otherwise deadlock a noisy launcher. The file is
opened with `O_NOFOLLOW`, forced to owner-only `0600` permissions, and reset on
every launch. Only its final 32 KiB is decoded for the in-app failure detail, so
diagnostic rendering and memory use do not grow with launcher output. The local
file remains the complete output for that launch unless it exceeds a future
explicit log-retention policy; this tranche bounds app ingestion, not the
launcher's own writes.

This health contract covers the canonical conversation surface and its backend.
It does not claim that every Eve-owned model, OpenClaw service, evaluator, or
daemon is healthy; whole-system power and service truth remain owned by their
separate lifecycle/status contracts.

The source app, launcher, app proxy, and runtime endpoint must deploy together. Until the
pending atomic runtime sync and app rebuild occur, this document describes the
verified source contract rather than the installed app.

## Design basis

The scheduling follows platform guidance to avoid unnecessary timers and
background networking while keeping user-visible work current:

- Apple, [Minimize Timer Usage](https://developer.apple.com/library/archive/documentation/Performance/Conceptual/power_efficiency_guidelines_osx/Timers.html)
- Apple, [Reducing networking and Bluetooth power usage](https://developer.apple.com/documentation/xcode/reducing-networking-and-bluetooth-power-usage)
- Apple, [Scheduling CPU work efficiently](https://developer.apple.com/documentation/xcode/scheduling-cpu-work-efficiently)
- MDN, [Page Visibility API](https://developer.mozilla.org/en-US/docs/Web/API/Page_Visibility_API)

The next performance step is to instrument actual idle wakeups, CPU, memory,
launch time, and refresh latency on the signed app. This contract deliberately
does not invent those budgets from request counts alone.
