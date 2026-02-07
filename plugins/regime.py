# -*- coding: utf-8 -*-
"""
plugins/regime.py
=================
시장 레짐 판단.
- 기본: ST + JMA (기존)
- 확장: MA 크로스 + VKOSPI + 외국인 순매수 + 해외 지수
"""
from __future__ import annotations
from typing import Dict, Any, Optional
import numpy as np
import pandas as pd
import logging

from core.interfaces import IRegimeDetector, IDataSource
from core.types import Regime, RegimeState
from plugins.indicators import SuperTrendIndicator, JMAIndicator

logger = logging.getLogger(__name__)


class STRegimeDetector(IRegimeDetector):
    """
    다중 지표 기반 레짐 판단.
    data_source를 주입하면 VKOSPI, 외국인 동향 등 추가 지표 활용.
    data_source 없으면 ST+JMA+MA만으로 판단 (하위 호환).
    """

    def __init__(self, data_source: Optional[IDataSource] = None):
        self._data_source = data_source

    def set_data_source(self, ds: IDataSource) -> None:
        self._data_source = ds

    def detect(self, index_df: pd.DataFrame,
               params: Dict[str, Any]) -> Regime:
        state = self.detect_detailed(index_df, params)
        return state.regime

    def detect_detailed(self, index_df: pd.DataFrame,
                        params: Dict[str, Any]) -> RegimeState:
        scores = {}

        # 1) ST + JMA (가중치 0.35)
        scores["st_jma"] = self._score_st_jma(index_df, params)

        # 2) MA 정배열/역배열 (가중치 0.20)
        scores["ma_trend"] = self._score_ma_trend(index_df)

        # 3) VKOSPI 변동성 (가중치 0.20) — data_source 필요
        scores["vkospi"] = self._score_vkospi(index_df, params)

        # 4) 외국인 순매수 (가중치 0.15) — data_source 필요
        scores["foreign"] = self._score_foreign(index_df, params)

        # 5) 모멘텀 (가중치 0.10)
        scores["momentum"] = self._score_momentum(index_df)

        weights = {
            "st_jma": 0.35, "ma_trend": 0.20,
            "vkospi": 0.20, "foreign": 0.15, "momentum": 0.10,
        }
        total = sum(scores[k] * weights[k] for k in scores)
        confidence = min(1.0, abs(total))

        alloc_map = {Regime.BULL: 1.0, Regime.SIDEWAYS: 0.4, Regime.BEAR: 0.1}
        if total >= 0.25:
            regime = Regime.BULL
        elif total <= -0.25:
            regime = Regime.BEAR
        else:
            regime = Regime.SIDEWAYS

        desc_parts = [f"{k}={v:+.2f}" for k, v in scores.items()]
        desc = f"total={total:+.2f} | " + ", ".join(desc_parts)

        logger.info(f"[REGIME] {regime.name} (conf={confidence:.2f}) {desc}")

        return RegimeState(
            regime=regime,
            confidence=confidence,
            scores=scores,
            capital_allocation=alloc_map.get(regime, 0.4),
            description=desc,
        )

    # ── 개별 점수 ──

    def _score_st_jma(self, index_df: pd.DataFrame,
                      params: Dict[str, Any]) -> float:
        try:
            rp = {
                "st_period": params.get("regime_st_period", 20),
                "st_multiplier": params.get("regime_st_multiplier", 2.5),
                "jma_length": params.get("jma_length", 7),
                "jma_phase": params.get("jma_phase", 50),
                "jma_power": params.get("jma_power", 2),
            }
            df = index_df.copy()
            df = SuperTrendIndicator().compute(df, rp)
            df = JMAIndicator().compute(df, rp)

            if df.empty or "st_dir" not in df.columns:
                return 0.0

            last_dir = int(df["st_dir"].iloc[-1])
            jma_slope = (
                float(df["jma_slope"].iloc[-1])
                if "jma_slope" in df.columns else 0.0
            )

            if last_dir == 1 and jma_slope > 0:
                return 1.0
            elif last_dir == -1 and jma_slope < 0:
                return -1.0
            return 0.0
        except Exception as e:
            logger.debug(f"[REGIME] st_jma error: {e}")
            return 0.0

    def _score_ma_trend(self, index_df: pd.DataFrame) -> float:
        try:
            if index_df is None or "close" not in index_df.columns:
                return 0.0
            close = index_df["close"].values.astype(float)
            if len(close) < 60:
                return 0.0
            ma20 = np.mean(close[-20:])
            ma60 = np.mean(close[-60:])
            cur = close[-1]
            if cur > ma20 > ma60:
                return 1.0
            elif cur < ma20 < ma60:
                return -1.0
            return 0.0
        except Exception:
            return 0.0

    def _score_vkospi(self, index_df: pd.DataFrame,
                      params: Dict[str, Any]) -> float:
        """VKOSPI 기반 점수. data_source가 없으면 0."""
        if not self._data_source:
            return 0.0
        try:
            # CybosDataSource를 통해 VKOSPI(V001) 조회 시도
            from datetime import datetime, timedelta
            end = datetime.now().strftime("%Y-%m-%d")
            start = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
            vdf = self._data_source.fetch_index_candles("VKOSPI", start, end)
            if vdf is None or vdf.empty or "close" not in vdf.columns:
                return 0.0
            vk = float(vdf["close"].iloc[-1])
            if vk < 15:
                return 0.5       # 저변동 → 상승 유리
            elif vk > 25:
                return -0.8      # 고변동 → 하락 위험
            elif vk > 20:
                return -0.3
            return 0.0
        except Exception:
            return 0.0

    def _score_foreign(self, index_df: pd.DataFrame,
                       params: Dict[str, Any]) -> float:
        """외국인 순매수 추이. data_source가 없으면 0."""
        if not self._data_source:
            return 0.0
        try:
            if not hasattr(self._data_source, "fetch_investor_trend"):
                # CompositeDataSource에 해당 메서드가 없을 수 있음
                return 0.0
            # TODO: CybosDataSource.fetch_investor_trend 연결
            return 0.0
        except Exception:
            return 0.0

    def _score_momentum(self, index_df: pd.DataFrame) -> float:
        """최근 20일 수익률 기반 모멘텀."""
        try:
            if index_df is None or "close" not in index_df.columns:
                return 0.0
            close = index_df["close"].values.astype(float)
            if len(close) < 20:
                return 0.0
            ret_20d = (close[-1] / close[-20] - 1)
            if ret_20d > 0.03:
                return 0.8
            elif ret_20d < -0.03:
                return -0.8
            return 0.0
        except Exception:
            return 0.0
