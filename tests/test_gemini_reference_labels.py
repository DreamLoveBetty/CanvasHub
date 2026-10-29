"""Native Gemini requests label each reference image 图片N, matching @图片N in prompts."""

import base64
import io
import unittest
from unittest import mock

from PIL import Image

from backend import provider_change2pro as change2pro
from backend.gemini_request_parts import labeled_reference_parts
from backend.provider_google_pool import GooglePoolProvider


def png_b64(color):
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), color).save(buffer, "PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


class CapturedPost(Exception):
    pass


class FakeSession:
    def __init__(self):
        self.trust_env = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, **kwargs):
        self.json = kwargs["json"]
        raise CapturedPost()


class FakeClient:
    def __init__(self):
        self.session = FakeSession()

    def connection(self):
        return "http://127.0.0.1:18080", {}

    def session_factory(self):
        return self.session


class GeminiReferenceLabelTest(unittest.TestCase):
    def setUp(self):
        self.images = [png_b64("red"), png_b64("blue")]

    def sent_parts(self, route):
        client = FakeClient()
        with self.assertRaises(CapturedPost):
            GooglePoolProvider(client, route=route).edit("@图片1 改为 @图片2 的风格", self.images)
        return client.session.json["contents"][0]["parts"]

    def test_labels_precede_each_image_in_order(self):
        parts = labeled_reference_parts([{"inlineData": "a"}, {"inlineData": "b"}])
        self.assertEqual(parts, [{"text": "图片1："}, {"inlineData": "a"}, {"text": "图片2："}, {"inlineData": "b"}])
        self.assertEqual(labeled_reference_parts([]), [])

    def test_google_oauth_pool_labels_reference_images(self):
        parts = self.sent_parts("google_pool")
        self.assertEqual(parts[0], {"text": "@图片1 改为 @图片2 的风格"})
        self.assertEqual([p.get("text") for p in parts[1::2]], ["图片1：", "图片2："])
        self.assertEqual([p["inlineData"]["data"] for p in parts[2::2]], self.images)

    def test_gemini_web_keeps_unlabeled_parts(self):
        parts = self.sent_parts("google_web")
        self.assertEqual(len(parts), 3)
        self.assertEqual([p["inlineData"]["data"] for p in parts[1:]], self.images)

    def test_official_google_payload_labels_reference_images(self):
        payload = change2pro.google_payload("提示词", "9:16", "4K", ["data:image/png;base64," + i for i in self.images])
        parts = payload["contents"][0]["parts"]
        self.assertEqual([p.get("text") for p in parts], ["提示词", "图片1：", None, "图片2：", None])

    def test_text_only_payload_is_unchanged(self):
        payload = change2pro.google_payload("提示词", "1:1", "2K")
        self.assertEqual(payload["contents"][0]["parts"], [{"text": "提示词"}])


if __name__ == "__main__":
    unittest.main()
