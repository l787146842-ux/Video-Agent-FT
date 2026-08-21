# -*- coding: utf-8 -*-
"""批 9b：代码注释/docstring 事故考古清零（受控转换，非盲删）。

只改写 COMMENT 与 docstring 文本；字符串字面量与代码一律不碰。
模式护栏：
- 「X轮」前若有 上/第/每/本/该/下/当/首/末/次/前/后/旧/新 视为自然语言，不动；
- 四位重复数字仅匹配词边界（事故号 1111-9999）；
- 清理后做残留归一（空括号/悬空分号/双空格），纯标点注释行整行删除。
用法：python scripts/clean_incident_refs.py [--apply]
"""
import io
import pathlib
import re
import sys
import tokenize

ROOT = pathlib.Path(__file__).resolve().parent.parent

# ---------- 考古模式（按序替换） ----------
PATTERNS = [
    re.compile(r"audit-0819[a-z]*"),                       # audit-0819e/0819b…
    re.compile(r"814[A-Z][A-Za-z0-9]*"),                   # 814R1/814H7/814Gb…
    re.compile(r"\b0817\b|\b0818\b|\b0819\b"),             # 日期批注
    re.compile(r"\b(\d)\1{3}\b"),                          # 1111/2222/…/9999
    # X轮 考古批注（自然语言「上一轮/每一轮」有前置字护栏，不误伤；
    # 「一轮」不开口：存量批注无一轮编号，而自然语「一轮 Agent 回复」常见）
    re.compile(r"(?<![上第每本该下当首末次前后旧新])\s*[二三四五六七八九]轮"),
    re.compile(r"事故"),                                    # 叙事词（编号已先去）
    re.compile(r"（?清偿）：?"),                            # 编号删尽后的孤立「（清偿）」
    re.compile(r"批次\s*\d+"),                              # 「批次5」类
    # 批次/整改标记（S2/#2、B0/F2、R4a/R4b 等；A/C 不开口：ADR 决策与
    # C1-C6 业界基准卡片是有意保留的设计锚点，不属事故考古）
    re.compile(
        r"(?<![A-Za-z0-9])[SRNBDGQTULEVYHPWMXF]\d{1,2}[a-z]?"
        r"(?:[/／]#?[A-Z]?\d{1,2}[a-z]?)*"),
]

# ---------- 残留归一 ----------
RESIDUE = [
    (re.compile(r"（\s*）"), ""),
    (re.compile(r"\(\s*\)"), ""),
    (re.compile(r"（\s*[；;:：]\s*"), "（"),
    (re.compile(r"\(\s*[;:]\s*"), "("),
    (re.compile(r"\s*[；;]\s*）"), "）"),
    (re.compile(r"\s*[;]\s*\)"), ")"),
    (re.compile(r"，\s*）"), "）"),
    (re.compile(r"，\s*\)"), ")"),
    (re.compile(r"（\s*，"), "（"),
    (re.compile(r"，{2,}"), "，"),
    (re.compile(r"（\s+"), "（"),
    (re.compile(r"\s+）"), "）"),
    (re.compile(r"；{2,}"), "；"),
    (re.compile(r"[ \t]{2,}"), " "),
    (re.compile(r"（），?"), ""),
    (re.compile(r"——\s*）"), "）"),
    (re.compile(r"（\s*——"), "（"),
    (re.compile(r"：\s*）"), "）"),
    # 注释开头悬空冒号（编号删尽后只剩「：正文」）
    (re.compile(r"^(#\s*)：\s*"), r"\1"),
    (re.compile(r"^：\s*"), ""),
    # 编号范围删尽后的悬空连字符（R01-R26 → -）；不碰分隔线（连申号串）
    (re.compile(r"^(#\s*)-(?![\-—])\s*"), r"\1"),
]


def clean_text(s: str) -> str:
    """注释 token 清理（单行，可用全部残留规则）"""
    for pat in PATTERNS:
        s = pat.sub("", s)
    for pat, rep in RESIDUE:
        s = pat.sub(rep, s)
    return s


# docstring 逐行清理：禁用会吞并多空格/跨行的规则（保护缩进）
RESIDUE_DOC_LINE = [r for r in RESIDUE if r[0].pattern not in (r"[ \t]{2,}",)]


def clean_doc_line(s: str) -> str:
    for pat in PATTERNS:
        s = pat.sub("", s)
    for pat, rep in RESIDUE_DOC_LINE:
        s = pat.sub(rep, s)
    return s


def clean_docstring(token_text: str) -> str:
    return "\n".join(clean_doc_line(l) for l in token_text.split("\n"))


def is_comment_line_dead(text: str) -> bool:
    """清理后注释只剩标点/空白 → 整行可删"""
    body = text.lstrip().lstrip("#").strip()
    return body == "" or all(ch in "（）()；;:：，,。、-—·/／ " for ch in body)


def docstring_line_set(src: str):
    import ast

    try:
        tree = ast.parse(src)
    except SyntaxError:
        return set()
    import ast as _ast

    lines = set()
    for node in _ast.walk(tree):
        if isinstance(node, (_ast.Module, _ast.ClassDef, _ast.FunctionDef,
                             _ast.AsyncFunctionDef)):
            b = node.body
            if (b and isinstance(b[0], _ast.Expr)
                    and isinstance(b[0].value, _ast.Constant)
                    and isinstance(b[0].value.value, str)):
                for ln in range(b[0].lineno, b[0].end_lineno + 1):
                    lines.add(ln)
    return lines


