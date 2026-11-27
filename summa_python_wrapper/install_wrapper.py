#!/usr/bin/env python3
"""
Install the PR675 SUMMA Python Fortran API into a SUMMA source checkout.

This script copies summa_python_api.f90 and updates the required CMake
source list and MPI linkage. It does not build SUMMA or install Python packages.

Usage:
    python install_wrapper.py --summa-source /path/to/summa
    python install_wrapper.py --summa-source /path/to/summa --apply

The default is a dry run. Use --apply to modify the SUMMA checkout.
Existing CMake entries are not duplicated. Review the changes with git diff
and rebuild libsumma.so after installation.
"""

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
API = ROOT / "fortran_api/summa_python_api.f90"
API_ENTRY = "    ${DRIVER_DIR}/python_api/summa_python_api.f90"
API_ANCHOR = "    ${DRIVER_DIR}/summa_spinup.f90"

MPI_LINK = "target_link_libraries(summa PRIVATE PARALLEL_UTILS MPI::MPI_Fortran)"
MPI_ANCHOR = (
    "  target_link_libraries(summa PUBLIC SUMMA_TYPES "
    "${EXT_TARGETS} SUMMA_NOAHMP SUMMA_COMM ${LIBRARY_LINKS})"
)
MPI_ADDITION = (
    "\n  # Python API: MPI linkage for independent model workers\n"
    "  if (USE_MPI)\n"
    f"    {MPI_LINK}\n"
    "  endif()\n"
)


def insert_once(text, entry, anchor, addition):
    """Insert a missing CMake entry at one verified location."""
    if entry in text:
        return text
    if text.count(anchor) != 1:
        raise ValueError(f"Cannot safely locate CMake anchor: {anchor}")
    return text.replace(anchor, addition + anchor, 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summa-source", required=True, type=Path)
    parser.add_argument("--apply", action="store_true",
                        help="Apply changes; otherwise only validate")
    args = parser.parse_args()

    summa = args.summa_source.expanduser().resolve()
    destination = summa / "build/source/driver/python_api/summa_python_api.f90"
    source_cmake = summa / "build/source/CMakeLists.txt"
    root_cmake = summa / "build/CMakeLists.txt"

    # Validate the API and both CMake files before writing anything.
    for file in (API, source_cmake, root_cmake):
        if not file.is_file():
            parser.error(f"Missing required file: {file}")

    if "SUMMA_PY_API_PR675" not in API.read_text():
        parser.error("API is missing the expected PR675 identifier")

    try:
        source_old = source_cmake.read_text()
        root_old = root_cmake.read_text()
        source_new = insert_once(
            source_old, API_ENTRY, API_ANCHOR, API_ENTRY + "\n"
        )
        root_new = insert_once(
            root_old, MPI_LINK, MPI_ANCHOR, MPI_ADDITION
        )
    except ValueError as exc:
        parser.error(str(exc))

    print(f"SUMMA source: {summa}")
    print(f"Fortran API:   {destination}")
    print(f"Source CMake:  {'UPDATE' if source_new != source_old else 'OK'}")
    print(f"Root CMake:    {'UPDATE' if root_new != root_old else 'OK'}")

    if not args.apply:
        print("DRY RUN: no files modified. Add --apply to install.")
        return

    # Install only after successful validation.
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(API, destination)
    if source_new != source_old:
        source_cmake.write_text(source_new)
    if root_new != root_old:
        root_cmake.write_text(root_new)

    print("Installation complete. Review git diff and rebuild SUMMA.")


if __name__ == "__main__":
    main()
