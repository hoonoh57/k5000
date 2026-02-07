# -*- coding: utf-8 -*-
"""
core/types.py  [IMMUTABLE]
==========================
프로젝트 전역에서 사용하는 데이터 타입 정의.
모든 모듈은 이 타입들만 주고받으며, 직접 dict나 tuple을 사용하지 않는다.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum, auto
from datetime import date, datetime
from typing import Optional, List
import pandas as pd


# ── 시장 레짐 ──
class Regime(Enum):
    BULL = auto()      # 상승장
    BEAR = auto()      # 하락장
    SIDEWAYS = auto()  # 횡보장


# ── 신호 방향 ──
class Direction(Enum):
    BUY = auto()
    SELL = auto()
    HOLD = auto()


# ── 캔들 데이터 ──
@dataclass(frozen=True)
class Candle:
    dt: date
    open: float
    high: float
    low: float
    close: float
    volume: int


# ── 매매 신호 ──
@dataclass
class Signal:
    direction: Direction
    code: str           # 종목코드
    dt: date
    price: float
    reason: str = ""    # 사람이 읽을 수 있는 사유


# ── 매매 기록 ──
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


# ── 백테스트 결과 요약 ──
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


# ── 종목 스크리닝 후보 ──
@dataclass
class Candidate:
    code: str
    name: str
    score: float = 0.0       # 스크리닝 점수
    beta: float = 0.0
    correlation: float = 0.0
    avg_volume: float = 0.0
