# -*- coding: utf-8 -*-
"""
plugins/signals.py
==================
매매 신호 생성: 레짐별 전략.
- STJMASignalGenerator: 상승장 주력 (기존)
- BearInverseSignalGenerator: 하락장 인버스
- SidewaysSwingSignalGenerator: 횡보장 단기 스윙
"""
from __future__ import annotations
from typing import List, Dict, Any
import numpy as np
import pandas as pd
from core.interfaces import ISignalGenerator
from core.types import Signal, Direction


class STJMASignalGenerator(ISignalGenerator):
    """상승장 주력: ST 상승 + JMA 상승전환 매수."""

    def generate(self, df: pd.DataFrame, code: str,
                 params: Dict[str, Any]) -> List[Signal]:
        signals: List[Signal] = []
        slope_min = params.get("jma_slope_min", 0.0)
        rsi_ob = params.get("rsi_ob", 80)
        rsi_os = params.get("rsi_os", 30)

        required = ["close", "st_dir", "jma", "jma_slope"]
        for col in required:
            if col not in df.columns:
                return signals

        close = df["close"].values
        st_dir = df["st_dir"].values
        jma_slope = df["jma_slope"].values
        dates = df["date"].values if "date" in df.columns else df.index.values
        rsi = df["rsi"].values if "rsi" in df.columns else np.full(len(df), 50.0)
        n = len(close)

        jma_dir = np.zeros(n, dtype=int)
        jma_dir[jma_slope > 0] = 1
        jma_dir[jma_slope < 0] = -1

        for i in range(2, n):
            dt = dates[i]
            cur_st = st_dir[i]
            prev_st = st_dir[i - 1]
            cur_jma = jma_dir[i]
            prev_jma = jma_dir[i - 1]
            cur_slope = jma_slope[i]
            cur_rsi = rsi[i]

            buy = False
            reason = ""
            strength = 0.0

            if cur_st == 1 and cur_jma == 1 and prev_jma <= 0:
                buy = True
                reason = "ST_UP+JMA_TURN_UP"
                strength = 0.7
            elif cur_st == 1 and prev_st != 1 and cur_jma == 1:
                buy = True
                reason = "ST_TURN_UP+JMA_UP"
                strength = 0.8

            if buy and slope_min > 0:
                if pd.isna(cur_slope) or cur_slope < slope_min:
                    buy = False

            if buy and not np.isnan(cur_rsi) and cur_rsi <= rsi_os:
                strength = min(strength + 0.2, 1.0)
                reason += "+RSI_OS"

            if buy:
                signals.append(Signal(
                    direction=Direction.BUY, code=code, dt=dt,
                    price=float(close[i]), strength=strength,
                    reason=f"{reason}(slope={cur_slope:.2f},str={strength:.1f})",
                ))
                continue

            sell = False
            if cur_st == -1 and prev_st == 1:
                sell = True
                reason = "ST_REVERSAL_DOWN"
                strength = 1.0
            elif cur_jma == -1 and prev_jma >= 0 and cur_st == 1:
                sell = True
                reason = "JMA_TURN_DOWN"
                strength = 0.5
            elif not np.isnan(cur_rsi) and cur_rsi >= rsi_ob and cur_jma <= 0:
                sell = True
                reason = "RSI_OB+JMA_WEAK"
                strength = 0.6

            if sell:
                signals.append(Signal(
                    direction=Direction.SELL, code=code, dt=dt,
                    price=float(close[i]), strength=strength,
                    reason=f"{reason}(str={strength:.1f})",
                ))

        return signals


