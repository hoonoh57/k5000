# -*- coding: utf-8 -*-
"""대신증권 Cybos Plus 주문 연동."""
from __future__ import annotations

import logging
import requests
from core import config

logger = logging.getLogger(__name__)


class CybosBroker:
    """Cybos REST API를 통한 주문 실행."""

    def __init__(self):
        port = config.get("broker.cybos.port", 8081)
        self.base_url = f"http://localhost:{port}/api"

    def send_order(self, code: str, direction: str,
                   qty: int, price: float) -> dict:
        """
        주문 전송.
        Returns: {"success": bool, "message": str, "order_no": str}
        """
        endpoint = f"{self.base_url}/order"
        payload = {
            "code": code,
            "type": "buy" if direction == "BUY" else "sell",
            "qty": qty,
            "price": int(price),
            "order_type": "limit",   # 지정가
        }

        try:
            logger.info(
                f"[BROKER] 주문 전송: {direction} {code} "
                f"{qty}주 @ {price:,.0f}"
            )
            resp = requests.post(endpoint, json=payload, timeout=10)

            if resp.status_code == 200:
                data = resp.json()
                logger.info(f"[BROKER] 주문 응답: {data}")
                return {
                    "success": data.get("success", False),
                    "message": data.get("message", ""),
                    "order_no": data.get("order_no", ""),
                }
            else:
                msg = f"HTTP {resp.status_code}"
                logger.error(f"[BROKER] 주문 실패: {msg}")
                return {"success": False, "message": msg}

        except Exception as e:
            logger.error(f"[BROKER] 주문 에러: {e}")
            return {"success": False, "message": str(e)}

    def get_balance(self) -> dict:
        """계좌 잔고 조회."""
        try:
            resp = requests.get(
                f"{self.base_url}/balance", timeout=10
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.error(f"[BROKER] 잔고 조회 에러: {e}")
        return {}

    def get_positions(self) -> list:
        """보유 종목 조회."""
        try:
            resp = requests.get(
                f"{self.base_url}/positions", timeout=10
            )
            if resp.status_code == 200:
                return resp.json().get("positions", [])
        except Exception as e:
            logger.error(f"[BROKER] 보유종목 조회 에러: {e}")
        return []
