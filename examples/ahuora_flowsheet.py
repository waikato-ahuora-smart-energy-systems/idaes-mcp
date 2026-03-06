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
from idaes.core.scaling.util import get_jacobian, report_scaling_factors, unscaled_variables_generator, unscaled_constraints_generator
from idaes.core.util.model_diagnostics import SVDToolbox
from generate_graph import generate_graph
from ruiz_scaling import apply_ruiz_scaling


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
    # for var in unscaled_variables_generator(m):
    #     if var.local_name == "pressure":
    #         set_scaling_factor(var,1e-5)
    #     if var.local_name == "work":
    #         set_scaling_factor(var,1e-5)
    #     if var.local_name == "flow_mol":
    #         set_scaling_factor(var,1e-4)
    #     if var.local_name == "mole_frac_comp[milk_solid]":
    #         set_scaling_factor(var,1e3)
    #     if var.local_name == "mole_frac_comp[water]":
    #         set_scaling_factor(var,1)
    #     if var.local_name == "temperature":
    #         set_scaling_factor(var,1e-2)
    #     if var.local_name == "enth_mol":
    #         set_scaling_factor(var,1e-4)
    #     # else:
    #     #     print("No scaling factor for variable " + var.name)
    
    # for cons in unscaled_constraints_generator(m):
    #     print(cons.name)
    #     if cons.local_name == "sum_mole_frac_out":
    #         set_scaling_factor(cons,1e4)
    #     elif cons.local_name == "sum_mole_frac":
    #         set_scaling_factor(cons,1e4)
    #     elif cons.local_name == "mole_frac_comp_equality[0.0,milk_solid]":
    #         set_scaling_factor(cons,1e4)
    #     elif cons.local_name == "mole_frac_comp_equality[0.0,water]":
    #         set_scaling_factor(cons,1e2)
        

    # for model in flowsheet.unit_models._unit_models.values():
    #     model.calculate_scaling_factors()

    apply_ruiz_scaling(m)
    report_scaling_factors(m)
    
    

    # print("POST SCALING:")
    # dt.report_numerical_issues()
    # dt.display_constraints_with_large_residuals()
    # dt.display_variables_at_or_outside_bounds()
    # dt.display_variables_with_extreme_jacobians()

    # svd_toolbox = dt.prepare_svd_toolbox()
    # svd_toolbox.display_underdetermined_variables_and_constraints()

    dt.report_numerical_issues()
    dt.display_near_parallel_constraints()
    
    try:
        flowsheet.solve()
    except Exception as e:
        print(e)
    # flowsheet.diagnose_problems()


    

    #dt.display_extreme_jacobian_entries()

    # generate_graph(m, graph_path="graph.html")

    # prop = flowsheet.properties_map.get(463458)


    # homotopy(m,[next(iter(prop.component))],[1437.63])

    # print("Starting MCP server at http://127.0.0.1:8005/mcp")
    # start_mcp_server(m, host="127.0.0.1", port=8005, allow_remote_hosts=True)