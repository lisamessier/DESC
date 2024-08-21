"""Tests for Mercier stability functions."""

import numpy as np
import pytest
from netCDF4 import Dataset
from scipy.interpolate import interp1d

import desc.examples
import desc.io
from desc.backend import eigvals, jnp
from desc.compute.utils import cross, dot
from desc.equilibrium import Equilibrium
from desc.grid import LinearGrid
from desc.objectives import MagneticWell, MercierStability

DEFAULT_RANGE = (0.05, 1)
DEFAULT_RTOL = 1e-2
DEFAULT_ATOL = 1e-6
MAX_SIGN_DIFF = 5


def assert_all_close(
    y1, y2, rho, rho_range=DEFAULT_RANGE, rtol=DEFAULT_RTOL, atol=DEFAULT_ATOL
):
    """Test that the values of y1 and y2, over a given range are close enough.

    Parameters
    ----------
    y1 : ndarray
        values to compare
    y2 : ndarray
        values to compare
    rho : ndarray
        rho values
    rho_range : (float, float)
        the range of rho values to compare
    rtol : float
        relative tolerance
    atol : float
        absolute tolerance

    """
    minimum, maximum = rho_range
    interval = (minimum < rho) & (rho < maximum)
    np.testing.assert_allclose(y1[interval], y2[interval], rtol=rtol, atol=atol)


def get_vmec_data(path, quantity):
    """Get data from a VMEC wout.nc file.

    Parameters
    ----------
    path : str
        Path to VMEC file.
    quantity: str
        Name of the quantity to return.

    Returns
    -------
    rho : ndarray
        Radial coordinate.
    q : ndarray
        Variable from VMEC output.

    """
    f = Dataset(path)
    rho = np.sqrt(f.variables["phi"] / np.array(f.variables["phi"])[-1])
    q = np.array(f.variables[quantity])
    f.close()
    return rho, q


@pytest.mark.unit
def test_mercier_vacuum():
    """Test that the Mercier stability criteria are 0 without pressure."""
    eq = Equilibrium()
    data = eq.compute(["D_shear", "D_current", "D_well", "D_geodesic", "D_Mercier"])
    np.testing.assert_allclose(data["D_shear"], 0)
    np.testing.assert_allclose(data["D_current"], 0)
    np.testing.assert_allclose(data["D_well"], 0)
    np.testing.assert_allclose(data["D_geodesic"], 0)
    np.testing.assert_allclose(data["D_Mercier"], 0)


@pytest.mark.unit
def test_compute_d_shear():
    """Test that D_shear has a stabilizing effect and matches VMEC."""

    def test(eq, vmec, rho_range=(0, 1), rtol=1e-12, atol=0.0):
        rho, d_shear_vmec = get_vmec_data(vmec, "DShear")
        grid = LinearGrid(M=eq.M_grid, N=eq.N_grid, NFP=eq.NFP, sym=eq.sym, rho=rho)
        d_shear = grid.compress(eq.compute("D_shear", grid=grid)["D_shear"])

        assert np.all(
            d_shear[bool(grid.axis.size) :] >= 0
        ), "D_shear should always have a stabilizing effect."
        assert_all_close(d_shear, d_shear_vmec, rho, rho_range, rtol, atol)

    test(
        desc.examples.get("DSHAPE_CURRENT"),
        ".//tests//inputs//wout_DSHAPE.nc",
        (0.3, 0.9),
        atol=0.01,
        rtol=0.1,
    )
    test(desc.examples.get("HELIOTRON"), ".//tests//inputs//wout_HELIOTRON.nc")


@pytest.mark.unit
def test_compute_d_current():
    """Test calculation of D_current stability criterion against VMEC."""

    def test(eq, vmec, rho_range=DEFAULT_RANGE, rtol=DEFAULT_RTOL, atol=DEFAULT_ATOL):
        rho, d_current_vmec = get_vmec_data(vmec, "DCurr")
        grid = LinearGrid(M=eq.M_grid, N=eq.N_grid, NFP=eq.NFP, sym=eq.sym, rho=rho)
        d_current = grid.compress(eq.compute("D_current", grid=grid)["D_current"])

        assert (
            np.nonzero(np.sign(d_current) != np.sign(d_current_vmec))[0].size
            <= MAX_SIGN_DIFF
        )
        assert_all_close(d_current, d_current_vmec, rho, rho_range, rtol, atol)

    test(
        desc.examples.get("DSHAPE_CURRENT"),
        ".//tests//inputs//wout_DSHAPE.nc",
        (0.3, 0.9),
        rtol=1e-1,
        atol=1e-2,
    )
    test(
        desc.examples.get("HELIOTRON"),
        ".//tests//inputs//wout_HELIOTRON.nc",
        (0.25, 0.85),
        rtol=1e-1,
    )


