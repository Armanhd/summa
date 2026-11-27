
#!/usr/bin/env python3
"""
Reusable ctypes interface for SUMMA + mizuRoute optimization.

SUMMA owns:
- TOML parameter definitions and bounds
- Spatial multipliers and parameter ratios
- Parameter dependencies and physical feasibility
- Model spin-up, simulation and objective calculations
- Native calibration NetCDF output
- Export of best physical parameter fields

Python owns:
- Optimization algorithms
- Candidate generation and scheduling
- Independent random seeds
- Best-solution tracking

One initialized SUMMA instance per Python process.
"""

import ctypes as C
import math
from datetime import datetime, timezone
from pathlib import Path


MESSAGE_LEN = 4096
MAX_OBJECTIVES = 128


class SummaModel:

    def __init__(self, library_path, config_path, run_index=1):

        self.library_path = str(Path(library_path).resolve())
        self.config_path = str(Path(config_path).resolve())

        self.run_index = int(run_index)
        if self.run_index < 1:
            raise ValueError('run_index must be positive')

        self.lib = C.CDLL(self.library_path)

        self.initialized = False
        self.output_opened = False
        self.parameters = []

        self._configure_api()
        self.initialize()


    def _configure_api(self):

        lib = self.lib

        lib.summa_py_api_version.argtypes = []
        lib.summa_py_api_version.restype = C.c_int

        lib.summa_py_init.argtypes = [
            C.c_char_p,
            C.POINTER(C.c_char),
            C.c_int,
        ]
        lib.summa_py_init.restype = C.c_int

        lib.summa_py_set_run_index.argtypes = [C.c_int]
        lib.summa_py_set_run_index.restype = C.c_int

        lib.summa_py_finalize.argtypes = []
        lib.summa_py_finalize.restype = C.c_int

        lib.summa_py_nparameters.argtypes = []
        lib.summa_py_nparameters.restype = C.c_int

        lib.summa_py_get_parameter.argtypes = [
            C.c_int,
            C.POINTER(C.c_char),
            C.c_int,
            C.POINTER(C.c_char),
            C.c_int,
            C.POINTER(C.c_double),
            C.POINTER(C.c_double),
            C.POINTER(C.c_double),
            C.POINTER(C.c_double),
        ]
        lib.summa_py_get_parameter.restype = C.c_int

        lib.summa_py_check_feasibility.argtypes = [
            C.c_int,
            C.POINTER(C.c_double),
            C.POINTER(C.c_int),
            C.POINTER(C.c_char),
            C.c_int,
        ]
        lib.summa_py_check_feasibility.restype = C.c_int

        lib.summa_py_evaluate.argtypes = [
            C.c_int,
            C.POINTER(C.c_double),
            C.c_int,
            C.POINTER(C.c_double),
            C.POINTER(C.c_int),
            C.POINTER(C.c_int),
            C.POINTER(C.c_char),
            C.c_int,
        ]
        lib.summa_py_evaluate.restype = C.c_int

        lib.summa_py_output_open.argtypes = [
            C.c_char_p,
            C.c_int,
            C.POINTER(C.c_char),
            C.c_int,
        ]
        lib.summa_py_output_open.restype = C.c_int

        lib.summa_py_set_optimizer.argtypes = [
            C.c_char_p,
            C.POINTER(C.c_char),
            C.c_int,
        ]
        lib.summa_py_set_optimizer.restype = C.c_int

        lib.summa_py_output_write.argtypes = [
            C.c_int,
            C.c_int,
            C.POINTER(C.c_double),
            C.c_int,
            C.POINTER(C.c_double),
            C.c_int,
            C.POINTER(C.c_int),
            C.POINTER(C.c_int),
            C.POINTER(C.c_char),
            C.c_int,
        ]
        lib.summa_py_output_write.restype = C.c_int

        lib.summa_py_output_close.argtypes = [
            C.POINTER(C.c_char),
            C.c_int,
        ]
        lib.summa_py_output_close.restype = C.c_int

        lib.summa_py_export_best.argtypes = [
            C.c_char_p,
            C.c_int,
            C.c_int,
            C.POINTER(C.c_double),
            C.POINTER(C.c_char),
            C.c_int,
        ]
        lib.summa_py_export_best.restype = C.c_int


    @staticmethod
    def _message():
        return C.create_string_buffer(MESSAGE_LEN)


    def initialize(self):

        version = self.lib.summa_py_api_version()

        if version != 675:
            raise RuntimeError(
                f"Unsupported SUMMA API version: {version}"
            )

        # Run index must be configured before SUMMA initialization.
        status = self.lib.summa_py_set_run_index(
            self.run_index
        )

        if status != 0:
            raise RuntimeError(
                f"Invalid SUMMA run_index: {self.run_index}"
            )

        message = self._message()

        status = self.lib.summa_py_init(
            self.config_path.encode(),
            message,
            MESSAGE_LEN,
        )

        if status != 0:
            raise RuntimeError(
                f"SUMMA initialization failed ({status}): "
                + message.value.decode(errors="replace")
            )

        self.initialized = True
        self.parameters = self.get_parameters()


    def get_parameters(self):
        """Retrieve parameter definitions from native SUMMA."""

        n = self.lib.summa_py_nparameters()

        if n <= 0:
            raise RuntimeError("No calibration parameters")

        parameters = []

        for index in range(1, n + 1):

            name = self._message()
            transform = self._message()

            lower = C.c_double()
            upper = C.c_double()
            search_lower = C.c_double()
            search_upper = C.c_double()

            status = self.lib.summa_py_get_parameter(
                index,
                name,
                len(name),
                transform,
                len(transform),
                C.byref(lower),
                C.byref(upper),
                C.byref(search_lower),
                C.byref(search_upper),
            )

            if status != 0:
                raise RuntimeError(
                    f"Cannot retrieve SUMMA parameter {index}"
                )

            entry = {
                "name": name.value.decode(),
                "transform": transform.value.decode().strip().lower(),
                "lower": lower.value,
                "upper": upper.value,
                "search_lower": search_lower.value,
                "search_upper": search_upper.value,
            }

            if entry["transform"] not in ("none", "log"):
                raise ValueError(
                    f"Unsupported transformation: {entry}"
                )

            if not all(
                math.isfinite(entry[key])
                for key in (
                    "lower", "upper",
                    "search_lower", "search_upper"
                )
            ):
                raise ValueError(f"Non-finite bounds: {entry}")

            if entry["search_lower"] >= entry["search_upper"]:
                raise ValueError(f"Invalid bounds: {entry}")

            parameters.append(entry)

        return parameters


    def _physical_array(self, values):
        """Accept native-ordered physical parameter vectors."""

        values = list(values)

        if len(values) != len(self.parameters):
            raise ValueError(
                f"Expected {len(self.parameters)} parameters, "
                f"received {len(values)}"
            )

        if not all(math.isfinite(float(v)) for v in values):
            raise ValueError("Non-finite parameter value")

        return (C.c_double * len(values))(
            *(float(v) for v in values)
        )


    def feasible(self, values):

        x = self._physical_array(values)

        accepted = C.c_int(0)
        message = self._message()

        status = self.lib.summa_py_check_feasibility(
            len(values),
            x,
            C.byref(accepted),
            message,
            MESSAGE_LEN,
        )

        if status != 0:
            raise RuntimeError(
                f"SUMMA feasibility error ({status}): "
                + message.value.decode(errors="replace")
            )

        return bool(accepted.value)


    def evaluate(self, values):
        """Evaluate a native-ordered physical parameter vector."""

        x = self._physical_array(values)

        objectives = (C.c_double * MAX_OBJECTIVES)()
        nout = C.c_int(0)
        failed = C.c_int(1)
        message = self._message()

        status = self.lib.summa_py_evaluate(
            len(values),
            x,
            MAX_OBJECTIVES,
            objectives,
            C.byref(nout),
            C.byref(failed),
            message,
            MESSAGE_LEN,
        )

        result_values = [
            objectives[i]
            for i in range(max(0, min(nout.value, MAX_OBJECTIVES)))
        ]

        success = (
            status == 0
            and failed.value == 0
            and len(result_values) > 0
            and all(math.isfinite(v) for v in result_values)
        )

        return {
            "success": success,
            "objectives": result_values,
            "trial_failed": not success,
            "error_code": status,
            "message": message.value.decode(errors="replace"),
        }


    def set_optimizer(self, algorithm):
        """
        Set the Python optimizer name in native SUMMA output.

        Must be called after initialization and before
        opening the calibration NetCDF file.
        """

        if not self.initialized:
            raise RuntimeError(
                "SUMMA must be initialized first"
            )

        if self.output_opened:
            raise RuntimeError(
                "Cannot change optimizer while output is open"
            )

        algorithm = str(algorithm).strip().lower()

        allowed = {
            "ga",
            "nsga2",
            "differential_evolution",
            "cma_es",
            "custom_dds",
            "spotpy_dds",
            "sceua",
        }

        if algorithm not in allowed:
            raise ValueError(
                f"Unsupported Python optimizer: {algorithm}"
            )

        message = self._message()

        status = self.lib.summa_py_set_optimizer(
            algorithm.encode(),
            message,
            MESSAGE_LEN,
        )

        if status != 0:
            raise RuntimeError(
                f"Setting optimizer failed ({status}): "
                + message.value.decode(errors="replace")
            )

        self.optimizer = algorithm


    def output_open(self, path, n_trials):

        if self.output_opened:
            raise RuntimeError("Calibration output already open")

        path = Path(path)

        if path.exists():
            raise FileExistsError(path)

        path.parent.mkdir(parents=True, exist_ok=True)

        message = self._message()

        status = self.lib.summa_py_output_open(
            str(path).encode(),
            int(n_trials),
            message,
            MESSAGE_LEN,
        )

        if status != 0:
            raise RuntimeError(
                f"NetCDF creation failed ({status}): "
                + message.value.decode(errors="replace")
            )

        self.output_opened = True


    @staticmethod
    def _time_components(moment):

        moment = moment.astimezone(timezone.utc)

        return (C.c_int * 8)(
            moment.year,
            moment.month,
            moment.day,
            0,
            moment.hour,
            moment.minute,
            moment.second,
            moment.microsecond // 1000,
        )


    def output_write(self, trial, values, objectives, failed,
                     start_time, end_time):

        if not self.output_opened:
            raise RuntimeError("Calibration output is not open")

        x = self._physical_array(values)

        y_values = list(objectives)

        if not y_values:
            raise ValueError(
                "Objective array is required for native output"
            )

        y = (C.c_double * len(y_values))(*y_values)
        message = self._message()

        status = self.lib.summa_py_output_write(
            int(trial),
            len(values),
            x,
            len(y_values),
            y,
            int(bool(failed)),
            self._time_components(start_time),
            self._time_components(end_time),
            message,
            MESSAGE_LEN,
        )

        if status != 0:
            raise RuntimeError(
                f"NetCDF write failed ({status}): "
                + message.value.decode(errors="replace")
            )


    def output_close(self):

        if not self.output_opened:
            return

        message = self._message()

        status = self.lib.summa_py_output_close(
            message,
            MESSAGE_LEN,
        )

        if status != 0:
            raise RuntimeError(
                f"NetCDF close failed ({status}): "
                + message.value.decode(errors="replace")
            )

        self.output_opened = False


    def export_best(self, path, trial, values):

        x = self._physical_array(values)
        message = self._message()

        status = self.lib.summa_py_export_best(
            str(path).encode(),
            int(trial),
            len(values),
            x,
            message,
            MESSAGE_LEN,
        )

        if status != 0:
            raise RuntimeError(
                f"Best-parameter export failed ({status}): "
                + message.value.decode(errors="replace")
            )


    def finalize(self):

        self.output_close()

        if self.initialized:
            status = self.lib.summa_py_finalize()

            if status != 0:
                raise RuntimeError(
                    f"SUMMA finalization failed ({status})"
                )

            self.initialized = False
