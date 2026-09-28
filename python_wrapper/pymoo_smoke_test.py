import numpy as np

from pymoo.core.problem import ElementwiseProblem
from pymoo.algorithms.soo.nonconvex.ga import GA
from pymoo.optimize import minimize

from summa_ctypes import SummaModel


LIB = (
    "/work/comphyd_lab/users/arman.haddadchi/"
    "hydro_models/builds/"
    "summa_v4.5_python_coupled/libsumma.so"
)

CONFIG = (
    "/work/comphyd_lab/users/arman.haddadchi/"
    "CENTURY_Basins_summa_mizuroute_exps/"
    "Exp5_coupledsumma_hourly_Newdata/"
    "python_wrapper/configs/CAN_01AD003.toml"
)


PARAM_NAMES = [
    "k_soil",
    "aquiferScaleFactor",
    "aquiferBaseflowExp",
    "qSurfScale",
    "Fcapil",
    "tempCritRain",
]


LOWER = np.array([
    1.0e-7,
    0.1,
    1.0,
    1.0,
    0.01,
    272.16,
])

UPPER = np.array([
    1.0e-5,
    100.0,
    10.0,
    100.0,
    0.10,
    274.16,
])


class SummaProblem(ElementwiseProblem):

    def __init__(self):

        super().__init__(
            n_var=len(PARAM_NAMES),
            n_obj=1,
            xl=LOWER,
            xu=UPPER,
        )

        self.model = SummaModel(
            library_path=LIB,
            config_path=CONFIG,
        )

    def _evaluate(self, x, out, *args, **kwargs):

        params = dict(zip(PARAM_NAMES, x))

        kge = self.model.evaluate(params)

        print(
            "KGE:",
            kge,
            "params:",
            params,
            flush=True,
        )

        # Pymoo minimizes, so maximize KGE by minimizing -KGE.
        out["F"] = -kge


problem = SummaProblem()

algorithm = GA(
    pop_size=4,
    eliminate_duplicates=True,
)

result = minimize(
    problem,
    algorithm,
    termination=("n_gen", 2),
    seed=1,
    verbose=True,
)


print()
print("========================================")
print("PYMOO SMOKE TEST COMPLETE")
print("========================================")

print("Best parameters:")
for name, value in zip(PARAM_NAMES, result.X):
    print(f"{name:24s} {value:.12g}")

print()
print("Best KGE:", -float(result.F))