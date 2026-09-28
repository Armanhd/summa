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


model = SummaModel(
    library_path=LIB,
    config_path=CONFIG,
)


# Use only parameters that we already know are safe to override.
params = {
    "k_soil": 7.5e-6,
    "aquiferScaleFactor": 0.35,
    "aquiferBaseflowExp": 2.0,
    "qSurfScale": 50.0,
    "Fcapil": 0.06,
    "tempCritRain": 273.16,
}


kge = model.evaluate(params)

print()
print("SUMMA Python wrapper test")
print("-------------------------")
print("KGE =", kge)