def process_file(path: pathlib.Path, apply: bool, comments_only: bool = False):
    src = path.read_text(encoding="utf-8")
    if not re.search(r"事故|814[A-Z]|\b(\d)\1{3}\b|[一二三四五六七八九]轮", src):
        return 0
    dls = set() if comments_only else docstring_line_set(src)
    changed = 0
    out_lines = src.splitlines(keepends=True)
    # 逐 token 收集替换（倒序应用，避免偏移）
    edits = []
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except tokenize.TokenizeError:
        return 0
    for tok in tokens:
        is_doc = tok.type == tokenize.STRING and tok.start[0] in dls
        if tok.type not in (tokenize.COMMENT,) and not is_doc:
            continue
        new = clean_docstring(tok.string) if is_doc else clean_text(tok.string)
        if new != tok.string:
            edits.append((tok.start, tok.end, new, tok.type))
            changed += 1
    if not changed:
        return 0
    if apply:
        # 倒序替换
        lines = src.split("\n")
        for (srow, scol), (erow, ecol), new, ttype in reversed(edits):
            if ttype == tokenize.COMMENT:
                line = lines[srow - 1]
                segment = line[scol:ecol]
                replaced = line[:scol] + new + line[ecol:]
                if is_comment_line_dead(new):
                    # 整行删除（仅当该行只有注释）
                    if line[:scol].strip() == "":
                        lines[srow - 1] = None  # 标记删除
                    else:
                        lines[srow - 1] = line[:scol].rstrip()
                else:
                    lines[srow - 1] = replaced
            else:
                # docstring：可能跨行，按整 token 区间替换（逐行清理保缩进）
                prefix = "\n".join(lines[:srow - 1])
                head = lines[srow - 1][:scol]
                tail = lines[erow - 1][ecol:]
                merged = prefix
                if merged:
                    merged += "\n"
                merged += head + new + tail
                lines = merged.split("\n") + lines[erow:]
        lines = [l for l in lines if l is not None]
        path.write_text("\n".join(lines), encoding="utf-8", newline="")
    return changed


def process_ts_file(path: pathlib.Path, apply: bool):
    """TS/TSX：只清理纯注释行（// 行与 JSDoc 块行）；代码行/字符串不碰。"""
    src = path.read_text(encoding="utf-8")
    if not re.search(r"事故|814[A-Z]|\b(\d)\1{3}\b|[一二三四五六七]轮", src):
        return 0
    lines = src.split("\n")
    changed = 0
    in_block = False
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if in_block:
            is_comment_line = stripped.startswith("*") or stripped.startswith("*/")
            if "*/" in stripped:
                in_block = False
        elif stripped.startswith("//"):
            is_comment_line = True
        elif stripped.startswith("/**") or stripped.startswith("/*"):
            is_comment_line = True
            if "*/" not in stripped:
                in_block = True
        else:
            is_comment_line = False
        if not is_comment_line:
            continue
        # 逐行清理（保缩进：只对注释标记后的文本清理再拼回）
        indent = line[:len(line) - len(stripped)]
        if stripped.startswith("//"):
            marker, body = "//", stripped[2:]
        elif stripped.startswith("/**"):
            marker, body = "/**", stripped[3:]
        elif stripped.startswith("/*"):
            marker, body = "/*", stripped[2:]
        elif stripped.startswith("*/"):
            marker, body = "*/", stripped[2:]
        elif stripped.startswith("*"):
            marker, body = "*", stripped[1:]
        else:
            continue
        new_body = clean_doc_line(body)  # 逐行规则（保缩进/不跨行）
        new_line = indent + marker + new_body
        # 清理后只剩标记的行删除（纯标点/空）
        if new_body.strip() == "" and marker in ("//", "*"):
            body_probe = new_body.strip()
            if body_probe == "":
                # 保留 JSDoc 空行形态（* 行空行常见），仅 // 空注释可删
                if marker == "//" and stripped.strip() != "//":
                    lines[i] = None
                    changed += 1
                    continue
        if new_line != line:
            lines[i] = new_line
            changed += 1
    if changed and apply:
        path.write_text(
            "\n".join(l for l in lines if l is not None), encoding="utf-8", newline="")
    return changed


def main():
    apply = "--apply" in sys.argv
    comments_only = "--comments-only" in sys.argv
    total = 0
    files = 0
    for base in ("src/video_agent",):
        for p in (ROOT / base).rglob("*.py"):
            n = process_file(p, apply, comments_only)
            if n:
                files += 1
                total += n
                print(f"{'APPLY' if apply else 'DRY'} {n:3d} tokens  {p.relative_to(ROOT).as_posix()}")
    for base in ("src/web",):
        for p in (ROOT / base).rglob("*"):
            if p.is_file() and p.suffix in (".ts", ".tsx"):
                n = process_ts_file(p, apply)
                if n:
                    files += 1
                    total += n
                    print(f"{'APPLY' if apply else 'DRY'} {n:3d} lines   {p.relative_to(ROOT).as_posix()}")
    print(f"[clean_incident_refs] {files} files, {total} items {'rewritten' if apply else 'would rewrite'}")


if __name__ == "__main__":
    main()
