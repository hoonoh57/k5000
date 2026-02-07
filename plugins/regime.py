# -*- coding: utf-8 -*-
"""
plugins/regime.py  [MUTABLE]
============================
시장 레짐 판단기 - KOSPI 지수에 SuperTrend + JMA + 보조 매크로 지표 적용.

기본 detect():  ST 방향 + JMA slope → BULL / BEAR / SIDEWAYS
확장 detect_detailed():  MA 크로스, VKOSPI, 모멘텀 점수까지 합산 → RegimeState 반환
"""
from __future__ import annotations

import logging
import numpy as np
import pandas as pd

from core.interfaces import IRegimeDetector
from core.types import Regime, RegimeState
from plugins.indicators import SuperTrendIndicator, JMAIndicator

logger = logging.getLogger(__name__)


class STRegimeDetector(IRegimeDetector):
    """SuperTrend + JMA 기반 시장 레짐 판단기."""

    def __init__(self, data_source=None):
        self._data_source = data_source   # VKOSPI 조회용 (선택)
        self._vkospi_failed = False       # VKOSPI 조회 실패 플래그


    # ================================================================
    #  기본 detect  - IRegimeDetector 계약 이행
    # ================================================================
    def detect(self, index_df: pd.DataFrame, params: dict) -> Regime:
        """
        간단 레짐 판정 (하위 호환).
        Returns: Regime.BULL / BEAR / SIDEWAYS
        """
        rp = {
            'st_period':      params.get('regime_st_period', 20),
            'st_multiplier':  params.get('regime_st_multiplier', 2.5),
            'jma_length':     params.get('jma_length', 7),
            'jma_phase':      params.get('jma_phase', 50),
        }

        try:
            df = index_df.copy()
            df = SuperTrendIndicator().compute(df, rp)
            df = JMAIndicator().compute(df, rp)
        except Exception as e:
            logger.warning(f"[REGIME] detect 지표 계산 실패: {e}")
            return Regime.SIDEWAYS

        if df.empty or 'st_dir' not in df.columns:
            return Regime.SIDEWAYS

        last_dir   = df['st_dir'].iloc[-1]
        jma_slope  = df['jma_slope'].iloc[-1] if 'jma_slope' in df.columns else 0.0

        if last_dir == 1 and jma_slope > 0:
            return Regime.BULL
        elif last_dir == -1 and jma_slope < 0:
            return Regime.BEAR
        else:
            return Regime.SIDEWAYS

    # ================================================================
    #  확장 detect_detailed  - 매크로 분석 포함
    # ================================================================
    def detect_detailed(self, index_df: pd.DataFrame, params: dict,
                        data_source=None,
                        start=None, end=None) -> RegimeState:
        """
        ST + JMA + MA 크로스 + VKOSPI + 모멘텀 -> 가중 합산 -> RegimeState.

        가중치 (VKOSPI 사용 가능 시):
            st_jma=0.35, ma_trend=0.30, vkospi=0.15, momentum=0.20

        VKOSPI 미사용 시 나머지 3개를 자동 정규화하여 합=1.0 유지.
        """
        # data_source가 인자로 안 들어오면 생성자에서 받은 것 사용
        if data_source is None:
            data_source = self._data_source

        rp = {
            'st_period':      params.get('regime_st_period', 20),
            'st_multiplier':  params.get('regime_st_multiplier', 2.5),
            'jma_length':     params.get('jma_length', 7),
            'jma_phase':      params.get('jma_phase', 50),
        }

        # ── 지표 계산 ──
        try:
            df = index_df.copy()
            df = SuperTrendIndicator().compute(df, rp)
            df = JMAIndicator().compute(df, rp)
        except Exception as e:
            logger.warning(f"[REGIME] detect_detailed 지표 계산 실패: {e}")
            return self._fallback_state("지표 계산 실패")

        if df.empty or 'st_dir' not in df.columns:
            return self._fallback_state("데이터 부족")

        # ────────────────────────────────────────────
        #  1) ST + JMA 기본 점수  (-1 ~ +1)
        # ────────────────────────────────────────────
        st_jma_score = self._calc_st_jma_score(df)

        # ────────────────────────────────────────────
        #  2) MA 추세 점수  (-1 ~ +1)
        # ────────────────────────────────────────────
        ma_trend_score = self._calc_ma_trend_score(df)

        # ────────────────────────────────────────────
        #  3) 모멘텀 점수  (-1 ~ +1)
        # ────────────────────────────────────────────
        momentum_score = self._calc_momentum_score(df)

        # ────────────────────────────────────────────
        #  4) VKOSPI 변동성 점수  (-1 ~ +1)
        # ────────────────────────────────────────────
        vkospi_score = 0.0
        vkospi_available = False

        if not self._vkospi_failed and data_source is not None:
            vkospi_score, vkospi_available = self._calc_vkospi_score(
                data_source, start, end
            )

        # ────────────────────────────────────────────
        #  5) 가중 합산
        # ────────────────────────────────────────────
        raw_weights = {
            'st_jma':    0.35,
            'ma_trend':  0.30,
            'momentum':  0.20,
        }
        if vkospi_available:
            raw_weights['vkospi'] = 0.15

        # 정규화 → 합 = 1.0
        total_w = sum(raw_weights.values())
        weights = {k: v / total_w for k, v in raw_weights.items()}

        scores = {
            'st_jma':   st_jma_score,
            'ma_trend': ma_trend_score,
            'momentum': momentum_score,
        }
        if vkospi_available:
            scores['vkospi'] = vkospi_score

        total = sum(scores[k] * weights[k] for k in scores)

        # ────────────────────────────────────────────
        #  6) 레짐 결정
        # ────────────────────────────────────────────
        if total > 0.2:
            regime = Regime.BULL
        elif total < -0.2:
            regime = Regime.BEAR
        else:
            regime = Regime.SIDEWAYS

        confidence = min(abs(total), 1.0)

        # 자본 배분 비율
        alloc_map = {
            Regime.BULL:     1.0,
            Regime.SIDEWAYS: 0.4,
            Regime.BEAR:     0.1,
        }
        allocation = alloc_map.get(regime, 0.4)

        # 설명 문자열
        desc_parts = [
            f"st_jma={st_jma_score:.2f}",
            f"ma_trend={ma_trend_score:.2f}",
        ]
        if vkospi_available:
            desc_parts.append(f"vkospi={vkospi_score:.2f}")
        else:
            desc_parts.append("vkospi=N/A")
        desc_parts.append(f"momentum={momentum_score:.2f}")
        desc_parts.append(f"total={total:+.2f}")

        logger.info(
            f"[REGIME] {regime.name} (conf={confidence:.2f}); "
            + ", ".join(desc_parts)
        )

        return RegimeState(
            regime=regime,
            confidence=confidence,
            scores=scores,
            capital_allocation=allocation,
            description="; ".join(desc_parts),
        )

    # ================================================================
    #  개별 점수 계산 헬퍼
    # ================================================================

    def _calc_st_jma_score(self, df: pd.DataFrame) -> float:
        """
        ST 방향 + JMA slope → -1 ~ +1.
        ST_UP & JMA_UP → +1, ST_DOWN & JMA_DOWN → -1, 그 외 → 0.
        """
        last_dir = df['st_dir'].iloc[-1]
        jma_slope = df['jma_slope'].iloc[-1] if 'jma_slope' in df.columns else 0.0

        score = 0.0
        if last_dir == 1:
            score += 0.5
        elif last_dir == -1:
            score -= 0.5

        if jma_slope > 0:
            score += 0.5
        elif jma_slope < 0:
            score -= 0.5

        return max(-1.0, min(1.0, score))

    def _calc_ma_trend_score(self, df: pd.DataFrame) -> float:
        """
        단기 MA(20) vs 장기 MA(60) 크로스 + 종가 위치 → -1 ~ +1.
        """
        close = df['close']
        if len(close) < 60:
            return 0.0

        ma20 = close.rolling(20).mean()
        ma60 = close.rolling(60).mean()

        if ma20.isna().iloc[-1] or ma60.isna().iloc[-1]:
            return 0.0

        last_ma20 = ma20.iloc[-1]
        last_ma60 = ma60.iloc[-1]
        last_close = close.iloc[-1]

        score = 0.0

        # MA20 > MA60 → 상승 추세 (+0.5), 반대 → (-0.5)
        if last_ma20 > last_ma60:
            score += 0.5
        elif last_ma20 < last_ma60:
            score -= 0.5

        # 종가가 MA20 위 → (+0.25), MA60 아래 → (-0.25)
        if last_close > last_ma20:
            score += 0.25
        elif last_close < last_ma60:
            score -= 0.25

        # 추가: MA20 기울기 (최근 5일)
        if len(ma20.dropna()) >= 5:
            ma20_slope = ma20.iloc[-1] - ma20.iloc[-5]
            if last_close > 0:
                slope_pct = ma20_slope / last_close
                if slope_pct > 0.01:
                    score += 0.25
                elif slope_pct < -0.01:
                    score -= 0.25

        return max(-1.0, min(1.0, score))

    def _calc_momentum_score(self, df: pd.DataFrame) -> float:
        """
        20일 수익률(ROC) + 60일 ROC → -1 ~ +1.
        """
        close = df['close']
        if len(close) < 60:
            # 데이터가 짧으면 가용한 만큼만
            if len(close) < 20:
                return 0.0
            roc20 = (close.iloc[-1] / close.iloc[-20] - 1) * 100
            return max(-1.0, min(1.0, roc20 / 10.0))  # 10% → 1.0 스케일

        roc20 = (close.iloc[-1] / close.iloc[-20] - 1) * 100
        roc60 = (close.iloc[-1] / close.iloc[-60] - 1) * 100

        score = 0.0

        # 20일 ROC: 5% 이상이면 +0.5, -5% 이하면 -0.5
        if roc20 > 5:
            score += 0.5
        elif roc20 > 0:
            score += 0.2
        elif roc20 < -5:
            score -= 0.5
        elif roc20 < 0:
            score -= 0.2

        # 60일 ROC: 10% 이상이면 +0.5, -10% 이하면 -0.5
        if roc60 > 10:
            score += 0.5
        elif roc60 > 0:
            score += 0.2
        elif roc60 < -10:
            score -= 0.5
        elif roc60 < 0:
            score -= 0.2

        return max(-1.0, min(1.0, score))

    def _calc_vkospi_score(self, data_source, start, end) -> tuple:
        """
        VKOSPI 변동성 지수 조회 → (score, available).

        Cybos Plus에서 VKOSPI 직접 조회가 불가능한 경우가 있음.
        실패 시 _vkospi_failed 플래그를 세팅하여 이후 재시도 방지.

        Returns:
            (score, True)  - 조회 성공 시
            (0.0,   False) - 조회 실패 시
        """
        try:
            # VKOSPI 코드 후보 시도: V001 → UVKOSPI 순서
            vkospi_df = None
            for code in ('V001', 'UVKOSPI', 'U001V'):
                try:
                    vkospi_df = data_source.fetch_index_candles(code, start, end)
                    if vkospi_df is not None and not vkospi_df.empty:
                        break
                except Exception:
                    continue

            if vkospi_df is None or vkospi_df.empty:
                raise ValueError("VKOSPI 데이터를 가져올 수 없음")

            if 'close' not in vkospi_df.columns:
                raise ValueError("VKOSPI 데이터에 close 컬럼 없음")

            last_vkospi = float(vkospi_df['close'].iloc[-1])

            # VKOSPI 구간별 점수
            #   < 15  → 저변동성 → 강세 신호 (+1.0)
            #   15~20 → 보통    → 약 강세   (+0.3)
            #   20~25 → 경계    → 중립      (0.0)
            #   25~30 → 높음    → 약 약세   (-0.5)
            #   > 30  → 극도    → 강 약세   (-1.0)
            if last_vkospi < 15:
                score = 1.0
            elif last_vkospi < 20:
                score = 0.3
            elif last_vkospi < 25:
                score = 0.0
            elif last_vkospi < 30:
                score = -0.5
            else:
                score = -1.0

            logger.debug(f"[REGIME] VKOSPI={last_vkospi:.2f} → score={score:.2f}")
            return score, True

        except Exception as e:
            self._vkospi_failed = True
            logger.warning(
                f"[REGIME] VKOSPI 조회 실패 - 이후 재시도 안 함: {e}"
            )
            return 0.0, False


    # ================================================================
    #  폴백
    # ================================================================

    @staticmethod
    def _fallback_state(reason: str) -> RegimeState:
        """데이터/지표 문제 시 안전한 기본값 반환."""
        logger.warning(f"[REGIME] 폴백 적용: {reason}")
        return RegimeState(
            regime=Regime.SIDEWAYS,
            confidence=0.0,
            scores={'st_jma': 0.0, 'ma_trend': 0.0, 'momentum': 0.0},
            capital_allocation=0.4,
            description=f"fallback: {reason}",
        )
