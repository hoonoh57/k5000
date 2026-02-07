# -*- coding: utf-8 -*-
"""
core/interfaces.py
==================
플러그인 인터페이스. 코어는 구체 구현을 모르고 이 인터페이스만 의존.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any, Tuple
import pandas as pd

from core.types import (
    Candle, Signal, Direction, Regime, RegimeState,
    Candidate, TradeRecord,
)


class IDataSource(ABC):
    @abstractmethod
    def fetch_candles(self, code: str, start: str, end: str) -> pd.DataFrame:
        ...

    @abstractmethod
    def fetch_index_candles(self, index_code: str, start: str, end: str) -> pd.DataFrame:
        ...


class IIndicator(ABC):
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def compute(self, df: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
        ...


class ISignalGenerator(ABC):
    @abstractmethod
    def generate(self, df: pd.DataFrame, code: str,
                 params: Dict[str, Any]) -> List[Signal]:
        ...


class IRegimeDetector(ABC):
    @abstractmethod
    def detect(self, index_df: pd.DataFrame,
               params: Dict[str, Any]) -> Regime:
        ...

    def detect_detailed(self, index_df: pd.DataFrame,
                        params: Dict[str, Any]) -> RegimeState:
        """상세 레짐 판단. 기본 구현은 detect()를 래핑."""
        regime = self.detect(index_df, params)
        alloc = {Regime.BULL: 1.0, Regime.SIDEWAYS: 0.4, Regime.BEAR: 0.1}
        return RegimeState(
            regime=regime,
            confidence=0.5,
            capital_allocation=alloc.get(regime, 0.4),
        )


class IStrategyRouter(ABC):
    """레짐 → (신호 생성기 + 파라미터 오버라이드) 매핑."""

    @abstractmethod
    def select(self, regime: Regime,
               base_params: Dict[str, Any]) -> Tuple[ISignalGenerator, Dict[str, Any]]:
        ...


class IScreener(ABC):
    @abstractmethod
    def screen(self, universe: List[str], index_df: pd.DataFrame,
               data_source: IDataSource, params: Dict[str, Any]) -> List[Candidate]:
        ...


class IBroker(ABC):
    @abstractmethod
    def send_order(self, account: str, code: str, qty: int,
                   price: int, side: str, order_type: str) -> str:
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
    @abstractmethod
    def check(self, order_info: Dict[str, Any]) -> bool:
        ...

    @abstractmethod
    def on_trade_closed(self, record: TradeRecord) -> None:
        ...
