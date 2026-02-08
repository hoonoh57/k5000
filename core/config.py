# -*- coding: utf-8 -*-
"""
불변 구조 핵심: YAML 설정을 로드하여 전역 파라미터 딕셔너리로 제공.
이 파일과 strategy.yaml만 있으면 코드 수정 없이 전략 조정 가능.
"""
from __future__ import annotations

import os
import yaml
import logging
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "config", "strategy.yaml"
)

_cache: dict | None = None


def load(path: str = None) -> dict:
    """YAML 설정을 로드하고 캐시한다."""
    global _cache
    if _cache is not None and path is None:
        return _cache

    p = path or _DEFAULT_PATH
    if not os.path.exists(p):
        logger.warning(f"[CONFIG] {p} 없음 - 기본값 사용")
        _cache = {}
        return _cache

    with open(p, "r", encoding="utf-8") as f:
        _cache = yaml.safe_load(f) or {}

    logger.info(f"[CONFIG] 로드 완료: {p}")
    return _cache


def get(key_path: str, default: Any = None) -> Any:
    """
    점(.)으로 구분된 경로로 값을 가져온다.
    예: get("signals.bull.sideways.atr_ratio", 0.85)
    """
    cfg = load()
    keys = key_path.split(".")
    node = cfg
    for k in keys:
        if isinstance(node, dict) and k in node:
            node = node[k]
        else:
            return default
    return node


def reload(path: str = None) -> dict:
    """캐시를 무효화하고 다시 로드한다."""
    global _cache
    _cache = None
    return load(path)
