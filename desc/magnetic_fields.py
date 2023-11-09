"""Classes for magnetic fields."""

from abc import ABC, abstractmethod

import numpy as np
import scipy.linalg
from jax import jacfwd
from netCDF4 import Dataset

from desc.backend import cond, fori_loop, gammaln, jit, jnp, odeint, sign
from desc.basis import DoubleFourierSeries
from desc.compute import rpz2xyz, rpz2xyz_vec, xyz2rpz, xyz2rpz_vec
from desc.derivatives import Derivative
from desc.equilibrium import EquilibriaFamily, Equilibrium
from desc.geometry import FourierRZToroidalSurface
from desc.grid import LinearGrid
from desc.interpolate import _approx_df, interp2d, interp3d
from desc.io import IOAble
from desc.transform import Transform
from desc.utils import copy_coeffs, errorif, warnif
from desc.vmec_utils import ptolemy_identity_fwd, ptolemy_identity_rev


def biot_savart_general(re, rs, J, dV):
    """Biot-Savart law for arbitrary sources.

    Parameters
    ----------
    re : ndarray, shape(n_eval_pts, 3)
        evaluation points to evaluate B at, in cartesian.
    rs : ndarray, shape(n_src_pts, 3)
        source points for current density J, in cartesian.
    J : ndarray, shape(n_src_pts, 3)
        current density vector at source points, in cartesian.
    dV : ndarray, shape(n_src_pts)
        volume element at source points

    Returns
    -------
    B : ndarray, shape(n,3)
        magnetic field in cartesian components at specified points
    """
    re, rs, J, dV = map(jnp.asarray, (re, rs, J, dV))
    assert J.shape == rs.shape
    JdV = J * dV[:, None]
    B = jnp.zeros_like(re)

    def body(i, B):
        r = re - rs[i, :]
        num = jnp.cross(JdV[i, :], r, axis=-1)
        den = jnp.linalg.norm(r, axis=-1) ** 3
        B = B + jnp.where(den[:, None] == 0, 0, num / den[:, None])
        return B

    return 1e-7 * fori_loop(0, J.shape[0], body, B)


def read_BNORM_file(fname, surface, eval_grid=None, scale_by_curpol=True):
    """Read BNORM-style .txt file containing Bnormal Fourier coefficients.

    Parameters
    ----------
    fname : str
        name of BNORM file to read and use to calculate Bnormal from.
    surface : Surface or Equilibrium
        Surface to calculate the magnetic field's Bnormal on.
        If an Equilibrium is supplied, will use its boundary surface.
    eval_grid : Grid, optional
        Grid of points on the plasma surface to evaluate the Bnormal at,
        if None defaults to a LinearGrid with twice
        the surface grid's poloidal and toroidal resolutions
    scale_by_curpol : bool, optional
        Whether or not to un-scale the Bnormal coefficients by curpol
        before calculating Bnormal, by default True
        (set to False if it is known that the BNORM file was saved without scaling
        by curpol)
        requires an Equilibrium to be passed in

    Returns
    -------
    Bnormal: ndarray,
        Bnormal distribution from the BNORM Fourier coefficients,
        evaluated on the given eval_grid
    """
    if isinstance(surface, EquilibriaFamily):
        surface = surface[-1]
    if isinstance(surface, Equilibrium):
        eq = surface
        surface = eq.surface
    else:
        eq = None

    assert surface.sym, (
        "BNORM assumes stellarator symmetry, but" "a non-symmetric surface was given!"
    )

    if scale_by_curpol and eq is None:
        raise RuntimeError(
            "an Equilibrium must be supplied when scale_by_curpol is True!"
        )

    curpol = (
        (2 * jnp.pi / eq.NFP * eq.compute("G", grid=LinearGrid(rho=jnp.array(1)))["G"])
        if scale_by_curpol
        else 1
    )

    data = np.genfromtxt(fname)

    xm = data[:, 0]
    xn = -data[:, 1]  # negate since BNORM uses sin(mu+nv) convention
    Bnorm_mn = data[:, 2] / curpol  # these will only be sin terms

    # convert to DESC Fourier representation i.e. like cos(mt)*cos(nz)
    m, n, Bnorm_mn = ptolemy_identity_fwd(xm, xn, Bnorm_mn, np.zeros_like(Bnorm_mn))
    basis = DoubleFourierSeries(
        int(np.max(m)), int(np.max(n)), sym="sin", NFP=surface.NFP
    )

    Bnorm_mn_desc_basis = copy_coeffs(
        Bnorm_mn.squeeze(), np.vstack((np.zeros_like(m), m, n)).T, basis.modes
    )

    if eval_grid is None:
        eval_grid = LinearGrid(
            rho=jnp.array(1.0), M=surface.M_grid, N=surface.N_grid, NFP=surface.NFP
        )
    trans = Transform(basis=basis, grid=eval_grid, build_pinv=True)

    # Evaluate Fourier Series
    Bnorm = trans.transform(Bnorm_mn_desc_basis)

    return Bnorm


class _MagneticField(IOAble, ABC):
    """Base class for all magnetic fields.

    Subclasses must implement the "compute_magnetic_field" method

    """

    _io_attrs_ = []

    def __mul__(self, x):
        if np.isscalar(x):
            return ScaledMagneticField(x, self)
        else:
            return NotImplemented

    def __rmul__(self, x):
        return self.__mul__(x)

    def __add__(self, x):
        if isinstance(x, _MagneticField):
            return SumMagneticField(self, x)
        else:
            return NotImplemented

    def __neg__(self):
        return ScaledMagneticField(-1, self)

    def __sub__(self, x):
        return self.__add__(-x)

    @abstractmethod
    def compute_magnetic_field(self, coords, params=None, basis="rpz", grid=None):
        """Compute magnetic field at a set of points.

        Parameters
        ----------
        coords : array-like shape(N,3) or Grid
            cylindrical or cartesian coordinates
        params : dict, optional
            parameters to pass to scalar potential function
        basis : {"rpz", "xyz"}
            basis for input coordinates and returned magnetic field
        grid : Grid, int or None
            Grid used to discretize MagneticField object if calculating
            B from biot savart. If an integer, uses that many equally spaced
            points.

        Returns
        -------
        field : ndarray, shape(N,3)
            magnetic field at specified points

        """

    def __call__(self, coords, params=None, basis="rpz"):
        """Compute magnetic field at a set of points."""
        return self.compute_magnetic_field(coords, params, basis)

    def compute_Bnormal(
        self, surface, eval_grid=None, source_grid=None, params=None, basis="rpz"
    ):
        """Compute Bnormal from self on the given surface.

        Parameters
        ----------
        surface : Surface or Equilibrium
            Surface to calculate the magnetic field's Bnormal on.
            If an Equilibrium is supplied, will use its boundary surface.
        eval_grid : Grid, optional
            Grid of points on the surface to calculate the Bnormal at,
            if None defaults to a LinearGrid with twice
            the surface poloidal and toroidal resolutions
            points are in surface angular coordinates i.e theta and zeta
        source_grid : Grid, int or None
            Grid used to discretize MagneticField object if calculating
            B from biot savart. If an integer, uses that many equally spaced
            points.
        params : list or tuple of dict, optional
            parameters to pass to underlying field's compute_magnetic_field function.
            If None, uses the default parameters for each field.
            If a list or tuple, should have one entry for each component field.
        basis : {"rpz", "xyz"}
            basis for returned coordinates on the surface
            cylindrical "rpz" by default

        Returns
        -------
        Bnorm : ndarray
            The normal magnetic field to the surface given, of size grid.num_nodes.
        coords: ndarray
            the locations (in specified basis) at which the Bnormal was calculated

        """
        if isinstance(surface, EquilibriaFamily):
            surface = surface[-1]
        if isinstance(surface, Equilibrium):
            surface = surface.surface
        if eval_grid is None:
            eval_grid = LinearGrid(
                rho=jnp.array(1.0), M=2 * surface.M, N=2 * surface.N, NFP=surface.NFP
            )
        data = surface.compute(["x", "n_rho"], grid=eval_grid, basis="xyz")
        coords = data["x"]
        surf_normal = data["n_rho"]
        B = self.compute_magnetic_field(
            coords, basis="xyz", grid=source_grid, params=params
        )

        Bnorm = jnp.sum(B * surf_normal, axis=-1)

        if basis.lower() == "rpz":
            coords = xyz2rpz(coords)

        return Bnorm, coords

    def save_BNORM_file(
        self,
        surface,
        fname,
        basis_M=24,
        basis_N=24,
        eval_grid=None,
        source_grid=None,
        params=None,
        sym="sin",
        scale_by_curpol=True,
    ):
        """Create BNORM-style .txt file containing Bnormal Fourier coefficients.

        Parameters
        ----------
        surface : Surface or Equilibrium
            Surface to calculate the magnetic field's Bnormal on.
            If an Equilibrium is supplied, will use its boundary surface.
        fname : str
            name of file to save the BNORM Bnormal Fourier coefficients to.
        basis_M : int, optional
            Poloidal resolution of the DoubleFourierSeries used to fit the Bnormal
            on the plasma surface, by default 24
        basis_N : int, optional
            Toroidal resolution of the DoubleFourierSeries used to fit the Bnormal
            on the plasma surface, by default 24
        eval_grid : Grid, optional
            Grid of points on the surface to calculate the Bnormal at,
            if None defaults to a LinearGrid with twice
            the surface poloidal and toroidal resolutions
            points are in surface angular coordinates i.e theta and zeta
        source_grid : Grid, int or None
            Grid used to discretize MagneticField object if calculating
            B from biot savart. If an integer, uses that many equally spaced
            points.
        params : list or tuple of dict, optional
            parameters to pass to underlying field's compute_magnetic_field function.
            If None, uses the default parameters for each field.
            If a list or tuple, should have one entry for each component field.
        sym : str, optional
            if Bnormal is symmetric, by default "sin"
            NOTE: BNORM code only ever deals with sin-symmetric modes, so results
            may not be as expected if attempt to create a BNORM file with a
            non-symmetric Bnormal distribution, as only the sin-symmetric modes
            will be saved.
        scale_by_curpol : bool, optional
            Whether or not to scale the Bnormal coefficients by curpol
            which is expected by most other codes that accept BNORM files,
            by default True

        Returns
        -------
        None
        """
        if sym != "sin":
            raise UserWarning(
                "BNORM code assumes that |B| has sin symmetry,"
                + " and so BNORM file only saves the sin coefficients!"
                + " Resulting BNORM file will not contain the cos modes"
            )

        if isinstance(surface, EquilibriaFamily):
            surface = surface[-1]
        if isinstance(surface, Equilibrium):
            eq = surface
            surface = eq.surface
        else:
            eq = None
        if scale_by_curpol and eq is None:
            raise RuntimeError(
                "an Equilibrium must be supplied when scale_by_curpol is True!"
            )
        if eval_grid is None:
            eval_grid = LinearGrid(
                rho=jnp.array(1.0), M=2 * basis_M, N=2 * basis_N, NFP=surface.NFP
            )

        basis = DoubleFourierSeries(M=basis_M, N=basis_N, NFP=surface.NFP, sym=sym)
        trans = Transform(basis=basis, grid=eval_grid, build_pinv=True)

        # compute Bnormal on the grid
        Bnorm, _ = self.compute_Bnormal(
            surface, eval_grid=eval_grid, source_grid=source_grid, params=params
        )

        # fit Bnorm with Fourier Series
        Bnorm_mn = trans.fit(Bnorm)
        # convert to VMEC-style mode numbers to conform with BNORM format
        xm, xn, s, c = ptolemy_identity_rev(
            basis.modes[:, 1], basis.modes[:, 2], Bnorm_mn.reshape((1, Bnorm_mn.size))
        )

        Bnorm_xn = -xn  # need to negate Xn for BNORM code format of cos(mu+nv)

        # BNORM also scales values by curpol, a VMEC output which is calculated by
        # (source:
        #  https://princetonuniversity.github.io/FOCUS/
        #   notes/Coil_design_codes_benchmark.html )
        # "BNORM scales B_n by curpol=(2*pi/nfp)*bsubv(m=0,n=0)
        # where bsubv is the extrapolation to the last full mesh point of
        # bsubvmnc."
        # this corresponds to 2pi/NFP*G(rho=1) in DESC
        curpol = (
            (
                2
                * jnp.pi
                / surface.NFP
                * eq.compute("G", grid=LinearGrid(rho=jnp.array(1)))["G"]
            )
            if scale_by_curpol
            else 1
        )

        # BNORM assumes |B| has sin sym so c=0, so we only need s
        data = np.vstack((xm, Bnorm_xn, s * curpol)).T

        np.savetxt(f"{fname}", data, fmt="%d %d %1.12e")
        return None


