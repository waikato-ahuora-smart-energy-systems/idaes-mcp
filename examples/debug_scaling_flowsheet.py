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
    get_jacobian,
    get_scaling_factor,
    jacobian_cond,
)
import pandas as pd
from idaes.core.util import to_json, from_json, StoreSpec
from idaes.core.util.model_diagnostics import DegeneracyHunter2

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



def fix_flow_mass(flowsheet,value):
    # We are specifically testing different values of flow mass, so this is all we care about for now.
    flow_mass = flowsheet.properties_map.get(366389)
    flow_mass_var = flow_mass.corresponding_constraint[0]
    flow_mass_var.fix(value)




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
    dh = DegeneracyHunter2(m)

    fix_flow_mass(flowsheet,29)
    # SCALE MODEL
    
    # dt.display_variables_with_extreme_jacobians()
    # apply_idaes_auto_scaling(m)
    apply_manual_scaling(flowsheet)
    
    svd_toolbox.display_underdetermined_variables_and_constraints()

    dh.report_irreducible_degenerate_sets(tee=True)
    # dt.report_numerical_issues()
    # dt.display_constraints_with_extreme_jacobians()

    #m.obj = pyo.Objective(expr=0)
    solver = pyo.SolverFactory("ipopt")
    solver.options["max_iter"] = 300
    solver.solve(m, tee=True)


    # UNO Ipopt options
    # solver = pyo.SolverFactory("asl", solver="/home/bd65/Downloads/uno/bin/uno_ampl")
    # solver.options["preset"] = "ipopt"
    # solver.options["linear_solver"] = "mumps"
    # UNO options
    # solver = pyo.SolverFactory("asl", solver="/home/bd65/Downloads/uno/bin/uno_ampl")
    # solver.options["preset"] = "filtersqp"
    # # solver.options["QP_solver"] = "BQPD"
    # results = solver.solve(m, tee=True)


    #dt.display_extreme_jacobian_entries()

    # generate_graph(m, graph_path="graph.html")


    # print("Starting MCP server at http://127.0.0.1:8005/mcp")
    # start_mcp_server(m, host="127.0.0.1", port=8005, allow_remote_hosts=True)