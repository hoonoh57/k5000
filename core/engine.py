# -*- coding: utf-8 -*-
"""
core/engine.py  [IMMUTABLE]
===========================
백테스트 + 실매매 공통 루프.
strategy.py 검증 로직 100% 이식:
- 매일 포지션 상태 체크
- ATR 기반 동적 손절 + 트레일링 스톱
- JMA 하락전환 매도 시 목표수익/ST 상태 분기
- 최고가 추적 (peak tracking)
- 최소 보유일 (min_hold_days)
"""
from __future__ import annotations
from typing import List, Dict, Any, Optional
import logging
import traceback
from datetime import datetime
from pathlib import Path
import pandas as pd
import numpy as np

from core.types import Signal, Direction, TradeRecord, BacktestResult, Regime
from core.interfaces import (
    IDataSource, IIndicator, ISignalGenerator, IRegimeDetector, IRiskGate,
)
from core.risk import RiskManager
from core.metrics import calc_metrics
from core.event_bus import EventBus

logger = logging.getLogger(__name__)
_LOG_DIR = Path("data/logs")
_LOG_DIR.mkdir(parents=True, exist_ok=True)


def _log_error(msg: str) -> None:
    try:
        with open(_LOG_DIR / "error_log.txt", "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")
    except Exception:
        pass


