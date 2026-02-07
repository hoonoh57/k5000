# -*- coding: utf-8 -*-
"""
core/risk.py
============
리스크 관리: 서킷브레이커, 포지션사이징, 노출한도.
백테스트·실매매 공통.
"""
from __future__ import annotations
from typing import Dict, Any, Optional, Callable
from datetime import datetime
import logging

from core.interfaces import IRiskGate
from core.types import TradeRecord

logger = logging.getLogger(__name__)


class RiskManager(IRiskGate):
    """
    통합 리스크 관리.
    - 일일/주간/월간 손실 한도
    - 연속 손실 횟수 → 재조정 콜백 트리거
    - 최대 동시 포지션, 종목당/섹터당 비중 제한
    - 백테스트 모드: 섹터/주간 체크 생략 가능
    """

    def __init__(
        self,
        max_daily_loss_pct: float = -5.0,
        max_weekly_loss_pct: float = -10.0,
        max_monthly_loss_pct: float = -20.0,
        max_consecutive_losses: int = 3,
        max_positions: int = 10,
        max_per_stock_pct: float = 100.0,
        max_per_sector_pct: float = 100.0,
        on_recalibrate: Optional[Callable] = None,
        backtest_mode: bool = True,
    ) -> None:
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_weekly_loss_pct = max_weekly_loss_pct
        self.max_monthly_loss_pct = max_monthly_loss_pct
        self.max_consecutive_losses = max_consecutive_losses
        self.max_positions = max_positions
        self.max_per_stock_pct = max_per_stock_pct
        self.max_per_sector_pct = max_per_sector_pct
        self._on_recalibrate = on_recalibrate
        self._backtest_mode = backtest_mode

        # 상태
        self._consecutive_losses = 0
        self._daily_pnl_pct = 0.0
        self._weekly_pnl_pct = 0.0
        self._monthly_pnl_pct = 0.0
        self._open_positions = 0
        self._sector_exposure: Dict[str, float] = {}
        self._circuit_breaker_on = False
        self._last_reset_day = datetime.now().date()
        self._last_reset_week = datetime.now().isocalendar()[1]
        self._last_reset_month = datetime.now().month

    def check(self, order_info: Dict[str, Any]) -> bool:
        if not self._backtest_mode:
            self._auto_reset()

        if self._circuit_breaker_on:
            logger.warning("RiskManager: circuit breaker active")
            return False

        if self._consecutive_losses >= self.max_consecutive_losses:
            logger.warning(
                f"RiskManager: {self._consecutive_losses} consecutive losses"
            )
            self._circuit_breaker_on = True
            if self._on_recalibrate:
                self._on_recalibrate()
            return False

        if self._daily_pnl_pct <= self.max_daily_loss_pct:
            logger.warning("RiskManager: daily loss limit hit")
            self._circuit_breaker_on = True
            return False

        if not self._backtest_mode:
            if self._weekly_pnl_pct <= self.max_weekly_loss_pct:
                logger.warning("RiskManager: weekly loss limit hit")
                self._circuit_breaker_on = True
                return False

        if self._monthly_pnl_pct <= self.max_monthly_loss_pct:
            logger.warning("RiskManager: monthly loss limit hit")
            self._circuit_breaker_on = True
            return False

        if self._open_positions >= self.max_positions:
            logger.warning("RiskManager: max positions reached")
            return False

        # 종목당 비중
        stock_pct = order_info.get("stock_pct", 0.0)
        if stock_pct > self.max_per_stock_pct:
            logger.warning(
                f"RiskManager: stock exposure {stock_pct:.1f}% > {self.max_per_stock_pct}%"
            )
            return False

        # 섹터당 비중 (실매매 전용)
        if not self._backtest_mode:
            sector = order_info.get("sector", "")
            if sector and self.max_per_sector_pct < 100.0:
                sector_total = self._sector_exposure.get(sector, 0.0) + stock_pct
                if sector_total > self.max_per_sector_pct:
                    logger.warning(
                        f"RiskManager: sector {sector} {sector_total:.1f}% > {self.max_per_sector_pct}%"
                    )
                    return False

        return True

    def on_trade_closed(self, record: TradeRecord) -> None:
        self._daily_pnl_pct += record.pnl_pct
        self._weekly_pnl_pct += record.pnl_pct
        self._monthly_pnl_pct += record.pnl_pct
        if record.pnl_pct < 0:
            self._consecutive_losses += 1
        else:
            self._consecutive_losses = 0
        self._open_positions = max(0, self._open_positions - 1)
        # 섹터 노출 감소
        if record.sector and record.sector in self._sector_exposure:
            self._sector_exposure[record.sector] = max(
                0.0, self._sector_exposure[record.sector] - 100.0 / self.max_positions
            )

    def on_position_opened(self, sector: str = "", pct: float = 0.0) -> None:
        self._open_positions += 1
        if sector:
            self._sector_exposure[sector] = (
                self._sector_exposure.get(sector, 0.0) + pct
            )

    def calc_position_size(
        self, capital: float, entry_price: float,
        atr: float, risk_pct: float = 1.0,
        atr_multiplier: float = 2.0,
    ) -> int:
        if atr <= 0 or entry_price <= 0:
            return 0
        risk_amount = capital * (risk_pct / 100.0)
        stop_distance = atr * atr_multiplier
        shares = int(risk_amount / stop_distance)
        max_shares = int(
            capital * (self.max_per_stock_pct / 100.0) / entry_price
        )
        return min(shares, max_shares) if shares > 0 else 0

    def set_live_mode(self) -> None:
        """실매매 모드 전환."""
        self._backtest_mode = False

    def set_backtest_mode(self) -> None:
        """백테스트 모드 전환."""
        self._backtest_mode = True

    def reset_daily(self) -> None:
        self._daily_pnl_pct = 0.0
        if (self._weekly_pnl_pct > self.max_weekly_loss_pct and
                self._monthly_pnl_pct > self.max_monthly_loss_pct):
            self._circuit_breaker_on = False

    def reset_weekly(self) -> None:
        self._weekly_pnl_pct = 0.0

    def reset_monthly(self) -> None:
        self._monthly_pnl_pct = 0.0
        self._circuit_breaker_on = False

    def _auto_reset(self) -> None:
        now = datetime.now()
        today = now.date()
        if today != self._last_reset_day:
            self.reset_daily()
            self._last_reset_day = today
        cw = now.isocalendar()[1]
        if cw != self._last_reset_week:
            self.reset_weekly()
            self._last_reset_week = cw
        if now.month != self._last_reset_month:
            self.reset_monthly()
            self._last_reset_month = now.month
