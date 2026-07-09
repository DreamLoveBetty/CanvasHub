import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def assert_asset_has_cache_bust(testcase, html: str, asset_path: str) -> None:
    testcase.assertRegex(html, re.escape(asset_path) + r"\?v=[0-9A-Za-z._-]+")


def read_text(relative_path: str) -> str:
    path = ROOT / relative_path
    if not path.exists() and relative_path.startswith(("desktop.html", "index.html", "scripts/", "styles/", "assets/", "vendor/")):
        path = ROOT / "frontend" / relative_path
    return path.read_text(encoding="utf-8")


def css_block(css: str, selector: str) -> str:
    marker = f"\n{selector} {{"
    start = css.index(marker) + len(marker)
    end = css.index("\n}", start)
    return css[start:end]


class GalleryPreviewBackdropTest(unittest.TestCase):
    def test_preview_modal_uses_image_backdrop_layer(self) -> None:
        html = read_text("desktop.html")
        js = read_text("scripts/desktop-history.js")
        css = read_text("styles/desktop-liquid.css")

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
        css = read_text("styles/desktop-liquid.css")

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
        css = read_text("styles/desktop-liquid.css")
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

        modal_block = css_block(css, ".desk-compare")
        panel_block = css_block(css, ".desk-compare__panel")
        actions_button_block = css_block(css, ".desk-compare__actions button")
        divider_block = css_block(css, ".desk-compare__divider")
        divider_dot_block = css_block(css, ".desk-compare__divider::before")
        label_block = css_block(css, ".desk-compare__label")

        self.assertIn("--desk-preview-radius: 12px;", modal_block)
        self.assertIn("inset: 52px 68px 48px 78px;", modal_block)
        self.assertIn("overflow: hidden;", modal_block)
        self.assertIn("border-radius: var(--desk-preview-radius);", modal_block)
        self.assertIn("backdrop-filter: blur(18px) saturate(1.14);", modal_block)
        self.assertIn("width: 100%;", panel_block)
        self.assertIn("height: 100%;", panel_block)
        self.assertIn("border-radius: inherit;", panel_block)
        self.assertIn("width: 34px;", actions_button_block)
        self.assertIn("height: 34px;", actions_button_block)
        self.assertIn('mask-image: url("../assets/icons/contrast.svg");', css)
        self.assertIn('mask-image: url("../assets/icons/circle-x.svg");', css)
        self.assertIn("width: 1px;", divider_block)
        self.assertIn("width: 18px;", divider_dot_block)
        self.assertIn("height: 18px;", divider_dot_block)
        self.assertIn("top: 20px;", label_block)
        self.assertIn("function compareAssetName", js)
        self.assertIn("basenameFromAssetPath(asset?.file)", js)
        self.assertIn("els.deskCompareLeftLabel.title = leftName;", js)
        self.assertIn("els.deskCompareRightLabel.title = rightName;", js)
        assert_asset_has_cache_bust(self, html, "scripts/desktop-history.js")
        self.assertIn('body.desk-app:not([data-theme="dark"]) .desk-compare {', css)
        self.assertIn("rgba(250, 253, 255, 0.16)", css)
        self.assertIn("lucide-contrast", contrast_icon)
        self.assertIn("lucide-circle-x", close_icon)

    def test_gallery_preview_counter_uses_full_asset_index_limit(self) -> None:
        html = read_text("desktop.html")
        js = read_text("scripts/desktop-history.js")

        assert_asset_has_cache_bust(self, html, "scripts/desktop-history.js")
        self.assertIn("const GALLERY_ASSET_LOAD_LIMIT = 5000;", js)
        self.assertIn("limit: GALLERY_ASSET_LOAD_LIMIT", js)
        self.assertIn("Number(galleryAssetTotal || 0)", js)
        self.assertNotIn("limit: 800", js)


if __name__ == "__main__":
    unittest.main()
