# -*- coding: utf-8 -*-
"""
plugins/broker_kiwoom.py
========================
키움증권 브로커 어댑터.
모드 1: OCX 직접 (32비트 동일 프로세스)
모드 2: HTTP 브릿지 (64비트 → localhost:8082 → 32비트 OCX)
"""
from __future__ import annotations
from typing import Dict, List, Any, Optional, Callable
import logging
import requests
from core.interfaces import IBroker

logger = logging.getLogger(__name__)


class KiwoomBroker(IBroker):

    def __init__(self, ocx: Any = None,
                 bridge_url: str = "http://localhost:8082") -> None:
        self._ocx = ocx
        self._bridge_url = bridge_url.rstrip("/")
        self._mode = "ocx" if ocx else "http"
        self._timeout = 10
        self._on_order_accepted: Optional[Callable] = None
        self._on_order_filled: Optional[Callable] = None
        self._on_order_cancelled: Optional[Callable] = None

    def set_ocx(self, ocx: Any) -> None:
        self._ocx = ocx
        self._mode = "ocx"

    def set_callbacks(
        self,
        on_accepted: Optional[Callable] = None,
        on_filled: Optional[Callable] = None,
        on_cancelled: Optional[Callable] = None,
    ) -> None:
        self._on_order_accepted = on_accepted
        self._on_order_filled = on_filled
        self._on_order_cancelled = on_cancelled

    # ── IBroker ──
    def send_order(self, account: str, code: str, qty: int,
                   price: int, side: str, order_type: str) -> str:
        if self._mode == "http":
            return self._http_send(account, code, qty, price, side, order_type)
        return self._ocx_send(account, code, qty, price, side, order_type)

    def cancel_order(self, order_no: str, code: str, qty: int) -> bool:
        if self._mode == "http":
            return self._http_cancel(order_no, code, qty)
        return self._ocx_cancel(order_no, code, qty)

    def get_balance(self, account: str) -> Dict[str, Any]:
        if self._mode == "http":
            return self._http_balance(account)
        return {}

    def get_unfilled_orders(self, account: str) -> List[Dict[str, Any]]:
        if self._mode == "http":
            return self._http_unfilled(account)
        return []

    # ── HTTP ──
    def _http_send(self, account, code, qty, price, side, order_type) -> str:
        try:
            r = requests.post(f"{self._bridge_url}/api/order", json={
                "account": account, "code": code, "qty": qty,
                "price": price, "side": side, "order_type": order_type,
            }, timeout=self._timeout)
            r.raise_for_status()
            body = r.json()
            if body.get("success"):
                ono = body.get("order_no", "")
                logger.info(f"[KIWOOM] HTTP order: {code} {side} {qty}@{price} → {ono}")
                return ono
            logger.error(f"[KIWOOM] HTTP order fail: {body.get('message', '')}")
            return ""
        except Exception as e:
            logger.error(f"[KIWOOM] HTTP send error: {e}")
            return ""

    def _http_cancel(self, order_no, code, qty) -> bool:
        try:
            r = requests.post(f"{self._bridge_url}/api/cancel", json={
                "order_no": order_no, "code": code, "qty": qty,
            }, timeout=self._timeout)
            return r.json().get("success", False)
        except Exception as e:
            logger.error(f"[KIWOOM] HTTP cancel error: {e}")
            return False

    def _http_balance(self, account) -> Dict[str, Any]:
        try:
            r = requests.get(f"{self._bridge_url}/api/balance",
                             params={"account": account}, timeout=self._timeout)
            return r.json().get("data", {})
        except Exception as e:
            logger.error(f"[KIWOOM] HTTP balance error: {e}")
            return {}

    def _http_unfilled(self, account) -> List[Dict[str, Any]]:
        try:
            r = requests.get(f"{self._bridge_url}/api/unfilled",
                             params={"account": account}, timeout=self._timeout)
            return r.json().get("data", [])
        except Exception as e:
            logger.error(f"[KIWOOM] HTTP unfilled error: {e}")
            return []

    # ── OCX ──
    def _ocx_send(self, account, code, qty, price, side, order_type) -> str:
        if not self._ocx:
            return ""
        try:
            ot = 1 if side == "1" else 2
            ret = self._ocx.dynamicCall(
                "SendOrder(QString, QString, QString, int, QString, int, int, QString, QString)",
                ["ORDER_REQ", "0101", account, ot, code, qty, price, order_type, ""],
            )
            if ret == 0:
                logger.info(f"[KIWOOM] OCX order: {code} {side} {qty}@{price}")
                return f"PENDING_{code}_{side}"
            logger.error(f"[KIWOOM] OCX order failed: ret={ret}")
            return ""
        except Exception as e:
            logger.error(f"[KIWOOM] OCX send error: {e}")
            return ""

    def _ocx_cancel(self, order_no, code, qty) -> bool:
        if not self._ocx:
            return False
        try:
            ret = self._ocx.dynamicCall(
                "SendOrder(QString, QString, QString, int, QString, int, int, QString, QString)",
                ["CANCEL_REQ", "0102", "", 3, code, qty, 0, "00", order_no],
            )
            return ret == 0
        except Exception as e:
            logger.error(f"[KIWOOM] OCX cancel error: {e}")
            return False

    # ── 체결 이벤트 ──
    def on_chejan_data(self, gubun: str, item_cnt: int, fid_list: str) -> None:
        if not self._ocx:
            return
        try:
            if gubun == "0":
                order_no = self._get_chejan("9203")
                status = self._get_chejan("913")
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
        except Exception as e:
            logger.error(f"[KIWOOM] chejan error: {e}")

    def _get_chejan(self, fid: str) -> str:
        try:
            return self._ocx.dynamicCall("GetChejanData(int)", int(fid)).strip()
        except Exception:
            return ""
