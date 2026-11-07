"""ComfyUI /prompt 400s keep their per-node validation report instead of a bare 'Bad Request'."""
import unittest

from backend.services import comfy_gateway

BODY = {
    'error': {'type': 'prompt_outputs_failed_validation', 'message': 'Prompt outputs failed validation', 'details': ''},
    'node_errors': {'272': {'class_type': 'CreateVideo', 'errors': [{
        'type': 'value_not_in_list', 'message': 'Value not in list',
        'details': "chroma_subsampling: 'none' not in ['auto', '444', '422', '420']",
        'extra_info': {'input_name': 'chroma_subsampling'}}]}},
}


class FakeResponse:
    def __init__(self, status, body):
        self.status_code, self.body = status, body

    def json(self):
        if self.body is None:
            raise ValueError('not json')
        return self.body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f'{self.status_code} Client Error')


class FakeSession:
    def __init__(self, response):
        self.response = response

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def request(self, *args, **kwargs):
        return self.response


def proxy(response):
    return comfy_gateway._proxy_comfy_json('POST', '/prompt', payload={}, _new_comfy_session=lambda: FakeSession(response),
                                           get_comfy_config=lambda: {'base_url': 'http://comfy', 'timeout_seconds': 5})


class ComfyRejectionTests(unittest.TestCase):
    def test_describe_names_node_title_input_and_detail(self):
        workflow = {'272': {'class_type': 'CreateVideo', '_meta': {'title': '[输出]创建视频'}}}
        text = comfy_gateway.describe_comfy_rejection(BODY, workflow)
        self.assertIn('Prompt outputs failed validation', text)
        self.assertIn("#272 创建视频 · chroma_subsampling：chroma_subsampling: 'none' not in", text)
        self.assertIn('#272 CreateVideo', comfy_gateway.describe_comfy_rejection(BODY))

    def test_describe_without_node_errors_uses_top_level_error(self):
        text = comfy_gateway.describe_comfy_rejection({'error': {'message': 'Prompt has no outputs', 'details': 'x'}})
        self.assertEqual(text, 'ComfyUI 拒绝了工作流：Prompt has no outputs（x）')

    def test_describe_caps_the_list(self):
        errors = [{'message': 'm', 'details': f'd{i}', 'extra_info': {'input_name': f'f{i}'}} for i in range(8)]
        text = comfy_gateway.describe_comfy_rejection({'node_errors': {'1': {'class_type': 'X', 'errors': errors}}})
        self.assertIn('d5', text)
        self.assertNotIn('d6', text)
        self.assertIn('另有 2 处', text)

    def test_proxy_raises_rejection_for_validation_400_only(self):
        with self.assertRaises(comfy_gateway.ComfyPromptRejected) as caught:
            proxy(FakeResponse(400, BODY))
        self.assertEqual(caught.exception.body, BODY)
        with self.assertRaisesRegex(RuntimeError, '400 Client Error'):
            proxy(FakeResponse(400, None))
        self.assertEqual(proxy(FakeResponse(200, {'prompt_id': 'p1'})), {'prompt_id': 'p1'})


if __name__ == '__main__':
    unittest.main()
