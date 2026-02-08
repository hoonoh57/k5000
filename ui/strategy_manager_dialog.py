# -*- coding: utf-8 -*-
"""
ui/strategy_manager_dialog.py
전략 관리자 다이얼로그 — v3.0
 • 조건 그룹핑 (AND/OR/NOT)
 • CrossOver/CrossUnder 연산자
 • 강제청산 4대 규칙
 • 전략 적용 설정 팝업
 • 수식검증
"""
from __future__ import annotations

import json
import logging
from typing import Optional, List, Dict, Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
    QWidget, QGroupBox, QFormLayout, QLineEdit, QTextEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QComboBox, QDoubleSpinBox, QSpinBox, QCheckBox,
    QMessageBox, QAbstractItemView, QLabel, QSplitter,
    QScrollArea, QFrame, QSizePolicy,
)
from PyQt6.QtGui import QFont, QColor

from core.db_strategy_store import DBStrategyStore

logger = logging.getLogger(__name__)

# ── 사용 가능한 지표 / 연산자 ──
AVAILABLE_INDICATORS = [
    "st_dir", "jma_slope", "jma_slope_prev", "rsi",
    "close", "high", "low", "open", "volume", "atr",
    "volume_ratio_5d", "ibs_score", "market_cap_rank",
    "momentum.return_20d", "momentum.vs_kospi_ratio",
    "momentum.relative_strength",
    "sector.is_leader", "sector.is_follower", "sector.sector_id",
    "macd", "macd_signal", "bb_upper", "bb_lower",
    "stochastic_k", "stochastic_d", "cci", "roc",
]

OPERATORS = [
    "==", "!=", ">", ">=", "<", "<=",
    "CrossOver", "CrossUnder", "change_to", "in",
]

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  조건 그룹 위젯
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class ConditionRowWidget(QWidget):
    """단일 조건 행: [NOT] [지표] [연산자] [값] [삭제]"""
    delete_requested = pyqtSignal(object)

    def __init__(self, indicator="", op=">=", value="",
                 negated=False, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)

        self.chk_not = QCheckBox("NOT")
        self.chk_not.setChecked(negated)
        self.chk_not.setFixedWidth(50)
        layout.addWidget(self.chk_not)

        self.combo_indicator = QComboBox()
        self.combo_indicator.addItems(AVAILABLE_INDICATORS)
        self.combo_indicator.setEditable(True)
        self.combo_indicator.setMinimumWidth(160)
        if indicator:
            self.combo_indicator.setCurrentText(indicator)
        layout.addWidget(self.combo_indicator, 2)

        self.combo_op = QComboBox()
        self.combo_op.addItems(OPERATORS)
        self.combo_op.setMinimumWidth(100)
        if op:
            self.combo_op.setCurrentText(op)
        layout.addWidget(self.combo_op, 1)

        self.edit_value = QLineEdit(str(value))
        self.edit_value.setMinimumWidth(80)
        layout.addWidget(self.edit_value, 1)

        btn_del = QPushButton("✕")
        btn_del.setFixedWidth(28)
        btn_del.setStyleSheet("color: red; font-weight: bold;")
        btn_del.clicked.connect(lambda: self.delete_requested.emit(self))
        layout.addWidget(btn_del)

    def to_dict(self) -> Dict[str, Any]:
        val_str = self.edit_value.text().strip()
        try:
            value = float(val_str)
            if value == int(value):
                value = int(value)
        except ValueError:
            if val_str.lower() == "true":
                value = True
            elif val_str.lower() == "false":
                value = False
            else:
                value = val_str

        d = {
            "indicator": self.combo_indicator.currentText().strip(),
            "op": self.combo_op.currentText().strip(),
            "value": value,
        }
        if self.chk_not.isChecked():
            d["negated"] = True
        return d

    @staticmethod
    def from_dict(rule: dict) -> "ConditionRowWidget":
        return ConditionRowWidget(
            indicator=rule.get("indicator", ""),
            op=rule.get("op", ">="),
            value=str(rule.get("value", "")),
            negated=rule.get("negated", False),
        )


