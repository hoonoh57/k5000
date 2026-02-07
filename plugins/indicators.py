# -*- coding: utf-8 -*-
"""
plugins/indicators.py  [MUTABLE]
================================
기술적 지표 플러그인: SuperTrend, JMA(VB.NET 완전 포팅), RSI.
"""
from __future__ import annotations
from typing import Dict, Any
import numpy as np
import pandas as pd
from core.interfaces import IIndicator


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SuperTrend
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class SuperTrendIndicator(IIndicator):
    def name(self) -> str:
        return "SuperTrend"

    def compute(self, df: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
        period = params.get("st_period", 14)
        multiplier = params.get("st_multiplier", params.get("st_mult", 2.0))

        high = df["high"].values.astype(float)
        low = df["low"].values.astype(float)
        close = df["close"].values.astype(float)
        n = len(close)

        if n < period + 2:
            df = df.copy()
            df["st"] = np.nan
            df["st_dir"] = 0
            df["atr"] = np.nan
            return df

        # ATR
        tr = np.zeros(n)
        for i in range(1, n):
            tr[i] = max(high[i] - low[i],
                        abs(high[i] - close[i - 1]),
                        abs(low[i] - close[i - 1]))
        tr[0] = high[0] - low[0]

        atr = np.full(n, np.nan)
        atr[period] = np.mean(tr[1:period + 1])
        for i in range(period + 1, n):
            atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

        # 밴드
        hl2 = (high + low) / 2.0
        upper_basic = hl2 + multiplier * atr
        lower_basic = hl2 - multiplier * atr

        upper_band = np.copy(upper_basic)
        lower_band = np.copy(lower_basic)
        st = np.zeros(n)
        direction = np.zeros(n, dtype=int)

        for i in range(period + 1, n):
            # 상한 밴드
            if upper_basic[i] < upper_band[i - 1] or close[i - 1] > upper_band[i - 1]:
                upper_band[i] = upper_basic[i]
            else:
                upper_band[i] = upper_band[i - 1]

            # 하한 밴드
            if lower_basic[i] > lower_band[i - 1] or close[i - 1] < lower_band[i - 1]:
                lower_band[i] = lower_basic[i]
            else:
                lower_band[i] = lower_band[i - 1]

            # 방향 결정
            if i == period + 1:
                direction[i] = 1 if close[i] > upper_band[i] else -1
            else:
                prev_dir = direction[i - 1]
                if prev_dir == -1 and close[i] > upper_band[i]:
                    direction[i] = 1
                elif prev_dir == 1 and close[i] < lower_band[i]:
                    direction[i] = -1
                else:
                    direction[i] = prev_dir

            st[i] = lower_band[i] if direction[i] == 1 else upper_band[i]

        st[:period + 1] = np.nan
        direction[:period + 1] = 0

        df = df.copy()
        df["st"] = st
        df["st_dir"] = direction
        df["atr"] = atr
        return df


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  JMA — VB.NET 완전 포팅 (strategy.py JMACalculator 이식)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class _JMACore:
    """Jurik Moving Average 핵심 계산 — VB.NET → Python 1:1 포팅.
    
    Jurik 적응형 변동성 밴드(uBand/lBand),
    동적 alpha, 3단계 적응 필터(EMA → Kalman → Jurik) 포함.
    """

    def calculate(self, prices: np.ndarray, period: int = 7,
                  phase: int = 50, power: int = 2):
        """
        반환: (jma, jma_up, jma_down, jma_slope) — 각각 numpy 배열
        jma_up: JMA 상승 구간만 값, 나머지 NaN
        jma_down: JMA 하락 구간만 값, 나머지 NaN
        jma_slope: 1일 차분 (current_jma - prev_jma)
        """
        n = len(prices)
        if n == 0:
            empty = np.full(0, np.nan)
            return empty.copy(), empty.copy(), empty.copy(), empty.copy()

        # ── PhaseRatio 계산 ──
        if phase < -100:
            phase_ratio = 0.5
        elif phase > 100:
            phase_ratio = 2.5
        else:
            phase_ratio = phase / 100.0 + 1.5

        # ── 기본 계수 ──
        _len = max(1.0, 0.5 * (period - 1))
        log_val = np.log(np.sqrt(_len))
        log2 = np.log(2.0)
        len1 = max(log_val / log2 + 2.0, 0.0)
        pow1 = max(len1 - 2.0, 0.5)
        len2 = len1 * np.sqrt(_len)
        beta_coeff = 0.45 * (period - 1) / (0.45 * (period - 1) + 2.0)
        bet = len2 / (len2 + 1.0)

        sum_length = 10
        avg_len = 65

        # ── 결과 배열 ──
        jma_arr = np.full(n, np.nan)
        up_arr = np.full(n, np.nan)
        down_arr = np.full(n, np.nan)
        slope_arr = np.full(n, np.nan)

        # ── 변동성 추적 ──
        volty = np.zeros(n)
        v_sum = np.zeros(n)
        uBand = prices[0]
        lBand = prices[0]
        ma1 = prices[0]
        det0 = 0.0
        det1 = 0.0
        prev_jma = prices[0]

        for i in range(n):
            price = prices[i]

            if i == 0:
                jma_arr[0] = price
                up_arr[0] = price
                down_arr[0] = price
                slope_arr[0] = 0.0
                prev_jma = price
                ma1 = price
                uBand = price
                lBand = price
                continue

            # ── 가격 변동성 (Jurik Bands) ──
            del1 = price - uBand
            del2 = price - lBand
            if abs(del1) != abs(del2):
                volty[i] = max(abs(del1), abs(del2))
            else:
                volty[i] = 0.0

            # ── 상대 변동성 ──
            start_idx = max(i - sum_length, 0)
            v_sum[i] = v_sum[i - 1] + (volty[i] - volty[start_idx]) / sum_length

            avg_start = max(i - avg_len, 0)
            avg_volty = np.mean(v_sum[avg_start:i + 1])

            if avg_volty == 0:
                d_volty = 0.0
            else:
                d_volty = volty[i] / avg_volty

            r_volty_max = np.power(len1, 1.0 / pow1) if len1 > 0 and pow1 > 0 else 1.0
            r_volty = max(1.0, min(r_volty_max, d_volty))

            # ── 동적 alpha ──
            pow2 = np.power(r_volty, pow1)
            kv = np.power(bet, np.sqrt(pow2))

            # ── Jurik Bands 갱신 ──
            if del1 > 0:
                uBand = price
            else:
                uBand = price - kv * del1
            if del2 < 0:
                lBand = price
            else:
                lBand = price - kv * del2

            # ── Dynamic Factor ──
            alpha_power = np.power(r_volty, pow1)
            alpha = np.power(beta_coeff, alpha_power)

            # ── 1단계: 적응 EMA ──
            ma1 = (1.0 - alpha) * price + alpha * ma1

            # ── 2단계: 칼만 필터 ──
            det0 = (price - ma1) * (1.0 - beta_coeff) + beta_coeff * det0
            ma2 = ma1 + phase_ratio * det0

            # ── 3단계: Jurik 적응 필터 ──
            det1 = (ma2 - prev_jma) * (1.0 - alpha) ** 2 + alpha ** 2 * det1
            current_jma = prev_jma + det1

            jma_arr[i] = current_jma

            # ── Up / Down / Slope ──
            if current_jma > prev_jma:
                up_arr[i] = current_jma
                down_arr[i] = np.nan
            elif current_jma < prev_jma:
                up_arr[i] = np.nan
                down_arr[i] = current_jma
            else:
                up_arr[i] = np.nan
                down_arr[i] = np.nan

            slope_arr[i] = current_jma - prev_jma
            prev_jma = current_jma

        # ── 초기 lookback NaN 처리 ──
        jma_arr[:period - 1] = np.nan
        slope_arr[:period - 1] = np.nan

        return jma_arr, up_arr, down_arr, slope_arr


class JMAIndicator(IIndicator):
    """Jurik Moving Average — VB.NET 완전 포팅.
    
    적응형 변동성 밴드 + 3단계 필터:
    1) 적응 EMA (동적 alpha)
    2) 칼만 필터 (위상 보정)
    3) Jurik 적응 필터 (노이즈 제거)
    """

    def __init__(self):
        self._core = _JMACore()

    def name(self) -> str:
        return "JMA"

    def compute(self, df: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
        length = params.get("jma_length", params.get("jma_period", 7))
        phase = params.get("jma_phase", 50)
        power = params.get("jma_power", 2)

        close = df["close"].values.astype(float)
        n = len(close)

        if n < length:
            df = df.copy()
            df["jma"] = np.nan
            df["jma_up"] = np.nan
            df["jma_down"] = np.nan
            df["jma_slope"] = 0.0
            df["jma_direction"] = 0
            df["prev_jma_direction"] = 0
            df["prev_jma_slope"] = 0.0
            return df

        jma, jma_up, jma_down, jma_slope = self._core.calculate(
            close, length, phase, power
        )

        df = df.copy()
        df["jma"] = jma
        df["jma_up"] = jma_up
        df["jma_down"] = jma_down
        df["jma_slope"] = jma_slope

        # jma_direction: 1=상승, -1=하락, 0=보합
        jma_dir = np.zeros(n, dtype=int)
        jma_dir[jma_slope > 0] = 1
        jma_dir[jma_slope < 0] = -1
        df["jma_direction"] = jma_dir

        # 이전값 (신호 생성용)
        df["prev_jma_direction"] = df["jma_direction"].shift(1).fillna(0).astype(int)
        df["prev_jma_slope"] = df["jma_slope"].shift(1).fillna(0.0)

        return df


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  RSI — 필터용
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class RSIIndicator(IIndicator):
    def name(self) -> str:
        return "RSI"

    def compute(self, df: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
        period = params.get("rsi_period", 14)
        fast_period = params.get("rsi_fast", 5)
        close = df["close"]

        df = df.copy()
        df["rsi"] = self._calc_rsi(close, period)
        df["rsi_fast"] = self._calc_rsi(close, fast_period)

        # 이전값 (신호 생성용)
        df["prev_rsi"] = df["rsi"].shift(1)

        return df

    def _calc_rsi(self, close: pd.Series, period: int) -> pd.Series:
        if close is None or len(close) < period + 1:
            return pd.Series(np.nan, index=close.index)

        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)
        avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100.0 - 100.0 / (1.0 + rs)
        return rsi
