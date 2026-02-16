# harden_flowsheet.py
from pyomo.environ import Var, Constraint
import idaes.core.util.scaling as iscale


def _tighten_bounds(v, lb=None, ub=None, push_value_inside=True):
    """Safely tighten bounds without widening existing ones."""
    if lb is not None:
        if v.lb is None or lb > v.lb:
            v.setlb(lb)
    if ub is not None:
        if v.ub is None or ub < v.ub:
            v.setub(ub)

    if push_value_inside and v.value is not None:
        # Only nudge UNFIXED vars; changing fixed specs silently is dangerous
        if not v.fixed:
            if v.lb is not None and v.value < v.lb:
                v.set_value(v.lb)
            if v.ub is not None and v.value > v.ub:
                v.set_value(v.ub)


def harden_bounds(m,
                  eps_flow=1e-8,
                  eps_x=1e-12,
                  p_bounds=(1e3, 3e7),     # Pa
                  T_bounds=(250.0, 650.0) # K
                  ):
    """
    Bounds that prevent:
      - division by zero (flow_mol denominators, etc.)
      - illegal VLE / correlation domains
      - mole-fraction-like internals being unbounded above
    """
    p_min, p_max = p_bounds
    T_min, T_max = T_bounds

    for v in m.component_data_objects(Var, descend_into=True):
        name = v.name

        # ---- (A) Mole-fraction-like "tbub" helper vars: enforce [eps, 1] ----
        if "._mole_frac_tbub" in name:
            _tighten_bounds(v, lb=eps_x, ub=1.0, push_value_inside=True)

        # If your property package has other mole_frac vars that are unbounded,
        # uncomment this (more aggressive):
        # if ".mole_frac" in name or "mole_frac_" in name:
        #     _tighten_bounds(v, lb=eps_x, ub=1.0, push_value_inside=True)

        # ---- (B) Total flow lower bound: stop 1/flow blowing up ----
        # This is conservative; if you truly need zero-flow streams,
        # apply this only to the specific streams appearing in denominators.
        if name.endswith(".flow_mol") or ".flow_mol[" in name:
            _tighten_bounds(v, lb=eps_flow, push_value_inside=True)

        # ---- (C) Temperature/pressure bounds: keep property calls in-domain ----
        if name.endswith(".temperature") or ".temperature[" in name:
            _tighten_bounds(v, lb=T_min, ub=T_max, push_value_inside=True)

        if name.endswith(".pressure") or ".pressure[" in name:
            _tighten_bounds(v, lb=p_min, ub=p_max, push_value_inside=True)

        # ---- (D) Fixed-at-bound "loss" vars: move slightly off the bound ----
        # (This avoids kinks/degeneracy from fixed vars sitting exactly at lb.)
        if name.endswith(".heat_loss[0.0]") or name.endswith(".pressure_loss[0.0]") \
           or ".heat_loss[" in name or ".pressure_loss[" in name:
            if v.fixed and (v.value is not None) and abs(v.value) == 0 and (v.lb is not None) and abs(v.lb) == 0:
                # Keep fixed, but not at the bound
                v.set_value(1e-10)


