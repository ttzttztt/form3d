"""Verify the actual CPU FPS algorithm against independent greedy invariants."""
import unittest
import numpy as np
import pytest
torch = pytest.importorskip("torch")
from holopart_runtime import fps


class FPSTests(unittest.TestCase):
    def test_greedy_choices_maximize_nearest_selected_distance(self):
        points=np.random.default_rng(47).normal(size=(50,3)).astype(np.float32)
        chosen=fps(torch.from_numpy(points),ratio=.4,random_start=False).numpy()
        self.assertEqual(len(chosen),20);self.assertEqual(chosen[0],0)
        for k,index in enumerate(chosen[1:],1):
            distance=np.min(np.sum((points[:,None]-points[chosen[:k]])**2,axis=2),axis=1)
            self.assertAlmostEqual(float(distance[index]),float(distance.max()),places=5)

    def test_batches_use_global_indices_and_round_count_up(self):
        points=torch.tensor([[0.,0],[10,0],[1,0],[11,0],[3,0],[20,0]])
        result=fps(points,torch.tensor([0,1,0,1,0,1]),ratio=.5,random_start=False)
        self.assertEqual(result.tolist(),[0,4,1,5])

    def test_duplicate_positions_are_not_repeated_indices(self):
        result=fps(torch.zeros(5,3),ratio=1,random_start=False)
        self.assertEqual(len(set(result.tolist())),5)

    def test_nonfinite_and_invalid_ratios_are_refused(self):
        for ratio in(0,-1,1.1):
            with self.assertRaises(ValueError):fps(torch.ones(2,3),ratio=ratio)
        with self.assertRaises(ValueError):fps(torch.tensor([[float('nan'),0.]]))


if __name__=='__main__':unittest.main()
