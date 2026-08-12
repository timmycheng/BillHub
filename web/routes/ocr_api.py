"""BillHub OCR API：POST /api/ocr 上传图片/PDF，返回识别 JSON。
复用 ocr.InvoiceOCR（桌面版同款）。模型加载较重，用模块级单例复用。"""
import os
import tempfile

from flask import Blueprint, jsonify, request
from flask_login import login_required

from ocr import InvoiceOCR

bp = Blueprint('ocr_api', __name__)

ALLOWED_EXTS = {'.png', '.jpg', '.jpeg', '.bmp', '.webp', '.pdf'}

# onnxruntime InferenceSession 支持多线程并发 Run，单例复用安全
_OCR = None


def _get_ocr():
    global _OCR
    if _OCR is None:
        _OCR = InvoiceOCR()
    return _OCR


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
