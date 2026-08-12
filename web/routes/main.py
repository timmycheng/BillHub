"""BillHub 主面板蓝图。P1 仅空三栏占位；P2+ 逐步填充合同/报销/预览。"""
from flask import Blueprint, render_template
from flask_login import login_required

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
@login_required
def dashboard():
    return render_template('dashboard.html')