class ScaledMagneticField(_MagneticField):
    """Magnetic field scaled by a scalar value.

    ie B_new = scalar * B_old

    Parameters
    ----------
    scalar : float, int
        scaling factor for magnetic field
    field : MagneticField
        base field to be scaled

    """

    _io_attrs = _MagneticField._io_attrs_ + ["_field", "_scalar"]

    def __init__(self, scalar, field):
        assert np.isscalar(scalar), "scalar must actually be a scalar value"
        assert isinstance(
            field, _MagneticField
        ), "field should be a subclass of MagneticField, got type {}".format(
            type(field)
        )
        self._scalar = scalar
        self._field = field

    def compute_magnetic_field(self, coords, params=None, basis="rpz", grid=None):
        """Compute magnetic field at a set of points.

        Parameters
        ----------
        coords : array-like shape(N,3) or Grid
            cylindrical or cartesian coordinates
        params : tuple, optional
            parameters to pass to underlying field
        basis : {"rpz", "xyz"}
            basis for input coordinates and returned magnetic field
        grid : Grid, int or None
            Grid used to discretize MagneticField object if calculating
            B from biot savart. If an integer, uses that many equally spaced
            points.

        Returns
        -------
        field : ndarray, shape(N,3)
            scaled magnetic field at specified points
        """
        return self._scalar * self._field.compute_magnetic_field(
            coords, params, basis, grid
        )


class SumMagneticField(_MagneticField):
    """Sum of two or more magnetic field sources.

    Parameters
    ----------
    fields : MagneticField
        two or more MagneticFields to add together
    """

    _io_attrs = _MagneticField._io_attrs_ + ["_fields"]

    def __init__(self, *fields):
        assert all(
            [isinstance(field, _MagneticField) for field in fields]
        ), "fields should each be a subclass of MagneticField, got {}".format(
            [type(field) for field in fields]
        )
        self._fields = fields

    def compute_magnetic_field(self, coords, params=None, basis="rpz", grid=None):
        """Compute magnetic field at a set of points.

        Parameters
        ----------
        coords : array-like shape(N,3) or Grid
            cylindrical or cartesian coordinates
        params : list or tuple of dict, optional
            parameters to pass to underlying fields. If None,
            uses the default parameters for each field. If a list or tuple, should have
            one entry for each component field.
        basis : {"rpz", "xyz"}
            basis for input coordinates and returned magnetic field
        grid : Grid, int or None
            Grid used to discretize MagneticField object if calculating
            B from biot savart. If an integer, uses that many equally spaced
            points.

        Returns
        -------
        field : ndarray, shape(N,3)
            scaled magnetic field at specified points
        """
        if params is None:
            params = [None] * len(self._fields)
        if isinstance(params, dict):
            params = [params]
        B = 0
        for i, field in enumerate(self._fields):
            B += field.compute_magnetic_field(
                coords, params[i % len(params)], basis, grid=grid
            )

        return B


class ToroidalMagneticField(_MagneticField):
    """Magnetic field purely in the toroidal (phi) direction.

    Magnitude is B0*R0/R where R0 is the major radius of the axis and B0
    is the field strength on axis

    Parameters
    ----------
    B0 : float
        field strength on axis
    R0 : major radius of axis

    """

    _io_attrs_ = _MagneticField._io_attrs_ + ["_B0", "_R0"]

    def __init__(self, B0, R0):
        assert float(B0) == B0, "B0 must be a scalar"
        assert float(R0) == R0, "R0 must be a scalar"
        self._B0 = float(B0)
        self._R0 = float(R0)

    def compute_magnetic_field(self, coords, params=None, basis="rpz", grid=None):
        """Compute magnetic field at a set of points.

        Parameters
        ----------
        coords : array-like shape(N,3) or Grid
            cylindrical or cartesian coordinates
        params : tuple, optional
            unused by this method
        basis : {"rpz", "xyz"}
            basis for input coordinates and returned magnetic field
        grid : Grid, int or None
            Grid used to discretize MagneticField object if calculating
            B from biot savart. If an integer, uses that many equally spaced
            points.
            Unused by this MagneticField class
        Returns
        -------
        field : ndarray, shape(N,3)
            magnetic field at specified points

        """
        assert basis.lower() in ["rpz", "xyz"]
        if hasattr(coords, "nodes"):
            coords = coords.nodes
        coords = jnp.atleast_2d(coords)
        if basis == "xyz":
            coords = xyz2rpz(coords)
        bp = self._B0 * self._R0 / coords[:, 0]
        brz = jnp.zeros_like(bp)
        B = jnp.array([brz, bp, brz]).T
        if basis == "xyz":
            B = rpz2xyz_vec(B, phi=coords[:, 1])

        return B


