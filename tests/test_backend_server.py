"""Backend lifecycle regressions; no Windows or game dependencies required."""
import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import backend_server


class BackendLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_late_engine_callback_is_ignored_after_shutdown(self):
        server = backend_server.EDAPEngineServer()
        server.loop = asyncio.new_event_loop()
        server.loop.close()
        server.shutdown_engine()
        server.ap_callback('log', 'worker finished after shutdown')

    async def test_broadcast_allows_client_membership_changes_during_send(self):
        server = backend_server.EDAPEngineServer()
        newcomer = AsyncMock()
        client = AsyncMock()

        async def join_during_send(_message):
            server.connected_clients.add(newcomer)

        client.send.side_effect = join_during_send
        server.connected_clients.add(client)
        await server.broadcast({"type": "pong"})
        client.send.assert_awaited_once()
        newcomer.send.assert_not_awaited()

    async def test_initial_send_failure_removes_client(self):
        server = backend_server.EDAPEngineServer()
        client = AsyncMock()
        client.send.side_effect = RuntimeError("connection failed")
        with self.assertRaisesRegex(RuntimeError, "connection failed"):
            await server.client_handler(client)
        self.assertFalse(server.connected_clients)

    async def test_startup_failure_cancels_telemetry_task(self):
        server = backend_server.EDAPEngineServer()
        with patch.object(server, "init_engine"), patch.object(
            backend_server.websockets, "serve", side_effect=OSError("port in use")
        ):
            with self.assertRaisesRegex(OSError, "port in use"):
                await server.main()
        await asyncio.sleep(0)
        self.assertFalse(any(
            task.get_coro().__name__ == "periodic_telemetry_and_screenshots"
            for task in asyncio.all_tasks() if task is not asyncio.current_task()
        ))


if __name__ == "__main__":
    unittest.main()
