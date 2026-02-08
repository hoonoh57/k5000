# -*- coding: utf-8 -*-
"""
모멘텀 에이전트
KOSPI/KOSDAQ 대비 상대 수익률(상대강도)을 계산한다.
"""
from __future__ import annotations

import logging
from typing import List

import numpy as np
import pandas as pd

from agents.base import IAgent

logger = logging.getLogger(__name__)


class MomentumAgent(IAgent):
    """시장 대비 상대강도 에이전트"""

    @property
    def name(self) -> str:
        return "momentum"

    @property
    def provided_indicators(self) -> List[str]:
        return [
            "momentum.return_20d",        # 종목 20일 수익률
            "momentum.kospi_return_20d",   # KOSPI 20일 수익률
            "momentum.vs_kospi_ratio",     # 종목수익률 / KOSPI수익률
            "momentum.relative_strength",  # 상대강도 (양수면 초과성과)
        ]

    def compute(self, universe_df: pd.DataFrame,
                market_df: pd.DataFrame = None,
                lookback: int = 20,
                **kwargs) -> pd.DataFrame:
        """
        Args:
            universe_df: 종목별 데이터 (code, close 컬럼 필수)
                         또는 종목별 요약 행(code, close_first, close_last)
            market_df:   KOSPI 지수 데이터 (close 컬럼)
            lookback:    수익률 계산 기간 (기본 20일)
        """
        df = universe_df.copy()

        # KOSPI 수익률 계산
        kospi_ret = 0.0
        if market_df is not None and len(market_df) > lookback:
            kospi_close = market_df["close"].values
            kospi_ret = (kospi_close[-1] / kospi_close[-lookback - 1] - 1) * 100
        else:
            logger.warning("[MOMENTUM_AGENT] KOSPI 데이터 부족, "
                           "상대강도 0으로 설정")

        # 종목별 수익률이 이미 계산되어 있으면 사용
        if "return_pct" in df.columns:
            df["momentum.return_20d"] = df["return_pct"]
        elif "close_last" in df.columns and "close_first" in df.columns:
            df["momentum.return_20d"] = (
                (df["close_last"] / df["close_first"] - 1) * 100
            )
        else:
            df["momentum.return_20d"] = 0.0

        df["momentum.kospi_return_20d"] = kospi_ret

        # 비율 계산 (KOSPI 수익률이 0이면 절대 수익률 사용)
        if abs(kospi_ret) > 0.01:
            df["momentum.vs_kospi_ratio"] = (
                df["momentum.return_20d"] / kospi_ret
            ).round(2)
        else:
            df["momentum.vs_kospi_ratio"] = np.where(
                df["momentum.return_20d"] > 0, 999.0, 0.0)

        # 상대강도 = 종목수익률 - KOSPI수익률
        df["momentum.relative_strength"] = (
            df["momentum.return_20d"] - kospi_ret
        ).round(2)

        logger.info(f"[MOMENTUM_AGENT] {len(df)}종목 상대강도 계산 완료 "
                     f"(KOSPI {lookback}일 수익률: {kospi_ret:.2f}%)")
        return df
