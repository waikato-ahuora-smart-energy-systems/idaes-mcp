import numpy as np
from generate_graph import decompose_jacobian
from pyomo.environ import ConcreteModel
from idaes.core.util.scaling import get_scaling_factor, set_scaling_factor

def apply_ruiz_scaling(m: ConcreteModel):
    jacobian, nlp, cmap, vmap = decompose_jacobian(m)
    Dr, Dc = ruiz_scaling(jacobian.toarray())

    for i, c in enumerate(nlp.clist):
        set_scaling_factor(c, Dr[i])

    # for i, v in enumerate(nlp.vlist):
    #     set_scaling_factor(v, Dc[i]* -1)



def ruiz_scaling(A, max_iter=20, tol=1e-3):
    """
    Compute row/column scaling for matrix equilibration.

    Returns:
        Dr  (constraint scaling)
        Dc  (variable scaling)
    """

    m, n = A.shape

    Dr = np.ones(m)
    Dc = np.ones(n)

    A_scaled = A.copy()

    for _ in range(max_iter):

        # Row scaling
        row_norms = np.sqrt(np.sum(A_scaled**2, axis=1))
        row_scale = 1.0 / np.maximum(row_norms, 1e-12)

        Dr *= row_scale
        A_scaled = np.diag(row_scale) @ A_scaled

        # Column scaling
        col_norms = np.sqrt(np.sum(A_scaled**2, axis=0))
        col_scale = 1.0 / np.maximum(col_norms, 1e-12)

        Dc *= col_scale
        A_scaled = A_scaled @ np.diag(col_scale)

        # convergence check
        if max(abs(row_norms - 1).max(), abs(col_norms - 1).max()) < tol:
            break

    return Dr, Dc