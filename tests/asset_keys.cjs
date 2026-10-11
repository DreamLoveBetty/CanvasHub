// Shared by feature tests: an asset is referenced with *some* ?v= cache key. Whether the key
// was bumped when the file changed is checked once, for every asset, by
// frontend/tooling/asset-versions.mjs (tests/test_asset_versions.cjs) — feature tests
// assert behaviour and load order and never pin key strings.
const escape = value => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const hasCacheKey = (html, asset) => new RegExp(`${escape(asset)}\\?v=[0-9A-Za-z._-]+`).test(html);
module.exports = { hasCacheKey };
