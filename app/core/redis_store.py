"""Namespaced Redis access shared by transient infrastructure."""

from __future__ import annotations

from redis import ConnectionPool, Redis


class RedisStore:
    def __init__(self, url: str, namespace: str) -> None:
        self.namespace = namespace.rstrip(":")
        self.pool = ConnectionPool.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
            health_check_interval=30,
            max_connections=20,
        )
        self.client: Redis = Redis(connection_pool=self.pool)

    def key(self, *parts: object) -> str:
        suffix = ":".join(str(part).strip(":") for part in parts)
        return f"{self.namespace}:{suffix}"

    def ping(self) -> None:
        if not self.client.ping():
            raise ConnectionError("Redis did not acknowledge PING.")

    def close(self) -> None:
        self.client.close()
        self.pool.disconnect()