class BearInverseSignalGenerator(ISignalGenerator):
    """
    하락장 인버스 전략:
    - ST 하락 + JMA 하락전환 → 인버스 ETF 매수
    - ST 상승전환 → 즉시 매도
    """

    def generate(self, df: pd.DataFrame, code: str,
                 params: Dict[str, Any]) -> List[Signal]:
        signals: List[Signal] = []
        required = ["close", "st_dir", "jma_slope"]
        for col in required:
            if col not in df.columns:
                return signals

        close = df["close"].values
        st_dir = df["st_dir"].values
        jma_slope = df["jma_slope"].values
        dates = df["date"].values if "date" in df.columns else df.index.values
        n = len(close)

        jma_dir = np.zeros(n, dtype=int)
        jma_dir[jma_slope > 0] = 1
        jma_dir[jma_slope < 0] = -1

        for i in range(2, n):
            dt = dates[i]
            cur_st = st_dir[i]
            prev_st = st_dir[i - 1]
            cur_jma = jma_dir[i]
            prev_jma = jma_dir[i - 1]

            # 매수: ST 하락 + JMA 하락전환
            if cur_st == -1 and cur_jma == -1 and prev_jma >= 0:
                signals.append(Signal(
                    direction=Direction.BUY, code=code, dt=dt,
                    price=float(close[i]), strength=0.7,
                    reason="BEAR_INVERSE_BUY(ST_DOWN+JMA_TURN_DOWN)",
                ))
                continue

            if cur_st == -1 and prev_st != -1 and cur_jma == -1:
                signals.append(Signal(
                    direction=Direction.BUY, code=code, dt=dt,
                    price=float(close[i]), strength=0.8,
                    reason="BEAR_INVERSE_BUY(ST_TURN_DOWN+JMA_DOWN)",
                ))
                continue

            # 매도: ST 상승전환
            if cur_st == 1 and prev_st == -1:
                signals.append(Signal(
                    direction=Direction.SELL, code=code, dt=dt,
                    price=float(close[i]), strength=1.0,
                    reason="BEAR_INVERSE_SELL(ST_REVERSAL_UP)",
                ))
            elif cur_jma == 1 and prev_jma <= 0 and cur_st == -1:
                signals.append(Signal(
                    direction=Direction.SELL, code=code, dt=dt,
                    price=float(close[i]), strength=0.5,
                    reason="BEAR_INVERSE_SELL(JMA_TURN_UP)",
                ))

        return signals


class SidewaysSwingSignalGenerator(ISignalGenerator):
    """
    횡보장 단기 스윙:
    - RSI 과매도 근처 + JMA 상승전환 → 매수
    - RSI 과매수 OR JMA 하락전환 → 매도
    """

    def generate(self, df: pd.DataFrame, code: str,
                 params: Dict[str, Any]) -> List[Signal]:
        signals: List[Signal] = []
        required = ["close", "jma_slope"]
        for col in required:
            if col not in df.columns:
                return signals

        close = df["close"].values
        jma_slope = df["jma_slope"].values
        dates = df["date"].values if "date" in df.columns else df.index.values
        rsi = (
            df["rsi"].values if "rsi" in df.columns
            else np.full(len(df), 50.0)
        )
        rsi_os = params.get("rsi_os", 35)
        rsi_ob = params.get("rsi_ob", 80)
        n = len(close)

        jma_dir = np.zeros(n, dtype=int)
        jma_dir[jma_slope > 0] = 1
        jma_dir[jma_slope < 0] = -1

        for i in range(2, n):
            dt = dates[i]
            cur_jma = jma_dir[i]
            prev_jma = jma_dir[i - 1]
            cur_rsi = rsi[i]

            # 매수
            if cur_rsi <= rsi_os + 10 and cur_jma == 1 and prev_jma <= 0:
                signals.append(Signal(
                    direction=Direction.BUY, code=code, dt=dt,
                    price=float(close[i]), strength=0.6,
                    reason=f"SWING_BUY(RSI={cur_rsi:.0f}+JMA_UP)",
                ))
                continue

            # 매도
            sell_reason_parts = []
            if not np.isnan(cur_rsi) and cur_rsi >= rsi_ob:
                sell_reason_parts.append(f"RSI_OB={cur_rsi:.0f}")
            if cur_jma == -1 and prev_jma >= 0:
                sell_reason_parts.append("JMA_DOWN")

            if sell_reason_parts:
                signals.append(Signal(
                    direction=Direction.SELL, code=code, dt=dt,
                    price=float(close[i]), strength=0.6,
                    reason=f"SWING_SELL({'+'.join(sell_reason_parts)})",
                ))

        return signals
