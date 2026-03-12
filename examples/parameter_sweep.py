import os
import json
import io
from ahuora_builder.flowsheet_manager import FlowsheetManager
from ahuora_builder_types.flowsheet_schema import FlowsheetSchema
from idaes.core.util.model_diagnostics import DiagnosticsToolbox
from idaes_mcp.server import start_mcp_server
from ahuora_builder.methods.property_map_manipulation import update_property
from pyomo.environ import SolverFactory
from idaes.core.solvers.homotopy import homotopy
from pyomo.contrib.community_detection.community_graph import generate_model_graph
import networkx as nx
import matplotlib.pyplot as plt
from pyvis.network import Network
from networkx.algorithms import bipartite
from pyomo.core.base.constraint import ConstraintData
import pyomo.environ as pyo
from pyomo.core.base.var import ScalarVar
from math import log
from idaes.core.util.scaling import get_scaling_factor, set_scaling_factor
from idaes.core.scaling import AutoScaler
from idaes.core.scaling.util import (
    get_jacobian, report_scaling_factors, unscaled_variables_generator, 
    unscaled_constraints_generator
)
from idaes.core.util.scaling import badly_scaled_var_generator, extreme_jacobian_columns, extreme_jacobian_rows
from idaes.core.util.model_diagnostics import SVDToolbox
from generate_graph import generate_graph
from ruiz_scaling import apply_ruiz_scaling
from minimise_jacobian_condition import minimize_jacobian_condition
from idaes.core.util.scaling import constraint_autoscale_large_jac
from idaes.core.scaling.custom_scaler_base import CustomScalerBase
from watertap.core.solvers import get_solver
from amplpy import modules # so that conopt can be found.
from manual_scaling import apply_manual_scaling
from idaes.core.scaling.util import (
    get_scaling_factor,
    jacobian_cond,
)
import pandas as pd
from idaes.core.util import to_json, from_json, StoreSpec

INPUT_FILE = "json/model.json"

# Get current location (so that we can retrieve pump.json)
__location__ = os.path.realpath(os.path.join(os.getcwd(), os.path.dirname(__file__)))


def apply_idaes_auto_scaling(m):
    my_scaler = AutoScaler()
    my_scaler.scale_model(m)


def print_badly_scaled_information(m):
    print("BADLY SCALED VARIABLES:")
    for var, current_absolute_scaled in badly_scaled_var_generator(m):
        print(f"{var.local_name:<90}   {pyo.value(var):<14.4f}  {(get_scaling_factor(var) or 1) :<10.4f}   {current_absolute_scaled:<10.4f}")

    print(" EXTREME JACOBIAN COLUMNS:")
    for norm, variable in extreme_jacobian_columns(m):
        print(f"{variable.name :<90}   {pyo.value(variable):<14.4e}  {(get_scaling_factor(variable) or 1) :<10.4e}   {norm:<10.4e} ")
    
    print(" EXTREME JACOBIAN ROWS:")
    for norm, constraint in extreme_jacobian_rows(m):
        print(f"{constraint.name :<90}   {pyo.value(constraint.lb):<14.4e}  {(get_scaling_factor(constraint) or 1) :<10.4e}   {norm:<10.4e} ")

def jacobian_condition_number(m):
    return jacobian_cond(m, scaled=True)

def solve_with_increasing_tolerance(solver,m, tee=True):
    try:
        solver.options["tol"] = 1e-3
        solver.solve(m, tee=tee)
        solver.options["tol"] = 1e-4
        solver.solve(m, tee=tee)
        solver.options["tol"] = 1e-5
        solver.solve(m, tee=tee)
        solver.options["tol"] = 1e-6
        solver.solve(m, tee=tee)
        solver.options["tol"] = 1e-7
        solver.solve(m, tee=tee)
        solver.options["tol"] = 1e-8
        result = solver.solve(m, tee=tee)
        del solver.options["tol"]
        if result.solver.termination_condition == pyo.TerminationCondition.optimal:
            return "S"
        else:
            return "F"
    except Exception as e:
        print(e)
        del solver.options["tol"]
        return "E"


def solve_once(solver,m,tee=True):
    try:
        result = solver.solve(m, tee=tee)
        if result.solver.termination_condition == pyo.TerminationCondition.optimal:
            return "S"
        else:
            return "F"
    except Exception as e:
        print(e)
        return "E"


flow_mass_values = [27,28,29,30,31]

def solve_across_flow_mass(solver,flowsheet):
    standard_results = []
    jacobian_results = []


    flow_mass = flowsheet.properties_map.get(366389)
    flow_mass_var = flow_mass.corresponding_constraint[0]

    store_spec = StoreSpec.value() # store all values, not just fixed, so we init from the same point.
    prev_state = to_json(flowsheet.model, fname=None, return_dict=True, wts=store_spec)
    for value in flow_mass_values:
        from_json(flowsheet.model, sd=prev_state, wts=store_spec)
        flow_mass_var.fix(value)

        standard_results.append(solve_once(solver,flowsheet.model))
        jacobian_results.append(jacobian_condition_number(flowsheet.model))

    # reset to original state
    from_json(flowsheet.model, sd=prev_state, wts=store_spec)
    return standard_results, jacobian_results



with open(os.path.join(__location__, INPUT_FILE), 'r') as file:

    data = json.load(file)

    flowsheet_schema = FlowsheetSchema.model_validate(data)
    flowsheet = FlowsheetManager(flowsheet_schema)
    flowsheet.load()
    flowsheet.initialise()
    assert flowsheet.degrees_of_freedom() == 0, "Degrees of freedom is not 0: " + str(flowsheet.degrees_of_freedom())
    m = flowsheet.model

    dt = DiagnosticsToolbox(m)
    svd_toolbox = dt.prepare_svd_toolbox()
    print(jacobian_condition_number(flowsheet.model.fs))
    
    solver = get_solver("ipopt")
    apply_manual_scaling(flowsheet)
    solver.options["nlp_scaling_method"] = "user-scaling"
    solver.options["max_iter"] = 600
    s, j = solve_across_flow_mass(solver,flowsheet)
    print(pd.DataFrame(list(zip(flow_mass_values,s,j)),columns=["flow_mass","success","jacobian"]))




#Parameter Sweep results with normal solver:

# WARNING: model contains export suffix 'scaling_factor' that contains 5
# component keys that are not exported as part of the NL file.  Skipping.
#   success      jacobian
# 0       E  3.761699e+13
# 1       F  1.370097e+13
# 2       S  3.844978e+13
# 3       F  1.521089e+13
# 4       F  1.661002e+13