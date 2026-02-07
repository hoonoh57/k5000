# -*- coding: utf-8 -*-
"""
core/types.py
=============
프로젝트 전역 데이터 타입.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum, auto
from datetime import date
from typing import Optional, List, Dict, Any
import pandas as pd


class Regime(Enum):
    BULL = auto()
    BEAR = auto()
    SIDEWAYS = auto()


class Direction(Enum):
    BUY = auto()
    SELL = auto()
    HOLD = auto()


@dataclass(frozen=True)
class Candle:
    dt: date
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass
class Signal:
    direction: Direction
    code: str
    dt: date
    price: float
    reason: str = ""
    strength: float = 0.0          # 신호 강도 0~1


@dataclass
class TradeRecord:
    code: str
    entry_date: date
    entry_price: float
    exit_date: Optional[date] = None
    exit_price: Optional[float] = None
    shares: int = 0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    exit_reason: str = ""
    sector: str = ""               # 섹터 (리스크 관리용)


@dataclass
class BacktestResult:
    code: str
    initial_capital: float
    final_capital: float
    total_return_pct: float
    trade_count: int
    win_count: int
    lose_count: int
    win_rate: float
    avg_pnl_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    avg_holding_days: float
    trades: List[TradeRecord] = field(default_factory=list)
    equity_curve: Optional[pd.Series] = None
    regime_used: Optional[Regime] = None  # 어떤 레짐으로 실행했는지


@dataclass
class Candidate:
    code: str
    name: str
    score: float = 0.0
    beta: float = 0.0
    correlation: float = 0.0
    avg_volume: float = 0.0
    sector: str = ""               # 섹터 분류


@dataclass
class RegimeState:
    """매크로 레짐 판단 결과 상세."""
    regime: Regime
    confidence: float = 0.0        # 0~1 확신도
    scores: Dict[str, float] = field(default_factory=dict)  # 개별 지표 점수
    capital_allocation: float = 1.0  # 권장 자본 배분 비율
    description: str = ""
