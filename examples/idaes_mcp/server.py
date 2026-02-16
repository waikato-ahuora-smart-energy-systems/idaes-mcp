import io
import os
from contextlib import redirect_stdout
from math import isfinite
from typing import Any

from idaes.core import FlowsheetBlock
from idaes.core.util import DiagnosticsToolbox
from idaes.core.util.model_diagnostics import (
    IpoptConvergenceAnalysis,
    check_parallel_jacobian,
    compute_ill_conditioning_certificate,
)
from idaes.core.util.model_statistics import degrees_of_freedom
from idaes.core.util.parameter_sweep import ParameterSweepSpecification
from idaes.core.surrogate.pysmo.sampling import UniformSampling
from pyomo.environ import SolverFactory
from pyomo.environ import check_optimal_termination
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
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


def start_mcp_server(
    m: Any,
    host: str = "127.0.0.1",
    port: int = 8005,
    allow_remote_hosts: bool = False,
) -> None:
    """Start the IDAES MCP server and register model inspection tools.

    The server exposes read-only diagnostics and model introspection helpers over
    MCP streamable HTTP transport.

    Args:
        m: The Pyomo/IDAES model to inspect.
        host: Bind address (use 0.0.0.0 to accept external connections).
        port: Port to listen on.
        allow_remote_hosts: If True, disable DNS rebinding protection so the server
            accepts requests forwarded via ngrok or other tunnels (Host header will
            be the tunnel hostname, e.g. xxx.ngrok-free.app). Set True when using
            ChatGPT custom connectors or Grok with ngrok. You can also set env var
            MCP_ALLOW_REMOTE_HOSTS=1 instead of passing True.
    """
    transport_security = None
    if allow_remote_hosts or os.environ.get("MCP_ALLOW_REMOTE_HOSTS", "").lower() in ("1", "true", "yes"):
        transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=False,
        )
    server = FastMCP(
        "idaes-mcp",
        host=host,
        port=port,
        streamable_http_path="/mcp",
        transport_security=transport_security,
    )

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

    @server.tool(name="idaes.list_models")
    def list_models() -> dict[str, Any]:
        """List top-level blocks (sub-models) in the Pyomo model.

        Use this to see the model structure (e.g. m.fs, m.unit) before
        listing variables/constraints or running diagnostics.

        Returns:
            A dictionary with:
            - block_names: List of top-level component names that are Blocks.
            - block_names_with_fs: If 'fs' exists, also lists direct child block names under fs.
        """
        block_names = [
            c.name for c in m.component_objects(Block, descend_into=False)
        ]
        out: dict[str, Any] = {"block_names": block_names}
        fs = getattr(m, "fs", None)
        if fs is not None and isinstance(fs, Block):
            out["block_names_with_fs"] = [
                c.name for c in fs.component_objects(Block, descend_into=False)
            ]
        return out

    @server.tool(name="idaes.fixed_variable_summary")
    def fixed_variable_summary(
        pattern: str | None = None,
        limit: int = 300,
    ) -> dict[str, Any]:
        """List fixed variables with their values for quick diagnosis.

        Use this to see specs at a glance (e.g. inlet/outlet T and P, heat_duty)
        so an AI can mirror explanations like 'inlet is 120°C', 'outlet 88°C',
        'heater duty fixed at 50000 kW' without scanning all variables.

        Args:
            pattern: Case-insensitive substring filter for variable names.
            limit: Max number of rows (clamped to [1, 500]).

        Returns:
            A dictionary with:
            - items: List of {name, value, block} for fixed variables (block = first two path segments, e.g. fs.valve).
            - count: Number of items returned.
            - total: Total fixed variables before limit.
        """
        safe_limit = max(1, min(int(limit), 500))
        rows: list[dict[str, Any]] = []
        for variable in m.component_data_objects(Var, descend_into=True):
            if not variable.fixed:
                continue
            name = variable.name
            if not _matches_pattern(name, pattern):
                continue
            parts = name.split(".")
            block = ".".join(parts[:2]) if len(parts) >= 2 else (parts[0] if parts else "")
            rows.append({
                "name": name,
                "value": _safe_value(variable),
                "block": block,
            })
        rows.sort(key=lambda item: (item["block"], item["name"]))
        total = len(rows)
        page = rows[:safe_limit]
        return {"items": page, "count": len(page), "total": total}

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
    def run_diagnostics(include_numerical: bool = False) -> dict[str, Any]:
        """Run IDAES diagnostics and return captured text output.

        Always runs structural checks (no solution required):
        - report_structural_issues()
        - display_underconstrained_set()
        - display_overconstrained_set()

        If include_numerical is True, also runs report_numerical_issues().
        Numerical checks require at least a partial solution; run after solve/initialize.

        Returns:
            A dictionary with:
            - headline: First line of diagnostic output.
            - report_text: Full captured diagnostic text.
            - included_numerical: Whether numerical report was included.
        """
        diagnostics = DiagnosticsToolbox(m)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            diagnostics.report_structural_issues()
            diagnostics.display_underconstrained_set()
            diagnostics.display_overconstrained_set()
            if include_numerical:
                diagnostics.report_numerical_issues()
        text = buffer.getvalue().strip()
        if not text:
            text = "Diagnostics completed with no text output."
        headline = text.splitlines()[0]
        return {
            "headline": headline,
            "report_text": text,
            "included_numerical": include_numerical,
        }

    @server.tool(name="idaes.report_numerical_issues")
    def report_numerical_issues() -> dict[str, Any]:
        """Run IDAES numerical diagnostics (requires at least a partial solution).

        Checks scaling, bounds, residuals, Jacobian, parallel rows/columns, etc.
        Run after initialize/solve. Use after resolving structural issues.

        Returns:
            A dictionary with report_text (captured output).
        """
        diagnostics = DiagnosticsToolbox(m)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            diagnostics.report_numerical_issues()
        text = buffer.getvalue().strip()
        return {"report_text": text or "No numerical issues reported."}

    @server.tool(name="idaes.infeasibility_explanation")
    def infeasibility_explanation(tee: bool = False) -> dict[str, Any]:
        """Explain why the model may be infeasible (relaxations + minimal infeasible set).

        Runs IDAES compute_infeasibility_explanation: finds constraint/bound
        relaxations that yield feasibility and attempts a Minimal Infeasible Set (MIS).
        Expensive (multiple solves). Use when the solver reports infeasible.

        Args:
            tee: If True, include solver log in output (noisier).

        Returns:
            A dictionary with report_text (explanation). On error, error message.
        """
        diagnostics = DiagnosticsToolbox(m)
        buffer = io.StringIO()
        try:
            with redirect_stdout(buffer):
                diagnostics.compute_infeasibility_explanation(stream=buffer, tee=tee)
            text = buffer.getvalue().strip()
            return {"report_text": text or "Infeasibility explanation produced no output."}
        except Exception as e:
            return {"error": str(e), "report_text": buffer.getvalue().strip()}

    @server.tool(name="idaes.dulmage_mendelsohn_partition")
    def dulmage_mendelsohn_partition() -> dict[str, Any]:
        """Return Dulmage–Mendelsohn partition: under- and over-constrained subproblems.

        Structured data (not just text): use to see exactly which variables/constraints
        are in the under-constrained set (need more specs) vs over-constrained set
        (redundant or conflicting). Essential for debugging DOF and structural singularity.

        Returns:
            A dictionary with:
            - under_constrained_variables: List of variable name lists per block.
            - under_constrained_constraints: List of constraint name lists per block.
            - over_constrained_variables: List of variable name lists per block.
            - over_constrained_constraints: List of constraint name lists per block.
        """
        diagnostics = DiagnosticsToolbox(m)
        try:
            u_vars, u_cons, o_vars, o_cons = diagnostics.get_dulmage_mendelsohn_partition()
        except Exception as e:
            return {"error": str(e)}

        def names(component_lists: Any) -> list[list[str]]:
            return [[getattr(c, "name", str(c)) for c in group] for group in component_lists]

        return {
            "under_constrained_variables": names(u_vars),
            "under_constrained_constraints": names(u_cons),
            "over_constrained_variables": names(o_vars),
            "over_constrained_constraints": names(o_cons),
        }

    _DIAGNOSTICS_DISPLAY_METHODS = {
        "large_residuals": "display_constraints_with_large_residuals",
        "canceling_terms": "display_constraints_with_canceling_terms",
        "mismatched_terms": "display_constraints_with_mismatched_terms",
        "inconsistent_units": "display_components_with_inconsistent_units",
        "potential_evaluation_errors": "display_potential_evaluation_errors",
        "external_variables": "display_external_variables",
        "unused_variables": "display_unused_variables",
        "no_free_variables": "display_constraints_with_no_free_variables",
        "near_parallel_constraints": "display_near_parallel_constraints",
        "near_parallel_variables": "display_near_parallel_variables",
        "variables_at_bounds": "display_variables_at_or_outside_bounds",
        "variables_near_bounds": "display_variables_near_bounds",
        "variables_fixed_to_zero": "display_variables_fixed_to_zero",
        "variables_extreme_values": "display_variables_with_extreme_values",
        "variables_none_value": "display_variables_with_none_value",
        "variables_near_zero": "display_variables_with_value_near_zero",
        "extreme_jacobian_constraints": "display_constraints_with_extreme_jacobians",
        "extreme_jacobian_variables": "display_variables_with_extreme_jacobians",
        "extreme_jacobian_entries": "display_extreme_jacobian_entries",
    }

    @server.tool(name="idaes.diagnostics_display")
    def diagnostics_display(display_kind: str) -> dict[str, Any]:
        """Run a specific DiagnosticsToolbox display method and return its output.

        Use for targeted insight after report_structural_issues or report_numerical_issues
        suggest next steps. display_kind must be one of: large_residuals, canceling_terms,
        mismatched_terms, inconsistent_units, potential_evaluation_errors, external_variables,
        unused_variables, no_free_variables, near_parallel_constraints, near_parallel_variables,
        variables_at_bounds, variables_near_bounds, variables_fixed_to_zero, variables_extreme_values,
        variables_none_value, variables_near_zero, extreme_jacobian_constraints, extreme_jacobian_variables,
        extreme_jacobian_entries.

        Returns:
            A dictionary with report_text (captured output). On error, error key.
        """
        method_name = _DIAGNOSTICS_DISPLAY_METHODS.get(display_kind)
        if not method_name:
            return {
                "error": f"Unknown display_kind. Choose from: {list(_DIAGNOSTICS_DISPLAY_METHODS.keys())}",
            }
        diagnostics = DiagnosticsToolbox(m)
        method = getattr(diagnostics, method_name, None)
        if method is None:
            return {"error": f"DiagnosticsToolbox has no method {method_name}"}
        buffer = io.StringIO()
        try:
            with redirect_stdout(buffer):
                method(stream=buffer)
            text = buffer.getvalue().strip()
            return {"report_text": text or f"{display_kind}: no output."}
        except Exception as e:
            return {"error": str(e), "report_text": buffer.getvalue().strip()}

    @server.tool(name="idaes.near_parallel_jacobian")
    def near_parallel_jacobian(
        direction: str = "row",
        tolerance: float = 0.0001,
    ) -> dict[str, Any]:
        """Find near-parallel rows (constraints) or columns (variables) in the Jacobian.

        Parallel rows/columns indicate possible degeneracy or redundant constraints/variables.
        Based on Klotz, INFORMS 2014.

        Args:
            direction: 'row' for constraints (default), 'column' for variables.
            tolerance: Cosine similarity tolerance (default 0.0001).

        Returns:
            A dictionary with pairs: list of 2-tuples of component names.
        """
        try:
            pairs = check_parallel_jacobian(m, tolerance=tolerance, direction=direction)
            return {
                "pairs": [[p[0].name, p[1].name] for p in pairs],
                "count": len(pairs),
                "direction": direction,
            }
        except Exception as e:
            return {"error": str(e), "pairs": [], "count": 0}

    @server.tool(name="idaes.ill_conditioning_certificate")
    def ill_conditioning_certificate(
        direction: str = "row",
        target_feasibility_tol: float = 1e-6,
        ratio_cutoff: float = 0.0001,
    ) -> dict[str, Any]:
        """Identify constraints (rows) or variables (columns) contributing to ill-conditioning.

        Returns certificate strings pointing to problematic components. Based on Klotz, INFORMS 2014.

        Args:
            direction: 'row' (constraints) or 'column' (variables).
            target_feasibility_tol: Feasibility tolerance for the certificate problem.
            ratio_cutoff: Cutoff for reporting.

        Returns:
            A dictionary with certificate_strings (list) and optional error.
        """
        try:
            cert = compute_ill_conditioning_certificate(
                m,
                target_feasibility_tol=target_feasibility_tol,
                ratio_cutoff=ratio_cutoff,
                direction=direction,
            )
            return {"certificate_strings": list(cert), "count": len(cert)}
        except Exception as e:
            return {"error": str(e), "certificate_strings": [], "count": 0}

    @server.tool(name="idaes.svd_underdetermined")
    def svd_underdetermined(
        number_of_smallest: int = 5,
    ) -> dict[str, Any]:
        """Run SVD analysis and return underdetermined variables/constraints (small singular values).

        Identifies scaling/rank-deficiency: constraints and variables associated with
        the smallest singular values. Expensive on large models.

        Args:
            number_of_smallest: Number of smallest singular values to consider (default 5).

        Returns:
            A dictionary with report_text (captured output). On error, error key.
        """
        diagnostics = DiagnosticsToolbox(m)
        buffer = io.StringIO()
        try:
            svd = diagnostics.prepare_svd_toolbox(
                number_of_smallest_singular_values=number_of_smallest,
            )
            with redirect_stdout(buffer):
                svd.run_svd_analysis()
                svd.display_underdetermined_variables_and_constraints(stream=buffer)
            text = buffer.getvalue().strip()
            return {"report_text": text or "SVD produced no output."}
        except Exception as e:
            return {"error": str(e), "report_text": buffer.getvalue().strip()}

    @server.tool(name="idaes.degeneracy_report")
    def degeneracy_report(tee: bool = False) -> dict[str, Any]:
        """Find and report Irreducible Degenerate Sets (IDS) via Degeneracy Hunter.

        Requires an MILP solver (e.g. SCIP). IDs are minimal sets of constraints that
        are linearly dependent; fixing them helps resolve degeneracy.

        Args:
            tee: If True, include solver log in output.

        Returns:
            A dictionary with report_text. On error (e.g. no solver), error key.
        """
        diagnostics = DiagnosticsToolbox(m)
        buffer = io.StringIO()
        try:
            hunter = diagnostics.prepare_degeneracy_hunter()
            with redirect_stdout(buffer):
                hunter.report_irreducible_degenerate_sets(stream=buffer, tee=tee)
            text = buffer.getvalue().strip()
            return {"report_text": text or "Degeneracy Hunter produced no output."}
        except Exception as e:
            return {"error": str(e), "report_text": buffer.getvalue().strip()}

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

    @server.tool(name="idaes.convergence_analysis")
    def convergence_analysis(
        inputs: list[dict[str, Any]],
        sample_size: list[int],
    ) -> dict[str, Any]:
        """Run IDAES IpoptConvergenceAnalysis: parameter sweep over given inputs and report convergence per point.

        Uses UniformSampling over [lower, upper] for each input. Runs the model at each sample point and reports iterations, time, and numerical issues. Runs sequentially (no parallel). Use to test multiple values and see where the model solves well or fails.

        Args:
            inputs: List of dicts, each with keys pyomo_path (str), lower (float), upper (float), and optional name (str). Example: [{"pyomo_path": "m.fs.unit.inlet.flow_mol[0]", "lower": 1, "upper": 20, "name": "flow"}].
            sample_size: For UniformSampling, list of ints: number of points per input (e.g. [3, 2] for 3×2 = 6 samples with 2 inputs).

        Returns:
            report_text: Summary from report_convergence_summary.
            results_summary: {total_samples, success_count, results_per_sample: [{iters, time, numerical_issues}, ...]}.
            On error: error key.
        """
        if len(inputs) != len(sample_size):
            return {"error": "inputs and sample_size length must match (one sample_size per input)."}
        try:
            spec = ParameterSweepSpecification()
            for inp in inputs:
                path = inp.get("pyomo_path")
                lo = float(inp.get("lower"))
                up = float(inp.get("upper"))
                name = inp.get("name", path)
                if path is None or lo is None or up is None:
                    return {"error": "Each input must have pyomo_path, lower, upper."}
                spec.add_sampled_input(path, lo, up, name=name)
            spec.set_sampling_method(UniformSampling)
            spec.set_sample_size(sample_size)
            spec.generate_samples()
        except Exception as e:
            return {"error": str(e)}
        try:
            analysis = IpoptConvergenceAnalysis(m, input_specification=spec)
            results = analysis.run_convergence_analysis()
        except Exception as e:
            return {"error": str(e)}
        buffer = io.StringIO()
        try:
            analysis.report_convergence_summary(stream=buffer)
            report_text = buffer.getvalue().strip()
        except Exception:
            report_text = ""
        results_summary = {"total_samples": len(results), "success_count": 0, "results_per_sample": []}
        for i, (sid, data) in enumerate(results.items()):
            if isinstance(data, dict) and data.get("results"):
                out = data["results"]
                results_summary["results_per_sample"].append({
                    "sample_id": sid,
                    "iters": out.get("iters", -1),
                    "time": out.get("time", -1),
                    "numerical_issues": out.get("numerical_issues", False),
                })
                if data.get("success"):
                    results_summary["success_count"] += 1
            else:
                results_summary["results_per_sample"].append({"sample_id": sid, "error": str(data)})
        return {"report_text": report_text or "Convergence analysis completed.", "results_summary": results_summary}

    @server.tool(name="idaes.solve_one_point")
    def solve_one_point(
        variable_values: dict[str, float],
        solver_name: str = "ipopt",
    ) -> dict[str, Any]:
        """Set specified variables to given values, solve the model once, then restore original state.

        Use to test a single operating point (e.g. one set of inputs). variable_values maps Pyomo path strings to numbers (e.g. {"m.fs.unit.inlet.flow_mol[0]": 10.0}). Variables are temporarily fixed; after solve, they are unfixed and restored to previous values.

        Args:
            variable_values: Dict mapping pyomo_path (str) to value (float).
            solver_name: Solver to use (default ipopt).

        Returns:
            success: True if optimal termination.
            termination_condition: Solver termination condition string.
            message: Solver message if any.
            error: Set if exception during solve or restore.
        """
        saved: list[tuple[Any, float | None, bool]] = []
        try:
            for path, val in variable_values.items():
                comp = m.find_component(path)
                if comp is None:
                    for c, ov, wf in saved:
                        try:
                            if hasattr(c, "unfix"):
                                c.unfix()
                                if wf and ov is not None:
                                    c.fix(ov)
                            elif hasattr(c, "value") and ov is not None:
                                c.value = ov
                        except Exception:
                            pass
                    return {"error": f"Component not found: {path}"}
                if hasattr(comp, "fix"):
                    was_fixed = comp.fixed
                    old_val = _safe_value(comp)
                    comp.fix(float(val))
                    saved.append((comp, old_val, was_fixed))
                elif hasattr(comp, "value"):
                    old_val = getattr(comp, "value", None)
                    comp.value = float(val)
                    saved.append((comp, old_val, False))
            solver = SolverFactory(solver_name)
            results = solver.solve(m, tee=False)
            success = bool(check_optimal_termination(results))
            tc = str(getattr(results.solver, "termination_condition", "unknown"))
            msg = str(getattr(results.solver, "message", "") or "")
        except Exception as e:
            tc = ""
            msg = ""
            success = False
            results = None
            err = str(e)
        for comp, old_val, was_fixed in saved:
            try:
                if hasattr(comp, "unfix"):
                    comp.unfix()
                    if was_fixed and old_val is not None:
                        comp.fix(old_val)
                elif hasattr(comp, "value") and old_val is not None:
                    comp.value = old_val
            except Exception:
                pass
        if results is None:
            return {"success": False, "termination_condition": "", "message": msg or err, "error": err}
        return {"success": success, "termination_condition": tc, "message": msg or ""}

    @server.tool(name="idaes.solve_flowsheet")
    def solve_flowsheet(
        solver_name: str = "ipopt",
        tee: bool = False,
    ) -> dict[str, Any]:
        """Solve the whole flowsheet (current model) with the given solver.

        Runs solver.solve(m) on the in-memory model. Use after the model is built and (ideally) initialized. Does not mutate or restore variables; the solution remains in the model.

        Args:
            solver_name: Solver to use (default ipopt).
            tee: If True, solver log is printed to server stdout (noisier).

        Returns:
            success: True if optimal termination.
            termination_condition: Solver termination condition string.
            message: Solver message if any.
            error: Set if solver or model raised an exception.
        """
        try:
            solver = SolverFactory(solver_name)
            results = solver.solve(m, tee=tee)
            success = bool(check_optimal_termination(results))
            tc = str(getattr(results.solver, "termination_condition", "unknown"))
            msg = str(getattr(results.solver, "message", "") or "")
            return {"success": success, "termination_condition": tc, "message": msg or ""}
        except Exception as e:
            return {"success": False, "termination_condition": "", "message": "", "error": str(e)}

    @server.tool(name="idaes.unfix_variables")
    def unfix_variables(paths: list[str]) -> dict[str, Any]:
        """Unfix the given variables in the live model (persistent until server restarts).

        Use this to free degrees of freedom so you can run solve_one_point or convergence_analysis with different values. With DOF=0, any extra fix in solve_one_point makes DOF negative and the solver fails; unfix specs here first (e.g. valve outlet temperatures), then test new operating points.

        Args:
            paths: List of Pyomo variable path strings (e.g. ["m.fs.Effect1Valve_1643611.control_volume.properties_out[0.0].temperature"]).

        Returns:
            unfixed: Number of variables unfixed.
            not_found: List of paths that could not be resolved.
            degrees_of_freedom: Model DOF after unfixing.
            error: Set if a path resolved to a non-variable or unfix failed.
        """
        not_found: list[str] = []
        unfixed = 0
        for path in paths:
            comp = m.find_component(path)
            if comp is None:
                not_found.append(path)
                continue
            if not hasattr(comp, "unfix"):
                return {"unfixed": unfixed, "not_found": not_found, "degrees_of_freedom": degrees_of_freedom(m), "error": f"Not a variable (no unfix): {path}"}
            try:
                comp.unfix()
                unfixed += 1
            except Exception as e:
                return {"unfixed": unfixed, "not_found": not_found, "degrees_of_freedom": degrees_of_freedom(m), "error": f"Unfix failed for {path}: {e}"}
        return {"unfixed": unfixed, "not_found": not_found, "degrees_of_freedom": degrees_of_freedom(m)}

    @server.tool(name="idaes.fix_variables")
    def fix_variables(variable_values: dict[str, float]) -> dict[str, Any]:
        """Set variables to the given values and fix them in the live model (persistent until server restarts).

        Use to swap specs: e.g. unfix valve outlet temperatures (unfix_variables), then fix a different variable (e.g. feed flow_mol) here so the model stays square. Also use to correct brittle specs (e.g. phase split 0.0 -> 0.001).

        Args:
            variable_values: Dict mapping Pyomo variable path to value (e.g. {"m.fs.Preheater_1643423.cold_side.properties_in[0.0].flow_mol": 1200.0}).

        Returns:
            fixed: Number of variables set and fixed.
            not_found: List of paths that could not be resolved.
            degrees_of_freedom: Model DOF after fixing.
            error: Set if a path resolved to a non-variable or fix failed.
        """
        not_found: list[str] = []
        fixed = 0
        for path, val in variable_values.items():
            comp = m.find_component(path)
            if comp is None:
                not_found.append(path)
                continue
            if hasattr(comp, "fix"):
                try:
                    comp.fix(float(val))
                    fixed += 1
                except Exception as e:
                    return {"fixed": fixed, "not_found": not_found, "degrees_of_freedom": degrees_of_freedom(m), "error": f"Fix failed for {path}: {e}"}
            elif hasattr(comp, "value"):
                try:
                    comp.value = float(val)
                    fixed += 1
                except Exception as e:
                    return {"fixed": fixed, "not_found": not_found, "degrees_of_freedom": degrees_of_freedom(m), "error": f"Set value failed for {path}: {e}"}
            else:
                return {"fixed": fixed, "not_found": not_found, "degrees_of_freedom": degrees_of_freedom(m), "error": f"Not a variable: {path}"}
        return {"fixed": fixed, "not_found": not_found, "degrees_of_freedom": degrees_of_freedom(m)}

    @server.tool(name="idaes.set_constraints_active")
    def set_constraints_active(paths: list[str], active: bool) -> dict[str, Any]:
        """Activate or deactivate constraints in the live model (persistent until server restarts).

        This is the constraint analogue of fix/unfix: active=True means the constraint is included in the model (\"fixed in\"); active=False means it is excluded (\"unfixed\"). Use to remove redundant or problematic specs: e.g. if temperature is both fixed and constrained, deactivate the extra constraint (active=False) so the model is not over-constrained. Use list_constraints / dulmage_mendelsohn_partition to find constraint paths.

        Args:
            paths: List of Pyomo constraint path strings (e.g. ["m.fs.unit.equality_temperature"]).
            active: True to activate (include in model), False to deactivate (exclude).

        Returns:
            changed: Number of constraints set to the requested active state.
            not_found: List of paths that could not be resolved.
            error: Set if a path resolved to a non-constraint or set failed.
        """
        not_found: list[str] = []
        changed = 0
        for path in paths:
            comp = m.find_component(path)
            if comp is None:
                not_found.append(path)
                continue
            if not hasattr(comp, "active"):
                return {"changed": changed, "not_found": not_found, "error": f"Not a constraint (no active): {path}"}
            try:
                comp.activate() if active else comp.deactivate()
                changed += 1
            except Exception as e:
                return {"changed": changed, "not_found": not_found, "error": f"Set active failed for {path}: {e}"}
        return {"changed": changed, "not_found": not_found}

    @server.tool(name="idaes.set_variable_bounds")
    def set_variable_bounds(variable_bounds: dict[str, dict[str, float | None]]) -> dict[str, Any]:
        """Set lower and/or upper bounds on variables in the live model (persistent until server restarts).

        IDAES workflow: after unfixing some variables for optimization, add bounds to constrain the solution space (variable.setlb / setub). Also use to relax bounds when infeasibility_explanation suggests loosening a bound. list_variables returns current lb/ub.

        Args:
            variable_bounds: Dict mapping Pyomo variable path to {"lower": float or None, "upper": float or None}. Omit "lower" or "upper" to leave that bound unchanged; use None to clear the bound (no limit). Example: {"m.fs.unit.flow[0]": {"lower": 0, "upper": 1000}}.

        Returns:
            changed: Number of variables whose bounds were updated.
            not_found: List of paths that could not be resolved.
            degrees_of_freedom: Model DOF after changes (bounds do not change DOF).
            error: Set if a path resolved to a non-variable or setlb/setub failed.
        """
        not_found: list[str] = []
        changed = 0
        for path, bounds in variable_bounds.items():
            comp = m.find_component(path)
            if comp is None:
                not_found.append(path)
                continue
            if not hasattr(comp, "setlb") and not hasattr(comp, "setub"):
                return {"changed": changed, "not_found": not_found, "degrees_of_freedom": degrees_of_freedom(m), "error": f"Not a variable (no setlb/setub): {path}"}
            try:
                if "lower" in bounds:
                    val = bounds["lower"]
                    if val is None:
                        comp.setlb(None)
                    else:
                        comp.setlb(float(val))
                if "upper" in bounds:
                    val = bounds["upper"]
                    if val is None:
                        comp.setub(None)
                    else:
                        comp.setub(float(val))
                if "lower" in bounds or "upper" in bounds:
                    changed += 1
            except Exception as e:
                return {"changed": changed, "not_found": not_found, "degrees_of_freedom": degrees_of_freedom(m), "error": f"Set bounds failed for {path}: {e}"}
        return {"changed": changed, "not_found": not_found, "degrees_of_freedom": degrees_of_freedom(m)}

    server.run(transport="streamable-http")
