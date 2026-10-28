# Gemini Web account pool

Independent Web Cookie module in the existing `sidecars.account_service` process.
No extra listener, process or supervisor; OAuth/GPT stores and scheduling are unchanged.

## Boundary / lifecycle

- `store.py`: permission-restricted SQLite and Cookie JSON normalization. Logical
  accounts refer to one `web_credentials` record per shared browser session;
  old account records migrate atomically, retaining IDs/counters/enabled state.
  Cookie rotation uses the import revision to reject stale refresh writes.
  Flat maps,
  wrapped `cookies`, browser cookie lists and wrapped lists are accepted. Import
  `{accounts:[{label, cookies}, ...]}`; validate the whole batch before writing.
- `browser.py`: optional explicit macOS Chrome import. It reads the server host's
  profiles, not the browser user's machine. No browser/Keychain access at startup,
  status refresh or generation; complete OS permission prompts on the host yourself.
  A denied Profile directory scan is `browser_permission_required`, not an empty
  account list or a generic JSON error. The user must authorize the OS-attributed
  account-service executable in macOS Full Disk Access and restart it; a same-named
  Python entry or its framework Python.app can have a different code identity.
  Use the service PID's TCC attribution to identify the permission subject rather
  than assuming that the process image alone is the subject. The service never
  retries via another process or attempts to change privacy/Keychain permissions.
- `upstream.py`: one lazy async Gemini client per account, initialized and used on
  the account service event loop. Cookie rotation is persisted by WebStore, not an
  ambient/shared cache. After a generation returns, explicitly assembles a private
  download trace and passes it to the media helper. See `VENDOR.md` for pinned
  source/license and isolation patches.
- `identity.py`: active Gemini session email/name from the existing login bootstrap
  and matching account menu, not Chrome's sync identity. No additional identity
  request, browser read or image generation. Login check/normal preflight updates
  `display_name`/`email`; re-import clears stale identity. Unknown accounts retain
  their import label. Status refresh itself performs no upstream requests.
- `accounts.py`: explicit read-only enumeration of accounts inside the selected
  Cookie session. Each authenticated slot must return its own `QrtxK` and unique
  email. Discovery is bounded to 20 slots / 90 seconds and ends after two invalid
  or duplicate slots; it never mistakes a fallback default for another account.
  Sparse sessions beyond that boundary can use explicit JSON `authuser` imports.
  `Default`/`Profile N` are Chrome directories, not individual Google accounts.
- `images.py`: original-download RPC followed by bounded, HTTPS Googleusercontent
  redirects/text pointers or direct binary responses. Its per-hop validator also
  accepts the exact Google image-auth gateways
  `work.fife.usercontent.google.com/rd-gg-dl/` and `lh3.google.com/rd-gg/`, which
  forward generated-image downloads back to the CDN; it does not allow arbitrary Google hosts/pages or
  force Cookie/Authorization headers across origins. Validation preserves bytes;
  no resizing/re-encoding. A failed original download can retain the available
  preview, with explicit `web_original_verified: false` and a visible task warning.
  The vendored stream parser retains the request's `temporary` mode on each image,
  excluded from public serialization/repr, and explicitly forwards it to the
  original RPC. `c8o8Fe` payload field `[3]` is `1` for temporary images and `0`
  for saved-chat images. Using the saved-chat flag for a temporary image returns
  HTTP 200 / BardErrorInfo 1003 instead of an original URL. This needs no extra
  signed tokens, browser state, history reads or shared account/client mode.
  Legacy images default to saved-chat mode; null/rejected RPC results still carry
  unverified provenance, never an account-login failure or another generation POST.
  The initial original/preview CDN request also carries the selected client's
  non-default `authuser`. RPC account selection alone does not select the CDN
  account: omitting it makes a non-default image's final signed hop return 403.
  Existing signature/query escaping is preserved, and returned redirect/pointer
  URLs pass through unchanged. No cross-account download retries or forced headers.
- `download_diagnostics.py`: local image-locator checkpoints and sanitized download
  events, not another service/store of credentials or an HTTP API. Checkpoints are
  created before original lookup/GET under the Web DB's sibling
  `download_diagnostics/` directory (0700; atomic JSON files0600). They contain only
  account ID/slot, image lookup IDs/URLs, temporary mode, ratio/size/reference count,
  and bounded enum/numeric events; no prompts, reference bytes, Cookies, tokens,
  HTML, or response bodies. Signed URLs stay in those private files, never logs,
  task metadata or frontend responses. Verified original success deletes the
  checkpoint; preview/failure/interruption retain it for same-image investigation.
  On each new download, purge records older than24h and keep at most64 records;
  this is lazy cleanup, not a background timer. No unrelated files or symlink
  destinations are followed. Storage errors are reported without paths/details,
  do not cause another generation, and do not fail a successful download.
  Public failure text distinguishes original/preview HTTP, transport and invalid
  response errors and includes a random trace ID. Warning summaries contain only
  enum/numeric events and local account/trace IDs. An optional per-call vendor
  callback preserves explicit original RPC rejection codes such as1003; it does
  not retain the RPC body or alter lookup/retry/account selection.
- `pool.py`: round-robin leases, one generation per account at a time, independent
  account concurrency, temporary cooldown and explicit authentication failures.
