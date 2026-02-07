# -*- coding: utf-8 -*-
"""
core/event_bus.py
=================
동기식 이벤트 버스. 스레드 안전.
"""
from __future__ import annotations
from typing import Callable, Dict, List, Any
import threading
import logging

logger = logging.getLogger(__name__)


class EventBus:
    def __init__(self) -> None:
        self._listeners: Dict[str, List[Callable[..., None]]] = {}
        self._lock = threading.Lock()

    def subscribe(self, event: str, callback: Callable[..., None]) -> None:
        with self._lock:
            self._listeners.setdefault(event, []).append(callback)

    def unsubscribe(self, event: str, callback: Callable[..., None]) -> None:
        with self._lock:
            if event in self._listeners:
                try:
                    self._listeners[event].remove(callback)
                except ValueError:
                    pass

    def publish(self, event: str, **kwargs: Any) -> None:
        with self._lock:
            handlers = list(self._listeners.get(event, []))
        for cb in handlers:
            try:
                cb(**kwargs)
            except Exception:
                logger.exception(f"EventBus: {event} handler {cb.__name__} failed")

    def clear(self) -> None:
        with self._lock:
            self._listeners.clear()
