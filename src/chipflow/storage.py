"""持久化。v1 用檔案;DB 為介面(P2 由 agent 依 infra 決策實作)。"""
from __future__ import annotations

import json
import os
from typing import Any


class Storage:
    def save_json(self, name: str, obj: Any) -> str: ...
    def save_text(self, name: str, text: str) -> str: ...
    def load_json(self, name: str) -> Any: ...


class FileStorage(Storage):
    def __init__(self, out_dir: str):
        self.out_dir = out_dir
        os.makedirs(out_dir, exist_ok=True)

    def _p(self, name: str) -> str:
        return os.path.join(self.out_dir, name)

    def save_json(self, name: str, obj: Any) -> str:
        p = self._p(name)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        return p

    def save_text(self, name: str, text: str) -> str:
        p = self._p(name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        return p

    def load_json(self, name: str) -> Any:
        with open(self._p(name), encoding="utf-8") as f:
            return json.load(f)


# TODO(agent, P2): DbStorage — 依 infra 決策(既有 MySQL / 時序 DB)實作,
#   並提供把 series 寫入 Prometheus/DB 供 Grafana 讀取的路徑。
