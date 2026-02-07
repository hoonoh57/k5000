# -*- coding: utf-8 -*-
"""
core/risk.py  [IMMUTABLE]
=========================
리스크 관리: 서킷브레이커, 포지션사이징, 노출한도.
"""
from __future__ import annotations
from typing import Dict, Any
from core.interfaces import IRiskGate
from core.types import TradeRecord
import logging

logger = logging.getLogger(__name__)


class RiskManager(IRiskGate):
    """
    리스크 관리 모듈.
    - 일일/월간 손실 한도 초과 시 매매 중단 (서킷브레이커)
    - 연속 손실 횟수 제한
    - 최대 동시 포지션 수 제한
    - 종목당 최대 자본 비중 제한
    """

    def __init__(
        self,
        max_daily_loss_pct: float = -5.0,
        max_monthly_loss_pct: float = -10.0,
        max_consecutive_losses: int = 3,
        max_positions: int = 7,
        max_per_stock_pct: float = 20.0,
    ) -> None:
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_monthly_loss_pct = max_monthly_loss_pct
        self.max_consecutive_losses = max_consecutive_losses
        self.max_positions = max_positions
        self.max_per_stock_pct = max_per_stock_pct

        # 상태
        self._consecutive_losses = 0
        self._daily_pnl_pct = 0.0
        self._monthly_pnl_pct = 0.0
        self._open_positions = 0
        self._circuit_breaker_on = False

    # ── IRiskGate 구현 ──
    def check(self, order_info: Dict[str, Any]) -> bool:
        if self._circuit_breaker_on:
            logger.warning("RiskManager: circuit breaker active, order rejected")
            return False

        if self._consecutive_losses >= self.max_consecutive_losses:
            logger.warning(f"RiskManager: {self._consecutive_losses} consecutive losses, order rejected")
            self._circuit_breaker_on = True
            return False

        if self._daily_pnl_pct <= self.max_daily_loss_pct:
            logger.warning("RiskManager: daily loss limit hit")
            self._circuit_breaker_on = True
            return False

        if self._monthly_pnl_pct <= self.max_monthly_loss_pct:
            logger.warning("RiskManager: monthly loss limit hit")
            self._circuit_breaker_on = True
            return False

        if self._open_positions >= self.max_positions:
            logger.warning("RiskManager: max positions reached")
            return False

        return True

    def on_trade_closed(self, record: TradeRecord) -> None:
        self._daily_pnl_pct += record.pnl_pct
        self._monthly_pnl_pct += record.pnl_pct
        if record.pnl_pct < 0:
            self._consecutive_losses += 1
        else:
            self._consecutive_losses = 0
        self._open_positions = max(0, self._open_positions - 1)

    # ── 유틸리티 ──
    def on_position_opened(self) -> None:
        self._open_positions += 1

    def reset_daily(self) -> None:
        self._daily_pnl_pct = 0.0
        if not (self._monthly_pnl_pct <= self.max_monthly_loss_pct):
            self._circuit_breaker_on = False

    def reset_monthly(self) -> None:
        self._monthly_pnl_pct = 0.0
        self._circuit_breaker_on = False

    def calc_position_size(self, capital: float, entry_price: float,
                           atr: float, risk_pct: float = 1.0,
                           atr_multiplier: float = 2.0) -> int:
        """ATR 기반 포지션 사이징. 리스크 금액 = capital * risk_pct%"""
        if atr <= 0 or entry_price <= 0:
            return 0
        risk_amount = capital * (risk_pct / 100.0)
        stop_distance = atr * atr_multiplier
        shares = int(risk_amount / stop_distance)
        # 종목당 최대 비중 제한
        max_shares = int(capital * (self.max_per_stock_pct / 100.0) / entry_price)
        return min(shares, max_shares) if shares > 0 else 0
