# -*- coding: utf-8 -*-
"""
main.py — Composition Root
===========================
전천후 적응형 시스템: 레짐 판단 → 전략 라우팅 → 백테스트/실매매.
"""
from __future__ import annotations
import sys
import os
import logging
from datetime import datetime, timedelta
from pathlib import Path

LOG_DIR = Path("data/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "app.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("main")

from core.event_bus import EventBus
from core.engine import BacktestEngine
from core.risk import RiskManager
from core.order_manager import OrderManager
from core.types import Regime
from config.default_params import DEFAULT_PARAMS, MYSQL_PARAMS, CYBOS_URL, KIWOOM_URL

from plugins.data_source import CompositeDataSource
from plugins.indicators import SuperTrendIndicator, JMAIndicator, RSIIndicator
from plugins.signals import (
    STJMASignalGenerator,
    BearInverseSignalGenerator,
    SidewaysSwingSignalGenerator,
)
from plugins.regime import STRegimeDetector
from plugins.screener import BetaCorrelationScreener
from plugins.strategy_router import StrategyRouter


def main():
    logger.info("=== KOSPI Big10 IBS Trading System ===")
    logger.info(f"App launched at {datetime.now():%H:%M:%S}")

    bus = EventBus()

    data_source = CompositeDataSource(
        mysql_params=MYSQL_PARAMS,
        cybos_url=CYBOS_URL,
        kiwoom_url=KIWOOM_URL,
    )

    indicators = [SuperTrendIndicator(), JMAIndicator(), RSIIndicator()]

    # ── 레짐별 신호 생성기 ──
    bull_gen = STJMASignalGenerator()
    bear_gen = BearInverseSignalGenerator()
    sideways_gen = SidewaysSwingSignalGenerator()

    # ── 전략 라우터 조립 ──
    router = StrategyRouter(default_gen=bull_gen)
    router.register(Regime.BULL, bull_gen, {
        "target_profit_pct": 0.15,
        "stop_loss_pct": -0.05,
        "screen_min_beta": 0.8,
    })
    router.register(Regime.BEAR, bear_gen, {
        "target_profit_pct": 0.05,
        "stop_loss_pct": -0.03,
        "min_hold_days": 1,
    })
    router.register(Regime.SIDEWAYS, sideways_gen, {
        "target_profit_pct": 0.05,
        "stop_loss_pct": -0.04,
        "jma_length": 5,
        "min_hold_days": 1,
    })

    # ── 레짐 판단 (매크로 통합) ──
    regime_detector = STRegimeDetector(data_source=data_source)

    # ── 리스크 관리 ──
    risk_mgr = RiskManager(
        max_daily_loss_pct=DEFAULT_PARAMS["max_daily_loss_pct"],
        max_weekly_loss_pct=-10.0,
        max_monthly_loss_pct=DEFAULT_PARAMS["max_monthly_loss_pct"],
        max_consecutive_losses=DEFAULT_PARAMS["max_consecutive_losses"],
        max_positions=DEFAULT_PARAMS["max_positions"],
        max_per_stock_pct=DEFAULT_PARAMS["max_per_stock_pct"],
        backtest_mode=True,
    )

    # ── 백테스트 엔진 (전략 라우터 포함) ──
    bt_engine = BacktestEngine(
        data_source=data_source,
        indicators=indicators,
        signal_gen=bull_gen,              # 기본 (router 없을 때 폴백)
        regime_detector=regime_detector,
        risk_gate=risk_mgr,
        event_bus=bus,
        params=DEFAULT_PARAMS,
        strategy_router=router,           # 레짐별 자동 라우팅
    )

    # ── 주문 관리 ──
    order_mgr = OrderManager(event_bus=bus)
    order_mgr.set_risk_gate(risk_mgr)

    # ── 실행 모드 ──
    mode = os.environ.get("RUN_MODE", "ui")

    if mode == "ui":
        try:
            from PyQt6.QtWidgets import QApplication
            from PyQt6.QtGui import QFont
            from ui.main_window import MainWindow

            app = QApplication.instance() or QApplication(sys.argv)
            font = QFont("Malgun Gothic", 9)
            app.setFont(font)

            import matplotlib
            matplotlib.rcParams["font.family"] = "Malgun Gothic"
            matplotlib.rcParams["axes.unicode_minus"] = False

            window = MainWindow()
            window.show()
            sys.exit(app.exec())
        except ImportError as e:
            logger.error(f"PyQt6 required for UI mode: {e}")
    else:
        _run_cli_pipeline(data_source, bt_engine, DEFAULT_PARAMS)


def _run_cli_pipeline(data_source, bt_engine, params):
    months = params.get("screen_months", 6)
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=months * 30)).strftime("%Y-%m-%d")

    logger.info(f"=== 스크리닝 시작: {start_date} ~ {end_date} ===")

    index_df = data_source.fetch_index_candles("KOSPI", start_date, end_date)
    if index_df is None or index_df.empty:
        logger.error("KOSPI 지수 데이터 없음 — 중단")
        return

    logger.info(f"KOSPI 지수: {len(index_df)}행")

    screener = BetaCorrelationScreener()
    candidates = screener.screen(
        universe=[], index_df=index_df,
        data_source=data_source, params=params,
    )

    if not candidates:
        logger.warning("스크리닝 결과 0개 — 중단")
        return

    logger.info(f"=== 스크리닝 완료: {len(candidates)}개 종목 ===")
    for i, c in enumerate(candidates):
        logger.info(
            f"  [{i+1}] {c.code} {c.name} | beta={c.beta:.3f} corr={c.correlation:.3f}"
        )

    logger.info(f"=== 백테스트 시작: {len(candidates)}개 종목 ===")
    results = []
    for c in candidates:
        result = bt_engine.run(c.code, start_date, end_date, params["initial_capital"])
        if result:
            results.append(result)
            logger.info(
                f"  [{c.code}] {c.name:10s} | regime={result.regime_used.name if result.regime_used else '?'} | "
                f"Return: {result.total_return_pct:+7.2f}% | "
                f"Trades: {result.trade_count} | Win: {result.win_rate:5.1f}% | "
                f"Sharpe: {result.sharpe_ratio:7.4f} | MDD: {result.max_drawdown_pct:7.2f}%"
            )
        else:
            logger.warning(f"  [{c.code}] {c.name} — 백테스트 실패")

    if results:
        avg_ret = sum(r.total_return_pct for r in results) / len(results)
        avg_sharpe = sum(r.sharpe_ratio for r in results) / len(results)
        avg_win = sum(r.win_rate for r in results) / len(results)
        total_trades = sum(r.trade_count for r in results)
        profit_count = sum(1 for r in results if r.total_return_pct > 0)

        logger.info("=" * 70)
        logger.info(f"  종목 수: {len(results)} | 수익: {profit_count}")
        logger.info(f"  평균 수익률: {avg_ret:+.2f}%")
        logger.info(f"  평균 샤프: {avg_sharpe:.4f}")
        logger.info(f"  평균 승률: {avg_win:.1f}%")
        logger.info(f"  총 거래: {total_trades}회")
        best = max(results, key=lambda r: r.total_return_pct)
        worst = min(results, key=lambda r: r.total_return_pct)
        logger.info(f"  최고: {best.code} {best.total_return_pct:+.2f}%")
        logger.info(f"  최저: {worst.code} {worst.total_return_pct:+.2f}%")
        logger.info("=" * 70)

    logger.info("=== Complete ===")
if __name__ == "__main__":
    import sys
    import traceback

    def exception_hook(exc_type, exc_value, exc_tb):
        traceback.print_exception(exc_type, exc_value, exc_tb)
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = exception_hook

    main()
