# -*- coding: utf-8 -*-
"""
ui/main_window.py  [MUTABLE]
============================
메인 윈도우 — 이전 strategy.py UI를 새 구조에 연결.
PyQt6 기반, core/engine + plugins 조립.
"""
from __future__ import annotations
import sys
import os
import logging
import traceback
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

from PyQt6.QtCore import Qt, QDate
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTableWidget, QTableWidgetItem, QHeaderView,
    QTabWidget, QGroupBox, QFormLayout, QDoubleSpinBox, QSpinBox,
    QDateEdit, QProgressBar, QTextEdit, QSplitter,
    QAbstractItemView, QMessageBox,
)
from PyQt6.QtGui import QColor, QFont
import matplotlib
matplotlib.use("QtAgg")
import matplotlib.ticker as mticker

from core.engine import BacktestEngine
from core.event_bus import EventBus
from core.risk import RiskManager
from config.default_params import DEFAULT_PARAMS, MYSQL_PARAMS, CYBOS_URL, KIWOOM_URL
from plugins.data_source import CompositeDataSource
from plugins.indicators import SuperTrendIndicator, JMAIndicator, RSIIndicator
from plugins.signals import STJMASignalGenerator
from plugins.regime import STRegimeDetector
from plugins.screener import BetaCorrelationScreener

