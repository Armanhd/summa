#!/usr/bin/env python3
import ctypes as C
import argparse
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--library", required=True)
parser.add_argument("--config", required=True)
args = parser.parse_args()

lib = C.CDLL(str(Path(args.library).resolve()))
config = str(Path(args.config).resolve())

lib.summa_py_init.argtypes = [C.c_char_p, C.POINTER(C.c_char), C.c_int]
lib.summa_py_init.restype = C.c_int

lib.summa_py_nparameters.argtypes = []
lib.summa_py_nparameters.restype = C.c_int

lib.summa_py_get_parameter.argtypes = [
    C.c_int, C.POINTER(C.c_char), C.c_int,
    C.POINTER(C.c_char), C.c_int,
    C.POINTER(C.c_double), C.POINTER(C.c_double),
    C.POINTER(C.c_double), C.POINTER(C.c_double),
]
lib.summa_py_get_parameter.restype = C.c_int

lib.summa_py_finalize.argtypes = []
lib.summa_py_finalize.restype = C.c_int

message = C.create_string_buffer(4096)

try:
    status = lib.summa_py_init(config.encode(), message, len(message))
    if status:
        raise RuntimeError(
            f"Initialization failed ({status}): {message.value.decode()}"
        )

    n = lib.summa_py_nparameters()
    print(f"\nNumber of calibration parameters: {n}", flush=True)

    if n != 16:
        raise RuntimeError(f"Expected 16 parameters, received {n}")

    print(
        f"{'Parameter':24s} {'Transform':12s} "
        f"{'Lower':>13s} {'Upper':>13s} "
        f"{'Search lower':>13s} {'Search upper':>13s}",
        flush=True,
    )

    for i in range(1, n + 1):
        name = C.create_string_buffer(128)
        transform = C.create_string_buffer(64)
        lower = C.c_double()
        upper = C.c_double()
        search_lower = C.c_double()
        search_upper = C.c_double()

        status = lib.summa_py_get_parameter(
            i, name, len(name), transform, len(transform),
            C.byref(lower), C.byref(upper),
            C.byref(search_lower), C.byref(search_upper),
        )

        if status:
            raise RuntimeError(f"Parameter {i}: API error {status}")

        print(
            f"{name.value.decode():24s} "
            f"{transform.value.decode():12s} "
            f"{lower.value:13.6g} {upper.value:13.6g} "
            f"{search_lower.value:13.6g} {search_upper.value:13.6g}",
            flush=True,
        )

    print("\nPARAMETER METADATA: PASS", flush=True)

finally:
    status = lib.summa_py_finalize()
    print(f"MPI finalization status: {status}", flush=True)
    if status:
        raise RuntimeError(f"MPI finalization failed: {status}")
