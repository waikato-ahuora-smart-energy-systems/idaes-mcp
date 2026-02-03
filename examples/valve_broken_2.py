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

m = ConcreteModel()
m.fs = FlowsheetBlock(dynamic=False)
m.fs.properties = build_package("helmholtz",["water"],["Liq","Vap"])
m.fs.valve = Valve(property_package=m.fs.properties)
# set inlet
m.fs.valve.control_volume.properties_in[0].constrain_component(m.fs.valve.control_volume.properties_in[0].temperature, (120 + 273.15 )*units.K)
m.fs.valve.inlet.flow_mol[0].fix(10)
m.fs.valve.inlet.pressure[0].fix(101325)


m.fs.valve.initialize(outlvl=1)
#m.fs.valve.Cv.fix(0.5)
m.fs.valve.Cv.unfix() # for some reason Cv is fixed by default.
m.fs.valve.valve_opening.fix(0.5)

m.fs.valve.control_volume.properties_out[0].constrain_component(m.fs.valve.control_volume.properties_out[0].temperature, (88 + 273.15 )*units.K)
print("Degrees of freedom =", degrees_of_freedom(m))



from idaes.core.util import DiagnosticsToolbox
dt = DiagnosticsToolbox(m)

dt.report_structural_issues()

dt.display_underconstrained_set()
dt.display_overconstrained_set()


iscale.calculate_scaling_factors(m)


solver = pyo.SolverFactory("ipopt")
solver.options = {"nlp_scaling_method": "user-scaling"}
solver.solve(m, tee=True)

print(pyo.value(m.fs.valve.Cv))
print(pyo.value(m.fs.valve.valve_opening[0]))
print(pyo.value(m.fs.valve.control_volume.properties_out[0].temperature))
print(pyo.value(m.fs.valve.control_volume.properties_out[0].pressure))