class VerticalMagneticField(_MagneticField):
    """Uniform magnetic field purely in the vertical (Z) direction.

    Parameters
    ----------
    B0 : float
        field strength

    """

    _io_attrs_ = _MagneticField._io_attrs_ + ["_B0"]

    def __init__(self, B0):
        assert np.isscalar(B0), "B0 must be a scalar"
        self._B0 = B0

    def compute_magnetic_field(self, coords, params=None, basis="rpz", grid=None):
        """Compute magnetic field at a set of points.

        Parameters
        ----------
        coords : array-like shape(N,3) or Grid
            cylindrical or cartesian coordinates
        params : tuple, optional
            unused by this method
        basis : {"rpz", "xyz"}
            basis for input coordinates and returned magnetic field
        grid : Grid, int or None
            Grid used to discretize MagneticField object if calculating
            B from biot savart. If an integer, uses that many equally spaced
            points.
            Unused by this MagneticField class

        Returns
        -------
        field : ndarray, shape(N,3)
            magnetic field at specified points

        """
        assert basis.lower() in ["rpz", "xyz"]
        if hasattr(coords, "nodes"):
            coords = coords.nodes
        coords = jnp.atleast_2d(coords)
        if basis == "xyz":
            coords = xyz2rpz(coords)
        bz = self._B0 * jnp.ones_like(coords[:, 2])
        brp = jnp.zeros_like(bz)
        B = jnp.array([brp, brp, bz]).T
        if basis == "xyz":
            B = rpz2xyz_vec(B, phi=coords[:, 1])

        return B


class PoloidalMagneticField(_MagneticField):
    """Pure poloidal magnetic field (ie in theta direction).

    Field strength is B0*iota*r/R0 where B0 is the toroidal field on axis,
    R0 is the major radius of the axis, iota is the desired rotational transform,
    and r is the minor radius centered on the magnetic axis.

    Combined with a toroidal field with the same B0 and R0, creates an
    axisymmetric field with rotational transform iota

    Note that the divergence of such a field is proportional to Z/R so is generally
    nonzero except on the midplane, but still serves as a useful test case

    Parameters
    ----------
    B0 : float
        field strength on axis
    R0 : float
        major radius of magnetic axis
    iota : float
        desired rotational transform

    """

    _io_attrs_ = _MagneticField._io_attrs_ + ["_B0", "_R0", "_iota"]

    def __init__(self, B0, R0, iota):
        assert np.isscalar(B0), "B0 must be a scalar"
        assert np.isscalar(R0), "R0 must be a scalar"
        assert np.isscalar(iota), "iota must be a scalar"
        self._B0 = B0
        self._R0 = R0
        self._iota = iota

    def compute_magnetic_field(self, coords, params=None, basis="rpz", grid=None):
        """Compute magnetic field at a set of points.

        Parameters
        ----------
        coords : array-like shape(N,3) or Grid
            cylindrical or cartesian coordinates
        params : tuple, optional
            unused by this method
        basis : {"rpz", "xyz"}
            basis for input coordinates and returned magnetic field
        grid : Grid, int or None
            Grid used to discretize MagneticField object if calculating
            B from biot savart. If an integer, uses that many equally spaced
            points.
            Unused by this MagneticField class

        Returns
        -------
        field : ndarray, shape(N,3)
            magnetic field at specified points, in cylindrical form [BR, Bphi,BZ]

        """
        assert basis.lower() in ["rpz", "xyz"]
        if hasattr(coords, "nodes"):
            coords = coords.nodes
        coords = jnp.atleast_2d(coords)
        if basis == "xyz":
            coords = xyz2rpz(coords)

        R, phi, Z = coords.T
        r = jnp.sqrt((R - self._R0) ** 2 + Z**2)
        theta = jnp.arctan2(Z, R - self._R0)
        br = -r * jnp.sin(theta)
        bp = jnp.zeros_like(br)
        bz = r * jnp.cos(theta)
        bmag = self._B0 * self._iota / self._R0
        B = bmag * jnp.array([br, bp, bz]).T
        if basis == "xyz":
            B = rpz2xyz_vec(B, phi=coords[:, 1])

        return B


class SplineMagneticField(_MagneticField):
    """Magnetic field from precomputed values on a grid.

    Parameters
    ----------
    R : array-like, size(NR)
        R coordinates where field is specified
    phi : array-like, size(Nphi)
        phi coordinates where field is specified
    Z : array-like, size(NZ)
        Z coordinates where field is specified
    BR : array-like, shape(NR,Nphi,NZ)
        radial magnetic field on grid
    Bphi : array-like, shape(NR,Nphi,NZ)
        toroidal magnetic field on grid
    BZ : array-like, shape(NR,Nphi,NZ)
        vertical magnetic field on grid
    method : str
        interpolation method
    extrap : bool
        whether to extrapolate beyond the domain of known field values or return nan
    period : float
        period in the toroidal direction (usually 2pi/NFP)

    """

    _io_attrs_ = [
        "_R",
        "_phi",
        "_Z",
        "_BR",
        "_Bphi",
        "_BZ",
        "_method",
        "_extrap",
        "_period",
        "_derivs",
        "_axisym",
    ]

    def __init__(self, R, phi, Z, BR, Bphi, BZ, method="cubic", extrap=False, period=0):
        R, phi, Z = np.atleast_1d(R), np.atleast_1d(phi), np.atleast_1d(Z)
        assert R.ndim == 1
        assert phi.ndim == 1
        assert Z.ndim == 1
        BR, Bphi, BZ = np.atleast_3d(BR), np.atleast_3d(Bphi), np.atleast_3d(BZ)
        assert BR.shape == Bphi.shape == BZ.shape == (R.size, phi.size, Z.size)

        self._R = R
        self._phi = phi
        if len(phi) == 1:
            self._axisym = True
        else:
            self._axisym = False
        self._Z = Z
        self._BR = BR
        self._Bphi = Bphi
        self._BZ = BZ

        self._method = method
        self._extrap = extrap
        self._period = period

        self._derivs = {}
        self._derivs["BR"] = self._approx_derivs(self._BR)
        self._derivs["Bphi"] = self._approx_derivs(self._Bphi)
        self._derivs["BZ"] = self._approx_derivs(self._BZ)

    def _approx_derivs(self, Bi):
        tempdict = {}
        tempdict["fx"] = _approx_df(self._R, Bi, self._method, 0)
        tempdict["fz"] = _approx_df(self._Z, Bi, self._method, 2)
        tempdict["fxz"] = _approx_df(self._Z, tempdict["fx"], self._method, 2)
        if self._axisym:
            tempdict["fy"] = jnp.zeros_like(tempdict["fx"])
            tempdict["fxy"] = jnp.zeros_like(tempdict["fx"])
            tempdict["fyz"] = jnp.zeros_like(tempdict["fx"])
            tempdict["fxyz"] = jnp.zeros_like(tempdict["fx"])
        else:
            tempdict["fy"] = _approx_df(self._phi, Bi, self._method, 1)
            tempdict["fxy"] = _approx_df(self._phi, tempdict["fx"], self._method, 1)
            tempdict["fyz"] = _approx_df(self._Z, tempdict["fy"], self._method, 2)
            tempdict["fxyz"] = _approx_df(self._Z, tempdict["fxy"], self._method, 2)
        if self._axisym:
            for key, val in tempdict.items():
                tempdict[key] = val[:, 0, :]
        return tempdict

    def compute_magnetic_field(self, coords, params=None, basis="rpz", grid=None):
        """Compute magnetic field at a set of points.

        Parameters
        ----------
        coords : array-like shape(N,3) or Grid
            cylindrical or cartesian coordinates
        params : tuple, optional
            unused by this method
        basis : {"rpz", "xyz"}
            basis for input coordinates and returned magnetic field
        grid : Grid, int or None
            Grid used to discretize MagneticField object if calculating
            B from biot savart. If an integer, uses that many equally spaced
            points.
            Unused by this MagneticField class

        Returns
        -------
        field : ndarray, shape(N,3)
            magnetic field at specified points, in cylindrical form [BR, Bphi,BZ]

        """
        assert basis.lower() in ["rpz", "xyz"]
        if hasattr(coords, "nodes"):
            coords = coords.nodes
        coords = jnp.atleast_2d(coords)
        if basis == "xyz":
            coords = xyz2rpz(coords)
        Rq, phiq, Zq = coords.T
        if self._axisym:
            BRq = interp2d(
                Rq,
                Zq,
                self._R,
                self._Z,
                self._BR[:, 0, :],
                self._method,
                (0, 0),
                self._extrap,
                (None, None),
                **self._derivs["BR"],
            )
            Bphiq = interp2d(
                Rq,
                Zq,
                self._R,
                self._Z,
                self._Bphi[:, 0, :],
                self._method,
                (0, 0),
                self._extrap,
                (None, None),
                **self._derivs["Bphi"],
            )
            BZq = interp2d(
                Rq,
                Zq,
                self._R,
                self._Z,
                self._BZ[:, 0, :],
                self._method,
                (0, 0),
                self._extrap,
                (None, None),
                **self._derivs["BZ"],
            )

        else:
            BRq = interp3d(
                Rq,
                phiq,
                Zq,
                self._R,
                self._phi,
                self._Z,
                self._BR,
                self._method,
                (0, 0, 0),
                self._extrap,
                (None, self._period, None),
                **self._derivs["BR"],
            )
            Bphiq = interp3d(
                Rq,
                phiq,
                Zq,
                self._R,
                self._phi,
                self._Z,
                self._Bphi,
                self._method,
                (0, 0, 0),
                self._extrap,
                (None, self._period, None),
                **self._derivs["Bphi"],
            )
            BZq = interp3d(
                Rq,
                phiq,
                Zq,
                self._R,
                self._phi,
                self._Z,
                self._BZ,
                self._method,
                (0, 0, 0),
                self._extrap,
                (None, self._period, None),
                **self._derivs["BZ"],
            )
        B = jnp.array([BRq, Bphiq, BZq]).T
        if basis == "xyz":
            B = rpz2xyz_vec(B, phi=coords[:, 1])
        return B

    @classmethod
    def from_mgrid(
        cls, mgrid_file, extcur=1, method="cubic", extrap=False, period=None
    ):
        """Create a SplineMagneticField from an "mgrid" file from MAKEGRID.

        Parameters
        ----------
        mgrid_file : str or path-like
            path to mgrid file in netCDF format
        extcur : array-like
            currents for each subset of the field
        method : str
            interpolation method
        extrap : bool
            whether to extrapolate beyond the domain of known field values or return nan
        period : float
            period in the toroidal direction (usually 2pi/NFP)

        """
        Rgrid, pgrid, Zgrid, br, bp, bz, nfp = read_mgrid(mgrid_file, extcur)

        if period is None:
            period = 2 * np.pi / (nfp)

        return cls(Rgrid, pgrid, Zgrid, br, bp, bz, method, extrap, period)

    @classmethod
    def from_field(
        cls, field, R, phi, Z, params=None, method="cubic", extrap=False, period=None
    ):
        """Create a splined magnetic field from another field for faster evaluation.

        Parameters
        ----------
        field : MagneticField or callable
            field to interpolate. If a callable, should take a vector of
            cylindrical coordinates and return the field in cylindrical components
        R, phi, Z : ndarray
            1d arrays of interpolation nodes in cylindrical coordinates
        params : dict, optional
            parameters passed to field
        method : str
            spline method for SplineMagneticField
        extrap : bool
            whether to extrapolate splines beyond specified R,phi,Z
        period : float
            period for phi coordinate. Usually 2pi/NFP

        """
        R, phi, Z = map(np.asarray, (R, phi, Z))
        rr, pp, zz = np.meshgrid(R, phi, Z, indexing="ij")
        shp = rr.shape
        coords = np.array([rr.flatten(), pp.flatten(), zz.flatten()]).T
        BR, BP, BZ = field.compute_magnetic_field(coords, params, basis="rpz").T
        return cls(
            R,
            phi,
            Z,
            BR.reshape(shp),
            BP.reshape(shp),
            BZ.reshape(shp),
            method,
            extrap,
            period,
        )


