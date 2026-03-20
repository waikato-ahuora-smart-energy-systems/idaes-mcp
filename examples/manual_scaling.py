import os
import json
import io
from ahuora_builder.flowsheet_manager import FlowsheetManager
from ahuora_builder_types.flowsheet_schema import FlowsheetSchema
from idaes.core.util.model_diagnostics import DiagnosticsToolbox
from idaes_mcp.server import start_mcp_server
from ahuora_builder.methods.property_map_manipulation import update_property
from pyomo.environ import SolverFactory, Var, Expression
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
from idaes.core.util.scaling import get_scaling_factor, set_scaling_factor, constraint_scaling_transform
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
from idaes.core.util.scaling import calculate_scaling_factors

def apply_manual_scaling(flowsheet):
    m = flowsheet.model

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
            set_scaling_factor(var,1e-2)
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
        if var.local_name.startswith("overall_heat_transfer_coefficient"):
            set_scaling_factor(var,1e-4)
        if var.local_name.startswith("area"):
            set_scaling_factor(var,1e-2)
    
    for var in m.component_data_objects(Expression, descend_into=True):
        if var.local_name.startswith("enth_mol_phase"):
            set_scaling_factor(var,1e-4)

    calculate_scaling_factors(m)