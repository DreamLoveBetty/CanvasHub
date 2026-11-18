import base64
import json
import unittest
from unittest.mock import patch

from sidecars.chatgpt_pool.openai_backend import OpenAIBackend, Requirements, UpstreamError


class ImageEventStream:
    status_code = 200

    def __init__(self, events):
        self.events = events

    def iter_lines(self, **_kwargs):
        for event in self.events:
            yield f"data: {json.dumps(event)}".encode()
        yield b"data: [DONE]"

    def close(self):
        pass


class ChatgptPoolImageResultTest(unittest.TestCase):
    def _edit_with_result_from(self, source):
        backend = OpenAIBackend("fixture-token")
        uploads = [
            {
                "file_id": file_id,
                "library_file_id": library_id,
                "file_name": f"image_{index}.png",
                "file_size": 300,
                "mime_type": "image/png",
                "width": 60,
                "height": 60,
            }
            for index, (file_id, library_id) in enumerate(
                [
                    ("file-subject", "file_subject_library"),
                    ("reference_style", "file_style_library"),
                    ("file-mask", "file_mask_library"),
                ],
                start=1,
            )
        ]
        output_message = {
            "author": {"role": "tool", "name": "image_gen"},
            "status": "finished_successfully",
            "content": {
                "content_type": "multimodal_text",
                "parts": [{
                    "content_type": "image_asset_pointer",
                    "asset_pointer": "file-service://generated_asset",
                    "file_id": None,
                }],
            },
        }
        mapping = {}
        poll_count = 0
        # Some stream deltas echo the pointer/ID without its owning user message.
        input_delta = {
            "p": "/message/content/parts/0",
            "o": "replace",
            "v": {
                "content_type": "image_asset_pointer",
                "asset_pointer": "sediment://reference_style",
                "file_id": "file-mask",
                "library_file_id": "file_subject_library",
            },
        }

        def open_stream(_url, *, json, **_kwargs):
            # The service can echo the uploaded assets before image generation.
            user_message = json["messages"][0]
            user_message["metadata"]["attachments"][0]["resolved_id"] = "file-echoed-alias"
            mapping["input"] = {"message": user_message}
            events = [{"conversation_id": "fixture-conversation"}]
            if source in {"stream", "library", "missing"}:
                events.extend([{"v": {"message": user_message}}, input_delta])
            if source == "delta":
                events.append(input_delta)
            if source in {"stream", "delta"}:
                events.append({
                    "p": "/message/content/parts/0",
                    "o": "replace",
                    "v": output_message["content"]["parts"][0],
                })
            return ImageEventStream(events)

        def conversation(_conversation_id):
            nonlocal poll_count
            poll_count += 1
            pending = source == "poll" and poll_count == 1
            return {
                "mapping": {
                    **mapping,
                    "assistant": {"message": {
                        "author": {"role": "assistant"},
                        "status": "in_progress" if pending else "finished_successfully",
                        "content": {"content_type": "text", "parts": ["Working" if pending else "Done"]},
                    }},
                    **({"image": {"message": output_message}} if source == "poll" and not pending else {}),
                },
                "metadata": {"file_id": "file_subject_library", "source_asset": "sediment://reference_style"},
            }

        def download_asset(url):
            if url == "https://example.test/generated_asset":
                return b"generated-image"
            return b"uploaded-reference"

        library_items = [{
            "conversation_id": "fixture-conversation",
            "url": "https://example.test/generated_asset",
        }] if source == "library" else []
        with (
            patch.object(backend, "_upload_editable_base64_image", side_effect=uploads),
            patch.object(backend, "_bootstrap"),
            patch.object(backend, "_requirements", return_value=Requirements(token="fixture")),
            patch.object(backend, "_prepare_image_conversation", return_value="fixture-conduit"),
            patch.object(backend.session, "post", side_effect=open_stream),
            patch.object(backend, "_get_conversation", side_effect=conversation),
            patch.object(backend, "_get_recent_image_generation_items", return_value={"items": library_items}),
            patch.object(backend, "_download_url_for_file", side_effect=lambda asset: f"https://example.test/{asset}"),
            patch.object(
                backend, "_download_url_for_attachment",
                side_effect=lambda _conversation, asset: f"https://example.test/{asset}",
            ),
            patch.object(backend, "_download_image", side_effect=download_asset),
            patch("sidecars.chatgpt_pool.openai_backend.time.sleep"),
        ):
            return backend.edit_image("Restyle the subject", ["subject-image", "style-image"], mask="mask-image")

    def test_edit_returns_generated_image_instead_of_echoed_uploads(self):
        for source in ("stream", "delta", "poll", "library"):
            with self.subTest(source=source):
                result = self._edit_with_result_from(source)
                self.assertEqual(base64.b64decode(result["b64_json"]), b"generated-image")

    def test_edit_with_only_uploaded_refs_fails_instead_of_reporting_success(self):
        with self.assertRaisesRegex(UpstreamError, "finished without image output"):
            self._edit_with_result_from("missing")
