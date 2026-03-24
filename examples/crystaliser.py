#################################################################################
# WaterTAP Copyright (c) 2020-2026, The Regents of the University of California,
# through Lawrence Berkeley National Laboratory, Oak Ridge National Laboratory,
# National Laboratory of the Rockies, and National Energy Technology
# Laboratory (subject to receipt of any required approvals from the U.S. Dept.
# of Energy). All rights reserved.
#
# Please see the files COPYRIGHT.md and LICENSE.md for full copyright and license
# information, respectively. These files are also available online at the URL
# "https://github.com/watertap-org/watertap/"
#################################################################################
from pyomo.environ import (
    ConcreteModel,
    TerminationCondition,
)
import pyomo.environ as pyo
from pyomo.util.check_units import assert_units_consistent

from idaes.core import FlowsheetBlock
from idaes.core.util.model_statistics import degrees_of_freedom

import idaes.core.util.scaling as iscale
import idaes.logger as idaeslog
from watertap.core.solvers import get_solver
from idaes.core import UnitModelCostingBlock

from watertap.property_models.unit_specific import cryst_prop_pack as props
from watertap.unit_models.crystallizer import Crystallization
from watertap.costing import WaterTAPCosting, CrystallizerCostType
from idaes.core.util import DiagnosticsToolbox
from ahuora_property_packages.build_package import build_package
from watertap.property_models.NaCl_prop_pack import NaClParameterBlock

# From http://github.com/watertap-org/watertap/blob/8cce4013f9f9b137f8aa995da6e59e258319e8b7/watertap/flowsheets/crystallization/sim_simple_crystallizer.py#L4

