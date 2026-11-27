#!/usr/bin/env python3
import argparse
import ctypes as C
import math
import json
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("--library", required=True)
p.add_argument("--config", required=True)
args = p.parse_args()

lib = C.CDLL(str(Path(args.library).resolve()))

lib.summa_py_init.argtypes = [
    C.c_char_p, C.POINTER(C.c_char), C.c_int
]
lib.summa_py_init.restype = C.c_int

lib.summa_py_finalize.argtypes = []
lib.summa_py_finalize.restype = C.c_int

lib.summa_py_nparameters.argtypes = []
lib.summa_py_nparameters.restype = C.c_int

lib.summa_py_get_parameter.argtypes = [
    C.c_int, C.POINTER(C.c_char), C.c_int,
    C.POINTER(C.c_char), C.c_int,
    C.POINTER(C.c_double), C.POINTER(C.c_double),
    C.POINTER(C.c_double), C.POINTER(C.c_double)
]
lib.summa_py_get_parameter.restype = C.c_int

lib.summa_py_check_feasibility.argtypes = [
    C.c_int, C.POINTER(C.c_double),
    C.POINTER(C.c_int), C.POINTER(C.c_char), C.c_int
]
lib.summa_py_check_feasibility.restype = C.c_int

lib.summa_py_evaluate.argtypes = [
    C.c_int, C.POINTER(C.c_double), C.c_int,
    C.POINTER(C.c_double), C.POINTER(C.c_int),
    C.POINTER(C.c_int), C.POINTER(C.c_char), C.c_int
]
lib.summa_py_evaluate.restype = C.c_int

msg = C.create_string_buffer(4096)

def parameters():
    result = []
    n = lib.summa_py_nparameters()
    assert n == 16, f"Expected 16 parameters, got {n}"

    for i in range(1, n + 1):
        name = C.create_string_buffer(128)
        transform = C.create_string_buffer(64)
        lo, hi = C.c_double(), C.c_double()
        slo, shi = C.c_double(), C.c_double()

        rc = lib.summa_py_get_parameter(
            i, name, len(name), transform, len(transform),
            C.byref(lo), C.byref(hi),
            C.byref(slo), C.byref(shi)
        )
        if rc:
            raise RuntimeError(f"Parameter metadata error: {i}")

        result.append((
            name.value.decode(), transform.value.decode(),
            lo.value, hi.value
        ))
    return result

def feasible(values):
    x = (C.c_double * len(values))(*values)
    accepted = C.c_int(0)
    msg.value = b""

    rc = lib.summa_py_check_feasibility(
        len(values), x, C.byref(accepted), msg, len(msg)
    )
    if rc:
        raise RuntimeError(
            f"Constraint checker error {rc}: {msg.value.decode()}"
        )

    return bool(accepted.value), msg.value.decode()

def evaluate(label, values):
    x = (C.c_double * len(values))(*values)
    scores = (C.c_double * 16)()
    nout = C.c_int(0)
    failed = C.c_int(1)
    msg.value = b""

    print(f"\nEvaluating {label}...", flush=True)

    rc = lib.summa_py_evaluate(
        len(values), x, 16, scores,
        C.byref(nout), C.byref(failed), msg, len(msg)
    )

    if rc or failed.value:
        raise RuntimeError(
            f"{label}: status={rc}, failed={failed.value}, "
            f"message={msg.value.decode()}"
        )

    result = [scores[i] for i in range(nout.value)]
    print(f"{label}: objectives = {result}", flush=True)

    if len(result) != 3 or not all(math.isfinite(v) for v in result):
        raise RuntimeError(f"{label}: invalid objective vector")

    return result

initialized = False
try:
    config = str(Path(args.config).resolve())
    rc = lib.summa_py_init(config.encode(), msg, len(msg))
    if rc:
        raise RuntimeError(f"Initialization {rc}: {msg.value.decode()}")

    initialized = True
    print("SUMMA INITIALIZED", flush=True)

    metadata = parameters()

    # Fixed midpoint candidate in PHYSICAL units.
    A = {}
    for name, transform, lo, hi in metadata:
        A[name] = math.sqrt(lo * hi) if transform == "log" \
                  else (lo + hi) / 2

    # Choose ordered soil parameters away from equal midpoints.
    A.update({
        "theta_res": 0.02,
        "critSoilWilting": 0.10,
        "critSoilTranspire": 0.20,
        "theta_sat": 0.55,
    })

    B = A.copy()
    B["frozenPrecipMultip"] *= 1.02
    B["qSurfScale"] *= 0.98

    names = [row[0] for row in metadata]
    a = [A[name] for name in names]
    b = [B[name] for name in names]

    # Record the exact physical candidate vectors.
    results_dir = Path(args.config).resolve().parent.parent / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    record = {
        "config": str(Path(args.config).resolve()),
        "parameters": [
            {
                "name": name,
                "transformation": transform,
                "lower": lo,
                "upper": hi,
                "A": A[name],
                "B": B[name],
            }
            for name, transform, lo, hi in metadata
        ],
        "A": a,
        "B": b,
    }

    for label, vector in (("A", a), ("B", b)):
        ok, detail = feasible(vector)
        print(f"{label} native feasibility: {ok} {detail}", flush=True)
        if not ok:
            raise RuntimeError(
                f"{label} was rejected by native constraints; "
                "no simulation performed"
            )

    result_a1 = evaluate("A1", a)
    result_b = evaluate("B", b)
    result_a2 = evaluate("A2", a)

    differences = [
        abs(x - y) for x, y in zip(result_a1, result_a2)
    ]

    print("\nA1:", result_a1, flush=True)
    print("B :", result_b, flush=True)
    print("A2:", result_a2, flush=True)
    print("Absolute A1-A2 differences:", differences, flush=True)

    assert all(d <= 1e-10 for d in differences), \
        "A-B-A reproducibility failed"

    print("A-B-A REPRODUCIBILITY: PASS", flush=True)

    record["objectives"] = {
        "A1": result_a1,
        "B": result_b,
        "A2": result_a2,
    }
    output = results_dir / "native_equivalence_vectors.json"
    output.write_text(json.dumps(record, indent=2) + "\n")
    print("Saved equivalence reference:", output, flush=True)

finally:
    rc = lib.summa_py_finalize()
    print("MPI finalization status:", rc, flush=True)
    if rc:
        raise RuntimeError(f"MPI finalization failed: {rc}")
