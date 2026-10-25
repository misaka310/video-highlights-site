from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import verify_deployed_data


class Response:
    def __init__(self, status: int):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class DeployedDataVerificationTests(unittest.TestCase):
    def test_excluded_detail_check_retries_stale_response_until_404(self):
        requests = []

        def open_request(request, timeout):
            requests.append(request)
            if len(requests) % 2:
                return Response(200)
            raise HTTPError(request.full_url, 404, "Not Found", {}, None)

        with (
            patch.object(verify_deployed_data, "PERMANENTLY_EXCLUDED_PUBLIC_VOD_IDS", frozenset({"excluded-test-vod"})),
            patch.object(verify_deployed_data.urllib.request, "urlopen", side_effect=open_request),
            patch.object(verify_deployed_data.time, "sleep"),
        ):
            verify_deployed_data.verify_excluded_vod_details(
                "https://site.invalid/",
                time.monotonic() + 5,
            )

        expected_ids = ["excluded-test-vod"]
        self.assertEqual(2 * len(expected_ids), len(requests))
        for index, vod_id in enumerate(expected_ids):
            stale_request = requests[index * 2]
            confirmed_request = requests[index * 2 + 1]
            self.assertIn(f"/data/vods/{vod_id}.json?deployment-check=", stale_request.full_url)
            self.assertIn(f"/data/vods/{vod_id}.json?deployment-check=", confirmed_request.full_url)
            self.assertEqual("no-cache", stale_request.get_header("Cache-control"))

    def test_excluded_detail_check_fails_if_200_persists_to_deadline(self):
        with (
            patch.object(verify_deployed_data, "PERMANENTLY_EXCLUDED_PUBLIC_VOD_IDS", frozenset({"excluded-test-vod"})),
            patch.object(verify_deployed_data.urllib.request, "urlopen", return_value=Response(200)),
            patch.object(verify_deployed_data.time, "monotonic", side_effect=[0, 0, 2]),
        ):
            with self.assertRaisesRegex(SystemExit, "remained reachable after 200"):
                verify_deployed_data.verify_excluded_vod_details("https://site.invalid", deadline=1)

    def test_empty_exclusion_set_skips_detail_404_check(self):
        with (
            patch.object(verify_deployed_data, "PERMANENTLY_EXCLUDED_PUBLIC_VOD_IDS", frozenset()),
            patch.object(verify_deployed_data.urllib.request, "urlopen") as open_request,
        ):
            verify_deployed_data.verify_excluded_vod_details("https://site.invalid", deadline=time.monotonic() + 5)

        open_request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
