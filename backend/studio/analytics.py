"""Deterministic data intelligence, safe calculations and one shared query engine.

No user configuration is executed as Python or SQL. JSON outputs never contain
NaN/Infinity. The renderer consumes labels/series for aggregates, rows for
record-oriented plots, and the explicit matrix/nodes/links for advanced plots.
"""
from __future__ import annotations

import ast
import calendar
import datetime as dt
import hashlib
import json
import math
import operator
import re
import statistics
from collections import Counter, defaultdict
from typing import Any

MAX_GROUPS = 1000
MAX_POINTS = 5000
NUMERIC_TYPES = {"numeric", "currency", "percentage", "ordinal"}
DATE_TYPES = {"date", "datetime", "time"}
FIELD_TYPES = NUMERIC_TYPES | DATE_TYPES | {"categorical", "boolean", "identifier", "text", "geographic"}


def missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip()) or (isinstance(value, float) and not math.isfinite(value))


def number(value: Any) -> float | None:
    if missing(value) or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        result = float(value)
    elif isinstance(value, str):
        text = value.strip().replace(",", "").replace("\u00a0", "")
        percent = text.endswith("%")
        text = re.sub(r"^[£$€¥₹]\s*", "", text).rstrip("%")
        if text.startswith("(") and text.endswith(")"):
            text = "-" + text[1:-1]
        try:
            result = float(text)
        except (ValueError, TypeError):
            return None
        if percent:
            result /= 100
    else:
        return None
    return result if math.isfinite(result) else None


def date_value(value: Any) -> dt.datetime | None:
    if isinstance(value, dt.datetime):
        return value.astimezone(dt.timezone.utc).replace(tzinfo=None) if value.tzinfo else value
    if isinstance(value, dt.date):
        return dt.datetime.combine(value, dt.time())
    if not isinstance(value, str) or len(value) > 60:
        return None
    value = value.strip()
    if not value or not re.search(r"[-/:T]", value):
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(dt.timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%b %d, %Y", "%H:%M:%S", "%H:%M"):
        try:
            return dt.datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _safe(value: Any) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(v) for v in value]
    return value


def _key(value: Any) -> str:
    return json.dumps(_safe(value), sort_keys=True, default=str, ensure_ascii=False)


def _columns(rows: list[dict]) -> list[str]:
    return list(dict.fromkeys(str(key) for row in rows for key in row))


def _infer(name: str, values: list) -> str:
    if not values:
        return "text"
    lower = name.lower().strip()
    tokens = re.sub(r"[_\W]+", " ", lower).split()
    if re.search(r"(^|[ _-])(id|uuid|code|sku|zip|postal|invoice|account|phone)([ _-]|$)", lower) or lower.endswith("id") and lower not in {"paid", "valid"}:
        return "identifier"
    if all(isinstance(v, bool) or str(v).lower() in {"true", "false", "yes", "no"} for v in values):
        return "boolean"
    numbers = [number(v) for v in values]
    if sum(n is not None for n in numbers) / len(values) >= .95:
        if any("%" in str(v) for v in values) or any(t in {"percent", "percentage", "rate", "ratio"} for t in tokens):
            return "percentage"
        if any(re.search(r"[£$€¥₹]", str(v)) for v in values) or any(t in {"revenue", "price", "cost", "profit", "salary", "income", "expense", "amount"} for t in tokens):
            return "currency"
        if any(t in {"latitude", "longitude", "lat", "lon", "lng"} for t in tokens):
            return "geographic"
        if any(t in {"rank", "rating", "priority", "level"} for t in tokens):
            return "ordinal"
        return "numeric"
    dates = [date_value(v) for v in values]
    if sum(d is not None for d in dates) / len(values) >= .9:
        if all(re.match(r"^\d{1,2}:\d{2}", str(v)) for v in values):
            return "time"
        return "datetime" if any(d and d.time() != dt.time() for d in dates) else "date"
    if any(t in {"country", "state", "city", "continent"} for t in tokens):
        return "geographic"
    cardinality = len({_key(v) for v in values})
    return "categorical" if cardinality <= max(30, len(values) * .5) else "text"


def _coordinate_name(name: str) -> str | None:
    name = re.sub(r"[\s_-]+", "", str(name)).casefold()
    if name in {"latitude", "lat"}:
        return "latitude"
    if name in {"longitude", "lon", "lng"}:
        return "longitude"
    return None


