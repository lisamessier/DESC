import numpy as np
import pytest

from desc.equilibrium import Equilibrium
from desc.objectives import (
    ObjectiveFunction,
    GenericObjective,
    Energy,
    Volume,
    AspectRatio,
    ToroidalCurrent,
    QuasisymmetryBoozer,
    QuasisymmetryTwoTerm,
    QuasisymmetryTripleProduct,
    MercierStability,
    MagneticWell,
)
from desc.profiles import PowerSeriesProfile


class TestObjectiveFunction:
    """Test ObjectiveFunction classes."""

    @pytest.mark.unit
    def test_generic(self):
        """Test GenericObjective for arbitrary quantities."""

        def test(f, eq):
            obj = GenericObjective(f, eq=eq)
            kwargs = {
                "R_lmn": eq.R_lmn,
                "Z_lmn": eq.Z_lmn,
                "L_lmn": eq.L_lmn,
                "i_l": eq.i_l,
                "c_l": eq.c_l,
                "Psi": eq.Psi,
            }
            np.testing.assert_allclose(obj.compute(**kwargs), eq.compute(f)[f])

        test("sqrt(g)", Equilibrium())
        test("current", Equilibrium(iota=PowerSeriesProfile(0)))
        test("iota", Equilibrium(current=PowerSeriesProfile(0)))

    @pytest.mark.unit
    def test_volume(self):
        """Test calculation of plasma volume."""

        def test(eq):
            obj = Volume(target=10 * np.pi ** 2, weight=1 / np.pi ** 2, eq=eq)
            V = obj.compute(eq.R_lmn, eq.Z_lmn)
            np.testing.assert_allclose(V, 10)
            V_compute_scalar = obj.compute_scalar(eq.R_lmn, eq.Z_lmn)
            np.testing.assert_allclose(V_compute_scalar, 10)

        test(Equilibrium(iota=PowerSeriesProfile(0)))
        test(Equilibrium(current=PowerSeriesProfile(0)))

    @pytest.mark.unit
    def test_aspect_ratio(self):
        """Test calculation of aspect ratio."""

        def test(eq):
            obj = AspectRatio(target=5, weight=2, eq=eq)
            AR = obj.compute(eq.R_lmn, eq.Z_lmn)
            np.testing.assert_allclose(AR, 10)

        test(Equilibrium(iota=PowerSeriesProfile(0)))
        test(Equilibrium(current=PowerSeriesProfile(0)))

    @pytest.mark.unit
    def test_energy(self):
        """Test calculation of MHD energy."""

        def test(eq):
            obj = Energy(target=0, weight=(4 * np.pi * 1e-7), eq=eq)
            W = obj.compute(
                eq.R_lmn, eq.Z_lmn, eq.L_lmn, eq.p_l, eq.i_l, eq.c_l, eq.Psi
            )
            np.testing.assert_allclose(W, 10)

        test(Equilibrium(node_pattern="quad", iota=PowerSeriesProfile(0)))
        test(Equilibrium(node_pattern="quad", current=PowerSeriesProfile(0)))

    @pytest.mark.unit
    def test_toroidal_current(self):
        """Test calculation of toroidal current."""

        def test(eq):
            obj = ToroidalCurrent(target=1, weight=2, eq=eq)
            I = obj.compute(eq.R_lmn, eq.Z_lmn, eq.L_lmn, eq.i_l, eq.c_l, eq.Psi)
            np.testing.assert_allclose(I, -2)

        test(Equilibrium(iota=PowerSeriesProfile(0)))
        test(Equilibrium(current=PowerSeriesProfile(0)))

    @pytest.mark.unit
    def test_qs_boozer(self):
        """Test calculation of boozer qs metric."""

        def test(eq):
            obj = QuasisymmetryBoozer(eq=eq)
            fb = obj.compute(eq.R_lmn, eq.Z_lmn, eq.L_lmn, eq.i_l, eq.c_l, eq.Psi)
            np.testing.assert_allclose(fb, 0)

        test(Equilibrium(iota=PowerSeriesProfile(0)))
        test(Equilibrium(current=PowerSeriesProfile(0)))

    @pytest.mark.unit
    def test_qs_twoterm(self):
        """Test calculation of two term qs metric."""

        def test(eq):
            obj = QuasisymmetryTwoTerm(eq=eq)
            fc = obj.compute(eq.R_lmn, eq.Z_lmn, eq.L_lmn, eq.i_l, eq.c_l, eq.Psi)
            np.testing.assert_allclose(fc, 0)

        test(Equilibrium(iota=PowerSeriesProfile(0)))
        test(Equilibrium(current=PowerSeriesProfile(0)))

    @pytest.mark.unit
    def test_qs_tp(self):
        """Test calculation of triple product qs metric."""

        def test(eq):
            obj = QuasisymmetryTripleProduct(eq=eq)
            ft = obj.compute(eq.R_lmn, eq.Z_lmn, eq.L_lmn, eq.i_l, eq.c_l, eq.Psi)
            np.testing.assert_allclose(ft, 0)

        test(Equilibrium(iota=PowerSeriesProfile(0)))
        test(Equilibrium(current=PowerSeriesProfile(0)))

    @pytest.mark.unit
    def test_mercier_stability(self):
        """Test calculation of mercier stability criteria."""

        def test(eq):
            obj = MercierStability(eq=eq)
            DMerc = obj.compute(
                eq.R_lmn, eq.Z_lmn, eq.L_lmn, eq.p_l, eq.i_l, eq.c_l, eq.Psi
            )
            np.testing.assert_equal(len(DMerc), obj.grid.num_rho)
            np.testing.assert_allclose(DMerc, 0)

        test(Equilibrium(iota=PowerSeriesProfile(0)))
        test(Equilibrium(current=PowerSeriesProfile(0)))

    @pytest.mark.unit
    def test_magnetic_well(self):
        """Test calculation of magnetic well stability criteria."""

        def test(eq):
            obj = MagneticWell(eq=eq)
            magnetic_well = obj.compute(
                eq.R_lmn, eq.Z_lmn, eq.L_lmn, eq.p_l, eq.i_l, eq.c_l, eq.Psi
            )
            np.testing.assert_equal(len(magnetic_well), obj.grid.num_rho)
            np.testing.assert_allclose(magnetic_well, 0, atol=1e-15)

        test(Equilibrium(iota=PowerSeriesProfile(0)))
        test(Equilibrium(current=PowerSeriesProfile(0)))


@pytest.mark.unit
def test_derivative_modes():
    """Test equality of derivatives using batched and blocked methods."""
    eq = Equilibrium(M=2, N=1, L=2)
    obj1 = ObjectiveFunction(MagneticWell(), deriv_mode="batched", use_jit=False)
    obj2 = ObjectiveFunction(MagneticWell(), deriv_mode="blocked", use_jit=False)

    obj1.build(eq)
    obj2.build(eq)
    x = obj1.x(eq)
    g1 = obj1.grad(x)
    g2 = obj2.grad(x)
    np.testing.assert_allclose(g1, g2, atol=1e-10)
    J1 = obj1.jac(x)
    J2 = obj2.jac(x)
    np.testing.assert_allclose(J1, J2, atol=1e-10)
    H1 = obj1.hess(x)
    H2 = obj2.hess(x)
    np.testing.assert_allclose(np.diag(H1), np.diag(H2), atol=1e-10)
