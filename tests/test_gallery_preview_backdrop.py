import re
import unittest
from pathlib import Path
from tests.legacy_css import read_legacy_css


ROOT = Path(__file__).resolve().parents[1]


def assert_asset_has_cache_bust(testcase, html: str, asset_path: str) -> None:
    testcase.assertRegex(html, re.escape(asset_path) + r"\?v=[0-9A-Za-z._-]+")


def read_text(relative_path: str) -> str:
    path = ROOT / relative_path
    if not path.exists() and relative_path.startswith(("desktop.html", "index.html", "scripts/", "styles/", "assets/", "vendor/")):
        path = ROOT / "frontend" / relative_path
    return path.read_text(encoding="utf-8")


def css_block(css: str, selector: str) -> str:
    # Migrated legacy rules carry a :where() scope in front of the selector.
    markers = [f"\n{selector} {{", f"\n:where(body.desk-app[data-theme]) {selector} {{"]
    marker = next(m for m in markers if m in css)
    start = css.index(marker) + len(marker)
    end = css.index("\n}", start)
    return css[start:end]


class GalleryPreviewBackdropTest(unittest.TestCase):
    def test_preview_modal_uses_image_backdrop_layer(self) -> None:
        html = read_text("desktop.html")
        js = read_text("scripts/desktop-history.js")
        css = read_legacy_css()

        self.assertIn('id="deskGalleryPreviewBackdropImg"', html)
        self.assertIn('class="desk-gallery-preview__backdrop"', html)
        self.assertIn("deskGalleryPreviewBackdropImg", js)
        self.assertIn("els.deskGalleryPreviewBackdropImg.src = imageSrc;", js)
        self.assertIn("els.deskGalleryPreviewBackdropImg.src = '';", js)
        self.assertIn(".desk-gallery-preview__backdrop", css)
        self.assertIn(".desk-gallery-preview__panel::before", css)
        modal_block = css_block(css, ".desk-gallery-preview")
        panel_block = css_block(css, ".desk-gallery-preview__panel")
        backdrop_block = css_block(css, ".desk-gallery-preview__backdrop")
        backdrop_img_block = css_block(css, ".desk-gallery-preview__backdrop img")
        stage_block = css_block(css, ".desk-gallery-preview__stage")

        self.assertIn("--desk-preview-radius: 12px;", modal_block)
        self.assertNotIn("--desk-preview-stage-top", modal_block)
        self.assertNotIn("--desk-preview-stage-bottom", modal_block)
        self.assertIn("overflow: hidden;", modal_block)
        self.assertIn("rgba(18, 24, 27, 0.20)", modal_block)
        self.assertIn("rgba(18, 24, 27, 0.24)", modal_block)
        self.assertIn("rgba(16, 22, 25, 0.24)", modal_block)
        self.assertIn("border-radius: var(--desk-preview-radius);", modal_block)
        self.assertIn("backdrop-filter: blur(18px) saturate(1.14);", modal_block)
        self.assertIn("border-radius: inherit;", panel_block)
        self.assertIn("border-radius: inherit;", backdrop_block)
        self.assertIn("rgba(255, 255, 255, 0.05)", backdrop_block)
        self.assertIn("rgba(255, 255, 255, 0.02)", backdrop_block)
        self.assertIn("rgba(15, 23, 26, 0.1)", backdrop_block)
        self.assertIn("opacity: 0.1;", backdrop_img_block)
        self.assertIn("right: var(--desk-preview-info-width);", stage_block)
        self.assertIn("top: 0;", stage_block)
        self.assertIn("bottom: 0;", stage_block)
        self.assertIn("background: transparent;", stage_block)
        self.assertIn("border-radius: 0;", stage_block)
        self.assertNotIn("background: #020608;", css)

    def test_preview_modal_has_day_mode_palette(self) -> None:
        html = read_text("desktop.html")
        css = read_legacy_css()

        assert_asset_has_cache_bust(self, html, "styles/desktop-liquid.css")
        self.assertIn('body.desk-app:not([data-theme="dark"]) .desk-gallery-preview {', css)
        self.assertIn("rgba(245, 250, 253, 0.26)", css)
        self.assertIn("rgba(250, 253, 255, 0.16)", css)
        self.assertIn("backdrop-filter: blur(24px) saturate(1.08);", css)
        self.assertIn('body.desk-app:not([data-theme="dark"]) .desk-gallery-preview__info', css)
        self.assertIn("rgba(27, 41, 56, 0.9)", css)
        self.assertIn("rgba(250, 253, 255, 0.56)", css)
        self.assertIn("rgba(250, 253, 255, 0.58)", css)
        self.assertIn('body.desk-app:not([data-theme="dark"]) #deskGalleryPreviewApplyBtn', css)
        self.assertIn("rgba(37, 99, 235, 0.88)", css)
        self.assertIn('body.desk-app:not([data-theme="dark"]) #deskGalleryPreviewDeleteBtn', css)

    def test_compare_modal_matches_preview_board_shell(self) -> None:
        html = read_text("desktop.html")
        js = read_text("scripts/desktop-history.js")
        css = read_legacy_css()
        contrast_icon = read_text("assets/icons/contrast.svg")
        close_icon = read_text("assets/icons/circle-x.svg")

        self.assertNotIn('id="deskCompareTitle"', html)
        self.assertNotIn("'deskCompareTitle'", js)
        self.assertNotIn('if (els.deskCompareTitle)', js)
        self.assertIn('id="deskCompareSwapBtn" title="交换对比图" aria-label="交换对比图"', html)
        self.assertIn('class="desk-compare__icon desk-compare__icon--swap"', html)
        self.assertIn('class="desk-compare__icon desk-compare__icon--close"', html)
        self.assertNotIn('id="deskCompareSwapBtn">交换</button>', html)
        self.assertNotIn('id="deskCompareCloseBtn" aria-label="关闭对比">关闭</button>', html)

        # Compare styles live in the token module desktop-compare.css (colours from the
        # --desk-compare-* tokens), no longer in the legacy stylesheets.
        compare_css = read_text("styles/desktop-compare.css")
        tokens_css = read_text("styles/desktop-tokens.css")
        scope = "body.desk-app[data-theme] "
        modal_block = css_block(compare_css, scope + ".desk-compare")
        panel_block = css_block(compare_css, scope + ".desk-compare__panel")
        actions_button_block = css_block(compare_css, scope + ".desk-compare__actions button")
        divider_block = css_block(compare_css, scope + ".desk-compare__divider")
        divider_dot_block = css_block(compare_css, scope + ".desk-compare__divider::before")
        label_block = css_block(compare_css, scope + ".desk-compare__label")

        self.assertNotIn("desk-compare", css, "no compare rules left in the legacy stylesheets")
        self.assertIn("--desk-preview-radius: 12px;", modal_block)
        self.assertIn("inset: 52px 68px 48px 78px;", modal_block)
        self.assertIn("overflow: hidden;", modal_block)
        self.assertIn("border-radius: var(--desk-preview-radius);", modal_block)
        # 性能不变量：对比模态禁止 backdrop-filter——背后画布/图库存在 infinite 动画时，
        # 毛玻璃每帧全区域重算模糊，会让分隔线拖动持续掉帧（与预览外壳有意不一致）
        self.assertNotIn("backdrop-filter", modal_block)
        self.assertIn(scope + ".desk-compare .desk-glass {", compare_css)
        self.assertIn("width: 100%;", panel_block)
        self.assertIn("height: 100%;", panel_block)
        self.assertIn("border-radius: inherit;", panel_block)
        self.assertIn("min-width: 34px;", actions_button_block)
        self.assertIn("height: 34px;", actions_button_block)
        self.assertIn('mask-image: url("../assets/icons/contrast.svg");', compare_css)
        self.assertIn('mask-image: url("../assets/icons/circle-x.svg");', compare_css)
        self.assertIn("width: 1px;", divider_block)
        self.assertIn("width: 18px;", divider_dot_block)
        self.assertIn("height: 18px;", divider_dot_block)
        self.assertIn("top: 20px;", label_block)
        # Light and dark backdrops are token values, one per theme.
        light_tokens = tokens_css[:tokens_css.index('body.desk-app[data-theme="dark"] {')]
        dark_tokens = tokens_css[tokens_css.index('body.desk-app[data-theme="dark"] {'):]
        self.assertIn("--desk-compare-background: linear-gradient(120deg, rgba(245, 250, 253, 0.78)", light_tokens)
        self.assertIn("--desk-compare-background: linear-gradient(90deg, rgba(18, 24, 27, 0.55)", dark_tokens)
        self.assertIn("function compareAssetName", js)
        self.assertIn("basenameFromAssetPath(asset?.file)", js)
        self.assertIn("els.deskCompareLeftLabel.title = leftName;", js)
        self.assertIn("els.deskCompareRightLabel.title = rightName;", js)
        assert_asset_has_cache_bust(self, html, "scripts/desktop-history.js")
        self.assertIn("rgba(250, 253, 255, 0.16)", css)
        self.assertIn("lucide-contrast", contrast_icon)
        self.assertIn("lucide-circle-x", close_icon)

    def test_compare_module_consumes_theme_tokens(self) -> None:
        html = read_text("desktop.html")
        compare_css = read_text("styles/desktop-compare.css")
        tokens_css = read_text("styles/desktop-tokens.css")
        code = re.sub(r"/\*.*?\*/", "", compare_css, flags=re.S)

        assert_asset_has_cache_bust(self, html, "styles/desktop-compare.css")
        self.assertNotIn("desktop-legacy-compare.css", html)
        self.assertNotIn("desk-compare", read_legacy_css())
        # Token module: no theme selectors, literal colours or !important.
        self.assertNotIn('data-theme="', code)
        self.assertNotIn(":not([data-theme", code)
        self.assertNotRegex(code, r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(")
        self.assertNotIn("!important", code)
        # Every compare token the module reads is defined for both themes.
        light = tokens_css[:tokens_css.index('body.desk-app[data-theme="dark"] {')]
        dark = tokens_css[tokens_css.index('body.desk-app[data-theme="dark"] {'):]
        used = set(re.findall(r"var\((--desk-compare-[\w-]+)", code)) - {"--desk-compare-info-width"}
        self.assertGreater(len(used), 30)
        for token in sorted(used):
            self.assertIn(f"  {token}:", light, token)
            self.assertIn(f"  {token}:", dark, token)

    def test_gallery_preview_counter_uses_full_asset_index_total(self) -> None:
        # 二期分页后：计数器的"全量"语义由服务端 data.total 保证，而非一次拉满 5000。
        html = read_text("desktop.html")
        js = read_text("scripts/desktop-history.js")

        assert_asset_has_cache_bust(self, html, "scripts/desktop-history.js")
        self.assertIn("const GALLERY_PAGE_SIZE = 200;", js)
        self.assertIn("fields: 'card'", js)
        self.assertIn("let galleryServerOffset = 0;", js)
        self.assertIn("function hasMoreGalleryAssets()", js)
        self.assertNotIn("offset: galleryAssets.length", js)
        self.assertIn("Number(galleryAssetTotal || 0)", js)
        self.assertIn("function loadMoreGalleryAssets", js)
        self.assertIn("function ensureAssetDetail", js)
        self.assertNotIn("limit: 800", js)


if __name__ == "__main__":
    unittest.main()