def profile(rows: list[dict], overrides: dict | None = None) -> dict:
    """Profile real records, preserving every source field and null count."""
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("Dataset records must be a list of objects.")
    overrides = overrides or {}
    names = _columns(rows)
    unknown = set(overrides) - set(names)
    if unknown:
        raise ValueError(f"Unknown column: {sorted(unknown)[0]}")
    if any(value not in FIELD_TYPES for value in overrides.values()):
        raise ValueError("Unsupported column type.")
    result = {"row_count": len(rows), "column_count": len(names), "columns": [], "duplicates": len(rows) - len({_key(row) for row in rows}), "warnings": [], "relationships": [], "surface_candidates": [], "regression_candidates": [], "coordinate_candidates": []}
    if result["duplicates"]:
        result["warnings"].append(f'{result["duplicates"]} duplicate records; original data is preserved until you choose to clean it.')
    for name in names:
        values = [row.get(name) for row in rows if not missing(row.get(name))]
        kind = overrides.get(name) or _infer(name, values)
        col = {"name": name, "type": kind, "missing": len(rows) - len(values), "unique": len({_key(v) for v in values})}
        col["missing_percent"] = round(col["missing"] / len(rows) * 100, 2) if rows else 0
        if not values:
            result["warnings"].append(f"{name}: column contains no usable values.")
        if col["missing_percent"] >= 20:
            result["warnings"].append(f'{name}: {col["missing_percent"]}% missing values.')
        if kind in NUMERIC_TYPES or (kind == "geographic" and all(number(v) is not None for v in values)):
            nums = [n for v in values if (n := number(v)) is not None]
            invalid = len(values) - len(nums)
            col["invalid"] = invalid
            if nums:
                col.update(min=min(nums), max=max(nums), mean=statistics.mean(nums), median=statistics.median(nums), std=statistics.pstdev(nums), sum=sum(nums))
                if len(nums) >= 4:
                    q1, _, q3 = statistics.quantiles(nums, n=4, method="inclusive")
                    iqr = q3 - q1
                    col["outliers"] = sum(n < q1 - iqr * 1.5 or n > q3 + iqr * 1.5 for n in nums) if iqr else sum(n != q1 for n in nums)
                    if col["outliers"]:
                        result["warnings"].append(f'{name}: {col["outliers"]} possible outliers (IQR rule).')
            if invalid:
                result["warnings"].append(f"{name}: {invalid} values could not be interpreted as numbers.")
        elif kind in DATE_TYPES:
            dates = [d for v in values if (d := date_value(v))]
            col["invalid"] = len(values) - len(dates)
            if dates:
                ordered = sorted(set(dates))
                gaps = [(b - a).total_seconds() for a, b in zip(ordered, ordered[1:])]
                col.update(min=min(dates).isoformat(), max=max(dates).isoformat(), interval_seconds=statistics.median(gaps) if gaps else None)
            if col["invalid"]:
                result["warnings"].append(f'{name}: {col["invalid"]} invalid dates.')
        else:
            counts = Counter(_key(v) for v in values)
            originals = {_key(v): v for v in values}
            col["categories"] = [{"value": originals[k], "count": n} for k, n in counts.most_common(100)]
            if kind in {"categorical", "geographic", "text"}:
                clean = [str(v).strip().casefold() for v in values]
                if len(set(clean)) < col["unique"]:
                    result["warnings"].append(f"{name}: category spellings differ only in case or surrounding spaces.")
        result["columns"].append(col)
    latitude = [c for c in result["columns"] if _coordinate_name(c["name"]) == "latitude" and "min" in c and c["min"] >= -90 and c["max"] <= 90]
    longitude = [c for c in result["columns"] if _coordinate_name(c["name"]) == "longitude" and "min" in c and c["min"] >= -180 and c["max"] <= 180]
    result["coordinate_candidates"] = [{"x": lon["name"], "y": lat["name"]} for lon in longitude for lat in latitude]
    nums = [c["name"] for c in result["columns"] if c["type"] in NUMERIC_TYPES][:12]
    for i, x in enumerate(nums):
        for y in nums[i+1:]:
            pairs = [(number(r.get(x)), number(r.get(y))) for r in rows]
            pairs = [(a, b) for a, b in pairs if a is not None and b is not None]
            if len(pairs) >= 2:
                xs, ys = zip(*pairs)
                if len(set(xs)) > 1:
                    result["regression_candidates"].append({"x": x, "y": y, "n": len(pairs)})
                elif len(set(ys)) > 1:
                    result["regression_candidates"].append({"x": y, "y": x, "n": len(pairs)})
                if len(pairs) >= 3 and len(set(xs)) > 1 and len(set(ys)) > 1:
                    result["relationships"].append({"x": x, "y": y, "correlation": statistics.correlation(xs, ys)})
    # A surface needs a meaningful sampled 2D grid, not three arbitrary columns.
    for i, x in enumerate(nums[:8]):
        for y in nums[i+1:8]:
            points = {(number(row.get(x)), number(row.get(y))) for row in rows if number(row.get(x)) is not None and number(row.get(y)) is not None}
            xs, ys = {a for a,b in points}, {b for a,b in points}
            if 2 <= len(xs) <= 100 and 2 <= len(ys) <= 100 and len(points) / (len(xs)*len(ys)) >= .5:
                z = next((name for name in nums if name not in {x,y}), None)
                if z:
                    result["surface_candidates"].append({"x": x, "y": y, "z": z})
    # Only recommend intervals explicitly supplied by the source, never infer a
    # confidence level or aggregate interval endpoints into fabricated certainty.
    lower_fields = [name for name in nums if re.search(r'(^|[ _])(lower|low|lcl)([ _]|$)', name, re.I)]
    upper_fields = [name for name in nums if re.search(r'(^|[ _])(upper|high|ucl)([ _]|$)', name, re.I)]
    dimensions = [c['name'] for c in result['columns'] if c['type'] in DATE_TYPES or c['type'] in {'categorical', 'ordinal'}]
    result['interval_candidates'] = []
    for lower in lower_fields[:3]:
        for upper in upper_fields[:3]:
            for center in [name for name in nums if name not in lower_fields + upper_fields][:6]:
                paired = [(number(row.get(lower)), number(row.get(center)), number(row.get(upper))) for row in rows]
                paired = [values for values in paired if all(value is not None for value in values)]
                dimension = next((name for name in dimensions + nums if name not in {lower, upper, center}), None)
                if paired and dimension and all(a <= b <= c for a, b, c in paired):
                    result['interval_candidates'].append({'x': dimension, 'y': center, 'lower': lower, 'upper': upper})
    return _safe(result)


# Requirements are descriptive and evaluated below; registered IDs match real
# supported frontend renderers, including actual WebGL mesh-based 3D pies.
_CHART_GROUPS = {
    "Comparisons": [("bar", "Column"), ("horizontal_bar", "Horizontal bar"), ("grouped_bar", "Grouped bar"), ("stacked_bar", "Stacked bar"), ("percent_bar", "100% stacked bar"), ("ranking", "Ranking"), ("waterfall", "Waterfall"), ("bullet", "Actual vs target"), ("radar", "Radar")],
    "Trends": [("line", "Line"), ("smooth_line", "Smooth line"), ("step_line", "Step line"), ("area", "Area"), ("stacked_area", "Stacked area"), ("cumulative", "Cumulative"), ("moving_average", "Moving average"), ("calendar", "Calendar heatmap"), ("timeline", "Timeline"), ("gantt", "Gantt")],
    "Composition": [("pie", "Pie"), ("pie3d", "3D pie"), ("donut", "Doughnut"), ("semi_donut", "Semi-doughnut"), ("treemap", "Treemap"), ("sunburst", "Sunburst"), ("funnel", "Funnel"), ("sankey", "Sankey")],
    "Distributions": [("histogram", "Histogram"), ("box", "Box plot"), ("violin", "Violin plot"), ("density", "Density curve"), ("pareto", "Pareto")],
    "Relationships": [("scatter", "Scatter"), ("regression", "Regression line"), ("bubble", "Bubble"), ("heatmap", "Correlation heatmap"), ("scatter3d", "3D scatter"), ("surface3d", "3D surface"), ("bar3d", "3D bars")],
    "Geographic": [("map", "Geographic map")],
    "KPI Suggestions": [("kpi", "KPI"), ("gauge", "Gauge"), ("progress", "Progress")],
    "Tables": [("table", "Data table"), ("pivot", "Pivot table"), ("summary", "Summary table")],
}
CHART_TYPES = [{"id": key, "name": name, "group": group} for group, items in _CHART_GROUPS.items() for key, name in items]
CHART_TYPES.extend([
    {'id': 'confidence_band', 'name': 'Provided interval band', 'group': 'Trends'},
    {'id': 'chord', 'name': 'Weighted chord diagram', 'group': 'Relationships'},
])
CHART_IDS = {item["id"] for item in CHART_TYPES}