def harden_scaling(m):
    """
    Set practical scaling factors for the common variable types.
    Then transform scaling onto key constraints.
    Finally let IDAES fill in any remaining scaling via calculate_scaling_factors().
    """
    # ---- (1) Variable scaling by name pattern ----
    for v in m.component_data_objects(Var, descend_into=True):
        n = v.name

        # Skip if already scaled
        if iscale.get_scaling_factor(v, default=None) is not None:
            continue

        # Pressure (Pa): typical 1e5–1e6 -> scale ~1e-5
        if n.endswith(".pressure") or ".pressure[" in n:
            iscale.set_scaling_factor(v, 1e-5)
            continue

        # Temperature (K): typical 300 -> scale ~1e-2
        if n.endswith(".temperature") or ".temperature[" in n:
            iscale.set_scaling_factor(v, 1e-2)
            continue

        # Total molar flow: pick something that makes typical flows O(1–100)
        if n.endswith(".flow_mol") or ".flow_mol[" in n:
            iscale.set_scaling_factor(v, 1e-1)
            continue

        # Enthalpy molar (often J/mol): typical 1e4–1e5 -> scale 1e-4
        if n.endswith(".enth_mol") or ".enth_mol[" in n:
            iscale.set_scaling_factor(v, 1e-4)
            continue

        # Heat duty / work / power (often W): typical 1e5–1e7 -> scale 1e-6
        if ("heat_duty" in n) or ("work" in n) or ("power" in n):
            iscale.set_scaling_factor(v, 1e-6)
            continue

        # Dimensionless fractions
        if ("mole_frac" in n) or ("phase_frac" in n) or ("vapor_frac" in n) or ("vap_frac" in n):
            iscale.set_scaling_factor(v, 1.0)
            continue

        # "ratio" vars (should be dimensionless once you fix units)
        if "flow_ratio" in n or n.endswith(".ratio") or ".ratio[" in n:
            iscale.set_scaling_factor(v, 1.0)
            continue

    # ---- (2) Constraint scaling transforms by pattern ----
    for c in m.component_data_objects(Constraint, active=True, descend_into=True):
        n = c.name

        # Skip if already transformed
        if iscale.get_scaling_factor(c, default=None) is not None:
            continue

        # Pressure equalities: residual in Pa -> scale ~1e-5
        if "pressure_equality" in n or ("pressure" in n and "equality" in n):
            iscale.constraint_scaling_transform(c, 1e-5)
            continue

        # Temperature equalities: residual in K -> scale ~1e-2
        if "temperature_equality" in n or ("temperature" in n and "equality" in n):
            iscale.constraint_scaling_transform(c, 1e-2)
            continue

        # Material balances: scale to typical flow magnitudes
        if "material_balances" in n:
            iscale.constraint_scaling_transform(c, 1e-1)
            continue

        # Enthalpy balances: often large energy terms
        if "enthalpy_balances" in n:
            iscale.constraint_scaling_transform(c, 1e-6)
            continue

    # ---- (3) Let IDAES compute remaining scaling factors ----
    # Many IDAES unit models/property packages provide default scaling logic.
    iscale.calculate_scaling_factors(m)


def harden_targeted_problem_constraints(m):
    """
    Optional: explicitly scale the specific constraints that showed near-parallel Jacobian rows.
    Safe to call even if names differ; it will just skip missing components.
    """
    name_to_sf = {
        # TVR Split (pressure/temperature equalities)
        "fs.TVR Split_1646163.pressure_equality_eqn[0.0,outlet_1]": 1e-5,
        "fs.TVR Split_1646163.pressure_equality_eqn[0.0,outlet_2]": 1e-5,
        "fs.TVR Split_1646163.temperature_equality_eqn[0.0,outlet_1]": 1e-2,
        "fs.TVR Split_1646163.temperature_equality_eqn[0.0,outlet_2]": 1e-2,

        # Momentum transfer unit (material vs enthalpy balance)
        "fs.Momentum Transfer Pressure Increase_1646100.control_volume.material_balances[0.0,water]": 1e-1,
        "fs.Momentum Transfer Pressure Increase_1646100.control_volume.enthalpy_balances[0.0]": 1e-6,

        # Control constraint vs vapour fraction constraint
        "fs.control_constraint_390161[0]": 1.0,
        "fs.Cooler2_1647876.control_volume.properties_out[0.0].constraints.vapor_frac": 1.0,
    }

    for cname, sf in name_to_sf.items():
        comp = m.find_component(cname)
        if comp is None:
            continue
        # Only Constraints can be transformed this way
        if isinstance(comp, Constraint):
            iscale.constraint_scaling_transform(comp, sf)


def harden_model(m,
                 eps_flow=1e-8,
                 eps_x=1e-12,
                 p_bounds=(1e3, 3e7),
                 T_bounds=(250.0, 650.0),
                 do_targeted=True):
    """
    One-call hardening.
    Call after building the flowsheet (and arcs expanded), before initialise/solve.
    """
    harden_bounds(m, eps_flow=eps_flow, eps_x=eps_x, p_bounds=p_bounds, T_bounds=T_bounds)
    harden_scaling(m)
    if do_targeted:
        harden_targeted_problem_constraints(m)