@pytest.mark.unit
def test_compute_d_well():
    """Test calculation of D_well stability criterion against VMEC."""

    def test(eq, vmec, rho_range=DEFAULT_RANGE, rtol=DEFAULT_RTOL, atol=DEFAULT_ATOL):
        rho, d_well_vmec = get_vmec_data(vmec, "DWell")
        grid = LinearGrid(M=eq.M_grid, N=eq.N_grid, NFP=eq.NFP, sym=eq.sym, rho=rho)
        d_well = grid.compress(eq.compute("D_well", grid=grid)["D_well"])

        assert (
            np.nonzero(np.sign(d_well) != np.sign(d_well_vmec))[0].size <= MAX_SIGN_DIFF
        )
        assert_all_close(d_well, d_well_vmec, rho, rho_range, rtol, atol)

    test(
        desc.examples.get("DSHAPE_CURRENT"),
        ".//tests//inputs//wout_DSHAPE.nc",
        (0.3, 0.9),
        rtol=1e-1,
    )
    test(
        desc.examples.get("HELIOTRON"),
        ".//tests//inputs//wout_HELIOTRON.nc",
        (0.01, 0.45),
        rtol=1.75e-1,
    )
    test(
        desc.examples.get("HELIOTRON"),
        ".//tests//inputs//wout_HELIOTRON.nc",
        (0.45, 0.6),
        atol=7.2e-1,
    )
    test(
        desc.examples.get("HELIOTRON"),
        ".//tests//inputs//wout_HELIOTRON.nc",
        (0.6, 0.99),
        rtol=2e-2,
    )


@pytest.mark.unit
def test_compute_d_geodesic():
    """Test that D_geodesic has a destabilizing effect and matches VMEC."""

    def test(eq, vmec, rho_range=DEFAULT_RANGE, rtol=DEFAULT_RTOL, atol=DEFAULT_ATOL):
        rho, d_geodesic_vmec = get_vmec_data(vmec, "DGeod")
        grid = LinearGrid(M=eq.M_grid, N=eq.N_grid, NFP=eq.NFP, sym=eq.sym, rho=rho)
        d_geodesic = grid.compress(eq.compute("D_geodesic", grid=grid)["D_geodesic"])

        assert np.all(
            d_geodesic[bool(grid.axis.size) :] <= 0
        ), "D_geodesic should always have a destabilizing effect."
        assert_all_close(d_geodesic, d_geodesic_vmec, rho, rho_range, rtol, atol)

    test(
        desc.examples.get("DSHAPE_CURRENT"),
        ".//tests//inputs//wout_DSHAPE.nc",
        (0.3, 0.9),
        rtol=1e-1,
    )
    test(
        desc.examples.get("HELIOTRON"),
        ".//tests//inputs//wout_HELIOTRON.nc",
        (0.15, 0.825),
        rtol=1.2e-1,
    )
    test(
        desc.examples.get("HELIOTRON"),
        ".//tests//inputs//wout_HELIOTRON.nc",
        (0.85, 0.95),
        atol=1.2e-1,
    )


@pytest.mark.unit
def test_compute_d_mercier():
    """Test calculation of D_Mercier stability criterion against VMEC."""

    def test(eq, vmec, rho_range=DEFAULT_RANGE, rtol=DEFAULT_RTOL, atol=DEFAULT_ATOL):
        rho, d_mercier_vmec = get_vmec_data(vmec, "DMerc")
        grid = LinearGrid(M=eq.M_grid, N=eq.N_grid, NFP=eq.NFP, sym=eq.sym, rho=rho)
        d_mercier = grid.compress(eq.compute("D_Mercier", grid=grid)["D_Mercier"])

        assert (
            np.nonzero(np.sign(d_mercier) != np.sign(d_mercier_vmec))[0].size
            <= MAX_SIGN_DIFF
        )
        assert_all_close(d_mercier, d_mercier_vmec, rho, rho_range, rtol, atol)

    test(
        desc.examples.get("DSHAPE_CURRENT"),
        ".//tests//inputs//wout_DSHAPE.nc",
        (0.3, 0.9),
        rtol=1e-1,
        atol=1e-2,
    )
    test(
        desc.examples.get("HELIOTRON"),
        ".//tests//inputs//wout_HELIOTRON.nc",
        (0.1, 0.325),
        rtol=1.3e-1,
    )
    test(
        desc.examples.get("HELIOTRON"),
        ".//tests//inputs//wout_HELIOTRON.nc",
        (0.325, 0.95),
        rtol=5e-2,
    )


