# -*- coding: utf-8 -*-
"""
MySQL 기반 전략/섹터 CRUD 저장소
DB: stock_info
테이블: ibs_sectors, ibs_sector_stocks, ibs_screen_strategies,
        ibs_trade_strategies, ibs_backtest_results
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import pymysql

logger = logging.getLogger(__name__)


class DBStrategyStore:
    """MySQL 전략·섹터 저장소 (stock_info DB 재사용)"""

    def __init__(self, host="localhost", port=3306,
                 user="root", password="", db="stock_info"):
        self._conn_params = dict(
            host=host, port=port, user=user,
            password=password, db=db,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True,
        )
        self._conn: Optional[pymysql.Connection] = None

    # ── 연결 관리 ──

    def _get_conn(self) -> pymysql.Connection:
        if self._conn is None or not self._conn.open:
            self._conn = pymysql.connect(**self._conn_params)
            logger.info("[DB_STORE] MySQL 연결 완료")
        return self._conn

    def close(self):
        if self._conn and self._conn.open:
            self._conn.close()
            logger.info("[DB_STORE] MySQL 연결 종료")

    def _execute(self, sql: str, args=None) -> List[Dict]:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(sql, args)
            return cur.fetchall()

    def _execute_one(self, sql: str, args=None) -> Optional[Dict]:
        rows = self._execute(sql, args)
        return rows[0] if rows else None

    def _execute_write(self, sql: str, args=None) -> int:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(sql, args)
            return cur.lastrowid

    # ═══════════════════════════════════════════
    #  섹터 (ibs_sectors / ibs_sector_stocks)
    # ═══════════════════════════════════════════

    def get_all_sectors(self, active_only=True) -> List[Dict]:
        sql = "SELECT * FROM ibs_sectors"
        if active_only:
            sql += " WHERE active = 1"
        sql += " ORDER BY sort_order"
        return self._execute(sql)

    def get_sector(self, sector_id: str) -> Optional[Dict]:
        return self._execute_one(
            "SELECT * FROM ibs_sectors WHERE sector_id = %s", (sector_id,))

    def add_sector(self, sector_id: str, sector_name: str,
                   keywords: list = None, description: str = "",
                   sort_order: int = 0) -> str:
        self._execute_write(
            """INSERT INTO ibs_sectors
               (sector_id, sector_name, keywords, description, sort_order)
               VALUES (%s, %s, %s, %s, %s)""",
            (sector_id, sector_name,
             json.dumps(keywords or [], ensure_ascii=False),
             description, sort_order))
        logger.info(f"[DB_STORE] 섹터 추가: {sector_id} {sector_name}")
        return sector_id

    def update_sector(self, sector_id: str, **kwargs) -> bool:
        if not kwargs:
            return False
        sets, vals = [], []
        for k, v in kwargs.items():
            if k == "keywords" and isinstance(v, list):
                v = json.dumps(v, ensure_ascii=False)
            sets.append(f"`{k}` = %s")
            vals.append(v)
        vals.append(sector_id)
        self._execute_write(
            f"UPDATE ibs_sectors SET {', '.join(sets)} WHERE sector_id = %s",
            tuple(vals))
        return True

    def deactivate_sector(self, sector_id: str) -> bool:
        return self.update_sector(sector_id, active=0)

    # ── 섹터-종목 매핑 ──

    def get_sector_stocks(self, sector_id: str,
                          role: str = None) -> List[Dict]:
        sql = ("SELECT * FROM ibs_sector_stocks "
               "WHERE sector_id = %s AND active = 1")
        args = [sector_id]
        if role:
            sql += " AND role = %s"
            args.append(role)
        sql += " ORDER BY priority"
        return self._execute(sql, tuple(args))

    def get_all_sector_stocks(self, active_only=True) -> List[Dict]:
        sql = "SELECT ss.*, s.sector_name FROM ibs_sector_stocks ss "
        sql += "JOIN ibs_sectors s ON ss.sector_id = s.sector_id"
        if active_only:
            sql += " WHERE ss.active = 1 AND s.active = 1"
        sql += " ORDER BY ss.sector_id, ss.priority"
        return self._execute(sql)

    def add_sector_stock(self, sector_id: str, stock_code: str,
                         stock_name: str = "", role: str = "candidate",
                         priority: int = 0) -> int:
        row_id = self._execute_write(
            """INSERT INTO ibs_sector_stocks
               (sector_id, stock_code, stock_name, role, priority)
               VALUES (%s, %s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE
               stock_name=%s, role=%s, priority=%s, active=1""",
            (sector_id, stock_code, stock_name, role, priority,
             stock_name, role, priority))
        logger.info(f"[DB_STORE] 섹터종목 추가: {sector_id}/{stock_code} "
                     f"({stock_name}) role={role}")
        return row_id

    def remove_sector_stock(self, sector_id: str, stock_code: str):
        self._execute_write(
            "UPDATE ibs_sector_stocks SET active=0 "
            "WHERE sector_id=%s AND stock_code=%s",
            (sector_id, stock_code))

    # ═══════════════════════════════════════════
    #  스크리닝 전략 (ibs_screen_strategies)
    # ═══════════════════════════════════════════

    def get_all_screen_strategies(self) -> List[Dict]:
        rows = self._execute(
            "SELECT * FROM ibs_screen_strategies ORDER BY strategy_id")
        for r in rows:
            r["conditions"] = self._parse_json(r.get("conditions"))
            r["grouping"] = self._parse_json(r.get("grouping"))
        return rows

    def get_screen_strategy(self, strategy_id: int) -> Optional[Dict]:
        r = self._execute_one(
            "SELECT * FROM ibs_screen_strategies WHERE strategy_id = %s",
            (strategy_id,))
        if r:
            r["conditions"] = self._parse_json(r.get("conditions"))
            r["grouping"] = self._parse_json(r.get("grouping"))
        return r

    def get_active_screen_strategy(self) -> Optional[Dict]:
        r = self._execute_one(
            "SELECT * FROM ibs_screen_strategies "
            "WHERE is_active = 1 LIMIT 1")
        if r:
            r["conditions"] = self._parse_json(r.get("conditions"))
            r["grouping"] = self._parse_json(r.get("grouping"))
        return r

    def save_screen_strategy(self, name: str, conditions: list,
                             grouping: dict = None,
                             description: str = "") -> int:
        sid = self._execute_write(
            """INSERT INTO ibs_screen_strategies
               (name, description, conditions, `grouping`)
               VALUES (%s, %s, %s, %s)""",
            (name, description,
             json.dumps(conditions, ensure_ascii=False),
             json.dumps(grouping, ensure_ascii=False) if grouping else None))
        logger.info(f"[DB_STORE] 스크린전략 저장: #{sid} {name}")
        return sid

    def update_screen_strategy(self, strategy_id: int, **kwargs) -> bool:
        existing = self.get_screen_strategy(strategy_id)
        if not existing:
            return False
        if existing.get("locked"):
            logger.warning(f"[DB_STORE] 잠긴 전략은 수정 불가: #{strategy_id}")
            return False
        sets, vals = [], []
        for k, v in kwargs.items():
            if k in ("conditions", "grouping") and isinstance(v, (list, dict)):
                v = json.dumps(v, ensure_ascii=False)
            sets.append(f"`{k}` = %s")
            vals.append(v)
        vals.append(strategy_id)
        self._execute_write(
            f"UPDATE ibs_screen_strategies SET {', '.join(sets)} "
            f"WHERE strategy_id = %s", tuple(vals))
        return True

    def delete_screen_strategy(self, strategy_id: int) -> bool:
        existing = self.get_screen_strategy(strategy_id)
        if not existing:
            return False
        if existing.get("locked"):
            logger.warning(f"[DB_STORE] 잠긴 전략은 삭제 불가: #{strategy_id}")
            return False
        self._execute_write(
            "DELETE FROM ibs_screen_strategies WHERE strategy_id = %s",
            (strategy_id,))
        logger.info(f"[DB_STORE] 스크린전략 삭제: #{strategy_id}")
        return True

    def clone_screen_strategy(self, strategy_id: int,
                              new_name: str) -> Optional[int]:
        src = self.get_screen_strategy(strategy_id)
        if not src:
            return None
        return self.save_screen_strategy(
            name=new_name,
            conditions=src["conditions"],
            grouping=src.get("grouping"),
            description=f"[복제] {src.get('description', '')}")

    def set_active_screen_strategy(self, strategy_id: int):
        self._execute_write(
            "UPDATE ibs_screen_strategies SET is_active = 0")
        self._execute_write(
            "UPDATE ibs_screen_strategies SET is_active = 1 "
            "WHERE strategy_id = %s", (strategy_id,))
        logger.info(f"[DB_STORE] 활성 스크린전략 변경: #{strategy_id}")

    # ═══════════════════════════════════════════
    #  매매전략 (ibs_trade_strategies)
    # ═══════════════════════════════════════════

    def get_all_trade_strategies(self) -> List[Dict]:
        rows = self._execute(
            "SELECT * FROM ibs_trade_strategies ORDER BY strategy_id")
        for r in rows:
            r["params"] = self._parse_json(r.get("params"))
            r["buy_rules"] = self._parse_json(r.get("buy_rules"))
            r["sell_rules"] = self._parse_json(r.get("sell_rules"))
        return rows

    def get_trade_strategy(self, strategy_id: int) -> Optional[Dict]:
        r = self._execute_one(
            "SELECT * FROM ibs_trade_strategies WHERE strategy_id = %s",
            (strategy_id,))
        if r:
            r["params"] = self._parse_json(r.get("params"))
            r["buy_rules"] = self._parse_json(r.get("buy_rules"))
            r["sell_rules"] = self._parse_json(r.get("sell_rules"))
        return r

    def get_active_trade_strategy(self) -> Optional[Dict]:
        r = self._execute_one(
            "SELECT * FROM ibs_trade_strategies "
            "WHERE is_active = 1 LIMIT 1")
        if r:
            r["params"] = self._parse_json(r.get("params"))
            r["buy_rules"] = self._parse_json(r.get("buy_rules"))
            r["sell_rules"] = self._parse_json(r.get("sell_rules"))
        return r

    def save_trade_strategy(self, name: str, regime_target: str,
                            params: dict, buy_rules: dict,
                            sell_rules: dict,
                            description: str = "") -> int:
        sid = self._execute_write(
            """INSERT INTO ibs_trade_strategies
               (name, description, regime_target, params, buy_rules, sell_rules)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (name, description, regime_target,
             json.dumps(params, ensure_ascii=False),
             json.dumps(buy_rules, ensure_ascii=False),
             json.dumps(sell_rules, ensure_ascii=False)))
        logger.info(f"[DB_STORE] 매매전략 저장: #{sid} {name}")
        return sid

    def update_trade_strategy(self, strategy_id: int, **kwargs) -> bool:
        existing = self.get_trade_strategy(strategy_id)
        if not existing:
            return False
        if existing.get("locked"):
            logger.warning(f"[DB_STORE] 잠긴 전략은 수정 불가: #{strategy_id}")
            return False
        sets, vals = [], []
        for k, v in kwargs.items():
            if k in ("params", "buy_rules", "sell_rules") and isinstance(v, (dict, list)):
                v = json.dumps(v, ensure_ascii=False)
            sets.append(f"`{k}` = %s")
            vals.append(v)
        vals.append(strategy_id)
        self._execute_write(
            f"UPDATE ibs_trade_strategies SET {', '.join(sets)} "
            f"WHERE strategy_id = %s", tuple(vals))
        return True

    def delete_trade_strategy(self, strategy_id: int) -> bool:
        existing = self.get_trade_strategy(strategy_id)
        if not existing:
            return False
        if existing.get("locked"):
            logger.warning(f"[DB_STORE] 잠긴 전략은 삭제 불가: #{strategy_id}")
            return False
        self._execute_write(
            "DELETE FROM ibs_trade_strategies WHERE strategy_id = %s",
            (strategy_id,))
        return True

    def clone_trade_strategy(self, strategy_id: int,
                             new_name: str) -> Optional[int]:
        src = self.get_trade_strategy(strategy_id)
        if not src:
            return None
        return self.save_trade_strategy(
            name=new_name,
            regime_target=src.get("regime_target", "BULL"),
            params=src["params"],
            buy_rules=src["buy_rules"],
            sell_rules=src["sell_rules"],
            description=f"[복제] {src.get('description', '')}")

    def set_active_trade_strategy(self, strategy_id: int):
        self._execute_write(
            "UPDATE ibs_trade_strategies SET is_active = 0")
        self._execute_write(
            "UPDATE ibs_trade_strategies SET is_active = 1 "
            "WHERE strategy_id = %s", (strategy_id,))

    # ═══════════════════════════════════════════
    #  백테스트 결과 (ibs_backtest_results)
    # ═══════════════════════════════════════════

    def save_backtest_result(self, strategy_type: str, strategy_id: int,
                             period_start, period_end,
                             avg_return: float, win_rate: float,
                             max_drawdown: float, sharpe_ratio: float,
                             stocks_tested: int,
                             details: dict = None) -> int:
        return self._execute_write(
            """INSERT INTO ibs_backtest_results
               (strategy_type, strategy_id, period_start, period_end,
                avg_return, win_rate, max_drawdown, sharpe_ratio,
                stocks_tested, details)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (strategy_type, strategy_id, period_start, period_end,
             avg_return, win_rate, max_drawdown, sharpe_ratio,
             stocks_tested,
             json.dumps(details, ensure_ascii=False, default=str)
             if details else None))

    def get_backtest_history(self, strategy_type: str,
                             strategy_id: int,
                             limit: int = 10) -> List[Dict]:
        rows = self._execute(
            """SELECT * FROM ibs_backtest_results
               WHERE strategy_type = %s AND strategy_id = %s
               ORDER BY run_at DESC LIMIT %s""",
            (strategy_type, strategy_id, limit))
        for r in rows:
            r["details"] = self._parse_json(r.get("details"))
        return rows

    # ── 유틸 ──

    @staticmethod
    def _parse_json(val) -> Any:
        if val is None:
            return None
        if isinstance(val, (dict, list)):
            return val
        if isinstance(val, str):
            try:
                return json.loads(val)
            except (json.JSONDecodeError, TypeError):
                return val
        return val
