#!/usr/bin/env python3
"""WZBill —— 智能行项目结算报销工具
PyQt6 桌面端：合同管理 + 智能报销生成 + OCR 识别 + 模板驱动
"""
import os
import sys
import re
import shutil
from datetime import datetime

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QListWidget, QListWidgetItem,
    QTableWidget, QTableWidgetItem, QMessageBox, QFileDialog,
    QSplitter, QGroupBox, QFormLayout, QTextEdit, QSpinBox,
    QDoubleSpinBox, QDateEdit, QMenuBar, QFrame, QDialog,
    QDialogButtonBox, QComboBox, QProgressBar, QAbstractItemView
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QDate
from PyQt6.QtGui import QAction, QFont, QPixmap, QDragEnterEvent, QDropEvent

# 资源路径（PyInstaller 兼容）
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
    RES_DIR = getattr(sys, '_MEIPASS', BASE_DIR)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    RES_DIR = BASE_DIR

import db
import template_engine
import contract_io
from ocr import InvoiceOCR

DEFAULT_TEMPLATE = os.path.join(RES_DIR, 'templates', '审批表模板2026.xlsx')  # 当前固定使用此模板
REPORT_DIR = os.path.join(BASE_DIR, '报销审批单')  # 审批单统一存放目录（按合同名分子文件夹）


def safe_dirname(name):
    """把合同名清洗为合法文件夹名（去 Windows 非法字符、截断）"""
    s = re.sub(r'[\\/:*?"<>|]', '_', name or '').strip()
    return s[:40] or '未命名合同'

CONTRACT_CATEGORIES = ['人力外包类', '采购类', '维保类', '软件开发类', '收据类']




# ============ OCR 工作线程 ============
class OCRThread(QThread):
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, image_path):
        super().__init__()
        self.image_path = image_path

    def run(self):
        try:
            ocr = InvoiceOCR()
            data = ocr.extract(self.image_path)
            self.finished.emit(data)
        except Exception as e:
            self.failed.emit(str(e))