@pytest.mark.unit
def test_compute_magnetic_well():
    """Test that D_well and magnetic_well match signs under finite pressure."""

    def test(eq, rho=np.linspace(0, 1, 128)):
        grid = LinearGrid(M=eq.M_grid, N=eq.N_grid, NFP=eq.NFP, sym=eq.sym, rho=rho)
        d_well = grid.compress(eq.compute("D_well", grid=grid)["D_well"])
        magnetic_well = grid.compress(
            eq.compute("magnetic well", grid=grid)["magnetic well"]
        )
        assert (
            np.nonzero(np.sign(d_well) != np.sign(magnetic_well))[0].size
            <= MAX_SIGN_DIFF
        )

    test(desc.examples.get("DSHAPE_CURRENT"))
    test(desc.examples.get("HELIOTRON"))


@pytest.mark.unit
def test_mercier_print(capsys):
    """Test that the Mercier stability criteria prints correctly."""
    eq = Equilibrium()
    grid = LinearGrid(L=10, M=10, N=5, axis=False)

    Dmerc = eq.compute("D_Mercier", grid=grid)["D_Mercier"]

    mercier_obj = MercierStability(eq=eq, grid=grid)
    mercier_obj.build()
    np.testing.assert_allclose(mercier_obj.compute(*mercier_obj.xs(eq)), 0)
    mercier_obj.print_value(*mercier_obj.xs(eq))
    out = capsys.readouterr()

    corr_out = str(
        "Precomputing transforms\n"
        + "Maximum "
        + mercier_obj._print_value_fmt.format(np.max(Dmerc))
        + mercier_obj._units
        + "\n"
        + "Minimum "
        + mercier_obj._print_value_fmt.format(np.min(Dmerc))
        + mercier_obj._units
        + "\n"
        + "Average "
        + mercier_obj._print_value_fmt.format(np.mean(Dmerc))
        + mercier_obj._units
        + "\n"
        + "Maximum "
        + mercier_obj._print_value_fmt.format(np.max(Dmerc / mercier_obj.normalization))
        + "(normalized)"
        + "\n"
        + "Minimum "
        + mercier_obj._print_value_fmt.format(np.min(Dmerc / mercier_obj.normalization))
        + "(normalized)"
        + "\n"
        + "Average "
        + mercier_obj._print_value_fmt.format(
            np.mean(Dmerc / mercier_obj.normalization)
        )
        + "(normalized)"
        + "\n"
    )
    assert out.out == corr_out


@pytest.mark.unit
def test_magwell_print(capsys):
    """Test that the magnetic well stability criteria prints correctly."""
    eq = desc.examples.get("HELIOTRON")
    grid = LinearGrid(L=12, M=12, N=6, NFP=eq.NFP, axis=False)
    obj = MagneticWell(eq=eq, grid=grid)
    obj.build()

    magwell = grid.compress(eq.compute("magnetic well", grid=grid)["magnetic well"])
    f = obj.compute(*obj.xs(eq))
    np.testing.assert_allclose(f, magwell)

    obj.print_value(*obj.xs(eq))
    out = capsys.readouterr()

    corr_out = str(
        "Precomputing transforms\n"
        + "Maximum "
        + obj._print_value_fmt.format(np.max(magwell))
        + obj._units
        + "\n"
        + "Minimum "
        + obj._print_value_fmt.format(np.min(magwell))
        + obj._units
        + "\n"
        + "Average "
        + obj._print_value_fmt.format(np.mean(magwell))
        + obj._units
        + "\n"
    )
    assert out.out == corr_out


