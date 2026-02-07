# -*- coding: utf-8 -*-
"""
core/order_manager.py  [IMMUTABLE]
==================================
주문 생애주기 관리.
생성 → 중복검사 → 리스크검증 → 전송 → 접수 → 체결 → 잔고갱신

브로커(IBroker)는 set_broker()로 주입. 코어는 브로커 구현을 모른다.
"""
from __future__ import annotations
from typing import Dict, Optional, Callable, Any
from datetime import datetime
import logging
import traceback
from pathlib import Path

from core.order_types import Order, OrderSide, OrderStatus, BalanceItem, AccountInfo
from core.interfaces import IBroker, IRiskGate
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


class OrderManager:
    """주문 관리자 — 불변 코어."""

    def __init__(self, event_bus: EventBus) -> None:
        self._bus = event_bus
        self._broker: Optional[IBroker] = None
        self._risk: Optional[IRiskGate] = None
        self._orders: Dict[str, Order] = {}          # order_no -> Order
        self._pending: Dict[str, Order] = {}          # code -> 활성 주문 (중복 방지)
        self._account = AccountInfo()

    # ── 의존성 주입 ──
    def set_broker(self, broker: IBroker) -> None:
        self._broker = broker

    def set_risk_gate(self, risk: IRiskGate) -> None:
        self._risk = risk

    @property
    def account(self) -> AccountInfo:
        return self._account

    @property
    def active_orders(self) -> Dict[str, Order]:
        return {k: v for k, v in self._orders.items()
                if v.status in (OrderStatus.SUBMITTED, OrderStatus.ACCEPTED, OrderStatus.PARTIAL)}

    # ── 주문 생성 ──
    def create_order(self, order: Order) -> bool:
        try:
            # 중복 검사
            if self._check_duplicate(order):
                logger.warning(f"중복 주문 차단: {order.code} {order.side.name}")
                return False

            # 리스크 검증
            if self._risk:
                info = {"code": order.code, "side": order.side.name,
                        "qty": order.qty, "price": order.price}
                if not self._risk.check(info):
                    logger.warning(f"리스크 거부: {order.code}")
                    order.status = OrderStatus.REJECTED
                    order.reject_reason = "Risk gate rejected"
                    return False

            # 전송
            return self._submit(order)

        except Exception as e:
            msg = f"create_order error: {e}\n{traceback.format_exc()}"
            logger.error(msg)
            _log_error(msg)
            order.status = OrderStatus.FAILED
            return False

    def _check_duplicate(self, order: Order) -> bool:
        active = self._pending.get(order.code)
        if active and active.status in (OrderStatus.SUBMITTED, OrderStatus.ACCEPTED, OrderStatus.PARTIAL):
            if active.side == order.side:
                return True
        return False

    def _submit(self, order: Order) -> bool:
        if not self._broker:
            logger.error("브로커가 설정되지 않음")
            order.status = OrderStatus.FAILED
            order.reject_reason = "No broker"
            return False

        try:
            side_str = "1" if order.side == OrderSide.BUY else "2"
            order_no = self._broker.send_order(
                account=self._account.account_no,
                code=order.code,
                qty=order.qty,
                price=order.price,
                side=side_str,
                order_type=order.price_type.value,
            )
            if order_no:
                order.order_no = order_no
                order.status = OrderStatus.SUBMITTED
                order.updated_at = datetime.now()
                self._orders[order_no] = order
                self._pending[order.code] = order
                self._bus.publish("order_submitted", order=order)
                logger.info(f"주문 전송: {order.code} {order.side.name} {order.qty}주 @ {order.price}")
                return True
            else:
                order.status = OrderStatus.FAILED
                order.reject_reason = "send_order returned empty"
                return False
        except Exception as e:
            msg = f"_submit error: {e}\n{traceback.format_exc()}"
            logger.error(msg)
            _log_error(msg)
            order.status = OrderStatus.FAILED
            return False

    # ── 이벤트 핸들러 (브로커 콜백에서 호출) ──
    def on_order_accepted(self, order_no: str) -> None:
        order = self._orders.get(order_no)
        if order:
            order.status = OrderStatus.ACCEPTED
            order.updated_at = datetime.now()
            self._bus.publish("order_accepted", order=order)

    def on_order_filled(self, order_no: str, filled_qty: int, filled_price: float) -> None:
        order = self._orders.get(order_no)
        if not order:
            return

        order.filled_qty += filled_qty
        order.filled_price = filled_price
        order.updated_at = datetime.now()

        if order.filled_qty >= order.qty:
            order.status = OrderStatus.FILLED
            self._pending.pop(order.code, None)
        else:
            order.status = OrderStatus.PARTIAL

        self._update_balance_from_fill(order, filled_qty, filled_price)
        self._bus.publish("order_filled", order=order,
                          filled_qty=filled_qty, filled_price=filled_price)
        logger.info(f"체결: {order.code} {order.side.name} {filled_qty}주 @ {filled_price}")

    def on_order_cancelled(self, order_no: str) -> None:
        order = self._orders.get(order_no)
        if order:
            order.status = OrderStatus.CANCELLED
            order.updated_at = datetime.now()
            self._pending.pop(order.code, None)
            self._bus.publish("order_cancelled", order=order)

    # ── 잔고 갱신 ──
    def _update_balance_from_fill(self, order: Order, qty: int, price: float) -> None:
        holdings = self._account.holdings
        item = holdings.get(order.code, BalanceItem(code=order.code))

        if order.side == OrderSide.BUY:
            total_cost = item.avg_price * item.qty + price * qty
            item.qty += qty
            item.avg_price = total_cost / item.qty if item.qty > 0 else 0.0
        elif order.side == OrderSide.SELL:
            item.qty -= qty
            if item.qty <= 0:
                holdings.pop(order.code, None)
                return

        holdings[order.code] = item

    def sync_balance(self) -> None:
        """브로커로부터 잔고 동기화"""
        if not self._broker:
            return
        try:
            data = self._broker.get_balance(self._account.account_no)
            if data:
                self._account.deposit = data.get("deposit", self._account.deposit)
                self._account.total_eval = data.get("total_eval", self._account.total_eval)
                # 상세 항목은 브로커 어댑터에서 파싱하여 제공
        except Exception as e:
            _log_error(f"sync_balance error: {e}")
