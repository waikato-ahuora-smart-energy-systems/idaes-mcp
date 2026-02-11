# -*- coding: utf-8 -*-
"""
Bert trying to figure out IDAES :)
"""
#Importing required pyomo and idaes components
from pyomo.environ import (
    Constraint,
    Var,
    ConcreteModel,
    Expression,
    Objective,
    SolverFactory,
    TransformationFactory,
    value,
    units,
)
from pyomo.network import Arc, SequentialDecomposition

from idaes.core import FlowsheetBlock

from idaes.models.unit_models import (
    HeatExchanger,
    Heater,
    PressureChanger,
    Compressor
)

from idaes.models.properties.general_helmholtz import (
    HelmholtzParameterBlock,
    PhaseType,
    StateVars,
    HelmholtzParameterBlockData,
    AmountBasis
)

from idaes.models.unit_models.heat_exchanger import ( HX0DInitializer, delta_temperature_amtd_callback)

from idaes.core.util.model_statistics import (degrees_of_freedom, number_unfixed_variables,report_statistics,unfixed_variables_set)

# Import idaes logger to set output levels
import idaes.logger as idaeslog

# CoolProp is used to figure out the saturation pressure of water at the various temperatures
import CoolProp.CoolProp as CP

from idaes_mcp.server import start_mcp_server

#Constructing the Flowsheet
m = ConcreteModel()
m.fs = FlowsheetBlock(dynamic=False)

# add the property packages to the flowsheet
fluidR = "propane"
m.fs.helmholtz_water = HelmholtzParameterBlock(
  pure_component=fluidR,
  phase_presentation=PhaseType.MIX,
  state_vars=StateVars.PH,
  amount_basis=AmountBasis.MASS
)


#Adding Unit Models

#Heater
m.fs.heater = Heater(
    property_package=m.fs.helmholtz_water,
    has_pressure_change=False,
    #has_phase_equilibrium=True, # No phase equilibrium, it only has one phase as it's modelled with Helmholtz MIX
)

#Pressure Changer
m.fs.pressureChanger = PressureChanger(
    property_package=m.fs.helmholtz_water,
    compressor=False, # False = Expander
)

#Compressor
m.fs.compressor = Compressor(
    property_package=m.fs.helmholtz_water,
)

#Heat Exchanger
# m.fs.cooler = HeatExchanger(
#     delta_temperature_callback=delta_temperature_amtd_callback,
#     hot_side_name="shell",
#     cold_side_name="tube",
#     shell={"property_package": m.fs.helmholtz_water},
#     tube={"property_package": m.fs.helmholtz_water},
# )
# Cooler
m.fs.cooler = Heater(
    property_package=m.fs.helmholtz_water,
    has_pressure_change=False,
)


#Adding Arcs
#Heater to Compressor
m.fs.heater_to_compressor = Arc(
    source=m.fs.heater.outlet,
    destination=m.fs.compressor.inlet,
)
#Compressor to Cooler
m.fs.compressor_to_cooler = Arc(
    source=m.fs.compressor.outlet,
    destination=m.fs.cooler.inlet,
)
#Cooler to Pressure Changer
m.fs.heatExchanger_to_pressureChanger = Arc(
    source=m.fs.cooler.outlet,
    destination=m.fs.pressureChanger.inlet,
)
#Pressure Changer to Heater
m.fs.pressureChanger_to_heater = Arc(
    source=m.fs.pressureChanger.outlet,
    destination=m.fs.heater.inlet,
)
TransformationFactory("network.expand_arcs").apply_to(m)
#Print out the number of degrees of freedom

print("Before Specifying Constraints")
#print(f"Degrees of Freedom: {degrees_of_freedom(m)}")
#print(f"Number Unfixed Variables: {number_unfixed_variables(m)}")
report_statistics(m)

#


#Specify constraints
m.fs.compressor.outlet.pressure.fix(201325 * units.Pa) # compressor makes it go to a higher pressure, which will heat it up
m.fs.pressureChanger.outlet.pressure.fix(101325 * units.Pa) # pressure changer makes it go to a lower pressure

# the heater has one degree of freedom, the heat duty. Instead of specifying that, we will specify the outlet temperature and inlet temperature
m.fs.cooler.outlet.enth_mass.fix(m.fs.helmholtz_water.htpx(p=201325 * units.Pa,x=0,amount_basis=AmountBasis.MASS,with_units=True))
m.fs.heater.heat_duty.fix(50000 * units.kW)

