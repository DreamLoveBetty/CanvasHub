"""Official tests for recent-history visibility after recorded files disappear."""
import unittest
from pathlib import Path

from backend.services.history_policy import (
    result_file_keys,
    task_should_render,
    task_should_render_display,
    task_result_files,
    visible_task_result_files,
)
from backend.services.history_query import collect_renderable_history_tasks
from backend.services.history_format import format_history_task


class ResultFileKeysTest(unittest.TestCase):
    def test_url_and_basename_share_a_key(self):
        keys = result_file_keys('/image/foo%20bar.png?w=420')
        self.assertIn('foo bar.png', keys)
        self.assertTrue(keys & result_file_keys('foo bar.png'))


class VisibleResultFilesTest(unittest.TestCase):
    def present(self, existing):
        existing = set(existing)
        return lambda task, name: name in existing or Path(name).name in existing

    def test_multi_file_task_keeps_only_existing_and_leaves_siblings(self):
        task = {'result_files': ['a.png', 'b.png', 'c.png'], 'result_file': 'a.png', 'status': 'succeeded'}
        visible, primary, meta = visible_task_result_files(
            task, task_result_files=task_result_files, is_present=self.present({'b.png', 'c.png'}))
        self.assertEqual(visible, ['b.png', 'c.png'])
        self.assertEqual(primary, 'b.png')
        self.assertFalse(meta['missing_result_files'])
        self.assertTrue(meta['had_recorded_files'])

    def test_all_recorded_files_gone_is_missing_not_a_never_had_file_task(self):
        task = {'result_files': ['gone.png'], 'result_file': 'gone.png', 'status': 'succeeded'}
        visible, primary, meta = visible_task_result_files(
            task, task_result_files=task_result_files, is_present=self.present(set()))
        self.assertEqual(visible, [])
        self.assertEqual(primary, '')
        self.assertTrue(meta['missing_result_files'])
        self.assertTrue(task_should_render_display('succeeded', visible, had_recorded_files=True))
        self.assertTrue(task_should_render_display('failed', visible, had_recorded_files=True))
        self.assertFalse(task_should_render('failed', []))
        self.assertFalse(task_should_render_display('failed', [], had_recorded_files=False))
        self.assertTrue(task_should_render_display('queued', [], had_recorded_files=False))


class HistoryCollectAndFormatFilterTest(unittest.TestCase):
    def test_collect_keeps_missing_recorded_and_inflight_drops_never_had_failed(self):
        tasks = [
            {'task_id': 'keep-partial', 'status': 'succeeded', 'result_files': ['live.png', 'dead.png'], 'created_at': 3},
            {'task_id': 'keep-missing', 'status': 'telegram_failed', 'result_files': ['dead.png'], 'created_at': 2},
            {'task_id': 'keep-queued', 'status': 'queued', 'result_files': [], 'created_at': 1},
            {'task_id': 'hide-failed', 'status': 'failed', 'result_files': [], 'created_at': 0},
        ]

        def is_present(task, name):
            return name == 'live.png'

        def visible(task):
            return visible_task_result_files(task, task_result_files=task_result_files, is_present=is_present)[:2]

        def should_include(task, _visible):
            visible_files, _primary, meta = visible_task_result_files(
                task, task_result_files=task_result_files, is_present=is_present)
            return task_should_render_display(task.get('status'), visible_files, had_recorded_files=meta['had_recorded_files'])

        rows = collect_renderable_history_tasks(
            load_database_tasks=lambda: tasks,
            load_legacy_tasks=lambda: [],
            task_timestamp=lambda task: task['created_at'],
            task_result_files=visible,
            should_render=task_should_render,
            dedupe_key=lambda task: ('task', task['task_id']),
            should_include=should_include,
        )
        self.assertEqual([row['task_id'] for row in rows], ['keep-partial', 'keep-missing', 'keep-queued'])

    def test_format_omits_missing_paths_and_flags_empty_archive(self):
        task = {'type': 'google-gen', 'status': 'succeeded', 'result_files': ['dead.png', 'live.png'], 'result_file': 'dead.png'}

        def is_present(task, name):
            return name == 'live.png'

        visible, primary, meta = visible_task_result_files(
            task, task_result_files=task_result_files, is_present=is_present)
        row = format_history_task(
            task,
            task_result_files=lambda _task: (visible, primary),
            h3_task_type='minimax-h3-video',
            public_h3_params=lambda params: params,
            safe_basename=lambda name: Path(name).name,
        )
        self.assertEqual(row['result_files'], ['live.png'])
        self.assertEqual(row['image_paths'], ['/image/live.png'])
        self.assertFalse(meta['missing_result_files'])

        gone = {'type': 'google-gen', 'status': 'failed', 'result_files': ['dead.png'], 'result_file': 'dead.png'}
        visible, primary, meta = visible_task_result_files(
            gone, task_result_files=task_result_files, is_present=lambda *_: False)
        row = format_history_task(
            gone,
            task_result_files=lambda _task: (visible, primary),
            h3_task_type='minimax-h3-video',
            public_h3_params=lambda params: params,
            safe_basename=lambda name: Path(name).name,
        )
        self.assertEqual(row['result_files'], [])
        self.assertEqual(row['image_paths'], [])
        self.assertTrue(meta['missing_result_files'])


class ResolverDoesNotHideOnError(unittest.TestCase):
    def test_is_present_exception_is_treated_as_still_available_by_callers(self):
        # The policy itself only uses the callback; wrappers must not map errors to missing.
        # This documents the contract the server wrapper follows.
        task = {'result_files': ['maybe.png'], 'result_file': 'maybe.png'}

        def raise_present(task, name):
            raise RuntimeError('lookup failed')

        with self.assertRaises(RuntimeError):
            visible_task_result_files(task, task_result_files=task_result_files, is_present=raise_present)


if __name__ == '__main__':
    unittest.main()
