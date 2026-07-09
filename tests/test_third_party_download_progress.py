import unittest
from unittest.mock import patch

from backend import server


class ThirdPartyDownloadProgressTest(unittest.TestCase):
    def test_download_progress_callback_persists_progress_and_retry_event(self):
        with patch.object(server, "_is_task_canceled", return_value=False), \
             patch.object(server, "update_task_status") as update_status, \
             patch.object(server, "_record_generation_event") as record_event, \
             patch.object(server.time, "time", return_value=1710000020):
            callback = server._make_third_party_download_progress_callback("gpt_task")
            callback({
                "event": "download_first_byte",
                "item_index": 1,
                "item_count": 1,
                "bytes_received": 0,
                "total_bytes": 100,
            })
            callback({
                "event": "download_progress",
                "item_index": 1,
                "item_count": 1,
                "bytes_received": 50,
                "total_bytes": 100,
            })
            callback({
                "event": "download_retry",
                "attempt": 1,
                "next_attempt": 2,
                "max_attempts": 3,
                "item_index": 1,
                "item_count": 1,
                "bytes_received": 50,
                "total_bytes": 100,
                "error_type": "ChunkedEncodingError",
            })

        self.assertTrue(
            any(call.kwargs.get("first_byte_at") == 1710000020 for call in update_status.call_args_list)
        )
        self.assertTrue(
            any(call.kwargs.get("bytes_received") == 50 for call in update_status.call_args_list)
        )
        self.assertTrue(
            any(call.kwargs.get("transport_error_type") == "ChunkedEncodingError" for call in update_status.call_args_list)
        )
        retry_events = [call for call in record_event.call_args_list if call.args[1] == "third_party_download_retry"]
        self.assertEqual(len(retry_events), 1)
        self.assertEqual(retry_events[0].kwargs["severity"], "warning")


if __name__ == "__main__":
    unittest.main()
