#!/usr/bin/env python3

import json
from pathlib import Path
from typing import Callable, Dict, Optional

import eve_store


EnsureStore = Callable[[], None]
ReadPathResolver = Callable[[Path, bool], Path]
AfterWrite = Callable[[Path], None]


class JsonDocumentRepository:
    def __init__(
        self,
        local_path: Path,
        label: str,
        *,
        ensure_store: EnsureStore,
        read_path_resolver: Optional[ReadPathResolver] = None,
        after_write: Optional[AfterWrite] = None,
    ) -> None:
        self.local_path = local_path
        self.label = label
        self._ensure_store = ensure_store
        self._read_path_resolver = read_path_resolver
        self._after_write = after_write

    def read_path(self, prefer_runtime: bool = False) -> Path:
        self._ensure_store()
        if self._read_path_resolver is None:
            return self.local_path
        return self._read_path_resolver(self.local_path, prefer_runtime)

    def load(self, *, prefer_runtime: bool = False, default: Optional[Dict[str, object]] = None) -> Dict[str, object]:
        read_path = self.read_path(prefer_runtime=prefer_runtime)
        fallback = dict(default or {})
        if not read_path.exists():
            return fallback
        try:
            payload = json.loads(read_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"Invalid {self.label} file at {read_path}: {exc}")
        return payload if isinstance(payload, dict) else fallback

    def save(self, payload: Dict[str, object], *, sort_keys: bool = False) -> None:
        self._ensure_store()
        eve_store.write_json_dict(self.local_path, payload, sort_keys=sort_keys)
        if self._after_write is not None:
            self._after_write(self.local_path)

    def update(self, mutator: Callable[[Dict[str, object]], object], *, sort_keys: bool = False) -> object:
        self._ensure_store()
        _, result = eve_store.mutate_json_dict(self.local_path, mutator, sort_keys=sort_keys)
        if self._after_write is not None:
            self._after_write(self.local_path)
        return result
