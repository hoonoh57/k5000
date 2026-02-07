# -*- coding: utf-8 -*-
"""
plugins/regime.py  [MUTABLE]
============================
시장 레짐(상승/하락/횡보) 판단.
KOSPI 지수에 SuperTrend 적용 + JMA 기울기 보조.
"""
from __future__ import annotations
from typing import Dict, Any
import numpy as np
from core.interfaces import IRegimeDetector
from core.types import Regime
from plugins.indicators import SuperTrendIndicator, JMAIndicator


class STRegimeDetector(IRegimeDetector):

    def detect(self, index_df, params: Dict[str, Any]) -> Regime:
        rp = {
            "st_period": params.get("regime_st_period", 20),
            "st_multiplier": params.get("regime_st_multiplier", 2.5),
            "jma_length": params.get("jma_length", 7),
            "jma_phase": params.get("jma_phase", 50),
        }

        df = index_df.copy()
        st_ind = SuperTrendIndicator()
        jma_ind = JMAIndicator()

        df = st_ind.compute(df, rp)
        df = jma_ind.compute(df, rp)

        if df.empty or "st_dir" not in df.columns:
            return Regime.SIDEWAYS

        last_dir = df["st_dir"].iloc[-1]
        jma_slope = df["jma_slope"].iloc[-1] if "jma_slope" in df.columns else 0

        if last_dir == 1 and jma_slope > 0:
            return Regime.BULL
        elif last_dir == -1 and jma_slope < 0:
            return Regime.BEAR
        else:
            return Regime.SIDEWAYS
