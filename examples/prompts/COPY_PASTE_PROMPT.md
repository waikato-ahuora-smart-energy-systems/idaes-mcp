# Copy-paste this prompt to the AI (Grok, ChatGPT, etc.) that has the IDAES MCP tools

Paste everything below the line into your chat.

---

You are helping me make my IDAES flowsheet model **non-brittle** and robust. The flowsheet is served by an MCP server with IDAES tools. Your goal is to **review the model, solve it, apply changes (fix/unfix variables, activate/deactivate constraints, set bounds), then provide a clear list of recommended changes** so the solved model is not numerically fragile.

## Your workflow

1. **Review**
   - Use `idaes.model_summary` (DOF, vars, constraints, fixed count).
   - Use `idaes.fixed_variable_summary` to see current specs (look for valve outlet temperatures, 1.0/0.0 or 0.999/0.001 split fractions, variables fixed to zero).
   - Use `idaes.list_constraints(pattern="temperature")` to find temperature-related constraints (redundant temperature specs cause ill-conditioning).
   - Use `idaes.run_diagnostics()` then `idaes.run_diagnostics(include_numerical=True)` after a solve to see structural and numerical issues (Jacobian condition number, variables at bounds).
   - Use `idaes.dulmage_mendelsohn_partition` if you need to see under/over-constrained sets.

2. **Solve**
   - Use `idaes.solve_flowsheet(solver_name="ipopt")` to get the current solve status and confirm the model solves.

3. **Change (fix/unfix, constraints, bounds)**
   - Prefer **one batch** of changes when possible: use **`idaes.apply_changes_and_solve`** with:
     - `unfix_variable_paths`: e.g. valve outlet temperatures (Effect1Valve, Effect2Valve, Valve6) so valves are not used as temperature setters.
     - `fix_variable_values`: e.g. soften split fractions (0.0 → 0.001, 1.0 → 0.999) or set a feed flow.
     - `deactivate_constraint_paths`: redundant temperature constraints (from list_constraints).
     - `variable_bounds`: optional, to relax bounds if diagnostics suggest it.
     - `solve=True` so you get apply summary + model summary + solve result + top residuals in one call.
   - If you prefer step-by-step, use `idaes.unfix_variables`, `idaes.fix_variables`, `idaes.set_constraints_active`, `idaes.set_variable_bounds`, then `idaes.solve_flowsheet`.

4. **Iterate**
   - Re-run diagnostics and, if DOF > 0, use `idaes.solve_one_point` or `idaes.convergence_analysis` to test multiple operating points. Adjust specs again with `apply_changes_and_solve` or the individual tools until the model solves reliably and numerical diagnostics improve (e.g. condition number drops).

5. **Provide changes**
   - At the end, give me a concise **list of changes to apply** (for my JSON or flowsheet builder), for example:
     - Unfix: [list of variable paths]
     - Fix: [path: value, ...]
     - Deactivate constraints: [list of constraint paths]
     - Variable bounds: [path: {lower, upper}, ...]
   - Note: you have already applied these in the live model; this list is so I can persist them (e.g. in the JSON) if I restart.

## Important details

- **Temperature as constraint**: In this system, temperature (and similar) may be set as **constraints** as well as fixed variables. That often causes over-constraint and huge condition numbers. Prefer: fix the temperature variable **or** use a temperature constraint, not both; and **do not** fix valve outlet temperatures (valves don’t set T; use pressure/delta P only).
- **DOF**: If DOF = 0, you cannot vary specs in `solve_one_point` or `convergence_analysis` until you unfix at least one variable. Use `unfix_variable_paths` in `apply_changes_and_solve` (or `unfix_variables`) first.
- **Paths**: Use full Pyomo paths with the `m.` prefix when required (e.g. `m.fs.Effect1Valve_1643611.control_volume.properties_out[0.0].temperature`). Get exact paths from `fixed_variable_summary` or `list_constraints` / `list_variables`.

Please start by reviewing my model with the tools above, then propose and apply a first batch of changes with `idaes.apply_changes_and_solve`, then iterate as needed and finally give me the summary list of changes to apply.
