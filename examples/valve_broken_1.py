from pyomo.environ import ConcreteModel, SolverFactory, TransformationFactory
import pyomo.environ as pyo
from idaes.core import FlowsheetBlock
from idaes.models.unit_models import Valve
from idaes.models.properties import iapws95
import idaes.core.util.scaling as iscale
from pyomo.environ import units
from property_packages.build_package import build_package
from idaes.core.util.model_statistics import degrees_of_freedom
import math

from idaes_mcp.server import start_mcp_server

m = ConcreteModel()
m.fs = FlowsheetBlock(dynamic=False)
m.fs.properties = build_package("helmholtz",["water"],["Liq","Vap"])
m.fs.valve = Valve(property_package=m.fs.properties)
# set inlet
m.fs.valve.control_volume.properties_in[0].constrain_component(m.fs.valve.control_volume.properties_in[0].temperature, (150 + 273.15 )*units.K)
m.fs.valve.inlet.flow_mol[0].fix(10)
m.fs.valve.inlet.pressure[0].fix(201325)
m.fs.valve.outlet.pressure[0].fix(101325)
m.fs.valve.valve_opening.fix(0.5)
print("Degrees of freedom =", degrees_of_freedom(m))

# iscale.calculate_scaling_factors(m)
# m.fs.valve.initialize(outlvl=1)


# solver = pyo.SolverFactory("ipopt")
# solver.options = {"nlp_scaling_method": "user-scaling"}
# solver.solve(m, tee=True)

# print("Starting MCP server at http://127.0.0.1:8005/mcp")
# start_mcp_server(m, host="127.0.0.1", port=8005)