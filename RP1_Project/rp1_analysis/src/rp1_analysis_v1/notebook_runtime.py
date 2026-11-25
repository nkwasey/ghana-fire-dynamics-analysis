"""Scoped kernel transport for clean native Windows notebook shutdown."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nbclient import NotebookClient
    from nbformat import NotebookNode


def _execute_in_owned_selector_loop(client: NotebookClient) -> NotebookNode:
    # nbclient's synchronous adapter caches a loop outside our ownership. On
    # Windows its default Proactor loop requires a Tornado selector thread for
    # ZMQ; leaving that cached loop open can crash interpreter shutdown after a
    # successful notebook. Await the public async API in a loop we close here.
    # A custom loop factory leaves the caller's event-loop policy/loop untouched.
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        return runner.run(client.async_execute())


def execute_notebook_client(client: NotebookClient) -> NotebookNode:
    """Execute a client, preserving errors and the caller's global loop policy.

    Native Windows uses an owned selector loop compatible with ZMQ. A caller
    already inside an event loop is served on a joined worker thread, rather
    than nesting event loops or changing the application's policy. Other
    platforms retain nbclient's existing synchronous transport.
    """
    if sys.platform != "win32":
        return client.execute()
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return _execute_in_owned_selector_loop(client)
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="rp1-notebook") as pool:
        return pool.submit(_execute_in_owned_selector_loop, client).result()
