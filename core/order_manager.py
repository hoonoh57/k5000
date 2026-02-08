# -*- coding: utf-8 -*-
"""
주문 관리자: 신호 → 주문수량 계산 → 브로커 전달 → 알림.
불변구조: 로직은 고정, 파라미터는 YAML에서 로드.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from core import config
from core.types import Signal, Direction

logger = logging.getLogger(__name__)


@dataclass
class OrderRequest:
    """주문 요청."""
    code: str
    name: str
    direction: str          # "BUY" or "SELL"
    qty: int
    price: float
    reason: str
    created_at: datetime = field(default_factory=datetime.now)
    status: str = "대기"    # 대기 → 확인 → 전송 → 체결/실패


@dataclass
class Position:
    """보유 포지션."""
    code: str
    name: str
    qty: int
    avg_price: float
    entry_date: datetime


class OrderManager:
    """신호를 주문으로 변환하고 관리한다."""

    def __init__(self, broker=None, notifier=None, event_bus=None):
        self.broker = broker
        self.notifier = notifier
        self.event_bus = event_bus
        self.risk_gate = None
        self.positions: dict[str, Position] = {}
        self.pending_orders: list[OrderRequest] = []
        self.order_history: list[OrderRequest] = []

    def set_risk_gate(self, risk_mgr):
        """리스크 매니저 연결 (main.py 호환)."""
        self.risk_gate = risk_mgr
        logger.info("[ORDER] 리스크 게이트 연결 완료")

    @property
    def total_capital(self) -> float:
        return config.get("order.total_capital", 50_000_000)

    @property
    def per_stock_pct(self) -> float:
        return config.get("order.per_stock_pct", 20.0)

    @property
    def max_stocks(self) -> int:
        return config.get("order.max_stocks", 5)

    def calc_buy_qty(self, price: float) -> int:
        """매수 수량 계산."""
        if price <= 0:
            return 0
        budget = self.total_capital * (self.per_stock_pct / 100.0)
        qty = int(budget // price)
        return qty

    def on_signal(self, signal: Signal, name: str = "",
                  regime: str = "") -> Optional[OrderRequest]:
        """
        신호 수신 → 주문 요청 생성 → 알림 전송.
        반자동 모드: 주문을 pending에 넣고 사용자 확인 대기.
        """
        mode = config.get("broker.mode", "semi_auto")
        code = signal.code
        price = signal.price

        if signal.direction == Direction.BUY:
            # 이미 보유 중이면 무시
            if code in self.positions:
                logger.info(f"[ORDER] {code} 이미 보유 중 - 매수 무시")
                return None

            # 최대 보유 종목수 초과 체크
            if len(self.positions) >= self.max_stocks:
                logger.info(f"[ORDER] 최대 보유({self.max_stocks}) 초과 - 매수 무시")
                return None

            qty = self.calc_buy_qty(price)
            if qty <= 0:
                return None

            order = OrderRequest(
                code=code, name=name, direction="BUY",
                qty=qty, price=price, reason=signal.reason,
            )

        elif signal.direction == Direction.SELL:
            # 보유 중이 아니면 무시
            if code not in self.positions:
                logger.info(f"[ORDER] {code} 미보유 - 매도 무시")
                return None

            pos = self.positions[code]
            order = OrderRequest(
                code=code, name=name, direction="SELL",
                qty=pos.qty, price=price, reason=signal.reason,
            )

        else:
            return None

        # 알림 전송
        if self.notifier:
            self.notifier.signal_alert(
                direction=order.direction, code=code, name=name,
                price=price, reason=signal.reason, regime=regime,
            )

        if mode == "full_auto":
            return self.execute(order)
        else:
            # 반자동: 대기열에 추가
            self.pending_orders.append(order)
            logger.info(
                f"[ORDER] 대기: {order.direction} {code} "
                f"{order.qty}주 @ {price:,.0f}"
            )
            return order

    def execute(self, order: OrderRequest) -> OrderRequest:
        """주문 실행 (브로커 전달)."""
        if not self.broker:
            order.status = "브로커 없음"
            logger.warning(f"[ORDER] 브로커 미연결 - 주문 미실행")
            self.order_history.append(order)
            return order

        try:
            order.status = "전송"
            result = self.broker.send_order(
                code=order.code,
                direction=order.direction,
                qty=order.qty,
                price=order.price,
            )

            if result.get("success"):
                order.status = "체결"
                # 포지션 업데이트
                if order.direction == "BUY":
                    self.positions[order.code] = Position(
                        code=order.code, name=order.name,
                        qty=order.qty, avg_price=order.price,
                        entry_date=datetime.now(),
                    )
                elif order.direction == "SELL":
                    self.positions.pop(order.code, None)
            else:
                order.status = f"실패: {result.get('message', '')}"

        except Exception as e:
            order.status = f"에러: {e}"
            logger.error(f"[ORDER] 주문 실행 에러: {e}")

        # 결과 알림
        if self.notifier:
            self.notifier.order_result(
                direction=order.direction, code=order.code,
                name=order.name, qty=order.qty,
                price=order.price, status=order.status,
            )

        self.order_history.append(order)
        if order in self.pending_orders:
            self.pending_orders.remove(order)

        return order

    def confirm_pending(self, index: int = 0) -> Optional[OrderRequest]:
        """대기 중인 주문을 사용자가 확인 후 실행."""
        if not self.pending_orders:
            logger.info("[ORDER] 대기 주문 없음")
            return None

        if index >= len(self.pending_orders):
            return None

        order = self.pending_orders[index]
        return self.execute(order)

    def reject_pending(self, index: int = 0) -> Optional[OrderRequest]:
        """대기 주문 거부."""
        if not self.pending_orders:
            return None

        if index >= len(self.pending_orders):
            return None

        order = self.pending_orders.pop(index)
        order.status = "거부"
        self.order_history.append(order)
        logger.info(f"[ORDER] 거부: {order.direction} {order.code}")
        return order

    def get_portfolio_summary(self) -> dict:
        """현재 포트폴리오 요약."""
        return {
            "positions": len(self.positions),
            "max_stocks": self.max_stocks,
            "pending_orders": len(self.pending_orders),
            "total_capital": self.total_capital,
            "invested": sum(
                p.qty * p.avg_price for p in self.positions.values()
            ),
        }
