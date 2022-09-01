import unittest
import numpy as np

from desc.backend import jnp
from desc.derivatives import AutoDiffDerivative, FiniteDiffDerivative

from numpy.random import default_rng


class TestDerivative(unittest.TestCase):
    """Tests Grid classes"""

    def test_finite_diff_vec(self):
        def test_fun(x, y, a):
            return x * y + a

        x = np.array([1, 5, 0.01, 200])
        y = np.array([60, 1, 100, 0.02])
        a = -2

        jac = FiniteDiffDerivative(test_fun, argnum=0)
        J = jac.compute(x, y, a)
        correct_J = np.diag(y)

        np.testing.assert_allclose(J, correct_J, atol=1e-8)

    def test_finite_diff_scalar(self):
        def test_fun(x, y, a):
            return np.dot(x, y) + a

        x = np.array([1, 5, 0.01, 200])
        y = np.array([60, 1, 100, 0.02])
        a = -2

        jac = FiniteDiffDerivative(test_fun, argnum=0)
        J = jac.compute(x, y, a)
        correct_J = y

        np.testing.assert_allclose(J, correct_J, atol=1e-8)

        jac.argnum = 1
        J = jac.compute(x, y, a)
        np.testing.assert_allclose(J, x, atol=1e-8)

    def test_auto_diff(self):
        def test_fun(x, y, a):
            return jnp.cos(x) + x * y + a

        x = np.array([1, 5, 0.01, 200])
        y = np.array([60, 1, 100, 0.02])
        a = -2

        jac = AutoDiffDerivative(test_fun, argnum=0)
        J = jac.compute(x, y, a)
        correct_J = np.diag(-np.sin(x) + y)

        np.testing.assert_allclose(J, correct_J, atol=1e-8)

    def test_compare_AD_FD(self):
        def test_fun(x, y, a):
            return jnp.cos(x) + x * y + a

        x = np.array([1, 5, 0.01, 200])
        y = np.array([60, 1, 100, 0.02])
        a = -2

        jac_AD = AutoDiffDerivative(test_fun, argnum=0)
        J_AD = jac_AD.compute(x, y, a)

        jac_FD = AutoDiffDerivative(test_fun, argnum=0)
        J_FD = jac_FD.compute(x, y, a)

        np.testing.assert_allclose(J_FD, J_AD, atol=1e-8)

    def test_fd_hessian(self):
        rando = default_rng(seed=0)

        n = 5
        A = rando.random((n, n))
        A = A + A.T
        g = rando.random(n)

        def f(x):
            return 5 + g.dot(x) + x.dot(1 / 2 * A.dot(x))

        hess = FiniteDiffDerivative(f, argnum=0, mode="hess")

        y = rando.random(n)
        A1 = hess(y)

        np.testing.assert_allclose(A1, A)

    def test_block_jacobian(self):
        rando = default_rng(seed=0)
        A = rando.random((19, 17))

        def fun(x):
            return jnp.dot(A, x)

        x = rando.random(17)

        jac = AutoDiffDerivative(fun, block_size=4, shape=A.shape)
        np.testing.assert_allclose(jac(x), A)
        jac = AutoDiffDerivative(fun, num_blocks=3, shape=A.shape)
        np.testing.assert_allclose(jac(x), A)


