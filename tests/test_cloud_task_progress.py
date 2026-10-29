"""Cloud image tasks map their observable stage to an equal-share progress band."""

import unittest

from backend.services.cloud_task_progress import progress_stage


def task(stage, status='processing', task_type='google-edit', telegram=False):
    return {'type': task_type, 'status': status, 'stage': stage, 'params': {'telegram_enabled': telegram}}


class CloudTaskProgressTest(unittest.TestCase):
    def test_stages_follow_the_recorded_checkpoints(self):
        cases = [
            (task('', status='queued'), 1, '准备'),
            (task('preparing'), 1, '准备'),
            (task('calling_api'), 2, '生成中'),
            (task('calling_chatgpt_pool_edit', task_type='gpt-edit'), 2, '生成中'),
            (task('started', task_type='gpt'), 2, '生成中'),
            (task('receiving_third_party_response', task_type='gpt'), 3, '接收并保存'),
            (task('saving'), 3, '接收并保存'),
        ]
        for value, index, label in cases:
            stage = progress_stage(value)
            self.assertEqual((stage['stage_index'], stage['stage_count'], stage['stage_label']), (index, 3, label), value)

    def test_telegram_delivery_adds_a_fourth_stage_only_when_enabled(self):
        self.assertEqual(progress_stage(task('calling_api', telegram=True))['stage_count'], 4)
        stage = progress_stage(task('sending_telegram', telegram=True))
        self.assertEqual((stage['stage_index'], stage['stage_count']), (4, 4))
        self.assertEqual(progress_stage({'type': 'gpt', 'status': 'processing', 'stage': 'saving', 'params': {}})['stage_count'], 4)

    def test_no_stage_for_local_finished_or_unknown_tasks(self):
        self.assertIsNone(progress_stage(task('calling_api', task_type='qwen21-image')))
        self.assertIsNone(progress_stage(task('done', status='succeeded')))
        self.assertIsNone(progress_stage(task('something_new')))


if __name__ == '__main__':
    unittest.main()