def main():
    m = ConcreteModel()
    m.fs = FlowsheetBlock(dynamic=False)
    # attach property package
    m.fs.properties = props.NaClParameterBlock()
    # build the unit model
    m.fs.c1 = Crystallization(property_package=m.fs.properties)

    # now specify the model
    print("DOF before specifying:", degrees_of_freedom(m.fs))

    sf = 6
    # Specify the Feed
    m.fs.c1.inlet.flow_mass_phase_comp[0, "Liq", "NaCl"].fix(10.0)
    m.fs.c1.inlet.flow_mass_phase_comp[0, "Liq", "H2O"].fix(68.0)
    m.fs.c1.inlet.flow_mass_phase_comp[0, "Sol", "NaCl"].fix(1e-6)
    m.fs.c1.inlet.flow_mass_phase_comp[0, "Vap", "H2O"].fix(1e-6)
    m.fs.c1.inlet.pressure[0].fix(141325)
    m.fs.c1.inlet.temperature[0].fix(273.15 + 20)

    print("DOF after specifying feed:", degrees_of_freedom(m.fs))
    ##########################################
    # # Case 1: Fix crystallizer temperature
    ##########################################
    print("\n--- Case 1 ---")
    #m.fs.c1.temperature_operating.fix(273.15 + 116)
    m.fs.c1.pressure_operating.fix(1.4e5)
    m.fs.c1.solids.flow_mass_phase_comp[0, "Sol", "NaCl"].fix(5.56)

    # Fix
    m.fs.c1.crystal_growth_rate.fix()
    m.fs.c1.souders_brown_constant.fix()
    m.fs.c1.crystal_median_length.fix()

    # Bounds adjustment
    m.fs.c1.height_crystallizer.setub(300) # was 25, doesn't work for big ones?
    m.fs.c1.height_slurry.setub(300) # was 25, doesn't work for big ones?
    m.fs.c1.diameter_crystallizer.setub(300) # was 25, doesn't work for big ones?
    m.fs.c1.magma_circulation_flow_vol.setub(1000) # was 100, doesn't work for large crystallizers
    m.fs.c1.work_mechanical.setub(500_000_000) # was 5000_000, doesn't work for large crystallizers


    # # Scaling
    m.fs.properties.set_default_scaling(
        "flow_mass_phase_comp", 1e-2* sf, index=("Liq", "H2O")
    )
    m.fs.properties.set_default_scaling(
        "flow_mass_phase_comp", 1e-2* sf, index=("Liq", "NaCl")
    )
    m.fs.properties.set_default_scaling(
        "flow_mass_phase_comp", 1e-2*sf, index=("Vap", "H2O")
    )
    m.fs.properties.set_default_scaling(
        "flow_mass_phase_comp", 1e-3*sf, index=("Sol", "NaCl")
    )
    iscale.calculate_scaling_factors(m.fs)


    m.fs.helmholtz = build_package("helmholtz",["water"],["Liq","Vap"])
    m.fs.vapor_out = m.fs.helmholtz.build_state_block(m.fs.time)

    @m.fs.Constraint(m.fs.time)
    def eq_vapor_temp_out(blk, t):
        return m.fs.vapor_out[t].temperature == m.fs.c1.properties_vapor[t].temperature
    
    @m.fs.Constraint(m.fs.time)
    def eq_vapor_pressure_out(blk, t):
        return m.fs.vapor_out[t].pressure == m.fs.c1.properties_vapor[t].pressure
    
    @m.fs.Constraint(m.fs.time)
    def eq_vapor_flow_out(blk, t):
        return m.fs.vapor_out[t].flow_mass == m.fs.c1.properties_vapor[t].flow_mass_phase_comp["Vap", "H2O"]

    


    dt = DiagnosticsToolbox(m)
    # solving
    m.fs.c1.initialize(outlvl=idaeslog.DEBUG)
    assert_units_consistent(m)  # check that units are consistent
    assert degrees_of_freedom(m) == 0
    solver = get_solver()
    results = solver.solve(m, tee=True, symbolic_solver_labels=True)
    assert results.solver.termination_condition == TerminationCondition.optimal
    m.fs.c1.report()
    # m.fs.c1.display()
    # dt.display_variables_near_bounds()

    m.fs.c1.inlet.flow_mass_phase_comp[0, "Liq", "NaCl"].fix((8045 + 4643) / 3600 * 0.27)
    m.fs.c1.inlet.flow_mass_phase_comp[0, "Liq", "H2O"].fix((8045 + 4643) / 3600 * 0.73)
    m.fs.c1.inlet.flow_mass_phase_comp[0, "Sol", "NaCl"].fix(1e-3)
    m.fs.c1.inlet.flow_mass_phase_comp[0, "Vap", "H2O"].fix(1e-3)
    #m.fs.c1.solids.flow_mass_phase_comp[0, "Sol", "NaCl"].fix((4658)/3600 * 0.66 ) # This has to be slightly less than in the calcs, as there needs to be a trace amount in the liquid outlet.
    # would be better to fix the liquid outlet to 1e-6 abd calculate the solids outlet.
    m.fs.c1.solids.flow_mass_phase_comp[0, "Sol", "NaCl"].unfix()
    
    #m.fs.c1.outlet.flow_mass_phase_comp[0, "Liq", "NaCl"].fix(1e-3)
    m.fs.c1.vapor.flow_mass_phase_comp[0, "Vap", "H2O"].fix((8045 + 4643) / 3600 * 0.73 -  (8045 + 4643) / 3600 * 0.27 / 2)

    @m.fs.Expression(m.fs.time)
    def ratio_salt(blk, t):
        # Constrain that 66% of the slurry (solid and liquid) is salt, meaning the rest of the water is vapor
        return (m.fs.c1.outlet.flow_mass_phase_comp[t, "Liq", "NaCl"] + m.fs.c1.solids.flow_mass_phase_comp[t, "Sol", "NaCl"]) / (
            m.fs.c1.outlet.flow_mass_phase_comp[t, "Liq", "NaCl"] + m.fs.c1.solids.flow_mass_phase_comp[t, "Sol", "NaCl"] + m.fs.c1.outlet.flow_mass_phase_comp[t, "Liq", "H2O"]
        ) 
    #m.fs.c1.product_volumetric_solids_fraction.fix(0.9)
    try:
        results = solver.solve(m,tee=False, symbolic_solver_labels=True)
        assert results.solver.termination_condition == TerminationCondition.optimal
    except Exception as e:
        print(e)
    print(pyo.value(m.fs.c1.product_volumetric_solids_fraction))

    m.fs.c1.report()
    print(pyo.value(m.fs.ratio_salt[0]))
    m.fs.vapor_out.report()

    # m.fs.c1.display()
    # Adjusting bounds is crucial to see how things work if you are trying to scale things up
    #dt.display_variables_near_bounds()



    #m.fs.c1.display()

    return m


if __name__ == "__main__":
    m = main()