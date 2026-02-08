# -*- coding: utf-8 -*-
"""
core/strategy_executor.py
전략 실행 엔진 — v3.0
 • 그룹핑된 JSON 조건 → DataFrame 필터링/신호 생성
 • CrossOver/CrossUnder 지원
 • NOT 지원
 • 강제청산 4대 규칙 적용
"""
from __future__ import annotations

import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  조건 평가 엔진
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _get_series(df: pd.DataFrame, indicator: str) -> pd.Series:
    """지표명으로 DataFrame 컬럼을 가져온다.
    '.'이 포함된 경우 (예: momentum.vs_kospi_ratio) 그대로 컬럼명으로 사용."""
    if indicator in df.columns:
        return df[indicator]
    # 대소문자 무시 검색
    for col in df.columns:
        if col.lower() == indicator.lower():
            return df[col]
    raise KeyError(f"지표 '{indicator}'를 데이터에서 찾을 수 없습니다.")


def _eval_single_rule(df: pd.DataFrame, rule: dict) -> pd.Series:
    """단일 규칙을 평가하여 bool Series 반환"""
    indicator = rule.get("indicator", "")
    op = rule.get("op", "==")
    value = rule.get("value")
    negated = rule.get("negated", False)

    series = _get_series(df, indicator)

    if op == "CrossOver":
        # value가 숫자면 고정값, 문자열이면 다른 지표
        if isinstance(value, str) and value in df.columns:
            other = _get_series(df, value)
        else:
            other = float(value)
        if isinstance(other, pd.Series):
            result = (series > other) & (series.shift(1) <= other.shift(1))
        else:
            result = (series > other) & (series.shift(1) <= other)

    elif op == "CrossUnder":
        if isinstance(value, str) and value in df.columns:
            other = _get_series(df, value)
        else:
            other = float(value)
        if isinstance(other, pd.Series):
            result = (series < other) & (series.shift(1) >= other.shift(1))
        else:
            result = (series < other) & (series.shift(1) >= other)

    elif op == "change_to":
        # 이전 값과 다르고 현재 값이 target인 경우
        target = float(value) if not isinstance(value, bool) else value
        result = (series == target) & (series.shift(1) != target)

    elif op == "in":
        # value를 리스트로 변환
        if isinstance(value, str):
            vals = [v.strip() for v in value.split(",")]
        elif isinstance(value, list):
            vals = value
        else:
            vals = [value]
        result = series.isin(vals)

    else:
        # 비교 연산자
        try:
            cmp_val = float(value) if not isinstance(value, bool) else value
        except (ValueError, TypeError):
            cmp_val = value

        if op == "==":
            result = series == cmp_val
        elif op == "!=":
            result = series != cmp_val
        elif op == ">":
            result = series > cmp_val
        elif op == ">=":
            result = series >= cmp_val
        elif op == "<":
            result = series < cmp_val
        elif op == "<=":
            result = series <= cmp_val
        else:
            logger.warning(f"알 수 없는 연산자: {op}")
            result = pd.Series(False, index=df.index)

    # NOT 처리
    if negated:
        result = ~result

    return result.fillna(False)


def _eval_group(df: pd.DataFrame, group: dict) -> pd.Series:
    """조건 그룹을 평가 — 그룹 내 로직(AND/OR)으로 결합"""
    logic = group.get("logic", "AND").upper()
    rules = group.get("rules", [])

    if not rules:
        return pd.Series(True, index=df.index)

    results = []
    for rule in rules:
        try:
            results.append(_eval_single_rule(df, rule))
        except KeyError as e:
            logger.warning(f"규칙 평가 실패: {e}")
            results.append(pd.Series(False, index=df.index))

    if logic == "AND":
        combined = results[0]
        for r in results[1:]:
            combined = combined & r
    else:  # OR
        combined = results[0]
        for r in results[1:]:
            combined = combined | r

    return combined


