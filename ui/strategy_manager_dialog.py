# -*- coding: utf-8 -*-
"""
ui/strategy_manager_dialog.py
전략 관리자 다이얼로그 — 스크리닝/매매 전략 CRUD + 조건 편집
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
    QWidget, QGroupBox, QFormLayout, QLineEdit, QTextEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QComboBox, QDoubleSpinBox, QSpinBox, QCheckBox,
    QMessageBox, QAbstractItemView, QLabel, QSplitter,
)
from PyQt6.QtGui import QFont, QColor

from core.db_strategy_store import DBStrategyStore

logger = logging.getLogger(__name__)

# 사용 가능한 지표 목록 (향후 에이전트 지표 추가 가능)
AVAILABLE_INDICATORS = [
    "st_dir", "jma_slope", "jma_slope_prev", "rsi",
    "close", "high", "low", "volume", "atr",
    "volume_ratio_5d", "ibs_score", "market_cap_rank",
    "momentum.vs_kospi_ratio", "momentum.relative_strength",
    "sector.is_leader", "sector.is_follower", "sector.sector_id",
]

OPERATORS = ["==", "!=", ">", ">=", "<", "<=", "in", "change_to"]
LOGIC_OPTIONS = ["AND", "OR"]


class StrategyManagerDialog(QDialog):
    """전략 관리자 다이얼로그"""

    def __init__(self, db_store: DBStrategyStore,
                 parent=None, initial_tab: str = "screen"):
        super().__init__(parent)
        self.setWindowTitle("전략 관리자")
        self.setMinimumSize(900, 650)
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

        # ── 탭 1: 스크리닝 전략 ──
        self.tabs.addTab(self._build_screen_tab(), "스크리닝 전략")

        # ── 탭 2: 매매 전략 ──
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
        btn_new = QPushButton("새로 만들기")
        btn_new.clicked.connect(self._new_screen_strategy)
        btn_row.addWidget(btn_new)
        btn_clone = QPushButton("복제")
        btn_clone.clicked.connect(self._clone_screen_strategy)
        btn_row.addWidget(btn_clone)
        btn_del = QPushButton("삭제")
        btn_del.clicked.connect(self._delete_screen_strategy)
        btn_row.addWidget(btn_del)
        left.addLayout(btn_row)

        # 우측: 편집
        right = QVBoxLayout()

        form = QFormLayout()
        self.screen_name_edit = QLineEdit()
        form.addRow("전략 이름:", self.screen_name_edit)
        self.screen_desc_edit = QLineEdit()
        form.addRow("설명:", self.screen_desc_edit)
        self.screen_locked_check = QCheckBox("잠금 (수정 불가)")
        form.addRow("", self.screen_locked_check)
        right.addLayout(form)

        # 조건 테이블
        right.addWidget(QLabel("조건 규칙:"))
        self.screen_cond_table = QTableWidget()
        self.screen_cond_table.setColumnCount(4)
        self.screen_cond_table.setHorizontalHeaderLabels(
            ["지표", "연산자", "값", "삭제"])
        self.screen_cond_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        right.addWidget(self.screen_cond_table)

        cond_btn_row = QHBoxLayout()
        btn_add_cond = QPushButton("+ 조건 추가")
        btn_add_cond.clicked.connect(
            lambda: self._add_condition_row(self.screen_cond_table))
        cond_btn_row.addWidget(btn_add_cond)
        right.addLayout(cond_btn_row)

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

        layout.addLayout(left, 1)
        layout.addLayout(right, 2)
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
        btn_new = QPushButton("새로 만들기")
        btn_new.clicked.connect(self._new_trade_strategy)
        btn_row.addWidget(btn_new)
        btn_clone = QPushButton("복제")
        btn_clone.clicked.connect(self._clone_trade_strategy)
        btn_row.addWidget(btn_clone)
        btn_del = QPushButton("삭제")
        btn_del.clicked.connect(self._delete_trade_strategy)
        btn_row.addWidget(btn_del)
        left.addLayout(btn_row)

        # 우측: 편집
        right = QVBoxLayout()

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
        right.addWidget(QLabel("파라미터:"))
        param_form = QFormLayout()
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
        self.trade_target = QDoubleSpinBox()
        self.trade_target.setRange(0.01, 0.50)
        self.trade_target.setSingleStep(0.01)
        self.trade_target.setValue(0.15)
        param_form.addRow("목표수익:", self.trade_target)
        self.trade_stop = QDoubleSpinBox()
        self.trade_stop.setRange(-0.30, -0.01)
        self.trade_stop.setSingleStep(0.01)
        self.trade_stop.setValue(-0.05)
        param_form.addRow("손절률:", self.trade_stop)
        self.trade_slope_min = QDoubleSpinBox()
        self.trade_slope_min.setRange(0.0, 10000.0)
        self.trade_slope_min.setSingleStep(100.0)
        self.trade_slope_min.setValue(0.0)
        param_form.addRow("JMA 기울기:", self.trade_slope_min)
        right.addLayout(param_form)

        # 매수/매도 조건
        right.addWidget(QLabel("매수 조건:"))
        self.trade_buy_table = QTableWidget()
        self.trade_buy_table.setColumnCount(4)
        self.trade_buy_table.setHorizontalHeaderLabels(
            ["지표", "연산자", "값", "삭제"])
        self.trade_buy_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        self.trade_buy_table.setMaximumHeight(120)
        right.addWidget(self.trade_buy_table)

        btn_add_buy = QPushButton("+ 매수 조건 추가")
        btn_add_buy.clicked.connect(
            lambda: self._add_condition_row(self.trade_buy_table))
        right.addWidget(btn_add_buy)

        right.addWidget(QLabel("매도 조건:"))
        self.trade_sell_table = QTableWidget()
        self.trade_sell_table.setColumnCount(4)
        self.trade_sell_table.setHorizontalHeaderLabels(
            ["지표", "연산자", "값", "삭제"])
        self.trade_sell_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        self.trade_sell_table.setMaximumHeight(120)
        right.addWidget(self.trade_sell_table)

        btn_add_sell = QPushButton("+ 매도 조건 추가")
        btn_add_sell.clicked.connect(
            lambda: self._add_condition_row(self.trade_sell_table))
        right.addWidget(btn_add_sell)

        # 저장/활성 버튼
        save_row = QHBoxLayout()
        btn_save = QPushButton("💾 저장")
        btn_save.setStyleSheet("font-weight: bold; padding: 8px;")
        btn_save.clicked.connect(self._save_trade_strategy)
        save_row.addWidget(btn_save)
        btn_activate = QPushButton("✅ 활성화")
        btn_activate.clicked.connect(self._activate_trade_strategy)
        save_row.addWidget(btn_activate)
        right.addLayout(save_row)

        layout.addLayout(left, 1)
        layout.addLayout(right, 2)
        return tab

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  공통: 조건 행 추가
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    def _add_condition_row(self, table: QTableWidget,
                           indicator="", op=">=", value=""):
        row = table.rowCount()
        table.insertRow(row)

        combo_ind = QComboBox()
        combo_ind.addItems(AVAILABLE_INDICATORS)
        combo_ind.setEditable(True)
        if indicator:
            combo_ind.setCurrentText(indicator)
        table.setCellWidget(row, 0, combo_ind)

        combo_op = QComboBox()
        combo_op.addItems(OPERATORS)
        if op:
            combo_op.setCurrentText(op)
        table.setCellWidget(row, 1, combo_op)

        val_edit = QLineEdit(str(value))
        table.setCellWidget(row, 2, val_edit)

        btn_del = QPushButton("✕")
        btn_del.setFixedWidth(30)
        btn_del.clicked.connect(lambda: table.removeRow(
            table.indexAt(btn_del.pos()).row()))
        table.setCellWidget(row, 3, btn_del)

    def _read_conditions(self, table: QTableWidget) -> list:
        """테이블에서 조건 규칙을 읽어 리스트로 반환"""
        rules = []
        for row in range(table.rowCount()):
            ind_widget = table.cellWidget(row, 0)
            op_widget = table.cellWidget(row, 1)
            val_widget = table.cellWidget(row, 2)
            if not (ind_widget and op_widget and val_widget):
                continue
            indicator = ind_widget.currentText().strip()
            op = op_widget.currentText().strip()
            val_str = val_widget.text().strip()

            # 값 타입 추론
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

            if indicator:
                rules.append({
                    "indicator": indicator,
                    "op": op,
                    "value": value,
                })
        return rules

    def _fill_conditions(self, table: QTableWidget, rules: list):
        """규칙 리스트를 테이블에 채운다"""
        table.setRowCount(0)
        if not rules:
            return
        for rule in rules:
            self._add_condition_row(
                table,
                indicator=rule.get("indicator", ""),
                op=rule.get("op", ">="),
                value=rule.get("value", ""),
            )

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

        conditions = s.get("conditions", [])
        if isinstance(conditions, dict) and "rules" in conditions:
            conditions = conditions["rules"]
        self._fill_conditions(self.screen_cond_table, conditions or [])

    def _new_screen_strategy(self):
        self._current_screen_id = None
        self.screen_name_edit.setText("새 스크린 전략")
        self.screen_desc_edit.setText("")
        self.screen_locked_check.setChecked(False)
        self.screen_cond_table.setRowCount(0)

    def _save_screen_strategy(self):
        name = self.screen_name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "알림", "전략 이름을 입력하세요.")
            return

        conditions = self._read_conditions(self.screen_cond_table)
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
                    QMessageBox.warning(self, "알림",
                        "저장 실패 — 잠긴 전략은 수정할 수 없습니다.\n복제 후 수정하세요.")
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
                QMessageBox.warning(self, "알림",
                    "삭제 실패 — 잠긴 전략은 삭제할 수 없습니다.")
            else:
                self._current_screen_id = None
                self._refresh_screen_list()

    def _activate_screen_strategy(self):
        if self._current_screen_id:
            self._db.set_active_screen_strategy(self._current_screen_id)
            QMessageBox.information(self, "완료", "활성 스크린전략이 변경되었습니다.")

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

        # 파라미터 반영
        p = s.get("params", {}) or {}
        self.trade_jma_len.setValue(int(p.get("jma_length", 7)))
        self.trade_jma_phase.setValue(int(p.get("jma_phase", 50)))
        self.trade_st_period.setValue(int(p.get("st_period", 14)))
        self.trade_st_mult.setValue(float(p.get("st_multiplier", 3.0)))
        self.trade_target.setValue(float(p.get("target_pct", 0.15)))
        self.trade_stop.setValue(float(p.get("stop_pct", -0.05)))
        self.trade_slope_min.setValue(float(p.get("jma_slope_min", 0.0)))

        # 매수/매도 조건
        buy_rules = s.get("buy_rules", {})
        if isinstance(buy_rules, dict):
            buy_rules = buy_rules.get("rules", [])
        self._fill_conditions(self.trade_buy_table, buy_rules or [])

        sell_rules = s.get("sell_rules", {})
        if isinstance(sell_rules, dict):
            sell_rules = sell_rules.get("rules", [])
        self._fill_conditions(self.trade_sell_table, sell_rules or [])

    def _new_trade_strategy(self):
        self._current_trade_id = None
        self.trade_name_edit.setText("새 매매 전략")
        self.trade_desc_edit.setText("")
        self.trade_locked_check.setChecked(False)
        self.trade_buy_table.setRowCount(0)
        self.trade_sell_table.setRowCount(0)

    def _save_trade_strategy(self):
        name = self.trade_name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "알림", "전략 이름을 입력하세요.")
            return

        params = {
            "jma_length": self.trade_jma_len.value(),
            "jma_phase": self.trade_jma_phase.value(),
            "st_period": self.trade_st_period.value(),
            "st_multiplier": self.trade_st_mult.value(),
            "target_pct": self.trade_target.value(),
            "stop_pct": self.trade_stop.value(),
            "jma_slope_min": self.trade_slope_min.value(),
        }
        buy_rules = {
            "logic": "AND",
            "rules": self._read_conditions(self.trade_buy_table),
        }
        sell_rules = {
            "logic": "OR",
            "rules": self._read_conditions(self.trade_sell_table),
        }
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
                    QMessageBox.warning(self, "알림",
                        "저장 실패 — 잠긴 전략은 수정할 수 없습니다.\n복제 후 수정하세요.")
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
                QMessageBox.warning(self, "알림",
                    "삭제 실패 — 잠긴 전략은 삭제할 수 없습니다.")
            else:
                self._current_trade_id = None
                self._refresh_trade_list()

    def _activate_trade_strategy(self):
        if self._current_trade_id:
            self._db.set_active_trade_strategy(self._current_trade_id)
            QMessageBox.information(self, "완료", "활성 매매전략이 변경되었습니다.")
