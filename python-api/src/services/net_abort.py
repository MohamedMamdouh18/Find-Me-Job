"""Killing outbound HTTP calls a run is blocked on.

A blocking socket read cannot be cancelled from another thread, and closing the
httpx client is not enough either: httpx will not reclaim a connection that is
checked out mid read, so the reading thread sits there until the timeout. Shutting
the raw socket down does interrupt it.

Every long outbound call in the pipeline registers its client here, so a stop kills
whichever one is currently blocked — the scoring LLM call, the cover-letter call, or
a scraper fetch. Pause never calls this; it waits for the call to end on its own.
"""

import logging
import socket
import threading

import httpx

logger = logging.getLogger(__name__)

_clients: set[httpx.Client] = set()
_lock = threading.Lock()


def register(client: httpx.Client) -> None:
    with _lock:
        _clients.add(client)


def unregister(client: httpx.Client) -> None:
    with _lock:
        _clients.discard(client)


def _shutdown_pool_sockets(client: httpx.Client) -> int:
    """Shuts down the raw sockets behind one client's connection pool.

    Pool internals are private and version-specific, hence the defensive walk. If
    httpx changes shape this silently finds nothing, which is why
    tests/test_llm_abort.py asserts that a real blocked read actually dies.
    """
    hit = 0
    try:
        pool = client._transport._pool  # type: ignore[attr-defined]
        connections = list(getattr(pool, "connections", []))
    except Exception as e:
        logger.warning(f"Could not reach the httpx connection pool: {e}")
        return 0

    for conn in connections:
        try:
            stream = conn._connection._network_stream  # type: ignore[attr-defined]
            sock = stream.get_extra_info("socket")
            if sock is not None:
                sock.shutdown(socket.SHUT_RDWR)
                hit += 1
        except Exception as e:
            logger.debug(f"Could not shut down a pooled socket: {e}")
    return hit


def abort_active_calls() -> int:
    """Kills every outbound call currently in flight. Returns how many sockets died."""
    with _lock:
        clients = list(_clients)

    total = 0
    for client in clients:
        total += _shutdown_pool_sockets(client)
        try:
            client.close()
        except Exception as e:  # closing under a live read is inherently racy
            logger.warning(f"Closing an in-flight client raised {e}")

    logger.info(f"Aborting in-flight calls: shut down {total} socket(s)")
    return total
