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
from idaes.core.util.model_statistics import degrees_of_freedom

# I'm trying to make a problem that is deliberately badly scaled,
# to test if scaling actually helps.

m = pyo.ConcreteModel()
m.f_in = pyo.Var()
m.f_out = pyo.Var()

m.f_out.setlb(0)
m.flow_balance = pyo.Constraint(expr= m.f_in== m.f_out**6 *1000000  + 1)
m.cp = pyo.Var()
m.h = pyo.Var()

m.t = pyo.Var()
m.t_constraint = pyo.Constraint(expr=m.t * m.cp * m.f_out == m.h )
m.pressure = pyo.Var()
m.pressure_constraint = pyo.Constraint(expr=m.pressure == 5000)

m.cp_constraint = pyo.Constraint(expr=m.cp == 500000 * m.pressure * m.pressure)
m.t.fix(300000)
m.f_in_constraint = pyo.Constraint(expr=m.f_in == 10)

m.obj = pyo.Objective(expr=0)


print("degrees of freedom: ", degrees_of_freedom(m))

solver = pyo.SolverFactory("ipopt")
# solver = pyo.SolverFactory("asl", solver="/home/bd65/Downloads/uno/bin/uno_ampl")
# solver.options["preset"] = "filtersqp"

results = solver.solve(m, tee=True)

generate_graph(m, graph_path="bad_scaling_example_before.html")

dt = DiagnosticsToolbox(m)
dt.report_numerical_issues()
dt.display_constraints_with_large_residuals()
dt.display_variables_at_or_outside_bounds()


# dt.compute_infeasibility_explanation()


set_scaling_factor(m.f_out,1e+5)
set_scaling_factor(m.pressure,1e-3)
set_scaling_factor(m.t,1e-5)

set_scaling_factor(m.cp, 1e15)

print("WITH FIXED SCALING:")

generate_graph(m, graph_path="bad_scaling_example_fixed_pre_solve.html")

dt.report_numerical_issues()


results = solver.solve(m, tee=True)

generate_graph(m, graph_path="bad_scaling_example_fixed.html")


