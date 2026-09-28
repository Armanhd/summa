from pathlib import Path


# ============================================================
# Main paths
# ============================================================

SUMMA_ROOT = Path(
    "/work/comphyd_lab/users/arman.haddadchi/"
    "hydro_models/summa_v4.5_python"
)

EXP5 = Path(
    "/work/comphyd_lab/users/arman.haddadchi/"
    "CENTURY_Basins_summa_mizuroute_exps/"
    "Exp5_coupledsumma_hourly_Newdata"
)

LIBSUMMA = Path(
    "/work/comphyd_lab/users/arman.haddadchi/"
    "hydro_models/builds/"
    "summa_v4.5_python_coupled/libsumma.so"
)


# ============================================================
# Optimization parameters
# ============================================================
#
# "transform": "log10"
# means Pymoo searches in log10 space, but SUMMA receives
# the original physical parameter value.
#
# Canopy height parameters are intentionally excluded for this
# first production calibration because they have an ordered
# dependency that should be handled explicitly later.
# ============================================================

PARAMETERS = [
    {
        "name": "k_soil",
        "lower": 1.0e-7,
        "upper": 1.0e-5,
        "transform": "log10",
    },
    {
        "name": "aquiferScaleFactor",
        "lower": 0.1,
        "upper": 100.0,
        "transform": "linear",
    },
    {
        "name": "aquiferBaseflowExp",
        "lower": 1.0,
        "upper": 10.0,
        "transform": "linear",
    },
    {
        "name": "qSurfScale",
        "lower": 1.0,
        "upper": 100.0,
        "transform": "linear",
    },
    {
        "name": "summerLAI",
        "lower": 0.01,
        "upper": 10.0,
        "transform": "linear",
    },
    {
        "name": "frozenPrecipMultip",
        "lower": 0.5,
        "upper": 1.5,
        "transform": "linear",
    },
    {
        "name": "Fcapil",
        "lower": 0.01,
        "upper": 0.10,
        "transform": "linear",
    },
    {
        "name": "tempCritRain",
        "lower": 272.16,
        "upper": 274.16,
        "transform": "linear",
    },
    {
        "name": "windReductionParam",
        "lower": 0.0,
        "upper": 1.0,
        "transform": "linear",
    },
    {
        "name": "vGn_n",
        "lower": 1.0,
        "upper": 3.0,
        "transform": "linear",
    },
]


# ============================================================
# Default production calibration
# ============================================================

DEFAULT_POPULATION = 40
DEFAULT_GENERATIONS = 20
DEFAULT_SEED = 1