class TestJVP(unittest.TestCase):
    @staticmethod
    def fun(x, c1, c2):
        Amat = np.arange(12).reshape((4, 3))
        return jnp.dot(Amat, (x + c1 * c2) ** 3)

    x = np.ones(3).astype(float)
    c1 = np.arange(3).astype(float)
    c2 = np.arange(3).astype(float) + 2

    dx = np.array([1, 2, 3]).astype(float)
    dc1 = np.array([3, 4, 5]).astype(float)
    dc2 = np.array([-3, 1, -2]).astype(float)

    def test_autodiff_jvp(self):

        df = AutoDiffDerivative.compute_jvp(
            self.fun, 0, self.dx, self.x, self.c1, self.c2
        )
        np.testing.assert_allclose(df, np.array([1554.0, 4038.0, 6522.0, 9006.0]))
        df = AutoDiffDerivative.compute_jvp(
            self.fun, 1, self.dc1, self.x, self.c1, self.c2
        )
        np.testing.assert_allclose(df, np.array([10296.0, 26658.0, 43020.0, 59382.0]))
        df = AutoDiffDerivative.compute_jvp(
            self.fun, (0, 2), (self.dx, self.dc2), self.x, self.c1, self.c2
        )
        np.testing.assert_allclose(df, np.array([-342.0, -630.0, -918.0, -1206.0]))

    def test_finitediff_jvp(self):

        df = FiniteDiffDerivative.compute_jvp(
            self.fun, 0, self.dx, self.x, self.c1, self.c2
        )
        np.testing.assert_allclose(df, np.array([1554.0, 4038.0, 6522.0, 9006.0]))
        df = FiniteDiffDerivative.compute_jvp(
            self.fun, 1, self.dc1, self.x, self.c1, self.c2
        )
        np.testing.assert_allclose(df, np.array([10296.0, 26658.0, 43020.0, 59382.0]))
        df = FiniteDiffDerivative.compute_jvp(
            self.fun, (0, 2), (self.dx, self.dc2), self.x, self.c1, self.c2
        )
        np.testing.assert_allclose(df, np.array([-342.0, -630.0, -918.0, -1206.0]))

    def test_autodiff_jvp2(self):

        df = AutoDiffDerivative.compute_jvp2(
            self.fun, 0, 0, self.dx + 1, self.dx, self.x, self.c1, self.c2
        )
        np.testing.assert_allclose(df, np.array([1440.0, 3852.0, 6264.0, 8676.0]))
        df = AutoDiffDerivative.compute_jvp2(
            self.fun, 1, 1, self.dc1 + 1, self.dc1, self.x, self.c1, self.c2
        )
        np.testing.assert_allclose(
            df, np.array([56160.0, 147744.0, 239328.0, 330912.0])
        )
        df = AutoDiffDerivative.compute_jvp2(
            self.fun, 0, 2, self.dx, self.dc2, self.x, self.c1, self.c2
        )
        np.testing.assert_allclose(df, np.array([-1248.0, -3048.0, -4848.0, -6648.0]))
        df = AutoDiffDerivative.compute_jvp2(
            self.fun, 0, (1, 2), self.dx, (self.dc1, self.dc2), self.x, self.c1, self.c2
        )
        np.testing.assert_allclose(df, np.array([5808.0, 15564.0, 25320.0, 35076.0]))
        df = AutoDiffDerivative.compute_jvp2(
            self.fun,
            (1, 2),
            (1, 2),
            (self.dc1, self.dc2),
            (self.dc1, self.dc2),
            self.x,
            self.c1,
            self.c2,
        )
        np.testing.assert_allclose(df, np.array([22368.0, 63066.0, 103764.0, 144462.0]))
        df = AutoDiffDerivative.compute_jvp2(
            self.fun, 0, (1, 2), self.dx, (self.dc1, self.dc2), self.x, self.c1, self.c2
        )
        np.testing.assert_allclose(df, np.array([5808.0, 15564.0, 25320.0, 35076.0]))

    def test_finitediff_jvp2(self):

        df = FiniteDiffDerivative.compute_jvp2(
            self.fun, 0, 0, self.dx + 1, self.dx, self.x, self.c1, self.c2
        )
        np.testing.assert_allclose(df, np.array([1440.0, 3852.0, 6264.0, 8676.0]))
        df = FiniteDiffDerivative.compute_jvp2(
            self.fun, 1, 1, self.dc1 + 1, self.dc1, self.x, self.c1, self.c2
        )
        np.testing.assert_allclose(
            df, np.array([56160.0, 147744.0, 239328.0, 330912.0])
        )
        df = FiniteDiffDerivative.compute_jvp2(
            self.fun, 0, 2, self.dx, self.dc2, self.x, self.c1, self.c2
        )
        np.testing.assert_allclose(df, np.array([-1248.0, -3048.0, -4848.0, -6648.0]))
        df = FiniteDiffDerivative.compute_jvp2(
            self.fun, 0, (1, 2), self.dx, (self.dc1, self.dc2), self.x, self.c1, self.c2
        )
        np.testing.assert_allclose(df, np.array([5808.0, 15564.0, 25320.0, 35076.0]))
        df = FiniteDiffDerivative.compute_jvp2(
            self.fun,
            (1, 2),
            (1, 2),
            (self.dc1, self.dc2),
            (self.dc1, self.dc2),
            self.x,
            self.c1,
            self.c2,
        )
        np.testing.assert_allclose(df, np.array([22368.0, 63066.0, 103764.0, 144462.0]))
        df = FiniteDiffDerivative.compute_jvp2(
            self.fun, 0, (1, 2), self.dx, (self.dc1, self.dc2), self.x, self.c1, self.c2
        )
        np.testing.assert_allclose(df, np.array([5808.0, 15564.0, 25320.0, 35076.0]))

    def test_autodiff_jvp3(self):

        df = AutoDiffDerivative.compute_jvp3(
            self.fun, 0, 0, 0, self.dx + 1, self.dx, self.dx, self.x, self.c1, self.c2
        )
        np.testing.assert_allclose(df, np.array([504.0, 1404.0, 2304.0, 3204.0]))
        df = AutoDiffDerivative.compute_jvp3(
            self.fun, 0, 1, 1, self.dx, self.dc1 + 1, self.dc1, self.x, self.c1, self.c2
        )
        np.testing.assert_allclose(df, np.array([19440.0, 52704.0, 85968.0, 119232.0]))
        df = AutoDiffDerivative.compute_jvp3(
            self.fun, 0, 1, 2, self.dx, self.dc1, self.dc2, self.x, self.c1, self.c2
        )
        np.testing.assert_allclose(
            df, np.array([-5784.0, -14118.0, -22452.0, -30786.0])
        )
        df = AutoDiffDerivative.compute_jvp3(
            self.fun,
            0,
            0,
            (1, 2),
            self.dx,
            self.dx,
            (self.dc1, self.dc2),
            self.x,
            self.c1,
            self.c2,
        )
        np.testing.assert_allclose(df, np.array([2040.0, 5676.0, 9312.0, 12948.0]))
        df = AutoDiffDerivative.compute_jvp3(
            self.fun,
            (1, 2),
            (1, 2),
            (1, 2),
            (self.dc1, self.dc2),
            (self.dc1, self.dc2),
            (self.dc1, self.dc2),
            self.x,
            self.c1,
            self.c2,
        )
        np.testing.assert_allclose(
            df, np.array([-33858.0, -55584.0, -77310.0, -99036.0])
        )

    def test_finitediff_jvp3(self):

        df = FiniteDiffDerivative.compute_jvp3(
            self.fun, 0, 0, 0, self.dx + 1, self.dx, self.dx, self.x, self.c1, self.c2
        )
        np.testing.assert_allclose(
            df, np.array([504.0, 1404.0, 2304.0, 3204.0]), rtol=1e-4
        )
        df = FiniteDiffDerivative.compute_jvp3(
            self.fun, 0, 1, 1, self.dx, self.dc1 + 1, self.dc1, self.x, self.c1, self.c2
        )
        np.testing.assert_allclose(
            df, np.array([19440.0, 52704.0, 85968.0, 119232.0]), rtol=1e-4
        )
        df = FiniteDiffDerivative.compute_jvp3(
            self.fun, 0, 1, 2, self.dx, self.dc1, self.dc2, self.x, self.c1, self.c2
        )
        np.testing.assert_allclose(
            df, np.array([-5784.0, -14118.0, -22452.0, -30786.0]), rtol=1e-4
        )
        df = FiniteDiffDerivative.compute_jvp3(
            self.fun,
            0,
            0,
            (1, 2),
            self.dx,
            self.dx,
            (self.dc1, self.dc2),
            self.x,
            self.c1,
            self.c2,
        )
        np.testing.assert_allclose(
            df, np.array([2040.0, 5676.0, 9312.0, 12948.0]), rtol=1e-4
        )
        df = FiniteDiffDerivative.compute_jvp3(
            self.fun,
            (1, 2),
            (1, 2),
            (1, 2),
            (self.dc1, self.dc2),
            (self.dc1, self.dc2),
            (self.dc1, self.dc2),
            self.x,
            self.c1,
            self.c2,
        )
        np.testing.assert_allclose(
            df, np.array([-33858.0, -55584.0, -77310.0, -99036.0]), rtol=1e-4
        )


def test_jac_looped():

    from numpy.random import default_rng

    rng = default_rng(seed=0)
    A = rng.random((10, 20))
    x = rng.random(20)

    def fun(x):
        y = A @ x
        y = y ** 2
        return A @ jnp.concatenate([y, y])

    J1 = AutoDiffDerivative(fun, mode="fwd")(x)
    J2 = AutoDiffDerivative(fun, mode="looped")(x)
    np.testing.assert_allclose(J1, J2)