class ConditionGroupWidget(QFrame):
    """조건 그룹: 내부 로직(AND/OR) + 조건 행들"""
    delete_requested = pyqtSignal(object)

    def __init__(self, logic="AND", rules=None, parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        self.setStyleSheet(
            "ConditionGroupWidget { border: 1px solid #888; "
            "border-radius: 4px; margin: 2px; padding: 4px; }")

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(6, 6, 6, 6)
        self._layout.setSpacing(2)

        # 그룹 헤더
        header = QHBoxLayout()
        header.addWidget(QLabel("그룹 내 로직:"))
        self.combo_logic = QComboBox()
        self.combo_logic.addItems(["AND", "OR"])
        self.combo_logic.setCurrentText(logic)
        self.combo_logic.setFixedWidth(70)
        header.addWidget(self.combo_logic)
        header.addStretch()

        btn_add = QPushButton("+ 조건")
        btn_add.setFixedWidth(70)
        btn_add.clicked.connect(lambda: self.add_condition_row())
        header.addWidget(btn_add)

        btn_del_group = QPushButton("그룹 삭제")
        btn_del_group.setFixedWidth(75)
        btn_del_group.setStyleSheet("color: red;")
        btn_del_group.clicked.connect(
            lambda: self.delete_requested.emit(self))
        header.addWidget(btn_del_group)
        self._layout.addLayout(header)

        # 조건 행 컨테이너
        self._rows_layout = QVBoxLayout()
        self._rows_layout.setSpacing(1)
        self._layout.addLayout(self._rows_layout)

        self._rows: List[ConditionRowWidget] = []
        if rules:
            for r in rules:
                self.add_condition_row(
                    indicator=r.get("indicator", ""),
                    op=r.get("op", ">="),
                    value=str(r.get("value", "")),
                    negated=r.get("negated", False),
                )

    def add_condition_row(self, indicator="", op=">=",
                          value="", negated=False):
        row = ConditionRowWidget(indicator, op, value, negated)
        row.delete_requested.connect(self._remove_condition_row)
        self._rows.append(row)
        self._rows_layout.addWidget(row)

    def _remove_condition_row(self, row_widget):
        if row_widget in self._rows:
            self._rows.remove(row_widget)
            self._rows_layout.removeWidget(row_widget)
            row_widget.deleteLater()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "logic": self.combo_logic.currentText(),
            "rules": [r.to_dict() for r in self._rows
                       if r.to_dict()["indicator"]],
        }

    def validate(self) -> List[str]:
        """검증: 오류 메시지 리스트 반환 (비어있으면 통과)"""
        errors = []
        if not self._rows:
            errors.append("빈 그룹이 있습니다.")
        for i, row in enumerate(self._rows):
            d = row.to_dict()
            if not d["indicator"]:
                errors.append(f"그룹 내 {i+1}번째 조건: 지표가 비어 있습니다.")
            if d["op"] in ("CrossOver", "CrossUnder"):
                if not isinstance(d["value"], str) or not d["value"]:
                    # CrossOver/CrossUnder의 value는 비교 대상 지표명이어야 함
                    try:
                        float(d["value"])
                        # 숫자도 허용 (0선 돌파 등)
                    except (ValueError, TypeError):
                        if not d["value"]:
                            errors.append(
                                f"그룹 내 {i+1}번째: CrossOver/CrossUnder의 "
                                f"비교값이 필요합니다.")
        return errors


