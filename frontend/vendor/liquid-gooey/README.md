# liquid-gooey image melt (ported)

Source: https://github.com/Jakubantalik/Libraries.dev/tree/main/packages/liquid-gooey
@ `b7c588f1cfe3497d1d8a2fd8a6950351f0330285` (MIT, see `LICENSE`).

| Ported to | Upstream path | Upstream SHA-256 |
| --- | --- | --- |
| `frontend/scripts/desktop-canvas-image-group-melt.js` | `packages/liquid-gooey/src/imageMelt.tsx` | `964f05f3cb9c0b7e6f51043974029fd79fe9b9470c2a07d7c2fffc2837d1a746` |

No upstream file is bundled. The image-group melt is a vanilla JavaScript rewrite of
the React `MeltPair` paint (pattern-filled cards, goo-on-colour filter, marble pass,
seam-erase masks and their default tuning). Differences from upstream: no React, no
registry or own animation loop (the image-group interaction controller owns time and
eases the proximity), pixel tunings scale with the card size instead of assuming 84px
cards, and the SVG covers only the pair's bounding box plus the filters' reach
instead of the whole group.
