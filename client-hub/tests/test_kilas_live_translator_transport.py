"""Connection scope and failure isolation, with no network or provider calls."""
import sys
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import MagicMock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from kilas_ai import live_translator_transport as transport

URL='https://api.elevenlabs.io/v1/user/subscription'


class TurnTransportTests(unittest.TestCase):
    def test_other_flows_and_origins_keep_their_existing_transport(self):
        client=MagicMock()
        with patch.object(transport.requests,'get') as fallback,patch.object(transport.requests,'Session',return_value=client):
            transport.get(URL,timeout=(5,10))
            with transport.turn_connection():
                transport.get('https://example.test/status',timeout=(5,10))
            transport.get(URL,timeout=(5,10))
        self.assertEqual(fallback.call_count,3);client.get.assert_not_called();client.close.assert_called_once()

    def test_failure_closes_client_restores_fallback_and_never_retries(self):
        client=MagicMock();client.post.side_effect=transport.requests.Timeout('synthetic ambiguous paid POST')
        with patch.object(transport.requests,'Session',return_value=client),patch.object(transport.requests,'get') as fallback:
            with self.assertRaises(transport.requests.Timeout):
                with transport.turn_connection():transport.post(URL,timeout=(5,45))
            transport.get(URL)
        client.post.assert_called_once();client.close.assert_called_once();fallback.assert_called_once()

    def test_nested_turns_restore_outer_client(self):
        first,second=MagicMock(),MagicMock()
        with patch.object(transport.requests,'Session',side_effect=[first,second]):
            with transport.turn_connection():
                transport.get(URL)
                with transport.turn_connection():transport.get(URL)
                transport.get(URL)
        self.assertEqual(first.get.call_count,2);second.get.assert_called_once()
        first.close.assert_called_once();second.close.assert_called_once()

    def test_concurrent_turns_use_distinct_clients_without_cross_thread_state(self):
        barrier=Barrier(2);clients=[]
        def factory():
            client=MagicMock();clients.append(client);return client
        def turn():
            with transport.turn_connection():
                before=transport._client(URL);barrier.wait(timeout=5)
                self.assertIs(transport._client(URL),before)
                transport.get(URL)
                return before
        with patch.object(transport.requests,'Session',side_effect=factory):
            with ThreadPoolExecutor(max_workers=2) as workers:
                first,second=[future.result() for future in [workers.submit(turn),workers.submit(turn)]]
        self.assertIsNot(first,second)
        for client in clients:client.get.assert_called_once();client.close.assert_called_once()

    def test_real_session_retains_zero_automatic_http_retries(self):
        with transport.turn_connection():
            client=transport._client(URL)
            self.assertEqual(client.get_adapter(URL).max_retries.total,0)
            self.assertTrue(client.verify)


if __name__=='__main__':unittest.main()