# ============ 合同编辑对话框 ============
class ContractDialog(QDialog):
    def __init__(self, parent=None, contract=None):
        super().__init__(parent)
        self.setWindowTitle('编辑合同' if contract else '新增合同')
        self.setMinimumWidth(420)

        form = QFormLayout()
        self.no_edit = QLineEdit()
        self.name_edit = QLineEdit()
        self.customer_edit = QLineEdit()
        self.manager_edit = QLineEdit()
        self.category_edit = QComboBox()
        self.category_edit.setEditable(True)
        self.category_edit.addItems(CONTRACT_CATEGORIES)
        self.payee_edit = QLineEdit()
        self.bank_name_edit = QLineEdit()
        self.bank_account_edit = QLineEdit()
        self.amount_edit = QDoubleSpinBox()
        self.amount_edit.setRange(0, 1e12)
        self.amount_edit.setDecimals(2)
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDate(QDate.currentDate())
        self.date_edit.setDisplayFormat('yyyy-MM-dd')
        self.remark_edit = QTextEdit()
        self.remark_edit.setMaximumHeight(80)

        form.addRow('合同编号（可选）', self.no_edit)
        form.addRow('合同名称 *', self.name_edit)
        form.addRow('客户/甲方', self.customer_edit)
        form.addRow('经办人', self.manager_edit)
        form.addRow('分类', self.category_edit)
        form.addRow('收款单位', self.payee_edit)
        form.addRow('开户银行', self.bank_name_edit)
        form.addRow('银行账号', self.bank_account_edit)
        form.addRow('合同总金额 *', self.amount_edit)
        form.addRow('签订日期', self.date_edit)
        form.addRow('备注', self.remark_edit)

        if contract:
            self.no_edit.setText(contract['contract_no'] or '')
            self.name_edit.setText(contract['contract_name'])
            self.customer_edit.setText(contract['customer_name'] or '')
            self.manager_edit.setText(contract['contract_manager'] or '')
            cat = contract['category'] or ''
            self.category_edit.setCurrentText(cat if cat in CONTRACT_CATEGORIES else cat)
            self.payee_edit.setText(contract['payee'] or '')
            self.bank_name_edit.setText(contract['bank_name'] or '')
            self.bank_account_edit.setText(contract['bank_account'] or '')
            self.amount_edit.setValue(contract['total_amount'])
            try:
                d = QDate.fromString(contract['sign_date'] or '2000-01-01', 'yyyy-MM-dd')
                self.date_edit.setDate(d)
            except Exception:
                pass
            self.remark_edit.setPlainText(contract['remark'] or '')

        # 付款计划编辑表格（期数 | 条件 | 比例% | 金额，金额由比例自动算、可手改）
        plan_group = QGroupBox('📅 付款计划')
        plan_layout = QVBoxLayout()
        self.plan_table = QTableWidget(0, 4)
        self.plan_table.setHorizontalHeaderLabels(['期数', '支付条件', '比例(%)', '金额(元)'])
        self.plan_table.horizontalHeader().setStretchLastSection(True)
        self.plan_table.setMaximumHeight(170)
        self.plan_table.cellChanged.connect(self._auto_amount)
        plan_layout.addWidget(self.plan_table)
        plan_btns = QHBoxLayout()
        add_plan_btn = QPushButton('＋ 添加一期')
        add_plan_btn.clicked.connect(self.add_plan_row)
        del_plan_btn = QPushButton('－ 删除选中')
        del_plan_btn.clicked.connect(self.del_plan_row)
        plan_btns.addWidget(add_plan_btn)
        plan_btns.addWidget(del_plan_btn)
        plan_btns.addStretch()
        plan_layout.addLayout(plan_btns)
        plan_group.setLayout(plan_layout)

        if contract:
            for p in db.list_payment_plan(contract['id']):
                self._append_plan_row(p)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.validate_and_accept)
        btns.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(plan_group)
        layout.addWidget(btns)

    # ---------- 付款计划编辑 ----------
    def _auto_amount(self, row, col):
        """比例列修改时按合同总额自动算金额"""
        if col != 2:
            return
        ratio_item = self.plan_table.item(row, 2)
        if not ratio_item:
            return
        try:
            ratio = float(ratio_item.text().strip().replace('%', ''))
        except ValueError:
            return
        amount_item = self.plan_table.item(row, 3)
        if not amount_item:
            return
        amount_item.setText(f"{self.amount_edit.value() * ratio / 100:.2f}")

    def _append_plan_row(self, p=None):
        """表格末尾追加一行；p 为数据库记录时预填"""
        row = self.plan_table.rowCount()
        self.plan_table.insertRow(row)
        items = [QTableWidgetItem(), QTableWidgetItem(), QTableWidgetItem(), QTableWidgetItem()]
        if p:
            items[0].setText(str(p['seq']))
            items[1].setText(p['condition'] or '')
            items[2].setText('' if p['ratio'] is None else f"{p['ratio'] * 100:g}")
            items[3].setText(f"{p['amount']:.2f}")
        items[0].setFlags(items[0].flags() & ~Qt.ItemFlag.ItemIsEditable)  # 期数自动编号
        for c, item in enumerate(items):
            self.plan_table.setItem(row, c, item)
        self._renumber()

    def add_plan_row(self):
        self._append_plan_row()

    def del_plan_row(self):
        row = self.plan_table.currentRow()
        if row < 0:
            QMessageBox.information(self, '提示', '请先选中要删除的行')
            return
        self.plan_table.removeRow(row)
        self._renumber()

    def _renumber(self):
        for i in range(self.plan_table.rowCount()):
            item = self.plan_table.item(i, 0)
            if item:
                item.setText(str(i + 1))

    def get_plan_rows(self):
        """读取表格（跳过全空行），ratio 转小数；返回 [{seq, condition, ratio, amount}]"""
        rows = []
        for i in range(self.plan_table.rowCount()):
            cond = self.plan_table.item(i, 1).text().strip() if self.plan_table.item(i, 1) else ''
            ratio_txt = self.plan_table.item(i, 2).text().strip() if self.plan_table.item(i, 2) else ''
            amount_txt = self.plan_table.item(i, 3).text().strip() if self.plan_table.item(i, 3) else ''
            if not cond and not ratio_txt and not amount_txt:
                continue
            ratio = None
            if ratio_txt:
                try:
                    ratio = float(ratio_txt.replace('%', '')) / 100
                except ValueError:
                    ratio = None
            try:
                amount = float(amount_txt.replace(',', ''))
            except ValueError:
                amount = 0.0
            rows.append({'seq': i + 1, 'condition': cond, 'ratio': ratio, 'amount': amount})
        return rows

    def validate_and_accept(self):
        # 合同编号可选（无编号合同靠隐藏 id 区分）
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, '提示', '合同名称不能为空')
            return
        if self.amount_edit.value() <= 0:
            QMessageBox.warning(self, '提示', '合同总金额必须大于 0')
            return
        rows = self.get_plan_rows()
        if rows:
            total = round(sum(r['amount'] for r in rows), 2)
            if abs(total - round(self.amount_edit.value(), 2)) > 0.01:
                ret = QMessageBox.question(
                    self, '确认',
                    f'付款计划金额合计 ¥{total:,.2f} 与合同总额 ¥{self.amount_edit.value():,.2f} 不一致，仍保存？')
                if ret != QMessageBox.StandardButton.Yes:
                    return
        self.accept()

    def get_data(self):
        return {
            'contract_no': self.no_edit.text().strip(),
            'contract_name': self.name_edit.text().strip(),
            'customer_name': self.customer_edit.text().strip(),
            'contract_manager': self.manager_edit.text().strip(),
            'category': self.category_edit.currentText().strip(),
            'payee': self.payee_edit.text().strip(),
            'bank_name': self.bank_name_edit.text().strip(),
            'bank_account': self.bank_account_edit.text().strip(),
            'total_amount': self.amount_edit.value(),
            'sign_date': self.date_edit.date().toString('yyyy-MM-dd'),
            'remark': self.remark_edit.toPlainText().strip(),
        }