class ScalarPotentialField(_MagneticField):
    """Magnetic field due to a scalar magnetic potential in cylindrical coordinates.

    Parameters
    ----------
    potential : callable
        function to compute the scalar potential. Should have a signature of
        the form potential(R,phi,Z,*params) -> ndarray.
        R,phi,Z are arrays of cylindrical coordinates.
    params : dict, optional
        default parameters to pass to potential function

    """

    def __init__(self, potential, params=None):
        self._potential = potential
        self._params = params

    def compute_magnetic_field(self, coords, params=None, basis="rpz", grid=None):
        """Compute magnetic field at a set of points.

        Parameters
        ----------
        coords : array-like shape(N,3) or Grid
            cylindrical or cartesian coordinates
        params : dict, optional
            parameters to pass to scalar potential function
        basis : {"rpz", "xyz"}
            basis for input coordinates and returned magnetic field
        grid : Grid, int or None
            Grid used to discretize MagneticField object if calculating
            B from biot savart. If an integer, uses that many equally spaced
            points.
            Unused by this MagneticField class

        Returns
        -------
        field : ndarray, shape(N,3)
            magnetic field at specified points

        """
        assert basis.lower() in ["rpz", "xyz"]
        if hasattr(coords, "nodes"):
            coords = coords.nodes
        coords = jnp.atleast_2d(coords)
        if coords.dtype == int:
            coords = coords.astype(float)
        if basis == "xyz":
            coords = xyz2rpz(coords)

        if params is None:
            params = self._params
        r, p, z = coords.T
        funR = lambda x: self._potential(x, p, z, **params)
        funP = lambda x: self._potential(r, x, z, **params)
        funZ = lambda x: self._potential(r, p, x, **params)
        br = Derivative.compute_jvp(funR, 0, (jnp.ones_like(r),), r)
        bp = Derivative.compute_jvp(funP, 0, (jnp.ones_like(p),), p)
        bz = Derivative.compute_jvp(funZ, 0, (jnp.ones_like(z),), z)
        B = jnp.array([br, bp / r, bz]).T
        if basis == "xyz":
            B = rpz2xyz_vec(B, phi=coords[:, 1])
        return B


