"""Tests for objective functions.

These generally don't test the accuracy of the computation for realistic examples,
that is done in test_compute_functions or regression tests.

This module primarily tests the constructing/building/calling methods.
"""

import numpy as np
import pytest
from scipy.constants import mu_0

from desc.equilibrium import Equilibrium
from desc.examples import get
from desc.objectives import (
    AspectRatio,
    Elongation,
    Energy,
    GenericObjective,
    MagneticWell,
    MercierStability,
    ObjectiveFunction,
    QuasisymmetryBoozer,
    QuasisymmetryTripleProduct,
    QuasisymmetryTwoTerm,
    RotationalTransform,
    ToroidalCurrent,
    Volume,
)
from desc.objectives.objective_funs import _Objective
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
            np.testing.assert_allclose(
                obj.compute(**kwargs),
                eq.compute(f, grid=obj.grid)[f] * obj.grid.weights,
            )

        test("sqrt(g)", Equilibrium())
        test("current", Equilibrium(iota=PowerSeriesProfile(0)))
        test("iota", Equilibrium(current=PowerSeriesProfile(0)))

    @pytest.mark.unit
    def test_volume(self):
        """Test calculation of plasma volume."""

        def test(eq):
            obj = Volume(
                target=10 * np.pi**2, weight=1 / np.pi**2, eq=eq, normalize=False
            )
            V = obj.compute(eq.R_lmn, eq.Z_lmn)
            V_scaled = obj.compute_scaled(eq.R_lmn, eq.Z_lmn)
            V_scalar = obj.compute_scalar(eq.R_lmn, eq.Z_lmn)
            np.testing.assert_allclose(V, 20 * np.pi**2)
            np.testing.assert_allclose(V_scaled, 10)
            np.testing.assert_allclose(V_scalar, 10)

        test(Equilibrium(iota=PowerSeriesProfile(0)))
        test(Equilibrium(current=PowerSeriesProfile(0)))

    @pytest.mark.unit
    def test_aspect_ratio(self):
        """Test calculation of aspect ratio."""

        def test(eq):
            obj = AspectRatio(target=5, weight=1, eq=eq)
            AR = obj.compute(eq.R_lmn, eq.Z_lmn)
            AR_scaled = obj.compute_scaled(eq.R_lmn, eq.Z_lmn)
            np.testing.assert_allclose(AR, 10)
            np.testing.assert_allclose(AR_scaled, 5)

        test(Equilibrium(iota=PowerSeriesProfile(0)))
        test(Equilibrium(current=PowerSeriesProfile(0)))

    @pytest.mark.unit
    def test_elongation(self):
        """Test calculation of elongation."""

        def test(eq):
            obj = Elongation(target=0, weight=2, eq=eq)
            f = obj.compute(eq.R_lmn, eq.Z_lmn)
            f_scaled = obj.compute_scaled(eq.R_lmn, eq.Z_lmn)
            np.testing.assert_allclose(f, 1.3 / 0.7, rtol=5e-3)
            np.testing.assert_allclose(f_scaled, 2 * (1.3 / 0.7), rtol=5e-3)

        test(get("HELIOTRON"))

    @pytest.mark.unit
    def test_energy(self):
        """Test calculation of MHD energy."""

        def test(eq):
            obj = Energy(target=0, weight=mu_0, eq=eq, normalize=False)
            W = obj.compute(*obj.xs(eq))
            W_scaled = obj.compute_scaled(*obj.xs(eq))
            np.testing.assert_allclose(W, 10 / mu_0)
            np.testing.assert_allclose(W_scaled, 10)

        test(Equilibrium(node_pattern="quad", iota=PowerSeriesProfile(0)))
        test(Equilibrium(node_pattern="quad", current=PowerSeriesProfile(0)))

    @pytest.mark.unit
    def test_target_iota(self):
        """Test calculation of iota profile."""

        def test(eq):
            obj = RotationalTransform(target=1, weight=2, eq=eq)
            iota = obj.compute(*obj.xs(eq))
            iota_scaled = obj.compute_scaled(*obj.xs(eq))
            np.testing.assert_allclose(iota, 0)
            np.testing.assert_allclose(iota_scaled, -2 / 3)

        test(Equilibrium(iota=PowerSeriesProfile(0)))
        test(Equilibrium(current=PowerSeriesProfile(0)))

    @pytest.mark.unit
    def test_toroidal_current(self):
        """Test calculation of toroidal current."""

        def test(eq):
            obj = ToroidalCurrent(target=1, weight=2, eq=eq, normalize=False)
            I = obj.compute(*obj.xs(eq))
            I_scaled = obj.compute_scaled(*obj.xs(eq))
            np.testing.assert_allclose(I, 0)
            np.testing.assert_allclose(I_scaled, -2 / 3)

        test(Equilibrium(iota=PowerSeriesProfile(0)))
        test(Equilibrium(current=PowerSeriesProfile(0)))

    @pytest.mark.unit
    def test_qs_boozer(self):
        """Test calculation of boozer qs metric."""

        def test(eq):
            obj = QuasisymmetryBoozer(eq=eq)
            fb = obj.compute(*obj.xs(eq))
            np.testing.assert_allclose(fb, 0, atol=1e-12)

        test(Equilibrium(L=2, M=2, N=1, iota=PowerSeriesProfile(0)))
        test(Equilibrium(L=2, M=2, N=1, current=PowerSeriesProfile(0)))

    @pytest.mark.unit
    def test_qs_twoterm(self):
        """Test calculation of two term qs metric."""

        def test(eq):
            obj = QuasisymmetryTwoTerm(eq=eq)
            fc = obj.compute(*obj.xs(eq))
            np.testing.assert_allclose(fc, 0)

        test(Equilibrium(iota=PowerSeriesProfile(0)))
        test(Equilibrium(current=PowerSeriesProfile(0)))

    @pytest.mark.unit
    def test_qs_tp(self):
        """Test calculation of triple product qs metric."""

        def test(eq):
            obj = QuasisymmetryTripleProduct(eq=eq)
            ft = obj.compute(*obj.xs(eq))
            np.testing.assert_allclose(ft, 0)

        test(Equilibrium(iota=PowerSeriesProfile(0)))
        test(Equilibrium(current=PowerSeriesProfile(0)))

    @pytest.mark.unit
    def test_mercier_stability(self):
        """Test calculation of mercier stability criteria."""

        def test(eq):
            obj = MercierStability(eq=eq)
            DMerc = obj.compute(*obj.xs(eq))
            np.testing.assert_equal(len(DMerc), obj.grid.num_rho)
            np.testing.assert_allclose(DMerc, 0)

        test(Equilibrium(iota=PowerSeriesProfile(0)))
        test(Equilibrium(current=PowerSeriesProfile(0)))

    @pytest.mark.unit
    def test_magnetic_well(self):
        """Test calculation of magnetic well stability criteria."""

        def test(eq):
            obj = MagneticWell(eq=eq)
            magnetic_well = obj.compute(*obj.xs(eq))
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