@pytest.mark.unit
def test_ballooning_geometry(tmpdir_factory):
    """Test the geometry coefficients used for the adjoint-ballooning solver.

    The same coefficients are used for local gyrokinetic solvers which would
    be useful when we couple DESC with GX/GS2 etc.
    Observation: The larger the force error, the worse the tests behave. For
    example, HELIOTRON coefficients are hard to match
    """
    psi = 0.5  # Actually rho^2 (normalized)
    alpha = 0
    ntor = 2.0

    eq0 = desc.examples.get("W7-X")
    eq1 = desc.examples.get("precise_QA")

    eq_list = [eq0, eq1]
    fac_list = [4, 4]

    for eq, fac in zip(eq_list, fac_list):
        eq_keys = ["iota", "iota_r", "a", "rho", "psi"]

        data_eq = eq.compute(eq_keys)

        fi = interp1d(data_eq["rho"], data_eq["iota"])
        fs = interp1d(data_eq["rho"], data_eq["iota_r"])

        iotas = fi(np.sqrt(psi))
        shears = fs(np.sqrt(psi))

        rho = np.sqrt(psi)
        N = int((2 * eq.M_grid * eq.N_grid) * ntor * int(fac) + 1)
        zeta = np.linspace(-ntor * np.pi, ntor * np.pi, N)

        data_keys = [
            "p_r",
            "psi",
            "psi_r",
            "sqrt(g)_PEST",
            "|grad(psi)|^2",
            "grad(|B|)",
            "grad(alpha)",
            "grad(psi)",
            "B",
            "grad(|B|)",
            "kappa",
            "iota",
            "lambda_t",
            "lambda_z",
            "lambda_tt",
            "lambda_zz",
            "lambda_tz",
            "g^aa",
            "g^ra",
            "g^rr",
            "cvdrift",
            "cvdrift0",
            "|B|",
            "B^zeta",
        ]

        grid = eq.get_rtz_grid(
            rho,
            alpha,
            zeta,
            coordinates="raz",
            period=(np.inf, 2 * np.pi, np.inf),
        )

        data = eq.compute(data_keys, grid=grid)

        psi_s = data_eq["psi"][-1]
        sign_psi = psi_s / np.abs(psi_s)
        sign_iota = iotas / np.abs(iotas)
        # normalizations
        Lref = data_eq["a"]
        Bref = 2 * np.abs(psi) / Lref**2

        modB = data["|B|"]
        x = Lref * np.sqrt(psi)
        shat = -x / iotas * shears / Lref

        psi_r = data["psi_r"]

        grad_psi = data["grad(psi)"]
        grad_psi_sq = data["|grad(psi)|^2"]
        grad_alpha = data["grad(alpha)"]

        g_sup_rr = data["g^rr"]
        g_sup_ra = data["g^ra"]
        g_sup_aa = data["g^aa"]

        modB = data["|B|"]

        B_sup_zeta = data["B^zeta"]

        gds2 = np.array(dot(grad_alpha, grad_alpha)) * Lref**2 * psi
        gds2_alt = g_sup_aa * Lref**2 * psi

        gds21 = -sign_iota * np.array(dot(grad_psi, grad_alpha)) * shat / Bref
        gds21_alt = -sign_iota * g_sup_ra * shat / Bref * (psi_r)

        gds22 = grad_psi_sq * (1 / psi) * (shat / (Lref * Bref)) ** 2
        gds22_alt = g_sup_rr * (psi_r) ** 2 * (1 / psi) * (shat / (Lref * Bref)) ** 2

        gbdrift = np.array(dot(cross(data["B"], data["grad(|B|)"]), grad_alpha))
        gbdrift *= -sign_psi * 2 * Bref * Lref**2 / modB**3 * np.sqrt(psi)
        gbdrift_alt = -sign_psi * data["gbdrift"] * 2 * Bref * Lref**2 * np.sqrt(psi)

        cvdrift = (
            -sign_psi
            * 2
            * Bref
            * Lref**2
            * np.sqrt(psi)
            * dot(cross(data["B"], data["kappa"]), grad_alpha)
            / modB**2
        )
        cvdrift_alt = -sign_psi * data["cvdrift"] * 2 * Bref * Lref**2 * np.sqrt(psi)

        np.testing.assert_allclose(gds2, gds2_alt)
        np.testing.assert_allclose(gds22, gds22_alt)
        np.testing.assert_allclose(gds21, gds21_alt)
        np.testing.assert_allclose(gbdrift, gbdrift_alt)
        np.testing.assert_allclose(cvdrift, cvdrift_alt, atol=1e-2)

        sqrt_g_PEST = data["sqrt(g)_PEST"]
        np.testing.assert_allclose(sqrt_g_PEST, 1 / (B_sup_zeta / psi_r))


