# -*- coding: utf-8 -*-
"""
plugins/screener.py  [MUTABLE]
==============================
종목 스크리닝: MySQL stock_base_info에서 KOSPI 대형주 풀 →
베타/상관도 계산 → 상위 N개 선정.

core_engine.DataService.fetch_large_cap_stocks() 로직 이식.

[FIX 2026-02-08] UI 날짜 미반영 버그 수정
- screen() 시그니처에 start_date/end_date 추가
- datetime.now() 하드코딩 제거 → 파라미터 우선
- index_df 날짜 범위 필터링 추가
"""
from __future__ import annotations
from typing import List, Dict, Any, Optional
import numpy as np
import pandas as pd
import logging
import traceback
from datetime import datetime, timedelta

from core.interfaces import IScreener, IDataSource
from core.types import Candidate

logger = logging.getLogger(__name__)


class BetaCorrelationScreener(IScreener):
    """
    스크리닝 파이프라인:
    1) MySQL stock_base_info에서 KOSPI 대형주 시총 상위 N개 로드
    2) 각 종목 일봉 → KOSPI 지수 대비 베타/상관도 계산
    3) 베타 ≥ min_beta, 상관 ≥ min_corr 필터링
    4) 베타 내림차순 상위 top_n 반환
    """

    def __init__(self, db_engine=None):
        """
        Parameters
        ----------
        db_engine : SQLAlchemy engine (MySQLDataSource._engine)
                    None이면 screen() 시 data_source에서 추출 시도
        """
        self._engine = db_engine

    def screen(
        self,
        universe: List[str],   # 사용 안 함 (DB에서 직접 로드)
        index_df: pd.DataFrame,
        data_source: IDataSource,
        params: Dict[str, Any],
        start_date: Optional[str] = None,   # ★ UI 시작일
        end_date: Optional[str] = None,     # ★ UI 종료일
    ) -> List[Candidate]:
        """전체 스크리닝 실행."""
        try:
            top_n = params.get("screen_top_n", 10)
            pool_size = params.get("candidate_pool", 50)
            min_beta = params.get("screen_min_beta", params.get("beta_min", 0.8))
            min_corr = params.get("screen_min_corr", params.get("corr_min", 0.4))
            months = params.get("screen_months", 6)

            # ★ 기간 계산 — UI 파라미터 우선, params 차선, now() 폴백
            if end_date is None:
                end_date = params.get("end_date",
                    datetime.now().strftime("%Y-%m-%d"))
            if start_date is None:
                start_date = params.get("start_date",
                    (datetime.now() - timedelta(days=months * 30)).strftime("%Y-%m-%d"))

            logger.info(f"[SCREEN] 시작: {start_date} ~ {end_date}, "
                        f"풀={pool_size}, 선정={top_n}")

            # 1) 대형주 후보 로드
            candidates = self._fetch_large_cap(pool_size)
            if not candidates:
                logger.warning("[SCREEN] 대형주 후보 0개")
                return []
            logger.info(f"[SCREEN] 후보 {len(candidates)}개 로드")

            # 2) KOSPI 지수 수익률
            if index_df is None or index_df.empty:
                index_df = data_source.fetch_index_candles(
                    "KOSPI", start_date, end_date)

            # ★ 전달된 index_df가 있어도 날짜 범위로 필터링
            if index_df is not None and not index_df.empty:
                if "date" in index_df.columns:
                    mask = ((index_df["date"] >= start_date)
                            & (index_df["date"] <= end_date))
                    filtered = index_df.loc[mask]
                    if len(filtered) >= 20:
                        index_df = filtered.copy()
                elif (index_df.index.name == "date"
                      or str(index_df.index.dtype).startswith("datetime")):
                    mask = ((index_df.index >= start_date)
                            & (index_df.index <= end_date))
                    filtered = index_df.loc[mask]
                    if len(filtered) >= 20:
                        index_df = filtered.copy()

            if index_df is None or index_df.empty or "close" not in index_df.columns:
                logger.warning("[SCREEN] KOSPI 지수 데이터 없음")
                return []

            kospi_close = index_df["close"]
            if isinstance(kospi_close, pd.DataFrame):
                kospi_close = kospi_close.iloc[:, 0]
            kospi_returns = kospi_close.pct_change().dropna()
            logger.info(f"[SCREEN] KOSPI 지수 {len(index_df)}행, "
                        f"수익률 {len(kospi_returns)}행")

            # 3) 각 종목 베타/상관 계산
            results = []
            for i, cand in enumerate(candidates):
                code = cand["code"]
                name = cand["name"]

                if i % 10 == 0:
                    logger.info(f"[SCREEN] 분석 중 {i+1}/{len(candidates)}: "
                                f"{name}({code})")

                try:
                    df = data_source.fetch_candles(code, start_date, end_date)
                    if df is None or df.empty or "close" not in df.columns:
                        continue
                    if len(df) < 30:
                        continue

                    stock_close = df["close"]
                    if isinstance(stock_close, pd.DataFrame):
                        stock_close = stock_close.iloc[:, 0]
                    stock_returns = stock_close.pct_change().dropna()

                    if len(stock_returns) < 20:
                        continue

                    beta = self._calc_beta(stock_returns, kospi_returns)
                    corr = self._calc_corr(stock_returns, kospi_returns)

                    if np.isnan(beta) or np.isnan(corr):
                        continue
                    if beta < min_beta or corr < min_corr:
                        continue

                    # 추가 정보
                    last_close = float(stock_close.iloc[-1])
                    first_close = float(stock_close.iloc[0])
                    return_6m = ((last_close / first_close - 1) * 100
                                 if first_close > 0 else 0)
                    avg_vol = (float(df["volume"].mean())
                               if "volume" in df.columns else 0)

                    results.append(Candidate(
                        code=code,
                        name=name,
                        score=beta * corr,
                        beta=round(beta, 3),
                        correlation=round(corr, 3),
                        avg_volume=avg_vol,
                    ))

                except Exception as e:
                    logger.debug(f"[SCREEN] {code} 예외: {e}")
                    continue

            # 4) 정렬 및 선정
            results.sort(key=lambda c: c.beta, reverse=True)
            results = results[:top_n]
            logger.info(f"[SCREEN] 최종 선정 {len(results)}개")
            return results

        except Exception as e:
            logger.error(f"[SCREEN] 전체 오류: {e}\n{traceback.format_exc()}")
            return []

    def _fetch_large_cap(self, top_n: int = 50) -> List[Dict[str, str]]:
        """MySQL stock_base_info에서 KOSPI 대형주 시총 상위 로드."""
        engine = self._engine
        if engine is None:
            try:
                from config.default_params import MYSQL_PARAMS
                from sqlalchemy import create_engine
                p = MYSQL_PARAMS
                url = (
                    f"mysql+pymysql://{p['user']}:{p['password']}"
                    f"@{p['host']}:{p['port']}/{p['database']}"
                    f"?charset=utf8mb4"
                )
                engine = create_engine(url, pool_pre_ping=True)
            except Exception as e:
                logger.error(f"[SCREEN] DB 연결 실패: {e}")
                return []

        try:
            filters = [
                # Level 0: 가장 엄격
                """
                SELECT code, name, market_cap
                FROM stock_base_info
                WHERE market = 'KOSPI'
                  AND is_common_stock = 1
                  AND is_excluded = 0
                  AND is_restricted = 0
                  AND instrument_type = 'STOCK'
                  AND market_cap IS NOT NULL AND market_cap > 0
                ORDER BY market_cap DESC
                LIMIT %(limit)s
                """,
                # Level 1
                """
                SELECT code, name, market_cap
                FROM stock_base_info
                WHERE market = 'KOSPI'
                  AND is_common_stock = 1
                  AND is_excluded = 0
                  AND market_cap IS NOT NULL AND market_cap > 0
                ORDER BY market_cap DESC
                LIMIT %(limit)s
                """,
                # Level 2
                """
                SELECT code, name, market_cap
                FROM stock_base_info
                WHERE market = 'KOSPI'
                  AND market_cap IS NOT NULL AND market_cap > 0
                ORDER BY market_cap DESC
                LIMIT %(limit)s
                """,
                # Level 3
                """
                SELECT code, name, market_cap
                FROM stock_base_info
                WHERE market = 'KOSPI'
                ORDER BY code ASC
                LIMIT %(limit)s
                """,
            ]

            for level, sql in enumerate(filters):
                try:
                    df = pd.read_sql(sql, engine, params={"limit": top_n})
                    if len(df) >= 5:
                        logger.info(f"[SCREEN] DB Level-{level}: {len(df)}개")
                        return [
                            {"code": str(row["code"]).strip(),
                             "name": str(row["name"]).strip()}
                            for _, row in df.iterrows()
                        ]
                except Exception as e:
                    logger.debug(f"[SCREEN] Level-{level} 실패: {e}")
                    continue

            return []

        except Exception as e:
            logger.error(f"[SCREEN] fetch_large_cap 오류: {e}")
            return []

    def _calc_beta(self, stock_ret: pd.Series,
                   market_ret: pd.Series) -> float:
        try:
            aligned = pd.concat([stock_ret, market_ret], axis=1).dropna()
            if len(aligned) < 20:
                return np.nan
            cov = np.cov(aligned.iloc[:, 0], aligned.iloc[:, 1])
            var_m = cov[1, 1]
            if var_m == 0:
                return np.nan
            return float(cov[0, 1] / var_m)
        except Exception:
            return np.nan

    def _calc_corr(self, stock_ret: pd.Series,
                   market_ret: pd.Series) -> float:
        try:
            aligned = pd.concat([stock_ret, market_ret], axis=1).dropna()
            if len(aligned) < 20:
                return np.nan
            return float(aligned.iloc[:, 0].corr(aligned.iloc[:, 1]))
        except Exception:
            return np.nan