class ConditionEditorWidget(QWidget):
    """전체 조건 편집기: 그룹간 로직 + 그룹들"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(0, 0, 0, 0)

        # 그룹 간 로직
        top = QHBoxLayout()
        top.addWidget(QLabel("그룹 간 로직:"))
        self.combo_inter_logic = QComboBox()
        self.combo_inter_logic.addItems(["OR", "AND"])
        self.combo_inter_logic.setFixedWidth(70)
        top.addWidget(self.combo_inter_logic)
        top.addStretch()

        btn_add_group = QPushButton("+ 그룹 추가")
        btn_add_group.clicked.connect(lambda: self.add_group())
        top.addWidget(btn_add_group)

        btn_validate = QPushButton("✔ 수식검증")
        btn_validate.setStyleSheet(
            "font-weight: bold; color: green; padding: 3px 10px;")
        btn_validate.clicked.connect(self._on_validate)
        top.addWidget(btn_validate)
        self._main_layout.addLayout(top)

        # 스크롤 영역
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(120)
        scroll_widget = QWidget()
        self._groups_layout = QVBoxLayout(scroll_widget)
        self._groups_layout.setSpacing(4)
        self._groups_layout.addStretch()
        scroll.setWidget(scroll_widget)
        self._main_layout.addWidget(scroll)

        self._groups: List[ConditionGroupWidget] = []

    def add_group(self, logic="AND", rules=None):
        group = ConditionGroupWidget(logic, rules)
        group.delete_requested.connect(self._remove_group)
        self._groups.append(group)
        # stretch 전에 삽입
        idx = self._groups_layout.count() - 1
        self._groups_layout.insertWidget(idx, group)
        if not rules:
            group.add_condition_row()  # 빈 행 하나 기본 추가

    def _remove_group(self, group_widget):
        if group_widget in self._groups:
            self._groups.remove(group_widget)
            self._groups_layout.removeWidget(group_widget)
            group_widget.deleteLater()

    def to_dict(self) -> Dict[str, Any]:
        """
        반환 형태:
        {
          "logic": "OR",
          "groups": [
            {"logic": "AND", "rules": [...]},
            {"logic": "AND", "rules": [...]}
          ]
        }
        """
        groups = [g.to_dict() for g in self._groups]
        # 그룹이 1개이고 규칙도 단순하면 단순화
        if len(groups) == 1 and len(groups[0].get("rules", [])) > 0:
            return groups[0]
        return {
            "logic": self.combo_inter_logic.currentText(),
            "groups": groups,
        }

    def from_dict(self, data):
        """JSON → UI 복원"""
        # 기존 그룹 제거
        for g in list(self._groups):
            self._remove_group(g)

        if not data:
            return

        # 하위 호환: 이전 형태 (flat list)
        if isinstance(data, list):
            self.add_group("AND", data)
            return

        # 단일 그룹 형태 {"logic": "AND", "rules": [...]}
        if "rules" in data and "groups" not in data:
            logic = data.get("logic", "AND")
            self.add_group(logic, data.get("rules", []))
            return

        # 다중 그룹 형태
        self.combo_inter_logic.setCurrentText(data.get("logic", "OR"))
        for grp in data.get("groups", []):
            self.add_group(
                grp.get("logic", "AND"),
                grp.get("rules", []))

    def validate(self) -> List[str]:
        errors = []
        if not self._groups:
            errors.append("조건이 없습니다. 최소 1개 그룹이 필요합니다.")
        for i, g in enumerate(self._groups):
            for err in g.validate():
                errors.append(f"[그룹 {i+1}] {err}")
        return errors

    def _on_validate(self):
        errors = self.validate()
        if errors:
            QMessageBox.warning(
                self, "수식검증 실패",
                "다음 문제가 발견되었습니다:\n\n" + "\n".join(errors))
        else:
            QMessageBox.information(
                self, "수식검증 통과",
                "모든 조건이 유효합니다. ✔")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  강제청산 규칙 위젯
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class ExitRulesWidget(QGroupBox):
    """강제청산 4대 규칙 — 체크박스 + 수치"""

    def __init__(self, parent=None):
        super().__init__("강제청산 규칙", parent)
        form = QFormLayout(self)

        # 1. 최대허용손실 (Stop Loss)
        row1 = QHBoxLayout()
        self.chk_stop = QCheckBox("최대허용손실 (Stop Loss)")
        self.chk_stop.setChecked(True)
        row1.addWidget(self.chk_stop)
        self.spin_stop = QDoubleSpinBox()
        self.spin_stop.setRange(-50.0, -0.1)
        self.spin_stop.setSingleStep(0.5)
        self.spin_stop.setValue(-5.0)
        self.spin_stop.setSuffix(" %")
        row1.addWidget(self.spin_stop)
        form.addRow(row1)

        # 2. 목표수익 (Take Profit)
        row2 = QHBoxLayout()
        self.chk_target = QCheckBox("목표수익 (Take Profit)")
        self.chk_target.setChecked(True)
        row2.addWidget(self.chk_target)
        self.spin_target = QDoubleSpinBox()
        self.spin_target.setRange(0.1, 100.0)
        self.spin_target.setSingleStep(0.5)
        self.spin_target.setValue(15.0)
        self.spin_target.setSuffix(" %")
        row2.addWidget(self.spin_target)
        form.addRow(row2)

        # 3. 트레일링 스톱
        row3 = QHBoxLayout()
        self.chk_trailing = QCheckBox("트레일링 스톱 (최대수익 대비 하락)")
        self.chk_trailing.setChecked(False)
        row3.addWidget(self.chk_trailing)
        self.spin_trailing = QDoubleSpinBox()
        self.spin_trailing.setRange(0.1, 50.0)
        self.spin_trailing.setSingleStep(0.5)
        self.spin_trailing.setValue(3.0)
        self.spin_trailing.setSuffix(" %")
        row3.addWidget(self.spin_trailing)
        form.addRow(row3)

        # 3-1. 트레일링 활성 조건 (N% 수익 이후부터 적용)
        row3a = QHBoxLayout()
        row3a.addSpacing(30)
        row3a.addWidget(QLabel("활성 조건:"))
        self.spin_trailing_activate = QDoubleSpinBox()
        self.spin_trailing_activate.setRange(0.0, 50.0)
        self.spin_trailing_activate.setSingleStep(0.5)
        self.spin_trailing_activate.setValue(2.0)
        self.spin_trailing_activate.setSuffix(" % 수익 이후")
        row3a.addWidget(self.spin_trailing_activate)
        form.addRow(row3a)

        # 4. 무변동 청산
        row4 = QHBoxLayout()
        self.chk_stagnant = QCheckBox("무변동 청산 (횡보 탈출)")
        self.chk_stagnant.setChecked(False)
        row4.addWidget(self.chk_stagnant)
        self.spin_stagnant_bars = QSpinBox()
        self.spin_stagnant_bars.setRange(1, 100)
        self.spin_stagnant_bars.setValue(10)
        self.spin_stagnant_bars.setSuffix(" 봉 이내")
        row4.addWidget(self.spin_stagnant_bars)
        self.spin_stagnant_pct = QDoubleSpinBox()
        self.spin_stagnant_pct.setRange(0.0, 10.0)
        self.spin_stagnant_pct.setSingleStep(0.1)
        self.spin_stagnant_pct.setValue(1.0)
        self.spin_stagnant_pct.setSuffix(" % 미만 변동")
        row4.addWidget(self.spin_stagnant_pct)
        form.addRow(row4)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stop_loss": {
                "enabled": self.chk_stop.isChecked(),
                "pct": self.spin_stop.value(),
            },
            "take_profit": {
                "enabled": self.chk_target.isChecked(),
                "pct": self.spin_target.value(),
            },
            "trailing_stop": {
                "enabled": self.chk_trailing.isChecked(),
                "pct": self.spin_trailing.value(),
                "activate_after_pct": self.spin_trailing_activate.value(),
            },
            "stagnant_close": {
                "enabled": self.chk_stagnant.isChecked(),
                "bars": self.spin_stagnant_bars.value(),
                "min_move_pct": self.spin_stagnant_pct.value(),
            },
        }

    def from_dict(self, data: dict):
        if not data:
            return
        sl = data.get("stop_loss", {})
        self.chk_stop.setChecked(sl.get("enabled", True))
        self.spin_stop.setValue(sl.get("pct", -5.0))

        tp = data.get("take_profit", {})
        self.chk_target.setChecked(tp.get("enabled", True))
        self.spin_target.setValue(tp.get("pct", 15.0))

        ts = data.get("trailing_stop", {})
        self.chk_trailing.setChecked(ts.get("enabled", False))
        self.spin_trailing.setValue(ts.get("pct", 3.0))
        self.spin_trailing_activate.setValue(
            ts.get("activate_after_pct", 2.0))

        sc = data.get("stagnant_close", {})
        self.chk_stagnant.setChecked(sc.get("enabled", False))
        self.spin_stagnant_bars.setValue(sc.get("bars", 10))
        self.spin_stagnant_pct.setValue(sc.get("min_move_pct", 1.0))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  전략 적용 설정 다이얼로그 (키움 스타일)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class StrategyApplyDialog(QDialog):
    """전략 실행 전 확인/수정 팝업 — 키움 '매매전략 조건 설정' 대응"""

    def __init__(self, strategy_name: str,
                 exit_rules: dict = None,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"전략 적용 설정 — {strategy_name}")
        self.setMinimumSize(500, 450)

        layout = QVBoxLayout(self)

        # 전략 이름 표시
        title = QLabel(f"전략: {strategy_name}")
        title.setFont(QFont("맑은 고딕", 12, QFont.Weight.Bold))
        layout.addWidget(title)

        # 강제청산 규칙
        self.exit_rules_widget = ExitRulesWidget()
        if exit_rules:
            self.exit_rules_widget.from_dict(exit_rules)
        layout.addWidget(self.exit_rules_widget)

        # 알림 설정
        alert_group = QGroupBox("알림 설정")
        alert_layout = QFormLayout(alert_group)
        self.chk_beep = QCheckBox("비프음 알림")
        self.chk_beep.setChecked(True)
        alert_layout.addRow(self.chk_beep)
        self.chk_popup = QCheckBox("팝업 알림")
        self.chk_popup.setChecked(True)
        alert_layout.addRow(self.chk_popup)
        layout.addWidget(alert_group)

        # 실행 모드
        mode_group = QGroupBox("실행 모드")
        mode_layout = QHBoxLayout(mode_group)
        self.radio_backtest = QCheckBox("백테스트 (시뮬레이션)")
        self.radio_backtest.setChecked(True)
        mode_layout.addWidget(self.radio_backtest)
        self.radio_live = QCheckBox("실전매매")
        self.radio_live.setChecked(False)
        mode_layout.addWidget(self.radio_live)
        layout.addWidget(mode_group)

        # 전략 수정 연결 버튼
        btn_edit = QPushButton("전략 수정 화면 열기")
        btn_edit.clicked.connect(self._request_edit)
        layout.addWidget(btn_edit)

        # 확인/취소
        btn_row = QHBoxLayout()
        btn_ok = QPushButton("✅ 적용")
        btn_ok.setStyleSheet(
            "font-weight: bold; padding: 10px; font-size: 13px;")
        btn_ok.clicked.connect(self.accept)
        btn_row.addWidget(btn_ok)
        btn_cancel = QPushButton("취소")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)
        layout.addLayout(btn_row)

        self._edit_requested = False

    def _request_edit(self):
        self._edit_requested = True
        self.reject()

    @property
    def edit_requested(self) -> bool:
        return self._edit_requested

    def get_settings(self) -> dict:
        return {
            "exit_rules": self.exit_rules_widget.to_dict(),
            "alert_beep": self.chk_beep.isChecked(),
            "alert_popup": self.chk_popup.isChecked(),
            "mode_backtest": self.radio_backtest.isChecked(),
            "mode_live": self.radio_live.isChecked(),
        }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  메인: 전략 관리자 다이얼로그
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class StrategyManagerDialog(QDialog):
    """전략 관리자 다이얼로그 — v3.0"""

    def __init__(self, db_store: DBStrategyStore,
                 parent=None, initial_tab: str = "screen"):
        super().__init__(parent)
        self.setWindowTitle("전략 관리자 v3.0")
        self.setMinimumSize(1000, 750)
        self._db = db_store
        self._current_screen_id: Optional[int] = None
        self._current_trade_id: Optional[int] = None

        self._build_ui()

        if initial_tab == "trade":
            self.tabs.setCurrentIndex(1)

        self._refresh_screen_list()
        self._refresh_trade_list()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_screen_tab(), "스크리닝 전략")
        self.tabs.addTab(self._build_trade_tab(), "매매 전략")
        layout.addWidget(self.tabs)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  스크리닝 전략 탭
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    def _build_screen_tab(self) -> QWidget:
        tab = QWidget()
        layout = QHBoxLayout(tab)

        # 좌측: 전략 목록
        left = QVBoxLayout()
        self.screen_list = QTableWidget()
        self.screen_list.setColumnCount(3)
        self.screen_list.setHorizontalHeaderLabels(["ID", "이름", "잠금"])
        self.screen_list.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        self.screen_list.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.screen_list.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.screen_list.currentCellChanged.connect(self._on_screen_selected)
        left.addWidget(self.screen_list)

        btn_row = QHBoxLayout()
        for text, handler in [
            ("새로 만들기", self._new_screen_strategy),
            ("복제", self._clone_screen_strategy),
            ("삭제", self._delete_screen_strategy),
        ]:
            btn = QPushButton(text)
            btn.clicked.connect(handler)
            btn_row.addWidget(btn)
        left.addLayout(btn_row)

        # 우측: 편집 (스크롤 가능)
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_widget = QWidget()
        right = QVBoxLayout(right_widget)

        form = QFormLayout()
        self.screen_name_edit = QLineEdit()
        form.addRow("전략 이름:", self.screen_name_edit)
        self.screen_desc_edit = QLineEdit()
        form.addRow("설명:", self.screen_desc_edit)
        self.screen_locked_check = QCheckBox("잠금 (수정 불가)")
        form.addRow("", self.screen_locked_check)
        right.addLayout(form)

        # 조건 편집기 (그룹핑)
        right.addWidget(QLabel("조건 규칙:"))
        self.screen_cond_editor = ConditionEditorWidget()
        right.addWidget(self.screen_cond_editor)

        # 저장/활성 버튼
        save_row = QHBoxLayout()
        btn_save = QPushButton("💾 저장")
        btn_save.setStyleSheet("font-weight: bold; padding: 8px;")
        btn_save.clicked.connect(self._save_screen_strategy)
        save_row.addWidget(btn_save)
        btn_activate = QPushButton("✅ 활성화")
        btn_activate.clicked.connect(self._activate_screen_strategy)
        save_row.addWidget(btn_activate)
        right.addLayout(save_row)

        right_scroll.setWidget(right_widget)
        layout.addLayout(left, 1)
        layout.addWidget(right_scroll, 2)
        return tab

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  매매 전략 탭
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    def _build_trade_tab(self) -> QWidget:
        tab = QWidget()
        layout = QHBoxLayout(tab)

        # 좌측: 전략 목록
        left = QVBoxLayout()
        self.trade_list = QTableWidget()
        self.trade_list.setColumnCount(4)
        self.trade_list.setHorizontalHeaderLabels(
            ["ID", "이름", "레짐", "잠금"])
        self.trade_list.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        self.trade_list.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.trade_list.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.trade_list.currentCellChanged.connect(self._on_trade_selected)
        left.addWidget(self.trade_list)

        btn_row = QHBoxLayout()
        for text, handler in [
            ("새로 만들기", self._new_trade_strategy),
            ("복제", self._clone_trade_strategy),
            ("삭제", self._delete_trade_strategy),
        ]:
            btn = QPushButton(text)
            btn.clicked.connect(handler)
            btn_row.addWidget(btn)
        left.addLayout(btn_row)

        # 우측: 편집 (스크롤 가능)
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_widget = QWidget()
        right = QVBoxLayout(right_widget)

        form = QFormLayout()
        self.trade_name_edit = QLineEdit()
        form.addRow("전략 이름:", self.trade_name_edit)
        self.trade_desc_edit = QLineEdit()
        form.addRow("설명:", self.trade_desc_edit)
        self.trade_regime_combo = QComboBox()
        self.trade_regime_combo.addItems(["BULL", "BEAR", "SIDEWAYS"])
        form.addRow("대상 레짐:", self.trade_regime_combo)
        self.trade_locked_check = QCheckBox("잠금 (수정 불가)")
        form.addRow("", self.trade_locked_check)
        right.addLayout(form)

        # 파라미터
        param_group = QGroupBox("전략 파라미터")
        param_form = QFormLayout(param_group)
        self.trade_jma_len = QSpinBox()
        self.trade_jma_len.setRange(3, 50)
        self.trade_jma_len.setValue(7)
        param_form.addRow("JMA 기간:", self.trade_jma_len)
        self.trade_jma_phase = QSpinBox()
        self.trade_jma_phase.setRange(-100, 100)
        self.trade_jma_phase.setValue(50)
        param_form.addRow("JMA 위상:", self.trade_jma_phase)
        self.trade_st_period = QSpinBox()
        self.trade_st_period.setRange(5, 50)
        self.trade_st_period.setValue(14)
        param_form.addRow("ST 기간:", self.trade_st_period)
        self.trade_st_mult = QDoubleSpinBox()
        self.trade_st_mult.setRange(0.5, 5.0)
        self.trade_st_mult.setSingleStep(0.1)
        self.trade_st_mult.setValue(3.0)
        param_form.addRow("ST 배수:", self.trade_st_mult)
        self.trade_slope_min = QDoubleSpinBox()
        self.trade_slope_min.setRange(-50.0, 50.0)
        self.trade_slope_min.setSingleStep(0.1)
        self.trade_slope_min.setDecimals(2)
        self.trade_slope_min.setValue(0.0)
        param_form.addRow("JMA 기울기 (%):", self.trade_slope_min)


        param_form.addRow("JMA 기울기:", self.trade_slope_min)
        right.addWidget(param_group)

        # 강제청산 규칙 (4대 항목)
        self.exit_rules_widget = ExitRulesWidget()
        right.addWidget(self.exit_rules_widget)

        # 매수 조건 (그룹핑)
        right.addWidget(QLabel("매수 조건:"))
        self.trade_buy_editor = ConditionEditorWidget()
        self.trade_buy_editor.combo_inter_logic.setCurrentText("AND")
        right.addWidget(self.trade_buy_editor)

        # 매도 조건 (그룹핑)
        right.addWidget(QLabel("매도 조건:"))
        self.trade_sell_editor = ConditionEditorWidget()
        self.trade_sell_editor.combo_inter_logic.setCurrentText("OR")
        right.addWidget(self.trade_sell_editor)

        # 저장/활성/적용 버튼
        save_row = QHBoxLayout()
        btn_save = QPushButton("💾 저장")
        btn_save.setStyleSheet("font-weight: bold; padding: 8px;")
        btn_save.clicked.connect(self._save_trade_strategy)
        save_row.addWidget(btn_save)
        btn_activate = QPushButton("✅ 활성화")
        btn_activate.clicked.connect(self._activate_trade_strategy)
        save_row.addWidget(btn_activate)
        btn_apply = QPushButton("▶ 전략 적용")
        btn_apply.setStyleSheet(
            "font-weight: bold; padding: 8px; color: white; "
            "background-color: #2196F3;")
        btn_apply.clicked.connect(self._apply_trade_strategy)
        save_row.addWidget(btn_apply)
        right.addLayout(save_row)

        right_scroll.setWidget(right_widget)
        layout.addLayout(left, 1)
        layout.addWidget(right_scroll, 2)
        return tab

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  스크리닝 전략 CRUD
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    def _refresh_screen_list(self):
        strategies = self._db.get_all_screen_strategies()
        self.screen_list.setRowCount(len(strategies))
        for i, s in enumerate(strategies):
            self.screen_list.setItem(
                i, 0, QTableWidgetItem(str(s["strategy_id"])))
            self.screen_list.setItem(
                i, 1, QTableWidgetItem(s["name"]))
            lock_text = "🔒" if s.get("locked") else ""
            self.screen_list.setItem(i, 2, QTableWidgetItem(lock_text))

    def _on_screen_selected(self, row, col, prev_row, prev_col):
        if row < 0:
            return
        id_item = self.screen_list.item(row, 0)
        if not id_item:
            return
        sid = int(id_item.text())
        self._current_screen_id = sid
        s = self._db.get_screen_strategy(sid)
        if not s:
            return
        self.screen_name_edit.setText(s.get("name", ""))
        self.screen_desc_edit.setText(s.get("description", ""))
        self.screen_locked_check.setChecked(bool(s.get("locked")))

        conditions = s.get("conditions", {})
        self.screen_cond_editor.from_dict(conditions)

    def _new_screen_strategy(self):
        self._current_screen_id = None
        self.screen_name_edit.setText("새 스크린 전략")
        self.screen_desc_edit.setText("")
        self.screen_locked_check.setChecked(False)
        self.screen_cond_editor.from_dict(None)

    def _save_screen_strategy(self):
        name = self.screen_name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "알림", "전략 이름을 입력하세요.")
            return

        # 수식검증
        errors = self.screen_cond_editor.validate()
        if errors:
            QMessageBox.warning(
                self, "수식검증 실패",
                "조건식에 문제가 있습니다:\n\n" + "\n".join(errors))
            return

        conditions = self.screen_cond_editor.to_dict()
        desc = self.screen_desc_edit.text().strip()

        try:
            if self._current_screen_id:
                ok = self._db.update_screen_strategy(
                    self._current_screen_id,
                    name=name, description=desc,
                    conditions=conditions,
                    locked=int(self.screen_locked_check.isChecked()),
                )
                if not ok:
                    QMessageBox.warning(
                        self, "알림",
                        "저장 실패 — 잠긴 전략은 수정할 수 없습니다.\n"
                        "복제 후 수정하세요.")
                    return
            else:
                self._current_screen_id = self._db.save_screen_strategy(
                    name=name, conditions=conditions, description=desc)

            self._refresh_screen_list()
            QMessageBox.information(self, "완료", f"'{name}' 저장 완료")
        except Exception as e:
            QMessageBox.critical(self, "오류", str(e))

    def _clone_screen_strategy(self):
        if not self._current_screen_id:
            QMessageBox.warning(self, "알림", "복제할 전략을 선택하세요.")
            return
        new_name = self.screen_name_edit.text().strip() + " (복사)"
        new_id = self._db.clone_screen_strategy(
            self._current_screen_id, new_name)
        if new_id:
            self._current_screen_id = new_id
            self._refresh_screen_list()

    def _delete_screen_strategy(self):
        if not self._current_screen_id:
            return
        reply = QMessageBox.question(
            self, "확인", "정말 삭제하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            ok = self._db.delete_screen_strategy(self._current_screen_id)
            if not ok:
                QMessageBox.warning(
                    self, "알림",
                    "삭제 실패 — 잠긴 전략은 삭제할 수 없습니다.")
            else:
                self._current_screen_id = None
                self._refresh_screen_list()

    def _activate_screen_strategy(self):
        if self._current_screen_id:
            self._db.set_active_screen_strategy(self._current_screen_id)
            QMessageBox.information(
                self, "완료", "활성 스크린전략이 변경되었습니다.")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  매매 전략 CRUD
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    def _refresh_trade_list(self):
        strategies = self._db.get_all_trade_strategies()
        self.trade_list.setRowCount(len(strategies))
        for i, s in enumerate(strategies):
            self.trade_list.setItem(
                i, 0, QTableWidgetItem(str(s["strategy_id"])))
            self.trade_list.setItem(
                i, 1, QTableWidgetItem(s["name"]))
            self.trade_list.setItem(
                i, 2, QTableWidgetItem(s.get("regime_target", "")))
            lock_text = "🔒" if s.get("locked") else ""
            self.trade_list.setItem(i, 3, QTableWidgetItem(lock_text))

    def _on_trade_selected(self, row, col, prev_row, prev_col):
        if row < 0:
            return
        id_item = self.trade_list.item(row, 0)
        if not id_item:
            return
        sid = int(id_item.text())
        self._current_trade_id = sid
        s = self._db.get_trade_strategy(sid)
        if not s:
            return

        self.trade_name_edit.setText(s.get("name", ""))
        self.trade_desc_edit.setText(s.get("description", ""))
        self.trade_locked_check.setChecked(bool(s.get("locked")))

        regime = s.get("regime_target", "BULL")
        idx = self.trade_regime_combo.findText(regime)
        if idx >= 0:
            self.trade_regime_combo.setCurrentIndex(idx)

        # 파라미터
        p = s.get("params", {}) or {}
        self.trade_jma_len.setValue(int(p.get("jma_length", 7)))
        self.trade_jma_phase.setValue(int(p.get("jma_phase", 50)))
        self.trade_st_period.setValue(int(p.get("st_period", 14)))
        self.trade_st_mult.setValue(float(p.get("st_multiplier", 3.0)))
        self.trade_slope_min.setValue(float(p.get("jma_slope_min", 0.0)))

        # 강제청산 규칙
        exit_rules = p.get("exit_rules", {})
        if exit_rules:
            self.exit_rules_widget.from_dict(exit_rules)
        else:
            # 이전 형태 호환: target_pct, stop_pct를 변환
            self.exit_rules_widget.from_dict({
                "stop_loss": {
                    "enabled": True,
                    "pct": float(p.get("stop_pct", -0.05)) * 100,
                },
                "take_profit": {
                    "enabled": True,
                    "pct": float(p.get("target_pct", 0.15)) * 100,
                },
            })

        # 매수/매도 조건
        buy_rules = s.get("buy_rules", {})
        self.trade_buy_editor.from_dict(buy_rules)

        sell_rules = s.get("sell_rules", {})
        self.trade_sell_editor.from_dict(sell_rules)

    def _new_trade_strategy(self):
        self._current_trade_id = None
        self.trade_name_edit.setText("새 매매 전략")
        self.trade_desc_edit.setText("")
        self.trade_locked_check.setChecked(False)
        self.trade_buy_editor.from_dict(None)
        self.trade_sell_editor.from_dict(None)
        self.exit_rules_widget.from_dict({})

    def _save_trade_strategy(self):
        name = self.trade_name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "알림", "전략 이름을 입력하세요.")
            return

        # 수식검증
        buy_errors = self.trade_buy_editor.validate()
        sell_errors = self.trade_sell_editor.validate()
        all_errors = (
            [f"[매수] {e}" for e in buy_errors] +
            [f"[매도] {e}" for e in sell_errors]
        )
        if all_errors:
            QMessageBox.warning(
                self, "수식검증 실패",
                "조건식에 문제가 있습니다:\n\n" + "\n".join(all_errors))
            return

        params = {
            "jma_length": self.trade_jma_len.value(),
            "jma_phase": self.trade_jma_phase.value(),
            "st_period": self.trade_st_period.value(),
            "st_multiplier": self.trade_st_mult.value(),
            "jma_slope_min": self.trade_slope_min.value(),
            "exit_rules": self.exit_rules_widget.to_dict(),
        }
        buy_rules = self.trade_buy_editor.to_dict()
        sell_rules = self.trade_sell_editor.to_dict()
        regime = self.trade_regime_combo.currentText()
        desc = self.trade_desc_edit.text().strip()

        try:
            if self._current_trade_id:
                ok = self._db.update_trade_strategy(
                    self._current_trade_id,
                    name=name, description=desc,
                    regime_target=regime,
                    params=params,
                    buy_rules=buy_rules,
                    sell_rules=sell_rules,
                    locked=int(self.trade_locked_check.isChecked()),
                )
                if not ok:
                    QMessageBox.warning(
                        self, "알림",
                        "저장 실패 — 잠긴 전략은 수정할 수 없습니다.\n"
                        "복제 후 수정하세요.")
                    return
            else:
                self._current_trade_id = self._db.save_trade_strategy(
                    name=name, regime_target=regime,
                    params=params, buy_rules=buy_rules,
                    sell_rules=sell_rules, description=desc)

            self._refresh_trade_list()
            QMessageBox.information(self, "완료", f"'{name}' 저장 완료")
        except Exception as e:
            QMessageBox.critical(self, "오류", str(e))

    def _clone_trade_strategy(self):
        if not self._current_trade_id:
            QMessageBox.warning(self, "알림", "복제할 전략을 선택하세요.")
            return
        new_name = self.trade_name_edit.text().strip() + " (복사)"
        new_id = self._db.clone_trade_strategy(
            self._current_trade_id, new_name)
        if new_id:
            self._current_trade_id = new_id
            self._refresh_trade_list()

    def _delete_trade_strategy(self):
        if not self._current_trade_id:
            return
        reply = QMessageBox.question(
            self, "확인", "정말 삭제하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            ok = self._db.delete_trade_strategy(self._current_trade_id)
            if not ok:
                QMessageBox.warning(
                    self, "알림",
                    "삭제 실패 — 잠긴 전략은 삭제할 수 없습니다.")
            else:
                self._current_trade_id = None
                self._refresh_trade_list()

    def _activate_trade_strategy(self):
        if self._current_trade_id:
            self._db.set_active_trade_strategy(self._current_trade_id)
            QMessageBox.information(
                self, "완료", "활성 매매전략이 변경되었습니다.")

    def _apply_trade_strategy(self):
        """▶ 전략 적용 버튼 — 키움 스타일 설정 팝업 후 실행"""
        if not self._current_trade_id:
            QMessageBox.warning(self, "알림", "적용할 전략을 선택하세요.")
            return

        name = self.trade_name_edit.text().strip()
        exit_rules = self.exit_rules_widget.to_dict()

        dlg = StrategyApplyDialog(name, exit_rules, parent=self)
        result = dlg.exec()

        if dlg.edit_requested:
            # 전략 수정 화면으로 돌아감 (이미 열려 있으므로 포커스만)
            self.tabs.setCurrentIndex(1)
            return

        if result == QDialog.DialogCode.Accepted:
            settings = dlg.get_settings()
            logger.info(f"전략 적용: {name}, 설정={settings}")
            QMessageBox.information(
                self, "전략 적용",
                f"'{name}' 전략이 다음 설정으로 적용됩니다:\n\n"
                f"손절: {settings['exit_rules']['stop_loss']}\n"
                f"익절: {settings['exit_rules']['take_profit']}\n"
                f"트레일링: {settings['exit_rules']['trailing_stop']}\n"
                f"무변동청산: {settings['exit_rules']['stagnant_close']}\n\n"
                f"모드: {'백테스트' if settings['mode_backtest'] else '실전매매'}")
