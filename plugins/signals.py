# -*- coding: utf-8 -*-
"""
plugins/signals.py  [MUTABLE]
=============================
매매 신호 생성: SuperTrend + JMA 조합.
strategy.py 검증 로직 100% 이식.

매수: ST 상승추세 + JMA 상승전환 (선택적 기울기 필터)
      ST 상승전환 순간 + JMA 상승 중
매도: ① ST 하락반전 → 즉시
      ② JMA 하락전환 → 목표수익 달성 후에만 (미달 시 ST 상승 중 보유)
      ③ RSI 극단 과매수 + JMA 약세 → 매도
      ④ 손절/트레일링 → backtest에서 처리
"""
from __future__ import annotations
from typing import List, Dict, Any
import numpy as np
import pandas as pd
from core.interfaces import ISignalGenerator
from core.types import Signal, Direction


class STJMASignalGenerator(ISignalGenerator):

    def generate(self, df: pd.DataFrame, code: str, params: Dict[str, Any]) -> List[Signal]:
        signals: List[Signal] = []

        slope_min = params.get("jma_slope_min", 0.0)
        rsi_ob = params.get("rsi_ob", 80)
        rsi_os = params.get("rsi_os", 30)

        # 필수 컬럼 확인
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

        # jma_direction: slope > 0 → 1, slope < 0 → -1, else 0
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

            # ── 매수 조건 ──
            buy = False
            reason = ""
            strength = 0.0

            # 핵심 매수: ST 상승(1) + JMA 상승전환(이전 ≤0 → 현재 1)
            if cur_st == 1 and cur_jma == 1 and prev_jma <= 0:
                buy = True
                reason = "ST_UP+JMA_TURN_UP"
                strength = 0.7

            # 보조 매수: ST가 상승전환(이전 ≠1 → 현재 1) + JMA 이미 상승 중
            elif cur_st == 1 and prev_st != 1 and cur_jma == 1:
                buy = True
                reason = "ST_TURN_UP+JMA_UP"
                strength = 0.8

            # JMA 기울기 필터
            if buy and slope_min > 0:
                if pd.isna(cur_slope) or cur_slope < slope_min:
                    buy = False
                    reason = ""

            # RSI 과매도 보너스
            if buy and not np.isnan(cur_rsi) and cur_rsi <= rsi_os:
                strength = min(strength + 0.2, 1.0)
                reason += "+RSI_OS"

            if buy:
                signals.append(Signal(
                    direction=Direction.BUY,
                    code=code, dt=dt, price=float(close[i]),
                    reason=f"{reason}(slope={cur_slope:.2f},str={strength:.1f})"
                ))
                continue  # 매수 신호가 있으면 매도 신호 생략

            # ── 매도 조건 ──
            sell = False

            # 1) ST 하락반전 (이전 1 → 현재 -1) → 즉시 매도
            if cur_st == -1 and prev_st == 1:
                sell = True
                reason = "ST_REVERSAL_DOWN"
                strength = 1.0

            # 2) JMA 하락전환 + ST 상승 중 → 매도 후보
            #    (backtest에서 수익 체크 후 최종 판단)
            elif cur_jma == -1 and prev_jma >= 0 and cur_st == 1:
                sell = True
                reason = "JMA_TURN_DOWN"
                strength = 0.5  # backtest에서 수익 조건 확인

            # 3) RSI 극단 과매수 + JMA 약세
            elif not np.isnan(cur_rsi) and cur_rsi >= rsi_ob and cur_jma <= 0:
                sell = True
                reason = "RSI_OB+JMA_WEAK"
                strength = 0.6

            if sell:
                signals.append(Signal(
                    direction=Direction.SELL,
                    code=code, dt=dt, price=float(close[i]),
                    reason=f"{reason}(str={strength:.1f})"
                ))

        return signals
