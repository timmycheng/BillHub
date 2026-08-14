#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键发版 prep 逻辑测试：与 CI workflow（build-release.yml）内嵌 Python 一致。

纯内存/临时副本验证 CHANGELOG 转正 + pyproject 版本 bump，不改动仓库文件。
运行：python test/test_release_prep.py
"""
import datetime
import os
import re
import sys
import tomllib

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)


def find_unreleased(text):
    m = re.search(r'^## \[Unreleased\][ \t]*\n?', text, re.M)
    if not m:
        return None
    body_start = m.end()
    nm = re.search(r'^## \[', text[body_start:], re.M)
    end = body_start + nm.start() if nm else len(text)
    return m.start(), body_start, end


def gen_from_commits():
    return '### 变更\n\n- （自动生成：无提交记录）'


def run(ver, extra, text):
    date = datetime.date.today().isoformat()
    if extra:
        r = find_unreleased(text)
        if r is None:
            vm = re.search(r'^## \[', text, re.M)
            block = '## [Unreleased]\n\n' + extra + '\n\n'
            text = text[:vm.start()] + block + text[vm.start():] if vm else text.rstrip() + '\n\n' + block
        else:
            s, b, e = r
            body = text[b:e].rstrip()
            text = text[:b] + (body + '\n\n' if body else '') + extra + '\n\n' + text[e:]
    r = find_unreleased(text)
    if r is not None:
        s, b, e = r
        body = text[b:e].strip()
        if not body:
            body = gen_from_commits()
        block = f'## [Unreleased]\n\n## [{ver}] - {date}\n\n{body}\n\n'
        text = text[:s] + block + text[e:]
    else:
        body = gen_from_commits()
        block = f'## [Unreleased]\n\n## [{ver}] - {date}\n\n{body}\n\n'
        vm = re.search(r'^## \[', text, re.M)
        text = text[:vm.start()] + block + text[vm.start():] if vm else text.rstrip() + '\n\n' + block
    return text


def extract_notes(text, ver):
    m = re.search(r'^##\s*\[' + re.escape(ver) + r'\][^\n]*\n(.*?)(?=\n^##\s*\[|\Z)', text, re.S | re.M)
    return m.group(1).strip() if m else ''


def main():
    with open(os.path.join(BASE, 'CHANGELOG.md'), encoding='utf-8') as fh:
        src = fh.read()
    fails = []

    def header_count(text, name):
        return len(re.findall(rf'^## \[{re.escape(name)}\](?:[ \t]*-[^\n]*)?[ \t]*$', text, re.M))

    def header_pos(text, name):
        m = re.search(rf'^## \[{re.escape(name)}\](?:[ \t]*-[^\n]*)?[ \t]*$', text, re.M)
        return m.start() if m else -1

    # 场景 1：现有 Unreleased 有内容 → 转正
    out = run('9.9.9', '', src)
    ok = (header_count(out, 'Unreleased') == 1
          and header_count(out, '9.9.9') == 1
          and '一键发版' in extract_notes(out, '9.9.9')
          and header_pos(out, '2.0.1') > 0
          and header_pos(out, 'Unreleased') < header_pos(out, '9.9.9') < header_pos(out, '2.0.1')
          and out.strip().startswith('# Changelog'))
    print('场景1 Unreleased转正:', 'PASS' if ok else 'FAIL')
    if not ok:
        fails.append('s1')

    # 场景 2：notes 追加到 Unreleased 后转正
    out2 = run('9.9.9', '### 修复\n\n- 补发说明测试', src)
    ok2 = ('补发说明测试' in out2 and '一键发版' in out2 and header_count(out2, '9.9.9') == 1)
    print('场景2 notes追加:', 'PASS' if ok2 else 'FAIL')
    if not ok2:
        fails.append('s2')

    # 场景 3：无 Unreleased 小节（移除标题行）→ 自动生成
    no_unrel = re.sub(r'^## \[Unreleased\][ \t]*\n?(?:\n|$)(?:(?!^## \[).)*', '', src, flags=re.S | re.M)
    assert header_count(no_unrel, 'Unreleased') == 0, 'removal failed'
    out3 = run('9.9.9', '', no_unrel)
    ok3 = (header_count(out3, '9.9.9') == 1 and '（自动生成：无提交记录）' in out3
           and header_count(out3, 'Unreleased') == 1)
    print('场景3 无Unreleased自动生成:', 'PASS' if ok3 else 'FAIL')
    if not ok3:
        fails.append('s3')

    # 场景 4：版本号 bump
    with open(os.path.join(BASE, 'pyproject.toml'), encoding='utf-8') as fh:
        c = fh.read()
    m = re.search(r'(?m)(?<=^version = ")[^"]+(?=")', c)
    c2 = c[:m.start()] + '9.9.9' + c[m.end():]
    ok4 = tomllib.loads(c2)['project']['version'] == '9.9.9'
    print('场景4 pyproject bump:', 'PASS' if ok4 else 'FAIL')
    if not ok4:
        fails.append('s4')

    print('FAILED:', fails if fails else '无')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
