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
    """상승장 주력: ST 상승 + JMA 상승전환 매수 (횡보 필터 포함)."""

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

            # ── 횡보 필터: 매수 직전 횡보 감지 시 억제 ──
            if buy and self._is_sideways(df, i):
                logger.debug(
                    f"[SIGNAL] {code} {dt}: 횡보 감지 - 매수 억제 "
                    f"({reason})"
                )
                buy = False
                # 억제된 것도 기록하려면 HOLD 신호로 남김
                signals.append(Signal(
                    direction=Direction.HOLD, code=code, dt=dt,
                    price=float(close[i]), strength=0.0,
                    reason=f"SIDEWAYS_FILTER({reason})",
                ))
                continue

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

    def _is_sideways(self, df: pd.DataFrame, idx: int) -> bool:
        """
        매수 시점(idx)에서 과거 데이터만으로 횡보 여부 판단.
        미래 데이터 참조 없음 - 모두 idx 이전 데이터만 사용.

        조건 (2개 이상 충족 시 횡보):
          1) ATR 축소: 현재 ATR < 20일 평균 ATR * 0.7
          2) JMA slope 진동: 최근 10일간 부호 전환 3회 이상
          3) 가격 레인지 축소: 최근 20일 일중 변동폭 평균 < 2%
        """
        lookback = 20
        if idx < lookback:
            return False

        sideways_count = 0

        # 조건 1: ATR 축소 (변동성 감소)
        if 'atr' in df.columns:
            atr_now = df['atr'].iloc[idx]
            atr_window = df['atr'].iloc[max(0, idx - lookback):idx]
            atr_avg = atr_window.mean()
            if atr_avg > 0 and not np.isnan(atr_now):
                if atr_now < atr_avg * 0.7:
                    sideways_count += 1

        # 조건 2: JMA slope 방향 진동 (추세 부재)
        if 'jma_slope' in df.columns:
            slope_window = df['jma_slope'].iloc[max(0, idx - 10):idx + 1]
            if len(slope_window) >= 5:
                signs = (slope_window > 0).astype(int)
                flips = signs.diff().abs().sum()
                if flips >= 3:
                    sideways_count += 1

        # 조건 3: 일중 변동폭 축소 (좁은 레인지)
        if all(c in df.columns for c in ['high', 'low', 'close']):
            window = df.iloc[max(0, idx - lookback):idx + 1]
            if len(window) >= 10:
                avg_close = window['close'].mean()
                if avg_close > 0:
                    range_pct = (
                        (window['high'] - window['low']) / avg_close
                    ).mean() * 100
                    if range_pct < 2.0:
                        sideways_count += 1

        return sideways_count >= 2


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
