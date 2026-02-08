# -*- coding: utf-8 -*-
"""Expert Agent 공통 인터페이스"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List

import pandas as pd


class IAgent(ABC):
    """모든 에이전트의 기반 클래스"""

    @property
    @abstractmethod
    def name(self) -> str:
        """에이전트 고유 이름 (예: 'sector', 'momentum')"""
        ...

    @property
    @abstractmethod
    def provided_indicators(self) -> List[str]:
        """이 에이전트가 제공하는 파생지표 목록
        예: ['sector.sector_id', 'sector.is_leader', ...]
        """
        ...

    @abstractmethod
    def compute(self, universe_df: pd.DataFrame,
                market_df: pd.DataFrame = None,
                **kwargs) -> pd.DataFrame:
        """universe_df에 파생지표 컬럼을 추가하여 반환
        Args:
            universe_df: 종목별 가격/지표 데이터
            market_df:   KOSPI 등 시장 지수 데이터 (필요 시)
        Returns:
            파생지표 컬럼이 추가된 DataFrame
        """
        ...

    def describe(self) -> Dict:
        """에이전트 설명 (UI 표시용)"""
        return {
            "name": self.name,
            "indicators": self.provided_indicators,
            "doc": self.__class__.__doc__ or "",
        }
