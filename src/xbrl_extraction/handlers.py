"""
handlers.py — Operations on a loaded Document.

This module BINDS methods onto `schema.Document` rather than defining a
separate class. Importing `xbrl_extraction.handlers` (which happens
automatically via the package `__init__`) adds: filter, to_dataframe,
tree, children_of, parent_of, expand, verify, render_statement, summary.

Why bind onto Document instead of subclassing? Because v1 already has
`Document` as the public type returned by `extract()`. Subclassing
would force every consumer to convert; binding lets them call
`doc.filter(...)` on whatever they already have.

Design rules:
  - Methods that need a linkbase raise RuntimeError with a clear "call
    attach_X first" message when not attached.
  - Filter returns a new Document (chainable). Periods and units are
    pruned to those still referenced.
  - to_dataframe is the exit ramp from the Document world.
  - Strict by default: verify(tolerance=0.0). Generous tolerance hides
    discrepancies, which is the opposite of what verify() is for.
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pandas as _pd

from xbrl_extraction.linkbases import (
    CalcArc,
    Calculations,
    PresArc,
)
from xbrl_extraction.schema import Document, Fact

logger = logging.getLogger(__name__)


# =============================================================================
# Helpers
# =============================================================================


def _require(doc: Document, attr: str, kind: str) -> Any:
    """Return doc.{attr} if attached; else raise a clear RuntimeError."""
    value = getattr(doc, attr)
    if value is None:
        raise RuntimeError(
            f"{kind} not attached. Call doc.attach_{attr}(path) first, "
            f"or use Document.load_all() for auto-discovery."
        )
    return value


def _concept_prefix(concept: str) -> str:
    """`us-gaap:Assets` → `us-gaap`. Returns '' for unprefixed names."""
    return concept.split(":", 1)[0] if ":" in concept else ""


# =============================================================================
# Filtering — returns a new Document
# =============================================================================

_FILTER_KWARGS = {
    "concept",
    "concept_contains",
    "concept_in",
    "period",
    "period_end",
    "period_type",
    "fiscal_year_only",
    "unit",
    "currency",
    "no_dimensions",
    "has_axis",
    "has_member",
    "statement",
    "statement_contains",
    "accounting_standard",
}


def _filter(self: Document, **kwargs) -> Document:
    """
    Return a new Document containing only facts that match every kwarg.

    All filter kwargs AND together. Unknown kwargs raise TypeError.
    The returned Document has its `periods` and `units` dicts pruned
    to only those referenced by the surviving facts. Attached linkbases
    are carried through unchanged.
    """
    unknown = set(kwargs) - _FILTER_KWARGS
    if unknown:
        raise TypeError(
            f"filter() got unexpected keyword argument(s): {sorted(unknown)}. "
            f"Accepted: {sorted(_FILTER_KWARGS)}"
        )

    # Accounting-standard filter: short-circuit if it excludes this doc.
    if kwargs.get("accounting_standard") is not None:
        if self.filing.accounting_standard != kwargs["accounting_standard"]:
            return _empty_clone(self)

    facts = list(self.facts)

    # ── Concept filters ────────────────────────────────────────────
    if (c := kwargs.get("concept")) is not None:
        facts = [f for f in facts if f.concept == c]
    if (c := kwargs.get("concept_contains")) is not None:
        needle = c.lower()
        facts = [f for f in facts if needle in f.concept.lower()]
    if (lst := kwargs.get("concept_in")) is not None:
        wanted = set(lst)
        facts = [f for f in facts if f.concept in wanted]

    # ── Period filters ─────────────────────────────────────────────
    if (p := kwargs.get("period")) is not None:
        facts = [f for f in facts if f.period == p]

    if (pe := kwargs.get("period_end")) is not None:
        # Match against either instant.date or duration.end
        matching_ctxs = {
            cid
            for cid, ctx in self.periods.items()
            if (ctx.type == "instant" and ctx.date == pe)
            or (ctx.type == "duration" and ctx.end == pe)
        }
        facts = [f for f in facts if f.period in matching_ctxs]

    if (pt := kwargs.get("period_type")) is not None:
        if pt not in ("instant", "duration"):
            raise ValueError(f"period_type must be 'instant' or 'duration', got {pt!r}")
        matching_ctxs = {cid for cid, ctx in self.periods.items() if ctx.type == pt}
        facts = [f for f in facts if f.period in matching_ctxs]

    if kwargs.get("fiscal_year_only"):
        fy_end = self.filing.period_end
        if fy_end:
            # The FY context is the longest duration ending on period_end.
            fy_ctxs = [
                cid
                for cid, ctx in self.periods.items()
                if ctx.type == "duration" and ctx.end == fy_end
            ]
            # Pick the one with the earliest start (full year, not Q4)
            if fy_ctxs:
                fy_ctxs.sort(key=lambda cid: self.periods[cid].start or "")
                target = fy_ctxs[0]
                facts = [f for f in facts if f.period == target]
            else:
                facts = []

    # ── Unit filters ───────────────────────────────────────────────
    if (u := kwargs.get("unit")) is not None:
        facts = [f for f in facts if f.unit == u]
    if kwargs.get("currency"):
        currency_units = {
            uid for uid, unit in self.units.items() if (unit.measure or "").startswith("iso4217:")
        }
        facts = [f for f in facts if f.unit in currency_units]

    # ── Dimension filters ──────────────────────────────────────────
    if kwargs.get("no_dimensions"):
        facts = [f for f in facts if not f.dimensions]
    if (axis := kwargs.get("has_axis")) is not None:
        facts = [f for f in facts if axis in f.dimensions]
    if (mem := kwargs.get("has_member")) is not None:
        facts = [f for f in facts if mem in f.dimensions.values()]

    # ── Statement filter (needs pres) ──────────────────────────────
    if (s := kwargs.get("statement")) is not None:
        pres = _require(self, "pres", "Presentation")
        concepts_in_stmt = {a.child for a in pres.arcs if a.role_short == s} | {
            a.parent for a in pres.arcs if a.role_short == s
        }
        facts = [f for f in facts if f.concept in concepts_in_stmt]

    if (sc := kwargs.get("statement_contains")) is not None:
        pres = _require(self, "pres", "Presentation")
        needle = sc.lower()
        roles = {a.role_short for a in pres.arcs if needle in (a.role_definition or "").lower()}
        concepts_in = {a.child for a in pres.arcs if a.role_short in roles} | {
            a.parent for a in pres.arcs if a.role_short in roles
        }
        facts = [f for f in facts if f.concept in concepts_in]

    return _rebuild(self, facts)


def _empty_clone(self: Document) -> Document:
    """Return a Document with the same filing but no facts."""
    return Document(
        filing=self.filing,
        periods={},
        units={},
        facts=[],
        calc=self.calc,
        pres=self.pres,
        labs=self.labs,
        defs=self.defs,
    )


def _rebuild(self: Document, facts: list[Fact]) -> Document:
    """Rebuild a Document with filtered facts and pruned period/unit dicts."""
    used_periods = {f.period for f in facts}
    used_units = {f.unit for f in facts}
    return Document(
        filing=self.filing,
        periods={k: v for k, v in self.periods.items() if k in used_periods},
        units={k: v for k, v in self.units.items() if k in used_units},
        facts=facts,
        calc=self.calc,
        pres=self.pres,
        labs=self.labs,
        defs=self.defs,
    )


# =============================================================================
# DataFrame export — exit ramp from the Document world
# =============================================================================


def _to_dataframe(self: Document) -> _pd.DataFrame:
    """Flatten facts to a long-format pandas DataFrame.

    Denormalises period and unit metadata into per-row columns. The
    `dimensions` column holds a dict per row (or NaN if empty). When
    labels are attached, a `label` column carries the resolved
    standardLabel for each concept.
    """
    import pandas as pd

    label_lookup = None
    if self.labs is not None:
        label_lookup = self.labs

    rows = []
    for f in self.facts:
        period = self.periods.get(f.period)
        unit = self.units.get(f.unit)

        row = {
            "concept": f.concept,
            "value": f.value,
            "unit": f.unit,
            "unit_measure": (
                unit.measure
                if unit and unit.measure
                else f"{unit.numerator}/{unit.denominator}" if unit else None
            ),
            "period": f.period,
            "period_type": period.type if period else None,
            "period_start": period.start if period else None,
            "period_end": period.end if period else None,
            "period_date": period.date if period else None,
            "scale": f.scale,
            "decimals": f.decimals,
            "dimensions": dict(f.dimensions) if f.dimensions else None,
            "source_file": self.filing.source_file,
        }
        if label_lookup is not None:
            row["label"] = label_lookup.get(f.concept)
        rows.append(row)

    return pd.DataFrame(rows)


# =============================================================================
# Calc-aware navigation
# =============================================================================


def _arcs_for_role(calc: Calculations, role_short: str | None) -> list[CalcArc]:
    """Filter calc arcs to a single role (or return all if None)."""
    if role_short is None:
        return calc.arcs
    return [a for a in calc.arcs if a.role_short == role_short]


def _children_of(self: Document, concept: str, role_short: str | None = None) -> list[dict]:
    """Children of `concept` in the calc graph.

    If role_short is None, returns children across every role the
    concept appears as parent in (useful for "anywhere this rolls up").
    """
    calc = _require(self, "calc", "Calculations")
    out = []
    for a in _arcs_for_role(calc, role_short):
        if a.parent == concept:
            out.append(
                {
                    "concept": a.child,
                    "weight": a.weight,
                    "order": a.order,
                    "role": a.role_short,
                }
            )
    out.sort(key=lambda r: (r["role"], r["order"]))
    return out


def _parent_of(self: Document, concept: str, role_short: str | None = None) -> list[dict]:
    """Parents of `concept` in the calc graph."""
    calc = _require(self, "calc", "Calculations")
    out = []
    for a in _arcs_for_role(calc, role_short):
        if a.child == concept:
            out.append(
                {
                    "concept": a.parent,
                    "weight": a.weight,
                    "role": a.role_short,
                }
            )
    return out


def _tree(self: Document, role_short: str) -> dict:
    """Return the calc tree for a role as nested dicts.

    Shape:
      { parent_concept: { child_concept: {...nested...}, ... }, ... }

    A "root" is any parent that doesn't itself appear as a child within
    the role. Most roles have one root; some have several (separate
    rollups in the same role).
    """
    calc = _require(self, "calc", "Calculations")
    arcs = _arcs_for_role(calc, role_short)

    children_by_parent: dict[str, list[CalcArc]] = defaultdict(list)
    is_child: set[str] = set()
    for a in arcs:
        children_by_parent[a.parent].append(a)
        is_child.add(a.child)

    def build(node: str) -> dict:
        return {
            child.child: build(child.child)
            for child in sorted(children_by_parent.get(node, []), key=lambda x: x.order)
        }

    roots = sorted(set(children_by_parent.keys()) - is_child)
    return {r: build(r) for r in roots}


def _expand(self: Document, concept: str, role_short: str, period_end: str) -> _pd.DataFrame:
    """Walk `concept` and its descendants in the calc tree for one role,
    returning a DataFrame.

    Columns: concept, depth, weight_path, value, label.

    `weight_path` is the product of weights along the path from the
    starting concept. So a child reached via a -1 arc has weight_path=-1;
    its child reached via a +1 arc has weight_path=-1 (not flipped twice).
    """
    import pandas as pd

    calc = _require(self, "calc", "Calculations")
    arcs = _arcs_for_role(calc, role_short)
    children_by_parent: dict[str, list[CalcArc]] = defaultdict(list)
    for a in arcs:
        children_by_parent[a.parent].append(a)

    # Build a lookup for fact values by (concept, period_end).
    # We allow any period whose end matches; in dimensional notes the
    # same concept may have many; we take any non-dimensional one.
    value_by_concept = _values_at(self, period_end)

    rows = []

    def walk(node: str, depth: int, weight_path: float):
        label = self.labs.get(node) if self.labs is not None else None
        rows.append(
            {
                "concept": node,
                "depth": depth,
                "weight_path": weight_path,
                "value": value_by_concept.get(node),
                "label": label,
            }
        )
        for child_arc in sorted(children_by_parent.get(node, []), key=lambda x: x.order):
            walk(child_arc.child, depth + 1, weight_path * child_arc.weight)

    walk(concept, 0, 1.0)
    return pd.DataFrame(rows)


def _values_at(self: Document, period_end: str) -> dict[str, float]:
    """Map concept → fact value for `period_end`, preferring
    non-dimensional facts. Used by expand() and verify()."""
    matching_ctxs = {
        cid
        for cid, ctx in self.periods.items()
        if (ctx.type == "instant" and ctx.date == period_end)
        or (ctx.type == "duration" and ctx.end == period_end)
    }
    result: dict[str, float] = {}
    for f in self.facts:
        if f.period not in matching_ctxs:
            continue
        if f.dimensions:
            continue  # skip segment breakdowns
        # First match wins; facts are concept-sorted, so this is stable
        result.setdefault(f.concept, f.value)
    return result


# =============================================================================
# verify() — does calc actually balance against the facts?
# =============================================================================


def _verify(
    self: Document,
    role_short: str | None = None,
    period_end: str | None = None,
    tolerance: float = 0.0,
) -> _pd.DataFrame:
    """Verify calc arithmetic against actual facts for a given period.

    For each parent in the calc graph (filtered by role_short if given),
    compute expected = Σ(weight × child_value) and compare to the
    actual parent fact value. Returns a DataFrame:
      parent | expected | actual | diff | status | role

    Status taxonomy:
      "match"            — exact match (or |diff| <= tolerance)
      "rounding"         — |diff| > 0 but <= tolerance (only when tolerance > 0)
      "mismatch"         — |diff| > tolerance
      "missing_children" — at least one child has no fact for this period
      "missing_parent"   — parent has no fact for this period (we still
                           report expected so the user can fill it in)

    Default tolerance is STRICT (0.0). The whole point of verify() is to
    catch discrepancies; pass tolerance=1.0 (or your value's natural
    rounding unit) to ignore filer rounding.
    """
    import pandas as pd

    calc = _require(self, "calc", "Calculations")
    if period_end is None:
        period_end = self.filing.period_end
    if not period_end:
        raise ValueError(
            "verify() needs a period_end; either pass one explicitly "
            "or ensure doc.filing.period_end is set."
        )

    values = _values_at(self, period_end)

    arcs = _arcs_for_role(calc, role_short)
    by_parent: dict[tuple[str, str], list[CalcArc]] = defaultdict(list)
    for a in arcs:
        by_parent[(a.parent, a.role_short)].append(a)

    rows = []
    for (parent, role), children in by_parent.items():
        actual = values.get(parent)
        # Compute expected sum, tracking missing children
        missing = [c.child for c in children if c.child not in values]
        if missing:
            status = "missing_children"
            expected = None
            diff = None
        else:
            expected = sum(values[c.child] * c.weight for c in children)
            if actual is None:
                status = "missing_parent"
                diff = None
            else:
                diff = actual - expected
                abs_diff = abs(diff)
                if abs_diff == 0:
                    status = "match"
                elif abs_diff <= tolerance:
                    status = "rounding"
                else:
                    status = "mismatch"
        rows.append(
            {
                "parent": parent,
                "expected": expected,
                "actual": actual,
                "diff": diff,
                "status": status,
                "role": role,
            }
        )

    df = pd.DataFrame(rows).sort_values(["role", "parent"]).reset_index(drop=True)
    return df


# =============================================================================
# Statement reconstruction — the indented +/- terminal print
# =============================================================================


def _render_statement(self: Document, role_short: str, period_end: str, print: bool = False) -> str:
    """Render a single statement at a single period as indented text.

    Requires `pres` (for structure) and `calc` (for the +/- signs).
    `labs` is optional; without it, raw concept names are shown.

    Layout (single period only — multi-period side-by-side is v3):

        <Statement title> — period ending YYYY-MM-DD (in <scale> <unit>)

          <Section header>
            <Subtotal>                                       123,456
              + <Leaf concept>                                12,345
              + <Leaf concept>                                23,456
              - <Leaf concept>                               (12,345)
          ...

    Indentation reflects the presentation tree depth. The sign prefix on
    leaves comes from the calc weight relative to the immediate parent.
    Subtotals (non-leaves) get no sign. Header rows (abstracts with no
    fact value) get no sign and no value column.

    Returns the rendered string. Pass print=True to also write it to
    stdout (handy in notebooks).
    """
    pres_obj = _require(self, "pres", "Presentation")
    # calc is desirable for signs but not strictly required — fall back
    # to all-plus rendering when calc is missing.
    calc_obj = self.calc

    # Build pres tree for this role
    pres_arcs = [a for a in pres_obj.arcs if a.role_short == role_short]
    if not pres_arcs:
        raise ValueError(
            f"render_statement: no presentation arcs for role_short={role_short!r}. "
            f"Use doc.summary() to list available statements."
        )

    children_by_parent: dict[str, list[PresArc]] = defaultdict(list)
    is_child: set[str] = set()
    for a in pres_arcs:
        children_by_parent[a.parent].append(a)
        is_child.add(a.child)
    roots = sorted(set(children_by_parent.keys()) - is_child)

    # Build calc weight lookup: weight by child concept, for this role.
    # The presentation parent and calc parent may differ (pres often has
    # an Abstract concept as parent where calc has the concrete subtotal).
    # We default to looking up by child within the same role; if that's
    # ambiguous (same child appears under multiple parents with different
    # weights) the first arc in document order wins.
    calc_weight_by_child: dict[str, float] = {}
    calc_parents_here: set[str] = set()
    if calc_obj is not None:
        for a in calc_obj.arcs:
            if a.role_short == role_short:
                calc_weight_by_child.setdefault(a.child, a.weight)
                calc_parents_here.add(a.parent)

    # Resolve values for this period
    values = _values_at(self, period_end)

    # Find a representative scale for the value column
    scales = Counter()
    for c in is_child | set(children_by_parent.keys()):
        for f in self.facts:
            if f.concept == c and f.scale and not f.dimensions:
                scales[f.scale] += 1
                break
    common_scale = scales.most_common(1)[0][0] if scales else None
    scale_label = _scale_label(common_scale)

    # Resolve currency
    currency = _common_currency(self) or "USD"

    # Statement title
    title = ""
    for a in pres_arcs:
        if a.role_definition:
            title = a.role_definition
            break
    title = title or role_short

    # Render
    lines: list[str] = []
    lines.append(f"{title} — period ending {period_end} ({scale_label} {currency})".rstrip())
    lines.append("")

    def label_for(concept: str, preferred: str | None) -> str:
        if self.labs is not None:
            text = self.labs.get(concept, preferred_label=preferred)
            if text:
                return text
        return concept

    def render(node: str, depth: int, parent: str | None, preferred: str | None):
        children = sorted(children_by_parent.get(node, []), key=lambda x: x.order)
        is_leaf = not children
        has_value = node in values

        # Determine sign prefix: leaf-level concepts (no calc children) only.
        # A pres-leaf that's also a calc-parent is a SUBTOTAL — render
        # without a sign even though it has a calc weight as someone
        # else's child.
        sign = "  "
        is_calc_subtotal = node in calc_parents_here
        if is_leaf and not is_calc_subtotal:
            w = calc_weight_by_child.get(node)
            if w is not None:
                sign = "+ " if w >= 0 else "- "

        # Abstract / header rows have no value — they're organisational
        # headers in the pres tree. We detect via "Abstract" suffix or
        # the absence of a fact value while having children. Be loose:
        # if it has children OR no value, treat as header.
        is_header = node.endswith("Abstract") or (not is_leaf and not has_value)

        indent = "  " * (depth + 1)
        label = label_for(node, preferred)

        if is_header:
            lines.append(f"{indent}{sign}{label}")
        elif has_value:
            val = values[node]
            val_str = _format_value(val)
            # Left column: indent + sign + label; right column: value
            left = f"{indent}{sign}{label}"
            # Pad to a target width so values right-align
            target_width = 60
            pad = max(2, target_width - len(left))
            lines.append(f"{left}{' ' * pad}{val_str:>15}")
        else:
            # Has no value and is a leaf — show as a missing fact.
            lines.append(f"{indent}{sign}{label}  [no value]")

        for c in children:
            render(c.child, depth + 1, node, c.preferred_label)

    for root in roots:
        render(root, 0, None, None)
        lines.append("")

    output = "\n".join(lines).rstrip() + "\n"
    if print:
        import builtins

        builtins.print(output)
    return output


def _scale_label(scale: str | None) -> str:
    if scale is None:
        return "as filed"
    s = str(scale)
    if s in ("3", "-3"):
        return "in thousands"
    if s in ("6", "-6"):
        return "in millions"
    if s in ("9", "-9"):
        return "in billions"
    return f"scale={s}"


def _common_currency(doc: Document) -> str | None:
    """Sniff the dominant currency. Returns 'USD'/'EUR'/etc. or None."""
    counts = Counter()
    for unit in doc.units.values():
        m = unit.measure or ""
        if m.startswith("iso4217:"):
            counts[m.split(":", 1)[1]] += 1
    if not counts:
        return None
    return counts.most_common(1)[0][0]


def _format_value(v: float) -> str:
    """Accounting-style: 1,234,567 or (1,234,567) for negatives."""
    if v < 0:
        return f"({abs(v):,.0f})"
    return f"{v:,.0f}"


# =============================================================================
# summary() — quick sanity check
# =============================================================================


def _summary(self: Document) -> str:
    """One-page text overview of the filing, useful in notebooks."""
    f = self.filing

    lines: list[str] = []
    title = f"{f.form or 'Unknown form'} — FY{f.fiscal_year or '?'}"
    if f.accounting_standard:
        title += f" ({f.accounting_standard})"
    lines.append(title)
    lines.append(f"  Source:    {f.source_file}")
    lines.append(f"  Primary:   {f.primary_document}")
    if f.period_end:
        lines.append(f"  Period end: {f.period_end}")
    lines.append("")

    # ── Facts breakdown ───────────────────────────────────────────
    lines.append(f"Facts: {len(self.facts):>5}")
    by_ns = Counter(_concept_prefix(fa.concept) for fa in self.facts)
    if by_ns:
        lines.append("  By namespace:")
        for ns, n in by_ns.most_common(8):
            lines.append(f"    {(ns + ':').ljust(28)} {n}")

    by_type = Counter(
        self.periods[fa.period].type for fa in self.facts if fa.period in self.periods
    )
    if by_type:
        lines.append("  By period type:")
        for pt, n in by_type.most_common():
            lines.append(f"    {pt.ljust(28)} {n}")

    dim_count = sum(1 for fa in self.facts if fa.dimensions)
    if self.facts:
        pct = dim_count * 100 // len(self.facts)
        lines.append(f"  Dimensional facts:           {dim_count} ({pct}%)")

    if dim_count:
        axis_counts = Counter()
        for fa in self.facts:
            for axis in fa.dimensions:
                axis_counts[axis] += 1
        lines.append("  Top axes:")
        for axis, n in axis_counts.most_common(5):
            lines.append(f"    {axis[:38].ljust(40)} {n}")

    # ── Attached linkbases ────────────────────────────────────────
    lines.append("")
    lines.append("Attached linkbases:")
    if self.calc is not None:
        n_arcs = len(self.calc.arcs)
        n_roles = len({a.role_short for a in self.calc.arcs})
        lines.append(f"  ✓ calc  ({n_arcs} arcs across {n_roles} roles)")
    else:
        lines.append("  ✗ calc  (not attached)")

    if self.pres is not None:
        n_arcs = len(self.pres.arcs)
        n_stmts = len({a.role_short for a in self.pres.arcs})
        lines.append(f"  ✓ pres  ({n_arcs} arcs, {n_stmts} statements)")
    else:
        lines.append("  ✗ pres  (not attached)")

    if self.labs is not None:
        lines.append(f"  ✓ labs  ({len(self.labs.entries)} labels)")
    else:
        lines.append("  ✗ labs  (not attached)")

    if self.defs is not None:
        lines.append(f"  ✓ defs  ({len(self.defs.arcs)} arcs)")
    else:
        lines.append("  ✗ defs  (not attached)")

    return "\n".join(lines) + "\n"


# =============================================================================
# Bind methods onto Document
# =============================================================================

# We attach these as plain methods so `doc.filter(...)` works and shows
# up in tab-completion. The dataclass `Document` is mutable at the class
# level — assignment here is permanent for the rest of the session.

Document.filter = _filter  # type: ignore[attr-defined]
Document.to_dataframe = _to_dataframe  # type: ignore[attr-defined]
Document.children_of = _children_of  # type: ignore[attr-defined]
Document.parent_of = _parent_of  # type: ignore[attr-defined]
Document.tree = _tree  # type: ignore[attr-defined]
Document.expand = _expand  # type: ignore[attr-defined]
Document.verify = _verify  # type: ignore[attr-defined]
Document.render_statement = _render_statement  # type: ignore[attr-defined]
Document.summary = _summary  # type: ignore[attr-defined]
