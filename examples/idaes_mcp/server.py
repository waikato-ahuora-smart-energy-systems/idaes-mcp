import io
from contextlib import redirect_stdout
from math import isfinite
from typing import Any

from idaes.core import FlowsheetBlock
from idaes.core.util import DiagnosticsToolbox
from idaes.core.util.model_statistics import degrees_of_freedom
from mcp.server.fastmcp import FastMCP
from pyomo.environ import Block, Constraint, Var, value

def _safe_float(raw: Any) -> float | None:
    if raw is None:
        return None
    try:
        number = float(raw)
    except (TypeError, ValueError):
        return None
    if not isfinite(number):
        return None
    return number

def _safe_value(raw: Any) -> float | None:
    try:
        return _safe_float(value(raw, exception=False))
    except Exception:
        return None

def _compute_constraint_residual(constraint: Constraint) -> float | None:
    body = _safe_value(constraint.body)
    lower = _safe_value(constraint.lower)
    upper = _safe_value(constraint.upper)
    if body is None:
        return None
    if lower is not None and upper is not None and abs(lower - upper) <= 1e-12:
        return abs(body - lower)
    if lower is not None and body < lower:
        return lower - body
    if upper is not None and body > upper:
        return body - upper
    return 0.0

def _matches_pattern(name: str, pattern: str | None) -> bool:
    if not pattern:
        return True
    return pattern.lower() in name.lower()

def _paginate(items: list[dict[str, Any]], limit: int, offset: int) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit), 500))
    safe_offset = max(0, int(offset))
    page = items[safe_offset : safe_offset + safe_limit]
    return {
        "items": page,
        "count": len(page),
        "total": len(items),
        "limit": safe_limit,
        "offset": safe_offset,
    }


def start_mcp_server(m: Any, host: str = "127.0.0.1", port: int = 8005) -> None:
    server = FastMCP("idaes-mcp", host=host, port=port, streamable_http_path="/mcp")

    @server.tool(name="idaes.model_summary")
    def model_summary() -> dict[str, Any]:
        variables = list(m.component_data_objects(Var, descend_into=True))
        constraints = list(m.component_data_objects(Constraint, descend_into=True))
        return {
            "degrees_of_freedom": degrees_of_freedom(m),
            "n_variables": len(variables),
            "n_constraints": len(constraints),
            "n_fixed_variables": sum(1 for variable in variables if variable.fixed),
        }

    @server.tool(name="idaes.list_variables")
    def list_variables(
        pattern: str | None = None,
        only_unfixed: bool = False,
        limit: int = 200,
        offset: int = 0,
    ) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        for variable in m.component_data_objects(Var, descend_into=True):
            name = variable.name
            if not _matches_pattern(name, pattern):
                continue
            if only_unfixed and variable.fixed:
                continue
            rows.append(
                {
                    "name": name,
                    "value": _safe_value(variable),
                    "fixed": bool(variable.fixed),
                    "lb": _safe_float(variable.lb),
                    "ub": _safe_float(variable.ub),
                }
            )
        rows.sort(key=lambda item: item["name"])
        return _paginate(rows, limit, offset)

    @server.tool(name="idaes.list_constraints")
    def list_constraints(
        pattern: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        for constraint in m.component_data_objects(Constraint, descend_into=True):
            name = constraint.name
            if not _matches_pattern(name, pattern):
                continue
            rows.append(
                {
                    "name": name,
                    "active": bool(constraint.active),
                    "lower": _safe_value(constraint.lower),
                    "upper": _safe_value(constraint.upper),
                }
            )
        rows.sort(key=lambda item: item["name"])
        return _paginate(rows, limit, offset)

    @server.tool(name="idaes.top_constraint_residuals")
    def top_constraint_residuals(
        n: int = 50,
        pattern: str | None = None,
    ) -> dict[str, Any]:
        safe_n = max(1, min(int(n), 500))
        rows: list[dict[str, Any]] = []
        for constraint in m.component_data_objects(Constraint, descend_into=True):
            name = constraint.name
            if not _matches_pattern(name, pattern):
                continue
            residual = _compute_constraint_residual(constraint)
            if residual is None:
                continue
            rows.append({"name": name, "residual": residual})
        rows.sort(key=lambda item: item["residual"], reverse=True)
        return {"items": rows[:safe_n], "count": min(len(rows), safe_n), "total": len(rows)}

    @server.tool(name="idaes.run_diagnostics")
    def run_diagnostics() -> dict[str, Any]:
        diagnostics = DiagnosticsToolbox(m)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            diagnostics.report_structural_issues()
            diagnostics.display_underconstrained_set()
            diagnostics.display_overconstrained_set()
        text = buffer.getvalue().strip()
        if not text:
            text = "Diagnostics completed with no text output."
        headline = text.splitlines()[0]
        return {"headline": headline, "report_text": text}

    @server.tool(name="idaes.flowsheet_report")
    def flowsheet_report() -> dict[str, Any]:
        fs = getattr(m, "fs", None)
        if fs is None or not isinstance(fs, FlowsheetBlock):
            return {"error": "No FlowsheetBlock found at m.fs"}
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            for block in fs.component_data_objects(Block, descend_into=False):
                if hasattr(block, "report"):
                    try:
                        block.report()
                    except Exception as exc:
                        print(f"[{block.name}] report() failed: {exc}")
        text = buffer.getvalue().strip()
        if not text:
            text = "Flowsheet report produced no output."
        return {"report_text": text}

    server.run(transport="streamable-http")
