# -*- coding: utf-8 -*-
"""
ui/chart_widget.py  [MUTABLE]
=============================
6행 차트 위젯: 가격+JMA+ST | 거래량 | JMA Slope | RSI | SuperTrend | KOSPI 비교
strategy.py StockChartWidget 이식.
"""
from __future__ import annotations
import logging
import traceback
import numpy as np
import pandas as pd

from PyQt6.QtWidgets import QWidget, QVBoxLayout

import matplotlib
matplotlib.use("QtAgg")
from matplotlib.backends.backend_qtagg import FigureCanvas
from matplotlib.figure import Figure
import matplotlib.dates as mdates

logger = logging.getLogger(__name__)


class StockChartWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.fig = Figure(figsize=(14, 12), dpi=80)
        self.canvas = FigureCanvas(self.fig)
        layout.addWidget(self.canvas)

    def plot(self, df, p, title="", trades=None, kospi_df=None):
        try:
            self.fig.clear()
            if df is None or df.empty or "close" not in df.columns:
                ax = self.fig.add_subplot(111)
                ax.text(0.5, 0.5, "데이터 없음", ha="center", va="center", fontsize=16)
                self.canvas.draw_idle()
                return

            # x축
            if "date" in df.columns:
                x = pd.to_datetime(df["date"])
            elif isinstance(df.index, pd.DatetimeIndex):
                x = df.index
            else:
                x = range(len(df))

            close = df["close"].values

            gs = self.fig.add_gridspec(6, 1, height_ratios=[3, 1, 1, 1, 1.5, 1], hspace=0.08)
            ax_price = self.fig.add_subplot(gs[0])
            ax_vol = self.fig.add_subplot(gs[1], sharex=ax_price)
            ax_slope = self.fig.add_subplot(gs[2], sharex=ax_price)
            ax_rsi = self.fig.add_subplot(gs[3], sharex=ax_price)
            ax_st = self.fig.add_subplot(gs[4], sharex=ax_price)
            ax_kospi = self.fig.add_subplot(gs[5], sharex=ax_price)

            # 1) 가격 + JMA + ST
            ax_price.plot(x, close, color="#333333", linewidth=1.0, label="종가", zorder=2)
            if "jma" in df.columns:
                ax_price.plot(x, df["jma"].values, color="#FF6600", linewidth=1.5, label="JMA", zorder=3)
            if "st" in df.columns:
                st_vals = df["st"].values
                st_dir = df["st_dir"].values if "st_dir" in df.columns else np.ones(len(df))
                for i in range(1, len(x)):
                    c = "#00AA00" if st_dir[i] == 1 else "#CC0000"
                    ax_price.plot([x.iloc[i-1] if hasattr(x, 'iloc') else x[i-1],
                                   x.iloc[i] if hasattr(x, 'iloc') else x[i]],
                                  [st_vals[i-1], st_vals[i]], color=c, linewidth=1.2, zorder=2)

            # 매매 마커
            if trades:
                for t in trades:
                    try:
                        bd = pd.Timestamp(t.entry_date)
                        sd = pd.Timestamp(t.exit_date) if t.exit_date else None
                        clr = "#CCFFCC" if t.pnl_pct > 0 else "#FFCCCC"
                        if sd:
                            ax_price.axvspan(bd, sd, alpha=0.15, color=clr, zorder=1)
                    except Exception:
                        pass

            ax_price.set_title(title or "SuperTrend + JMA", fontsize=11, fontweight="bold")
            ax_price.legend(loc="upper left", fontsize=7, ncol=4)
            ax_price.grid(True, alpha=0.3)
            ax_price.set_ylabel("가격")

            # 2) 거래량
            if "volume" in df.columns:
                vol = df["volume"].values
                vc = ["#CC3333" if close[i] < close[max(i-1, 0)] else "#3333CC" for i in range(len(close))]
                ax_vol.bar(x, vol, color=vc, alpha=0.6, width=0.8)
            ax_vol.set_ylabel("거래량", fontsize=7)
            ax_vol.grid(True, alpha=0.2)

            # 3) JMA Slope
            if "jma_slope" in df.columns:
                slope = df["jma_slope"].values
                ax_slope.bar(x, np.where(slope > 0, slope, 0), color="#00CC00", alpha=0.7, width=0.8)
                ax_slope.bar(x, np.where(slope < 0, slope, 0), color="#CC0000", alpha=0.7, width=0.8)
                ax_slope.axhline(y=0, color="black", linewidth=0.5)
            ax_slope.set_ylabel("JMA Slope", fontsize=7)
            ax_slope.grid(True, alpha=0.2)

            # 4) RSI
            if "rsi" in df.columns:
                ax_rsi.plot(x, df["rsi"].values, color="#8800AA", linewidth=1.0, label="RSI(14)")
                if "rsi_fast" in df.columns:
                    ax_rsi.plot(x, df["rsi_fast"].values, color="#00AACC", linewidth=0.8, alpha=0.7, label="RSI(5)")
                ax_rsi.axhline(y=p.get("rsi_os", 35), color="green", linestyle="--", alpha=0.5)
                ax_rsi.axhline(y=p.get("rsi_ob", 80), color="red", linestyle="--", alpha=0.5)
                ax_rsi.set_ylim(0, 100)
                ax_rsi.legend(fontsize=7, loc="upper left")
            ax_rsi.set_ylabel("RSI", fontsize=7)
            ax_rsi.grid(True, alpha=0.2)

            # 5) SuperTrend 영역
            if "st_dir" in df.columns:
                st_dir = df["st_dir"].values
                ax_st.plot(x, close, color="#333333", linewidth=0.8)
                for i in range(1, len(x)):
                    xi_prev = x.iloc[i-1] if hasattr(x, 'iloc') else x[i-1]
                    xi = x.iloc[i] if hasattr(x, 'iloc') else x[i]
                    c = "green" if st_dir[i] == 1 else "red"
                    ax_st.axvspan(xi_prev, xi, alpha=0.1, color=c)
            ax_st.set_ylabel("SuperTrend", fontsize=7)
            ax_st.grid(True, alpha=0.2)

            # 6) KOSPI 비교
            if kospi_df is not None and "close" in kospi_df.columns and len(kospi_df) > 0:
                try:
                    stock_norm = close / close[0] * 100
                    k_close = kospi_df["close"].values
                    k_norm = k_close / k_close[0] * 100
                    k_x = pd.to_datetime(kospi_df["date"]) if "date" in kospi_df.columns else range(len(k_close))
                    ax_kospi.plot(x, stock_norm, color="#FF4444", linewidth=1.0, label="종목")
                    ax_kospi.plot(k_x, k_norm, color="#4444FF", linewidth=1.0, label="KOSPI")
                    ax_kospi.axhline(y=100, color="gray", linestyle="--", alpha=0.3)
                    ax_kospi.legend(fontsize=7, loc="upper left")
                except Exception:
                    ax_kospi.text(0.5, 0.5, "비교 실패", ha="center", va="center", fontsize=8)
            else:
                ax_kospi.text(0.5, 0.5, "KOSPI 없음", ha="center", va="center", fontsize=9, alpha=0.5)
            ax_kospi.set_ylabel("상대강도", fontsize=7)
            ax_kospi.grid(True, alpha=0.2)

            for ax in [ax_price, ax_vol, ax_slope, ax_rsi, ax_st]:
                ax.tick_params(labelbottom=False)

            try:
                self.fig.tight_layout()
            except Exception:
                pass
            self.canvas.draw_idle()

        except Exception as e:
            logger.error(f"ChartWidget error: {e}\n{traceback.format_exc()}")
            try:
                self.fig.clear()
                ax = self.fig.add_subplot(111)
                ax.text(0.5, 0.5, f"차트 오류: {e}", ha="center", va="center")
                self.canvas.draw_idle()
            except Exception:
                pass