def compatible(metadata: dict) -> list[dict]:
    cols = metadata.get("columns", [])
    nums = [c for c in cols if c["type"] in NUMERIC_TYPES and c.get("unique", 0) > 0 and "min" in c]
    cats = [c for c in cols if (c["type"] in {"categorical", "boolean", "ordinal"} or c["type"] == "geographic" and "categories" in c) and 0 < c.get("unique", 0) <= 100]
    nonnegative = [c for c in nums if c.get("min", 0) >= 0]
    targets = [c for c in nonnegative if re.search(r'\b(target|goal|budget|quota|capacity)\b', c['name'], re.I) and c.get('sum', 0) > 0]
    dates = [c for c in cols if c["type"] in DATE_TYPES]
    results = []
    for item in CHART_TYPES:
        kind, reason = item["id"], ""
        if kind in {"table", "summary"}:
            okay = bool(cols)
        elif kind == "pivot":
            okay = bool(cats and nums)
        elif kind == 'confidence_band':
            okay = bool(metadata.get('interval_candidates'))
            reason = 'Needs actual lower/upper interval columns, an observed center, and a distinct dimension. No confidence level is inferred.'
        elif kind == "map":
            okay = bool(metadata.get("coordinate_candidates"))
            reason = "Needs explicitly named Latitude/Lat and Longitude/Lon/Lng numerical columns with valid coordinate ranges."
        elif kind == "regression":
            okay = bool(metadata.get("regression_candidates") or metadata.get("relationships"))
            reason = "Needs two paired numerical measures and variation in X."
        elif kind == "density":
            okay = any(c.get("unique", 0) > 1 for c in nums)
            reason = "Needs at least two distinct numerical values."
        elif kind in {"scatter", "bubble", "heatmap"}:
            okay = len(nums) >= (3 if kind == "bubble" else 2)
            reason = "Needs at least two numerical measures." if kind != "bubble" else "Needs three numerical measures."
        elif kind == "surface3d":
            okay = bool(metadata.get("surface_candidates"))
            reason = "Needs three measures with a sufficiently dense X/Y coordinate grid."
        elif kind in {"scatter3d", "bar3d"}:
            okay = len(nums) >= 3
            reason = "Needs three numerical measures."
        elif kind in {"line", "smooth_line", "step_line", "area", "stacked_area", "cumulative", "moving_average", "calendar", "timeline"}:
            okay = bool(dates and nums)
            reason = "Needs a date/time field and a numerical measure."
        elif kind == "gantt":
            okay = len(dates) >= 2 and bool(cats)
            reason = "Needs task names and two date fields (start and end)."
        elif kind in {"sankey", "chord"}:
            okay = len(cats) >= 2 and bool(nonnegative)
            reason = "Needs two categorical stages and a non-negative numerical flow measure."
        elif kind in {'gauge', 'progress'}:
            okay = bool(targets and any(c['name'] != targets[0]['name'] for c in nums))
            reason = 'Needs an actual measure and a positive target/goal column. For a manual goal, add a KPI, set its Target, then change its visualization.'
        elif kind in {"histogram", "box", "violin", "kpi"}:
            okay = bool(nums) or kind == "kpi"
            reason = "Needs a numerical measure."
        elif kind in {"pie", "pie3d", "donut", "semi_donut", "treemap", "sunburst", "funnel", "pareto"}:
            okay = bool(cats and nonnegative)
            reason = "Needs categories and a non-negative numerical contribution measure."
        elif kind == "bullet":
            okay = len(nums) >= 2
            reason = "Needs actual and target numerical measures."
        elif kind in {"grouped_bar", "stacked_bar", "percent_bar"}:
            measures = nonnegative if kind == "percent_bar" else nums
            okay = bool(cats and measures) and (len(cats) >= 2 or len(measures) >= 2)
            reason = "Needs a category and multiple numerical measures or a series field."
        else:
            okay = bool(cats and nums)
            reason = "Needs a categorical field and a numerical measure."
        results.append({**item, "compatible": okay, "reason": "" if okay else reason or "Dataset has no usable columns."})
    return results


def recommend(metadata: dict) -> list[dict]:
    """Consider every renderer, but cap combinations to meaningful alternatives."""
    cols = metadata.get("columns", [])
    nums = [c["name"] for c in cols if c["type"] in NUMERIC_TYPES and c.get("unique", 0) > 0 and "min" in c]
    cats = [c["name"] for c in cols if (c["type"] in {"categorical", "boolean", "ordinal"} or c["type"] == "geographic" and "categories" in c) and 0 < c.get("unique", 0) <= 100]
    nonnegative = [c["name"] for c in cols if c["type"] in NUMERIC_TYPES and c.get("unique", 0) > 0 and "min" in c and c["min"] >= 0]
    dates = [c["name"] for c in cols if c["type"] in DATE_TYPES and c.get("unique", 0)]
    result = []
    for chart in compatible(metadata):
        if not chart["compatible"]:
            continue
        kind = chart["id"]
        y = (nonnegative[0] if nonnegative else None) if kind in {"pie", "pie3d", "donut", "semi_donut", "treemap", "sunburst", "funnel", "pareto", "percent_bar", "sankey", "chord"} else (nums[0] if nums else None)
        x = cats[0] if cats else None
        spec = {"id": kind, "type": kind, "title": chart["name"], "x": x, "y": y, "aggregation": "sum", "group": chart["group"], "score": 75, "reason": "Summarize the available records using a compatible configuration."}
        if kind == 'confidence_band':
            spec.update(metadata['interval_candidates'][0])
            spec.update(title=f"{spec['y']} with provided interval", reason='Display the supplied lower and upper bounds alongside actual observations. No statistical confidence level is inferred.')
        elif kind == "map":
            candidate = metadata["coordinate_candidates"][0]
            spec.update(candidate)
            spec.update(title="Geographic distribution", reason="Plot exact uploaded latitude and longitude coordinates without guessed locations.", score=92)
            if y:
                spec["z"] = y
            if cats:
                spec["series"] = cats[0]
        elif chart["group"] == "Trends" or kind == "calendar":
            spec.update(x=dates[0], granularity="month", title=f"{y} over time", reason=f"Track changes in {y} by {dates[0]}.", score=96 if kind == "line" else 80)
            if kind == "gantt":
                spec.update(x=dates[0], end=dates[1], series=cats[0], title=f"{cats[0]} schedule")
        elif kind in {"scatter", "regression", "bubble", "scatter3d", "surface3d", "bar3d"}:
            spec.update(x=nums[0], y=nums[1], title=f"{nums[1]} vs {nums[0]}", reason="Explore relationships between independent numerical measures.")
            if len(nums) > 2 and kind in {"bubble", "scatter3d", "surface3d", "bar3d"}:
                spec["z"] = nums[2]
                spec["size"] = nums[2]
            if kind == "surface3d":
                spec.update(metadata["surface_candidates"][0])
            if kind == "regression":
                candidate = (metadata.get("regression_candidates") or metadata.get("relationships"))[0]
                spec.update(x=candidate["x"], y=candidate["y"], title=f'{candidate["y"]} vs {candidate["x"]} · regression', reason="Fit an ordinary least-squares trend to actual paired observations, with R².")
        elif kind == "heatmap":
            spec.update(x=nums[0], y=nums[1], title="Measure correlations", reason="Compare pairwise Pearson correlations; constant measures remain undefined.")
        elif kind in {"histogram", "box", "violin", "density"}:
            if kind == "density":
                y = next(c["name"] for c in cols if c["type"] in NUMERIC_TYPES and c.get("unique", 0) > 1 and "min" in c)
                spec["y"] = y
            spec.update(x=cats[0] if cats else None, title=f"{y} distribution", reason=f"Inspect the spread and outliers in {y}.")
        elif kind in {"kpi", "gauge", "progress"}:
            spec.update(x=None, title=f"Total {y}" if y else "Record count", aggregation="sum" if y else "count", reason="Track an aggregate from the imported records.", score=98)
            if kind in {'gauge', 'progress'}:
                target = next(c['name'] for c in cols if c['name'] in nonnegative and re.search(r'\b(target|goal|budget|quota|capacity)\b', c['name'], re.I) and c.get('sum', 0) > 0)
                actual = next(name for name in nums if name != target)
                spec.update(y=actual, target_field=target, title=f'{actual} vs {target}', reason=f'Compare actual {actual} against the supplied {target} values.')
        elif kind in {"table", "summary", "pivot"}:
            spec.update(title="Data explorer" if kind == "table" else "Performance summary", columns=[c["name"] for c in cols[:8]])
        elif kind in {"sankey", "chord"}:
            spec.update(series=cats[1], title=f"{cats[0]} to {cats[1]}", reason="Compare weighted flows between explicitly selected stages.")
        elif kind == "bullet":
            spec.update(target_field=nums[1], title=f"{nums[0]} vs {nums[1]}")
        elif kind in {"grouped_bar", "stacked_bar", "percent_bar", "stacked_area"}:
            if len(cats) >= 2:
                spec["series"] = cats[1]
            elif len(nums) >= 2:
                spec["measures"] = (nonnegative if kind == "percent_bar" else nums)[:3]
        else:
            spec.update(title=f"{y} by {x}", reason=f"Compare aggregated {y} across {x}.", score=94 if kind == "bar" else 83)
        if not y and not spec.get("formula"):
            spec["aggregation"] = "count"
        result.append(spec)
    # Offer sensible alternatives across additional measures/dimensions without
    # exploding into the Cartesian product of all possible field assignments.
    for measure in nums[1:5]:
        result.append({"id": f"kpi-{measure}", "type": "kpi", "title": f"Total {measure}", "x": None, "y": measure, "aggregation": "sum", "score": 95, "group": "KPI Suggestions", "reason": f"Monitor the total of {measure}."})
    for dimension in cats[1:4]:
        if nums:
            result.append({"id": f"bar-{dimension}", "type": "bar", "title": f"{nums[0]} by {dimension}", "x": dimension, "y": nums[0], "aggregation": "sum", "score": 90, "group": "Comparisons", "reason": f"Compare {nums[0]} across a different meaningful dimension."})
    return sorted(result, key=lambda item: -item["score"])


