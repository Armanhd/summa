
#!/usr/bin/env python3
"""MPI-launched persistent JSON-line service for SUMMA's validated ctypes API.

Start using: mpirun -np 1 python -u summa_ray_worker.py ...
Fortran/MPI output can interleave with stdout. Protocol replies are prefixed.
"""

import argparse
import json
import sys
import traceback
from pathlib import Path

PREFIX = "@@SUMMA_JSON@@"


def reply(value):
    print(PREFIX + json.dumps(value, allow_nan=True), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--library", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--dds-script", required=True)
    args = parser.parse_args()

    sys.path.insert(
        0,
        str(Path(args.dds_script).resolve().parent)
    )

    from dds_optimiser import SummaWorker

    worker = SummaWorker(args.library)

    try:
        worker.initialise(args.config)

        reply({
            "ok": True,
            "ready": True,
            "parameters": worker.parameters,
        })

        for raw in sys.stdin:
            if not raw.strip():
                continue

            try:
                msg = json.loads(raw)
                action = msg["action"]

                if action == "evaluate":
                    response = worker.evaluate(
                        msg["physical"]
                    )

                elif action == "feasible":
                    response = {
                        "feasible": worker.feasible(
                            msg["physical"]
                        )
                    }

                elif action == "defaults":
                    response = {
                        "defaults": worker.get_defaults()
                    }

                elif action == "metadata":
                    response = {
                        "parameters": worker.parameters
                    }

                elif action == "output_open":
                    worker.output_open(
                        msg["path"],
                        msg["n_trials"],
                    )
                    response = {"written": True}

                elif action == "output_write":
                    from datetime import datetime

                    worker.output_write(
                        msg["trial"],
                        msg["physical"],
                        msg["result"],
                        datetime.fromisoformat(msg["start"]),
                        datetime.fromisoformat(msg["end"]),
                    )
                    response = {"written": True}

                elif action == "output_close":
                    worker.output_close()
                    response = {"closed": True}

                elif action == "export_best":
                    worker.export_best(
                        msg["path"],
                        msg["trial"],
                        msg["physical"],
                    )
                    response = {"exported": True}

                elif action == "stop":
                    reply({
                        "ok": True,
                        "stopped": True,
                    })
                    break

                else:
                    raise ValueError(
                        f"Unknown action: {action}"
                    )

                reply({
                    "ok": True,
                    "response": response,
                })

            except Exception as exc:
                reply({
                    "ok": False,
                    "error": repr(exc),
                    "traceback": traceback.format_exc(),
                })

    except Exception as exc:
        reply({
            "ok": False,
            "fatal": True,
            "error": repr(exc),
            "traceback": traceback.format_exc(),
        })
        raise

    finally:
        worker.finalize()


if __name__ == "__main__":
    main()
