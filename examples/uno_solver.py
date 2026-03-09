import subprocess
import os
from pyomo.solvers.plugins.solvers.ASL import ASL
from pyomo.opt.base.solvers import OptSolver
from pyomo.opt.base import SolverFactory
from pyomo.opt.results import SolverResults, SolverStatus, TerminationCondition


@SolverFactory.register("uno_ampl", doc="UNO nonlinear solver")
class UNOSolver(ASL):
    def __init__(self, **kwds):
        kwds["type"] = "uno_ampl"
        super().__init__(**kwds)