class DommaschkPotentialField(ScalarPotentialField):
    """Magnetic field due to a Dommaschk scalar magnetic potential in rpz coordinates.

        From Dommaschk 1986 paper https://doi.org/10.1016/0010-4655(86)90109-8

        this is the field due to the dommaschk potential (eq. 1) for
        a given set of m,l indices and their corresponding
        coefficients a_ml, b_ml, c_ml d_ml.

    Parameters
    ----------
    ms : 1D array-like of int
        first indices of V_m_l terms (eq. 12 of reference)
    ls : 1D array-like of int
        second indices of V_m_l terms (eq. 12 of reference)
    a_arr : 1D array-like of float
        a_m_l coefficients of V_m_l terms, which multiply the cos(m*phi)*D_m_l terms
    b_arr : 1D array-like of float
        b_m_l coefficients of V_m_l terms, which multiply the sin(m*phi)*D_m_l terms
    c_arr : 1D array-like of float
        c_m_l coefficients of V_m_l terms, which multiply the cos(m*phi)*N_m_l-1 term
    d_arr : 1D array-like of float
        d_m_l coefficients of V_m_l terms, which multiply the sin(m*phi)*N_m_l-1 terms
    B0: float
        scale strength of the magnetic field's 1/R portion

    """

    def __init__(self, ms, ls, a_arr, b_arr, c_arr, d_arr, B0=1.0):

        ms = jnp.atleast_1d(ms)
        ls = jnp.atleast_1d(ls)
        a_arr = jnp.atleast_1d(a_arr)
        b_arr = jnp.atleast_1d(b_arr)
        c_arr = jnp.atleast_1d(c_arr)
        d_arr = jnp.atleast_1d(d_arr)

        assert (
            ms.size == ls.size == a_arr.size == b_arr.size == c_arr.size == d_arr.size
        ), "Passed in arrays must all be of the same size!"
        assert not jnp.any(
            jnp.logical_or(ms < 0, ls < 0)
        ), "m and l mode numbers must be >= 0!"
        assert (
            jnp.isscalar(B0) or jnp.atleast_1d(B0).size == 1
        ), "B0 should be a scalar value!"

        params = {}
        params["ms"] = ms
        params["ls"] = ls
        params["a_arr"] = a_arr
        params["b_arr"] = b_arr
        params["c_arr"] = c_arr
        params["d_arr"] = d_arr
        params["B0"] = B0

        super().__init__(dommaschk_potential, params)

    @classmethod
    def fit_magnetic_field(cls, field, coords, max_m, max_l, sym=False):
        """Fit a vacuum magnetic field with a Dommaschk Potential field.

        Parameters
        ----------
            field (MagneticField or callable): magnetic field to fit
                if callable, must accept (num_nodes,3) ndarray as argument
                and output (num_nodes,3) as the B field in cylindrical rpz basis.
            coords (ndarray): shape (num_nodes,3) of R,phi,Z points to fit field at
            max_m (int): maximum m to use for Dommaschk Potentials
            max_l (int): maximum l to use for Dommaschk Potentials
            sym (bool): if field is stellarator symmetric or not.
                if True, only stellarator-symmetric modes will
                be included in the fitting
        """
        # We seek c in  Ac = b
        # A will be the BR, Bphi and BZ from each individual
        # dommaschk potential basis function evaluated at each node
        # c is the dommaschk potential coefficients
        # c will be [B0, a_00, a_10, a_01, a_11... etc]
        # b is the magnetic field at each node which we are fitting

        if not isinstance(field, _MagneticField):
            B = field(coords)
        else:
            B = field.compute_magnetic_field(coords)

        num_nodes = coords.shape[0]  # number of coordinate nodes

        # we will have the rhs be 3*num_nodes in length (bc of vector B)

        #########
        # make b
        #########

        rhs = jnp.vstack((B[:, 0], B[:, 1], B[:, 2])).T.flatten(order="F")

        #####################
        # b is made, now do A
        #####################
        num_modes = (
            1 + (max_l + 1) * (max_m + 1) * 4
            if not sym
            else 1 + (max_l + 1) * (max_m + 1) * 2
        )
        # TODO: technically we can drop some modes
        # since if max_l=0, there are only ever nonzero terms
        # for a and b
        # and if max_m=0, there are only ever nonzero terms
        # for a and c
        # but since we are only fitting in a least squares sense,
        # and max_l and max_m should probably be both nonzero anyways,
        # this is not an issue right now

        A = jnp.zeros((3 * num_nodes, num_modes))

        # mode numbers
        ms = []
        ls = []

        # order of coeffs are B0, a_ml, b_ml, c_ml, d_ml
        coef_ind = 1
        abcd_inds = [[], [], [], []]
        a_s = []
        b_s = []
        c_s = []
        d_s = []
        for l in range(max_l + 1):
            for m in range(max_m + 1):
                if not sym:
                    which_coefs = range(4)  # no sym, use all coefs
                elif l // 2 == 0:
                    which_coefs = [1, 2]  # a=d=0 for even l with sym
                elif l // 2 == 1:
                    which_coefs = [0, 3]  # b=c=0 for odd l with sym
                for which_coef in which_coefs:
                    a = 1 if which_coef == 0 else 0
                    b = 1 if which_coef == 1 else 0
                    c = 1 if which_coef == 2 else 0
                    d = 1 if which_coef == 3 else 0

                    a_s.append(a)
                    b_s.append(b)
                    c_s.append(c)
                    d_s.append(d)
                    ms.append(m)
                    ls.append(l)
                    abcd_inds[which_coef].append(coef_ind)
                    coef_ind += 1

        params = {
            "ms": ms,
            "ls": ls,
            "a_arr": a_s,
            "b_arr": b_s,
            "c_arr": c_s,
            "d_arr": d_s,
            "B0": 0.0,
        }
        n = len(ms)  # how many l-m mode pairs there are, also is len(a_s)

        domm_field = DommaschkPotentialField(0, 0, 0, 0, 0, 0, 1)

        def get_B_dom(coords, X, ms, ls):
            """Fxn wrapper to find jacobian of dommaschk B wrt coefs a,b,c,d."""
            return domm_field.compute_magnetic_field(
                coords,
                params={
                    "ms": jnp.asarray(ms),
                    "ls": jnp.asarray(ls),
                    "a_arr": jnp.asarray(X[1 : n + 1]),
                    "b_arr": jnp.asarray(X[n + 1 : 2 * n + 1]),
                    "c_arr": jnp.asarray(X[2 * n + 1 : 3 * n + 1]),
                    "d_arr": jnp.asarray(X[3 * n + 1 : 4 * n + 1]),
                    "B0": X[0],
                },
            )

        X = []
        for key in ["B0", "a_arr", "b_arr", "c_arr", "d_arr"]:
            obj = params[key]
            if isinstance(obj, list):
                X += obj
            else:
                X += [obj]
        X = jnp.asarray(X)

        jac = jit(jacfwd(get_B_dom, argnums=1))(coords, X, params["ms"], params["ls"])

        A = jac.reshape((rhs.size, len(X)), order="F")

        # now solve Ac=b for the coefficients c

        Ainv = scipy.linalg.pinv(A, rcond=None)
        c = jnp.matmul(Ainv, rhs)

        res = jnp.matmul(A, c) - rhs
        print(f"Mean Residual of fit: {jnp.mean(jnp.abs(res)):1.4e} T")
        print(f"Max Residual of fit: {jnp.max(jnp.abs(res)):1.4e} T")
        print(f"Min Residual of fit: {jnp.min(jnp.abs(res)):1.4e} T")

        # recover the params from the c coefficient vector
        B0 = c[0]

        a_arr = c[1 : n + 1]
        b_arr = c[n + 1 : 2 * n + 1]
        c_arr = c[2 * n + 1 : 3 * n + 1]
        d_arr = c[3 * n + 1 : 4 * n + 1]

        return cls(ms, ls, a_arr, b_arr, c_arr, d_arr, B0)


def field_line_integrate(
    r0, z0, phis, field, params=None, grid=None, rtol=1e-8, atol=1e-8, maxstep=1000
):
    """Trace field lines by integration.

    Parameters
    ----------
    r0, z0 : array-like
        initial starting coordinates for r,z on phi=phis[0] plane
    phis : array-like
        strictly increasing array of toroidal angles to output r,z at
        Note that phis is the geometric toroidal angle for positive Bphi,
        and the negative toroidal angle for negative Bphi
    field : MagneticField
        source of magnetic field to integrate
    params: dict
        parameters passed to field
    grid : Grid, optional
        Collocation points used to discretize source field.
    rtol, atol : float
        relative and absolute tolerances for ode integration
    maxstep : int
        maximum number of steps between different phis

    Returns
    -------
    r, z : ndarray
        arrays of r, z coordinates at specified phi angles

    """
    r0, z0, phis = map(jnp.asarray, (r0, z0, phis))
    assert r0.shape == z0.shape, "r0 and z0 must have the same shape"
    rshape = r0.shape
    r0 = r0.flatten()
    z0 = z0.flatten()
    x0 = jnp.array([r0, phis[0] * jnp.ones_like(r0), z0]).T

    @jit
    def odefun(rpz, s):
        rpz = rpz.reshape((3, -1)).T
        r = rpz[:, 0]
        br, bp, bz = field.compute_magnetic_field(rpz, params, basis="rpz", grid=grid).T
        return jnp.array(
            [r * br / bp * jnp.sign(bp), jnp.sign(bp), r * bz / bp * jnp.sign(bp)]
        ).squeeze()

    intfun = lambda x: odeint(odefun, x, phis, rtol=rtol, atol=atol, mxstep=maxstep)
    x = jnp.vectorize(intfun, signature="(k)->(n,k)")(x0)
    r = x[:, :, 0].T.reshape((len(phis), *rshape))
    z = x[:, :, 2].T.reshape((len(phis), *rshape))
    return r, z


### Dommaschk potential utility functions ###

# based off Representations for vacuum potentials in stellarators
# https://doi.org/10.1016/0010-4655(86)90109-8

# written with naive for loops initially and can jax-ify later

true_fun = lambda m_n: 0.0  # used for returning 0 when conditionals evaluate to True


@jit
def gamma(n):
    """Gamma function, only implemented for integers (equiv to factorial of (n-1))."""
    return jnp.exp(gammaln(n))


@jit
def alpha(m, n):
    """Alpha of eq 27, 1st ind comes from C_m_k, 2nd is the subscript of alpha."""
    # modified for eqns 31 and 32

    def false_fun(m_n):
        m, n = m_n
        return (-1) ** n / (gamma(m + n + 1) * gamma(n + 1) * 2.0 ** (2 * n + m))

    def bool_fun(n):
        return jnp.any(n < 0)

    return cond(
        bool_fun(n),
        true_fun,
        false_fun,
        (
            m,
            n,
        ),
    )


@jit
def alphastar(m, n):
    """Alphastar of eq 27, 1st ind comes from C_m_k, 2nd is the subscript of alpha."""
    # modified for eqns 31 and 32
    def false_fun(m_n):
        m, n = m_n
        return (2 * n + m) * alpha(m, n)

    return cond(jnp.any(n < 0), true_fun, false_fun, (m, n))


@jit
def beta(m, n):
    """Beta of eq 28, modified for eqns 31 and 32."""

    def false_fun(m_n):
        m, n = m_n
        return gamma(m - n) / (gamma(n + 1) * 2.0 ** (2 * n - m + 1))

    return cond(jnp.any(jnp.logical_or(n < 0, n >= m)), true_fun, false_fun, (m, n))


@jit
def betastar(m, n):
    """Beta* of eq 28, modified for eqns 31 and 32."""

    def false_fun(m_n):
        m, n = m_n
        return (2 * n - m) * beta(m, n)

    return cond(jnp.any(jnp.logical_or(n < 0, n >= m)), true_fun, false_fun, (m, n))


@jit
def gamma_n(m, n):
    """gamma_n of eq 33."""

    def body_fun(i, val):
        return val + 1 / i + 1 / (m + i)

    def false_fun(m_n):
        m, n = m_n
        return alpha(m, n) / 2 * fori_loop(1, n, body_fun, 0)

    return cond(jnp.any(n <= 0), true_fun, false_fun, (m, n))


@jit
def gamma_nstar(m, n):
    """gamma_n star of eq 33."""

    def false_fun(m_n):
        m, n = m_n
        return (2 * n + m) * gamma_n(m, n)

    return cond(jnp.any(n <= 0), true_fun, false_fun, (m, n))


