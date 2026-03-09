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

from amplpy import modules # so that conopt can be found.
import uno_solver


INPUT_FILE = "json/model.json"

# Get current location (so that we can retrieve pump.json)
__location__ = os.path.realpath(os.path.join(os.getcwd(), os.path.dirname(__file__)))


with open(os.path.join(__location__, INPUT_FILE), 'r') as file:

    data = json.load(file)

    flowsheet_schema = FlowsheetSchema.model_validate(data)
    flowsheet = FlowsheetManager(flowsheet_schema)
    flowsheet.load()
    flowsheet.initialise()
    assert flowsheet.degrees_of_freedom() == 0, "Degrees of freedom is not 0: " + str(flowsheet.degrees_of_freedom())
    flowsheet.report_statistics()

    m = flowsheet.model

    dt = DiagnosticsToolbox(m)
    dt.report_numerical_issues()
    #dt.display_constraints_with_large_residuals()
    #dt.display_variables_at_or_outside_bounds()
    #dt.display_variables_with_extreme_jacobians()

    # SCALE MODEL
    # my_scaler = AutoScaler()
    # my_scaler.scale_model(m)
    # dt.display_variables_with_extreme_jacobians()
    csb = CustomScalerBase()
    for var in unscaled_variables_generator(m):
        if var.local_name == "pressure":
            set_scaling_factor(var,1e-5)
        if var.local_name == "deltaP[0.0]":
            set_scaling_factor(var,1e-4)
        if var.local_name == "deltaP_inverted[0.0]":
            set_scaling_factor(var,1e-2)
        if var.local_name == "work":
            set_scaling_factor(var,1e-5)
        if var.local_name == "flow_mol":
            set_scaling_factor(var,1e-3)
        if var.local_name == "mole_frac_comp[milk_solid]":
            set_scaling_factor(var,1e3)
        if var.local_name == "mole_frac_comp[water]":
            set_scaling_factor(var,1)
        if var.local_name == "temperature":
            set_scaling_factor(var,1e-2)
        if var.local_name == "enth_mol":
            set_scaling_factor(var,1e-4)
        if var.local_name == "heat[0.0]":
            set_scaling_factor(var,1e-6)
        if var.local_name == "heat_duty_inverted[0.0]":
            set_scaling_factor(var,1e-5)
        if var.local_name == "phase_frac[Liq]":
            set_scaling_factor(var,1e1)
        if var.local_name == "phase_frac[Vap]":
            set_scaling_factor(var,1e2)
        if var.local_name == "work[0.0]":
            set_scaling_factor(var,1e-4)
        if var.local_name == "power":
            set_scaling_factor(var,1e-4)
    #     # else:
        #     print("No scaling factor for variable " + var.name)
    
    for cons in unscaled_constraints_generator(m):
        if cons.local_name == "overall_energy_balance[0.0]":
            set_scaling_factor(cons,1e-8)
        if cons.local_name == "enthalpy_balances[0.0]":
            set_scaling_factor(cons,1e-7)
        if cons.local_name.startswith("enthalpy_mixing_equations"):
            set_scaling_factor(cons,1e-7)
        if cons.local_name.startswith("molar_enthalpy_splitting_eqn"):
            set_scaling_factor(cons,1e-7)
        if cons.local_name.startswith("heat_duty"):
            set_scaling_factor(cons,1e-7)
        if cons.local_name.startswith("ratioP"):
            set_scaling_factor(cons,1e-5)
        if cons.local_name.startswith("ratioP_calculation"):
            set_scaling_factor(cons,1)
        if cons.local_name.startswith("pressure_balance"):
            set_scaling_factor(cons,1e-5)
        if cons.local_name.startswith("equality_constraint"):
            set_scaling_factor(cons,1e-2)
        if cons.local_name.startswith("pressure_equality"):
            set_scaling_factor(cons,1e-4)
        if cons.local_name.startswith("eq_temperature_bubble"):
            set_scaling_factor(cons,1e-5)
        if cons.local_name.startswith("eq_outlet_enth_mol"):
            set_scaling_factor(cons,1e-4)
        if cons.local_name.startswith("enth_mol_equality"):
            set_scaling_factor(cons,1e-4)
        if cons.local_name.startswith("flow_mol_equality"):
            set_scaling_factor(cons,1e-3)
        if cons.local_name.startswith("component_flow_balances"):
            set_scaling_factor(cons,1e-3)
        if cons.local_name.startswith("total_flow_balance"):
            set_scaling_factor(cons,1e-3)
        if cons.local_name.startswith("deltaP_inverted_constraint"):
            set_scaling_factor(cons,1e-4)

    for model in flowsheet.unit_models._unit_models.values():
        model.calculate_scaling_factors()

    #apply_ruiz_scaling(m)
    
    #report_scaling_factors(m, descend_into=True)

    # D = minimize_jacobian_condition(m)

    # print("Optimal scaling matrix:")
    # print(D)
    #constraint_autoscale_large_jac(m)
    print("BADLY SCALED VARIABLES:")
    for var, current_absolute_scaled in badly_scaled_var_generator(m):
        print(f"{var.local_name:<90}   {pyo.value(var):<14.4f}  {(get_scaling_factor(var) or 1) :<10.4f}   {current_absolute_scaled:<10.4f}")

    print(" EXTREME JACOBIAN COLUMNS:")
    for norm, variable in extreme_jacobian_columns(m):
        print(f"{variable.name :<90}   {pyo.value(variable):<14.4e}  {(get_scaling_factor(variable) or 1) :<10.4e}   {norm:<10.4e} ")
    
    print(" EXTREME JACOBIAN ROWS:")
    for norm, constraint in extreme_jacobian_rows(m):
        print(f"{constraint.name :<90}   {pyo.value(constraint):<14.4e}  {(get_scaling_factor(constraint) or 1) :<10.4e}   {norm:<10.4e} ")

    
    # print("POST SCALING:")
    # dt.report_numerical_issues()
    # dt.display_constraints_with_large_residuals()
    # dt.display_variables_at_or_outside_bounds()
    # dt.display_variables_with_extreme_jacobians()

    # svd_toolbox = dt.prepare_svd_toolbox()
    # svd_toolbox.display_underdetermined_variables_and_constraints()

    # dt.report_numerical_issues()
    # dt.display_near_parallel_constraints()

    # dt.display_constraints_with_extreme_jacobians()

    m.obj = pyo.Objective(expr=0)

    
    import os

    #IPOPT options
    # solver = pyo.SolverFactory("ipopt")
    # solver.options["tol"] = 1e-1
    # solver.options["linear_solver"] = "ma57"
    # solver.options["nlp_scaling_method"] = "gradient-based"

    # UNO options
    solver = pyo.SolverFactory("asl", solver="/home/bd65/Downloads/uno/bin/uno_ampl")
    solver.options["preset"] = "filtersqp"
    # solver.options["QP_solver"] = "BQPD"


    
    results = solver.solve(m, tee=True)

    # flowsheet.diagnose_problems()


    

    #dt.display_extreme_jacobian_entries()

    # generate_graph(m, graph_path="graph.html")

    # prop = flowsheet.properties_map.get(463458)


    # homotopy(m,[next(iter(prop.component))],[1437.63])

    # print("Starting MCP server at http://127.0.0.1:8005/mcp")
    # start_mcp_server(m, host="127.0.0.1", port=8005, allow_remote_hosts=True)