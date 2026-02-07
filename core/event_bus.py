# -*- coding: utf-8 -*-
"""
core/event_bus.py  [IMMUTABLE]
==============================
간단한 동기식 이벤트 버스. 모듈 간 느슨한 결합 유지.
"""
from __future__ import annotations
from typing import Callable, Dict, List, Any
import logging

logger = logging.getLogger(__name__)


class EventBus:
    """발행-구독 이벤트 버스 (인스턴스 기반, 싱글톤 아님)."""

    def __init__(self) -> None:
        self._listeners: Dict[str, List[Callable[..., None]]] = {}

    def subscribe(self, event: str, callback: Callable[..., None]) -> None:
        self._listeners.setdefault(event, []).append(callback)

    def unsubscribe(self, event: str, callback: Callable[..., None]) -> None:
        if event in self._listeners:
            try:
                self._listeners[event].remove(callback)
            except ValueError:
                pass

    def publish(self, event: str, **kwargs: Any) -> None:
        for cb in self._listeners.get(event, []):
            try:
                cb(**kwargs)
            except Exception:
                logger.exception(f"EventBus: {event} handler {cb.__name__} failed")

    def clear(self) -> None:
        self._listeners.clear()
