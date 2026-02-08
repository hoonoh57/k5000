# -*- coding: utf-8 -*-
"""
ui/workers.py  [MUTABLE]
========================
QThread 워커: 스크리닝, 단일 분석, 일괄 분석.
"""
from __future__ import annotations
import logging
import traceback

from PyQt6.QtCore import QThread, pyqtSignal

from plugins.screener import BetaCorrelationScreener

logger = logging.getLogger(__name__)


class ScreeningWorker(QThread):
    finished = pyqtSignal(list)    # List[dict]
    error = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, data_source, params, start_date=None, end_date=None, parent=None):
        super().__init__(parent)
        self.data_source = data_source
        self.params = params
        self._start_date = start_date
        self._end_date = end_date

    def run(self):
        try:
            screener = BetaCorrelationScreener()

            from datetime import datetime, timedelta
            months = self.params.get("screen_months", 6)
            end_date = self._end_date or datetime.now().strftime("%Y-%m-%d")
            start_date = self._start_date or (datetime.now() - timedelta(days=months * 30)).strftime("%Y-%m-%d")

            self.progress.emit(f"KOSPI 지수 로드 중...")
            index_df = self.data_source.fetch_index_candles("KOSPI", start_date, end_date)

            self.progress.emit(f"스크리닝 시작: {start_date} ~ {end_date}")
            candidates = screener.screen(
                universe=[],
                index_df=index_df,
                data_source=self.data_source,
                params=self.params,
                start_date=start_date,
                end_date=end_date,
            )

            results = []
            for c in candidates:
                results.append({
                    "code": c.code,
                    "name": c.name,
                    "beta": c.beta,
                    "correlation": c.correlation,
                    "score": c.score,
                    "avg_volume": c.avg_volume,
                })

            self.finished.emit(results)

        except Exception as e:
            msg = f"ScreeningWorker error: {e}\n{traceback.format_exc()}"
            logger.error(msg)
            self.error.emit(msg)

class AnalysisWorker(QThread):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, engine, code, name, start_date, end_date,
                 data_source, params, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.code = code
        self.name = name
        self.start_date = start_date
        self.end_date = end_date
        self.data_source = data_source
        self.params = params

    def run(self):
        try:
            self.progress.emit(f"데이터 로드 중: {self.name}")

            # 백테스트 실행
            self.progress.emit(f"백테스트 중: {self.name}")
            result = self.engine.run(
                self.code, self.start_date, self.end_date,
                self.params.get("initial_capital", 10_000_000)
            )

            if result is None:
                self.error.emit(f"{self.code}: 백테스트 실패")
                return

            # 지표 계산된 DataFrame도 필요 (차트용)
            df = self.data_source.fetch_candles(self.code, self.start_date, self.end_date)
            if df is not None and not df.empty:
                from plugins.indicators import SuperTrendIndicator, JMAIndicator, RSIIndicator
                for ind in [SuperTrendIndicator(), JMAIndicator(), RSIIndicator()]:
                    try:
                        df = ind.compute(df, self.params)
                    except Exception:
                        pass

            # KOSPI (비교용)
            kospi_df = None
            try:
                kospi_df = self.data_source.fetch_index_candles(
                    "KOSPI", self.start_date, self.end_date
                )
            except Exception:
                pass

            self.finished.emit({
                "code": self.code,
                "name": self.name,
                "backtest_result": result,
                "df": df,
                "kospi_df": kospi_df,
                "regime": getattr(result, "regime_used", None),
            })


        except Exception as e:
            msg = f"AnalysisWorker error: {e}\n{traceback.format_exc()}"
            logger.error(msg)
            self.error.emit(msg)


class BatchAnalysisWorker(QThread):
    finished = pyqtSignal(list)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)
    single_done = pyqtSignal(dict)

    def __init__(self, engine, stocks, start_date, end_date,
                 data_source, params, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.stocks = stocks
        self.start_date = start_date
        self.end_date = end_date
        self.data_source = data_source
        self.params = params

    def run(self):
        try:
            results = []
            total = len(self.stocks)

            for idx, stock in enumerate(self.stocks):
                code = stock.get("code", "")
                name = stock.get("name", "")
                if not code:
                    continue

                self.progress.emit(f"[{idx+1}/{total}] {name}({code}) 분석 중...")

                try:
                    bt = self.engine.run(
                        code, self.start_date, self.end_date,
                        self.params.get("initial_capital", 10_000_000)
                    )
                    if bt is None:
                        continue

                    result = {
                        "code": code,
                        "name": name,
                        "backtest_result": bt,
                    }
                    results.append(result)
                    self.single_done.emit(result)

                except Exception as e:
                    logger.debug(f"BatchWorker {code} error: {e}")
                    continue

            self.finished.emit(results)

        except Exception as e:
            msg = f"BatchWorker error: {e}\n{traceback.format_exc()}"
            logger.error(msg)
            self.error.emit(msg)
