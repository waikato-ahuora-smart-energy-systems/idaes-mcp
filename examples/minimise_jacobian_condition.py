import pyomo.environ as pyo
import numpy as np
from idaes.core.scaling.util import get_jacobian


def minimize_jacobian_condition(model):
    """
    Given a Pyomo ConcreteModel M with constraints F(x)=0,
    compute scaling that minimizes the Euclidean condition
    number of the Jacobian.
    """

    # Extract Jacobian numerically
    print("Extracting Jacobian...")
    jacobian, nlp = get_jacobian(model)
    J = jacobian.toarray()

    n = J.shape[0]

    A = J
    Ainv = np.linalg.inv(A)

    # Construct matrix M from the paper
    M = np.block([
        [np.zeros((n,n)), A],
        [Ainv, np.zeros((n,n))]
    ])

    dim = 2*n

    m = pyo.ConcreteModel()

    m.N = pyo.RangeSet(dim)

    # scaling variables (log scaling for convexity)
    m.d = pyo.Var(m.N)

    # singular value bound
    m.t = pyo.Var(within=pyo.NonNegativeReals)

    # scaled matrix X = e^D M e^{-D}
    def X_init(blk,i,j):
        return M[i-1,j-1]

    m.M = pyo.Param(m.N, m.N, initialize=X_init, mutable=False)

    m.X = pyo.Var(m.N, m.N)

    def scaled_matrix_rule(m,i,j):
        return m.X[i,j] == pyo.exp(m.d[i]) * m.M[i,j] * pyo.exp(-m.d[j])
    
    print("Adding scaled matrix constraint...")

    m.scaled_matrix = pyo.Constraint(m.N, m.N, rule=scaled_matrix_rule)

    print("Adding SDP constraint...")
    # SDP matrix variable
    size = 2*dim
    m.K = pyo.RangeSet(size)

    m.S = pyo.Var(m.K, m.K)

    # Build block matrix
    def block_matrix_rule(m,i,j):

        if i <= dim and j <= dim:
            return m.S[i,j] == m.t if i==j else 0

        elif i <= dim and j > dim:
            return m.S[i,j] == m.X[i, j-dim]

        elif i > dim and j <= dim:
            return m.S[i,j] == m.X[j, i-dim]

        else:
            return m.S[i,j] == m.t if (i-dim)==(j-dim) else 0

    m.block_matrix = pyo.Constraint(m.K, m.K, rule=block_matrix_rule)

    # Objective
    m.obj = pyo.Objective(expr=m.t)
    print("Solving SDP...")

    # NOTE: need SDP solver
    solver = pyo.SolverFactory("mosek")
    solver.solve(m)
    print("solved!")

    # extract scaling
    d = np.array([pyo.value(m.d[i]) for i in m.N])
    D = np.diag(np.exp(d))

    return D