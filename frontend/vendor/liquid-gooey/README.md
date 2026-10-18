# liquid-gooey image melt and morph (ported)

Source: https://github.com/Jakubantalik/Libraries.dev/tree/main/packages/liquid-gooey
@ `b7c588f1cfe3497d1d8a2fd8a6950351f0330285` (MIT, see `LICENSE`).

| Ported to | Upstream path | Upstream SHA-256 |
| --- | --- | --- |
| `frontend/scripts/desktop-canvas-image-group-melt.js` | `packages/liquid-gooey/src/imageMelt.tsx` | `964f05f3cb9c0b7e6f51043974029fd79fe9b9470c2a07d7c2fffc2837d1a746` |
| `frontend/scripts/desktop-canvas-image-group-role-picker.js` | `packages/liquid-gooey/src/Gooey.tsx` | `5c8052fa6ba89e02e171a5696fa046b397e7897a7f4bf90237e39622e4085850` |
| `frontend/scripts/desktop-canvas-image-group-role-picker.js` | `packages/liquid-gooey/src/LiquidItem.tsx` | `aeed41a5663818e4c076949dc783f7f638867866a3c93bedcba66c1a699595a3` |

No upstream file is bundled. The image-group melt is a vanilla JavaScript rewrite of
the React `MeltPair` paint (pattern-filled cards, goo-on-colour filter, marble pass,
seam-erase masks and their default tuning). Differences from upstream: no React, no
registry or own animation loop (the image-group interaction controller owns time and
eases the proximity), pixel tunings scale with the card size instead of assuming 84px
cards, and the SVG covers only the pair's bounding box plus the filters' reach
instead of the whole group.

The role picker ports the default `effect="morph"` merge (no shape physics): each item's
blob lives in one goo-filtered layer (blur, alpha contrast) under its crisp content, and
items spring between positions with the demo's `cubic-bezier(.34, 1.56, .64, 1)` over
550ms. Differences from upstream: no React or observer engine (CSS transitions move the
blobs and the buttons together through shared custom properties), the project's existing
goo filter primitives (blur 6, contrast 18) are reused, and items sit on a ring around a
thumbnail rather than at hand-placed offsets.
