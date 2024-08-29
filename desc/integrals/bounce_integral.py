"""Methods for computing bounce integrals (singular or otherwise)."""

import numpy as np
from interpax import CubicHermiteSpline, PPoly
from orthax.legendre import leggauss

from desc.backend import jnp
from desc.integrals.bounce_utils import (
    _check_bounce_points,
    _set_default_plot_kwargs,
    bounce_points,
    bounce_quadrature,
    get_pitch_inv,
    interp_to_argmin,
    plot_ppoly,
)
from desc.integrals.interp_utils import polyder_vec
from desc.integrals.quad_utils import (
    automorphism_sin,
    get_quadrature,
    grad_automorphism_sin,
)
from desc.io import IOAble
from desc.utils import atleast_nd, errorif, setdefault, warnif


class Bounce1D(IOAble):
    """Computes bounce integrals using one-dimensional local spline methods.

    The bounce integral is defined as ∫ f(ℓ) dℓ, where
        dℓ parameterizes the distance along the field line in meters,
        f(ℓ) is the quantity to integrate along the field line,
        and the boundaries of the integral are bounce points ζ₁, ζ₂ s.t. λ|B|(ζᵢ) = 1,
        where λ is a constant proportional to the magnetic moment over energy
        and |B| is the norm of the magnetic field.

    For a particle with fixed λ, bounce points are defined to be the location on the
    field line such that the particle's velocity parallel to the magnetic field is zero.
    The bounce integral is defined up to a sign. We choose the sign that corresponds to
    the particle's guiding center trajectory traveling in the direction of increasing
    field-line-following coordinate ζ.

    Notes
    -----
    Brief description of algorithm for developers.

    For applications which reduce to computing a nonlinear function of distance
    along field lines between bounce points, it is required to identify these
    points with field-line-following coordinates. (In the special case of a linear
    function summing integrals between bounce points over a flux surface, arbitrary
    coordinate systems may be used as this operation reduces to a surface integral,
    which is invariant to the order of summation).

    The DESC coordinate system is related to field-line-following coordinate
    systems by a relation whose solution is best found with Newton iteration.
    There is a unique real solution to this equation, so Newton iteration is a
    globally convergent root-finding algorithm here. For the task of finding
    bounce points, even if the inverse map: θ(α, ζ) was known, Newton iteration
    is not a globally convergent algorithm to find the real roots of
    f : ζ ↦ |B|(ζ) − 1/λ where ζ is a field-line-following coordinate.
    For this, function approximation of |B| is necessary.

    The function approximation in ``Bounce1D`` is ignorant that the objects to
    approximate are defined on a bounded subset of ℝ². Instead, the domain is
    projected to ℝ, where information sampled about the function at infinity
    cannot support reconstruction of the function near the origin. As the
    functions of interest do not vanish at infinity, pseudo-spectral techniques
    are not used. Instead, function approximation is done with local splines.
    This is useful if one can efficiently obtain data along field lines and
    most efficient if the number of toroidal transit to follow a field line is
    not too large.

    After obtaining the bounce points, the supplied quadrature is performed.
    By default, this is a Gauss quadrature after removing the singularity.
    Local splines interpolate functions in the integrand to the quadrature nodes.

    See Also
    --------
    Bounce2D : Uses two-dimensional pseudo-spectral techniques for the same task.

    Examples
    --------
    See ``tests/test_integrals.py::TestBounce1D::test_bounce1d_checks``.

    Attributes
    ----------
    required_names : list
        Names in ``data_index`` required to compute bounce integrals.
    B : jnp.ndarray
        Shape (M, L, N - 1, B.shape[-1]).
        Polynomial coefficients of the spline of |B| in local power basis.
        Last axis enumerates the coefficients of power series. For a polynomial
        given by ∑ᵢⁿ cᵢ xⁱ, coefficient cᵢ is stored at ``B[...,n-i]``.
        Third axis enumerates the polynomials that compose a particular spline.
        Second axis enumerates flux surfaces.
        First axis enumerates field lines of a particular flux surface.

    """

    required_names = ["B^zeta", "B^zeta_z|r,a", "|B|", "|B|_z|r,a"]
    get_pitch_inv = staticmethod(get_pitch_inv)

    def __init__(
        self,
        grid,
        data,
        quad=leggauss(32),
        automorphism=(automorphism_sin, grad_automorphism_sin),
        Bref=1.0,
        Lref=1.0,
        check=False,
        **kwargs,
    ):
        """Returns an object to compute bounce integrals.

        Parameters
        ----------
        grid : Grid
            Clebsch coordinate (ρ, α, ζ) tensor-product grid.
            The ζ coordinates (the unique values prior to taking the tensor-product)
            must be strictly increasing and preferably uniformly spaced. These are used
            as knots to construct splines. A reference knot density is 100 knots per
            toroidal transit. Note that below shape notation defines
            L = ``grid.num_rho``, M = ``grid.num_alpha``, and N = ``grid.num_zeta``.
        data : dict[str, jnp.ndarray]
            Data evaluated on ``grid``.
            Must include names in ``Bounce1D.required_names``.
        quad : (jnp.ndarray, jnp.ndarray)
            Quadrature points xₖ and weights wₖ for the approximate evaluation of an
            integral ∫₋₁¹ g(x) dx = ∑ₖ wₖ g(xₖ). Default is 32 points.
        automorphism : (Callable, Callable) or None
            The first callable should be an automorphism of the real interval [-1, 1].
            The second callable should be the derivative of the first. This map defines
            a change of variable for the bounce integral. The choice made for the
            automorphism will affect the performance of the quadrature method.
        Bref : float
            Optional. Reference magnetic field strength for normalization.
        Lref : float
            Optional. Reference length scale for normalization.
        check : bool
            Flag for debugging. Must be false for JAX transformations.

        """
        # Strictly increasing zeta knots enforces dζ > 0.
        # To retain dℓ = (|B|/B^ζ) dζ > 0 after fixing dζ > 0, we require
        # B^ζ = B⋅∇ζ > 0. This is equivalent to changing the sign of ∇ζ or [∂ℓ/∂ζ]|ρ,a.
        # Recall dζ = ∇ζ⋅dR, implying 1 = ∇ζ⋅(e_ζ|ρ,a). Hence, a sign change in ∇ζ
        # requires the same sign change in e_ζ|ρ,a to retain the metric identity.
        warnif(
            check and kwargs.pop("warn", True) and jnp.any(data["B^zeta"] <= 0),
            msg="(∂ℓ/∂ζ)|ρ,a > 0 is required. Enforcing positive B^ζ.",
        )
        data = {
            "B^zeta": jnp.abs(data["B^zeta"]) * Lref / Bref,
            "B^zeta_z|r,a": data["B^zeta_z|r,a"]
            * jnp.sign(data["B^zeta"])
            * Lref
            / Bref,
            "|B|": data["|B|"] / Bref,
            "|B|_z|r,a": data["|B|_z|r,a"] / Bref,  # This is already the correct sign.
        }
        self._data = dict(zip(data.keys(), Bounce1D.reshape_data(grid, *data.values())))
        self._x, self._w = get_quadrature(quad, automorphism)

        # Compute local splines.
        self._zeta = grid.compress(grid.nodes[:, 2], surface_label="zeta")
        self.B = jnp.moveaxis(
            CubicHermiteSpline(
                x=self._zeta,
                y=self._data["|B|"],
                dydx=self._data["|B|_z|r,a"],
                axis=-1,
                check=check,
            ).c,
            source=(0, 1),
            destination=(-1, -2),
        )
        assert self.B.shape == (grid.num_alpha, grid.num_rho, grid.num_zeta - 1, 4)
        self._dB_dz = polyder_vec(self.B)
        assert self._dB_dz.shape == (grid.num_alpha, grid.num_rho, grid.num_zeta - 1, 3)

    @staticmethod
    def reshape_data(grid, *arys):
        """Reshape arrays for acceptable input to ``integrate``.

        Parameters
        ----------
        grid : Grid
            Clebsch coordinate (ρ, α, ζ) tensor-product grid.
        arys : jnp.ndarray
            Data evaluated on grid.

        Returns
        -------
        f : list[jnp.ndarray]
            List of reshaped data which may be given to ``integrate``.

        """
        f = [grid.meshgrid_reshape(d, "arz") for d in arys]
        return f

    def points(self, pitch_inv, num_well=None):
        """Compute bounce points.

        Notes
        -----
        Only the dimensions following L are required. The leading axes are batch axes.

        Parameters
        ----------
        pitch_inv : jnp.ndarray
            Shape (P, M, L).
            1/λ values to evaluate the bounce integral at each field line. 1/λ(ρ,α) is
            specified by ``pitch_inv[...,α,ρ]`` where in the latter the labels
            are interpreted as the index into the last axis that corresponds to
            that field line.
        num_well : int or None
            Specify to return the first ``num_well`` pairs of bounce points for each
            pitch along each field line. This is useful if ``num_well`` tightly
            bounds the actual number. As a reference, there are typically 20 wells
            per toroidal transit for a given pitch. You can check this by plotting
            the field lines with the ``check_points`` method.

            If not specified, then all bounce points are returned. If there were fewer
            wells detected along a field line than the size of the last axis of the
            returned arrays, then that axis is padded with zero.

        Returns
        -------
        z1, z2 : (jnp.ndarray, jnp.ndarray)
            Shape (P, M, L, num_well).
            ζ coordinates of bounce points. The points are ordered and grouped such
            that the straight line path between ``z1`` and ``z2`` resides in the
            epigraph of |B|.

            If there were less than ``num_wells`` wells detected along a field line,
            then the last axis, which enumerates bounce points for a particular field
            line and pitch, is padded with zero.

        """
        return bounce_points(pitch_inv, self._zeta, self.B, self._dB_dz, num_well)

    def check_points(self, z1, z2, pitch_inv, plot=True, **kwargs):
        """Check that bounce points are computed correctly.

        Parameters
        ----------
        z1, z2 : (jnp.ndarray, jnp.ndarray)
            Shape (P, M, L, num_well).
            ζ coordinates of bounce points. The points are ordered and grouped such
            that the straight line path between ``z1`` and ``z2`` resides in the
            epigraph of |B|.
        pitch_inv : jnp.ndarray
            Shape (P, M, L).
            1/λ values to evaluate the bounce integral at each field line. 1/λ(ρ,α) is
            specified by ``pitch_inv[...,α,ρ]`` where in the latter the labels
            are interpreted as the index into the last axis that corresponds to
            that field line.
        plot : bool
            Whether to plot stuff.
        kwargs
            Keyword arguments into ``self.plot_ppoly``.

        Returns
        -------
        plots : list
            Matplotlib (fig, ax) tuples for the 1D plot of each field line.

        """
        return _check_bounce_points(
            z1=z1,
            z2=z2,
            pitch_inv=atleast_nd(3, pitch_inv),
            knots=self._zeta,
            B=self.B,
            plot=plot,
            **kwargs,
        )

    def integrate(
        self,
        pitch_inv,
        integrand,
        f=None,
        weight=None,
        num_well=None,
        method="cubic",
        batch=True,
        check=False,
    ):
        """Bounce integrate ∫ f(ℓ) dℓ.

        Computes the bounce integral ∫ f(ℓ) dℓ for every specified field line
        for every λ value in ``pitch_inv``.

        Notes
        -----
        Only the dimensions following L are required. The leading axes are batch axes.

        Parameters
        ----------
        pitch_inv : jnp.ndarray
            Shape (P, M, L).
            1/λ values to evaluate the bounce integral at each field line. 1/λ(ρ,α) is
            specified by ``pitch_inv[...,α,ρ]`` where in the latter the labels
            are interpreted as the index into the last axis that corresponds to
            that field line.
        integrand : callable
            The composition operator on the set of functions in ``f`` that maps the
            functions in ``f`` to the integrand f(ℓ) in ∫ f(ℓ) dℓ. It should accept the
            arrays in ``f`` as arguments as well as the additional keyword arguments:
            ``B`` and ``pitch``. A quadrature will be performed to approximate the
            bounce integral of ``integrand(*f,B=B,pitch=pitch)``.
        f : list[jnp.ndarray]
            Shape (M, L, N).
            Real scalar-valued functions evaluated on the ``grid`` supplied to
            construct this object. These functions should be arguments to the callable
            ``integrand``. Use the method ``self.reshape_data`` to reshape the data
            into the expected shape.
        weight : jnp.ndarray
            Shape (M, L, N).
            If supplied, the bounce integral labeled by well j is weighted such that
            the returned value is w(j) ∫ f(ℓ) dℓ, where w(j) is ``weight``
            interpolated to the deepest point in the magnetic well. Use the method
            ``self.reshape_data`` to reshape the data into the expected shape.
        num_well : int or None
            Specify to return the first ``num_well`` pairs of bounce points for each
            pitch along each field line. This is useful if ``num_well`` tightly
            bounds the actual number. As a reference, there are typically 20 wells
            per toroidal transit for a given pitch. You can check this by plotting
            the field lines with the ``check_points`` method.

            If not specified, then all bounce points are returned. If there were fewer
            wells detected along a field line than the size of the last axis of the
            returned arrays, then that axis is padded with zero.
        method : str
            Method of interpolation.
            See https://interpax.readthedocs.io/en/latest/_api/interpax.interp1d.html.
            Default is cubic C1 local spline.
        batch : bool
            Whether to perform computation in a batched manner. Default is true.
        check : bool
            Flag for debugging. Must be false for JAX transformations.

        Returns
        -------
        result : jnp.ndarray
            Shape (P, M, L, num_well).
            Last axis enumerates the bounce integrals for a given pitch, field line,
            and flux surface.

        """
        pitch_inv = atleast_nd(3, pitch_inv)
        z1, z2 = self.points(pitch_inv, num_well)
        result = bounce_quadrature(
            x=self._x,
            w=self._w,
            z1=z1,
            z2=z2,
            pitch_inv=pitch_inv,
            integrand=integrand,
            f=setdefault(f, []),
            data=self._data,
            knots=self._zeta,
            method=method,
            batch=batch,
            check=check,
        )
        if weight is not None:
            result *= interp_to_argmin(
                weight,
                z1,
                z2,
                self._zeta,
                self.B,
                self._dB_dz,
                method,
            )
        assert result.shape[0] == pitch_inv.shape[0]
        assert result.shape[-1] == setdefault(num_well, np.prod(self._dB_dz.shape[-2:]))
        return result

    def plot(self, pitch_inv, m, l, **kwargs):
        """Plot the field line and bounce points of the given pitch angles.

        Parameters
        ----------
        pitch_inv : jnp.ndarray
            Shape (P, ).
            1/λ values to evaluate the bounce integral at the field line
            specified by the (α(m), ρ(l)) Clebsch coordinate.
        m, l : int, int
            Indices into the nodes of the grid supplied to make this object.
            ``alpha, rho = grid.meshgrid_reshape(grid.nodes[:, :2], "arz")[m, l, 0]``.
        kwargs
            Keyword arguments into ``desc/integrals/bounce_utils.py::plot_ppoly``.

        Returns
        -------
        fig, ax
            Matplotlib (fig, ax) tuple.

        """
        pitch_inv = jnp.atleast_1d(jnp.squeeze(pitch_inv))
        errorif(
            pitch_inv.ndim != 1,
            msg=f"Got pitch_inv.ndim={pitch_inv.ndim}, but expected 1.",
        )
        z1, z2 = bounce_points(
            pitch_inv[:, jnp.newaxis, jnp.newaxis],
            self._zeta,
            self.B[m, l],
            self._dB_dz[m, l],
        )
        fig, ax = plot_ppoly(
            ppoly=PPoly(self.B[m, l].T, self._zeta),
            z1=z1,
            z2=z2,
            k=pitch_inv,
            **_set_default_plot_kwargs(kwargs),
        )
        return fig, ax
