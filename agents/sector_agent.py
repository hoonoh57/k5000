# -*- coding: utf-8 -*-
"""
섹터 전문가 에이전트
DB(ibs_sectors, ibs_sector_stocks)에서 섹터 분류를 읽어
종목별 섹터 정보 + 대장주/추종주 태그를 부여한다.
"""
from __future__ import annotations

import logging
from typing import Dict, List

import pandas as pd

from agents.base import IAgent
from core.db_strategy_store import DBStrategyStore

logger = logging.getLogger(__name__)


class SectorAgent(IAgent):
    """DB 기반 섹터 분류 에이전트"""

    def __init__(self, store: DBStrategyStore = None):
        self._store = store or DBStrategyStore()
        self._cache: Dict = {}

    @property
    def name(self) -> str:
        return "sector"

    @property
    def provided_indicators(self) -> List[str]:
        return [
            "sector.sector_id",
            "sector.sector_name",
            "sector.role",           # 'leader', 'follower', 'candidate', ''
            "sector.is_leader",      # True/False
            "sector.is_follower",    # True/False
            "sector.priority",       # 섹터 내 순위
        ]

    def _load_mapping(self) -> Dict[str, Dict]:
        """DB에서 종목→섹터 매핑을 로드하여 캐시"""
        if self._cache:
            return self._cache

        rows = self._store.get_all_sector_stocks(active_only=True)
        mapping = {}
        for r in rows:
            code = r["stock_code"]
            # 종목이 여러 섹터에 속할 수 있으므로 priority가 높은(작은) 것 우선
            if code not in mapping or r["priority"] < mapping[code]["priority"]:
                mapping[code] = {
                    "sector_id": r["sector_id"],
                    "sector_name": r.get("sector_name", ""),
                    "role": r["role"],
                    "priority": r["priority"],
                }
        self._cache = mapping
        logger.info(f"[SECTOR_AGENT] 매핑 로드: {len(mapping)}종목, "
                     f"{len(set(m['sector_id'] for m in mapping.values()))}섹터")
        return mapping

    def refresh(self):
        """캐시 무효화 — 섹터 변경 후 호출"""
        self._cache.clear()
        logger.info("[SECTOR_AGENT] 캐시 초기화")

    def compute(self, universe_df: pd.DataFrame,
                market_df: pd.DataFrame = None,
                **kwargs) -> pd.DataFrame:
        """종목 DataFrame에 섹터 정보 컬럼을 추가"""
        mapping = self._load_mapping()

        # code 컬럼 확인
        if "code" not in universe_df.columns:
            logger.warning("[SECTOR_AGENT] 'code' 컬럼 없음")
            return universe_df

        df = universe_df.copy()

        sector_ids, sector_names, roles = [], [], []
        is_leaders, is_followers, priorities = [], [], []

        for _, row in df.iterrows():
            code = str(row["code"]).strip()
            info = mapping.get(code, {})

            sector_ids.append(info.get("sector_id", ""))
            sector_names.append(info.get("sector_name", ""))
            role = info.get("role", "")
            roles.append(role)
            is_leaders.append(role == "leader")
            is_followers.append(role == "follower")
            priorities.append(info.get("priority", 999))

        df["sector.sector_id"] = sector_ids
        df["sector.sector_name"] = sector_names
        df["sector.role"] = roles
        df["sector.is_leader"] = is_leaders
        df["sector.is_follower"] = is_followers
        df["sector.priority"] = priorities

        assigned = sum(1 for s in sector_ids if s)
        logger.info(f"[SECTOR_AGENT] {len(df)}종목 중 {assigned}종목 섹터 매핑 완료")
        return df

    def get_sector_summary(self) -> List[Dict]:
        """UI 표시용: 활성 섹터 목록 + 각 섹터의 종목 수"""
        sectors = self._store.get_all_sectors(active_only=True)
        result = []
        for s in sectors:
            stocks = self._store.get_sector_stocks(s["sector_id"])
            leaders = [st for st in stocks if st["role"] == "leader"]
            followers = [st for st in stocks if st["role"] == "follower"]
            result.append({
                "sector_id": s["sector_id"],
                "sector_name": s["sector_name"],
                "total": len(stocks),
                "leaders": len(leaders),
                "followers": len(followers),
                "leader_names": [st["stock_name"] for st in leaders],
                "active": s["active"],
            })
        return result
