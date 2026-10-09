# Ambient CSS (vendored, unmodified)

Source: https://github.com/kikkupico/ambientcss @ `f829df728ca34a1addecb475ca62b6493733b898` (MIT, see `LICENSE`).

| File | Upstream path | SHA-256 |
| --- | --- | --- |
| `ambient.css` | `packages/ambient-css/src/ambient.css` | `0498bab2fc1dfb9b7feb31a072744aea19631694752a1e43e1cdcd8cd4a3280b` |
| `components.css` | `packages/ambient-components/src/styles.css` | `60e7636ef506b0b80c2f3cd1fdd0b611212b6481ff4779422f3d6e20ba7458a2` |

These files are never linked from a page: they declare `:root` / `*` / `@property`
globally. `frontend/tooling/build-ambient-controls.mjs` extracts only the rules the
optional "Ambient" control material needs and scopes them to
`#deskApp[data-control-material="ambient"]`, writing
`frontend/styles/desktop-ambient-controls.css`. Do not edit these files; update the
pinned commit, hashes and regenerate instead.
