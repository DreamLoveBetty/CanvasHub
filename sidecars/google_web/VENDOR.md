# Gemini Web runtime provenance

`vendor/gemini_webapi` is vendored from
https://github.com/vanch007/gemini-banana-pro-skill at commit
`921f63a7f27fb1dc1deb2a43146677b0bf49b772` (2026-10-23).
The included `LICENSE.gemini-webapi` is GNU AGPL version 3. Preserve it when
distributing this runtime. This is not an official Google API client.

CanvasHub-local patches:
- `_generate` uses zero automatic retries; unknown outcomes are never replayed.
- Session initialization uses only the selected account's supplied cookies.
  Browser discovery, ambient Cookie caches and secret-bearing cache filenames
  are removed; the application owns explicit imports and per-account persistence.
- Cookie rotation stays in memory. Only the Web store persists credential state.
- Vendored logging is routed through a silent logger to avoid leaking upstream
  payloads or credentials to the host's shared logs.
- Login initialization accepts an explicit `on_bootstrap` callback for the host's
  active-account identity parser; HTML is not retained. No extra login request.
- Explicit `authuser` is propagated through initialization, generation, batch RPC
  (including original-image lookup) and reference upload. The bootstrap callback
  checks pinned identity before initialization RPCs or a retried initialization.
  Group Cookie persistence/refresh belongs to the Web host, not per-client tasks.
- The host uses `images.py`, not the vendor's `GeneratedImage.save` fallback. The
  latter assumes exactly two text-pointer hops and can silently fall back to a
  size-suffixed preview. Host downloads accept direct binary/variable pointer hops
  and report original-vs-unverified provenance without changing generation retries.
  The host explicitly carries the selected client's non-default `authuser` into
  the initial CDN download URL too; the RPC selector does not govern CDN account
  authentication. Signed query values and returned pointer URLs are not re-encoded.
- The stream parser records `temporary` on each `GeneratedImage` (excluded from
  public serialization/repr). Both host lookup and vendor save explicitly pass
  this per-image mode to `_get_full_size_image`: `c8o8Fe` payload `[3]` must be `1`
  for a temporary image, not the upstream's unconditional saved-chat `0`. Live
  same-image 0/1 ablation reproduces null/1003 versus the byte-identical 2K original.
  Extra signed tokens/descriptors/image keys were not needed and are not retained.
  Legacy calls still default to saved-chat mode and keep the existing RPC shape.
  Result parsing selects matching `wrb.fr/c8o8Fe` records even after telemetry;
  null/1003 remains no URL, not an auth error or a reason to regenerate.
- Original lookup optionally reports HTTP/transport status and explicit numeric
  BardErrorInfo rejection codes to a per-call host callback. No signed URLs,
  response text, credentials or exception messages are passed to it. The callback
  is optional, isolated from lookup success/failure, and has no retry/account or
  generation side effects. Host-owned private locator retention and redacted
  diagnostic logs live in `download_diagnostics.py`, not a vendor global/cache.

The CLI and its Cockpit backend are not imported. These changes do not affect
the project's existing OAuth/GPT libraries or account stores.