_AGGREGATIONS = {"sum", "count", "distinct_count", "average", "avg", "mean", "min", "max", "median", "std", "first", "last"}


def aggregate(rows: list[dict], field: str | None, method: str = "sum") -> float | int | None:
    method = str(method).lower()
    if method not in _AGGREGATIONS:
        raise ValueError(f"Unsupported aggregation: {method}")
    values = [r.get(field) for r in rows if not missing(r.get(field))] if field else []
    if method == "count":
        return len(values) if field else len(rows)
    if method == "distinct_count":
        return len({_key(v) for v in values})
    nums = [n for v in values if (n := number(v)) is not None]
    if not nums:
        return None
    if method == "sum":
        return sum(nums)
    if method in {"avg", "mean", "average"}:
        return statistics.mean(nums)
    if method == "min":
        return min(nums)
    if method == "max":
        return max(nums)
    if method == "median":
        return statistics.median(nums)
    if method == "std":
        return statistics.pstdev(nums)
    return nums[0] if method == "first" else nums[-1]


class Formula:
    """Small AST interpreter; rejects attributes, indexing, imports and Python calls."""
    FUNCTIONS = {"SUM": "sum", "AVG": "average", "AVERAGE": "average", "COUNT": "count", "DISTINCT_COUNT": "distinct_count", "MIN": "min", "MAX": "max", "MEDIAN": "median"}

    def __init__(self, expression: str, columns: list[str]):
        if not isinstance(expression, str) or not expression.strip() or len(expression) > 512:
            raise ValueError("Enter a formula of at most 512 characters.")
        self.fields = {name: name for name in columns if str(name).isidentifier()}
        def replace(match):
            name = match.group(1)
            if name not in columns:
                raise ValueError(f"Formula references missing column: {name}")
            alias = f"_field_{len(self.fields)}"
            self.fields[alias] = name
            return alias
        expression = re.sub(r"\[([^\[\]]+)\]", replace, expression)
        if "=" in expression and not any(c in expression for c in ("==", "<=", ">=", "!=")):
            expression = expression.split("=", 1)[1].strip()
        try:
            self.tree = ast.parse(expression, mode="eval")
        except (SyntaxError, ValueError, RecursionError) as exc:
            raise ValueError("Invalid formula. Use arithmetic, [Column Name], and SUM/AVG/COUNT/MIN/MAX/MEDIAN.") from exc
        nodes = list(ast.walk(self.tree))
        allowed = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Name, ast.Load, ast.Constant, ast.Call, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod, ast.USub, ast.UAdd)
        if len(nodes) > 100 or any(not isinstance(n, allowed) for n in nodes):
            raise ValueError("Formula contains unsupported syntax. Only arithmetic and aggregate functions are allowed.")
        for node in nodes:
            if isinstance(node, ast.Name) and node.id not in self.fields and node.id.upper() not in self.FUNCTIONS and node.id.upper() not in {"ABS", "ROUND"}:
                raise ValueError(f"Formula references missing column or function: {node.id}")
            if isinstance(node, ast.Call) and (not isinstance(node.func, ast.Name) or node.func.id.upper() not in {*self.FUNCTIONS, "ABS", "ROUND"} or node.keywords):
                raise ValueError("Only supported aggregate and rounding functions may be called.")
            if isinstance(node, ast.Constant) and (isinstance(node.value, bool) or not isinstance(node.value, (int, float)) or abs(node.value) > 1e15):
                raise ValueError("Formula constants must be finite numbers of reasonable size.")

    def evaluate(self, rows: list[dict], row: dict | None = None) -> float | int | None:
        return _safe(self._evaluate(self.tree.body, rows, row))

    def _evaluate(self, node, rows, row):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id not in self.fields:
                raise ValueError("Function names must be called with parentheses.")
            field = self.fields[node.id]
            return number(row.get(field)) if row is not None else aggregate(rows, field, "sum")
        if isinstance(node, ast.UnaryOp):
            value = self._evaluate(node.operand, rows, row)
            return None if value is None else (-value if isinstance(node.op, ast.USub) else value)
        if isinstance(node, ast.BinOp):
            a, b = self._evaluate(node.left, rows, row), self._evaluate(node.right, rows, row)
            if a is None or b is None:
                return None
            if isinstance(node.op, (ast.Div, ast.Mod)) and b == 0:
                raise ValueError("Division by zero in formula. Adjust the denominator or filter out zero totals.")
            if isinstance(node.op, ast.Pow) and (abs(b) > 8 or abs(a) > 1e12):
                raise ValueError("Exponent is outside the supported safe range.")
            operation = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod}[type(node.op)]
            try:
                value = operation(a, b)
                if isinstance(value, complex) or not math.isfinite(value):
                    raise ValueError("Formula result is not a finite real number.")
                return value
            except (OverflowError, ZeroDivisionError) as exc:
                raise ValueError("Formula result exceeds the supported numerical range.") from exc
        if isinstance(node, ast.Call):
            name = node.func.id.upper()
            if name in self.FUNCTIONS:
                if len(node.args) != 1:
                    raise ValueError(f"{name} needs exactly one field or arithmetic expression.")
                arg = node.args[0]
                if isinstance(arg, ast.Name) and arg.id in self.fields:
                    return aggregate(rows, self.fields[arg.id], self.FUNCTIONS[name])
                if any(isinstance(n, ast.Call) for n in ast.walk(arg)):
                    raise ValueError("Nested aggregate functions are not supported.")
                values = [{"_value": self._evaluate(arg, rows, record)} for record in rows]
                return aggregate(values, "_value", self.FUNCTIONS[name])
            values = [self._evaluate(arg, rows, row) for arg in node.args]
            if any(v is None for v in values):
                return None
            if name == "ABS" and len(values) == 1:
                return abs(values[0])
            if name == "ROUND" and 1 <= len(values) <= 2:
                precision = int(values[1]) if len(values) == 2 else 0
                if abs(precision) > 12:
                    raise ValueError("Rounding precision must be between -12 and 12.")
                return round(values[0], precision)
            raise ValueError(f"Invalid arguments to {name}.")
        raise ValueError("Unsupported formula expression.")


def evaluate_formula(expression: str, rows: list[dict]) -> float | None:
    return Formula(expression, _columns(rows)).evaluate(rows)


