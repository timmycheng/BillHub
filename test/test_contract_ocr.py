#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""合同 OCR 探查脚本：对 templates/ 下示例合同（doc/docx/pdf/图片）逐个跑识别并打印结果。

样例文件不入库（.gitignore），无样例时直接退出；用于人工核对识别效果。
运行：python test/test_contract_ocr.py
"""
import glob
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from ocr import ContractOCR  # noqa: E402

pdfs = (glob.glob(os.path.join(BASE, 'templates', '*.pdf'))
        + glob.glob(os.path.join(BASE, 'templates', '*.docx'))
        + glob.glob(os.path.join(BASE, 'templates', '*.doc')))
if not pdfs:
    print('无样例文件（templates/ 下无 doc/docx/pdf），退出。')
    sys.exit(0)

print('候选文件:', pdfs)
ocr = ContractOCR()
for p in pdfs:
    print('\n==== ', p)
    try:
        data = ocr.extract(p)
    except Exception as e:
        print('  ERROR:', e)
        continue
    for k, v in data.items():
        if k == 'plan':
            print('  plan:')
            for row in v:
                print('   ', row)
        else:
            print(f'  {k} = {v!r}')
