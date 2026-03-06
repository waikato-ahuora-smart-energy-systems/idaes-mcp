from pyomo.contrib.community_detection.community_graph import generate_model_graph
from pyvis.network import Network
from pyomo.core.base.constraint import ConstraintData
import pyomo.environ as pyo
from math import log
from idaes.core.scaling.util import get_jacobian
from idaes.core.util.scaling import get_scaling_factor

def decompose_jacobian(block : pyo.Block):
    jacobian, nlp = get_jacobian(block)

    # dictionay [ID of of variable using python id(ConstraintData object), index of constraint in nlp.clist]
    cmap : dict[int,int] = {
        id(constraint): index for index,constraint in enumerate(nlp.clist)
    }
    # dictionay [ID of of variable using python id(ScalarVar), index of variable in nlp.vlist]
    vmap : dict[int, int] = {
        id(variable): index for index,variable in enumerate(nlp.vlist)
    }
    return jacobian,nlp, cmap, vmap

def generate_graph(block : pyo.Block, show_fixed: bool=False, graph_path="graph.html"):

    graph, number_component_map, constraint_variable_map = generate_model_graph(block,"bipartite")

    net = Network(notebook=True, cdn_resources="remote")
    
    jacobian, nlp, cmap, vmap = decompose_jacobian(block)


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

    net.show(graph_path)