def eval_conditions(df: pd.DataFrame, conditions: dict) -> pd.Series:
    """
    전체 조건 구조를 평가하여 bool Series 반환.

    지원 형태:
    1) {"logic": "AND", "rules": [...]}           — 단일 그룹
    2) {"logic": "OR", "groups": [...]}            — 다중 그룹
    3) [rule1, rule2, ...]                         — 하위 호환 (AND)
    """
    if not conditions:
        return pd.Series(True, index=df.index)

    # 하위 호환: 리스트
    if isinstance(conditions, list):
        return _eval_group(df, {"logic": "AND", "rules": conditions})

    # 단일 그룹
    if "rules" in conditions and "groups" not in conditions:
        return _eval_group(df, conditions)

    # 다중 그룹
    inter_logic = conditions.get("logic", "OR").upper()
    groups = conditions.get("groups", [])

    if not groups:
        return pd.Series(True, index=df.index)

    group_results = []
    for grp in groups:
        group_results.append(_eval_group(df, grp))

    if inter_logic == "AND":
        combined = group_results[0]
        for r in group_results[1:]:
            combined = combined & r
    else:  # OR
        combined = group_results[0]
        for r in group_results[1:]:
            combined = combined | r

    return combined


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  스크리닝 전략 실행
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def execute_screen_strategy(
    df: pd.DataFrame,
    strategy: dict,
    top_n: int = 10,
) -> pd.DataFrame:
    """
    스크리닝 전략 실행.
    strategy: DB에서 읽은 전략 dict (conditions, grouping 등)
    df: 유니버스 DataFrame (종목별 1행)
    반환: 필터링 + 랭킹된 DataFrame
    """
    conditions = strategy.get("conditions", {})
    grouping = strategy.get("grouping", {})

    # 조건 필터링
    mask = eval_conditions(df, conditions)
    filtered = df[mask].copy()

    if filtered.empty:
        logger.warning("스크리닝 결과: 조건을 만족하는 종목이 없습니다.")
        return filtered

    # 랭킹
    if grouping and isinstance(grouping, dict):
        ranking = grouping.get("ranking", {})
        rank_by = ranking.get("by", "")
        rank_order = ranking.get("order", "desc")
        if rank_by and rank_by in filtered.columns:
            ascending = rank_order.lower() == "asc"
            filtered = filtered.sort_values(rank_by, ascending=ascending)

        select = grouping.get("select", top_n)
        filtered = filtered.head(select)

    else:
        filtered = filtered.head(top_n)

    logger.info(f"스크리닝 결과: {len(filtered)}개 종목 선정")
    return filtered


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  매매 신호 생성
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def generate_trade_signals(
    df: pd.DataFrame,
    strategy: dict,
) -> pd.DataFrame:
    """
    매매 전략의 매수/매도 조건을 평가하여 신호 컬럼 추가.
    strategy: DB에서 읽은 매매 전략 dict
    df: 종목의 시계열 DataFrame

    추가 컬럼:
      - signal_buy: bool
      - signal_sell: bool
    """
    buy_rules = strategy.get("buy_rules", {})
    sell_rules = strategy.get("sell_rules", {})

    df = df.copy()
    df["signal_buy"] = eval_conditions(df, buy_rules)
    df["signal_sell"] = eval_conditions(df, sell_rules)

    buy_count = df["signal_buy"].sum()
    sell_count = df["signal_sell"].sum()
    logger.info(f"신호 생성: 매수 {buy_count}건, 매도 {sell_count}건")

    return df


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  강제청산 규칙 적용
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class ExitRuleEngine:
    """강제청산 4대 규칙을 거래에 적용"""

    def __init__(self, exit_rules: dict):
        self._rules = exit_rules or {}

    @property
    def stop_loss_pct(self) -> Optional[float]:
        sl = self._rules.get("stop_loss", {})
        if sl.get("enabled", False):
            return sl.get("pct", -5.0) / 100.0  # -5% → -0.05
        return None

    @property
    def take_profit_pct(self) -> Optional[float]:
        tp = self._rules.get("take_profit", {})
        if tp.get("enabled", False):
            return tp.get("pct", 15.0) / 100.0  # 15% → 0.15
        return None

    @property
    def trailing_stop(self) -> Optional[dict]:
        ts = self._rules.get("trailing_stop", {})
        if ts.get("enabled", False):
            return {
                "pct": ts.get("pct", 3.0) / 100.0,
                "activate_after": ts.get("activate_after_pct", 2.0) / 100.0,
            }
        return None

    @property
    def stagnant_close(self) -> Optional[dict]:
        sc = self._rules.get("stagnant_close", {})
        if sc.get("enabled", False):
            return {
                "bars": sc.get("bars", 10),
                "min_move_pct": sc.get("min_move_pct", 1.0) / 100.0,
            }
        return None

    def check_exit(
        self,
        entry_price: float,
        current_price: float,
        max_price_since_entry: float,
        bars_held: int,
        price_range_pct: float,
    ) -> Tuple[bool, str]:
        """
        청산 여부와 사유를 반환.

        Args:
            entry_price: 진입가
            current_price: 현재가
            max_price_since_entry: 진입 이후 최고가
            bars_held: 보유 봉 수
            price_range_pct: 보유 기간 중 (고가-저가)/진입가

        Returns:
            (should_exit, reason)
        """
        pnl_pct = (current_price - entry_price) / entry_price

        # 1. 최대허용손실
        sl = self.stop_loss_pct
        if sl is not None and pnl_pct <= sl:
            return True, f"손절 ({pnl_pct:.2%} ≤ {sl:.2%})"

        # 2. 목표수익
        tp = self.take_profit_pct
        if tp is not None and pnl_pct >= tp:
            return True, f"익절 ({pnl_pct:.2%} ≥ {tp:.2%})"

        # 3. 트레일링 스톱
        ts = self.trailing_stop
        if ts is not None:
            max_pnl = (max_price_since_entry - entry_price) / entry_price
            if max_pnl >= ts["activate_after"]:
                drawdown_from_peak = (
                    (max_price_since_entry - current_price)
                    / max_price_since_entry
                )
                if drawdown_from_peak >= ts["pct"]:
                    return True, (
                        f"트레일링 스톱 (고점 대비 "
                        f"-{drawdown_from_peak:.2%} ≥ -{ts['pct']:.2%})")

        # 4. 무변동 청산
        sc = self.stagnant_close
        if sc is not None:
            if bars_held >= sc["bars"] and price_range_pct < sc["min_move_pct"]:
                return True, (
                    f"무변동 청산 ({bars_held}봉간 "
                    f"변동 {price_range_pct:.2%} < {sc['min_move_pct']:.2%})")

        return False, ""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  통합 백테스트 실행기
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class StrategyBacktester:
    """DB 전략 기반 백테스트 실행기"""

    def __init__(self, strategy: dict, initial_capital: float = 10_000_000):
        self._strategy = strategy
        self._initial_capital = initial_capital

        params = strategy.get("params", {}) or {}
        exit_rules = params.get("exit_rules", {})
        self._exit_engine = ExitRuleEngine(exit_rules)

    def run(self, df: pd.DataFrame) -> dict:
        """
        백테스트 실행.

        Args:
            df: 지표가 계산된 시계열 DataFrame
                (st_dir, jma_slope 등 필요 컬럼 포함)

        Returns:
            {
                "trades": [...],
                "total_return_pct": float,
                "win_rate": float,
                "max_drawdown_pct": float,
                "trade_count": int,
                "equity_curve": [...],
            }
        """
        # 매수/매도 신호 생성
        df = generate_trade_signals(df, self._strategy)

        capital = self._initial_capital
        position = None  # {"entry_idx", "entry_price", "shares", "max_price"}
        trades = []
        equity_curve = []

        for i in range(len(df)):
            row = df.iloc[i]
            date = df.index[i] if isinstance(df.index[i], datetime) else \
                pd.Timestamp(df.index[i])

            if position is None:
                # 포지션 없음 → 매수 신호 확인
                if row.get("signal_buy", False):
                    price = row["close"]
                    shares = int(capital * 0.95 / price)  # 95% 투자
                    if shares > 0:
                        position = {
                            "entry_idx": i,
                            "entry_date": date,
                            "entry_price": price,
                            "shares": shares,
                            "max_price": price,
                            "min_price_in_window": price,
                            "max_price_in_window": price,
                        }
                        capital -= shares * price

            else:
                # 포지션 보유 중
                current_price = row["close"]
                position["max_price"] = max(
                    position["max_price"], row.get("high", current_price))

                bars_held = i - position["entry_idx"]

                # 최근 봉들의 가격 범위 계산 (무변동 판단용)
                sc = self._exit_engine.stagnant_close
                if sc:
                    window = min(bars_held, sc["bars"])
                    if window > 0:
                        window_slice = df.iloc[i - window:i + 1]
                        high_max = window_slice["high"].max() if "high" in \
                            window_slice.columns else current_price
                        low_min = window_slice["low"].min() if "low" in \
                            window_slice.columns else current_price
                        price_range_pct = (
                            (high_max - low_min) / position["entry_price"]
                        )
                    else:
                        price_range_pct = 1.0
                else:
                    price_range_pct = 1.0

                # 강제청산 확인
                should_exit, exit_reason = self._exit_engine.check_exit(
                    entry_price=position["entry_price"],
                    current_price=current_price,
                    max_price_since_entry=position["max_price"],
                    bars_held=bars_held,
                    price_range_pct=price_range_pct,
                )

                # 매도 신호 확인
                if not should_exit and row.get("signal_sell", False):
                    should_exit = True
                    exit_reason = "매도 조건"

                if should_exit:
                    pnl = (current_price - position["entry_price"]) * \
                        position["shares"]
                    pnl_pct = (
                        (current_price - position["entry_price"])
                        / position["entry_price"]
                    )
                    capital += position["shares"] * current_price
                    trades.append({
                        "entry_date": position["entry_date"],
                        "entry_price": position["entry_price"],
                        "exit_date": date,
                        "exit_price": current_price,
                        "shares": position["shares"],
                        "pnl": pnl,
                        "pnl_pct": pnl_pct,
                        "exit_reason": exit_reason,
                        "bars_held": bars_held,
                    })
                    position = None

            # 자본곡선
            if position:
                mark_to_market = capital + position["shares"] * row["close"]
            else:
                mark_to_market = capital
            equity_curve.append({
                "date": date,
                "equity": mark_to_market,
            })

        # 마지막 포지션 강제 청산
        if position and len(df) > 0:
            last_row = df.iloc[-1]
            current_price = last_row["close"]
            pnl = (current_price - position["entry_price"]) * \
                position["shares"]
            pnl_pct = (
                (current_price - position["entry_price"])
                / position["entry_price"]
            )
            capital += position["shares"] * current_price
            date = df.index[-1] if isinstance(df.index[-1], datetime) else \
                pd.Timestamp(df.index[-1])
            trades.append({
                "entry_date": position["entry_date"],
                "entry_price": position["entry_price"],
                "exit_date": date,
                "exit_price": current_price,
                "shares": position["shares"],
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "exit_reason": "기간 종료",
                "bars_held": len(df) - 1 - position["entry_idx"],
            })

        # 성과 지표 계산
        result = self._calc_metrics(trades, equity_curve)
        return result

    def _calc_metrics(self, trades: list, equity_curve: list) -> dict:
        trade_count = len(trades)
        if trade_count == 0:
            return {
                "trades": [],
                "total_return_pct": 0.0,
                "win_rate": 0.0,
                "max_drawdown_pct": 0.0,
                "trade_count": 0,
                "win_count": 0,
                "lose_count": 0,
                "avg_pnl_pct": 0.0,
                "avg_holding_days": 0.0,
                "sharpe_ratio": 0.0,
                "initial_capital": self._initial_capital,
                "final_capital": self._initial_capital,
                "equity_curve": equity_curve,
            }

        wins = [t for t in trades if t["pnl"] > 0]
        losses = [t for t in trades if t["pnl"] <= 0]
        pnl_list = [t["pnl_pct"] for t in trades]

        total_return = 1.0
        for p in pnl_list:
            total_return *= (1 + p)
        total_return_pct = (total_return - 1) * 100

        final_capital = self._initial_capital * total_return

        # 최대 낙폭
        equities = [e["equity"] for e in equity_curve] if equity_curve else \
            [self._initial_capital]
        peak = equities[0]
        max_dd = 0.0
        for eq in equities:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd

        # 샤프 비율
        if len(pnl_list) > 1:
            avg_ret = np.mean(pnl_list)
            std_ret = np.std(pnl_list)
            sharpe = (avg_ret / std_ret * np.sqrt(252)) if std_ret > 0 else 0
        else:
            sharpe = 0.0

        # 평균 보유일
        holding_days = [t.get("bars_held", 0) for t in trades]
        avg_holding = np.mean(holding_days) if holding_days else 0

        return {
            "trades": trades,
            "total_return_pct": round(total_return_pct, 2),
            "win_rate": round(len(wins) / trade_count * 100, 2),
            "max_drawdown_pct": round(-max_dd * 100, 2),
            "trade_count": trade_count,
            "win_count": len(wins),
            "lose_count": len(losses),
            "avg_pnl_pct": round(np.mean(pnl_list) * 100, 2),
            "avg_holding_days": round(avg_holding, 1),
            "sharpe_ratio": round(sharpe, 4),
            "initial_capital": self._initial_capital,
            "final_capital": round(final_capital, 0),
            "equity_curve": equity_curve,
        }
