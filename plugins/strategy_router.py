# -*- coding: utf-8 -*-
"""
plugins/strategy_router.py
==========================
전략 라우터: 레짐 → (신호 생성기 + 파라미터 오버라이드) 매핑.
적응형 파라미터 조정 포함.
"""
from __future__ import annotations
from typing import Dict, Any, Tuple
import logging
import numpy as np

from core.interfaces import IStrategyRouter, ISignalGenerator
from core.types import Regime

logger = logging.getLogger(__name__)


class StrategyRouter(IStrategyRouter):
    """
    레짐별 전략 매핑.
    register()로 레짐-전략-파라미터 오버라이드를 등록하고,
    select()로 현재 레짐에 맞는 조합을 반환.
    """

    def __init__(self, default_gen: ISignalGenerator = None):
        self._strategies: Dict[Regime, Tuple[ISignalGenerator, Dict[str, Any]]] = {}
        self._default_gen = default_gen

    def register(self, regime: Regime,
                 signal_gen: ISignalGenerator,
                 param_overrides: Dict[str, Any]) -> None:
        self._strategies[regime] = (signal_gen, param_overrides)

    def select(self, regime: Regime,
               base_params: Dict[str, Any]) -> Tuple[ISignalGenerator, Dict[str, Any]]:
        if regime in self._strategies:
            sig_gen, overrides = self._strategies[regime]
            merged = dict(base_params)
            merged.update(overrides)
            return sig_gen, merged

        # 등록되지 않은 레짐 → default 또는 SIDEWAYS 폴백
        if self._default_gen:
            return self._default_gen, base_params
        if Regime.SIDEWAYS in self._strategies:
            sig_gen, overrides = self._strategies[Regime.SIDEWAYS]
            merged = dict(base_params)
            merged.update(overrides)
            return sig_gen, merged

        raise ValueError(f"No strategy registered for {regime}")


class AdaptiveParamAdjuster:
    """
    종목별 적응형 파라미터 조정.
    StrategyRouter가 레짐별 기본 파라미터를 선택한 후,
    이 클래스가 종목 ATR/변동성에 맞게 미세 조정.
    """

    def adjust(self, params: Dict[str, Any],
               regime: Regime,
               atr_20: float = 0.0,
               close_price: float = 0.0) -> Dict[str, Any]:
        p = dict(params)

        # JMA 기간: 횡보 → 짧게, 추세 → 길게
        base_jma = p.get("jma_length", 7)
        if regime == Regime.SIDEWAYS:
            p["jma_length"] = max(3, base_jma - 2)
        elif regime == Regime.BULL:
            p["jma_length"] = base_jma + 2

        # ATR 기반 ST 배수 조정
        if atr_20 > 0 and close_price > 0:
            atr_pct = atr_20 / close_price
            base_mult = p.get("st_multiplier", 3.0)
            if atr_pct > 0.04:
                p["st_multiplier"] = round(base_mult * 1.2, 2)
            elif atr_pct < 0.015:
                p["st_multiplier"] = round(base_mult * 0.8, 2)

        # 적응형 목표수익: ATR_20 × 3 / 진입가
        if atr_20 > 0 and close_price > 0:
            adaptive_target = (atr_20 * 3.0) / close_price
            adaptive_target = max(0.03, min(0.20, adaptive_target))
            p["target_profit_pct"] = round(adaptive_target, 4)

        return p
