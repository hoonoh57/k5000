# -*- coding: utf-8 -*-
"""
ui/chart_widget.py
==================
6패널 주식 차트: 캔들스틱 + JMA/ST 오버레이, 볼륨, JMA 슬로프, RSI, ST, KOSPI 비교.
Buy/Sell 마커, 크로스헤어(x=날짜, y=가격) 포함.
"""
from __future__ import annotations

import logging
import numpy as np
import pandas as pd
from datetime import datetime

from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtCore import Qt

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.gridspec import GridSpec
from matplotlib.patches import FancyBboxPatch
import matplotlib.ticker as mticker
import matplotlib.dates as mdates
from core import config          # <== 이 줄 추가
logger = logging.getLogger(__name__)


class StockChartWidget(QWidget):
    """PyQt6 위젯: matplotlib 기반 6패널 주식 차트."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.fig = Figure(figsize=(14, 10), dpi=100, facecolor='#1e1e2e')
        self.canvas = FigureCanvas(self.fig)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)

        # 크로스헤어 상태
        self._crosshair_lines = []
        self._crosshair_texts = []
        self._axes_list = []
        self._x_dates = []   # datetime 리스트
        self._bg = None

        self.canvas.mpl_connect('motion_notify_event', self._on_mouse_move)
        self.canvas.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    # ─────────────────── 메인 plot ───────────────────
    def plot(self, df: pd.DataFrame, p: dict, title: str = '',
             trades=None, kospi_df=None):
        """전체 차트를 다시 그린다."""
        self.fig.clear()
        self._crosshair_lines.clear()
        self._crosshair_texts.clear()
        self._axes_list.clear()
        self._x_dates.clear()

        if df is None or df.empty:
            ax = self.fig.add_subplot(111)
            ax.set_facecolor('#1e1e2e')
            ax.text(0.5, 0.5, '데이터 없음', transform=ax.transAxes,
                    ha='center', va='center', fontsize=16, color='#888')
            self.canvas.draw()
            return

        try:
            self._do_plot(df, p, title, trades, kospi_df)
        except Exception as e:
            logger.error(f"[CHART] plot 에러: {e}", exc_info=True)
            self.fig.clear()
            ax = self.fig.add_subplot(111)
            ax.set_facecolor('#1e1e2e')
            ax.text(0.5, 0.5, f'차트 렌더링 에러:\n{e}',
                    transform=ax.transAxes, ha='center', va='center',
                    fontsize=12, color='#ff6666', wrap=True)
            self.canvas.draw()

    def _do_plot(self, df, p, title, trades, kospi_df):
        """실제 차트 렌더링 로직."""
        df = df.copy().reset_index(drop=True)

        # ── x축 날짜 준비 ──
        if 'date' in df.columns:
            dates = pd.to_datetime(df['date'])
        elif isinstance(df.index, pd.DatetimeIndex):
            dates = df.index.to_series().reset_index(drop=True)
        else:
            dates = pd.Series(range(len(df)))

        x = np.arange(len(df))
        self._x_dates = dates.tolist()

        # ── JMA slope_pct 계산 ──
        if 'jma' in df.columns and 'jma_slope' in df.columns:
            jma_shifted = df['jma'].shift(1)
            df['slope_pct'] = np.where(
                jma_shifted.abs() > 1e-9,
                (df['jma_slope'] / jma_shifted) * 100,
                0.0
            )
        else:
            df['slope_pct'] = 0.0

        # ── GridSpec: 6행 ──
        gs = GridSpec(6, 1, figure=self.fig,
                      height_ratios=[3.5, 1, 1, 1, 1.5, 1],
                      hspace=0.05)

        style = dict(facecolor='#1e1e2e')
        ax_price = self.fig.add_subplot(gs[0], **style)
        ax_vol   = self.fig.add_subplot(gs[1], sharex=ax_price, **style)
        ax_slope = self.fig.add_subplot(gs[2], sharex=ax_price, **style)
        ax_rsi   = self.fig.add_subplot(gs[3], sharex=ax_price, **style)
        ax_st    = self.fig.add_subplot(gs[4], sharex=ax_price, **style)
        ax_kospi = self.fig.add_subplot(gs[5], sharex=ax_price, **style)

        axes = [ax_price, ax_vol, ax_slope, ax_rsi, ax_st, ax_kospi]
        self._axes_list = axes

        for ax in axes:
            ax.set_facecolor('#1e1e2e')
            ax.tick_params(colors='#aaa', labelsize=7)
            ax.grid(True, alpha=0.15, color='#555')
            for spine in ax.spines.values():
                spine.set_color('#444')

        # ── 1) 캔들스틱 + JMA + ST ──
        self._draw_candlestick(ax_price, df, x)
        self._draw_jma_overlay(ax_price, df, x)
        self._draw_st_overlay(ax_price, df, x)

        if trades:
            self._draw_trade_markers(ax_price, df, x, dates, trades)

        # 횡보 구간 표시 (추가)
        self._draw_sideways_zones(ax_price, df, x)   ####추가됨

        ax_price.set_title(title or '가격 차트', color='#eee',
                           fontsize=11, pad=8, loc='left')
        ax_price.set_ylabel('가격', color='#aaa', fontsize=8)

        # ── 2) 볼륨 ──
        if 'volume' in df.columns:
            colors_vol = ['#26a69a' if df['close'].iloc[i] >= df['open'].iloc[i]
                          else '#ef5350' for i in range(len(df))]
            ax_vol.bar(x, df['volume'], color=colors_vol, alpha=0.7, width=0.7)
        ax_vol.set_ylabel('거래량', color='#aaa', fontsize=8)
        ax_vol.yaxis.set_major_formatter(
            mticker.FuncFormatter(lambda v, _: f'{v/1e6:.1f}M' if v >= 1e6
                                  else f'{v/1e3:.0f}K' if v >= 1e3 else f'{v:.0f}'))

        # ── 3) JMA 슬로프 (%) ──
        sp = df['slope_pct']
        colors_slope = ['#26a69a' if v >= 0 else '#ef5350' for v in sp]
        ax_slope.bar(x, sp, color=colors_slope, alpha=0.8, width=0.7)
        ax_slope.axhline(0, color='#666', linewidth=0.5)
        abs_max = max(sp.abs().max(), 0.5) * 1.2
        ax_slope.set_ylim(-abs_max, abs_max)
        ax_slope.set_ylabel('JMA 슬로프 %', color='#aaa', fontsize=8)

        # ── 4) RSI ──
        if 'rsi' in df.columns:
            ax_rsi.plot(x, df['rsi'], color='#ab47bc', linewidth=1, label='RSI')
            if 'rsi_fast' in df.columns:
                ax_rsi.plot(x, df['rsi_fast'], color='#ffa726',
                            linewidth=0.8, alpha=0.7, label='RSI Fast')
            rsi_ob = p.get('rsi_ob', 80)
            rsi_os = p.get('rsi_os', 35)
            ax_rsi.axhline(rsi_ob, color='#ef5350', linewidth=0.5,
                           linestyle='--', alpha=0.6)
            ax_rsi.axhline(rsi_os, color='#26a69a', linewidth=0.5,
                           linestyle='--', alpha=0.6)
            ax_rsi.axhline(50, color='#666', linewidth=0.3, linestyle=':')
            ax_rsi.set_ylim(0, 100)
            ax_rsi.legend(loc='upper left', fontsize=6,
                          facecolor='#1e1e2e', edgecolor='#444',
                          labelcolor='#ccc')
        ax_rsi.set_ylabel('RSI', color='#aaa', fontsize=8)

        # ── 5) SuperTrend ──
        if 'st' in df.columns:
            ax_st.plot(x, df['close'], color='#888', linewidth=0.8,
                       alpha=0.5, label='종가')
            ax_st.plot(x, df['st'], color='#42a5f5', linewidth=1.2,
                       label='SuperTrend')
            if 'st_dir' in df.columns:
                up_mask = df['st_dir'] == 1
                dn_mask = df['st_dir'] == -1
                ax_st.fill_between(x, df['st'], df['close'],
                                   where=up_mask, alpha=0.1, color='#26a69a')
                ax_st.fill_between(x, df['st'], df['close'],
                                   where=dn_mask, alpha=0.1, color='#ef5350')
            ax_st.legend(loc='upper left', fontsize=6,
                         facecolor='#1e1e2e', edgecolor='#444',
                         labelcolor='#ccc')
        ax_st.set_ylabel('ST', color='#aaa', fontsize=8)

        # ── 6) KOSPI 비교 ──
        if kospi_df is not None and not kospi_df.empty:
            self._draw_kospi_comparison(ax_kospi, df, kospi_df, x, dates)
        else:
            ax_kospi.text(0.5, 0.5, 'KOSPI 데이터 없음',
                          transform=ax_kospi.transAxes,
                          ha='center', va='center', fontsize=9, color='#666')
        ax_kospi.set_ylabel('비교 (기준=100)', color='#aaa', fontsize=8)

        # ── x축 설정 ──
        for ax in axes[:-1]:
            ax.tick_params(labelbottom=False)

        # 마지막 축에 날짜 라벨
        tick_step = max(1, len(x) // 10)
        tick_positions = x[::tick_step]
        tick_labels = []
        for i in tick_positions:
            if i < len(self._x_dates):
                dt = self._x_dates[i]
                if hasattr(dt, 'strftime'):
                    tick_labels.append(dt.strftime('%m/%d'))
                else:
                    tick_labels.append(str(dt))
            else:
                tick_labels.append('')
        ax_kospi.set_xticks(tick_positions)
        ax_kospi.set_xticklabels(tick_labels, rotation=45, fontsize=7, color='#aaa')

        # ── 크로스헤어 초기화 ──
        self._init_crosshair(axes)

        # ── 레이아웃 ──
        try:
            self.fig.subplots_adjust(left=0.08, right=0.95, top=0.95,
                                     bottom=0.06, hspace=0.05)
        except Exception:
            pass

        self.canvas.draw()
        # blitting 용 배경 저장
        try:
            self._bg = self.canvas.copy_from_bbox(self.fig.bbox)
        except Exception:
            self._bg = None

    # ─────────────── 캔들스틱 ───────────────
    def _draw_candlestick(self, ax, df, x):
        """OHLC 캔들스틱을 직접 그린다."""
        opens = df['open'].values
        highs = df['high'].values
        lows = df['low'].values
        closes = df['close'].values

        for i in range(len(df)):
            o, h, l, c = opens[i], highs[i], lows[i], closes[i]
            if np.isnan(o) or np.isnan(c):
                continue

            color = '#26a69a' if c >= o else '#ef5350'
            # 심지 (wick)
            ax.plot([x[i], x[i]], [l, h], color=color, linewidth=0.6)
            # 몸통 (body)
            body_low = min(o, c)
            body_high = max(o, c)
            body_height = max(body_high - body_low, (h - l) * 0.01)  # 최소 높이
            ax.bar(x[i], body_height, bottom=body_low, width=0.7,
                   color=color, edgecolor=color, linewidth=0.3)

    # ─────────────── JMA 오버레이 ───────────────
    def _draw_jma_overlay(self, ax, df, x):
        """JMA 라인을 가격 차트에 오버레이."""
        if 'jma' not in df.columns:
            return

        jma = df['jma'].values
        valid = ~np.isnan(jma)

        if 'jma_slope' in df.columns:
            slope = df['jma_slope'].values
            # 상승/하락 구간별로 색상 구분
            up = slope >= 0
            dn = slope < 0

            # 상승 구간
            for start, end in self._get_segments(up & valid):
                seg_x = x[start:end+1]
                seg_y = jma[start:end+1]
                ax.plot(seg_x, seg_y, color='#ff9800', linewidth=1.8, alpha=0.9)

            # 하락 구간
            for start, end in self._get_segments(dn & valid):
                seg_x = x[start:end+1]
                seg_y = jma[start:end+1]
                ax.plot(seg_x, seg_y, color='#ab47bc', linewidth=1.8, alpha=0.9)
        else:
            # slope 정보 없으면 단색
            ax.plot(x[valid], jma[valid], color='#ff9800', linewidth=1.5,
                    alpha=0.8, label='JMA')

    # ─────────────── ST 오버레이 ───────────────
    def _draw_st_overlay(self, ax, df, x):
        """SuperTrend 라인을 가격 차트에 오버레이."""
        if 'st' not in df.columns:
            return

        st = df['st'].values
        valid = ~np.isnan(st)

        if 'st_dir' in df.columns:
            st_dir = df['st_dir'].values
            up = (st_dir == 1) & valid
            dn = (st_dir == -1) & valid

            for start, end in self._get_segments(up):
                ax.plot(x[start:end+1], st[start:end+1],
                        color='#26a69a', linewidth=1.2, linestyle='--', alpha=0.7)
            for start, end in self._get_segments(dn):
                ax.plot(x[start:end+1], st[start:end+1],
                        color='#ef5350', linewidth=1.2, linestyle='--', alpha=0.7)
        else:
            ax.plot(x[valid], st[valid], color='#42a5f5', linewidth=1,
                    alpha=0.6, linestyle='--')

    # ─────────────── 매매 신호 마커 ───────────────
    def _draw_trade_markers(self, ax, df, x, dates, trades):
        """Buy/Sell 마커를 가격 차트에 표시."""
        if not trades:
            return

        # ===== 긴급 디버그 =====
        sample_date = dates[0] if len(dates) > 0 else None
        t0 = trades[0]
        ed = getattr(t0, 'entry_date', None)
        logger.info(f"[CHART DEBUG] dates[0]: type={type(sample_date).__name__}, "
                     f"val='{sample_date}', str10='{str(sample_date)[:10]}'")
        logger.info(f"[CHART DEBUG] trade.entry: type={type(ed).__name__}, "
                     f"val='{ed}', str10='{str(ed)[:10]}'")


        # date_to_x 매핑 구축
        date_to_x = {}
        for i, dt in enumerate(dates):
            try:
                key = str(dt)[:10]
                date_to_x[key] = i
            except Exception:
                continue

        logger.info(f"[CHART DEBUG] date_to_x keys (first 5): "
                     f"{list(date_to_x.keys())[:5]}")
        logger.info(f"[CHART DEBUG] looking for: '{str(ed)[:10]}' "
                     f"-> found={str(ed)[:10] in date_to_x}")
        # ===== 디버그 끝 =====

        buy_x, buy_y = [], []
        sell_x, sell_y = [], []

        for t in trades:
            entry_date = getattr(t, 'entry_date', None)
            entry_price = getattr(t, 'entry_price', None)
            if entry_date is not None and entry_price is not None:
                key = str(entry_date)[:10]
                if key in date_to_x:
                    buy_x.append(date_to_x[key])
                    buy_y.append(float(entry_price))

            exit_date = getattr(t, 'exit_date', None)
            exit_price = getattr(t, 'exit_price', None)
            if exit_date is not None and exit_price is not None:
                key = str(exit_date)[:10]
                if key in date_to_x:
                    sell_x.append(date_to_x[key])
                    sell_y.append(float(exit_price))

        if buy_x:
            ax.scatter(buy_x, buy_y, marker='^', color='#00e676',
                       s=80, zorder=10, edgecolors='white', linewidths=0.5,
                       label=f'Buy ({len(buy_x)})')
            for bx, by in zip(buy_x, buy_y):
                ax.annotate('B', (bx, by), textcoords="offset points",
                            xytext=(0, -14), fontsize=6, color='#00e676',
                            ha='center', fontweight='bold')

        if sell_x:
            ax.scatter(sell_x, sell_y, marker='v', color='#ff1744',
                       s=80, zorder=10, edgecolors='white', linewidths=0.5,
                       label=f'Sell ({len(sell_x)})')
            for sx, sy in zip(sell_x, sell_y):
                ax.annotate('S', (sx, sy), textcoords="offset points",
                            xytext=(0, 12), fontsize=6, color='#ff1744',
                            ha='center', fontweight='bold')

        for t in trades:
            ed = getattr(t, 'entry_date', None)
            xd = getattr(t, 'exit_date', None)
            if ed is None or xd is None:
                continue
            ek, xk = str(ed)[:10], str(xd)[:10]
            if ek in date_to_x and xk in date_to_x:
                x1, x2 = date_to_x[ek], date_to_x[xk]
                pnl = getattr(t, 'pnl', 0)
                color = '#26a69a' if pnl >= 0 else '#ef5350'
                ax.axvspan(x1 - 0.5, x2 + 0.5, alpha=0.06, color=color)

        if buy_x or sell_x:
            ax.legend(loc='upper left', fontsize=7,
                      facecolor='#1e1e2e', edgecolor='#444',
                      labelcolor='#ccc')

        logger.info(f"[CHART] 매매 마커: Buy={len(buy_x)}, Sell={len(sell_x)}")


    # ─────────────── 횡보 구간 표시 ───────────────
    def _draw_sideways_zones(self, ax, df, x):
        """횡보 구간을 회색 배경으로 표시."""

        # 차트도 같은 YAML 값을 읽어 일치 보장
        atr_ratio = config.get("signals.bull.sideways.atr_ratio", 0.85)
        jma_flips_th = config.get("signals.bull.sideways.jma_flips", 3)
        range_th = config.get("signals.bull.sideways.range_pct", 3.5)
        min_cond = config.get("signals.bull.sideways.min_conditions", 1)
        sw_alpha = config.get("chart.sideways_alpha", 0.12)
        sw_color = config.get("chart.sideways_color", "#9e9e9e")


        if len(df) < 20:
            return

        try:
            sideways_mask = np.zeros(len(df), dtype=bool)
            atr_hits = 0
            jma_hits = 0
            range_hits = 0

            for i in range(20, len(df)):
                count = 0

                # 조건 1: ATR 축소 (0.7 -> 0.85로 완화)
                if 'atr' in df.columns:
                    atr_now = df['atr'].iloc[i]
                    atr_avg = df['atr'].iloc[max(0, i - 20):i].mean()
                    if atr_avg > 0 and not np.isnan(atr_now):
                        if atr_now < atr_avg * 0.85:
                            count += 1
                            atr_hits += 1

                # 조건 2: JMA slope 진동 (flips >= 3 유지)
                if 'jma_slope' in df.columns:
                    slope_window = df['jma_slope'].iloc[max(0, i - 10):i + 1]
                    if len(slope_window) >= 5:
                        signs = (slope_window > 0).astype(int)
                        flips = signs.diff().abs().sum()
                        if flips >= 3:
                            count += 1
                            jma_hits += 1

                # 조건 3: 가격 레인지 축소 (2.0% -> 3.5%로 완화)
                if all(c in df.columns for c in ['high', 'low', 'close']):
                    window = df.iloc[max(0, i - 20):i + 1]
                    if len(window) >= 10:
                        avg_close = window['close'].mean()
                        if avg_close > 0:
                            range_pct = (
                                (window['high'] - window['low']) / avg_close
                            ).mean() * 100
                            if range_pct < 3.5:
                                count += 1
                                range_hits += 1

                # 1개 이상 충족 시 횡보 (기존 2개 -> 1개로 완화)
                sideways_mask[i] = (count >= 1)

            total_bars = len(df) - 20
            logger.info(
                f"[CHART SIDEWAYS] {total_bars}봉: "
                f"ATR={atr_hits}, JMA={jma_hits}, Range={range_hits}, "
                f"횡보={int(sideways_mask.sum())}개"
            )

            segments = self._get_segments(sideways_mask)
            for start, end in segments:
                ax.axvspan(
                    x[start] - 0.5, x[end] + 0.5,
                    alpha=0.10, color='#9e9e9e',
                    zorder=0,
                )

            if segments:
                from matplotlib.patches import Patch
                sideways_patch = Patch(
                    facecolor='#9e9e9e', alpha=0.3,
                    label=f'횡보 ({len(segments)})'
                )
                handles, labels = ax.get_legend_handles_labels()
                handles.append(sideways_patch)
                labels.append(f'횡보 ({len(segments)})')
                ax.legend(
                    handles, labels,
                    loc='upper left', fontsize=7,
                    facecolor='#1e1e2e', edgecolor='#444',
                    labelcolor='#ccc',
                )

            logger.info(f"[CHART] 횡보 구간: {len(segments)}개")

        except Exception as e:
            logger.warning(f"[CHART] 횡보 구간 표시 에러: {e}")


    # ─────────────── KOSPI 비교 ───────────────
    def _draw_kospi_comparison(self, ax, df, kospi_df, x, dates):
        """KOSPI와 종목의 정규화 비교 차트."""
        try:
            kospi_df = kospi_df.copy()

            # kospi_df 날짜를 문자열 키로 변환
            if 'date' in kospi_df.columns:
                kospi_df['_date_key'] = kospi_df['date'].apply(lambda d: str(d)[:10])
            elif isinstance(kospi_df.index, pd.DatetimeIndex):
                kospi_df = kospi_df.reset_index()
                kospi_df.rename(columns={kospi_df.columns[0]: 'date'}, inplace=True)
                kospi_df['_date_key'] = kospi_df['date'].apply(lambda d: str(d)[:10])
            else:
                ax.text(0.5, 0.5, 'KOSPI 날짜 컬럼 없음', transform=ax.transAxes,
                        ha='center', fontsize=9, color='#666')
                return

            # 종목 날짜도 문자열 키로
            stock_date_keys = [str(d)[:10] for d in dates]

            # kospi 종가를 종목 날짜 순서에 맞춰 매핑
            kospi_map = dict(zip(kospi_df['_date_key'], kospi_df['close']))
            kospi_matched = []
            for dk in stock_date_keys:
                kospi_matched.append(kospi_map.get(dk, np.nan))

            kospi_series = pd.Series(kospi_matched)
            kospi_series = kospi_series.ffill().bfill()

            if kospi_series.notna().sum() == 0:
                ax.text(0.5, 0.5, 'KOSPI 매칭 실패', transform=ax.transAxes,
                        ha='center', fontsize=9, color='#666')
                return

            # 정규화 (기준=100)
            stock_first = df['close'].iloc[0]
            kospi_first = kospi_series.dropna().iloc[0]

            if stock_first == 0 or kospi_first == 0:
                ax.text(0.5, 0.5, 'KOSPI 정규화 실패', transform=ax.transAxes,
                        ha='center', fontsize=9, color='#666')
                return

            stock_norm = (df['close'] / stock_first) * 100
            kospi_norm = (kospi_series / kospi_first) * 100

            ax.plot(x, stock_norm.values, color='#ffa726', linewidth=1.2, label='종목')
            ax.plot(x, kospi_norm.values, color='#42a5f5', linewidth=1.0,
                    alpha=0.7, label='KOSPI')
            ax.axhline(100, color='#666', linewidth=0.3, linestyle=':')
            ax.legend(loc='upper left', fontsize=6,
                      facecolor='#1e1e2e', edgecolor='#444', labelcolor='#ccc')

        except Exception as e:
            logger.warning(f"[CHART] KOSPI 비교 에러: {e}")
            ax.text(0.5, 0.5, f'KOSPI 비교 에러', transform=ax.transAxes,
                    ha='center', fontsize=9, color='#666')

    # ─────────────── 크로스헤어 ───────────────
    def _init_crosshair(self, axes):
        """크로스헤어용 라인/텍스트 객체 초기화."""
        self._crosshair_lines.clear()
        self._crosshair_texts.clear()

        labels = ['가격', '거래량', '슬로프%', 'RSI', 'ST', 'KOSPI']

        for i, ax in enumerate(axes):
            hline = ax.axhline(0, color='#ffeb3b', linewidth=0.5,
                               alpha=0.6, visible=False)
            vline = ax.axvline(0, color='#ffeb3b', linewidth=0.5,
                               alpha=0.6, visible=False)
            self._crosshair_lines.append((hline, vline))

            # y값 텍스트 (오른쪽)
            txt_y = ax.text(1.01, 0.5, '', transform=ax.transAxes,
                            fontsize=7, color='#ffeb3b',
                            ha='left', va='center', visible=False,
                            bbox=dict(boxstyle='round,pad=0.2',
                                      facecolor='#333', alpha=0.8,
                                      edgecolor='#ffeb3b'))
            self._crosshair_texts.append(txt_y)

        # 날짜 텍스트 (하단 축 아래)
        self._date_text = axes[-1].text(
            0.5, -0.15, '', transform=axes[-1].transAxes,
            fontsize=8, color='#ffeb3b', ha='center', va='top',
            visible=False,
            bbox=dict(boxstyle='round,pad=0.2',
                      facecolor='#333', alpha=0.8, edgecolor='#ffeb3b'))

    def _on_mouse_move(self, event):
        """마우스 이동 시 크로스헤어 업데이트."""
        if not self._axes_list or not self._crosshair_lines:
            return

        if event.inaxes is None or event.xdata is None:
            self._hide_crosshair()
            return

        try:
            xi = int(round(event.xdata))
            if xi < 0 or xi >= len(self._x_dates):
                self._hide_crosshair()
                return

            # 배경 복원
            if self._bg is not None:
                self.canvas.restore_region(self._bg)

            # 날짜 텍스트
            dt = self._x_dates[xi]
            if hasattr(dt, 'strftime'):
                date_str = dt.strftime('%Y-%m-%d')
            else:
                date_str = str(dt)[:10]

            self._date_text.set_text(date_str)
            self._date_text.set_visible(True)

            format_funcs = [
                lambda y: f'{y:,.0f}',                                          # 가격
                lambda y: f'{y/1e6:.1f}M' if abs(y) >= 1e6 else f'{y:,.0f}',  # 볼륨
                lambda y: f'{y:.2f}%',                                          # 슬로프
                lambda y: f'{y:.1f}',                                           # RSI
                lambda y: f'{y:,.0f}',                                          # ST
                lambda y: f'{y:.1f}',                                           # KOSPI
            ]

            for i, ax in enumerate(self._axes_list):
                hline, vline = self._crosshair_lines[i]
                txt = self._crosshair_texts[i]

                # 수직선은 모든 축에 표시
                vline.set_xdata([xi])
                vline.set_visible(True)

                if event.inaxes == ax:
                    # 마우스가 이 축 위에 있으면 수평선 + y값 표시
                    y_val = event.ydata
                    hline.set_ydata([y_val])
                    hline.set_visible(True)

                    try:
                        fmt = format_funcs[i]
                        txt.set_text(fmt(y_val))
                    except Exception:
                        txt.set_text(f'{y_val:.2f}')
                    txt.set_visible(True)
                else:
                    hline.set_visible(False)
                    txt.set_visible(False)

                # artist 그리기
                ax.draw_artist(vline)
                if hline.get_visible():
                    ax.draw_artist(hline)
                if txt.get_visible():
                    ax.draw_artist(txt)

            # 날짜 텍스트 그리기
            self._axes_list[-1].draw_artist(self._date_text)
            self.canvas.blit(self.fig.bbox)

        except Exception:
            pass  # 크로스헤어 실패는 무시


    def _hide_crosshair(self):
        """크로스헤어 숨김."""
        try:
            if self._bg is not None:
                self.canvas.restore_region(self._bg)
            for hline, vline in self._crosshair_lines:
                hline.set_visible(False)
                vline.set_visible(False)
            for txt in self._crosshair_texts:
                txt.set_visible(False)
            if hasattr(self, '_date_text'):
                self._date_text.set_visible(False)
            self.canvas.blit(self.fig.bbox)
        except Exception:
            pass

    # ─────────────── 유틸리티 ───────────────
    @staticmethod
    def _get_segments(mask):
        """bool 마스크에서 연속 True 구간의 (start, end) 리스트 반환."""
        segments = []
        in_seg = False
        start = 0
        for i, v in enumerate(mask):
            if v and not in_seg:
                start = i
                in_seg = True
            elif not v and in_seg:
                segments.append((start, i - 1))
                in_seg = False
        if in_seg:
            segments.append((start, len(mask) - 1))
        return segments