@pytest.mark.unit
def test_ballooning_stability_eval():
    """Cross-compare all the stability functions.

    We calculated the ideal ballooning growth rate and Newcomb ball
    metric for the HELIOTRON case at different radii.
    """
    mu_0 = 4 * np.pi * 1e-7
    eq = desc.examples.get("HELIOTRON")

    # Flux surfaces on which to evaluate ballooning stability
    surfaces = [0.01, 0.8, 1.0]

    grid = LinearGrid(rho=jnp.array(surfaces), NFP=eq.NFP)
    eq_data_keys = ["iota"]

    data = eq.compute(eq_data_keys, grid=grid)

    N_alpha = int(8)

    # Field lines on which to evaluate ballooning stability
    alpha = jnp.linspace(0, np.pi, N_alpha + 1)[:N_alpha]

    # Number of toroidal transits of the field line
    ntor = int(3)

    # Number of point along a field line in ballooning space
    N_zeta = int(2.0 * ntor * eq.M_grid * eq.N_grid + 1)

    # range of the ballooning coordinate zeta
    zeta = np.linspace(-jnp.pi * ntor, jnp.pi * ntor, N_zeta)

    for i in range(len(surfaces)):
        rho = np.array([surfaces[i]])

        grid = eq.get_rtz_grid(
            rho,
            alpha,
            zeta,
            coordinates="raz",
            period=(np.inf, 2 * np.pi, np.inf),
        )

        data_keys0 = [
            "g^aa",
            "g^ra",
            "g^rr",
            "cvdrift",
            "cvdrift0",
            "|B|",
            "B^zeta",
            "p_r",
            "iota",
            "shear",
            "psi",
            "psi_r",
            "rho",
            "Psi",
        ]
        data0 = eq.compute(data_keys0, grid=grid)

        rho = data0["rho"]
        psi_b = eq.compute("Psi")["Psi"][-1] / (2 * jnp.pi)
        a_N = eq.compute(["a"])["a"]
        B_N = 2 * psi_b / a_N**2

        N_zeta0 = int(15)
        # up-down symmetric equilibria only
        zeta0 = jnp.linspace(-0.5 * jnp.pi, 0.5 * jnp.pi, N_zeta0)

        iota = data0["iota"]
        shear = data0["shear"]
        psi = data0["psi"]
        sign_psi = jnp.sign(psi)
        sign_iota = jnp.sign(iota)

        phi = zeta

        B = jnp.reshape(data0["|B|"], (N_alpha, 1, N_zeta))
        gradpar = jnp.reshape(data0["B^zeta"] / data0["|B|"], (N_alpha, 1, N_zeta))
        dpdpsi = jnp.mean(mu_0 * data0["p_r"] / data0["psi_r"])

        gds2 = jnp.reshape(
            rho**2
            * (
                data0["g^aa"][None, :]
                - 2 * sign_iota * shear / rho * zeta0[:, None] * data0["g^ra"][None, :]
                + zeta0[:, None] ** 2 * (shear / rho) ** 2 * data0["g^rr"][None, :]
            ),
            (N_alpha, N_zeta0, N_zeta),
        )

        f = a_N**3 * B_N * gds2 / B**3 * 1 / gradpar
        g = a_N**3 * B_N * gds2 / B * gradpar
        g_half = (g[:, :, 1:] + g[:, :, :-1]) / 2
        c = (
            1
            * a_N**3
            * B_N
            * jnp.reshape(
                2
                / data0["B^zeta"][None, :]
                * sign_psi
                * rho**2
                * dpdpsi
                * (
                    data0["cvdrift"][None, :]
                    - shear / rho * zeta0[:, None] * data0["cvdrift0"][None, :]
                ),
                (N_alpha, N_zeta0, N_zeta),
            )
        )

        h = phi[1] - phi[0]

        A = jnp.zeros((N_alpha, N_zeta0, N_zeta - 2, N_zeta - 2))

        i = jnp.arange(N_alpha)[:, None, None, None]
        l = jnp.arange(N_zeta0)[None, :, None, None]
        j = jnp.arange(N_zeta - 2)[None, None, :, None]
        k = jnp.arange(N_zeta - 2)[None, None, None, :]

        A = A.at[i, l, j, k].set(
            g_half[i, l, k] / f[i, l, k] * 1 / h**2 * (j - k == -1)
            + (
                -(g_half[i, l, j + 1] + g_half[i, l, j]) / f[i, l, j + 1] * 1 / h**2
                + c[i, l, j + 1] / f[i, l, j + 1]
            )
            * (j - k == 0)
            + g_half[i, l, j] / f[i, l, j + 1] * 1 / h**2 * (j - k == 1)
        )

        w = eigvals(jnp.where(jnp.isfinite(A), A, 0))

        lam1 = jnp.max(jnp.real(jnp.max(w, axis=(2,))))

        data_keys = ["ideal ball gamma2", "Newcomb ball metric"]
        data = eq.compute(data_keys, grid=grid)

        lam2 = np.max(data["ideal ball gamma2"])
        Newcomb_metric = data["Newcomb ball metric"]

        np.testing.assert_allclose(lam1, lam2, atol=5e-3, rtol=1e-8)

        if lam2 > 0:
            assert (
                Newcomb_metric >= 1
            ), "Newcomb metric indicates stabiliy for an unstable equilibrium"
        else:
            assert (
                Newcomb_metric < 1
            ), "Newcomb metric indicates instabiliy for a stable equilibrium"


