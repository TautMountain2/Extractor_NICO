"""Transporte HTTP reutilizable para Banxico API privada."""

from __future__ import annotations

import io
import json
import time
import urllib.error
from dataclasses import dataclass
from typing import Any

import urllib3
from urllib3.util import Timeout

_TRANSIENT_HTTP_STATUS = {408, 429, 500, 502, 503, 504}


@dataclass(slots=True)
class BanxicoHttpResponse:
    status: int
    data: bytes
    headers: dict[str, str]
    elapsed_seconds: float
    attempt: int


class BanxicoHttpClient:
    def __init__(
        self,
        *,
        timeout_seconds: int,
        connect_timeout_seconds: int | None = None,
        pool_maxsize: int = 4,
    ) -> None:
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.connect_timeout_seconds = (
            max(1, int(connect_timeout_seconds))
            if connect_timeout_seconds is not None
            else min(15, self.timeout_seconds)
        )
        self.pool_maxsize = max(1, int(pool_maxsize))
        self._default_headers: dict[str, str] = {}
        self._pool = self._build_pool()

    def _build_pool(self) -> urllib3.PoolManager:
        return urllib3.PoolManager(
            num_pools=1,
            maxsize=self.pool_maxsize,
            block=True,
            retries=False,
            timeout=Timeout(
                connect=self.connect_timeout_seconds,
                read=self.timeout_seconds,
            ),
        )

    def update_session_headers(self, headers: dict[str, str]) -> None:
        self._default_headers = {
            str(k): str(v)
            for k, v in headers.items()
            if k
            and v
            and str(k).lower() not in {"content-length", "host", "connection"}
        }

    def request_json(
        self,
        *,
        url: str,
        payload: dict[str, Any],
        max_attempts: int,
        retry_delay_seconds: float,
        headers_extra: dict[str, str] | None = None,
    ) -> BanxicoHttpResponse:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        last_exc: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            started = time.perf_counter()
            response = None

            headers = dict(self._default_headers)
            if headers_extra:
                headers.update(
                    {
                        str(k): str(v)
                        for k, v in headers_extra.items()
                        if k and v and str(k).lower() not in {"content-length", "host", "connection"}
                    }
                )
            headers.setdefault("Content-Type", "application/json;charset=UTF-8")

            try:
                response = self._pool.request(
                    "POST",
                    url,
                    body=body,
                    headers=headers,
                    preload_content=True,
                    decode_content=False,
                )
                elapsed = time.perf_counter() - started
                status = int(response.status)

                if status >= 400:
                    err = urllib.error.HTTPError(
                        url=url,
                        code=status,
                        msg=f"HTTP {status}",
                        hdrs=response.headers,
                        fp=io.BytesIO(response.data),
                    )
                    if status in _TRANSIENT_HTTP_STATUS and attempt < max_attempts:
                        last_exc = err
                        time.sleep(retry_delay_seconds * attempt)
                        continue
                    raise err

                return BanxicoHttpResponse(
                    status=status,
                    data=bytes(response.data),
                    headers={str(k): str(v) for k, v in response.headers.items()},
                    elapsed_seconds=elapsed,
                    attempt=attempt,
                )

            except urllib.error.HTTPError as exc:
                last_exc = exc
                if exc.code in _TRANSIENT_HTTP_STATUS and attempt < max_attempts:
                    time.sleep(retry_delay_seconds * attempt)
                    continue
                raise

            except (urllib3.exceptions.HTTPError, OSError, TimeoutError) as exc:
                last_exc = exc
                if attempt < max_attempts:
                    time.sleep(retry_delay_seconds * attempt)
                    continue
                raise

            finally:
                if response is not None:
                    response.release_conn()

        assert last_exc is not None
        raise last_exc

    def close(self) -> None:
        self._pool.clear()