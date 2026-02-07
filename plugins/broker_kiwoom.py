# -*- coding: utf-8 -*-
"""
plugins/broker_kiwoom.py  [MUTABLE]
====================================
키움증권 OpenAPI 브로커 어댑터.
실제 키움 OCX 또는 kiwoomserver 래퍼를 통해 주문 실행.
다른 증권사로 교체하려면 이 파일을 복사해 수정.
"""
from __future__ import annotations
from typing import Dict, List, Any, Optional, Callable
import logging
from core.interfaces import IBroker

logger = logging.getLogger(__name__)


class KiwoomBroker(IBroker):
    """
    키움증권 브로커.
    kiwoomserver 또는 OpenAPI OCX 객체를 _ocx로 주입받는다.
    """

    def __init__(self, ocx: Any = None) -> None:
        self._ocx = ocx
        self._on_order_accepted: Optional[Callable] = None
        self._on_order_filled: Optional[Callable] = None
        self._on_order_cancelled: Optional[Callable] = None

    def set_ocx(self, ocx: Any) -> None:
        self._ocx = ocx

    def set_callbacks(
        self,
        on_accepted: Optional[Callable] = None,
        on_filled: Optional[Callable] = None,
        on_cancelled: Optional[Callable] = None,
    ) -> None:
        self._on_order_accepted = on_accepted
        self._on_order_filled = on_filled
        self._on_order_cancelled = on_cancelled

    # ── IBroker 구현 ──
    def send_order(self, account: str, code: str, qty: int,
                   price: int, side: str, order_type: str) -> str:
        """
        키움 SendOrder 호출.
        side: "1"=매수, "2"=매도
        order_type: "00"=지정가, "03"=시장가
        """
        if not self._ocx:
            logger.error("OCX not set")
            return ""

        try:
            # 키움 API: SendOrder(sRQName, sScreenNo, sAccNo, nOrderType, sCode, nQty, nPrice, sHogaGb, sOrgOrderNo)
            order_type_int = 1 if side == "1" else 2
            ret = self._ocx.dynamicCall(
                "SendOrder(QString, QString, QString, int, QString, int, int, QString, QString)",
                ["ORDER_REQ", "0101", account, order_type_int, code, qty, price, order_type, ""]
            )
            if ret == 0:
                logger.info(f"SendOrder success: {code} {side} {qty}@{price}")
                return f"PENDING_{code}_{side}"  # 실제 주문번호는 이벤트로 수신
            else:
                logger.error(f"SendOrder failed: ret={ret}")
                return ""
        except Exception as e:
            logger.error(f"send_order error: {e}")
            return ""

    def cancel_order(self, order_no: str, code: str, qty: int) -> bool:
        if not self._ocx:
            return False
        try:
            ret = self._ocx.dynamicCall(
                "SendOrder(QString, QString, QString, int, QString, int, int, QString, QString)",
                ["CANCEL_REQ", "0102", "", 3, code, qty, 0, "00", order_no]
            )
            return ret == 0
        except Exception as e:
            logger.error(f"cancel_order error: {e}")
            return False

    def get_balance(self, account: str) -> Dict[str, Any]:
        """잔고 조회 — TR opw00018 등으로 구현."""
        # TODO: 실제 TR 요청 구현
        return {}

    def get_unfilled_orders(self, account: str) -> List[Dict[str, Any]]:
        """미체결 조회."""
        # TODO: 실제 TR 요청 구현
        return []

    # ── 키움 이벤트 핸들러 (OnReceiveChejanData에서 호출) ──
    def on_chejan_data(self, gubun: str, item_cnt: int, fid_list: str) -> None:
        """
        체결/잔고 이벤트 처리.
        gubun: "0"=주문체결, "1"=잔고변경, "3"=특이신호
        """
        if not self._ocx:
            return

        try:
            if gubun == "0":  # 주문체결
                order_no = self._get_chejan("9203")   # 주문번호
                status = self._get_chejan("913")       # 주문상태
                filled_qty = abs(int(self._get_chejan("911") or "0"))
                filled_price = abs(int(self._get_chejan("910") or "0"))

                if "체결" in status and filled_qty > 0:
                    if self._on_order_filled:
                        self._on_order_filled(order_no, filled_qty, float(filled_price))
                elif "접수" in status:
                    if self._on_order_accepted:
                        self._on_order_accepted(order_no)
                elif "취소" in status:
                    if self._on_order_cancelled:
                        self._on_order_cancelled(order_no)

            elif gubun == "1":  # 잔고변경
                pass  # sync_balance에서 처리

        except Exception as e:
            logger.error(f"on_chejan_data error: {e}")

    def _get_chejan(self, fid: str) -> str:
        try:
            return self._ocx.dynamicCall("GetChejanData(int)", int(fid)).strip()
        except Exception:
            return ""