@jit
def CD_m_k(R, m, k):
    """Eq 31 of Dommaschk paper."""

    def body_fun(j, val):
        result = (
            val
            + (
                -(
                    alpha(m, j)
                    * (
                        alphastar(m, k - m - j) * jnp.log(R)
                        + gamma_nstar(m, k - m - j)
                        - alpha(m, k - m - j)
                    )
                    - gamma_n(m, j) * alphastar(m, k - m - j)
                    + alpha(m, j) * betastar(m, k - j)
                )
                * R ** (2 * j + m)
            )
            + beta(m, j) * alphastar(m, k - j) * R ** (2 * j - m)
        )
        return result

    return fori_loop(0, k + 1, body_fun, jnp.zeros_like(R))


@jit
def CN_m_k(R, m, k):
    """Eq 32 of Dommaschk paper."""

    def body_fun(j, val):
        result = (
            val
            + (
                (
                    alpha(m, j)
                    * (alpha(m, k - m - j) * jnp.log(R) + gamma_n(m, k - m - j))
                    - gamma_n(m, j) * alpha(m, k - m - j)
                    + alpha(m, j) * beta(m, k - j)
                )
                * R ** (2 * j + m)
            )
            - beta(m, j) * alpha(m, k - j) * R ** (2 * j - m)
        )
        return result

    return fori_loop(0, k + 1, body_fun, jnp.zeros_like(R))


