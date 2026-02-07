# -*- coding: utf-8 -*-
"""
core/order_types.py  [IMMUTABLE]
================================
주문/체결/잔고 관련 데이터 타입.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum, auto
from datetime import datetime
from typing import Optional


class OrderSide(Enum):
    BUY = auto()
    SELL = auto()


class OrderType(Enum):
    NEW = auto()       # 신규
    MODIFY = auto()    # 정정
    CANCEL = auto()    # 취소


class PriceType(Enum):
    LIMIT = "00"       # 지정가
    MARKET = "03"      # 시장가


class OrderStatus(Enum):
    CREATED = auto()     # 생성됨
    SUBMITTED = auto()   # 서버로 전송됨
    ACCEPTED = auto()    # 접수됨
    PARTIAL = auto()     # 부분체결
    FILLED = auto()      # 완전체결
    CANCELLED = auto()   # 취소됨
    REJECTED = auto()    # 거부됨
    FAILED = auto()      # 전송 실패


@dataclass
class Order:
    code: str                          # 종목코드
    side: OrderSide
    order_type: OrderType = OrderType.NEW
    price_type: PriceType = PriceType.LIMIT
    qty: int = 0                       # 주문수량
    price: int = 0                     # 주문가격 (시장가면 0)
    status: OrderStatus = OrderStatus.CREATED
    order_no: str = ""                 # 증권사 주문번호
    filled_qty: int = 0               # 체결수량
    filled_price: float = 0.0         # 체결단가
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: Optional[datetime] = None
    reject_reason: str = ""


@dataclass
class BalanceItem:
    code: str
    name: str = ""
    qty: int = 0                # 보유수량
    avg_price: float = 0.0      # 평균매입가
    current_price: float = 0.0  # 현재가
    eval_amount: float = 0.0    # 평가금액
    pnl: float = 0.0            # 손익금액
    pnl_pct: float = 0.0        # 손익률


@dataclass
class AccountInfo:
    account_no: str = ""
    total_eval: float = 0.0       # 총평가금액
    total_purchase: float = 0.0   # 총매입금액
    total_pnl: float = 0.0       # 총손익
    deposit: float = 0.0          # 예수금
    holdings: dict = field(default_factory=dict)  # code -> BalanceItem
