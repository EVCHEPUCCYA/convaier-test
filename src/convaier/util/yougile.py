"""YouGile REST API клиент (только stdlib urllib)."""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

log = logging.getLogger("convaier")


class YouGileClient:
    """Тонкий HTTP-клиент для YouGile REST API без сторонних зависимостей."""

    def __init__(self, base_url: str, token: str, column_id: str, timeout: int = 30) -> None:
        self._base = base_url.rstrip("/")
        self._token = token
        self._column_id = column_id
        self._timeout = timeout

    def create_task(self, title: str, description: str = "") -> dict:
        """Создать задачу в колонке YouGile. Возвращает созданный объект задачи."""
        body: dict[str, Any] = {
            "title": title,
            "columnId": self._column_id,
        }
        if description:
            body["description"] = description
        return self._request("POST", "/tasks", body)

    def find_tasks_by_title(self, title: str) -> list[dict]:
        """Найти задачи с совпадающим title в данной колонке (защита от дублей)."""
        path = f"/tasks?columnId={urllib.parse.quote(self._column_id)}&limit=100"
        try:
            result = self._request("GET", path)
            items = result.get("content", result) if isinstance(result, dict) else result
            if not isinstance(items, list):
                return []
            return [t for t in items if t.get("title", "") == title]
        except RuntimeError:
            return []

    def _request(self, method: str, path: str, body: dict | None = None) -> Any:
        """Выполнить HTTP-запрос к YouGile API."""
        url = self._base + path
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers: dict[str, str] = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }
        if data is not None:
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as e:
            body_text = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"YouGile HTTP {e.code}: {body_text[:200]}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"YouGile недоступен ({e.reason}). Проверьте base_url.") from e
