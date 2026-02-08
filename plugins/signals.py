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
import logging
from typing import List, Dict, Any
import numpy as np
import pandas as pd
from core.interfaces import ISignalGenerator
from core.types import Signal, Direction

logger = logging.getLogger(__name__)     # <== 이 줄이 반드시 있어야 함

from core import config

class STJMASignalGenerator(ISignalGenerator):

    def generate(self, df, code, params):
        """상승장 주력: ST 상승 + JMA 상승전환 매수."""
        signals = []
        required = ["close", "st_dir", "jma", "jma_slope"]
        if not all(c in df.columns for c in required):
            return signals

        close = df["close"].values
        st_dir = df["st_dir"].values
        jma = df["jma"].values
        jma_slope = df["jma_slope"].values
        jma_dir = (jma_slope > 0).astype(int)
        dates = df["date"].values if "date" in df.columns else df.index.values
        rsi = df["rsi"].values if "rsi" in df.columns else np.full(len(close), 50.0)
        n = len(close)

        slope_min = params.get("jma_slope_min", 0.0)
        rsi_ob = params.get("rsi_overbought", 80)
        rsi_os = params.get("rsi_oversold", 30)

        for i in range(1, n):
            dt = dates[i]
            price = float(close[i])
            cur_st = int(st_dir[i])
            prev_st = int(st_dir[i - 1])
            cur_jma = int(jma_dir[i])
            prev_jma = int(jma_dir[i - 1])
            cur_slope = float(jma_slope[i])
            cur_rsi = float(rsi[i])

            # ── 매수 조건 ──
            buy = False
            reason_parts = []

            if cur_st == 1 and cur_jma == 1 and prev_jma <= 0:
                buy = True
                reason_parts.append("JMA_TURN")
            elif cur_st == 1 and prev_st != 1 and cur_jma == 1:
                buy = True
                reason_parts.append("ST_TURN")

            if buy and slope_min > 0 and cur_slope < slope_min:
                buy = False

            if buy:
                strength = 0.7
                if cur_rsi <= rsi_os:
                    strength = 0.9
                    reason_parts.append("RSI_OS")

                signals.append(Signal(
                    direction=Direction.BUY, code=code,
                    dt=dt, price=price, strength=strength,
                    reason="+".join(reason_parts)
                ))

            # ── 매도 조건 ──
            sell = False
            sell_reason = []

            if cur_st == -1 and prev_st == 1:
                sell = True
                sell_reason.append("ST_REV")
            elif cur_jma == -1 and prev_jma >= 0 and cur_st == 1:
                sell = True
                sell_reason.append("JMA_DOWN")
            elif cur_rsi >= rsi_ob and cur_jma <= 0:
                sell = True
                sell_reason.append("RSI_OB")

            if sell:
                signals.append(Signal(
                    direction=Direction.SELL, code=code,
                    dt=dt, price=price, strength=0.7,
                    reason="+".join(sell_reason)
                ))

        return signals


    def _is_sideways(self, df, idx):
        """YAML 설정 기반 횡보 감지."""
        lookback = 20
        if idx < lookback:
            return False

        window = df.iloc[max(0, idx - lookback):idx + 1]
        count = 0

        atr_ratio = config.get("signals.bull.sideways.atr_ratio", 0.85)
        jma_flips_th = config.get("signals.bull.sideways.jma_flips", 3)
        range_th = config.get("signals.bull.sideways.range_pct", 3.5)
        min_cond = config.get("signals.bull.sideways.min_conditions", 1)

        if 'atr' in df.columns:
            atr_now = df['atr'].iloc[idx]
            atr_avg = window['atr'].mean()
            if atr_avg > 0 and not np.isnan(atr_now):
                if atr_now < atr_avg * atr_ratio:
                    count += 1

        if 'jma_slope' in df.columns:
            slope_window = df['jma_slope'].iloc[max(0, idx - 10):idx + 1]
            if len(slope_window) >= 5:
                signs = np.sign(slope_window.values)
                flips = np.sum(signs[1:] != signs[:-1])
                if flips >= jma_flips_th:
                    count += 1

        if all(c in df.columns for c in ['high', 'low', 'close']):
            if len(window) >= 10:
                avg_close = window['close'].mean()
                if avg_close > 0:
                    range_pct = (
                        (window['high'] - window['low']) / avg_close
                    ).mean() * 100
                    if range_pct < range_th:
                        count += 1

        return count >= min_cond



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
