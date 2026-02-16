
# IDAES MCP Server

## Setup

```bash
uv sync
uv run idaes get-extensions
```

I'm not sure how nicely idaes get-extensions plays with uv. Make sure  the `ipopt` command works. 

If it doesn't, the easiest thing to do is install idaes locally as well:

```bash
pip install idaes-pse
idaes get-extensions
```


# Usage

This MVP starts an MCP-over-HTTP server from the same process that owns the model.

```bash
uv run main.py
```

The demo entrypoint builds a tiny model and starts the server at:

```text
http://127.0.0.1:8000/mcp
```

In your own script, build `m` first and then call:

```python
from idaes_mcp.server import start_mcp_server

start_mcp_server(m, host="127.0.0.1", port=8000)
```

Available tools:

**Model overview**
- `idaes.list_models` – Top-level blocks (e.g. `fs`) and, if present, blocks under `fs`
- `idaes.model_summary` – DOF, variable/constraint counts, fixed variable count
- `idaes.list_variables` – List/filter variables (value, bounds, fixed)
- `idaes.list_constraints` – List/filter constraints (bounds, active)
- `idaes.fixed_variable_summary` – Fixed variables with name, value, and block (quick view of specs for diagnosis)
- `idaes.flowsheet_report` – Unit `report()` output for flowsheet blocks

**Structural and numerical diagnostics**
- `idaes.run_diagnostics` – Structural report + under/over-constrained sets; use `include_numerical=True` after solve
- `idaes.report_numerical_issues` – Full numerical report (scaling, residuals, Jacobian, etc.; requires a solution)
- `idaes.top_constraint_residuals` – Largest constraint violations (quick feasibility triage)
- `idaes.dulmage_mendelsohn_partition` – Structured under/over-constrained variable and constraint sets (by block)
- `idaes.diagnostics_display` – Run a specific display (e.g. `large_residuals`, `inconsistent_units`, `near_parallel_constraints`); see tool description for `display_kind` options

**Advanced / high-insight**
- `idaes.infeasibility_explanation` – Why the model is infeasible (relaxations + minimal infeasible set); runs extra solves
- `idaes.near_parallel_jacobian` – Near-parallel constraint rows or variable columns (degeneracy / redundancy)
- `idaes.ill_conditioning_certificate` – Constraints/variables contributing to ill-conditioning (Klotz-style)
- `idaes.svd_underdetermined` – SVD-based underdetermined variables/constraints (small singular values)
- `idaes.degeneracy_report` – Irreducible degenerate sets (IDS); requires MILP solver (e.g. SCIP)

**Solve**
- `idaes.solve_flowsheet` – Solve the whole flowsheet (current model) with ipopt or another solver; returns success, termination_condition, message. Solution stays in the model.

**Change specs in the live model (persistent until server restarts)**  
*Required so the model can have DOF > 0 and you can run solve_one_point / convergence_analysis.*
- `idaes.unfix_variables` – Unfix given variable paths (frees DOF). Use e.g. to unfix valve outlet temperatures so you can sweep feed flow.
- `idaes.fix_variables` – Set variables to values and fix them (e.g. swap specs or set phase split 0.0 → 0.001).
- `idaes.set_constraints_active` – **Fix/unfix constraints**: activate (`active=True`) or deactivate (`active=False`) constraints by path. Use to remove redundant specs (e.g. duplicate temperature constraint).
- `idaes.set_variable_bounds` – Set lower/upper bounds on variables (setlb/setub). Use for optimization (bound decision variables) or to relax bounds when infeasibility_explanation suggests it.

**Test multiple values (after freeing DOF)**
- `idaes.solve_one_point` – Set given variables to values, solve once, **restore** state; for testing one operating point. Only works if DOF ≥ 0 after the temporary fixes (so unfix some specs first if DOF was 0).
- `idaes.convergence_analysis` – Parameter sweep over input ranges (UniformSampling); runs model at each sample, returns iterations/time/numerical_issues per point (sequential). Requires DOF ≥ 0 for the sweep inputs.


## Model diagnostics workflow (for real insight)

1. **Structural (no solution needed)**  
   `run_diagnostics()` → fix DOF, then use `dulmage_mendelsohn_partition()` to see exactly which variables/constraints are under- or over-constrained. Follow up with `diagnostics_display("inconsistent_units")`, `diagnostics_display("potential_evaluation_errors")`, etc. as suggested in the report.

2. **After initialize/solve**  
   `run_diagnostics(include_numerical=True)` or `report_numerical_issues()`. Use `top_constraint_residuals` for quick feasibility check and `diagnostics_display("large_residuals")` for details.

3. **If solver says infeasible**  
   `infeasibility_explanation()` to get relaxations and a minimal infeasible set (conflicting constraints/bounds).

4. **Scaling / degeneracy**  
   `near_parallel_jacobian(direction="row")` or `direction="column"`, `ill_conditioning_certificate()`, then `svd_underdetermined()` and optionally `degeneracy_report()` (needs SCIP or another MILP solver).

# Examples

The example files show working and broken idaes flowsheets. A description file is also provided.
