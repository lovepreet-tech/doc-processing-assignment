"""Deterministic evaluator for a safe subset of Excel formulas: +, -, *, /, parens,
numeric literals, cell refs, and SUM/AVERAGE/MIN/MAX/IF over literal ranges/refs.
Anything else (VLOOKUP, INDEX/MATCH, external refs, volatile functions, ...) is
not evaluated; callers should fall back to cached_value and tag the result
`inferred`.

Used by extraction/formula_trace.py to cross-check cached_value during citation
verification.
"""

import re
from typing import Callable

CellLookup = Callable[[str], float | int | str | None]

_SAFE_FUNCS = {"SUM", "AVERAGE", "MIN", "MAX", "IF", "ROUND"}
_CELL_RE = re.compile(r"\$?[A-Z]{1,3}\$?\d+")
_RANGE_RE = re.compile(r"\$?[A-Z]{1,3}\$?\d+:\$?[A-Z]{1,3}\$?\d+")
# 'Sheet Name'!A1 or Sheet1!A1 - resolved through lookup("Sheet Name!A1")
_CROSS_SHEET_CELL_RE = re.compile(r"(?:'([^']+)'|([A-Za-z0-9_]+))!(\$?[A-Z]{1,3}\$?\d+)(?!\s*:)")
# token scanner used to flag anything outside the safe subset
_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\(")


def evaluate(formula: str, lookup: CellLookup) -> tuple[float | int | str | None, bool]:
    """Returns (value, is_safe_subset). is_safe_subset=False means: don't trust `value`,
    fall back to cached_value and tag `inferred` instead of `explicit`.

    `lookup` receives either a plain ref ("A1", the formula's own sheet) or a
    sheet-qualified one ("Other Sheet!A1").
    """
    body = formula[1:] if formula.startswith("=") else formula

    called_funcs = {m.group(0)[:-1].upper() for m in _TOKEN_RE.finditer(body)}
    if called_funcs - _SAFE_FUNCS:
        return None, False

    def _cross_sheet_sub(m: re.Match) -> str:
        sheet = m.group(1) or m.group(2)
        return _literal(lookup(f"{sheet}!{m.group(3).replace('$', '')}"))

    body = _CROSS_SHEET_CELL_RE.sub(_cross_sheet_sub, body)
    # anything still sheet-qualified (a cross-sheet range) isn't resolvable here
    if "!" in body:
        return None, False

    try:
        expr = _to_python_operators(_rewrite(body, lookup))
        value = eval(expr, {"__builtins__": {}}, _SAFE_EVAL_NAMESPACE(lookup))  # noqa: S307 - restricted namespace below
        return value, True
    except Exception:
        return None, False


def _SAFE_EVAL_NAMESPACE(lookup: CellLookup) -> dict:
    def _sum(*args):
        return sum(v for v in _flatten(args) if isinstance(v, (int, float)))

    def _avg(*args):
        vals = [v for v in _flatten(args) if isinstance(v, (int, float))]
        return sum(vals) / len(vals) if vals else 0

    def _min(*args):
        vals = [v for v in _flatten(args) if isinstance(v, (int, float))]
        return min(vals) if vals else 0

    def _max(*args):
        vals = [v for v in _flatten(args) if isinstance(v, (int, float))]
        return max(vals) if vals else 0

    def _if(cond, true_val, false_val=None):
        return true_val if cond else false_val

    def _round(value, digits=0):
        # Excel rounds half away from zero; Python's round() is banker's rounding
        factor = 10 ** int(digits)
        scaled = abs(value) * factor
        rounded = int(scaled + 0.5) / factor
        return rounded if value >= 0 else -rounded

    return {"SUM": _sum, "AVERAGE": _avg, "MIN": _min, "MAX": _max, "IF": _if, "ROUND": _round}


def _to_python_operators(expr: str) -> str:
    """Excel comparison operators -> Python: "<>" is "!=", a lone "=" is "==".
    Only applied outside quoted string literals."""
    parts = re.split(r"('(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\")", expr)
    for i in range(0, len(parts), 2):
        parts[i] = re.sub(r"(?<![<>!=])=(?!=)", "==", parts[i].replace("<>", "!=")).replace("^", "**")
    return "".join(parts)


def _flatten(args):
    for a in args:
        if isinstance(a, (list, tuple)):
            yield from _flatten(a)
        else:
            yield a


def _rewrite(body: str, lookup: CellLookup) -> str:
    """Rewrites ranges to python lists and single cell refs to looked-up values,
    leaving function calls (SUM(...) etc) and arithmetic operators intact for eval().
    """
    # ranges first so single-cell regex doesn't also match pieces of a range
    def _range_sub(m: re.Match) -> str:
        start, end = m.group(0).split(":")
        cells = _expand_range(start, end)
        values = [_literal(lookup(c)) for c in cells]
        return "[" + ", ".join(values) + "]"

    body = _RANGE_RE.sub(_range_sub, body)

    def _cell_sub(m: re.Match) -> str:
        return _literal(lookup(m.group(0).replace("$", "")))

    body = _CELL_RE.sub(_cell_sub, body)
    return body


def _literal(value) -> str:
    if value is None:
        return "0"
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        # cached_value is stored as text, so a numeric cell comes back as e.g.
        # "100000.0" and needs coercing back to a number for arithmetic
        try:
            return repr(int(value))
        except ValueError:
            pass
        try:
            return repr(float(value))
        except ValueError:
            pass
    return repr(str(value))  # genuinely non-numeric text - quote so eval() doesn't choke on it


def _expand_range(start_ref: str, end_ref: str, max_cells: int = 500) -> list[str]:
    sm = _CELL_RE.match(start_ref.replace("$", ""))
    em = _CELL_RE.match(end_ref.replace("$", ""))
    if not sm or not em:
        return []

    col_re = re.compile(r"[A-Z]{1,3}")
    row_re = re.compile(r"\d+")
    c1 = _col_to_num(col_re.match(start_ref.replace("$", "")).group(0))
    r1 = int(row_re.search(start_ref.replace("$", "")).group(0))
    c2 = _col_to_num(col_re.match(end_ref.replace("$", "")).group(0))
    r2 = int(row_re.search(end_ref.replace("$", "")).group(0))

    refs = []
    count = 0
    for r in range(min(r1, r2), max(r1, r2) + 1):
        for c in range(min(c1, c2), max(c1, c2) + 1):
            if count >= max_cells:
                return refs
            refs.append(f"{_num_to_col(c)}{r}")
            count += 1
    return refs


def _col_to_num(col: str) -> int:
    n = 0
    for ch in col:
        n = n * 26 + (ord(ch) - ord("A") + 1)
    return n


def _num_to_col(n: int) -> str:
    out = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        out = chr(rem + ord("A")) + out
    return out