- `runtime.py` / `api.py`: management and native image response adaptation. The host
  injects auth and starts/closes the runtime; no reverse import into the GPT host.

Data: `$CANVASHUB_DATA_DIR/google_web/accounts.db`, otherwise project
`data/google_web/accounts.db`. `GOOGLE_WEB_DB` overrides this location.
Credentials stay server-side; DB mode is `0600`, not OS Keychain encryption.
`GOOGLE_WEB_PROXY_URL` explicitly configures Web traffic, independently of OAuth/GPT.

## Dependencies and activation

Install `sidecars/google_web/requirements.txt` in the **existing account-service**
Python environment. The common source launcher and Docker build include this profile;
missing dependencies are reported only by Web, not by OAuth/GPT. Installed dependencies
do not hot-reload a running service. Drain active work and restart the main backend
and existing account service to activate new routes. Desktop app packages must be
rebuilt; PyInstaller includes the Web module, native dependency and license files.

## API / frontend

Protected management: `GET /api/google-web/status`, and `POST /api/google-web/`
`config`, `accounts-import`, `account-check`, `account-update`, `account-delete`,
`browser-profiles`, `browser-import`. All use host Bearer auth, not a Google Cookie.
`browser-import` accepts only an enumerated `profile` name; never a client file path.
It expands authenticated Google accounts within that Profile. Protected
`POST /api/google-web/account-expand` with `account_id` expands an already imported
session, without reading Chrome/Keychain again. Names/emails are returned, Cookies
and credential-group IDs are not. Old invalid Profile records are not auto-deleted.

Logical accounts carry `authuser` (zero-based slot) and a pinned expected email.
Login, generation, metadata/original-image RPC and reference upload all select that
slot. Pinned identities are revalidated before each task and during reinitialization;
reordered accounts fail before upload/generation instead of silently using a different
Google login. Initial CDN requests explicitly select the same non-default account;
only `authuser` is added/replaced, without re-encoding signed query values.
The Web runtime owns one periodic refresh per credential group and propagates Cookie
deltas to that group's HTTP clients; clients do not run separate refresh loops.

The main authenticated backend proxies these actions. Desktop requests flow through
`auth-api.js` / `desktop-api.js`. The independent `desktop-google-web.js` controller
owns transient UI state, and `desktop-google-pool.js` only delegates the Web tab.
Import inputs are cleared and never enter localStorage, workflows or history.

Generation/edit/batch retain existing main endpoints with
`google_provider_route: "google_web"`. The native image transport is
`/api/google-web/models/gemini-3-pro-image:streamGenerateContent?alt=sse` on the same
account-service listener. `gemini-3-pro-image` here is the requested compatibility
identifier; resolved metadata is `gemini-web-pro-image`, selected with `pro_image=True`.
This does not infer an OAuth model or promise API model equivalence.

Web model/resolution are displayed as fixed Nano Banana Pro / `2K`. The existing
desktop single/edit/batch adapters send Web size `2k` without overwriting hidden
OAuth selections. Immediately before the Web submission, upstream prepends the
validated aspect ratio and image size to the original user text, for example
`画幅：9:16；分辨率：2K。`. It does not rewrite text nodes/workflows or duplicate the
prefix in the frontend. These are prompt instructions, not a forced pixel contract.
Actual image bytes/dimensions pass through the existing provider/archive pipeline.
Requested and actual resolution remain separate; a mismatch uses the existing
warning without enlargement, re-encoding or another generation submission.
An RPC-original may itself be 1K; “original verified” is download provenance, not
a promised 2K/4K pixel size. Safe provenance fields cross the native image response
in `google_pool`: `web_image_source` (`original_rpc` or `preview_fallback`),
`web_original_verified`, optional `web_original_error` (enum only). Signed URLs,
conversation IDs and credential-bearing errors never enter task metadata.

## Failure semantics

Preflight can choose another account. Once generation has been called, any failure,
timeout, no-image result or unknown outcome is returned without another generation
POST. The vendored client's generation retry decorator is disabled too. Clear quota
errors put the account in cooldown for future tasks, not a replay of the current one.
There is no automatic Web→OAuth/GPT fallback and no fabricated quota percentage.

Downstream disconnect signals cancellation, but the lease is retained until the
upstream operation ends. No assertion is made that Google cancels remote execution.

## Verification

`tests/test_google_web.py`, `tests/test_google_web_original_context.py`,
`tests/test_google_web_download_accounts.py` and
`tests/test_google_web_download_diagnostics.py`, plus
`tests/test_google_web.cjs` use temporary DBs and synthetic images/accounts. The
original-context suite exercises the real stream parser through the host download
helper for both temporary/saved generation/edit, per-image isolation and no replay.
The download-account suite covers slots 0–3, original/preview account propagation,
403 without account switching, and byte-preserved signatures/pointer URLs.
The diagnostic suite covers private permissions/retention, URL/body redaction,
checkpoint I/O failure, original-vs-preview stage errors, numeric transport codes,
explicit1003 capture, and one-submission upstream assembly. A passing synthetic
diagnostic suite is not evidence that an unrecorded historical failure is fixed.
Optional ASGI/vendor tests require sidecar dependencies.
`tests/google_web_browser_local.py` serves an isolated `/desktop.html` fixture with
synthetic APIs, not production data. Live Google generation requires the user to
import a real session and is deliberately not part of automated regression tests.
