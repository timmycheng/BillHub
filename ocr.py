#!/usr/bin/env python3
"""SmartBill - OCR 智能识别模块
使用 RapidOCR 提取发票/收据关键信息：金额、日期、发票号。
"""
import os
import re


def get_model_dir():
    """模型目录：优先 exe 旁的 models/，其次打包内置，最后包内"""
    # PyInstaller 打包后
    if getattr(__import__('sys'), 'frozen', False):
        import sys
        base = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
        models = os.path.join(base, 'models')
        if os.path.exists(models):
            return models
    # 开发环境
    models = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'models')
    if os.path.exists(models):
        return models
    return None


class InvoiceOCR:
    def __init__(self):
        from rapidocr_onnxruntime import RapidOCR
        model_dir = get_model_dir()
        kwargs = {}
        if model_dir:
            os.environ['RAPIDOCR_PATH'] = model_dir
        self.ocr = RapidOCR()

    def extract(self, image_path):
        """识别图片/PDF 并提取 {amount, date, invoice_no, seller, buyer}"""
        if str(image_path).lower().endswith('.pdf'):
            return self._extract_pdf(image_path)
        result, _ = self.ocr(image_path)
        if not result:
            return None
        return self._parse([line[1] for line in result])

    def _extract_pdf(self, pdf_path):
        """PDF：逐页渲染为图像后 OCR，合并文本再统一解析（发票一般 1 页）"""
        import fitz
        import numpy as np
        from PIL import Image

        texts = []
        with fitz.open(pdf_path) as doc:
            for page in doc:
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                img = pix.pil_image()
                result, _ = self.ocr(np.array(img.convert('RGB')))
                if result:
                    texts.extend(line[1] for line in result)
        if not texts:
            return None
        return self._parse(texts)

    def _parse(self, texts):
        """从 OCR 文本行中提取关键字段"""
        full_text = ' '.join(texts)
        # OCR 常把半角标点识别成全角（．￥：，），统一归一化便于正则匹配
        full_text = full_text.replace('．', '.').replace('￥', '¥').replace('：', ':').replace('，', ',')
        data = {'amount': '', 'date': '', 'invoice_no': '', 'seller': '', 'buyer': ''}

        # 1. 金额：优先取价税合计（总金额）。OCR 常把括号/文字识别残缺，
        #    且“金额”（不含税）列排在价税合计前面，不能简单取第一个 ¥ 金额
        m = None
        for kw in ('价税', '合计'):
            idx = full_text.find(kw)
            if idx != -1:
                # 关键词后 80 字符窗口内找金额；先找带 ¥ 的（可跳过“（大写）壹仟…”中文金额）
                tail = full_text[idx:idx + 80]
                m = re.search(r'[¥￥]\s*([\d,]+(?:\.\d{1,2})?)', tail)
                if not m:
                    m = re.search(r'(?<![A-Za-z0-9])([\d,]+\.\d{1,2})(?![A-Za-z0-9])', tail)
                break
        if not m:
            # 退而求其次：取最后一个 ¥ 金额（价税合计通常位于票面底部）
            matches = list(re.finditer(r'[¥￥]\s*([\d,]+\.\d{1,2})', full_text))
            if matches:
                m = matches[-1]
        if not m:
            m = re.search(r'(?<![A-Za-z0-9])(\d{1,3}(?:,\d{3})+\.\d{2}|\d+\.\d{2})(?![A-Za-z0-9])', full_text)
        if m:
            data['amount'] = m.group(1).replace(',', '')

        # 2. 日期
        m = re.search(r'(\d{4})[年\-/.](\d{1,2})[月\-/.](\d{1,2})日?', full_text)
        if m:
            data['date'] = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

        # 3. 发票号
        m = re.search(r'发票号码[:：]?\s*([A-Za-z0-9]{8,25})', full_text)
        if not m:
            m = re.search(r'号码[:：]\s*([A-Za-z0-9]{8,25})', full_text)
        if not m:
            m = re.search(r'(?<!\d)(\d{15,25})(?!\d)', full_text)
        if m:
            data['invoice_no'] = m.group(1)

        # 4. 销售方 / 购买方（逐行匹配，避免粘连）
        for t in texts:
            m = re.match(r'销售方[名称]?[:：]\s*(.+)', t.strip())
            if m:
                data['seller'] = m.group(1).strip()[:40]
            m = re.match(r'购买方[名称]?[:：]\s*(.+)', t.strip())
            if m:
                data['buyer'] = m.group(1).strip()[:40]

        # 无任何有效信息时返回 None
        if not any(data.values()):
            return None
        return data
