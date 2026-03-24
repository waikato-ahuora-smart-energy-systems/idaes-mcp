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

def set_bounds(crystallizer):
    # Bounds adjustment
    crystallizer.height_crystallizer.setub(300) # was 25, doesn't work for big ones?
    crystallizer.height_slurry.setub(300) # was 25, doesn't work for big ones?
    crystallizer.diameter_crystallizer.setub(300) # was 25, doesn't work for big ones?
    crystallizer.magma_circulation_flow_vol.setub(1000) # was 100, doesn't work for large crystallizers
    crystallizer.work_mechanical.setub(500_000_000) # was 5000_000, doesn't work for large crystallizers

def fix_constants(crystallizer):
    # Fix
    crystallizer.crystal_growth_rate.fix()
    crystallizer.souders_brown_constant.fix()
    crystallizer.crystal_median_length.fix()

def calc_mass_fractions(total_mass : list[float], X_NaCl : list[float]):
    # from a list of total mass and corresponding mass fractions, calculate the mass of each component
    mass_NaCl = sum([total * x for total, x in zip(total_mass, X_NaCl)])
    mass_H2O = sum([total * (1 - x) for total, x in zip(total_mass, X_NaCl)])
    return mass_NaCl, mass_H2O

def main():
    m = ConcreteModel()
    m.fs = FlowsheetBlock(dynamic=False)
    # attach property package
    m.fs.properties = props.NaClParameterBlock()

    ####################################################
    # Crystallizer 1
    ####################################################
    m.fs.c1 = Crystallization(property_package=m.fs.properties)
    set_bounds(m.fs.c1)
    fix_constants(m.fs.c1)

    # Specify the Feed
    m.fs.c1.inlet.pressure[0].fix(2.5e5)
    m.fs.c1.inlet.temperature[0].fix(273.15 + 20)
    mass_nacl, mass_h2o = calc_mass_fractions([8045/3600, 4643/3600], [0.27, 0.27])
    m.fs.c1.inlet.flow_mass_phase_comp[0, "Liq", "NaCl"].fix(mass_nacl)
    m.fs.c1.inlet.flow_mass_phase_comp[0, "Liq", "H2O"].fix(mass_h2o)
    m.fs.c1.inlet.flow_mass_phase_comp[0, "Sol", "NaCl"].fix(1e-3)
    m.fs.c1.inlet.flow_mass_phase_comp[0, "Vap", "H2O"].fix(1e-3)
    # Specify the operating conditions
    m.fs.c1.pressure_operating.fix(2.5e5) # 2.5 bar
    m.fs.c1.vapor.flow_mass_phase_comp[0, "Vap", "H2O"].fix(mass_h2o -  mass_nacl / 2) # remove enough vapor for 66% nacl wt% slurry, i.e the amount of water left is half the amount of nacl.

    ####################################################
    # Crystallizer 2
    ####################################################
    m.fs.c2 = Crystallization(property_package=m.fs.properties)
    set_bounds(m.fs.c2)
    fix_constants(m.fs.c2)

    # Specify the Feed
    m.fs.c2.inlet.pressure[0].fix(1.4e5)
    m.fs.c2.inlet.temperature[0].fix(273.15 + 20)
    # Feed from B evap, B evap leg, and purge is all mixed together as inlet.
    mass_nacl, mass_h2o = calc_mass_fractions([7376/3600, 4301/3600, 1519/3600], [0.27, 0.27, 0.31])
    m.fs.c2.inlet.flow_mass_phase_comp[0, "Liq", "NaCl"].fix(mass_nacl)
    m.fs.c2.inlet.flow_mass_phase_comp[0, "Liq", "H2O"].fix(mass_h2o)
    m.fs.c2.inlet.flow_mass_phase_comp[0, "Sol", "NaCl"].fix(1e-3)
    m.fs.c2.inlet.flow_mass_phase_comp[0, "Vap", "H2O"].fix(1e-3)
    # Specify the operating conditions
    m.fs.c2.pressure_operating.fix(1.4e5) # 1.4 bar
    m.fs.c2.vapor.flow_mass_phase_comp[0, "Vap", "H2O"].fix(mass_h2o -  mass_nacl / 2) 

    #################################################
    # # Scaling
    #################################################
    sf = 6
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

    ################################################
    #   Initialisation
    ################################################
    dt = DiagnosticsToolbox(m)
    # solving
    m.fs.c1.initialize(outlvl=idaeslog.INFO_LOW)
    m.fs.c2.initialize(outlvl=idaeslog.INFO_LOW)
    assert_units_consistent(m)  # check that units are consistent
    assert degrees_of_freedom(m) == 0
    solver = get_solver()

    try:
        results = solver.solve(m,tee=False, symbolic_solver_labels=True)
        assert results.solver.termination_condition == TerminationCondition.optimal
    except Exception as e:
        print(e)

    m.fs.c1.report()
    m.fs.c2.report()

    # m.fs.c1.display()
    # Adjusting bounds is crucial to see how things work if you are trying to scale things up
    #dt.display_variables_near_bounds()

    return m


if __name__ == "__main__":
    m = main()