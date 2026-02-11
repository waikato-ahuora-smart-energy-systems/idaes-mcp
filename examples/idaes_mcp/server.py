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
    """Start the IDAES MCP server and register model inspection tools.

    The server exposes read-only diagnostics and model introspection helpers over
    MCP streamable HTTP transport.
    """
    server = FastMCP("idaes-mcp", host=host, port=port, streamable_http_path="/mcp")

    @server.tool(name="idaes.model_summary")
    def model_summary() -> dict[str, Any]:
        """Return a high-level summary of the active Pyomo/IDAES model.

        Returns:
            A dictionary with:
            - degrees_of_freedom: Integer model DOF.
            - n_variables: Total number of variables.
            - n_constraints: Total number of constraints.
            - n_fixed_variables: Number of fixed variables.
        """
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
        """List model variables with optional filtering and pagination.

        Args:
            pattern: Case-insensitive substring filter for variable names.
            only_unfixed: If True, return only variables where fixed is False.
            limit: Page size (clamped to [1, 500]).
            offset: Starting index for pagination (clamped to >= 0).

        Returns:
            A page dictionary with keys:
            - items: List of variable rows sorted by name.
            - count: Number of rows in this page.
            - total: Total rows before pagination.
            - limit: Effective limit after clamping.
            - offset: Effective offset after clamping.

            Each item includes:
            - name: Variable name.
            - value: Numeric value if evaluable, otherwise null.
            - fixed: Whether the variable is fixed.
            - lb: Numeric lower bound if finite, otherwise null.
            - ub: Numeric upper bound if finite, otherwise null.
        """
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
        """List model constraints with optional filtering and pagination.

        Args:
            pattern: Case-insensitive substring filter for constraint names.
            limit: Page size (clamped to [1, 500]).
            offset: Starting index for pagination (clamped to >= 0).

        Returns:
            A page dictionary with keys:
            - items: List of constraint rows sorted by name.
            - count: Number of rows in this page.
            - total: Total rows before pagination.
            - limit: Effective limit after clamping.
            - offset: Effective offset after clamping.

            Each item includes:
            - name: Constraint name.
            - active: Whether the constraint is active.
            - lower: Numeric lower bound if evaluable, otherwise null.
            - upper: Numeric upper bound if evaluable, otherwise null.
        """
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
        """Return the largest constraint residuals for quick feasibility triage.

        Residual is computed as violation magnitude against lower/upper bounds.
        Equality constraints use |body - bound|. Feasible constraints return 0.

        Args:
            n: Number of top residual rows to return (clamped to [1, 500]).
            pattern: Case-insensitive substring filter for constraint names.

        Returns:
            A dictionary with:
            - items: Residual rows sorted descending by residual.
            - count: Number of rows returned.
            - total: Total residual rows considered after filtering.

            Each item includes:
            - name: Constraint name.
            - residual: Non-negative residual magnitude.
        """
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
        """Run IDAES structural diagnostics and return captured text output.

        This tool captures standard output from:
        - report_structural_issues()
        - display_underconstrained_set()
        - display_overconstrained_set()

        Returns:
            A dictionary with:
            - headline: First line of diagnostic output.
            - report_text: Full captured diagnostic text.
        """
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
        """Run report() on top-level flowsheet blocks and capture text output.

        Expects a FlowsheetBlock at m.fs and calls report() on each direct child
        block where report() exists.

        Returns:
            A dictionary with:
            - report_text: Combined captured report output.

            If m.fs is missing or not a FlowsheetBlock, returns:
            - error: Error description.
        """
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