@pytest.mark.unit
def test_compare_with_COBRAVMEC():
    """Compare marginal stability points from DESC ballooning solve with COBRAVMEC."""

    def find_root_simple(x, y):
        sign_changes = np.where(np.diff(np.sign(y)))[0]

        if len(sign_changes) == 0:
            return None  # No zero crossing found

        # Get the indices where y changes sign
        i = sign_changes[0]

        # Linear interpolation
        x0, x1 = x[i], x[i + 1]
        y0, y1 = y[i], y[i + 1]

        # Calculate the zero crossing
        x_zero = x0 + (0 - y0) * (x1 - x0) / (y1 - y0)

        return x_zero

    A = np.loadtxt("./tests/inputs/cobra_grate.HELIOTRON_L24_M16_N12")

    ns1 = int(A[0, 2])
    nangles = int(np.shape(A)[0] / (ns1 + 1))

    B = np.zeros((ns1,))
    for i in range(nangles):
        if i == 0:
            B = A[i + 1 : (i + 1) * ns1 + 1, 2]
        else:
            B = np.vstack((B, A[i * ns1 + i + 1 : (i + 1) * ns1 + i + 1, 2]))

    gamma1 = np.amax(B, axis=0)

    s1 = np.linspace(0, 1, ns1)
    s1 = s1 + np.diff(s1)[0]

    # COBRAVMEC calculated everything in s(=rho^2),
    # DESC calculates in rho(=sqrt(s))
    rho1 = np.sqrt(s1)

    root_COBRAVMEC = find_root_simple(rho1, gamma1)

    eq = desc.examples.get("HELIOTRON")

    # Flux surfaces on which to evaluate ballooning stability
    surfaces = [0.98, 0.985, 0.99, 0.995, 1.0]

    grid = LinearGrid(rho=jnp.array(surfaces), NFP=eq.NFP)

    Nalpha = int(8)  # Number of field lines

    assert Nalpha == int(8), "Nalpha in the compute function hard-coded to 8!"

    # Field lines on which to evaluate ballooning stability
    alpha = jnp.linspace(0, np.pi, Nalpha + 1)[:Nalpha]

    # Number of toroidal transits of the field line
    ntor = int(3)

    # Number of point along a field line in ballooning space
    N0 = int(2.0 * ntor * eq.M_grid * eq.N_grid + 1)

    # range of the ballooning coordinate zeta
    zeta = np.linspace(-jnp.pi * ntor, jnp.pi * ntor, N0)

    lam2_array = np.zeros(
        len(surfaces),
    )

    for i in range(len(surfaces)):
        rho = surfaces[i]

        grid = eq.get_rtz_grid(
            rho,
            alpha,
            zeta,
            coordinates="raz",
            period=(np.inf, 2 * np.pi, np.inf),
        )

        data_keys = ["ideal ball gamma2"]
        data = eq.compute(data_keys, grid=grid)

        lam2_array[i] = np.max(data["ideal ball gamma2"])

    root_DESC = find_root_simple(np.array(surfaces), lam2_array)

    # Comparing the points of marginal stability from COBRAVMEC and DESC
    np.testing.assert_allclose(root_COBRAVMEC, root_DESC, atol=5e-4, rtol=1e-8)