@pytest.mark.unit
def test_rejit():
    """Test that updating attributes and recompiling correctly updates."""

    class DummyObjective(_Objective):
        def __init__(self, y, eq=None, target=0, weight=1, name="dummy"):
            self.y = y
            super().__init__(eq=eq, target=target, weight=weight, name=name)

        def build(self, eq, use_jit=True, verbose=1):
            self._dim_f = 1
            super().build(eq, use_jit, verbose)

        def compute(self, R_lmn):
            return self.y * R_lmn**3

    objective = DummyObjective(3.0)
    eq = Equilibrium()
    objective.build(eq)
    assert objective.compute(4.0) == 192.0
    objective.target = 1.0
    objective.weight = 2.0
    assert objective.compute(4.0) == 192.0
    objective.jit()
    assert objective.compute(4.0) == 194.0

    objective2 = ObjectiveFunction(objective)
    objective2.build(eq)
    x = objective2.x(eq)

    z = objective2.compute(x)
    J = objective2.jac(x)
    assert z[0] == 3002.0
    objective2.objectives[0].target = 3.0
    objective2.objectives[0].weight = 4.0
    objective2.objectives[0].y = 2.0
    assert objective2.compute(x)[0] == 3002.0
    np.testing.assert_allclose(objective2.jac(x), J)
    objective2.jit()
    assert objective2.compute(x)[0] == 2012.0
    np.testing.assert_allclose(objective2.jac(x), J / 3 * 2)


@pytest.mark.unit
def test_generic_compute():
    """Test for gh issue #388."""
    eq = Equilibrium()
    obj = ObjectiveFunction(AspectRatio(target=2, weight=1), eq=eq)
    a1 = obj.compute_scalar(obj.x(eq))
    obj = ObjectiveFunction(GenericObjective("R0/a", target=2, weight=1), eq=eq)
    a2 = obj.compute_scalar(obj.x(eq))
    assert np.allclose(a1, a2)


@pytest.mark.unit
def test_target_bounds():
    """Test that tuple targets are in the format (lower bound, upper bound)."""
    eq = Equilibrium()
    with pytest.raises(AssertionError):
        _ = GenericObjective("R", target=(1,), eq=eq)
    with pytest.raises(AssertionError):
        _ = GenericObjective("R", target=(1, 2, 3), eq=eq)
    with pytest.raises(ValueError):
        _ = GenericObjective("R", target=(1, -1), eq=eq)


# TODO: add test for _Objective.compute_scaled


@pytest.mark.unit
def test_target_profiles():
    """Tests for using Profile objects as targets for profile objectives."""
    iota = PowerSeriesProfile([1, 0, -0.3])
    current = PowerSeriesProfile([4, 0, 1, 0, -1])
    eqi = Equilibrium(L=5, N=3, M=3, iota=iota)
    eqc = Equilibrium(L=3, N=3, M=3, current=current)
    obji = RotationalTransform(target=iota)
    obji.build(eqc)
    np.testing.assert_allclose(
        obji.target, iota(obji.grid.nodes[obji.grid.unique_rho_idx])
    )
    objc = ToroidalCurrent(target=current)
    objc.build(eqi)
    np.testing.assert_allclose(
        objc.target, current(objc.grid.nodes[objc.grid.unique_rho_idx])
    )
