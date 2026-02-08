# -*- coding: utf-8 -*-
"""
알림 모듈: PC 소리 + 팝업.
추가 설치 없이 Windows 기본 기능만 사용.
"""
from __future__ import annotations

import logging
import winsound
import threading
from datetime import datetime

logger = logging.getLogger(__name__)


class Notifier:
    """PC 소리 + 콘솔 팝업 알림."""

    def __init__(self):
        self.history: list[dict] = []

    def _beep(self, freq: int = 1000, duration: int = 500, repeat: int = 1):
        """비동기 비프음."""
        def _play():
            for _ in range(repeat):
                winsound.Beep(freq, duration)
        threading.Thread(target=_play, daemon=True).start()

    def signal_alert(self, direction: str, code: str, name: str,
                     price: float, reason: str, regime: str):
        """매매 신호 알림."""
        now = datetime.now().strftime("%H:%M:%S")

        if direction == "BUY":
            self._beep(freq=1200, duration=300, repeat=3)  # 높은 음 3회
            icon = "[매수]"
        else:
            self._beep(freq=800, duration=500, repeat=2)   # 낮은 음 2회
            icon = "[매도]"

        msg = (
            f"\n{'='*50}\n"
            f"  {icon} 신호 발생  ({now})\n"
            f"{'='*50}\n"
            f"  종목: {name} ({code})\n"
            f"  가격: {price:,.0f}원\n"
            f"  사유: {reason}\n"
            f"  레짐: {regime}\n"
            f"{'='*50}\n"
        )

        logger.info(msg)
        print(msg)

        # 기록 저장
        self.history.append({
            "time": now,
            "direction": direction,
            "code": code,
            "name": name,
            "price": price,
            "reason": reason,
        })

        # Windows 토스트 알림 (선택 - 실패해도 무시)
        try:
            from ctypes import windll
            windll.user32.MessageBeep(0x00000040)
        except Exception:
            pass

        return True

    def order_result(self, direction: str, code: str, name: str,
                     qty: int, price: float, status: str):
        """주문 결과 알림."""
        now = datetime.now().strftime("%H:%M:%S")

        if status == "체결":
            self._beep(freq=1500, duration=200, repeat=2)
        else:
            self._beep(freq=400, duration=800, repeat=3)  # 경고음

        msg = (
            f"\n{'*'*50}\n"
            f"  주문 {status}  ({now})\n"
            f"{'*'*50}\n"
            f"  종목: {name} ({code})\n"
            f"  방향: {direction}\n"
            f"  수량: {qty:,}주\n"
            f"  가격: {price:,.0f}원\n"
            f"{'*'*50}\n"
        )

        logger.info(msg)
        print(msg)
        return True