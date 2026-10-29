"""Cloud task estimates come from recent successful runs of the same route/model/resolution."""

import unittest

from backend.services.task_duration_estimate import MIN_SAMPLES, TaskDurationEstimator

POOL_2K = {'google_provider_route': 'google_pool', 'model': 'gemini-3.1-flash-image', 'requested_resolution': '2k'}
POOL_4K = dict(POOL_2K, requested_resolution='4k')


def task(params, task_type='google-edit', status='processing'):
    return {'type': task_type, 'status': status, 'params': params}


class TaskDurationEstimateTest(unittest.TestCase):
    def estimator(self, history, clock=lambda: 0):
        self.calls = 0

        def load(task_type):
            self.calls += 1
            return history.get(task_type, [])

        return TaskDurationEstimator(load, clock=clock)

    def test_uses_median_of_the_matching_group(self):
        history = {'google-edit': [(POOL_2K, 40), (POOL_2K, 60), (POOL_2K, 500), (POOL_4K, 120), (POOL_4K, 130), (POOL_4K, 140)]}
        e = self.estimator(history)
        self.assertEqual(e.estimate_seconds(task({**POOL_2K, 'requested_resolution': None, 'quality': '2k'})), 60)
        self.assertEqual(e.estimate_seconds(task({**POOL_2K, 'requested_resolution': None, 'quality': 'hd'})), 130)

    def test_falls_back_to_broader_group_when_samples_are_few(self):
        history = {'google-edit': [(POOL_2K, 50)] * MIN_SAMPLES + [(dict(POOL_2K, requested_resolution='1k'), 10)]}
        self.assertEqual(self.estimator(history).estimate_seconds(task(dict(POOL_2K, requested_resolution='1k'))), 50)

    def test_unknown_without_enough_history_or_for_local_and_finished_tasks(self):
        e = self.estimator({'google-edit': [(POOL_2K, 50)] * (MIN_SAMPLES - 1), 'qwen21-image': [({}, 200)] * 9})
        self.assertIsNone(e.estimate_seconds(task(POOL_2K)))
        self.assertIsNone(e.estimate_seconds(task({}, task_type='qwen21-image')))
        self.assertIsNone(e.estimate_seconds(task(POOL_2K, status='succeeded')))

    def test_history_is_cached_between_polls(self):
        now = [0]
        e = self.estimator({'gpt-edit': [({'resolution': '2k'}, 45)] * MIN_SAMPLES}, clock=lambda: now[0])
        for _ in range(5):
            self.assertEqual(e.estimate_seconds(task({'resolution': '2k'}, task_type='gpt-edit')), 45)
        self.assertEqual(self.calls, 1)
        now[0] = 1000
        e.estimate_seconds(task({'resolution': '2k'}, task_type='gpt-edit'))
        self.assertEqual(self.calls, 2)

    def test_history_errors_never_break_status(self):
        def broken(_task_type):
            raise RuntimeError('db locked')
        self.assertIsNone(TaskDurationEstimator(broken).estimate_seconds(task(POOL_2K)))


if __name__ == '__main__':
    unittest.main()
