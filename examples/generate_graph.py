from pyomo.contrib.community_detection.community_graph import generate_model_graph
from pyvis.network import Network
from pyomo.core.base.constraint import ConstraintData
import pyomo.environ as pyo
from math import log
from idaes.core.util.scaling import get_scaling_factor

def generate_graph(block : pyo.Block, show_fixed: bool=False, graph_path="graph.html"):

    graph, number_component_map, constraint_variable_map = generate_model_graph(block,"bipartite")

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
            size = log((infeasibility*scaling_factor*10**15)+1)+1
            net.add_node(node, color='red', title=str(component) + f" ({'{:.2e}'.format(infeasibility)}) (SF: {'{:.2e}'.format(scaling_factor)})", size=size)
        else:
            if not component.is_fixed() or show_fixed:
                net.add_node(node, color=( 'lightblue' if component.is_fixed() else 'blue'),title=str(component) + f" ({'{:.2e}'.format(current_value)}) (SF: {'{:.2e}'.format(scaling_factor)})", size=10)
    for edge in graph.edges():
        # only add edge if both nodes are in the graph (since pyvis will throw an error otherwise)
        # this allows us to only visualise part of the graph if we want to.
        if edge[0] in net.node_ids and edge[1] in net.node_ids:
            net.add_edge(edge[0], edge[1],color="gray")

    net.show(graph_path)