from pathlib import Path
import shutil


BASIN = "CAN_01AD003"
NWORKERS = 4

EXP5 = Path(
    "/work/comphyd_lab/users/arman.haddadchi/"
    "CENTURY_Basins_summa_mizuroute_exps/"
    "Exp5_coupledsumma_hourly_Newdata"
)

BASE_CONFIG = (
    EXP5 / "python_wrapper" / "configs" / f"{BASIN}.toml"
)

DOMAIN = EXP5 / "domain" / BASIN

RUNTIME = (
    EXP5 / "python_wrapper" / "runtime" / BASIN
)


def main():

    base_text = BASE_CONFIG.read_text()

    for i in range(NWORKERS):

        worker = RUNTIME / f"worker_{i:02d}"

        state_dir = worker / "state"
        work_dir = worker / "work"

        state_dir.mkdir(parents=True, exist_ok=True)
        work_dir.mkdir(parents=True, exist_ok=True)

        # Each worker gets its own writable state directory.
        cold_src = DOMAIN / "summa_state" / "coldState.nc"
        cold_dst = state_dir / "coldState.nc"

        if cold_dst.exists() or cold_dst.is_symlink():
            cold_dst.unlink()

        cold_dst.symlink_to(cold_src)

        text = base_text

        # Keep all large/read-only files in the original basin directory.
        # Change only writable state and output locations.
        text = text.replace(
            'state_path   = "{home}/{basin_dir}/summa_state/"',
            f'state_path   = "{state_dir}/"',
        )

        text = text.replace(
            'work_path = "{home}/{basin_dir}/work/"',
            f'work_path = "{work_dir}/"',
        )

        config = worker / "config.toml"
        config.write_text(text)

        print(f"Prepared worker {i:02d}: {config}")


if __name__ == "__main__":
    main()