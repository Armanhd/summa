#!/usr/bin/env python3
"""Regression smoke test: CMA-ES accepts a final partial generation.

Run with: python -m unittest discover -s summa_python_wrapper/tests -v
Does not load SUMMA or submit Slurm jobs.
"""
import unittest

import cma
import numpy as np


class TestCmaPartialGeneration(unittest.TestCase):
    def test_population_30_budget_50(self):
        optimizer = cma.CMAEvolutionStrategy(
            np.full(4, 0.5), 0.3,
            {"bounds": [0.0, 1.0], "popsize": 30,
             "seed": 42, "verbose": -9, "verb_disp": 0},
        )
        counts = []
        evaluated = 0
        budget = 50
        while evaluated < budget:
            population = optimizer.ask(number=min(30, budget - evaluated))
            scores = [float(np.sum((np.asarray(x) - 0.25)**2))
                      for x in population]
            optimizer.tell(population, scores)
            evaluated += len(population)
            counts.append(len(population))
        self.assertEqual(counts, [30, 20])
        self.assertEqual(evaluated, budget)


if __name__ == "__main__":
    unittest.main()
