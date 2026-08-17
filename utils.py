"""BillHub 公共工具模块（桌面版 main.py 与 Web 版共享）。
num_to_cn / safe_dirname 从 main.py 抽取，桌面版改为 import 复用。"""
import re
from datetime import date, datetime

import db


def safe_dirname(name):
    """把合同名清洗为合法文件夹名（去 Windows 非法字符、截断）"""
    s = re.sub(r'[\\/:*?"<>|]', '_', name or '').strip()
    return s[:40] or '未命名合同'


def contract_statuses(c):
    """计算合同的签订状态与生效状态（派生字段，不落库）。
    - 签订状态：依据是否已上传 PDF 扫描件 → '是' / '否'
    - 生效状态：依据生效时间 start_date、结束时间 end_date 与今天的关系：
      未生效（尚未到生效时间/未设置生效时间）、生效中、已失效。
    返回 {'signed': '是'|'否', 'effective': '未生效'|'生效中'|'已失效',
          'effective_key': 'pending'|'active'|'expired', 'signed_bool': bool}"""
    signed = '是' if c.get('scan_file') else '否'
    today = date.today().isoformat()
    start = c.get('start_date') or ''
    end = c.get('end_date') or ''
    if end and today > end:
        eff, key = '已失效', 'expired'
    elif start and (not end or today <= end) and today >= start:
        eff, key = '生效中', 'active'
    else:
        eff, key = '未生效', 'pending'
    return {'signed': signed, 'effective': eff, 'effective_key': key,
            'signed_bool': bool(c.get('scan_file'))}


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


def auto_main_content(c, stage='', amount=0, invoice_no=''):
    """「主要内容」留空时的自动介绍文案：合同名 + 期数 + 金额 + 发票号。
    例：信息系统安全服务合同第1期付款，金额 ¥258,000.00，发票号 03123456"""
    name = (c.get('contract_name') or '').strip()
    if not name:
        return ''
    parts = [name + (stage or '').strip() + '付款',
             f'金额 ¥{float(amount):,.2f}']
    if (invoice_no or '').strip():
        parts.append(f'发票号 {invoice_no.strip()}')
    return '，'.join(parts)


def build_report_context(c, pay_date, invoice_date, amount, invoice_no,
                         stage, main_content='', remark='', include_virtual=True):
    """组装审批表渲染上下文（与桌面版 MainWindow._build_report_data 等价）。
    include_virtual=True：金额>0 时叠加一条虚拟本次记录用于预览（未落库）。
    返回 (context, stages, this_pay)；this_pay 为本次填报落在各期的金额。"""
    if include_virtual and amount > 0:
        extra = {'id': 0, 'pay_date': pay_date, 'invoice_date': invoice_date,
                 'stage': stage, 'amount': amount, 'invoice_no': invoice_no}
        stages, _ = db.get_plan_status(c['id'], extra_record=extra)
    else:
        stages, _ = db.get_plan_status(c['id'])
    base = stages
    if include_virtual and amount > 0:
        base, _ = db.get_plan_status(c['id'])
    this_pay = [round(stages[i]['paid'] - base[i]['paid'], 2)
                for i in range(len(stages))]

    stats = db.get_contract_stats(c['id'])
    ctx = {
        '合同编号': c['contract_no'],
        '合同名称': c['contract_name'],
        '客户名称': c['customer_name'] or '',
        '合同备注': main_content or auto_main_content(c, stage, amount, invoice_no) or c['remark'] or '',
        '合同总额': f"{c['total_amount']:,.2f}",
        '合同总额大写': num_to_cn(c['total_amount']),
        '已报销总额': f"{stats['paid']:,.2f}",
        '剩余金额': f"{stats['remaining']:,.2f}",
        '票据总额': f"{amount:,.2f}",
        '票据总额大写': num_to_cn(amount),
        '本次金额': f"{amount:,.2f}",
        '大写金额': num_to_cn(amount),
        '发票号': invoice_no,
        '开票日期': invoice_date,
        '报销日期': pay_date,
        '阶段': stage,
        '备注': remark,
        '生成日期': datetime.now().strftime('%Y-%m-%d %H:%M'),
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
        ctx[f'付款计划_{k}_已支付'] = base[i]['paid']
        ctx[f'付款计划_{k}_本次支付'] = this_pay[i]
        ctx[f'付款计划_{k}_付款依据'] = ';'.join(s['invoices'])
        sum_ratio += s['ratio'] or 0
        sum_amount += s['amount']
        sum_paid += base[i]['paid']
        sum_this += this_pay[i]
    ctx['比例合计'] = sum_ratio
    ctx['计划金额合计'] = sum_amount
    ctx['已支付合计'] = sum_paid
    ctx['本次支付合计'] = sum_this
    return ctx, stages, this_pay


def build_record_preview(c, rec):
    """已保存支付记录的预览上下文：不叠加虚拟记录（该记录已在库中），
    本次支付 = 该记录自身的分期分配。返回 (ctx, stages, this_pay)。"""
    ctx, stages, _ = build_report_context(
        c, rec['pay_date'], rec.get('invoice_date') or '', rec['amount'],
        rec.get('invoice_no') or '', rec.get('stage') or '',
        rec.get('main_content') or '',
        rec.get('remark') or '', include_virtual=False)
    plan_rows = db.list_payment_plan(c['id'])
    paid, _, _ = db.compute_stage_alloc(plan_rows, [rec])
    this_pay = [round(x, 2) for x in paid]
    return ctx, stages, this_pay