def _comparable(value):
    if missing(value):
        return None
    n = number(value)
    if n is not None:
        return n
    date = date_value(value)
    return date if date else str(value).casefold()


def _filter_one(row: dict, condition: dict) -> bool:
    field, op = condition.get("field"), condition.get("op", "eq")
    value = row.get(field)
    expected = condition.get("value")
    identifier = bool(re.search(r"(^|[ _-])(id|uuid|code|sku|zip|postal|invoice|account|phone)([ _-]|$)", field.lower()))
    def compare(item):
        if identifier:
            return None if missing(item) else str(item).casefold()
        return _comparable(item)
    if op in {"is_null", "null"}:
        return missing(value)
    if op in {"not_null", "is_not_null"}:
        return not missing(value)
    if op in {"eq", "equals", "boolean"}:
        return compare(value) == compare(expected)
    if op in {"neq", "not_eq", "exclude"}:
        return compare(value) != compare(expected)
    if op in {"in", "not_in", "include"}:
        values = expected if isinstance(expected, list) else [expected]
        if len(values) > 1000:
            raise ValueError("Filter selection exceeds 1000 values.")
        found = compare(value) in [compare(v) for v in values]
        return not found if op == "not_in" else found
    if op in {"contains", "not_contains", "starts_with", "ends_with", "search"}:
        if missing(value):
            return False
        actual, term = str(value).casefold(), str(expected or "").casefold()
        if op == "starts_with":
            return actual.startswith(term)
        if op == "ends_with":
            return actual.endswith(term)
        return term not in actual if op == "not_contains" else term in actual
    if op in {"between", "date_range", "range"}:
        if not isinstance(expected, (list, tuple)) or len(expected) != 2:
            raise ValueError("Range filters need a minimum and maximum value.")
        actual, low, high = compare(value), compare(expected[0]), compare(expected[1])
        if actual is None:
            return False
        # A date-only upper boundary includes that whole day.
        if isinstance(high, dt.datetime) and isinstance(expected[1], str) and re.match(r"^\d{4}-\d{2}-\d{2}$", expected[1]):
            high += dt.timedelta(days=1, microseconds=-1)
        try:
            return (low is None or actual >= low) and (high is None or actual <= high)
        except TypeError:
            return False
    if op == "relative_date":
        actual = date_value(value)
        if not actual:
            return False
        try:
            days = int(expected.get("days", 30)) if isinstance(expected, dict) else int(expected or 30)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Relative date range needs a valid number of days.") from exc
        if not 1 <= days <= 36500:
            raise ValueError("Relative date range must be 1–36500 days.")
        now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
        return now - dt.timedelta(days=days) <= actual <= now
    if op in {"gt", "gte", "lt", "lte", "before", "after"}:
        a, b = compare(value), compare(expected)
        if a is None or b is None:
            return False
        try:
            return {"gt": operator.gt, "gte": operator.ge, "lt": operator.lt, "lte": operator.le, "before": operator.lt, "after": operator.gt}[op](a, b)
        except TypeError:
            return False
    raise ValueError(f"Unsupported filter operator: {op}")


def filter_rows(rows: list[dict], filters: list | dict | None, columns: list[str] | None = None) -> list[dict]:
    columns = columns if columns is not None else _columns(rows)
    count = [0]
    def compile_filter(filters, depth=0):
        if depth > 5:
            raise ValueError("Filter groups are nested too deeply.")
        if isinstance(filters, list):
            conditions, logic = filters, "and"
        elif isinstance(filters, dict) and "conditions" in filters:
            conditions, logic = filters["conditions"], filters.get("logic", "and")
            if not isinstance(logic, str):
                raise ValueError("Filter logic must be AND or OR.")
            logic = logic.lower()
        elif isinstance(filters, dict) and "field" in filters:
            conditions, logic = [filters], "and"
        elif filters in (None, {}):
            return lambda row: True
        else:
            raise ValueError("Filters must be a list of conditions or an AND/OR group.")
        if logic not in {"and", "or"} or not isinstance(conditions, list):
            raise ValueError("Filter logic must be AND or OR with a list of conditions.")
        predicates = []
        for condition in conditions:
            count[0] += 1
            if count[0] > 64 or not isinstance(condition, dict):
                raise ValueError("Use at most 64 valid filter conditions.")
            if "conditions" in condition:
                predicates.append(compile_filter(condition, depth + 1))
            else:
                if not isinstance(condition.get("field"), str) or condition.get("field") not in columns:
                    raise ValueError(f'Missing filter column: {condition.get("field")}')
                # Validate operator even with an empty input dataset.
                valid = {"is_null", "null", "not_null", "is_not_null", "eq", "equals", "boolean", "neq", "not_eq", "exclude", "in", "not_in", "include", "contains", "not_contains", "starts_with", "ends_with", "search", "between", "date_range", "range", "relative_date", "gt", "gte", "lt", "lte", "before", "after"}
                if not isinstance(condition.get("op", "eq"), str) or condition.get("op", "eq") not in valid:
                    raise ValueError(f'Unsupported filter operator: {condition.get("op")}')
                predicates.append(lambda row, condition=condition: _filter_one(row, condition))
        combine = all if logic == "and" else any
        return lambda row: combine(p(row) for p in predicates) if predicates else True
    predicate = compile_filter(filters)
    return [r for r in rows if predicate(r)]


def _date_bucket(value: Any, granularity: str | None):
    date = date_value(value)
    if not date or not granularity or granularity in {"none", "raw"}:
        return "(Missing)" if missing(value) else str(value)
    if granularity == "year":
        return f"{date.year:04}"
    if granularity == "quarter":
        return f"{date.year:04}-Q{(date.month-1)//3+1}"
    if granularity == "month":
        return date.strftime("%Y-%m")
    if granularity == "week":
        return (date - dt.timedelta(days=date.weekday())).strftime("%Y-%m-%d")
    if granularity == "day":
        return date.strftime("%Y-%m-%d")
    if granularity == "hour":
        return date.strftime("%Y-%m-%d %H:00")
    raise ValueError(f"Unsupported time granularity: {granularity}")


def _correlations(rows, fields):
    matrix = []
    for x in fields:
        line = []
        for y in fields:
            pairs = [(number(row.get(x)), number(row.get(y))) for row in rows]
            pairs = [(a, b) for a, b in pairs if a is not None and b is not None]
            if len(pairs) < 2:
                line.append(None)
            else:
                xs, ys = zip(*pairs)
                line.append(statistics.correlation(xs, ys) if len(set(xs)) > 1 and len(set(ys)) > 1 else None)
        matrix.append(line)
    return matrix


def _metric(rows, spec, columns):
    if spec.get("formula"):
        return Formula(spec["formula"], columns).evaluate(rows)
    method = spec.get("aggregation", "sum")
    if not isinstance(method, str):
        raise ValueError("Aggregation must be a supported function name.")
    y = spec.get("y")
    if method in {"ratio", "percentage", "difference", "growth"}:
        a = aggregate(rows, y, spec.get("numerator_aggregation", "sum"))
        denominator = spec.get("denominator") or spec.get("target_field")
        if denominator not in columns:
            raise ValueError("Choose a valid denominator or target field.")
        b = aggregate(rows, denominator, spec.get("denominator_aggregation", "sum"))
        if a is None or b is None:
            return None
        if method == "difference":
            return a - b
        if b == 0:
            raise ValueError("Division by zero: the denominator totals zero in this filter context.")
        return (a - b) / b * 100 if method == "growth" else a / b * (100 if method == "percentage" else 1)
    if method == "conditional_count":
        return len(filter_rows(rows, spec.get("condition", []), columns))
    return aggregate(rows, y, method)


