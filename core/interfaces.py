# -*- coding: utf-8 -*-
"""
core/interfaces.py  [IMMUTABLE]
===============================
모든 플러그인이 구현해야 하는 인터페이스(추상 클래스).
코어는 구체 구현을 모르고, 이 인터페이스만 의존한다.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any, Callable
import pandas as pd

from core.types import Candle, Signal, Direction, Regime, Candidate, TradeRecord


class IDataSource(ABC):
    """데이터 공급 인터페이스"""
    @abstractmethod
    def fetch_candles(self, code: str, start: str, end: str) -> pd.DataFrame:
        """OHLCV DataFrame 반환. 컬럼: date,open,high,low,close,volume"""
        ...

    @abstractmethod
    def fetch_index_candles(self, index_code: str, start: str, end: str) -> pd.DataFrame:
        ...


class IIndicator(ABC):
    """기술적 지표 계산 인터페이스"""
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def compute(self, df: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
        """입력 df에 지표 컬럼을 추가하여 반환"""
        ...


class ISignalGenerator(ABC):
    """매매 신호 생성 인터페이스"""
    @abstractmethod
    def generate(self, df: pd.DataFrame, code: str, params: Dict[str, Any]) -> List[Signal]:
        ...


class IRegimeDetector(ABC):
    """시장 레짐 판단 인터페이스"""
    @abstractmethod
    def detect(self, index_df: pd.DataFrame, params: Dict[str, Any]) -> Regime:
        ...


class IScreener(ABC):
    """종목 스크리닝 인터페이스"""
    @abstractmethod
    def screen(self, universe: List[str], index_df: pd.DataFrame,
               data_source: IDataSource, params: Dict[str, Any]) -> List[Candidate]:
        ...


class IBroker(ABC):
    """증권사 브로커 인터페이스"""
    @abstractmethod
    def send_order(self, account: str, code: str, qty: int,
                   price: int, side: str, order_type: str) -> str:
        """주문번호(문자열) 반환"""
        ...

    @abstractmethod
    def cancel_order(self, order_no: str, code: str, qty: int) -> bool:
        ...

    @abstractmethod
    def get_balance(self, account: str) -> Dict[str, Any]:
        ...

    @abstractmethod
    def get_unfilled_orders(self, account: str) -> List[Dict[str, Any]]:
        ...


class IRiskGate(ABC):
    """리스크 게이트 — 주문 전 거부권"""
    @abstractmethod
    def check(self, order_info: Dict[str, Any]) -> bool:
        """True면 통과, False면 주문 거부"""
        ...

    @abstractmethod
    def on_trade_closed(self, record: TradeRecord) -> None:
        """거래 종료 후 상태 업데이트 (연속손실 카운트 등)"""
        ...
