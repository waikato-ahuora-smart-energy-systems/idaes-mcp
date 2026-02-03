import pyomo.environ as pyo



def step_solve(solver, model: pyo.ConcreteModel, max_iter: int, expressions_to_track: list)-> list[list[float]]:
    """
    Solves a model in steps, checking the values of the expressions against the expected values after each step.

    This may be useful for diagnosing convergence issues in complex models.
    
    :param solver: Idaes solver object. E.g SolverFactory('ipopt')
    :param model: Pyomo model to solve e.g model = ConcreteModel()
    :param max_iter: Maximum number of iterations to perform. Each iteration will perform one solver step.
    :param expressions_to_track: List of Pyomo expressions in the model to track. E.g [model.expr1, model.expr2]

    :return: A 2d list for each of the expressions tracked, containing the value of the expression after each step.
    """

    solver.options['max_iter'] = 3
    expression_values: list[list[float]] = [[] for _ in expressions_to_track]
    for i in range(max_iter):
        solver.options['max_iter'] = i
        results = solver.solve(model, tee=False)
        for j, expr in enumerate(expressions_to_track):
                val : float = pyo.value(expr)
                expression_values[j].append(val)
        if (results.solver.termination_condition !=pyo.TerminationCondition.maxIterations):
             break
        
    return expression_values
