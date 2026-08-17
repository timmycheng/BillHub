"""BillHub OCR API：POST /api/ocr 上传图片/PDF，返回识别 JSON。
复用 ocr.InvoiceOCR（桌面版同款）。模型加载较重，用模块级单例复用。"""
import json
import os
import tempfile

from flask import Blueprint, jsonify, request
from flask_login import login_required

import db
from ocr import InvoiceOCR, ContractOCR, merge_contract_rules

bp = Blueprint('ocr_api', __name__)

ALLOWED_EXTS = {'.png', '.jpg', '.jpeg', '.bmp', '.webp', '.pdf'}

# onnxruntime InferenceSession 支持多线程并发 Run，单例复用安全
_OCR = None
_CONTRACT_OCR = None


def _get_ocr():
    global _OCR
    if _OCR is None:
        _OCR = InvoiceOCR()
    return _OCR


def _get_contract_ocr():
    global _CONTRACT_OCR
    if _CONTRACT_OCR is None:
        # 引擎懒加载：doc/docx 解析与类型校验不依赖 OCR 模型，
        # 无模型环境（如 CI）也能正确校验/解析；图片 PDF 首次需要时才加载（仍共用单例）
        _CONTRACT_OCR = ContractOCR(ocr_factory=_get_ocr)
    return _CONTRACT_OCR


def _contract_rule_overrides():
    """读取数据库自定义 OCR 规则（管理员在「OCR 规则」页维护），非法内容回退出厂默认。"""
    raw = db.get_setting('ocr_rules')
    if not raw:
        return None
    try:
        overrides = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return overrides if isinstance(overrides, dict) else None


@bp.route('/api/ocr', methods=['POST'])
@login_required
def ocr():
    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({'ok': False, 'error': '未收到文件'}), 400
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ALLOWED_EXTS:
        return jsonify({'ok': False, 'error': '不支持的文件类型，请上传图片或 PDF'}), 400

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
    f.save(tmp.name)
    tmp.close()
    try:
        data = _get_ocr().extract(tmp.name)
    except Exception as e:
        return jsonify({'ok': False, 'error': f'OCR 识别失败：{e}'}), 500
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass

    if not data or not any(data.values()):
        return jsonify({'ok': False,
                        'error': '未能识别出有效信息，请手动填写或换清晰图片'}), 422
    return jsonify({'ok': True, **data})


@bp.route('/api/ocr/contract', methods=['POST'])
@login_required
def contract_ocr():
    """上传合同文件（doc/docx/pdf/图片）→ 识别合同信息与付款计划 → JSON。"""
    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({'ok': False, 'error': '未收到文件'}), 400
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in {'.doc', '.docx', '.pdf', '.png', '.jpg', '.jpeg', '.bmp', '.webp'}:
        return jsonify({'ok': False, 'error': '不支持的文件类型，请上传 doc/docx/pdf/图片'}), 400

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
    f.save(tmp.name)
    tmp.close()
    try:
        data = _get_contract_ocr().extract(tmp.name,
                                           rules=merge_contract_rules(_contract_rule_overrides()))
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    except Exception as e:
        return jsonify({'ok': False, 'error': f'合同识别失败：{e}'}), 500
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
    return jsonify({'ok': True, **data})
