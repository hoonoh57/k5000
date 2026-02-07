# -*- coding: utf-8 -*-
"""
ui/chart_widget.py  [MUTABLE]
=============================
6행 차트: 캔들+JMA+ST | 거래량 | JMA Slope(%) | RSI | SuperTrend | KOSPI 비교
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
import matplotlib.ticker as mticker

logger = logging.getLogger(__name__)


class StockChartWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.fig = Figure(figsize=(14, 12), dpi=80)
        self.canvas = FigureCanvas(self.fig)
        layout.addWidget(self.canvas)

        # 크로스헤어
        self._crosshair_lines = []
        self._crosshair_texts = []
        self._axes_list = []
        self._x_data = None
        self._date_labels = None
        self._x_date_text = None
        self._bg_cache = None

        self.canvas.mpl_connect("motion_notify_event", self._on_mouse_move)
        self.canvas.mpl_connect("axes_leave_event", self._on_mouse_leave)
        self.canvas.mpl_connect("draw_event", self._on_draw)

    # ================================================================
    #  메인 plot
    # ================================================================
    def plot(self, df, p, title="", trades=None, kospi_df=None):
        try:
            self.fig.clear()
            self._crosshair_lines = []
            self._crosshair_texts = []
            self._axes_list = []
            self._x_date_text = None
            self._bg_cache = None

            if df is None or df.empty or "close" not in df.columns:
                ax = self.fig.add_subplot(111)
                ax.text(0.5, 0.5, "데이터 없음", ha="center", va="center", fontsize=16)
                self.canvas.draw()
                return

            # ── x축 준비 ──
            if "date" in df.columns:
                dates = pd.to_datetime(df["date"]).reset_index(drop=True)
            elif isinstance(df.index, pd.DatetimeIndex):
                dates = df.index.to_series().reset_index(drop=True)
            else:
                dates = pd.Series(pd.date_range("2020-01-01", periods=len(df)))

            n = len(df)
            x = np.arange(n)
            self._x_data = x
            self._date_labels = dates

            o = df["open"].values.astype(float)
            h = df["high"].values.astype(float)
            lo = df["low"].values.astype(float)
            c = df["close"].values.astype(float)

            # ── JMA Slope → 퍼센트 변환 ──
            slope_pct = None
            if "jma_slope" in df.columns and "jma" in df.columns:
                jma_vals = df["jma"].values.astype(float)
                raw_slope = df["jma_slope"].values.astype(float)
                prev_jma = np.roll(jma_vals, 1)
                prev_jma[0] = np.nan
                with np.errstate(divide='ignore', invalid='ignore'):
                    slope_pct = np.where(
                        (prev_jma != 0) & (~np.isnan(prev_jma)),
                        raw_slope / prev_jma * 100, 0.0
                    )
                slope_pct[0] = 0.0
                slope_pct = np.nan_to_num(slope_pct, nan=0.0)

            # ── GridSpec ──
            gs = self.fig.add_gridspec(
                6, 1, height_ratios=[3.5, 1, 1, 1, 1.5, 1], hspace=0.06
            )
            ax_price = self.fig.add_subplot(gs[0])
            ax_vol   = self.fig.add_subplot(gs[1], sharex=ax_price)
            ax_slope = self.fig.add_subplot(gs[2], sharex=ax_price)
            ax_rsi   = self.fig.add_subplot(gs[3], sharex=ax_price)
            ax_st    = self.fig.add_subplot(gs[4], sharex=ax_price)
            ax_kospi = self.fig.add_subplot(gs[5], sharex=ax_price)

            all_axes = [ax_price, ax_vol, ax_slope, ax_rsi, ax_st, ax_kospi]
            self._axes_list = all_axes

            def _date_formatter(val, pos):
                idx = int(round(val))
                if 0 <= idx < n:
                    return dates.iloc[idx].strftime("%Y-%m-%d")
                return ""

            # =============================================
            # 1) 캔들차트 + JMA(2색) + ST + 매매신호
            # =============================================
            self._draw_candlestick(ax_price, x, o, h, lo, c)

            # JMA 오버레이 (상승=주황, 하락=보라)
            if "jma" in df.columns and "jma_slope" in df.columns:
                jma_v = df["jma"].values.astype(float)
                jma_s = df["jma_slope"].values.astype(float)
                for i in range(1, n):
                    if np.isnan(jma_v[i]) or np.isnan(jma_v[i - 1]):
                        continue
                    clr = "#FF6600" if jma_s[i] >= 0 else "#9900CC"
                    ax_price.plot(
                        [x[i - 1], x[i]], [jma_v[i - 1], jma_v[i]],
                        color=clr, linewidth=2.2, zorder=10, alpha=0.95
                    )
                ax_price.plot([], [], color="#FF6600", linewidth=2.2, label="JMA↑")
                ax_price.plot([], [], color="#9900CC", linewidth=2.2, label="JMA↓")

            # SuperTrend 라인
            if "st" in df.columns and "st_dir" in df.columns:
                st_vals = df["st"].values.astype(float)
                st_dir_arr = df["st_dir"].values
                for i in range(1, n):
                    if np.isnan(st_vals[i]) or np.isnan(st_vals[i - 1]):
                        continue
                    clr = "#00AA00" if st_dir_arr[i] == 1 else "#CC0000"
                    ax_price.plot(
                        [x[i - 1], x[i]], [st_vals[i - 1], st_vals[i]],
                        color=clr, linewidth=1.3, zorder=5, alpha=0.8
                    )

            # ── 매매 신호 마커 ──
            # logger.info(f"[SIGNAL] trades received: {type(trades)}, count={len(trades) if trades else 0}")

            if trades is not None and len(trades) > 0:
                buy_x, buy_y = [], []
                sell_x, sell_y = [], []

                # 날짜 배열을 문자열로 변환 (가장 확실한 매칭)
                dates_str = [str(d)[:10] for d in dates.values]
                # logger.info(f"[SIGNAL] dates_str sample: {dates_str[:3]}...{dates_str[-1]}")

                for ti, t in enumerate(trades):
                    try:
                        # entry_date → 문자열 10자리로 통일
                        entry_str = str(t.entry_date)[:10]
                        exit_str = str(t.exit_date)[:10] if t.exit_date is not None else None

                        #logger.info(f"[SIGNAL] trade[{ti}]: entry={entry_str}, exit={exit_str}, "
                        #            f"entry_price={t.entry_price}, exit_price={t.exit_price}")

                        # 매수 인덱스 찾기
                        b_idx = None
                        for j, ds in enumerate(dates_str):
                            if ds == entry_str:
                                b_idx = j
                                break

                        if b_idx is not None:
                            buy_x.append(b_idx)
                            buy_y.append(float(t.entry_price))
                            # logger.info(f"[SIGNAL] BUY marker at idx={b_idx}, price={t.entry_price}")

                            # 매도 인덱스 찾기
                            if exit_str and t.exit_price:
                                s_idx = None
                                for j, ds in enumerate(dates_str):
                                    if ds == exit_str:
                                        s_idx = j
                                        break

                                if s_idx is not None:
                                    sell_x.append(s_idx)
                                    sell_y.append(float(t.exit_price))
                                    # logger.info(f"[SIGNAL] SELL marker at idx={s_idx}, price={t.exit_price}")

                                    # 배경 span
                                    bg = "#CCFFCC" if t.pnl_pct > 0 else "#FFCCCC"
                                    ax_price.axvspan(
                                        b_idx - 0.5, s_idx + 0.5,
                                        alpha=0.12, color=bg, zorder=0
                                    )
                        else:
                            logger.warning(f"[SIGNAL] entry date NOT FOUND: {entry_str}")

                    except Exception as ex:
                        logger.error(f"[SIGNAL] Trade marker error: {ex}")
                        continue

                # 매수 마커
                if buy_x:
                    ax_price.scatter(
                        buy_x, buy_y,
                        marker="^", s=150, c="#00CC00", edgecolors="#006600",
                        linewidths=1.2, zorder=15, label=f"매수({len(buy_x)})"
                    )
                # 매도 마커
                if sell_x:
                    ax_price.scatter(
                        sell_x, sell_y,
                        marker="v", s=150, c="#FF3333", edgecolors="#990000",
                        linewidths=1.2, zorder=15, label=f"매도({len(sell_x)})"
                    )

                # logger.info(f"[SIGNAL] RESULT: buy={len(buy_x)}, sell={len(sell_x)}")

            ax_price.set_title(title or "SuperTrend + JMA", fontsize=11, fontweight="bold")
            ax_price.legend(loc="upper left", fontsize=7, ncol=6)
            ax_price.grid(True, alpha=0.25, linewidth=0.5)
            ax_price.set_ylabel("가격", fontsize=8)

            # =============================================
            # 2) 거래량
            # =============================================
            if "volume" in df.columns:
                vol = df["volume"].values.astype(float)
                vc = ["#CC3333" if c[i] < c[max(i - 1, 0)] else "#3333CC"
                       for i in range(n)]
                ax_vol.bar(x, vol, color=vc, alpha=0.6, width=0.7)
            ax_vol.set_ylabel("거래량", fontsize=7)
            ax_vol.grid(True, alpha=0.2, linewidth=0.5)

            # =============================================
            # 3) JMA Slope (%)
            # =============================================
            if slope_pct is not None:
                ax_slope.bar(x, np.where(slope_pct > 0, slope_pct, 0),
                             color="#00CC00", alpha=0.7, width=0.7)
                ax_slope.bar(x, np.where(slope_pct < 0, slope_pct, 0),
                             color="#CC0000", alpha=0.7, width=0.7)
                ax_slope.axhline(y=0, color="black", linewidth=0.8)
                ax_slope.axhline(y=0.3, color="#00AA00", linestyle="--",
                                 linewidth=0.6, alpha=0.5)
                ax_slope.axhline(y=-0.3, color="#CC0000", linestyle="--",
                                 linewidth=0.6, alpha=0.5)
                ax_slope.axhline(y=1.0, color="#006600", linestyle=":",
                                 linewidth=0.5, alpha=0.4)
                ax_slope.axhline(y=-1.0, color="#990000", linestyle=":",
                                 linewidth=0.5, alpha=0.4)
                valid = slope_pct[~np.isnan(slope_pct)]
                if len(valid) > 0:
                    p5, p95 = np.percentile(valid, [2, 98])
                    margin = max(abs(p5), abs(p95)) * 1.3
                    margin = max(margin, 0.5)
                    ax_slope.set_ylim(-margin, margin)
            ax_slope.set_ylabel("JMA Slope(%)", fontsize=7)
            ax_slope.grid(True, alpha=0.2, linewidth=0.5)

            # =============================================
            # 4) RSI
            # =============================================
            if "rsi" in df.columns:
                ax_rsi.plot(x, df["rsi"].values, color="#8800AA",
                            linewidth=1.0, label="RSI(14)")
                if "rsi_fast" in df.columns:
                    ax_rsi.plot(x, df["rsi_fast"].values,
                                color="#00AACC", linewidth=0.8, alpha=0.7, label="RSI(5)")
                rsi_os = p.get("rsi_os", 35)
                rsi_ob = p.get("rsi_ob", 80)
                ax_rsi.axhline(y=rsi_os, color="green", linestyle="--", alpha=0.5)
                ax_rsi.axhline(y=rsi_ob, color="red", linestyle="--", alpha=0.5)
                ax_rsi.fill_between(x, rsi_os, rsi_ob, alpha=0.03, color="gray")
                ax_rsi.set_ylim(0, 100)
                ax_rsi.legend(fontsize=7, loc="upper left")
            ax_rsi.set_ylabel("RSI", fontsize=7)
            ax_rsi.grid(True, alpha=0.2, linewidth=0.5)

            # =============================================
            # 5) SuperTrend 영역
            # =============================================
            if "st_dir" in df.columns:
                st_dir_vals = df["st_dir"].values
                ax_st.plot(x, c, color="#333333", linewidth=0.8)
                for i in range(n):
                    clr = "green" if st_dir_vals[i] == 1 else "red"
                    ax_st.axvspan(x[i] - 0.5, x[i] + 0.5, alpha=0.12, color=clr)
            ax_st.set_ylabel("SuperTrend", fontsize=7)
            ax_st.grid(True, alpha=0.2, linewidth=0.5)

            # =============================================
            # 6) KOSPI 비교
            # =============================================
            if kospi_df is not None and "close" in kospi_df.columns and len(kospi_df) > 0:
                try:
                    stock_norm = c / c[0] * 100
                    k_close = kospi_df["close"].values.astype(float)
                    k_norm = k_close / k_close[0] * 100
                    k_len = min(len(k_norm), n)
                    ax_kospi.plot(x[:k_len], stock_norm[:k_len],
                                 color="#FF4444", linewidth=1.0, label="종목")
                    ax_kospi.plot(x[:k_len], k_norm[:k_len],
                                 color="#4444FF", linewidth=1.0, label="KOSPI")
                    ax_kospi.axhline(y=100, color="gray", linestyle="--", alpha=0.3)
                    ax_kospi.legend(fontsize=7, loc="upper left")
                except Exception:
                    ax_kospi.text(0.5, 0.5, "비교 실패", ha="center", va="center", fontsize=8)
            else:
                ax_kospi.text(0.5, 0.5, "KOSPI 없음", ha="center", va="center",
                              fontsize=9, alpha=0.5)
            ax_kospi.set_ylabel("상대강도", fontsize=7)
            ax_kospi.grid(True, alpha=0.2, linewidth=0.5)

            # ── x축 라벨 ──
            for ax in [ax_price, ax_vol, ax_slope, ax_rsi, ax_st]:
                ax.tick_params(labelbottom=False)
            ax_kospi.xaxis.set_major_formatter(mticker.FuncFormatter(_date_formatter))
            ax_kospi.tick_params(axis="x", rotation=25, labelsize=7)
            ax_price.set_xlim(-1, n)

            # 크로스헤어 초기화
            self._init_crosshair(all_axes)

            try:
                self.fig.tight_layout()
            except Exception:
                pass
            self.canvas.draw()

        except Exception as e:
            logger.error(f"ChartWidget error: {e}\n{traceback.format_exc()}")
            try:
                self.fig.clear()
                ax = self.fig.add_subplot(111)
                ax.text(0.5, 0.5, f"차트 오류: {e}", ha="center", va="center")
                self.canvas.draw()
            except Exception:
                pass

    # ================================================================
    #  캔들스틱
    # ================================================================
    def _draw_candlestick(self, ax, x, o, h, lo, c):
        up = c >= o
        dn = ~up
        if np.any(up):
            body_h = np.where(up, c - o, 0.0)
            body_h = np.maximum(body_h, (h - lo) * 0.005)
            ax.bar(x[up], body_h[up], bottom=o[up], width=0.6,
                   color="#FF3333", edgecolor="#CC0000", linewidth=0.5, zorder=4)
        if np.any(dn):
            body_h = np.where(dn, o - c, 0.0)
            body_h = np.maximum(body_h, (h - lo) * 0.005)
            ax.bar(x[dn], body_h[dn], bottom=c[dn], width=0.6,
                   color="#3333FF", edgecolor="#0000CC", linewidth=0.5, zorder=4)
        top_body = np.maximum(o, c)
        ax.vlines(x, top_body, h, colors=np.where(up, "#CC0000", "#0000CC"),
                  linewidth=0.8, zorder=3)
        bot_body = np.minimum(o, c)
        ax.vlines(x, lo, bot_body, colors=np.where(up, "#CC0000", "#0000CC"),
                  linewidth=0.8, zorder=3)

    # ================================================================
    #  크로스헤어 (blitting으로 성능 개선)
    # ================================================================
    def _init_crosshair(self, axes):
        self._crosshair_lines = []
        self._crosshair_texts = []

        for ax in axes:
            vline = ax.axvline(x=0, color="#888888", linewidth=0.7,
                               linestyle="--", alpha=0.7, visible=False, animated=True)
            hline = ax.axhline(y=0, color="#888888", linewidth=0.7,
                               linestyle="--", alpha=0.7, visible=False, animated=True)
            self._crosshair_lines.append((vline, hline))

            y_text = ax.text(
                1.01, 0.5, "", transform=ax.get_yaxis_transform(),
                fontsize=7, color="white", ha="left", va="center",
                bbox=dict(boxstyle="round,pad=0.2", fc="#444444", ec="none", alpha=0.85),
                visible=False, zorder=100, clip_on=False, animated=True
            )
            self._crosshair_texts.append(y_text)

        self._x_date_text = axes[-1].text(
            0.5, -0.15, "", transform=axes[-1].get_xaxis_transform(),
            fontsize=8, color="white", ha="center", va="top",
            bbox=dict(boxstyle="round,pad=0.3", fc="#333333", ec="none", alpha=0.9),
            visible=False, zorder=100, clip_on=False, animated=True
        )

    def _on_draw(self, event):
        """draw 이벤트 발생 시 배경 캐시 저장 (blitting용)"""
        self._bg_cache = self.canvas.copy_from_bbox(self.fig.bbox)

    def _on_mouse_move(self, event):
        if (event.inaxes is None or not self._crosshair_lines
                or self._x_data is None or self._date_labels is None
                or self._bg_cache is None):
            self._hide_crosshair()
            return

        x_val = event.xdata
        y_val = event.ydata
        if x_val is None or y_val is None:
            self._hide_crosshair()
            return

        n = len(self._x_data)
        idx = int(round(x_val))
        if idx < 0 or idx >= n:
            self._hide_crosshair()
            return

        try:
            date_str = self._date_labels.iloc[idx].strftime("%Y-%m-%d")
        except Exception:
            date_str = ""

        # 배경 복원 (blitting)
        self.canvas.restore_region(self._bg_cache)

        for i, (vline, hline) in enumerate(self._crosshair_lines):
            vline.set_xdata([x_val])
            vline.set_visible(True)
            self._axes_list[i].draw_artist(vline)

            if self._axes_list[i] == event.inaxes:
                hline.set_ydata([y_val])
                hline.set_visible(True)
                if i == 2:
                    txt = f"{y_val:.2f}%"
                elif i == 3:
                    txt = f"{y_val:.1f}"
                else:
                    txt = f"{y_val:,.0f}"
                self._crosshair_texts[i].set_position((1.01, y_val))
                self._crosshair_texts[i].set_text(txt)
                self._crosshair_texts[i].set_visible(True)
                self._crosshair_texts[i].set_transform(
                    self._axes_list[i].get_yaxis_transform()
                )
                self._axes_list[i].draw_artist(hline)
                self._axes_list[i].draw_artist(self._crosshair_texts[i])
            else:
                hline.set_visible(False)
                self._crosshair_texts[i].set_visible(False)

        if self._x_date_text:
            self._x_date_text.set_position((x_val, -0.15))
            self._x_date_text.set_text(date_str)
            self._x_date_text.set_visible(True)
            self._x_date_text.set_transform(self._axes_list[-1].get_xaxis_transform())
            self._axes_list[-1].draw_artist(self._x_date_text)

        self.canvas.blit(self.fig.bbox)

    def _on_mouse_leave(self, event):
        self._hide_crosshair()

    def _hide_crosshair(self):
        if self._bg_cache is None:
            return
        changed = False
        for vline, hline in self._crosshair_lines:
            if vline.get_visible() or hline.get_visible():
                vline.set_visible(False)
                hline.set_visible(False)
                changed = True
        for txt in self._crosshair_texts:
            if txt.get_visible():
                txt.set_visible(False)
                changed = True
        if self._x_date_text and self._x_date_text.get_visible():
            self._x_date_text.set_visible(False)
            changed = True
        if changed:
            self.canvas.restore_region(self._bg_cache)
            self.canvas.blit(self.fig.bbox)