#efficiencies
m.fs.compressor.efficiency_isentropic.fix(0.9)
#m.fs.pressureChanger.efficiency_isentropic.fix(0.9)

#Equality constraints between two ports method


# the enthalpy will be the same for the cooler (i.e enthalpy of heater inlet = enthalpy of cooler outlet and vice versa)
## the same is true for the cooler
#m.fs.cooler.inlet.enth_mass.fix(m.fs.helmholtz_water.htpx(T=(0+ 273.15)* units.K,x=1,amount_basis=AmountBasis.MASS,with_units=True))
#m.fs.cooler.outlet.enth_mass.fix(m.fs.helmholtz_water.htpx(T=(75+ 273.15) * units.K,x=0,amount_basis=AmountBasis.MASS,with_units=True))

print("After Specifying Constraints")
report_statistics(m)


# Initialize the model
#initializer = HX0DInitializer()
#initializer.initialize(m.fs.heatExchanger)

# To initialize the model we need to specify all degreees of freedom (including ones that we aren't so worried about, like flow rates)



#m.fs.heater.inlet.flow_mass.fix(1)
#m.fs.heater.outlet.flow_mass.fix(1)
#m.fs.pressureChanger.inlet.flow_mass.fix(1)
#m.fs.pressureChanger.outlet.flow_mass.fix(1)
#m.fs.compressor.inlet.flow_mass.fix(1)
#m.fs.compressor.outlet.flow_mass.fix(1)
#m.fs.cooler.inlet.flow_mass.fix(1)
#m.fs.cooler.outlet.flow_mass.fix(1)
report_statistics(m)


# The following don't change the number of degrees of freedom
# m.fs.heater.inlet.pressure.fix(saturation_pressure_0) 
# m.fs.heater.outlet.pressure.fix(saturation_pressure_0)
# m.fs.cooler.inlet.pressure.fix(saturation_pressure_75)
# m.fs.pressureChanger.inlet.enth_mass.fix(m.fs.helmholtz_water.htpx(T=(0+ 273.15)* units.K,x=0,amount_basis=AmountBasis.MASS,with_units=True))
# m.fs.pressureChanger.outlet.enth_mass.fix(m.fs.helmholtz_water.htpx(T=(75+ 273.15) * units.K,x=1,amount_basis=AmountBasis.MASS,with_units=True))
# m.fs.compressor.inlet.enth_mass.fix(m.fs.helmholtz_water.htpx(T=(0+ 273.15)* units.K,x=0,amount_basis=AmountBasis.MASS,with_units=True))
# m.fs.compressor.outlet.enth_mass.fix(m.fs.helmholtz_water.htpx(T=(75+ 273.15) * units.K,x=1,amount_basis=AmountBasis.MASS,with_units=True))
# m.fs.compressor.inlet.pressure.fix(saturation_pressure_0 * units.Pa) 
# m.fs.pressureChanger.inlet.pressure.fix(saturation_pressure_75 * units.Pa)


seq = SequentialDecomposition()
seq.options.select_tear_method = "heuristic"
seq.options.tear_method = "Wegstein"
seq.options.iterLim = 3

# Using the SD tool
G = seq.create_graph(m)
heuristic_tear_set = seq.tear_set_arcs(G, method="heuristic")
order = seq.calculation_order(G)

print("The tear set is")
for o in heuristic_tear_set:
    print(o.name)
print("The calculation order is")
for o in order:
    print(o[0].name)

#Tear guesses
tear_guesses = {
    "flow_mass": {0:1},
    "enth_mass": {0: value(m.fs.helmholtz_water.htpx(p=101325 * units.Pa,x=1,amount_basis=AmountBasis.MASS,with_units=True))},
    "pressure": {0: 101325 },
}

# Pass the tear_guess to the SD tool
seq.set_guesses_for(m.fs.compressor.inlet, tear_guesses)

report_statistics(m)

# #Unit initialisation function
# def function(unit):
#     unit.initialize(outlvl=idaeslog.INFO)

# try:
#     seq.run(m, function)
#     #Create solver object
#     solver = SolverFactory("ipopt")
#     solver.options = {"nlp_scaling_method": "user-scaling"}
#     solver.solve(m, tee=True)
# except:
#     print("Error: The model has an error")