class BacktestEngine:
    """백테스트 엔진 — strategy.py 검증 로직 이식."""

    def __init__(
        self,
        data_source: IDataSource,
        indicators: List[IIndicator],
        signal_gen: ISignalGenerator,
        regime_detector: Optional[IRegimeDetector] = None,
        risk_gate: Optional[IRiskGate] = None,
        event_bus: Optional[EventBus] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.data_source = data_source
        self.indicators = indicators
        self.signal_gen = signal_gen
        self.regime_detector = regime_detector
        self.risk_gate = risk_gate
        self.bus = event_bus or EventBus()
        self.params = params or {}

    def run(self, code: str, start: str, end: str,
            initial_capital: float = 10_000_000) -> Optional[BacktestResult]:
        """단일 종목 백테스트 실행."""
        try:
            df = self.data_source.fetch_candles(code, start, end)
            if df is None or df.empty:
                logger.warning(f"{code}: 데이터 없음")
                return None

            df = self._validate_data(df)
            if df.empty:
                return None

            # 레짐 판단
            regime = Regime.BULL
            if self.regime_detector:
                try:
                    idx_df = self.data_source.fetch_index_candles("KOSPI", start, end)
                    if idx_df is not None and not idx_df.empty:
                        regime = self.regime_detector.detect(idx_df, self.params)
                except Exception:
                    pass

            # 지표 계산
            for ind in self.indicators:
                try:
                    df = ind.compute(df, self.params)
                except Exception as e:
                    logger.error(f"{code}: indicator {ind.name()} failed: {e}")

            # 신호 생성
            signals = self.signal_gen.generate(df, code, self.params)

            # 시뮬레이션 (strategy.py backtest 로직)
            result = self._simulate(df, signals, code, initial_capital, regime)
            self.bus.publish("backtest_done", code=code, result=result)
            return result

        except Exception as e:
            msg = f"BacktestEngine.run({code}) error: {e}\n{traceback.format_exc()}"
            logger.error(msg)
            _log_error(msg)
            return None

    def run_batch(self, codes: List[str], start: str, end: str,
                  initial_capital: float = 10_000_000) -> List[BacktestResult]:
        """여러 종목 일괄 백테스트."""
        results = []
        for code in codes:
            result = self.run(code, start, end, initial_capital)
            if result:
                results.append(result)
        return results

    def _validate_data(self, df: pd.DataFrame) -> pd.DataFrame:
        required = ["open", "high", "low", "close", "volume"]
        for col in required:
            if col not in df.columns:
                logger.error(f"Missing column: {col}")
                return pd.DataFrame()
        df = df.replace([np.inf, -np.inf], np.nan)
        df = df.dropna(subset=["open", "high", "low", "close"])
        return df

    def _simulate(
        self,
        df: pd.DataFrame,
        signals: List[Signal],
        code: str,
        capital: float,
        regime: Regime,
    ) -> BacktestResult:
        """
        strategy.py backtest() 완전 이식:
        - 매일 포지션 상태 체크
        - ATR 동적 손절 + 트레일링
        - JMA 하락전환 시 수익/ST 분기
        - 최고가 추적, 최소 보유일
        """
        p = self.params
        target_pct = p.get("target_profit_pct", 0.07)
        stop_pct = p.get("stop_loss_pct", -0.05)
        trail_pct = p.get("trailing_stop_pct", 0.05)
        use_atr = p.get("use_atr_stops", True)
        atr_stop_m = p.get("atr_stop_mult", 2.0)
        atr_trail_m = p.get("atr_trailing_mult", 2.5)
        min_hold = p.get("min_hold_days", 2)

        trades: List[TradeRecord] = []
        equity = []
        cash = capital
        position = None  # dict: entry_price, entry_idx, entry_date, shares, peak

        # 신호 맵
        signal_map: Dict = {}
        for sig in signals:
            signal_map[sig.dt] = sig

        close_arr = df["close"].values
        atr_arr = df["atr"].values if "atr" in df.columns else np.full(len(df), np.nan)
        st_dir_arr = df["st_dir"].values if "st_dir" in df.columns else np.ones(len(df))
        dates = df["date"].values if "date" in df.columns else df.index.values

        n = len(df)

        for i in range(n):
            close = float(close_arr[i])
            dt = dates[i]
            atr_val = float(atr_arr[i]) if not np.isnan(atr_arr[i]) else 0.0
            st_dir = int(st_dir_arr[i])
            sig = signal_map.get(dt)
            sig_direction = sig.direction if sig else Direction.HOLD
            sig_reason = sig.reason if sig else ""

            if position is not None:
                # ── 보유 중: 매일 체크 ──
                entry_price = position["entry_price"]
                hold_days = i - position["entry_idx"]

                if entry_price <= 0:
                    equity.append(cash)
                    continue

                pnl_pct = (close - entry_price) / entry_price

                # 최고가 갱신
                if close > position["peak"]:
                    position["peak"] = close
                peak = position["peak"]
                drawdown_from_peak = (close - peak) / peak if peak > 0 else 0

                # 동적 손절선/트레일링
                if use_atr and atr_val > 0:
                    dyn_stop = -atr_stop_m * atr_val / entry_price
                    dyn_trail = -atr_trail_m * atr_val / peak if peak > 0 else -trail_pct
                else:
                    dyn_stop = stop_pct
                    dyn_trail = -trail_pct

                sell_now = False
                sell_reason = ""

                # ① 손절 — 항상 작동
                if pnl_pct <= dyn_stop:
                    sell_now = True
                    sell_reason = f"STOP_LOSS({pnl_pct:.1%})"

                # ② 트레일링 스톱 (목표수익 달성 후)
                elif pnl_pct >= target_pct and drawdown_from_peak <= dyn_trail:
                    sell_now = True
                    sell_reason = f"TRAILING({drawdown_from_peak:.1%})"

                # ③ 매도 신호 처리
                elif sig_direction == Direction.SELL and hold_days >= min_hold:
                    if "ST_REVERSAL_DOWN" in sig_reason:
                        # ST 하락반전 → 무조건 매도
                        sell_now = True
                        sell_reason = sig_reason

                    elif "JMA_TURN_DOWN" in sig_reason:
                        # 목표수익 달성 → 매도
                        if pnl_pct >= target_pct:
                            sell_now = True
                            sell_reason = f"JMA_DOWN+TARGET({pnl_pct:.1%})"
                        elif st_dir != 1:
                            # ST도 상승 아님 → 매도
                            sell_now = True
                            sell_reason = f"JMA_DOWN+ST_NOT_UP({pnl_pct:.1%})"
                        # else: ST 상승 중 + 목표 미달 → 보유 유지

                    elif "RSI_OB" in sig_reason:
                        if pnl_pct >= target_pct * 0.5:
                            sell_now = True
                            sell_reason = sig_reason

                if sell_now:
                    shares = position["shares"]
                    pnl_amount = (close - entry_price) * shares
                    cash += close * shares

                    trades.append(TradeRecord(
                        code=code,
                        entry_date=position["entry_date"],
                        entry_price=entry_price,
                        exit_date=dt,
                        exit_price=close,
                        shares=shares,
                        pnl=pnl_amount,
                        pnl_pct=pnl_pct * 100,
                        exit_reason=sell_reason,
                    ))
                    position = None

            elif sig_direction == Direction.BUY and position is None:
                # ── 매수 ──
                if close > 0 and cash > close:
                    shares = int(cash // close)
                    if shares > 0:
                        cash -= shares * close
                        position = {
                            "entry_price": close,
                            "entry_idx": i,
                            "entry_date": dt,
                            "shares": shares,
                            "peak": close,
                        }

            # 자산 평가
            if position is not None:
                equity.append(cash + position["shares"] * close)
            else:
                equity.append(cash)

        # 미청산 포지션 강제 청산
        if position is not None and n > 0:
            last_close = float(close_arr[-1])
            last_dt = dates[-1]
            entry_price = position["entry_price"]
            shares = position["shares"]
            pnl_pct = (last_close - entry_price) / entry_price if entry_price > 0 else 0
            pnl_amount = (last_close - entry_price) * shares
            cash += last_close * shares

            trades.append(TradeRecord(
                code=code,
                entry_date=position["entry_date"],
                entry_price=entry_price,
                exit_date=last_dt,
                exit_price=last_close,
                shares=shares,
                pnl=pnl_amount,
                pnl_pct=pnl_pct * 100,
                exit_reason="PERIOD_END",
            ))
            equity[-1] = cash

        eq_series = pd.Series(equity, name="equity") if equity else pd.Series(dtype=float)
        return calc_metrics(code, trades, capital, eq_series)
