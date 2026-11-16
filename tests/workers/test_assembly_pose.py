import unittest
import numpy as np
from assembly_pose import shortest_up_rotation


class PoseTests(unittest.TestCase):
    def test_shortest_rotation_levels_without_an_unrequested_half_turn(self):
        angle=np.deg2rad(16);normal=[0,np.cos(angle),np.sin(angle)];r=shortest_up_rotation(normal)
        np.testing.assert_allclose(r@normal,[0,1,0],atol=1e-12)
        np.testing.assert_allclose(r@[1,0,0],[1,0,0],atol=1e-12)
        self.assertAlmostEqual(np.arccos((np.trace(r)-1)/2),angle,places=12)

    def test_identity_and_oblique_rotations_are_proper_and_rigid(self):
        np.testing.assert_allclose(shortest_up_rotation([0,1,0]),np.eye(3),atol=1e-12)
        for normal in([.1,1,.2],[-.3,1,-.1]):
            r=shortest_up_rotation(normal);np.testing.assert_allclose(r.T@r,np.eye(3),atol=1e-12)
            self.assertAlmostEqual(np.linalg.det(r),1,places=12)
            np.testing.assert_allclose(r@(np.array(normal)/np.linalg.norm(normal)),[0,1,0],atol=1e-12)

    def test_undefined_or_downward_normal_refused(self):
        for normal in([0,0,0],[0,-1,0],[float('nan'),1,0]):
            with self.assertRaises(ValueError):shortest_up_rotation(normal)


if __name__=='__main__':unittest.main()