# ============ 主窗口 ============
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('WZBill —— 智能行项目结算报销工具')
        self.resize(1400, 800)
        self.current_contract = None
        self.template_path = DEFAULT_TEMPLATE
        self.ocr_thread = None
        self._invoice_src = None  # 本次上传的发票/收据原文件路径
        self._history_records = {}  # 历史记录行号 -> 记录 dict（供查看按钮）

        self._init_menu()
        self._init_ui()
        db.init_db()
        self.refresh_contracts()

    # ---------- 菜单 ----------
    def _init_menu(self):
        bar = self.menuBar()

        file_menu = bar.addMenu('文件(&F)')
        backup_act = QAction('备份数据库', self)
        backup_act.triggered.connect(self.backup_db)
        file_menu.addAction(backup_act)
        file_menu.addSeparator()
        export_act = QAction('导出合同清单…', self)
        export_act.triggered.connect(self.export_contracts)
        file_menu.addAction(export_act)
        import_act = QAction('导入合同清单…', self)
        import_act.triggered.connect(self.import_contracts)
        file_menu.addAction(import_act)
        file_menu.addSeparator()
        exit_act = QAction('退出', self)
        exit_act.triggered.connect(self.close)
        file_menu.addAction(exit_act)

        help_menu = bar.addMenu('关于(&H)')
        about_act = QAction('关于 WZBill', self)
        about_act.triggered.connect(self.show_about)
        help_menu.addAction(about_act)

    # ---------- UI ----------
    def _init_ui(self):
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ===== 左栏：合同列表（上）+ 合同详情（下） =====
        left = QSplitter(Qt.Orientation.Vertical)

        list_box = QWidget()
        left_layout = QVBoxLayout(list_box)
        left_layout.setContentsMargins(6, 6, 6, 6)

        search_box = QLineEdit()
        search_box.setPlaceholderText('🔍 搜索合同…')
        search_box.textChanged.connect(self.filter_contracts)
        left_layout.addWidget(search_box)

        self.contract_list = QListWidget()
        self.contract_list.currentItemChanged.connect(self.on_contract_selected)
        left_layout.addWidget(self.contract_list, 1)

        btn_row = QHBoxLayout()
        add_btn = QPushButton('＋ 新增')
        add_btn.clicked.connect(self.add_contract)
        edit_btn = QPushButton('✎ 编辑')
        edit_btn.clicked.connect(self.edit_contract)
        del_btn = QPushButton('🗑 删除')
        del_btn.clicked.connect(self.delete_contract)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(edit_btn)
        btn_row.addWidget(del_btn)
        left_layout.addLayout(btn_row)
        left.addWidget(list_box)

        # 左栏下部：合同信息卡片 + 付款计划摘要
        detail_box = QWidget()
        detail_layout = QVBoxLayout(detail_box)
        detail_layout.setContentsMargins(6, 6, 6, 6)

        self.info_group = QGroupBox('📄 合同信息')
        info_layout = QFormLayout()
        self.lbl_contract = QLabel('未选择合同')
        self.lbl_customer = QLabel('-')
        self.lbl_manager = QLabel('-')
        self.lbl_category = QLabel('-')
        self.lbl_payee = QLabel('-')
        self.lbl_bank = QLabel('-')
        self.lbl_total = QLabel('-')
        self.lbl_paid = QLabel('-')
        self.lbl_remaining = QLabel('-')
        self.lbl_remaining.setStyleSheet('color:#c0392b;font-weight:bold;')
        info_layout.addRow('合同：', self.lbl_contract)
        info_layout.addRow('客户：', self.lbl_customer)
        info_layout.addRow('经办人：', self.lbl_manager)
        info_layout.addRow('分类：', self.lbl_category)
        info_layout.addRow('收款单位：', self.lbl_payee)
        info_layout.addRow('开户银行：', self.lbl_bank)
        info_layout.addRow('总额：', self.lbl_total)
        info_layout.addRow('已付：', self.lbl_paid)
        info_layout.addRow('剩余：', self.lbl_remaining)
        self.info_group.setLayout(info_layout)
        detail_layout.addWidget(self.info_group)

        self.plan_summary = QTextEdit()
        self.plan_summary.setReadOnly(True)
        self.plan_summary.setMaximumHeight(150)
        detail_layout.addWidget(self.plan_summary, 1)
        left.addWidget(detail_box)
        left.setStretchFactor(0, 2)
        left.setStretchFactor(1, 1)

        # ===== 中栏：本次报销录入 + 历史记录 =====
        middle = QWidget()
        middle_layout = QVBoxLayout(middle)
        middle_layout.setContentsMargins(6, 6, 6, 6)

        self.form_group = QGroupBox('🧾 本次报销录入')
        form_layout = QVBoxLayout()

        # OCR 拖拽区
        self.drop_area = QLabel('📷 拖拽发票/收据图片或 PDF 到此处，自动 OCR 识别\n（也支持点击选择文件）')
        self.drop_area.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_area.setMinimumHeight(80)
        self.drop_area.setStyleSheet(
            'border:2px dashed #aaa;border-radius:8px;background:#f8f9fa;color:#666;')
        self.drop_area.setAcceptDrops(True)
        self.drop_area.mousePressEvent = self.choose_image
        self.drop_area.dragEnterEvent = self.drag_enter
        self.drop_area.dropEvent = self.drop_image
        form_layout.addWidget(self.drop_area)

        self.ocr_progress = QProgressBar()
        self.ocr_progress.setVisible(False)
        self.ocr_progress.setRange(0, 0)
        form_layout.addWidget(self.ocr_progress)

        # 表单
        grid = QFormLayout()
        self.inv_no = QLineEdit()
        self.inv_no.setPlaceholderText('OCR 自动填充或手动输入')
        self.invoice_date = QDateEdit()
        self.invoice_date.setCalendarPopup(True)
        self.invoice_date.setDate(QDate.currentDate())
        self.invoice_date.setDisplayFormat('yyyy-MM-dd')
        self.pay_date = QDateEdit()
        self.pay_date.setCalendarPopup(True)
        self.pay_date.setDate(QDate.currentDate())
        self.pay_date.setDisplayFormat('yyyy-MM-dd')
        self.amount = QDoubleSpinBox()
        self.amount.setRange(0, 1e12)
        self.amount.setDecimals(2)
        self.stage_combo = QComboBox()
        self.stage_combo.setEditable(True)
        self.stage_combo.setPlaceholderText('如：第一期 30%')
        self.main_content = QTextEdit()
        self.main_content.setMaximumHeight(60)
        self.main_content.setPlaceholderText('审批表主要内容（留空则用合同备注）')
        self.remark = QTextEdit()
        self.remark.setMaximumHeight(60)
        self.remark.setPlaceholderText('备注（可选）')

        grid.addRow('发票号：', self.inv_no)
        grid.addRow('开票日期：', self.invoice_date)
        grid.addRow('报销日期：', self.pay_date)
        grid.addRow('金额：', self.amount)
        grid.addRow('阶段：', self.stage_combo)
        grid.addRow('主要内容：', self.main_content)
        grid.addRow('备注：', self.remark)
        form_layout.addLayout(grid)

        # 操作栏
        op_row = QHBoxLayout()
        gen_btn = QPushButton('📥 生成报销单 Excel')
        gen_btn.clicked.connect(self.generate_report)
        gen_btn.setStyleSheet('background:#27ae60;color:white;padding:8px 20px;font-weight:bold;')
        reset_btn = QPushButton('🔄 重置')
        reset_btn.clicked.connect(self.reset_form)
        op_row.addWidget(gen_btn)
        op_row.addWidget(reset_btn)
        op_row.addStretch()
        form_layout.addLayout(op_row)

        self.form_group.setLayout(form_layout)
        middle_layout.addWidget(self.form_group, 1)

        # 历史支付记录
        self.history_group = QGroupBox('📊 历史支付记录')
        hist_layout = QVBoxLayout()
        self.history_table = QTableWidget(0, 7)
        self.history_table.setHorizontalHeaderLabels(['报销日期', '开票日期', '阶段', '金额', '发票号', '票据', '备注'])
        self.history_table.horizontalHeader().setStretchLastSection(True)
        self.history_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.history_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.history_table.itemDoubleClicked.connect(self.open_invoice_file)
        hist_layout.addWidget(self.history_table)
        hist_btns = QHBoxLayout()
        excel_btn = QPushButton('📊 查看选中记录 Excel')
        excel_btn.clicked.connect(self.view_report_file)
        invoice_btn = QPushButton('🧾 查看选中记录报销依据')
        invoice_btn.clicked.connect(self.view_invoice_file)
        del_pay_btn = QPushButton('🗑 删除选中记录')
        del_pay_btn.clicked.connect(self.delete_payment)
        hist_btns.addWidget(excel_btn)
        hist_btns.addWidget(invoice_btn)
        hist_btns.addWidget(del_pay_btn)
        hist_btns.addStretch()
        hist_layout.addLayout(hist_btns)
        self.history_group.setLayout(hist_layout)
        middle_layout.addWidget(self.history_group)

        splitter.addWidget(left)
        splitter.addWidget(middle)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 7)
        self.setCentralWidget(splitter)

    # ---------- 合同列表 ----------
    def refresh_contracts(self, keyword=''):
        self.current_contract = None  # 先置空,clear() 触发选中变化时预览才会清空
        self.contract_list.clear()
        self._contracts = {}
        for c in db.list_contracts():
            if keyword and keyword not in c['contract_no'] and keyword not in c['contract_name']:
                continue
            item = QListWidgetItem(f"{c['contract_no'] or '(未编号)'} | {c['contract_name']}")
            item.setData(Qt.ItemDataRole.UserRole, c['id'])
            self.contract_list.addItem(item)
            self._contracts[c['id']] = c
        self.clear_info()

    def filter_contracts(self, text):
        self.refresh_contracts(text.strip())

    def on_contract_selected(self, current, _prev):
        if not current:
            return
        cid = current.data(Qt.ItemDataRole.UserRole)
        self.current_contract = db.get_contract(cid)
        self.update_info()
        self.load_history()
        self.update_plan_summary()
        self._fill_stage_combo()

    # ---------- 合同 CRUD ----------
    def add_contract(self):
        dlg = ContractDialog(self)
        if dlg.exec():
            data = dlg.get_data()
            cid = db.add_contract(**data)
            if cid is None:
                QMessageBox.warning(self, '提示', '合同编号已存在！')
                return
            db.save_payment_plan(cid, dlg.get_plan_rows())
            self.refresh_contracts()
            # 选中新合同
            for i in range(self.contract_list.count()):
                if self.contract_list.item(i).data(Qt.ItemDataRole.UserRole) == cid:
                    self.contract_list.setCurrentRow(i)
                    break

    def edit_contract(self):
        if not self.current_contract:
            QMessageBox.information(self, '提示', '请先选择合同')
            return
        dlg = ContractDialog(self, self.current_contract)
        if dlg.exec():
            data = dlg.get_data()
            cid = self.current_contract['id']
            db.update_contract(cid, **data)
            db.save_payment_plan(cid, dlg.get_plan_rows())
            self.refresh_contracts()

    def delete_contract(self):
        if not self.current_contract:
            QMessageBox.information(self, '提示', '请先选择合同')
            return
        ret = QMessageBox.question(self, '确认',
            f'确定删除合同「{self.current_contract["contract_name"]}」及其所有支付记录？')
        if ret == QMessageBox.StandardButton.Yes:
            db.delete_contract(self.current_contract['id'])
            self.refresh_contracts()

    # ---------- 信息展示 ----------
    def clear_info(self):
        self.lbl_contract.setText('未选择合同')
        self.lbl_customer.setText('-')
        self.lbl_manager.setText('-')
        self.lbl_category.setText('-')
        self.lbl_payee.setText('-')
        self.lbl_bank.setText('-')
        self.lbl_total.setText('-')
        self.lbl_paid.setText('-')
        self.lbl_remaining.setText('-')
        self.history_table.setRowCount(0)
        self.plan_summary.clear()

    def update_plan_summary(self):
        """左栏付款计划摘要（只读）"""
        if not self.current_contract:
            return
        stages, surplus = db.get_plan_status(self.current_contract['id'])
        if not stages:
            self.plan_summary.setPlainText('（未设置付款计划）')
            return
        lines = []
        for s in stages:
            cond = f" [{s['condition']}]" if s['condition'] else ''
            ratio = f"{s['ratio'] * 100:g}%" if s['ratio'] is not None else '-'
            lines.append(
                f"第{s['seq']}期{cond} 比例{ratio} 计划¥{s['amount']:,.2f} "
                f"已付¥{s['paid']:,.2f} 待付¥{s['remaining']:,.2f}")
        if surplus > 0:
            lines.append(f"⚠️ 超出计划 ¥{surplus:,.2f}")
        self.plan_summary.setPlainText('\n'.join(lines))

    def update_info(self):
        if not self.current_contract:
            return
        c = self.current_contract
        stats = db.get_contract_stats(c['id'])
        self.lbl_contract.setText(f"{c['contract_no'] or '(未编号)'} | {c['contract_name']}")
        self.lbl_customer.setText(c['customer_name'] or '-')
        self.lbl_manager.setText(c['contract_manager'] or '-')
        self.lbl_category.setText(c['category'] or '-')
        self.lbl_payee.setText(c['payee'] or '-')
        self.lbl_bank.setText(f"{c['bank_name'] or '-'} {c['bank_account'] or ''}".strip())
        self.lbl_total.setText(f"¥{stats['total']:,.2f}")
        self.lbl_paid.setText(f"¥{stats['paid']:,.2f}")
        remaining = stats['remaining']
        self.lbl_remaining.setText(f"¥{remaining:,.2f}")
        self.lbl_remaining.setStyleSheet(
            'color:#c0392b;font-weight:bold;' if remaining > 0 else 'color:#27ae60;font-weight:bold;')

    def load_history(self):
        if not self.current_contract:
            return
        records = db.list_payments(self.current_contract['id'])
        self.history_table.setRowCount(len(records))
        self._history_records = {}
        for r, rec in enumerate(records):
            self._history_records[r] = rec
            date_item = QTableWidgetItem(rec['pay_date'])
            date_item.setData(Qt.ItemDataRole.UserRole, rec['id'])  # 存记录 id 供删除
            self.history_table.setItem(r, 0, date_item)
            self.history_table.setItem(r, 1, QTableWidgetItem(rec.get('invoice_date') or ''))
            self.history_table.setItem(r, 2, QTableWidgetItem(rec['stage'] or ''))
            self.history_table.setItem(r, 3, QTableWidgetItem(f"¥{rec['amount']:,.2f}"))
            self.history_table.setItem(r, 4, QTableWidgetItem(rec['invoice_no'] or ''))
            # 票据列：显示文件名，双击打开
            fname = os.path.basename(rec['invoice_file']) if rec['invoice_file'] else ''
            item = QTableWidgetItem(fname)
            item.setData(Qt.ItemDataRole.UserRole, rec['invoice_file'] or '')
            self.history_table.setItem(r, 5, item)
            self.history_table.setItem(r, 6, QTableWidgetItem(rec['remark'] or ''))
        self.history_table.clearSelection()

    def _selected_record(self):
        """当前选中的历史记录 dict（无选中返回 None）"""
        row = self.history_table.currentRow()
        if row < 0:
            QMessageBox.information(self, '提示', '请先选中一条支付记录')
            return None
        return self._history_records.get(row)

    def view_report_file(self):
        """查看选中记录对应的审批表 Excel"""
        rec = self._selected_record()
        if not rec:
            return
        path = rec.get('report_file') or ''
        if path and os.path.exists(path):
            os.startfile(path)
        else:
            QMessageBox.information(self, '提示', '该记录没有可查看的 Excel 文件（可能已移动或删除）')

    def view_invoice_file(self):
        """查看选中记录上传的发票/收据"""
        rec = self._selected_record()
        if not rec:
            return
        path = rec.get('invoice_file') or ''
        if path and os.path.exists(path):
            os.startfile(path)
        else:
            QMessageBox.information(self, '提示', '该记录没有保存报销依据（上传的发票/收据文件）')

    def delete_payment(self):
        """删除选中的历史支付记录"""
        if not self.current_contract:
            return
        row = self.history_table.currentRow()
        if row < 0:
            QMessageBox.information(self, '提示', '请先选中要删除的记录')
            return
        pid = self.history_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        if pid is None:
            return
        ret = QMessageBox.question(self, '确认', '确定删除这条支付记录？\n（删除后合同已付/剩余金额会重新计算）')
        if ret != QMessageBox.StandardButton.Yes:
            return
        db.delete_payment(pid)
        self.load_history()
        self.update_info()
        self.update_plan_summary()

    def open_invoice_file(self, item):
        """双击票据列打开发票/收据文件"""
        path = item.data(Qt.ItemDataRole.UserRole) if item.column() == 5 else None
        if not path:
            path = self.history_table.item(item.row(), 4).data(Qt.ItemDataRole.UserRole)
        if path and os.path.exists(path):
            os.startfile(path)

    # ---------- OCR ----------
    def choose_image(self, _event):
        path, _ = QFileDialog.getOpenFileName(
            self, '选择发票文件', '', '支持的文件 (*.png *.jpg *.jpeg *.bmp *.webp *.pdf)')
        if path:
            self.start_ocr(path)

    def drag_enter(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def drop_image(self, event):
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if os.path.isfile(path):
                self.start_ocr(path)

    def start_ocr(self, image_path):
        self._invoice_src = image_path  # 记录本次上传的票据文件
        self.drop_area.setText(f'⏳ 识别中：{os.path.basename(image_path)} …')
        self.ocr_progress.setVisible(True)
        self.ocr_thread = OCRThread(image_path)
        self.ocr_thread.finished.connect(self.on_ocr_done)
        self.ocr_thread.failed.connect(self.on_ocr_failed)
        self.ocr_thread.start()

    def on_ocr_done(self, data):
        self.ocr_progress.setVisible(False)
        if not data:
            self.drop_area.setText('⚠️ 未能识别出有效信息，请手动填写或换清晰图片')
            return
        if data.get('invoice_no'):
            self.inv_no.setText(data['invoice_no'])
        if data.get('date'):
            try:
                d = QDate.fromString(data['date'], 'yyyy-MM-dd')
                if d.isValid():
                    self.invoice_date.setDate(d)
            except Exception:
                pass
        if data.get('amount'):
            try:
                self.amount.setValue(float(data['amount']))
            except Exception:
                pass
        seller = data.get('seller') or ''
        parts = []
        if data.get('invoice_no'):
            parts.append(f"发票号 {data['invoice_no']}")
        if data.get('amount'):
            parts.append(f"金额 ¥{data['amount']}")
        if data.get('date'):
            parts.append(f"日期 {data['date']}")
        if seller:
            parts.append(f"销售方 {seller}")
        self.drop_area.setText(f'✅ 识别完成：{" | ".join(parts)}\n（请人工核对金额！）')
        self.drop_area.setStyleSheet(
            'border:2px dashed #27ae60;border-radius:8px;background:#eafaf1;color:#1e8449;')

    def on_ocr_failed(self, err):
        self.ocr_progress.setVisible(False)
        self.drop_area.setText(f'❌ OCR 失败：{err}')

    # ---------- 生成报销单 ----------
    def generate_report(self):
        if not self.current_contract:
            QMessageBox.information(self, '提示', '请先选择合同')
            return
        if self.amount.value() <= 0:
            QMessageBox.warning(self, '提示', '请输入本次报销金额')
            return
        if not os.path.exists(self.template_path):
            QMessageBox.warning(self, '提示', f'找不到模板文件：\n{self.template_path}')
            return

        c = self.current_contract
        pay_date = self.pay_date.date().toString('yyyy-MM-dd')
        invoice_date = self.invoice_date.date().toString('yyyy-MM-dd')
        amount = self.amount.value()
        ctx, stages, this_pay = self._build_report_data(include_virtual=True)

        # 发票号重复/相似校验（归一化后与历史记录一致则禁止填报）
        invoice_no = self.inv_no.text().strip()
        if invoice_no:
            norm = re.sub(r'[^A-Za-z0-9]', '', invoice_no).upper()
            for old in db.list_invoice_nos():
                if re.sub(r'[^A-Za-z0-9]', '', old).upper() == norm:
                    QMessageBox.warning(
                        self, '提示', f'发票号「{invoice_no}」与历史记录「{old}」相同，不能重复填报！')
                    return

        # 统一保存到 报销审批单/<合同名>/ 下，文件名带日期时间防止同日多次重名
        contract_dir = os.path.join(REPORT_DIR, safe_dirname(c['contract_name']))
        os.makedirs(contract_dir, exist_ok=True)
        fname = f"审批表_{pay_date}_{datetime.now().strftime('%H%M%S%f')}.xlsx"  # 毫秒防同日多次重名
        out_path = os.path.join(contract_dir, fname)

        try:
            template_engine.render_approval_template(self.template_path, out_path, ctx, stages)
        except Exception as e:
            QMessageBox.critical(self, '生成失败', str(e))
            return

        # 保存本次上传的发票/收据文件（复制到 invoices/ 目录，路径记入记录）
        invoice_file = ''
        if self._invoice_src and os.path.exists(self._invoice_src):
            inv_dir = os.path.join(BASE_DIR, 'invoices')
            os.makedirs(inv_dir, exist_ok=True)
            ext = os.path.splitext(self._invoice_src)[1].lower() or ''
            safe_no = re.sub(r'[^\w\-]', '', c['contract_no'] or '') or f"id{c['id']}"
            fname = f"{safe_no}_{pay_date}_{datetime.now().strftime('%H%M%S')}{ext}"
            try:
                dest = os.path.join(inv_dir, fname)
                shutil.copy2(self._invoice_src, dest)
                invoice_file = dest
            except OSError:
                invoice_file = ''

        # 保存支付记录
        db.add_payment(
            contract_id=c['id'],
            pay_date=pay_date,
            invoice_date=invoice_date,
            stage=self.stage_value(),
            amount=amount,
            invoice_no=invoice_no,
            remark=self.remark.toPlainText().strip(),
            invoice_file=invoice_file,
            report_file=out_path,
        )
        self.update_info()
        self.load_history()
        self.update_plan_summary()
        self.reset_form()
        QMessageBox.information(self, '完成', f'✅ 审批表已生成并保存记录！\n{out_path}')

    def reset_form(self):
        self.inv_no.clear()
        self.amount.setValue(0)
        if self.stage_combo.count():
            idx = self._first_enabled_stage_index()
            self.stage_combo.setCurrentIndex(idx if idx >= 0 else 0)
        else:
            self.stage_combo.setEditText('')
        self.main_content.clear()
        self.remark.clear()
        self.invoice_date.setDate(QDate.currentDate())
        self.pay_date.setDate(QDate.currentDate())
        self._invoice_src = None  # 票据文件随本次填报重置
        self.drop_area.setText('📷 拖拽发票/收据图片或 PDF 到此处，自动 OCR 识别\n（也支持点击选择文件）')
        self.drop_area.setStyleSheet(
            'border:2px dashed #aaa;border-radius:8px;background:#f8f9fa;color:#666;')

    # ---------- 合同清单导入导出 ----------
    def export_contracts(self):
        default_name = f"合同清单_{datetime.now().strftime('%Y%m%d')}.xlsx"
        path, _ = QFileDialog.getSaveFileName(
            self, '导出合同清单', os.path.join(os.path.expanduser('~'), default_name),
            'Excel 文件 (*.xlsx)')
        if not path:
            return
        if not path.lower().endswith('.xlsx'):  # QFileDialog 不自动补后缀
            path += '.xlsx'
        try:
            n = contract_io.export_contracts(path)
        except Exception as e:
            QMessageBox.critical(self, '导出失败', str(e))
            return
        QMessageBox.information(self, '完成', f'✅ 已导出 {n} 条合同：\n{path}')

    def import_contracts(self):
        path, _ = QFileDialog.getOpenFileName(self, '导入合同清单', '', 'Excel 文件 (*.xlsx)')
        if not path:
            return
        try:
            result = contract_io.import_contracts(path)
        except Exception as e:
            QMessageBox.critical(self, '导入失败', str(e))
            return
        self.refresh_contracts()
        lines = [f'新增 {result["added"]} 条',
                 f'跳过 {result["skipped"]} 条（编号重复）',
                 f'失败 {result["failed"]} 条']
        if result['errors']:
            lines.append('\n明细：')
            for e in result['errors'][:20]:  # 限 20 行防对话框过长
                lines.append(f"第 {e['row']} 行：{e['reason']}")
            if len(result['errors']) > 20:
                lines.append(f'… 其余 {len(result["errors"]) - 20} 条略')
        QMessageBox.information(self, '导入结果', '\n'.join(lines))

    # ---------- 审批表数据与预览 ----------
    def stage_value(self):
        """表单阶段取值：有计划 → '第N期'；无计划 → 手输文本"""
        seq = self.stage_combo.currentData()
        if seq is not None:
            return f"第{seq}期"
        return self.stage_combo.currentText().strip()

    def _fill_stage_combo(self):
        """切换合同时填充阶段下拉（有计划只许下拉，无计划可手输）。
        已报销过的期数置灰不可选，默认选中第一个未报销期。"""
        self.stage_combo.blockSignals(True)
        self.stage_combo.clear()
        if self.current_contract:
            plan = db.list_payment_plan(self.current_contract['id'])
            if plan:
                paid = self._paid_stages()
                for p in plan:
                    text = f"第{p['seq']}期"
                    if p['condition']:
                        text += f"({p['condition']})"
                    self.stage_combo.addItem(text, p['seq'])
                    if p['seq'] in paid:
                        idx = self.stage_combo.count() - 1
                        self.stage_combo.setItemData(idx, None, Qt.ItemDataRole.UserRole)
                        item = self.stage_combo.model().item(idx)
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                self.stage_combo.setEditable(False)
                idx = self._first_enabled_stage_index()
                self.stage_combo.setCurrentIndex(idx if idx >= 0 else 0)
            else:
                self.stage_combo.setEditable(True)
                self.stage_combo.setPlaceholderText('如：第一期 30%')
        else:
            self.stage_combo.setEditable(True)
        self.stage_combo.blockSignals(False)

    def _paid_stages(self):
        """该合同历史记录中已填报过的期数集合（1 基 seq）"""
        if not self.current_contract:
            return set()
        plan = db.list_payment_plan(self.current_contract['id'])
        if not plan:
            return set()
        n = len(plan)
        paid = set()
        for rec in db.list_payments(self.current_contract['id']):
            idx = db._match_stage(rec.get('stage'), n)
            if idx is not None:
                paid.add(idx + 1)
        return paid

    def _first_enabled_stage_index(self):
        """阶段下拉第一个可选项的索引（全禁用返回 -1）"""
        model = self.stage_combo.model()
        for i in range(self.stage_combo.count()):
            if model.flags(model.index(i, 0)) & Qt.ItemFlag.ItemIsEnabled:
                return i
        return -1

    def _build_report_data(self, include_virtual=False):
        """组装 xlsx/PDF 渲染数据（与本次表单联动）。
        返回 (context, stages, this_pay)；this_pay 为本次填报落在各期的金额。"""
        c = self.current_contract
        if not c:
            return None
        pay_date = self.pay_date.date().toString('yyyy-MM-dd')
        invoice_date = self.invoice_date.date().toString('yyyy-MM-dd')
        amount = self.amount.value()
        invoice_no = self.inv_no.text().strip()
        remark = self.remark.toPlainText().strip()
        extra = None
        if include_virtual and amount > 0:
            extra = {'id': 0, 'pay_date': pay_date, 'invoice_date': invoice_date,
                     'stage': self.stage_value(),
                     'amount': amount, 'invoice_no': invoice_no}
        stages, _ = db.get_plan_status(c['id'], extra_record=extra)
        base = stages
        if include_virtual and amount > 0:
            base, _ = db.get_plan_status(c['id'])
        this_pay = [round(stages[i]['paid'] - base[i]['paid'], 2) for i in range(len(stages))]

        stats = db.get_contract_stats(c['id'])
        ctx = {
            # 基础信息
            '合同编号': c['contract_no'],
            '合同名称': c['contract_name'],
            '客户名称': c['customer_name'] or '',
            # 主要内容：优先本次填报，留空回退合同备注
            '合同备注': self.main_content.toPlainText().strip() or c['remark'] or '',
            '合同总额': c['total_amount'],
            '合同总额大写': num_to_cn(c['total_amount']),
            '已报销总额': f"{stats['paid']:,.2f}",   # 旧模板兼容
            '剩余金额': f"{stats['remaining']:,.2f}",
            # 本次填报
            '票据总额': amount,
            '票据总额大写': num_to_cn(amount),
            '本次金额': amount,
            '大写金额': num_to_cn(amount),
            '发票号': invoice_no,
            '开票日期': invoice_date,
            '报销日期': pay_date,
            '阶段': self.stage_value(),
            '备注': remark,
            '生成日期': datetime.now().strftime('%Y-%m-%d %H:%M'),
            # 收款信息随合同走；经办人留空（审批表上的经办人需打印后手写签字）
            '经办人': '',
            '收款单位': c['payee'] or '',
            '开户银行': c['bank_name'] or '',
            '银行账号': c['bank_account'] or '',
        }
        sum_ratio = sum_amount = sum_paid = sum_this = 0.0
        for i, s in enumerate(stages):
            k = i + 1
            ctx[f'付款计划_{k}_期数'] = s['seq']
            ctx[f'付款计划_{k}_比例'] = s['ratio']
            ctx[f'付款计划_{k}_金额'] = s['amount']
            ctx[f'付款计划_{k}_已支付'] = base[i]['paid']  # 不含本次
            ctx[f'付款计划_{k}_本次支付'] = this_pay[i]
            ctx[f'付款计划_{k}_付款依据'] = ';'.join(s['invoices'])  # 含本次发票号
            sum_ratio += s['ratio'] or 0
            sum_amount += s['amount']
            sum_paid += base[i]['paid']
            sum_this += this_pay[i]
        ctx['比例合计'] = sum_ratio
        ctx['计划金额合计'] = sum_amount
        ctx['已支付合计'] = sum_paid
        ctx['本次支付合计'] = sum_this
        return ctx, stages, this_pay

    # ---------- 其他 ----------
    def backup_db(self):
        try:
            path = db.backup_db()
            QMessageBox.information(self, '完成', f'数据库已备份：\n{path}')
        except Exception as e:
            QMessageBox.critical(self, '失败', str(e))

    def show_about(self):
        QMessageBox.about(self, '关于 WZBill',
            'WZBill —— 智能行项目结算报销工具\n\n'
            '版本：1.1.0\n'
            '功能：合同管理（付款计划 / 分类 / 收款信息）\n'
            '      OCR 发票识别（图片 / PDF）\n'
            '      模板驱动审批表生成（统一归档）\n'
            '运行环境：完全离线，数据存储于本地 SQLite\n\n'
            'Created by Tim')


def num_to_cn(num):
    """金额转中文大写"""
    if num is None or num == '':
        return ''
    num = float(num)
    digits = '零壹贰叁肆伍陆柒捌玖'
    units = ['', '拾', '佰', '仟']
    big_units = ['', '万', '亿']
    num = round(num * 100) / 100
    int_part = int(num)
    dec_part = round((num - int_part) * 100)
    int_str = str(int_part)
    groups = []
    while len(int_str) > 4:
        groups.insert(0, int_str[-4:])
        int_str = int_str[:-4]
    groups.insert(0, int_str)
    result = ''
    need_zero = False
    for g in range(len(groups)):
        group = groups[g]
        part = ''
        zero_flag = False
        for i in range(len(group)):
            d = int(group[i])
            pos = len(group) - 1 - i
            if d == 0:
                zero_flag = True
            else:
                if zero_flag:
                    part += '零'
                part += digits[d] + units[pos]
                zero_flag = False
        if part:
            if need_zero:
                result += '零'
            result += part + big_units[len(groups) - 1 - g]
            need_zero = False
        else:
            need_zero = True
    if not result:
        result = '零'
    if dec_part == 0:
        return result + '元整'
    jiao = dec_part // 10
    fen = dec_part % 10
    if jiao == 0:
        return result + '元零' + digits[fen] + '分'
    if fen == 0:
        return result + '元' + digits[jiao] + '角整'
    return result + '元' + digits[jiao] + '角' + digits[fen] + '分'


def main():
    db.init_db()
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    font = QFont('Microsoft YaHei', 10)
    app.setFont(font)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
