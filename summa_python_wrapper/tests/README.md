# Wrapper checks

Run the non-SUMMA CMA-ES regression test:

```bash
python -m unittest discover -s summa_python_wrapper/tests -v
```

The existing native integration diagnostics remain in `python_wrapper/`:
`test_pr675_init.py`, `test_pr675_parameters.py`, and `test_pr675_evaluate.py`.
They require a compiled compatible `libsumma.so`, valid basin configuration, and
the appropriate FIR modules; they are not suitable for ordinary CI without the model runtime.

The regression test verifies the 30 + 20 candidate partial-generation path used
by CMA2 (5000 evaluations, population 30) without executing 5000 simulations.