from ui.chart_widget import StockChartWidget
from ui.workers import ScreeningWorker, AnalysisWorker, BatchAnalysisWorker

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("KOSPI SuperTrend + JMA 전략")
        self.setMinimumSize(1400, 900)

        self.params = dict(DEFAULT_PARAMS)
        self.screened_stocks = []
        self.analysis_results = []
        self.current_result = None
        self._workers = []

        # ── 엔진 조립 ──
        self._data_source = CompositeDataSource(
            mysql_params=MYSQL_PARAMS,
            cybos_url=CYBOS_URL,
            kiwoom_url=KIWOOM_URL,
        )
        self._indicators = [SuperTrendIndicator(), JMAIndicator(), RSIIndicator()]
        self._signal_gen = STJMASignalGenerator()
        self._regime = STRegimeDetector()
        self._risk = RiskManager(
            max_daily_loss_pct=self.params["max_daily_loss_pct"],
            max_monthly_loss_pct=self.params["max_monthly_loss_pct"],
            max_consecutive_losses=self.params["max_consecutive_losses"],
            max_positions=self.params["max_positions"],
            max_per_stock_pct=self.params["max_per_stock_pct"],
        )
        self._bus = EventBus()
        self._engine = BacktestEngine(
            data_source=self._data_source,
            indicators=self._indicators,
            signal_gen=self._signal_gen,
            regime_detector=self._regime,
            risk_gate=self._risk,
            event_bus=self._bus,
            params=self.params,
        )

        self._build_ui()
        logger.info("[UI] MainWindow 초기화 완료")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  UI 구성
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)

        # ── 좌측 패널 ──
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_panel.setMaximumWidth(360)

        # 스크리닝 그룹
        scan_group = QGroupBox("스크리닝")
        scan_layout = QFormLayout(scan_group)

        self.date_start = QDateEdit()
        self.date_start.setCalendarPopup(True)
        self.date_start.setDate(QDate.currentDate().addMonths(-6))
        scan_layout.addRow("시작일:", self.date_start)

        self.date_end = QDateEdit()
        self.date_end.setCalendarPopup(True)
        self.date_end.setDate(QDate.currentDate())
        scan_layout.addRow("종료일:", self.date_end)

        self.spin_pool = QSpinBox()
        self.spin_pool.setRange(10, 200)
        self.spin_pool.setValue(50)
        scan_layout.addRow("후보 수:", self.spin_pool)

        self.spin_top_n = QSpinBox()
        self.spin_top_n.setRange(3, 50)
        self.spin_top_n.setValue(10)
        scan_layout.addRow("선정 수:", self.spin_top_n)

        self.btn_screen = QPushButton("스크리닝 실행")
        self.btn_screen.clicked.connect(self._on_screen)
        scan_layout.addRow(self.btn_screen)

        left_layout.addWidget(scan_group)

        # 종목 테이블
        self.stock_table = QTableWidget()
        self.stock_table.setColumnCount(5)
        self.stock_table.setHorizontalHeaderLabels(["순위", "코드", "이름", "베타", "상관"])
        self.stock_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.stock_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.stock_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        left_layout.addWidget(self.stock_table)

        # 파라미터 그룹
        param_group = QGroupBox("전략 파라미터")
        param_layout = QFormLayout(param_group)

        self.spin_jma_period = QSpinBox()
        self.spin_jma_period.setRange(3, 50)
        self.spin_jma_period.setValue(self.params.get("jma_length", 7))
        param_layout.addRow("JMA 기간:", self.spin_jma_period)

        self.spin_jma_phase = QSpinBox()
        self.spin_jma_phase.setRange(-100, 100)
        self.spin_jma_phase.setValue(self.params.get("jma_phase", 50))
        param_layout.addRow("JMA 위상:", self.spin_jma_phase)

        self.spin_st_period = QSpinBox()
        self.spin_st_period.setRange(5, 50)
        self.spin_st_period.setValue(self.params.get("st_period", 14))
        param_layout.addRow("ST 기간:", self.spin_st_period)

        self.spin_st_mult = QDoubleSpinBox()
        self.spin_st_mult.setRange(0.5, 5.0)
        self.spin_st_mult.setSingleStep(0.1)
        self.spin_st_mult.setValue(self.params.get("st_multiplier", 2.0))
        param_layout.addRow("ST 배수:", self.spin_st_mult)

        self.spin_target = QDoubleSpinBox()
        self.spin_target.setRange(0.01, 0.50)
        self.spin_target.setSingleStep(0.01)
        self.spin_target.setValue(self.params.get("target_profit_pct", 0.07))
        param_layout.addRow("목표수익:", self.spin_target)

        self.spin_stoploss = QDoubleSpinBox()
        self.spin_stoploss.setRange(-0.30, -0.01)
        self.spin_stoploss.setSingleStep(0.01)
        self.spin_stoploss.setValue(self.params.get("stop_loss_pct", -0.05))
        param_layout.addRow("손절률:", self.spin_stoploss)

        self.spin_slope_min = QDoubleSpinBox()
        self.spin_slope_min.setRange(0.0, 10000.0)
        self.spin_slope_min.setSingleStep(100.0)
        self.spin_slope_min.setValue(self.params.get("jma_slope_min", 0.0))
        param_layout.addRow("JMA 기울기:", self.spin_slope_min)

        left_layout.addWidget(param_group)

        # 분석 버튼
        self.btn_analyze = QPushButton("선택종목 분석")
        self.btn_analyze.clicked.connect(self._on_analyze)
        left_layout.addWidget(self.btn_analyze)

        self.btn_batch = QPushButton("일괄 분석")
        self.btn_batch.clicked.connect(self._on_batch)
        left_layout.addWidget(self.btn_batch)

        # 진행 상태
        self.progress_label = QLabel("대기 중")
        left_layout.addWidget(self.progress_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.hide()
        left_layout.addWidget(self.progress_bar)

        # ── 우측 패널 ──
        right_panel = QTabWidget()

        # 차트 탭
        self.chart_widget = StockChartWidget()
        right_panel.addTab(self.chart_widget, "차트")

        # 거래 내역 탭
        self.trades_table = QTableWidget()
        self.trades_table.setColumnCount(8)
        self.trades_table.setHorizontalHeaderLabels([
            "매수일", "매수가", "매도일", "매도가", "수량", "수익", "수익률%", "매도사유"
        ])
        self.trades_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.trades_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        right_panel.addTab(self.trades_table, "거래 내역")

        # 포트폴리오 탭
        self.portfolio_text = QTextEdit()
        self.portfolio_text.setReadOnly(True)
        self.portfolio_text.setFont(QFont("Consolas", 10))
        right_panel.addTab(self.portfolio_text, "포트폴리오")

        # 자본곡선 탭
        self.equity_widget = QWidget()
        equity_layout = QVBoxLayout(self.equity_widget)
        from matplotlib.backends.backend_qtagg import FigureCanvas
        from matplotlib.figure import Figure
        self.equity_fig = Figure(figsize=(10, 4), dpi=80)
        self.equity_canvas = FigureCanvas(self.equity_fig)
        equity_layout.addWidget(self.equity_canvas)
        right_panel.addTab(self.equity_widget, "자본곡선")

        # 일괄 결과 탭
        self.batch_table = QTableWidget()
        self.batch_table.setColumnCount(8)
        self.batch_table.setHorizontalHeaderLabels([
            "코드", "이름", "수익률%", "거래수", "승률%", "최대낙폭%", "샤프", "보유일"
        ])
        self.batch_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.batch_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        right_panel.addTab(self.batch_table, "일괄 결과")

        # 로그 탭
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        right_panel.addTab(self.log_text, "로그")

        # 스플리터
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([350, 1050])
        main_layout.addWidget(splitter)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  파라미터 동기화
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    def _sync_params(self) -> dict:
        p = dict(DEFAULT_PARAMS)
        p["jma_length"] = self.spin_jma_period.value()
        p["jma_period"] = self.spin_jma_period.value()
        p["jma_phase"] = self.spin_jma_phase.value()
        p["st_period"] = self.spin_st_period.value()
        p["st_multiplier"] = self.spin_st_mult.value()
        p["st_mult"] = self.spin_st_mult.value()
        p["target_profit_pct"] = self.spin_target.value()
        p["stop_loss_pct"] = self.spin_stoploss.value()
        p["jma_slope_min"] = self.spin_slope_min.value()
        p["candidate_pool"] = self.spin_pool.value()
        p["screen_top_n"] = self.spin_top_n.value()
        self.params = p
        self._engine.params = p
        return p

    def _get_dates(self):
        return (self.date_start.date().toString("yyyy-MM-dd"),
                self.date_end.date().toString("yyyy-MM-dd"))

    def _append_log(self, msg: str):
        try:
            self.log_text.append(f"[{datetime.now():%H:%M:%S}] {msg}")
        except Exception:
            pass

    def _show_busy(self, busy: bool):
        if busy:
            self.progress_bar.show()
            self.btn_screen.setEnabled(False)
            self.btn_analyze.setEnabled(False)
            self.btn_batch.setEnabled(False)
        else:
            self.progress_bar.hide()
            self.btn_screen.setEnabled(True)
            self.btn_analyze.setEnabled(True)
            self.btn_batch.setEnabled(True)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  스크리닝
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    def _on_screen(self):
        self._show_busy(True)
        self.progress_label.setText("스크리닝 중...")
        self._append_log("스크리닝 시작")
        params = self._sync_params()

        worker = ScreeningWorker(
            data_source=self._data_source,
            params=params,
        )
        worker.finished.connect(self._on_screen_done)
        worker.error.connect(self._on_screen_error)
        worker.progress.connect(self._on_screen_progress)
        self._workers.append(worker)
        worker.start()

    def _on_screen_progress(self, msg):
        self.progress_label.setText(msg)
        self._append_log(msg)

    def _on_screen_done(self, results):
        self._show_busy(False)
        self.screened_stocks = results
        self.stock_table.setRowCount(len(results))
        for i, r in enumerate(results):
            self.stock_table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            self.stock_table.setItem(i, 1, QTableWidgetItem(r.get("code", "")))
            self.stock_table.setItem(i, 2, QTableWidgetItem(r.get("name", "")))
            self.stock_table.setItem(i, 3, QTableWidgetItem(f"{r.get('beta', 0):.3f}"))
            self.stock_table.setItem(i, 4, QTableWidgetItem(f"{r.get('correlation', 0):.3f}"))
        msg = f"스크리닝 완료: {len(results)}개 종목"
        self.progress_label.setText(msg)
        self._append_log(msg)

    def _on_screen_error(self, err):
        self._show_busy(False)
        self.progress_label.setText("스크리닝 오류")
        self._append_log(f"오류: {err}")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  단일 분석
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    def _on_analyze(self):
        rows = self.stock_table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.warning(self, "알림", "종목을 선택하세요.")
            return

        idx = rows[0].row()
        if idx >= len(self.screened_stocks):
            return

        stock = self.screened_stocks[idx]
        code = stock.get("code", "")
        name = stock.get("name", "")
        start_date, end_date = self._get_dates()
        params = self._sync_params()

        self._show_busy(True)
        self.progress_label.setText(f"분석 중: {name}")

        worker = AnalysisWorker(
            engine=self._engine,
            code=code, name=name,
            start_date=start_date, end_date=end_date,
            data_source=self._data_source,
            params=params,
        )
        worker.finished.connect(self._on_analysis_done)
        worker.error.connect(self._on_analysis_error)
        worker.progress.connect(lambda m: self.progress_label.setText(m))
        self._workers.append(worker)
        worker.start()

    def _on_analysis_done(self, result):
        self._show_busy(False)
        self.current_result = result
        name = result.get("name", "")
        code = result.get("code", "")
        bt = result.get("backtest_result")

        if bt is None:
            self.progress_label.setText(f"{name} 분석 실패")
            return

        self.progress_label.setText(
            f"{name} 완료 — 수익률 {bt.total_return_pct:.2f}%"
        )

        # 차트
        df = result.get("df")
        if df is not None:
            self.chart_widget.plot(
                df, self._sync_params(),
                title=f"{name} ({code}) — SuperTrend + JMA",
                trades=bt.trades,
                kospi_df=result.get("kospi_df"),
            )

        # 거래 내역
        trades = bt.trades
        self.trades_table.setRowCount(len(trades))
        for i, t in enumerate(trades):
            entry_d = str(pd.Timestamp(t.entry_date))[:10] if t.entry_date is not None else ""
            exit_d = str(pd.Timestamp(t.exit_date))[:10] if t.exit_date is not None else ""
            self.trades_table.setItem(i, 0, QTableWidgetItem(entry_d))
            self.trades_table.setItem(i, 1, QTableWidgetItem(f"{t.entry_price:,.0f}"))
            self.trades_table.setItem(i, 2, QTableWidgetItem(exit_d))
            self.trades_table.setItem(i, 3, QTableWidgetItem(f"{t.exit_price:,.0f}" if t.exit_price else ""))
            self.trades_table.setItem(i, 4, QTableWidgetItem(str(t.shares)))
            self.trades_table.setItem(i, 5, QTableWidgetItem(f"{t.pnl:,.0f}"))
            ret_item = QTableWidgetItem(f"{t.pnl_pct:.2f}%")
            ret_item.setForeground(QColor("red") if t.pnl_pct > 0 else QColor("blue"))
            self.trades_table.setItem(i, 6, ret_item)
            self.trades_table.setItem(i, 7, QTableWidgetItem(t.exit_reason))

        # 포트폴리오 요약
        txt = f"""
{'=' * 60}
  종목: {name} ({code})
{'=' * 60}
  초기 자본:           {bt.initial_capital:>15,.0f} 원
  최종 자본:           {bt.final_capital:>15,.0f} 원
  총 수익률:           {bt.total_return_pct:>14.2f}%
  총 거래 횟수:        {bt.trade_count:>10}
  승리:                {bt.win_count:>10}
  패배:                {bt.lose_count:>10}
  승률:                {bt.win_rate:>13.2f}%
  평균 손익(%):        {bt.avg_pnl_pct:>13.2f}%
  최대 낙폭:           {bt.max_drawdown_pct:>13.2f}%
  샤프 비율:           {bt.sharpe_ratio:>13.4f}
  평균 보유일:         {bt.avg_holding_days:>13.1f} 일
{'=' * 60}
"""
        self.portfolio_text.setPlainText(txt)

        # 자본곡선
        self._plot_equity(bt.equity_curve)

    def _on_analysis_error(self, err):
        self._show_busy(False)
        self.progress_label.setText("분석 오류")
        self._append_log(f"분석 오류: {err}")

    def _plot_equity(self, equity):
        self.equity_fig.clear()
        if equity is None or len(equity) == 0:
            self.equity_canvas.draw_idle()
            return
        ax = self.equity_fig.add_subplot(111)
        eq_vals = equity.values if hasattr(equity, "values") else list(equity)
        ax.plot(eq_vals, color="#2266AA", linewidth=1.2)
        ax.fill_between(range(len(eq_vals)), eq_vals, eq_vals[0], alpha=0.1, color="#2266AA")
        ax.axhline(y=eq_vals[0], color="gray", linestyle="--", alpha=0.5)
        ax.set_title("자본 곡선", fontsize=10)
        ax.set_ylabel("자본 (원)")
        ax.grid(True, alpha=0.3)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, p: f"{v:,.0f}"))
        try:
            self.equity_fig.tight_layout()
        except Exception:
            pass
        self.equity_canvas.draw_idle()

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  일괄 분석
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    def _on_batch(self):
        if not self.screened_stocks:
            QMessageBox.warning(self, "알림", "먼저 스크리닝을 실행하세요.")
            return

        self._show_busy(True)
        self.progress_label.setText("일괄 분석 중...")
        self.batch_table.setRowCount(0)
        self.analysis_results = []

        start_date, end_date = self._get_dates()
        params = self._sync_params()

        worker = BatchAnalysisWorker(
            engine=self._engine,
            stocks=self.screened_stocks,
            start_date=start_date,
            end_date=end_date,
            data_source=self._data_source,
            params=params,
        )
        worker.finished.connect(self._on_batch_done)
        worker.error.connect(self._on_batch_error)
        worker.progress.connect(lambda m: self.progress_label.setText(m))
        worker.single_done.connect(self._on_batch_single)
        self._workers.append(worker)
        worker.start()

    def _on_batch_single(self, result):
        self.analysis_results.append(result)
        bt = result.get("backtest_result")
        if bt is None:
            return
        row = self.batch_table.rowCount()
        self.batch_table.insertRow(row)

        self.batch_table.setItem(row, 0, QTableWidgetItem(result.get("code", "")))
        self.batch_table.setItem(row, 1, QTableWidgetItem(result.get("name", "")))

        ret_item = QTableWidgetItem(f"{bt.total_return_pct:.2f}")
        ret_item.setForeground(QColor("red") if bt.total_return_pct > 0 else QColor("blue"))
        self.batch_table.setItem(row, 2, ret_item)

        self.batch_table.setItem(row, 3, QTableWidgetItem(str(bt.trade_count)))
        self.batch_table.setItem(row, 4, QTableWidgetItem(f"{bt.win_rate:.1f}"))
        self.batch_table.setItem(row, 5, QTableWidgetItem(f"{bt.max_drawdown_pct:.2f}"))
        self.batch_table.setItem(row, 6, QTableWidgetItem(f"{bt.sharpe_ratio:.3f}"))
        self.batch_table.setItem(row, 7, QTableWidgetItem(f"{bt.avg_holding_days:.1f}"))

    def _on_batch_done(self, results):
        self._show_busy(False)
        total = len(results)
        if total > 0:
            avg_ret = np.mean([r["backtest_result"].total_return_pct for r in results if r.get("backtest_result")])
            msg = f"일괄 분석 완료: {total}개 종목, 평균 수익률 {avg_ret:.2f}%"
        else:
            msg = "일괄 분석 완료: 결과 없음"
        self.progress_label.setText(msg)
        self._append_log(msg)

    def _on_batch_error(self, err):
        self._show_busy(False)
        self.progress_label.setText("일괄 분석 오류")
        self._append_log(f"오류: {err}")
