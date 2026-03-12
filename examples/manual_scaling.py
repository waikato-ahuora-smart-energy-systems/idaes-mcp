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
        if cons.local_name.startswith("eq_phase_frac"):
            set_scaling_factor(cons,1e-2)
        if cons.local_name.startswith("eq_mole_frac_tbub"):
            set_scaling_factor(cons,1e-3)
        if cons.local_name.startswith("equilibrium_constraint"):
            set_scaling_factor(cons,1e-5)
        if cons.local_name.startswith("eq_outlet_combined_enthalpy"):
            set_scaling_factor(cons,1e-5)
        if cons.local_name.startswith("eq_power_out"):
            set_scaling_factor(cons,1e-5)
        if cons.local_name.startswith("heat_transfer_equation"):
            set_scaling_factor(cons,1e-4)
        if cons.local_name.startswith("unit_heat_balance"):
            set_scaling_factor(cons,1e-5)
        if cons.local_name.startswith("saturated_vap_pressure_eq"):
            set_scaling_factor(cons,1e-5)
        if cons.local_name.startswith("eq_steam_cooled_pressure"):
            set_scaling_factor(cons,1e-5)
        if cons.local_name.startswith("eq_mixed_pressure"):
            set_scaling_factor(cons,1e-5)
        if cons.local_name.startswith("eq_outlet_pressure"):
            set_scaling_factor(cons,1e-5)
        if cons.local_name.startswith("eq_momentum_balance"):
            set_scaling_factor(cons,1e-5) # pressure balance
        if cons.local_name.startswith("intlet_water_momentum_balance"): # tim needs to fix his naming
            set_scaling_factor(cons,1e-5)
        if cons.local_name.startswith("ratioP_calculation"):
            set_scaling_factor(cons,1e-3) # pressure ratio is calculated as a function of pressure.
        if cons.local_name.startswith("saturated_vap_enthalpy"):
            set_scaling_factor(cons,1e-5) # pressure ratio is calculated as a function of pressure.
        if cons.local_name.startswith("overall_momentum_balance"):
            set_scaling_factor(cons,1e-5) # pressure ratio is calculated as a function of pressure.
        scaling_factor = get_scaling_factor(cons)
        # if scaling_factor is not None:
        #     constraint_scaling_transform(cons, scaling_factor, overwrite=True)
        
    for model in flowsheet.unit_models._unit_models.values():
        model.calculate_scaling_factors()