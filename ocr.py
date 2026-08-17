#!/usr/bin/env python3
"""BillHub - OCR 智能识别模块
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


# ============ 合同文本识别（ContractOCR）============
import zipfile  # noqa: E402

# 全角 -> 半角（合同文本里数字/标点常是全角）
_FW = str.maketrans('０１２３４５６７８９．，：；', '0123456789.,:;')


def _norm(text):
    """合同文本归一化：全角转半角、统一常见符号。"""
    if not text:
        return ''
    return (text.translate(_FW)
            .replace('：', ':').replace('，', ',').replace('；', ';')
            .replace('（', '(').replace('）', ')'))


def _find_date_after(text, keywords):
    """在任一关键词之后 40 字符窗口内找首个日期，返回 'YYYY-MM-DD' 或 None。"""
    for kw in keywords:
        idx = text.find(kw)
        if idx == -1:
            continue
        tail = text[idx:idx + 45]
        m = re.search(r'(\d{4})\s*[年\-/.]\s*(\d{1,2})\s*[月\-/.]\s*(\d{1,2})', tail)
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return None


class ContractOCR:
    """从合同文件（doc/docx/PDF/图片）提取结构化信息。
    docx 直接抽文本；PDF 优先用文本层，无文本则渲染后 OCR；.doc 二进制不支持。"""

    def __init__(self, invoice_ocr=None, ocr_factory=None):
        # 复用外部 InvoiceOCR（共用 RapidOCR 单例），避免重复加载模型；
        # ocr_factory 支持懒加载：doc/docx 解析不依赖模型，首次需要时才调用
        self._invoice_ocr = invoice_ocr
        self._ocr_factory = ocr_factory

    def _get_ocr(self):
        if self._invoice_ocr is None:
            if self._ocr_factory is not None:
                self._invoice_ocr = self._ocr_factory()
            else:
                self._invoice_ocr = InvoiceOCR()
        return self._invoice_ocr

    def extract(self, path):
        """返回 {customer_name, total_amount, payee, bank_name, bank_account,
        start_date, end_date, plan:[{seq, ratio, amount}]}。"""
        ext = os.path.splitext(path)[1].lower()
        if ext == '.docx':
            lines = self._docx_lines(path)
        elif ext == '.pdf':
            lines = self._pdf_lines(path)
        elif ext in ('.png', '.jpg', '.jpeg', '.bmp', '.webp'):
            lines = self._image_lines(path)
        elif ext == '.doc':
            raise ValueError('暂不支持旧版 .doc 格式，请另存为 .docx 或 PDF 后再识别')
        else:
            raise ValueError(f'不支持的合同文件类型：{ext}')
        if not lines:
            raise ValueError('未识别到任何文本，请改用清晰可复制的电子稿')
        return self._parse(lines)

    # ---- 文本提取 ----
    def _docx_lines(self, path):
        """docx：解压 document.xml，按段落抽文本。"""
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            target = 'word/document.xml'
            if target not in names:
                # 子文档：word/documentN.xml
                targets = [n for n in names if re.match(r'word/document\d*\.xml$', n)]
                if not targets:
                    return []
                target = sorted(targets)[0]
            xml = z.read(target).decode('utf-8', 'ignore')
        # 按段落 </w:p> 切分，收集 <w:t> 内文本
        lines = []
        for para in xml.split('</w:p>'):
            texts = re.findall(r'<w:t[^>]*>(.*?)</w:t>', para, flags=re.S)
            line = ''.join(texts)
            line = (line.replace('&amp;', '&').replace('&lt;', '<')
                    .replace('&gt;', '>').replace('&quot;', '"'))
            line = re.sub(r'<[^>]+>', '', line).strip()
            if line:
                lines.append(line)
        return lines

    def _pdf_lines(self, path):
        """PDF：优先文本层；文本太少则渲染后 OCR。"""
        import fitz
        lines = []
        with fitz.open(path) as doc:
            for page in doc:
                t = page.get_text('text') or ''
                if t.strip():
                    lines.extend([l for l in t.splitlines() if l.strip()])
        if sum(len(l) for l in lines) < 40:  # 文本层稀薄（扫描件）→ OCR
            ocr_lines = []
            import numpy as np
            from PIL import Image
            with fitz.open(path) as doc:
                for page in doc:
                    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                    img = pix.pil_image()
                    result, _ = self._get_ocr().ocr(np.array(img.convert('RGB')))
                    if result:
                        ocr_lines.extend(line[1] for line in result)
            if ocr_lines:
                lines = ocr_lines
        return lines

    def _image_lines(self, path):
        result, _ = self._get_ocr().ocr(path)
        return [line[1] for line in result] if result else []

    # ---- 字段解析 ----
    def _parse(self, lines):
        norm_lines = [_norm(l) for l in lines]
        full = _norm(' '.join(lines))
        data = {
            'customer_name': '', 'total_amount': '', 'payee': '', 'bank_name': '',
            'bank_account': '', 'start_date': '', 'end_date': '', 'plan': [],
        }

        # 签订单位（乙方）：封面常为空，真实名称在“乙方名称：”或“户名：”（=收款单位）
        def _looks_like_name(s):
            s = s.strip(' ：:()（）')
            if not s or len(s) < 3:
                return False
            if re.fullmatch(r'[\d\s\-]+', s):
                return False
            bad = ('法定', '地址', '联系', '电话', '邮编', '名称', '代表', '甲方', '乙方')
            return not any(b in s for b in bad)

        customer_name = ''
        for ln in norm_lines:
            m = re.search(r'乙方名称\s*[:：]\s*(.{2,40})', ln)
            if m and _looks_like_name(m.group(1)):
                customer_name = m.group(1).strip(' ：:()（）'); break
        if not customer_name:
            for ln in norm_lines:
                m = re.search(r'乙方\s*[:：]\s*(.{2,40})', ln)
                if m and _looks_like_name(m.group(1)):
                    customer_name = m.group(1).strip(' ：:()（）'); break
        if not customer_name:
            for pat in (r'供应商\s*[:：]?\s*(.{2,40})', r'服务商\s*[:：]?\s*(.{2,40})',
                        r'承包方\s*[:：]?\s*(.{2,40})', r'受托方\s*[:：]?\s*(.{2,40})',
                        r'出卖人\s*[:：]?\s*(.{2,40})'):
                for ln in norm_lines:
                    m = re.search(pat, ln)
                    if m and _looks_like_name(m.group(1)):
                        customer_name = m.group(1).strip(' ：:()（）'); break
                if customer_name:
                    break
        data['customer_name'] = customer_name

        # 合同金额：优先关键词窗口内的 ¥ 金额；否则取全文最大的 ¥ 金额（≥100，过滤税率等噪声）
        amount_keywords = ('合同金额', '合同总价', '合同总额', '总金额', '合同价款', '总价款',
                           '费用金额', '服务费', '服务费用', '含税', '中标价', '暂定总价')
        picked = ''
        for kw in amount_keywords:
            idx = full.find(kw)
            if idx == -1:
                continue
            tail = full[idx:idx + 70]
            yen = re.findall(r'[¥￥]\s*[【\[]*(\d[\d,]*(?:\.\d{1,2})?)[】\]]*', tail)
            if yen:
                picked = max(yen, key=lambda x: float(x.replace(',', '')))
                break
        if not picked:
            yen_all = re.findall(r'[¥￥]\s*[【\[]*(\d[\d,]*(?:\.\d{1,2})?)[】\]]*', full)
            big = [y for y in yen_all if float(y.replace(',', '')) >= 100]
            if big:
                picked = max(big, key=lambda x: float(x.replace(',', '')))
        if picked:
            data['total_amount'] = picked.replace(',', '')

        # 收款单位 / 开户银行 / 银行账号：逐行就近匹配
        for ln in norm_lines:
            if not data['payee']:
                m = re.search(r'(?:收款单位|收款方|账户名称|户名)\s*[:：]?\s*([^\n,，;；。]{2,40})', ln)
                if m:
                    data['payee'] = m.group(1).strip(' ：:()（）')
            if not data['bank_name']:
                m = re.search(r'(?:开户银行|开户行|开户银行名称|银行名称)\s*[:：]?\s*([^\n,，;；。]{2,40})', ln)
                if m:
                    data['bank_name'] = m.group(1).strip(' ：:()（）')
            if not data['bank_account']:
                m = re.search(r'(?:银行账号|开户账号|账号|账户号?|帐号)\s*[:：]?\s*([\d\s\-]{8,40})', ln)
                if m:
                    acc = re.sub(r'[\s\-]', '', m.group(1))
                    if 6 <= len(acc) <= 40 and acc.isdigit():
                        data['bank_account'] = acc

        # 生效 / 结束时间：先处理 “自/从 X 至/到 Y” 整段范围
        rng = re.search(r'[自从]\s*(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日?)\s*[至到\-—~]+\s*(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日?)', full)
        if rng:
            data['start_date'] = self._parse_date_text(rng.group(1))
            data['end_date'] = self._parse_date_text(rng.group(2))
        else:
            rng2 = re.search(r'(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日?)\s*[至到\-—~]+\s*(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日?)', full)
            if rng2:
                data['start_date'] = self._parse_date_text(rng2.group(1))
                data['end_date'] = self._parse_date_text(rng2.group(2))
        if not data['start_date']:
            data['start_date'] = _find_date_after(full, ['生效日期', '生效时间', '起始日期', '开始日期',
                                                         '合同起始', '生效期', '实施日期', '进场日期']) or ''
        if not data['end_date']:
            data['end_date'] = _find_date_after(full, ['结束日期', '结束时间', '终止日期', '到期日期',
                                                       '截止日期', '有效期至', '合同届满', '履约期限',
                                                       '合同期限', '服务期限', '完工日期']) or ''

        # 付款计划：逐行匹配 第X期/首期/预付款/进度款/尾款/质保金/签订后/余款 + 附近比例或金额
        plan = []
        for ln in norm_lines:
            if '支付' not in ln and '付款' not in ln and '款' not in ln:
                # 第X期 描述行可能不含"款"，放宽：含"第X期"即纳入
                if not re.search(r'第\s*[一二三四五六七八九十\d]+\s*(?:期|次|阶段)', ln):
                    continue
            seq = None
            m = re.search(r'第\s*([一二三四五六七八九十\d]+)\s*(?:期|次|阶段|批)', ln)
            if m:
                seq = self._cn_or_int(m.group(1))
            else:
                kw_map = {'预付款': 1, '首期': 1, '首付款': 1, '定金': 1, '签订': 1,
                          '进度款': 2, '中期款': 2,
                          '验收款': 3, '尾款': 9, '余款': 9, '质保金': 10, '保修金': 10}
                for k, v in kw_map.items():
                    if k in ln:
                        seq = v
                        break
            if seq is None:
                continue
            ratio = None
            rm = re.search(r'(\d+(?:\.\d+)?)\s*%', ln)
            if rm:
                ratio = round(float(rm.group(1)) / 100, 4)
            amount = ''
            am = re.search(r'[¥￥]?\s*([【\[]?\d[\d,]*(?:\.\d{1,2})?[】\]]?)', ln)
            if am and re.search(r'\d', am.group(1)):
                cand = am.group(1).replace(',', '').strip('【[]】')
                if cand.replace('.', '').isdigit() and float(cand) >= 1:
                    amount = cand
            plan.append({'seq': seq, 'ratio': ratio, 'amount': amount})
        # 去重（按期数）、排序、重排序号
        seen = {}
        for p in plan:
            seen.setdefault(p['seq'], p)
        plan = [seen[k] for k in sorted(seen)]
        for i, p in enumerate(plan, start=1):
            p['seq'] = i
        data['plan'] = plan

        # 兜底：乙方为空但识别到收款单位，则用收款单位补
        if not data['customer_name'] and data['payee']:
            data['customer_name'] = data['payee']

        return data

    @staticmethod
    def _cn_or_int(s):
        cn = '零一二三四五六七八九十'
        s = s.strip()
        if s.isdigit():
            return int(s)
        # 简单中文数字：十/十一/二十…
        if '十' in s:
            parts = s.split('十')
            tens = (cn.index(parts[0]) if parts[0] in cn else 1) if parts[0] else 1
            ones = (cn.index(parts[1]) if len(parts) > 1 and parts[1] in cn else 0)
            return tens * 10 + ones
        if len(s) == 1 and s in cn:
            return cn.index(s)
        try:
            return int(s)
        except ValueError:
            return None

    @staticmethod
    def _parse_date_text(s):
        m = re.search(r'(\d{4})\s*年?\s*(\d{1,2})\s*月?\s*(\d{1,2})', s)
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        m = re.search(r'(\d{4})\s*[\-/.]\s*(\d{1,2})\s*[\-/.]\s*(\d{1,2})', s)
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        return ''
