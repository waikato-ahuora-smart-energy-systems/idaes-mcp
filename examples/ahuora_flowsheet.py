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
from idaes.core.util.scaling import get_scaling_factor
from idaes.core.scaling import AutoScaler
from idaes.core.scaling.util import get_jacobian
from idaes.core.util.model_diagnostics import SVDToolbox

INPUT_FILE = "json/evaporator_dsi.json"

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
    dt.display_constraints_with_large_residuals()
    dt.display_variables_at_or_outside_bounds()
    dt.display_variables_with_extreme_jacobians()

    # SCALE MODEL
    # my_scaler = AutoScaler()
    # my_scaler.scale_model(m)
    # dt.display_variables_with_extreme_jacobians()

    # print("POST SCALING:")
    # dt.report_numerical_issues()
    # dt.display_constraints_with_large_residuals()
    # dt.display_variables_at_or_outside_bounds()
    # dt.display_variables_with_extreme_jacobians()


    try:
        flowsheet.solve()
    except Exception as e:
        print(e)
    # flowsheet.diagnose_problems()

    flowsheet.properties_map.items()

    svd_toolbox = dt.prepare_svd_toolbox()
    svd_toolbox.display_underdetermined_variables_and_constraints()

    dt.display_extreme_jacobian_entries()

    jacobian, nlp = get_jacobian(m)
    # dictionay [ID of of variable using python id(ConstraintData object), index of constraint in nlp.clist]
    cmap : dict[int,int] = {
        id(constraint): index for index,constraint in enumerate(nlp.clist)
    }
    # dictionay [ID of of variable using python id(ScalarVar), index of variable in nlp.vlist]
    vmap : dict[int, int] = {
        id(variable): index for index,variable in enumerate(nlp.vlist)
    }


    

    


    graph, number_component_map, constraint_variable_map = generate_model_graph(m,"bipartite")

    net = Network(notebook=True, cdn_resources="remote")

    # this is a bipartite graph, so we can color the two sets of nodes differently
    for node in graph.nodes():
        component = number_component_map[node]
        current_value :float = pyo.value(component)
        scaling_factor = get_scaling_factor(component)
        if scaling_factor is None:
            scaling_factor = 1
        if isinstance(component, ConstraintData):
            target_value :float = pyo.value(component.upper)
            infeasibility = abs(current_value - target_value)
            size = log((infeasibility*scaling_factor*10**14)+1)+1
            net.add_node(node, color='red', title=str(component) + f" ({'{:.2e}'.format(infeasibility)}) (SF: {'{:.2e}'.format(scaling_factor)})", size=size)
        else:
            if not component.is_fixed():
                net.add_node(node, color=( 'lightblue' if component.is_fixed() else 'blue'),title=str(component) + f" ({'{:.2e}'.format(current_value)}) (SF: {'{:.2e}'.format(scaling_factor)})", size=10)
    for edge in graph.edges():
        # only add edge if both nodes are in the graph (since pyvis will throw an error otherwise)
        # this allows us to only visualise part of the graph if we want to.
        if edge[0] in net.node_ids and edge[1] in net.node_ids:
            # find the variable and constraint associated with this edge
            edge0 = number_component_map[edge[0]]
            edge1 = number_component_map[edge[1]]
            if isinstance(edge0, ConstraintData):
                # as this is a bipartite graph, we know that the other edge must be a variable
                variable = edge1
                constraint = edge0
            else:
                variable = edge0
                constraint = edge1
            # get the indexes of the variable and constraint in the jacobian, and get the jacobian value
            jacobian_value = jacobian[cmap[id(constraint)], vmap[id(variable)]]
            # weight the edge by the log of the jacobian value
            net.add_edge(edge[0], edge[1], value=(abs(jacobian_value)+0.000001), title='{:.2e}'.format(jacobian_value),
                         color=("#333333" if jacobian_value != 0 else "#440099"))


    net.show("graph.html")
    # prop = flowsheet.properties_map.get(463458)


    # homotopy(m,[next(iter(prop.component))],[1437.63])

    # print("Starting MCP server at http://127.0.0.1:8005/mcp")
    # start_mcp_server(m, host="127.0.0.1", port=8005, allow_remote_hosts=True)