@jit
def D_m_n(R, Z, m, n):
    """D_m_n term in eqn 8 of Dommaschk paper."""
    # the sum comes from fact that D_mn = I_mn and the def of I_mn in eq 2 of the paper

    def body_fun(k, val):
        return val + Z ** (n - 2 * k) / gamma(n - 2 * k + 1) * CD_m_k(R, m, k)

    return fori_loop(0, n // 2 + 1, body_fun, jnp.zeros_like(R))


@jit
def N_m_n(R, Z, m, n):
    """N_m_n term in eqn 9 of Dommaschk paper."""
    # the sum comes from fact that N_mn = I_mn and the def of I_mn in eq 2 of the paper

    def body_fun(k, val):
        return val + Z ** (n - 2 * k) / gamma(n - 2 * k + 1) * CN_m_k(R, m, k)

    return fori_loop(0, n // 2 + 1, body_fun, jnp.zeros_like(R))


@jit
def V_m_l(R, phi, Z, m, l, a, b, c, d):
    """Eq 12 of Dommaschk paper.

    Parameters
    ----------
    R,phi,Z : array-like
        Cylindrical coordinates (1-D arrays of each of size num_eval_pts)
            to evaluate the Dommaschk potential term at.
    m : int
        first index of V_m_l term
    l : int
        second index of V_m_l term
    a : float
        a_m_l coefficient of V_m_l term, which multiplies cos(m*phi)*D_m_l
    b : float
        b_m_l coefficient of V_m_l term, which multiplies sin(m*phi)*D_m_l
    c : float
        c_m_l coefficient of V_m_l term, which multiplies cos(m*phi)*N_m_l-1
    d : float
        d_m_l coefficient of V_m_l term, which multiplies sin(m*phi)*N_m_l-1

    Returns
    -------
    value : array-like
        Value of this V_m_l term evaluated at the given R,phi,Z points
        (same size as the size of the given R,phi, or Z arrays).

    """
    return (a * jnp.cos(m * phi) + b * jnp.sin(m * phi)) * D_m_n(R, Z, m, l) + (
        c * jnp.cos(m * phi) + d * jnp.sin(m * phi)
    ) * N_m_n(R, Z, m, l - 1)


@jit
def dommaschk_potential(R, phi, Z, ms, ls, a_arr, b_arr, c_arr, d_arr, B0=1):
    """Eq 1 of Dommaschk paper.

        this is the total dommaschk potential for
        a given set of m,l indices and their corresponding
        coefficients a_ml, b_ml, c_ml d_ml.

    Parameters
    ----------
    R,phi,Z : array-like
        Cylindrical coordinates (1-D arrays of each of size num_eval_pts)
        to evaluate the Dommaschk potential term at.
    ms : 1D array-like of int
        first indices of V_m_l terms
    ls : 1D array-like of int
        second indices of V_m_l terms
    a_arr : 1D array-like of float
        a_m_l coefficients of V_m_l terms, which multiplies cos(m*phi)*D_m_l
    b_arr : 1D array-like of float
        b_m_l coefficients of V_m_l terms, which multiplies sin(m*phi)*D_m_l
    c_arr : 1D array-like of float
        c_m_l coefficients of V_m_l terms, which multiplies cos(m*phi)*N_m_l-1
    d_arr : 1D array-like of float
        d_m_l coefficients of V_m_l terms, which multiplies sin(m*phi)*N_m_l-1
    B0: float, toroidal magnetic field strength scale, this is the strength of the
        1/R part of the magnetic field and is the Bphi at R=1.

    Returns
    -------
    value : array-like
        Value of the total dommaschk potential evaluated
        at the given R,phi,Z points
        (same size as the size of the given R,phi, Z arrays).
    """
    value = B0 * phi  # phi term

    # make sure all are 1D arrays
    ms = jnp.atleast_1d(ms)
    ls = jnp.atleast_1d(ls)
    a_arr = jnp.atleast_1d(a_arr)
    b_arr = jnp.atleast_1d(b_arr)
    c_arr = jnp.atleast_1d(c_arr)
    d_arr = jnp.atleast_1d(d_arr)
    for m, l, a, b, c, d in zip(ms, ls, a_arr, b_arr, c_arr, d_arr):
        value += V_m_l(R, phi, Z, m, l, a, b, c, d)

    return value


def read_mgrid(
    mgrid_file,
    extcur=1,
):
    """Read an "mgrid" file from MAKEGRID and return the grid and magnetic field.

    Parameters
    ----------
    mgrid_file : str or path-like
        path to mgrid file in netCDF format
    extcur : array-like
        currents for each subset of the field

    """
    mgrid = Dataset(mgrid_file, "r")
    ir = int(mgrid["ir"][()])
    jz = int(mgrid["jz"][()])
    kp = int(mgrid["kp"][()])
    nfp = mgrid["nfp"][()].data
    nextcur = int(mgrid["nextcur"][()])
    rMin = mgrid["rmin"][()]
    rMax = mgrid["rmax"][()]
    zMin = mgrid["zmin"][()]
    zMax = mgrid["zmax"][()]

    br = np.zeros([kp, jz, ir])
    bp = np.zeros([kp, jz, ir])
    bz = np.zeros([kp, jz, ir])
    extcur = np.broadcast_to(extcur, nextcur)
    for i in range(nextcur):

        # apply scaling by currents given in VMEC input file
        scale = extcur[i]

        # sum up contributions from different coils
        coil_id = "%03d" % (i + 1,)
        br[:, :, :] += scale * mgrid["br_" + coil_id][()]
        bp[:, :, :] += scale * mgrid["bp_" + coil_id][()]
        bz[:, :, :] += scale * mgrid["bz_" + coil_id][()]
    mgrid.close()

    # shift axes to correct order
    br = np.moveaxis(br, (0, 1, 2), (1, 2, 0))
    bp = np.moveaxis(bp, (0, 1, 2), (1, 2, 0))
    bz = np.moveaxis(bz, (0, 1, 2), (1, 2, 0))

    # re-compute grid knots in radial and vertical direction
    Rgrid = np.linspace(rMin, rMax, ir)
    Zgrid = np.linspace(zMin, zMax, jz)
    pgrid = 2.0 * np.pi / (nfp * kp) * np.arange(kp)

    return Rgrid, Zgrid, pgrid, br, bp, bz, nfp


class CurrentPotentialField(_MagneticField, FourierRZToroidalSurface):
    """Magnetic field due to a surface current potential on a toroidal surface.

        surface current K is assumed given by
         K = n x ∇ Φ
        where:
               n is the winding surface unit normal.
               Phi is the current potential function,
                which is a function of theta and zeta.
        This function then uses biot-savart to find the
        B field from this current density K on the surface.

    Parameters
    ----------
    potential : callable
        function to compute the current potential. Should have a signature of
        the form potential(theta,zeta,**params) -> ndarray.
        theta,zeta are poloidal and toroidal angles on the surface
    potential_dtheta: callable
        function to compute the theta derivative of the current potential
    potential_dzeta: callable
        function to compute the zeta derivative of the current potential
    params : dict, optional
        default parameters to pass to potential function (and its derivatives)
    R_lmn, Z_lmn : array-like, shape(k,)
        Fourier coefficients for winding surface R and Z in cylindrical coordinates
    modes_R : array-like, shape(k,2)
        poloidal and toroidal mode numbers [m,n] for R_lmn.
    modes_Z : array-like, shape(k,2)
        mode numbers associated with Z_lmn, defaults to modes_R
    NFP : int
        number of field periods
    sym : bool
        whether to enforce stellarator symmetry for the surface geometry.
        Default is "auto" which enforces if modes are symmetric. If True,
        non-symmetric modes will be truncated.
    name : str
        name for this field
    check_orientation : bool
        ensure that this surface has a right handed orientation. Do not set to False
        unless you are sure the parameterization you have given is right handed
        (ie, e_theta x e_zeta points outward from the surface).

    """

    _io_attrs_ = (
        _MagneticField._io_attrs_
        + FourierRZToroidalSurface._io_attrs_
        + [
            "_surface_grid",
            "_params",
        ]
    )

    def __init__(
        self,
        potential,
        potential_dtheta,
        potential_dzeta,
        params=None,
        R_lmn=None,
        Z_lmn=None,
        modes_R=None,
        modes_Z=None,
        NFP=1,
        sym="auto",
        name="",
        check_orientation=True,
    ):
        assert callable(potential), "Potential must be callable!"
        assert callable(potential_dtheta), "Potential derivative must be callable!"
        assert callable(potential_dzeta), "Potential derivative must be callable!"

        self._potential = potential
        self._potential_dtheta = potential_dtheta
        self._potential_dzeta = potential_dzeta
        self._params = params

        super().__init__(
            R_lmn,
            Z_lmn,
            modes_R,
            modes_Z,
            NFP,
            sym,
            name=name,
            check_orientation=check_orientation,
        )

    @property
    def params(self):
        """Dict of parameters to pass to potential function and its derivatives."""
        return self._params

    @params.setter
    def params(self, new):
        warnif(
            len(new) != len(self._params),
            UserWarning,
            "Length of new params is different from length of current params! "
            "May cause errors unless potential function is also changed.",
        )
        self._params = new

    @property
    def potential(self):
        """Potential function, signature (theta,zeta,**params) -> potential value."""
        return self._potential

    @potential.setter
    def potential(self, new):
        if new != self._potential:
            assert callable(new), "Potential must be callable!"
            self._potential = new

    @property
    def potential_dtheta(self):
        """Phi poloidal deriv. function, signature (theta,zeta,**params) -> value."""
        return self._potential_dtheta

    @potential_dtheta.setter
    def potential_dtheta(self, new):
        if new != self._potential_dtheta:
            assert callable(new), "Potential derivative must be callable!"
            self._potential_dtheta = new

    @property
    def potential_dzeta(self):
        """Phi toroidal deriv. function, signature (theta,zeta,**params) -> value."""
        return self._potential_dzeta

    @potential_dzeta.setter
    def potential_dzeta(self, new):
        if new != self._potential_dzeta:
            assert callable(new), "Potential derivative must be callable!"
            self._potential_dzeta = new

    def save(self, file_name, file_format=None, file_mode="w"):
        """Save the object.

        **Not supported for this object!

        Parameters
        ----------
        file_name : str file path OR file instance
            location to save object
        file_format : str (Default hdf5)
            format of save file. Only used if file_name is a file path
        file_mode : str (Default w - overwrite)
            mode for save file. Only used if file_name is a file path

        """
        raise OSError(
            "Saving CurrentPotentialField is not supported,"
            " as the potential function cannot be serialized."
        )

    def compute_magnetic_field(self, coords, params=None, basis="rpz", grid=None):
        """Compute magnetic field at a set of points.

        Parameters
        ----------
        coords : array-like shape(N,3) or Grid
            cylindrical or cartesian coordinates
        params : dict, optional
            parameters to pass to compute function
            should include the potential
        basis : {"rpz", "xyz"}
            basis for input coordinates and returned magnetic field
        grid : Grid,
            source grid upon which to evaluate the surface current density K

        Returns
        -------
        field : ndarray, shape(N,3)
            magnetic field at specified points

        """
        return _compute_magnetic_field_from_CurrentPotentialField(
            field=self, coords=coords, params=params, basis=basis, grid=grid
        )

    @classmethod
    def from_surface(
        cls,
        surface,
        potential,
        potential_dtheta,
        potential_dzeta,
        params=None,
    ):
        """Create CurrentPotentialField using geometry provided by given surface.

        Parameters
        ----------
        surface: FourierRZToroidalSurface, optional, default None
            Existing FourierRZToroidalSurface object to create a
            CurrentPotentialField with.
        potential : callable
            function to compute the current potential. Should have a signature of
            the form potential(theta,zeta,**params) -> ndarray.
            theta,zeta are poloidal and toroidal angles on the surface
        potential_dtheta: callable
            function to compute the theta derivative of the current potential
        potential_dzeta: callable
            function to compute the zeta derivative of the current potential
        params : dict, optional
            default parameters to pass to potential function (and its derivatives)

        """
        errorif(
            not isinstance(surface, FourierRZToroidalSurface),
            TypeError,
            "Expected type FourierRZToroidalSurface for argument surface, "
            f"instead got type {type(surface)}",
        )

        R_lmn = surface.R_lmn
        Z_lmn = surface.Z_lmn
        modes_R = surface._R_basis.modes[:, 1:]
        modes_Z = surface._Z_basis.modes[:, 1:]
        NFP = surface.NFP
        sym = surface.sym
        name = surface.name

        return cls(
            potential,
            potential_dtheta,
            potential_dzeta,
            params,
            R_lmn,
            Z_lmn,
            modes_R,
            modes_Z,
            NFP,
            sym,
            name=name,
            check_orientation=False,
        )


class FourierCurrentPotentialField(_MagneticField, FourierRZToroidalSurface):
    """Magnetic field due to a surface current potential on a toroidal surface.

        surface current K is assumed given by

        K = n x ∇ Φ
        Φ(θ,ζ) = Φₛᵥ(θ,ζ) + Gζ/2π + Iθ/2π

        where:
              n is the winding surface unit normal.
              Phi is the current potential function,
                which is a function of theta and zeta,
                and is given as a secular linear term in theta/zeta
                and a double Fourier series in theta/zeta.
        This function then uses biot-savart to find the
        B field from this current density K on the surface.

    Parameters
    ----------
    Phi_mn : ndarray
        Fourier coefficients of the double FourierSeries part of the current potential.
    modes_Phi : array-like, shape(k,2)
        Poloidal and Toroidal mode numbers corresponding to passed-in Phi_mn
        coefficients.
    I : float
        Net current linking the plasma and the surface toroidally
        Denoted I in the algorithm
    G : float
        Net current linking the plasma and the surface poloidally
        Denoted G in the algorithm
        NOTE: a negative G will tend to produce a positive toroidal magnetic field
        B in DESC, as in DESC the poloidal angle is taken to be positive
        and increasing when going in the clockwise direction, which with the
        convention n x grad(phi) will result in a toroidal field in the negative
        toroidal direction.
    sym_Phi :  {"auto","cos","sin",False}
        whether to enforce a given symmetry for the DoubleFourierSeries part of the
        current potential. Default is "auto" which enforces if modes are symmetric.
        If True, non-symmetric modes will be truncated.
    R_lmn, Z_lmn : array-like, shape(k,)
        Fourier coefficients for winding surface R and Z in cylindrical coordinates
    modes_R : array-like, shape(k,2)
        poloidal and toroidal mode numbers [m,n] for R_lmn.
    modes_Z : array-like, shape(k,2)
        mode numbers associated with Z_lmn, defaults to modes_R
    NFP : int
        number of field periods
    sym : bool
        whether to enforce stellarator symmetry for the surface geometry.
        Default is "auto" which enforces if modes are symmetric. If True,
        non-symmetric modes will be truncated.
    name : str
        name for this field
    check_orientation : bool
        ensure that this surface has a right handed orientation. Do not set to False
        unless you are sure the parameterization you have given is right handed
        (ie, e_theta x e_zeta points outward from the surface).

    """

    _io_attrs_ = (
        _MagneticField._io_attrs_
        + FourierRZToroidalSurface._io_attrs_
        + ["_surface_grid", "_Phi_mn", "_I", "_G"]
    )

    def __init__(
        self,
        Phi_mn=np.array([0.0]),
        modes_Phi=np.array([[0, 0]]),
        I=0,
        G=0,
        sym_Phi="auto",
        R_lmn=None,
        Z_lmn=None,
        modes_R=None,
        modes_Z=None,
        NFP=1,
        sym="auto",
        name="",
        check_orientation=True,
    ):
        self._Phi_mn = Phi_mn

        Phi_mn, modes_Phi = map(np.asarray, (Phi_mn, modes_Phi))

        assert np.issubdtype(modes_Phi.dtype, np.integer)

        M_Phi = np.max(abs(modes_Phi[:, 0]))
        N_Phi = np.max(abs(modes_Phi[:, 1]))

        self._M_Phi = M_Phi
        self._N_Phi = N_Phi

        if sym_Phi == "auto":
            if np.all(
                Phi_mn[np.where(sign(modes_Phi[:, 0]) == sign(modes_Phi[:, 1]))] == 0
            ):
                sym_Phi = "sin"
            elif np.all(
                Phi_mn[np.where(sign(modes_Phi[:, 0]) != sign(modes_Phi[:, 1]))] == 0
            ):
                sym_Phi = "cos"
            else:
                sym_Phi = False
            # catch case where only (0,0) mode is given as 0
            if np.all(Phi_mn == 0.0) and np.all(modes_Phi == 0):
                sym_Phi = "cos"
        self._sym_Phi = sym_Phi
        self._Phi_basis = DoubleFourierSeries(M=M_Phi, N=N_Phi, NFP=NFP, sym=sym_Phi)

        assert np.isscalar(I), "I must be a scalar"
        assert np.isscalar(G), "G must be a scalar"
        self._I = float(I)
        self._G = float(G)

        super().__init__(
            R_lmn,
            Z_lmn,
            modes_R,
            modes_Z,
            NFP,
            sym,
            name=name,
            check_orientation=check_orientation,
        )

    @property
    def I(self):  # noqa: E743
        """Net current linking the plasma and the surface toroidally."""
        return self._I

    @I.setter
    def I(self, new):  # noqa: E743
        assert np.isscalar(new), "I must be a scalar"
        self._I = float(new)

    @property
    def G(self):
        """Net current linking the plasma and the surface poloidally."""
        return self._G

    @G.setter
    def G(self, new):
        assert np.isscalar(new), "G must be a scalar"
        self._G = float(new)

    @property
    def Phi_mn(self):
        """Fourier coefficients describing single-valued part of potential."""
        return self._Phi_mn

    @Phi_mn.setter
    def Phi_mn(self, new):
        if len(new) == self.Phi_basis.num_modes:
            self._Phi_mn = jnp.asarray(new)
        else:
            raise ValueError(
                f"Phi_mn should have the same size as the basis, got {len(new)} for "
                + f"basis with {self.Phi_basis.num_modes} modes."
            )

    @property
    def Phi_basis(self):
        """DoubleFourierSeries: Spectral basis for Phi."""
        return self._Phi_basis

    @property
    def sym_Phi(self):
        """str: Type of symmetry of periodic part of Phi (no symmetry if False)."""
        return self._sym_Phi

    def change_Phi_resolution(self, M=None, N=None, NFP=None, sym_Phi=None):
        """Change the maximum poloidal and toroidal resolution for Phi.

        Parameters
        ----------
        M : int
            Poloidal resolution to change Phi basis to.
            If None, defaults to current self.Phi_basis poloidal resolution
        N : int
            Toroidal resolution to change Phi basis to.
            If None, defaults to current self.Phi_basis toroidal resolution
        NFP : int
            Number of field periods for surface and Phi basis.
            If None, defaults to current NFP.
            Note: will change the NFP of the surface geometry as well as the
            Phi basis.
        sym_Phi :  {"auto","cos","sin",False}
            whether to enforce a given symmetry for the DoubleFourierSeries part of the
            current potential. Default is "auto" which enforces if modes are symmetric.
            If True, non-symmetric modes will be truncated.

        """
        M = self._M_Phi or M
        N = self._M_Phi or N
        NFP = NFP or self.NFP
        sym_Phi = sym_Phi or self.sym_Phi

        Phi_modes_old = self.Phi_basis.modes
        self.Phi_basis.change_resolution(M=M, N=N, NFP=self.NFP, sym=sym_Phi)

        self._Phi_mn = copy_coeffs(self.Phi_mn, Phi_modes_old, self.Phi_basis.modes)
        self._M_Phi = M
        self._N_Phi = N
        self._sym_Phi = sym_Phi
        self.change_resolution(
            NFP=NFP
        )  # make sure surface and Phi basis NFP are the same

    def compute_magnetic_field(self, coords, params=None, basis="rpz", grid=None):
        """Compute magnetic field at a set of points.

        Parameters
        ----------
        coords : array-like shape(N,3) or Grid
            cylindrical or cartesian coordinates
        params : dict, optional
            parameters to pass to compute function
            should include the potential
        basis : {"rpz", "xyz"}
            basis for input coordinates and returned magnetic field
        grid : Grid,
            grid upon which to evaluate the surface current density K

        Returns
        -------
        field : ndarray, shape(N,3)
            magnetic field at specified points

        """
        grid = grid or LinearGrid(
            M=self._M_Phi * 3 + 1, N=self._N_Phi * 3 + 1, NFP=self.NFP
        )
        return _compute_magnetic_field_from_CurrentPotentialField(
            field=self, coords=coords, params=params, basis=basis, grid=grid
        )

    @classmethod
    def from_surface(
        cls,
        surface,
        Phi_mn=np.array([0.0]),
        modes_Phi=np.array([[0, 0]]),
        I=0,
        G=0,
        sym_Phi="auto",
    ):
        """Create FourierCurrentPotentialField using geometry of given surface.

        Parameters
        ----------
        surface: FourierRZToroidalSurface, optional, default None
            Existing FourierRZToroidalSurface object to create a
            CurrentPotentialField with.
        Phi_mn : ndarray
            Fourier coefficients of the double FourierSeries of the current potential.
            Should correspond to the given DoubleFourierSeries basis object passed in.
        modes_Phi : array-like, shape(k,2)
            Poloidal and Toroidal mode numbers corresponding to passed-in Phi_mn
            coefficients
        I : float
            Net current linking the plasma and the surface toroidally
            Denoted I in the algorithm
        G : float
            Net current linking the plasma and the surface poloidally
            Denoted G in the algorithm
            NOTE: a negative G will tend to produce a positive toroidal magnetic field
            B in DESC, as in DESC the poloidal angle is taken to be positive
            and increasing when going in the clockwise direction, which with the
            convention n x grad(phi) will result in a toroidal field in the negative
            toroidal direction.
        name : str
            name for this field
        check_orientation : bool
            ensure that this surface has a right handed orientation. Do not set to False
            unless you are sure the parameterization you have given is right handed
            (ie, e_theta x e_zeta points outward from the surface).

        """
        if not isinstance(surface, FourierRZToroidalSurface):
            raise TypeError(
                "Expected type FourierRZToroidalSurface for argument surface, "
                f"instead got type {type(surface)}"
            )
        R_lmn = surface.R_lmn
        Z_lmn = surface.Z_lmn
        modes_R = surface._R_basis.modes[:, 1:]
        modes_Z = surface._Z_basis.modes[:, 1:]
        NFP = surface.NFP
        sym = surface.sym
        name = surface.name

        return cls(
            Phi_mn,
            modes_Phi,
            I,
            G,
            sym_Phi,
            R_lmn,
            Z_lmn,
            modes_R,
            modes_Z,
            NFP,
            sym,
            name=name,
            check_orientation=False,
        )


def _compute_magnetic_field_from_CurrentPotentialField(
    field, coords, params=None, basis="rpz", grid=None
):
    """Compute magnetic field at a set of points.

    Parameters
    ----------
    field : CurrentPotentialField or FourierCurrentPotentialField
        current potential field object from which to compute magnetic field.
    coords : array-like shape(N,3) or Grid
        cylindrical or cartesian coordinates
    params : dict, optional
        parameters to pass to compute function
        should include the potential
    basis : {"rpz", "xyz"}
        basis for input coordinates and returned magnetic field
    grid : Grid,
        source grid upon which to evaluate the surface current density K

    Returns
    -------
    field : ndarray, shape(N,3)
        magnetic field at specified points

    """
    assert basis.lower() in ["rpz", "xyz"]
    if hasattr(coords, "nodes"):
        coords = coords.nodes
    coords = jnp.atleast_2d(coords)
    if basis == "rpz":
        coords = rpz2xyz(coords)
    surface_grid = grid or LinearGrid(M=30, N=30, NFP=field.NFP)

    # compute surface current, and store grid quantities
    # needed for integration in class
    # TODO: does this have to be xyz, or can it be computed in rpz as well?
    data = field.compute(["K", "x"], grid=surface_grid, basis="xyz", params=params)

    _rs = xyz2rpz(data["x"])
    _K = xyz2rpz_vec(data["K"], phi=surface_grid.nodes[:, 2])

    # surface element, must divide by NFP to remove the NFP multiple on the
    # surface grid weights, as we account for that when doing the for loop
    # over NFP
    _dV = surface_grid.weights * data["|e_theta x e_zeta|"] / surface_grid.NFP

    def nfp_loop(j, f):
        # calculate (by rotating) rs, rs_t, rz_t
        phi = (surface_grid.nodes[:, 2] + j * 2 * jnp.pi / surface_grid.NFP) % (
            2 * jnp.pi
        )
        # new coords are just old R,Z at a new phi (bc of discrete NFP symmetry)
        rs = jnp.vstack((_rs[:, 0], phi, _rs[:, 2])).T
        rs = rpz2xyz(rs)
        K = rpz2xyz_vec(_K, phi=phi)
        fj = biot_savart_general(
            coords,
            rs,
            K,
            _dV,
        )
        f += fj
        return f

    B = fori_loop(0, surface_grid.NFP, nfp_loop, jnp.zeros_like(coords))
    if basis == "rpz":
        B = xyz2rpz_vec(B, x=coords[:, 0], y=coords[:, 1])
    return B
