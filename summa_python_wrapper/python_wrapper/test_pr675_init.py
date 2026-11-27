#!/usr/bin/env python3

import argparse
import ctypes
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--library", required=True)
parser.add_argument("--config", required=True)
args = parser.parse_args()

library = Path(args.library).resolve()
config = Path(args.config).resolve()

if not library.is_file():
    raise SystemExit(f"SUMMA library not found: {library}")

if not config.is_file():
    raise SystemExit(f"SUMMA configuration not found: {config}")

print("========== PYTHON-SUMMA INITIALIZATION ==========", flush=True)
print("Library:", library, flush=True)
print("Configuration:", config, flush=True)

lib = ctypes.CDLL(str(library))

lib.summa_py_api_version.argtypes = []
lib.summa_py_api_version.restype = ctypes.c_int

lib.summa_py_init.argtypes = [
    ctypes.c_char_p,
    ctypes.POINTER(ctypes.c_char),
    ctypes.c_int,
]
lib.summa_py_init.restype = ctypes.c_int

version = lib.summa_py_api_version()
print("API version:", version, flush=True)

if version != 675:
    raise SystemExit("Incorrect SUMMA API version")

message = ctypes.create_string_buffer(4096)

print("Starting native SUMMA initialization and spin-up...", flush=True)

status = lib.summa_py_init(
    str(config).encode("utf-8"),
    message,
    len(message),
)

# Finalize MPI before leaving the Python worker process.
lib.summa_py_finalize.argtypes = []
lib.summa_py_finalize.restype = ctypes.c_int

finalize_status = lib.summa_py_finalize()

print("MPI finalization status:", finalize_status, flush=True)

if finalize_status != 0:
    raise SystemExit(f"MPI finalization failed: {finalize_status}")

print("========== INITIALIZATION RESULT ==========", flush=True)
print("Return code:", status, flush=True)
print("SUMMA message:", message.value.decode(errors="replace"), flush=True)

if status != 0:
    raise SystemExit(status)

print("SUMMA Python initialization: PASS", flush=True)