def query(rows: list[dict], spec: dict, schema: dict | list | None = None) -> dict:
    """Query records through a validated specification, shared by editor and public views."""
    if not isinstance(spec, dict):
        raise ValueError("Chart specification must be an object.")
    spec = dict(spec)
    if "time_granularity" in spec and "granularity" not in spec:
        spec["granularity"] = spec["time_granularity"]
    for setting in ("aggregation", "granularity", "comparison", "direction", "sort"):
        if spec.get(setting) is not None and not isinstance(spec[setting], str):
            raise ValueError(f"{setting.replace('_', ' ').title()} must be text.")
    for setting in ("window", "page", "limit"):
        if spec.get(setting) is not None and (isinstance(spec[setting], bool) or not isinstance(spec[setting], (str, int, float))):
            raise ValueError(f"{setting.title()} must be an integer.")
    if spec.get("measures") is not None and (not isinstance(spec["measures"], list) or any(not isinstance(field, str) for field in spec["measures"])):
        raise ValueError("Measures must be a list of field names.")
    columns = _columns(rows)
    if isinstance(schema, dict):
        schema_columns = schema.get("columns", [])
    else:
        schema_columns = schema or []
    columns = list(dict.fromkeys(columns + [c["name"] if isinstance(c, dict) else str(c) for c in schema_columns]))
    rows = [dict(row) for row in rows]
    calculated = spec.get("calculated_fields", [])
    if isinstance(calculated, dict):
        calculated = [{"name": name, "formula": formula} for name, formula in calculated.items()]
    if not isinstance(calculated, list) or len(calculated) > 20:
        raise ValueError("Use at most 20 calculated fields.")
    for field in calculated:
        name = field.get("name") if isinstance(field, dict) else None
        if not isinstance(name, str) or not name.strip() or name in columns:
            raise ValueError("Calculated field needs a new, non-empty column name.")
        expression = Formula(field.get("formula"), columns)
        if any(isinstance(node, ast.Call) and node.func.id.upper() in Formula.FUNCTIONS for node in ast.walk(expression.tree)):
            raise ValueError('Calculated columns use row-level arithmetic. Put aggregate functions in a KPI formula instead.')
        for row in rows:
            row[name] = expression.evaluate(rows, row=row)
        columns.append(name)
    kind = spec.get("type", "bar")
    if not isinstance(kind, str) or kind not in CHART_IDS:
        raise ValueError(f"Unsupported visualization: {kind}")
    x, y, series = spec.get("x"), spec.get("y"), spec.get("series")
    for name in (x, y, series, spec.get("z"), spec.get("size"), spec.get("end"), spec.get("target_field"), spec.get("denominator"), spec.get('lower'), spec.get('upper')):
        if name and (not isinstance(name, str) or name not in columns):
            raise ValueError(f"Missing data column: {name}")
    selected_columns = spec.get("columns") or columns[:12]
    if not isinstance(selected_columns, list) or any(c not in columns for c in selected_columns):
        raise ValueError("Table column selection references a missing column.")
    filters = spec.get("filters", [])
    if isinstance(filters, list) and "filter_logic" in spec:
        filters = {"logic": spec["filter_logic"], "conditions": filters}
    rows = filter_rows(rows, filters, columns)
    limit = spec.get("limit", 100 if kind in {"table", "summary", "pivot"} else 50)
    try:
        limit = int(limit)
    except (ValueError, TypeError, OverflowError):
        raise ValueError("Display limit must be an integer.")
    if not 1 <= limit <= MAX_POINTS:
        raise ValueError(f"Display limit must be between 1 and {MAX_POINTS}.")
    response = {"labels": [], "series": [], "value": None, "rows": [], "columns": [], "row_count": len(rows), "filtered_count": len(rows), "truncated": False}
    if spec.get("formula"):
        Formula(spec["formula"], columns)  # Validate even when a chart has no rows.
    if kind in {"kpi", "gauge", "progress"}:
        if not y and not spec.get("formula") and spec.get("aggregation", "sum") not in {"count", "conditional_count"}:
            raise ValueError("Choose a numerical measure or record count for this KPI.")
        response["value"] = _metric(rows, spec, columns)
        if spec.get("target_field"):
            response["target"] = aggregate(rows, spec["target_field"], "sum")
        elif number(spec.get("target")) is not None:
            response["target"] = number(spec["target"])
        if kind in {'gauge', 'progress'} and rows and (response.get('target') is None or response['target'] <= 0):
            raise ValueError('This visualization needs a positive supplied target. Set Target or choose a positive target field; no goal is invented.')
        if x and spec.get("comparison") in {"previous_period", "mom", "yoy"}:
            dated = [(date_value(row.get(x)), row) for row in rows]
            dated = [(date, row) for date, row in dated if date]
            if dated:
                latest = max(date for date, row in dated)
                if spec["comparison"] == "yoy":
                    current = [row for date, row in dated if date.year == latest.year]
                    previous = [row for date, row in dated if date.year == latest.year - 1]
                else:
                    prev_month = (latest.replace(day=1) - dt.timedelta(days=1))
                    current = [row for date, row in dated if (date.year, date.month) == (latest.year, latest.month)]
                    previous = [row for date, row in dated if (date.year, date.month) == (prev_month.year, prev_month.month)]
                response["value"] = _metric(current, spec, columns)
                response["previous"] = _metric(previous, spec, columns)
                prev = response["previous"]
                response["change"] = ((response["value"] - prev) / abs(prev) * 100) if prev not in (None, 0) and response["value"] is not None else None
        if x:
            groups = defaultdict(list)
            for row in rows:
                groups[_date_bucket(row.get(x), spec.get("granularity", "month"))].append(row)
            response["sparkline"] = [{"label": key, "value": _metric(groups[key], spec, columns)} for key in sorted(groups)[-24:]]
        return _safe(response)
    if kind == "table":
        search = str(spec.get("search", "")).casefold()
        if search:
            rows = [row for row in rows if any(search in str(row.get(c, "")).casefold() for c in selected_columns)]
        sort = spec.get("sort")
        if sort and sort in columns:
            rows.sort(key=lambda r: (missing(r.get(sort)), number(r.get(sort)) is None, str(r.get(sort)) if number(r.get(sort)) is None else number(r.get(sort))), reverse=spec.get("direction") == "desc")
        page = max(1, int(spec.get("page", 1)))
        response.update(rows=[{c: row.get(c) for c in selected_columns} for row in rows[(page-1)*limit:page*limit]], columns=selected_columns, total=len(rows), page=page, total_pages=math.ceil(len(rows)/limit), truncated=len(rows) > limit)
        return _safe(response)
    if kind == 'confidence_band':
        lower, upper = spec.get('lower'), spec.get('upper')
        if not all((x, y, lower, upper)) or len({y, lower, upper}) != 3:
            raise ValueError('Choose a dimension and three distinct center, lower, and upper interval fields.')
        points, labels_seen = [], set()
        for row in rows:
            if any(missing(row.get(field)) for field in (x, y, lower, upper)):
                continue
            lo, center, hi = (number(row.get(field)) for field in (lower, y, upper))
            if any(value is None for value in (lo, center, hi)):
                raise ValueError('Interval center and bounds must contain valid numbers.')
            if not lo <= center <= hi:
                raise ValueError('Provided interval bounds must satisfy lower ≤ center ≤ upper for every observation.')
            label = _safe(row[x])
            if _key(label) in labels_seen:
                raise ValueError('Interval bands need one observation per dimension value. Filter duplicate observations; interval bounds cannot be aggregated safely.')
            labels_seen.add(_key(label))
            points.append({x: label, y: center, lower: lo, upper: hi})
        points.sort(key=lambda row: (number(row[x]) is None, number(row[x]) if number(row[x]) is not None else str(row[x])))
        total = len(points)
        points = points[:min(limit, MAX_GROUPS)]
        response.update(labels=[row[x] for row in points], rows=points, columns=[x, y, lower, upper], bands={'center':[row[y] for row in points], 'lower':[row[lower] for row in points], 'upper':[row[upper] for row in points]}, series=[{'name':y,'values':[row[y] for row in points]}], truncated=total>len(points), excluded_incomplete=len(rows)-total, interval_source='provided')
        return _safe(response)
    if kind == "map":
        if not x or not y or _coordinate_name(x) != "longitude" or _coordinate_name(y) != "latitude":
            raise ValueError("Choose explicitly named Longitude/Lon/Lng and Latitude/Lat source columns for the map. No locations are guessed.")
        size = spec.get("z") or spec.get("size")
        fields = list(dict.fromkeys([x, y] + ([size] if size else []) + ([series] if series else [])))
        points = []
        for row in rows:
            if missing(row.get(x)) or missing(row.get(y)):
                continue
            longitude, latitude = number(row[x]), number(row[y])
            if longitude is None or latitude is None:
                raise ValueError("Map coordinates must be numerical. Correct invalid latitude/longitude values or filter those records.")
            if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
                raise ValueError("Map coordinates are out of range: longitude must be -180 to 180 and latitude -90 to 90. Correct the source data.")
            record = {x: longitude, y: latitude}
            if size:
                weight = number(row.get(size))
                if weight is None and not missing(row.get(size)):
                    raise ValueError("Map size/color measure must be numerical or empty.")
                record[size] = weight
            if series and series not in record:
                record[series] = row.get(series)
            points.append(record)
        step = max(1, math.ceil(len(points) / MAX_POINTS))
        response.update(rows=points[::step][:MAX_POINTS], columns=fields, truncated=len(points)>MAX_POINTS)
        return _safe(response)
    if kind in {"scatter", "regression", "bubble", "scatter3d", "bar3d", "surface3d"}:
        if not x or not y:
            raise ValueError("Scatter and 3D plots require numerical X and Y fields.")
        z = (spec.get("z") or spec.get("size")) if kind in {"scatter3d", "bar3d", "surface3d", "bubble"} else None
        if kind in {"scatter3d", "bar3d", "surface3d", "bubble"} and not z:
            raise ValueError("Choose a third numerical field for Z or bubble size.")
        fields = list(dict.fromkeys([x, y] + ([z] if z else []) + ([series] if series else [])))
        numeric_fields = [x, y] + ([z] if z else [])
        usable = [row for row in rows if all(number(row.get(c)) is not None for c in numeric_fields)]
        # Deterministic downsampling covers the whole input instead of truncating its tail.
        step = max(1, math.ceil(len(usable) / MAX_POINTS))
        points = usable[::step][:MAX_POINTS]
        response.update(rows=[{c: number(row.get(c)) if c in numeric_fields else row.get(c) for c in fields} for row in points], columns=fields, truncated=len(usable) > MAX_POINTS)
        if kind == "regression":
            if len(usable) < 2:
                raise ValueError("Regression needs at least two paired numerical observations after filtering.")
            xs, ys = [number(row[x]) for row in usable], [number(row[y]) for row in usable]
            if len(set(xs)) < 2:
                raise ValueError("Regression needs at least two distinct X values after filtering.")
            try:
                slope, intercept = statistics.linear_regression(xs, ys)
                prediction = [min(xs), max(xs)]
                r_squared = statistics.correlation(xs, ys) ** 2 if len(set(ys)) > 1 else None
                response["regression"] = {"x": prediction, "y": [slope * value + intercept for value in prediction], "slope": slope, "intercept": intercept, "r_squared": r_squared, "n": len(usable), "method": "ordinary_least_squares"}
                if any(not math.isfinite(v) for v in (slope, intercept, *response["regression"]["y"])):
                    raise ValueError("Regression calculation exceeds the supported numerical range.")
            except (OverflowError, statistics.StatisticsError) as exc:
                raise ValueError("Regression could not be calculated at this numerical scale. Rescale the measures.") from exc
        if kind == "surface3d":
            xs, ys = sorted(set(number(r[x]) for r in usable)), sorted(set(number(r[y]) for r in usable))
            if len(xs) > 100 or len(ys) > 100:
                raise ValueError("Surface plot needs at most 100 distinct X and Y coordinates. Aggregate or filter the data first.")
            grid = defaultdict(list)
            for row in usable:
                grid[(number(row[x]), number(row[y]))].append(number(row[z]))
            response.update(x_values=xs, y_values=ys, matrix=[[statistics.mean(grid[(a,b)]) if (a,b) in grid else None for a in xs] for b in ys])
        return _safe(response)
    if kind in {"histogram", "box", "violin", "density"}:
        if not y:
            raise ValueError("Choose a numerical distribution field.")
        points = [row for row in rows if number(row.get(y)) is not None]
        if kind == "density":
            values = sorted(number(row[y]) for row in points)
            if len(values) < 2 or values[0] == values[-1]:
                raise ValueError("Density estimation needs at least two distinct numerical values after filtering.")
            count = min(len(values), MAX_POINTS)
            samples = values if len(values) <= count else [values[round(i * (len(values)-1)/(count-1))] for i in range(count)]
            try:
                sigma = statistics.stdev(samples)
                q1, _, q3 = statistics.quantiles(samples, n=4, method="inclusive")
                scale = min(sigma, (q3-q1)/1.34) if q3 > q1 else sigma
                bandwidth = .9 * scale * len(samples) ** (-.2)
                if bandwidth <= 0 or not math.isfinite(bandwidth):
                    raise ValueError("Density bandwidth cannot be calculated; rescale the numerical field.")
                lower, upper = samples[0] - 3*bandwidth, samples[-1] + 3*bandwidth
                span = upper-lower
                if not math.isfinite(span):
                    raise ValueError("Density range is too large; rescale the numerical field.")
                coordinates = [lower + span*i/127 for i in range(128)]
                normalizer = len(samples)*bandwidth*math.sqrt(2*math.pi)
                estimates = [math.fsum(math.exp(-.5*((coordinate-value)/bandwidth)**2) for value in samples)/normalizer for coordinate in coordinates]
            except (OverflowError, statistics.StatisticsError) as exc:
                raise ValueError("Density cannot be estimated at this numerical scale. Rescale the field.") from exc
            response.update(density={"x":coordinates,"y":estimates,"bandwidth":bandwidth,"n":len(values),"sample_size":len(samples),"method":"gaussian_kde_silverman"}, columns=[y,"Density"], rows=[{y:coordinate,"Density":estimate} for coordinate,estimate in zip(coordinates,estimates)], truncated=len(values)>MAX_POINTS)
            return _safe(response)
        step = max(1, math.ceil(len(points) / MAX_POINTS))
        points = points[::step][:MAX_POINTS]
        response.update(rows=[{y: number(row.get(y)), **({x: row.get(x)} if x else {})} for row in points], columns=([x] if x else []) + [y], values=[number(row.get(y)) for row in points], truncated=len(rows) > MAX_POINTS)
        return _safe(response)
    if kind == "heatmap":
        fields = spec.get("measures") or [c["name"] for c in schema_columns if isinstance(c, dict) and c.get("type") in NUMERIC_TYPES]
        fields = fields or [c for c in columns if any(number(r.get(c)) is not None for r in rows)]
        fields = fields[:20]
        if any(c not in columns for c in fields):
            raise ValueError("Correlation references a missing measure.")
        if len(fields) < 2:
            raise ValueError("Correlation heatmap needs two numerical measures.")
        response.update(labels=fields, matrix=_correlations(rows, fields), columns=fields)
        return _safe(response)
    if kind == "gantt":
        end = spec.get("end")
        label = series or spec.get("label")
        if not x or not end or label not in columns:
            raise ValueError("Gantt needs start, end, and task-name fields.")
        points = []
        for row in rows:
            start_date, end_date = date_value(row.get(x)), date_value(row.get(end))
            if start_date and end_date:
                if end_date < start_date:
                    raise ValueError("A Gantt task ends before it starts. Correct the dates or field assignments.")
                points.append({"task": row.get(label), "start": start_date.isoformat(), "end": end_date.isoformat(), "duration": (end_date - start_date).total_seconds() * 1000})
        response.update(rows=points[:limit], columns=["task", "start", "end", "duration"])
        return _safe(response)
    if kind in {"sankey", "chord"}:
        if not x or not series or not y:
            raise ValueError("Sankey needs source, destination and weight fields.")
        groups = defaultdict(list)
        for row in rows:
            if not missing(row.get(x)) and not missing(row.get(series)):
                groups[(str(row[x]), str(row[series]))].append(row)
        pairs = []
        for pair, records in groups.items():
            weight = _metric(records, spec, columns)
            if weight is not None and weight < 0:
                raise ValueError("Sankey flow weights cannot be negative.")
            if weight and weight > 0:
                pairs.append((pair, weight))
        pairs = sorted(pairs, key=lambda p: -p[1])[:min(limit, MAX_GROUPS)]
        nodes = list(dict.fromkeys(["Source: " + a for (a,b), weight in pairs] + ["Target: " + b for (a,b), weight in pairs]))
        response.update(nodes=[{"id": i, "name": name.split(": ",1)[1]} for i,name in enumerate(nodes)], links=[{"source": nodes.index("Source: " + a), "target": nodes.index("Target: " + b), "value": weight} for (a,b),weight in pairs], rows=[{x:a,series:b,y:weight} for (a,b),weight in pairs], columns=[x,series,y], truncated=len(groups)>len(pairs))
        return _safe(response)
    # All remaining chart types share the same grouping and measure semantics.
    if not x and kind not in {"summary", "bullet"}:
        raise ValueError("Choose an X-axis or grouping field.")
    if not y and not spec.get("formula") and spec.get("aggregation", "sum") not in {"count", "conditional_count"}:
        raise ValueError("Choose a numerical measure or a record-count aggregation.")
    measures = spec.get("measures") or ([y] if y else [None])
    if not isinstance(measures, list) or len(measures) > 12 or any(m and m not in columns for m in measures):
        raise ValueError("Choose at most 12 valid numerical measures.")
    groups, series_names = defaultdict(list), []
    for row in rows:
        label = _date_bucket(row.get(x), spec.get("granularity")) if x else "Total"
        subgroup = str(row.get(series)) if series and not missing(row.get(series)) else "(Missing)" if series else None
        groups[(label, subgroup)].append(row)
        if subgroup not in series_names:
            series_names.append(subgroup)
    labels = list(dict.fromkeys(label for label, subgroup in groups))
    if len(labels) > 10000 or len(series_names) > 100:
        raise ValueError("Too many chart groups. Add filters or choose a lower-cardinality field.")
    series_results = []
    for subgroup in series_names or [None]:
        for measure in measures:
            measure_spec = {**spec, "y": measure}
            values = [_metric(groups.get((label, subgroup), []), measure_spec, columns) for label in labels]
            name = str(subgroup) if subgroup is not None else str(measure or "Count")
            if subgroup is not None and len(measures) > 1:
                name += " · " + str(measure)
            series_results.append({"name": name, "values": values})
    direction = spec.get("direction", "desc" if kind in {"ranking", "pareto", "funnel"} else "asc")
    sort = spec.get("sort", "value" if kind in {"ranking", "pareto", "funnel"} else "label")
    if not isinstance(sort, str) or not isinstance(direction, str) or direction not in {"asc", "desc"}:
        raise ValueError("Sort must be a field, label or value with direction asc/desc.")
    if sort in {"value", "y", "measure", y} and series_results:
        order = sorted(range(len(labels)), key=lambda i: sum((s["values"][i] or 0) for s in series_results), reverse=direction == "desc")
    else:
        order = sorted(range(len(labels)), key=lambda i: (number(labels[i]) is None, number(labels[i]) if number(labels[i]) is not None else labels[i]), reverse=direction == "desc")
    if kind == "pareto" and any((v or 0) < 0 for series_item in series_results for v in series_item["values"]):
        raise ValueError("Pareto contributions must be non-negative.")
    if kind in {"pie", "pie3d", "donut", "semi_donut", "treemap", "sunburst", "funnel", "percent_bar"} and any((v or 0) < 0 for s in series_results for v in s["values"]):
        raise ValueError("This contribution chart requires non-negative values. Use a bar chart for signed values.")
    original_count = len(order)
    order = order[:min(limit, MAX_GROUPS)]
    labels = [labels[i] for i in order]
    for item in series_results:
        item["values"] = [item["values"][i] for i in order]
        if kind == "cumulative":
            total = 0
            item["values"] = [total := total + (v or 0) for v in item["values"]]
        elif kind == "moving_average":
            window = max(1, min(int(spec.get("window", 3)), 100))
            vals = item["values"]
            item["values"] = [statistics.mean(valid) if (valid := [v for v in vals[max(0,i-window+1):i+1] if v is not None]) else None for i in range(len(vals))]
    if kind == "percent_bar":
        for i in range(len(labels)):
            total = sum(item["values"][i] or 0 for item in series_results)
            for item in series_results:
                item["values"][i] = item["values"][i] / total * 100 if total and item["values"][i] is not None else None
    records = [{str(x or "Group"): label, **{item["name"]: item["values"][i] for item in series_results}} for i,label in enumerate(labels)]
    response.update(labels=labels, series=series_results, rows=records, columns=[str(x or "Group")] + [item["name"] for item in series_results], truncated=original_count > len(labels))
    if kind == "pareto" and series_results:
        vals = series_results[0]["values"]
        total, running = sum(v or 0 for v in vals), 0
        response["cumulative_percent"] = [(running := running + (v or 0)) / total * 100 if total else None for v in vals]
    if kind == "bullet":
        response["value"] = _metric(rows, spec, columns)
        response["target"] = aggregate(rows, spec.get("target_field"), "sum") if spec.get("target_field") else number(spec.get("target"))
    if kind in {"treemap", "sunburst"} and series:
        response["hierarchy"] = [{"name": label, "children": [{"name": item["name"], "value": item["values"][i] or 0} for item in series_results]} for i,label in enumerate(labels)]
    return _safe(response)
