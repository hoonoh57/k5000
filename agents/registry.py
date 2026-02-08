# -*- coding: utf-8 -*-
"""
에이전트 등록소
agents/ 폴더의 에이전트를 자동 등록하고,
지표 이름으로 해당 에이전트를 찾을 수 있게 한다.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from agents.base import IAgent
from agents.sector_agent import SectorAgent
from agents.momentum_agent import MomentumAgent

logger = logging.getLogger(__name__)


class AgentRegistry:
    """에이전트 등록소 — 싱글턴 패턴"""

    _instance: Optional["AgentRegistry"] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._agents: Dict[str, IAgent] = {}
            cls._instance._indicator_map: Dict[str, str] = {}
            cls._instance._initialized = False
        return cls._instance

    def initialize(self, **agent_kwargs):
        """기본 에이전트 등록"""
        if self._initialized:
            return

        # 기본 에이전트 등록
        self.register(SectorAgent(**agent_kwargs.get("sector", {})))
        self.register(MomentumAgent())

        self._initialized = True
        logger.info(f"[AGENT_REGISTRY] 초기화 완료: "
                     f"{len(self._agents)}개 에이전트, "
                     f"{len(self._indicator_map)}개 지표")

    def register(self, agent: IAgent):
        """에이전트 등록"""
        self._agents[agent.name] = agent
        for indicator in agent.provided_indicators:
            self._indicator_map[indicator] = agent.name
        logger.info(f"[AGENT_REGISTRY] 등록: {agent.name} "
                     f"({len(agent.provided_indicators)}개 지표)")

    def get_agent(self, name: str) -> Optional[IAgent]:
        return self._agents.get(name)

    def get_agent_for_indicator(self, indicator: str) -> Optional[IAgent]:
        """지표 이름으로 담당 에이전트 반환"""
        agent_name = self._indicator_map.get(indicator)
        if agent_name:
            return self._agents.get(agent_name)
        # 접두사 매칭 (예: 'sector.xxx' → sector 에이전트)
        prefix = indicator.split(".")[0] if "." in indicator else ""
        return self._agents.get(prefix)

    def get_all_indicators(self) -> List[str]:
        """등록된 모든 지표 이름 반환 (UI 드롭다운용)"""
        return sorted(self._indicator_map.keys())

    def get_all_agents(self) -> List[IAgent]:
        return list(self._agents.values())

    def describe_all(self) -> List[Dict]:
        """모든 에이전트 설명 (UI 표시용)"""
        return [a.describe() for a in self._agents.values()]
