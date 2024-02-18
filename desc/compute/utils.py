"""Functions for flux surface averages and vector algebra operations."""

import copy
import inspect
import warnings

import numpy as np
from scipy.interpolate import CubicHermiteSpline, CubicSpline
from termcolor import colored

from desc.backend import complex_sqrt, cond, fori_loop, jnp, put
from desc.grid import ConcentricGrid, Grid, LinearGrid, _meshgrid_expand

from .data_index import data_index

# map from profile name to equilibrium parameter name
profile_names = {
    "pressure": "p_l",
    "iota": "i_l",
    "current": "c_l",
    "electron_temperature": "Te_l",
    "electron_density": "ne_l",
    "ion_temperature": "Ti_l",
    "atomic_number": "Zeff_l",
}


def _parse_parameterization(p):
    if isinstance(p, str):
        return p
    klass = p.__class__
    module = klass.__module__
    if module == "builtins":
        return klass.__qualname__  # avoid outputs like 'builtins.str'
    return module + "." + klass.__qualname__


def compute(parameterization, names, params, transforms, profiles, data=None, **kwargs):
    """Compute the quantity given by name on grid.

    Parameters
    ----------
    parameterization : str, class, or instance
        Type of object to compute for, eg Equilibrium, Curve, etc.
    names : str or array-like of str
        Name(s) of the quantity(s) to compute.
    params : dict of ndarray
        Parameters from the equilibrium, such as R_lmn, Z_lmn, i_l, p_l, etc.
        Defaults to attributes of self.
    transforms : dict of Transform
        Transforms for R, Z, lambda, etc. Default is to build from grid
    profiles : dict of Profile
        Profile objects for pressure, iota, current, etc. Defaults to attributes
        of self
    data : dict of ndarray
        Data computed so far, generally output from other compute functions

    Returns
    -------
    data : dict of ndarray
        Computed quantity and intermediate variables.

    """
    p = _parse_parameterization(parameterization)
    if isinstance(names, str):
        names = [names]
    for name in names:
        if name not in data_index[p]:
            raise ValueError(f"Unrecognized value '{name}' for parameterization {p}.")
    allowed_kwargs = {"helicity", "M_booz", "N_booz", "gamma", "basis", "method"}
    bad_kwargs = kwargs.keys() - allowed_kwargs
    if len(bad_kwargs) > 0:
        raise ValueError(f"Unrecognized argument(s): {bad_kwargs}")

    for name in names:
        assert _has_params(name, params, p), f"Don't have params to compute {name}"
        assert _has_profiles(
            name, profiles, p
        ), f"Don't have profiles to compute {name}"
        assert _has_transforms(
            name, transforms, p
        ), f"Don't have transforms to compute {name}"

    if data is None:
        data = {}

    data = _compute(
        p,
        names,
        params=params,
        transforms=transforms,
        profiles=profiles,
        data=data,
        **kwargs,
    )
    return data


def _compute(
    parameterization, names, params, transforms, profiles, data=None, **kwargs
):
    """Same as above but without checking inputs for faster recursion."""
    for name in names:
        if name in data:
            # don't compute something that's already been computed
            continue
        if not has_dependencies(
            parameterization, name, params, transforms, profiles, data
        ):
            # then compute the missing dependencies
            data = _compute(
                parameterization,
                data_index[parameterization][name]["dependencies"]["data"],
                params=params,
                transforms=transforms,
                profiles=profiles,
                data=data,
                **kwargs,
            )
            if transforms["grid"].axis.size:
                data = _compute(
                    parameterization,
                    data_index[parameterization][name]["dependencies"][
                        "axis_limit_data"
                    ],
                    params=params,
                    transforms=transforms,
                    profiles=profiles,
                    data=data,
                    **kwargs,
                )
        # now compute the quantity
        data = data_index[parameterization][name]["fun"](
            params=params, transforms=transforms, profiles=profiles, data=data, **kwargs
        )

    return data


def get_data_deps(keys, obj, has_axis=False):
    """Get list of data keys needed to compute a given quantity.

    Parameters
    ----------
    keys : str or array-like of str
        Name of the desired quantity from the data index
    obj : Equilibrium, Curve, Surface, Coil, etc.
        Object to compute quantity for.
    has_axis : bool
        Whether the grid to compute on has a node on the magnetic axis.

    Returns
    -------
    deps : list of str
        Names of quantities needed to compute key
    """
    p = _parse_parameterization(obj)
    keys = [keys] if isinstance(keys, str) else keys

    def _get_deps_1_key(key):
        if has_axis:
            if "full_with_axis_dependencies" in data_index[p][key]:
                return data_index[p][key]["full_with_axis_dependencies"]["data"]
        elif "full_dependencies" in data_index[p][key]:
            return data_index[p][key]["full_dependencies"]["data"]
        deps = data_index[p][key]["dependencies"]["data"]
        if len(deps) == 0:
            return deps
        out = deps.copy()  # to avoid modifying the data_index
        for dep in deps:
            out += _get_deps_1_key(dep)
        if has_axis:
            axis_limit_deps = data_index[p][key]["dependencies"]["axis_limit_data"]
            out += axis_limit_deps.copy()  # to be safe
            for dep in axis_limit_deps:
                out += _get_deps_1_key(dep)
        return sorted(list(set(out)))

    out = []
    for key in keys:
        out += _get_deps_1_key(key)
    return sorted(list(set(out)))


def get_derivs(keys, obj, has_axis=False):
    """Get dict of derivative orders needed to compute a given quantity.

    Parameters
    ----------
    keys : str or array-like of str
        Name of the desired quantity from the data index
    obj : Equilibrium, Curve, Surface, Coil, etc.
        Object to compute quantity for.
    has_axis : bool
        Whether the grid to compute on has a node on the magnetic axis.

    Returns
    -------
    derivs : dict of list of int
        Orders of derivatives needed to compute key.
        Keys for R, Z, L, etc
    """
    p = _parse_parameterization(obj)
    keys = [keys] if isinstance(keys, str) else keys

    def _get_derivs_1_key(key):
        if has_axis:
            if "full_with_axis_dependencies" in data_index[p][key]:
                return data_index[p][key]["full_with_axis_dependencies"]["transforms"]
        elif "full_dependencies" in data_index[p][key]:
            return data_index[p][key]["full_dependencies"]["transforms"]
        deps = [key] + get_data_deps(key, p, has_axis=has_axis)
        derivs = {}
        for dep in deps:
            for key, val in data_index[p][dep]["dependencies"]["transforms"].items():
                if key not in derivs:
                    derivs[key] = []
                derivs[key] += val
        return derivs

    derivs = {}
    for key in keys:
        derivs1 = _get_derivs_1_key(key)
        for key1, val in derivs1.items():
            if key1 not in derivs:
                derivs[key1] = []
            derivs[key1] += val
    return {key: np.unique(val, axis=0).tolist() for key, val in derivs.items()}


def get_profiles(keys, obj, grid=None, has_axis=False, jitable=False, **kwargs):
    """Get profiles needed to compute a given quantity on a given grid.

    Parameters
    ----------
    keys : str or array-like of str
        Name of the desired quantity from the data index.
    obj : Equilibrium, Curve, Surface, Coil, etc.
        Object to compute quantity for.
    grid : Grid
        Grid to compute quantity on.
    has_axis : bool
        Whether the grid to compute on has a node on the magnetic axis.
    jitable: bool
        Whether to skip certain checks so that this operation works under JIT

    Returns
    -------
    profiles : list of str or dict of Profile
        Profiles needed to compute key.
        if eq is None, returns a list of the names of profiles needed
        otherwise, returns a dict of Profiles
        Keys for pressure, iota, etc.
    """
    p = _parse_parameterization(obj)
    keys = [keys] if isinstance(keys, str) else keys
    has_axis = has_axis or (grid is not None and grid.axis.size)
    deps = list(keys) + get_data_deps(keys, p, has_axis=has_axis)
    profs = []
    for key in deps:
        profs += data_index[p][key]["dependencies"]["profiles"]
    profs = sorted(list(set(profs)))
    if isinstance(obj, str) or inspect.isclass(obj):
        return profs
    # need to use copy here because profile may be None
    profiles = {name: copy.deepcopy(getattr(obj, name)) for name in profs}
    return profiles


def get_params(keys, obj, has_axis=False, **kwargs):
    """Get parameters needed to compute a given quantity.

    Parameters
    ----------
    keys : str or array-like of str
        Name of the desired quantity from the data index
    obj : Equilibrium, Curve, Surface, Coil, etc.
        Object to compute quantity for.
    has_axis : bool
        Whether the grid to compute on has a node on the magnetic axis.

    Returns
    -------
    params : list of str or dict of ndarray
        Parameters needed to compute key.
        If eq is None, returns a list of the names of params needed
        otherwise, returns a dict of ndarray with keys for R_lmn, Z_lmn, etc.
    """
    p = _parse_parameterization(obj)
    keys = [keys] if isinstance(keys, str) else keys
    deps = list(keys) + get_data_deps(keys, p, has_axis=has_axis)
    params = []
    for key in deps:
        params += data_index[p][key]["dependencies"]["params"]
    if isinstance(obj, str) or inspect.isclass(obj):
        return params
    temp_params = {}
    for name in params:
        p = getattr(obj, name)
        if isinstance(p, dict):
            temp_params[name] = p.copy()
        else:
            temp_params[name] = jnp.atleast_1d(p)
    return temp_params


def get_transforms(keys, obj, grid, jitable=False, **kwargs):
    """Get transforms needed to compute a given quantity on a given grid.

    Parameters
    ----------
    keys : str or array-like of str
        Name of the desired quantity from the data index
    obj : Equilibrium, Curve, Surface, Coil, etc.
        Object to compute quantity for.
    grid : Grid
        Grid to compute quantity on
    jitable: bool
        Whether to skip certain checks so that this operation works under JIT

    Returns
    -------
    transforms : dict of Transform
        Transforms needed to compute key.
        Keys for R, Z, L, etc

    """
    from desc.basis import DoubleFourierSeries
    from desc.transform import Transform

    method = "jitable" if jitable or kwargs.get("method") == "jitable" else "auto"
    keys = [keys] if isinstance(keys, str) else keys
    derivs = get_derivs(keys, obj, has_axis=grid.axis.size)
    transforms = {"grid": grid}
    for c in derivs.keys():
        if hasattr(obj, c + "_basis"):
            transforms[c] = Transform(
                grid,
                getattr(obj, c + "_basis"),
                derivs=derivs[c],
                build=True,
                method=method,
            )
        elif c == "B":
            transforms["B"] = Transform(
                grid,
                DoubleFourierSeries(
                    M=kwargs.get("M_booz", 2 * obj.M),
                    N=kwargs.get("N_booz", 2 * obj.N),
                    NFP=obj.NFP,
                    sym=obj.R_basis.sym,
                ),
                derivs=derivs["B"],
                build=True,
                build_pinv=True,
                method=method,
            )
        elif c == "w":
            transforms["w"] = Transform(
                grid,
                DoubleFourierSeries(
                    M=kwargs.get("M_booz", 2 * obj.M),
                    N=kwargs.get("N_booz", 2 * obj.N),
                    NFP=obj.NFP,
                    sym=obj.Z_basis.sym,
                ),
                derivs=derivs["w"],
                build=True,
                build_pinv=True,
                method=method,
            )
        elif c not in transforms:
            transforms[c] = getattr(obj, c)

    return transforms


def has_dependencies(parameterization, qty, params, transforms, profiles, data):
    """Determine if we have the ingredients needed to compute qty.

    Parameters
    ----------
    parameterization : str or class
        Type of thing we're checking dependencies for. eg desc.equilibrium.Equilibrium
    qty : str
        Name of something from the data index.
    params : dict of ndarray
        Dictionary of parameters we have.
    transforms : dict of Transform
        Dictionary of transforms we have.
    profiles : dict of Profile
        Dictionary of profiles we have.
    data : dict of ndarray
        Dictionary of what we've computed so far.

    Returns
    -------
    has_dependencies : bool
        Whether we have what we need.
    """
    return (
        _has_data(qty, data, parameterization)
        and (
            not transforms["grid"].axis.size
            or _has_axis_limit_data(qty, data, parameterization)
        )
        and _has_params(qty, params, parameterization)
        and _has_profiles(qty, profiles, parameterization)
        and _has_transforms(qty, transforms, parameterization)
    )


def _has_data(qty, data, parameterization):
    p = _parse_parameterization(parameterization)
    deps = data_index[p][qty]["dependencies"]["data"]
    return all(d in data for d in deps)


def _has_axis_limit_data(qty, data, parameterization):
    p = _parse_parameterization(parameterization)
    deps = data_index[p][qty]["dependencies"]["axis_limit_data"]
    return all(d in data for d in deps)


def _has_params(qty, params, parameterization):
    p = _parse_parameterization(parameterization)
    deps = data_index[p][qty]["dependencies"]["params"]
    return all(d in params for d in deps)


def _has_profiles(qty, profiles, parameterization):
    p = _parse_parameterization(parameterization)
    deps = data_index[p][qty]["dependencies"]["profiles"]
    return all(d in profiles for d in deps)


def _has_transforms(qty, transforms, parameterization):
    p = _parse_parameterization(parameterization)
    flags = {}
    derivs = data_index[p][qty]["dependencies"]["transforms"]
    for key in derivs.keys():
        if key not in transforms:
            return False
        else:
            flags[key] = np.array(
                [d in transforms[key].derivatives.tolist() for d in derivs[key]]
            ).all()
    return all(flags.values())


def dot(a, b, axis=-1):
    """Batched vector dot product.

    Parameters
    ----------
    a : array-like
        First array of vectors.
    b : array-like
        Second array of vectors.
    axis : int
        Axis along which vectors are stored.

    Returns
    -------
    y : array-like
        y = sum(a*b, axis=axis)

    """
    return jnp.sum(a * b, axis=axis, keepdims=False)


def cross(a, b, axis=-1):
    """Batched vector cross product.

    Parameters
    ----------
    a : array-like
        First array of vectors.
    b : array-like
        Second array of vectors.
    axis : int
        Axis along which vectors are stored.

    Returns
    -------
    y : array-like
        y = a x b

    """
    return jnp.cross(a, b, axis=axis)


def safenorm(x, ord=None, axis=None, fill=0, threshold=0):
    """Like jnp.linalg.norm, but without nan gradient at x=0.

    Parameters
    ----------
    x : ndarray
        Vector or array to norm.
    ord : {non-zero int, inf, -inf, 'fro', 'nuc'}, optional
        Order of norm.
    axis : {None, int, 2-tuple of ints}, optional
        Axis to take norm along.
    fill : float, ndarray, optional
        Value to return where x is zero.
    threshold : float >= 0
        How small is x allowed to be.

    """
    is_zero = (jnp.abs(x) <= threshold).all(axis=axis, keepdims=True)
    y = jnp.where(is_zero, jnp.ones_like(x), x)  # replace x with ones if is_zero
    n = jnp.linalg.norm(y, ord=ord, axis=axis)
    n = jnp.where(is_zero.squeeze(), fill, n)  # replace norm with zero if is_zero
    return n


def safenormalize(x, ord=None, axis=None, fill=0, threshold=0):
    """Normalize a vector to unit length, but without nan gradient at x=0.

    Parameters
    ----------
    x : ndarray
        Vector or array to norm.
    ord : {non-zero int, inf, -inf, 'fro', 'nuc'}, optional
        Order of norm.
    axis : {None, int, 2-tuple of ints}, optional
        Axis to take norm along.
    fill : float, ndarray, optional
        Value to return where x is zero.
    threshold : float >= 0
        How small is x allowed to be.

    """
    is_zero = (jnp.abs(x) <= threshold).all(axis=axis, keepdims=True)
    y = jnp.where(is_zero, jnp.ones_like(x), x)  # replace x with ones if is_zero
    n = safenorm(x, ord, axis, fill, threshold) * jnp.ones_like(x)
    # return unit vector with equal components if norm <= threshold
    return jnp.where(n <= threshold, jnp.ones_like(y) / jnp.sqrt(y.size), y / n)


def safediv(a, b, fill=0, threshold=0):
    """Divide a/b with guards for division by zero.

    Parameters
    ----------
    a, b : ndarray
        Numerator and denominator.
    fill : float, ndarray, optional
        Value to return where b is zero.
    threshold : float >= 0
        How small is b allowed to be.
    """
    mask = jnp.abs(b) <= threshold
    num = jnp.where(mask, fill, a)
    den = jnp.where(mask, 1, b)
    return num / den


def cumtrapz(y, x=None, dx=1.0, axis=-1, initial=None):
    """Cumulatively integrate y(x) using the composite trapezoidal rule.

    Taken from SciPy, but changed NumPy references to JAX.NumPy:
        https://github.com/scipy/scipy/blob/v1.10.1/scipy/integrate/_quadrature.py

    Parameters
    ----------
    y : array_like
        Values to integrate.
    x : array_like, optional
        The coordinate to integrate along. If None (default), use spacing `dx`
        between consecutive elements in `y`.
    dx : float, optional
        Spacing between elements of `y`. Only used if `x` is None.
    axis : int, optional
        Specifies the axis to cumulate. Default is -1 (last axis).
    initial : scalar, optional
        If given, insert this value at the beginning of the returned result.
        Typically, this value should be 0. Default is None, which means no
        value at ``x[0]`` is returned and `res` has one element less than `y`
        along the axis of integration.

    Returns
    -------
    res : ndarray
        The result of cumulative integration of `y` along `axis`.
        If `initial` is None, the shape is such that the axis of integration
        has one less value than `y`. If `initial` is given, the shape is equal
        to that of `y`.

    """
    y = jnp.asarray(y)
    if x is None:
        d = dx
    else:
        x = jnp.asarray(x)
        if x.ndim == 1:
            d = jnp.diff(x)
            # reshape to correct shape
            shape = [1] * y.ndim
            shape[axis] = -1
            d = d.reshape(shape)
        elif len(x.shape) != len(y.shape):
            raise ValueError("If given, shape of x must be 1-D or the " "same as y.")
        else:
            d = jnp.diff(x, axis=axis)

        if d.shape[axis] != y.shape[axis] - 1:
            raise ValueError(
                "If given, length of x along axis must be the " "same as y."
            )

    def tupleset(t, i, value):
        l = list(t)
        l[i] = value
        return tuple(l)

    nd = len(y.shape)
    slice1 = tupleset((slice(None),) * nd, axis, slice(1, None))
    slice2 = tupleset((slice(None),) * nd, axis, slice(None, -1))
    res = jnp.cumsum(d * (y[slice1] + y[slice2]) / 2.0, axis=axis)

    if initial is not None:
        if not jnp.isscalar(initial):
            raise ValueError("`initial` parameter should be a scalar.")

        shape = list(res.shape)
        shape[axis] = 1
        res = jnp.concatenate(
            [jnp.full(shape, initial, dtype=res.dtype), res], axis=axis
        )

    return res


def _get_grid_surface(grid, surface_label):
    """Return grid quantities associated with the given surface label.

    Parameters
    ----------
    grid : Grid
        Collocation grid containing the nodes to evaluate at.
    surface_label : str
        The surface label of rho, theta, or zeta.

    Returns
    -------
    unique_size : int
        The number of the unique values of the surface_label.
    inverse_idx : ndarray
        Indexing array to go from unique values to full grid.
    spacing : ndarray
        The relevant columns of grid.spacing.
    has_endpoint_dupe : bool
        Whether this surface label's nodes have a duplicate at the endpoint
        of a periodic domain. (e.g. a node at 0 and 2π).

    """
    assert surface_label in {"rho", "theta", "zeta"}
    if surface_label == "rho":
        unique_size = grid.num_rho
        inverse_idx = grid.inverse_rho_idx
        spacing = grid.spacing[:, 1:]
        has_endpoint_dupe = False
    elif surface_label == "theta":
        unique_size = grid.num_theta
        inverse_idx = grid.inverse_theta_idx
        spacing = grid.spacing[:, [0, 2]]
        has_endpoint_dupe = (grid.nodes[grid.unique_theta_idx[0], 1] == 0) & (
            grid.nodes[grid.unique_theta_idx[-1], 1] == 2 * np.pi
        )
    else:
        unique_size = grid.num_zeta
        inverse_idx = grid.inverse_zeta_idx
        spacing = grid.spacing[:, :2]
        has_endpoint_dupe = (grid.nodes[grid.unique_zeta_idx[0], 2] == 0) & (
            grid.nodes[grid.unique_zeta_idx[-1], 2] == 2 * np.pi / grid.NFP
        )
    return unique_size, inverse_idx, spacing, has_endpoint_dupe


def line_integrals(
    grid,
    q=jnp.array([1.0]),
    line_label="theta",
    fix_surface=("rho", 1.0),
    expand_out=True,
):
    """Compute line integrals over curves covering the given surface.

    As an example, by specifying the combination of ``line_label="theta"`` and
    ``fix_surface=("rho", 1.0)``, the intention is to integrate along the
    outermost perimeter of a particular zeta surface (toroidal cross-section),
    for each zeta surface in the grid.

    Notes
    -----
        It is assumed that the integration curve has length 1 when the line
        label is rho and length 2π when the line label is theta or zeta.
        You may want to multiply the input by the line length Jacobian.

        Correctness is not guaranteed on grids with duplicate nodes.
        An attempt to print a warning is made if the given grid has duplicate
        nodes and is one of the predefined grid types
        (``Linear``, ``Concentric``, ``Quadrature``).
        If the grid is custom, no attempt is made to warn.

    Parameters
    ----------
    grid : Grid
        Collocation grid containing the nodes to evaluate at.
    q : ndarray
        Quantity to integrate.
        The first dimension of the array should have size ``grid.num_nodes``.

        When ``q`` is 1-dimensional, the intention is to integrate,
        over the domain parameterized by rho, theta, and zeta,
        a scalar function over the previously mentioned domain.

        When ``q`` is 2-dimensional, the intention is to integrate,
        over the domain parameterized by rho, theta, and zeta,
        a vector-valued function over the previously mentioned domain.

        When ``q`` is 3-dimensional, the intention is to integrate,
        over the domain parameterized by rho, theta, and zeta,
        a matrix-valued function over the previously mentioned domain.
    line_label : str
        The coordinate curve to compute the integration over.
        To clarify, a theta (poloidal) curve is the intersection of a
        rho surface (flux surface) and zeta (toroidal) surface.
    fix_surface : str, float
        A tuple of the form: label, value.
        ``fix_surface`` label should differ from ``line_label``.
        By default, ``fix_surface`` is chosen to be the flux surface at rho=1.
    expand_out : bool
        Whether to expand the output array so that the output has the same
        shape as the input. Defaults to true so that the output may be
        broadcast in the same way as the input. Setting to false will save
        memory.

    Returns
    -------
    integrals : ndarray
        Line integrals of the input over curves covering the given surface.
        By default, the returned array has the same shape as the input.

    """
    assert (
        line_label != fix_surface[0]
    ), "There is no valid use for this combination of inputs."
    assert line_label == "theta" or not isinstance(
        grid, ConcentricGrid
    ), "ConcentricGrid should only be used for theta line integrals."
    if isinstance(grid, LinearGrid) and grid.endpoint:
        warnings.warn(
            colored(
                "Correctness not guaranteed on grids with duplicate nodes.", "yellow"
            )
        )
    # Generate a new quantity q_prime which is zero everywhere
    # except on the fixed surface, on which q_prime takes the value of q.
    # Then forward the computation to surface_integrals().
    # The differential element of the line integral, denoted dl,
    # should correspond to the line label's spacing.
    # The differential element of the surface integral is
    # ds = dl * fix_surface_dl, so we scale q_prime by 1 / fix_surface_dl.
    labels = {"rho": 0, "theta": 1, "zeta": 2}
    column_id = labels[fix_surface[0]]
    mask = grid.nodes[:, column_id] == fix_surface[1]
    q_prime = (mask * jnp.atleast_1d(q).T / grid.spacing[:, column_id]).T
    (surface_label,) = labels.keys() - {line_label, fix_surface[0]}
    return surface_integrals(grid, q_prime, surface_label, expand_out)


def surface_integrals(grid, q=jnp.array([1.0]), surface_label="rho", expand_out=True):
    """Compute a surface integral for each surface in the grid.

    Notes
    -----
        It is assumed that the integration surface has area 4π² when the
        surface label is rho and area 2π when the surface label is theta or
        zeta. You may want to multiply the input by the surface area Jacobian.

    Parameters
    ----------
    grid : Grid
        Collocation grid containing the nodes to evaluate at.
    q : ndarray
        Quantity to integrate.
        The first dimension of the array should have size ``grid.num_nodes``.

        When ``q`` is 1-dimensional, the intention is to integrate,
        over the domain parameterized by rho, theta, and zeta,
        a scalar function over the previously mentioned domain.

        When ``q`` is 2-dimensional, the intention is to integrate,
        over the domain parameterized by rho, theta, and zeta,
        a vector-valued function over the previously mentioned domain.

        When ``q`` is 3-dimensional, the intention is to integrate,
        over the domain parameterized by rho, theta, and zeta,
        a matrix-valued function over the previously mentioned domain.
    surface_label : str
        The surface label of rho, theta, or zeta to compute the integration over.
    expand_out : bool
        Whether to expand the output array so that the output has the same
        shape as the input. Defaults to true so that the output may be
        broadcast in the same way as the input. Setting to false will save
        memory.

    Returns
    -------
    integrals : ndarray
        Surface integral of the input over each surface in the grid.
        By default, the returned array has the same shape as the input.

    """
    return surface_integrals_map(grid, surface_label, expand_out)(q)


def surface_integrals_map(grid, surface_label="rho", expand_out=True):
    """Returns a method to compute any surface integral for each surface in the grid.

    Parameters
    ----------
    grid : Grid
        Collocation grid containing the nodes to evaluate at.
    surface_label : str
        The surface label of rho, theta, or zeta to compute the integration over.
    expand_out : bool
        Whether to expand the output array so that the output has the same
        shape as the input. Defaults to true so that the output may be
        broadcast in the same way as the input. Setting to false will save
        memory.

    Returns
    -------
    function : callable
        Method to compute any surface integral of the input ``q`` over each
        surface in the grid with code: ``function(q)``.

    """
    if surface_label == "theta" and isinstance(grid, ConcentricGrid):
        warnings.warn(
            colored(
                "Integrals over constant theta surfaces are poorly defined for "
                + "ConcentricGrid.",
                "yellow",
            )
        )
    unique_size, inverse_idx, spacing, has_endpoint_dupe = _get_grid_surface(
        grid, surface_label
    )

    # Todo: Define masks as a sparse matrix once sparse matrices are no longer
    #       experimental in jax.
    # The ith row of masks is True only at the indices which correspond to the
    # ith surface. The integral over the ith surface is the dot product of the
    # ith row vector and the vector of integrands of all surfaces.
    masks = inverse_idx == jnp.arange(unique_size)[:, jnp.newaxis]
    # Imagine a torus cross-section at zeta=π.
    # A grid with a duplicate zeta=π node has 2 of those cross-sections.
    #     In grid.py, we multiply by 1/n the areas of surfaces with
    # duplicity n. This prevents the area of that surface from being
    # double-counted, as surfaces with the same node value are combined
    # into 1 integral, which sums their areas. Thus, if the zeta=π
    # cross-section has duplicity 2, we ensure that the area on the zeta=π
    # surface will have the correct total area of π+π = 2π.
    #     An edge case exists if the duplicate surface has nodes with
    # different values for the surface label, which only occurs when
    # has_endpoint_dupe is true. If ``has_endpoint_dupe`` is true, this grid
    # has a duplicate surface at surface_label=0 and
    # surface_label=max surface value. Although the modulo of these values
    # are equal, their numeric values are not, so the integration
    # would treat them as different surfaces. We solve this issue by
    # combining the indices corresponding to the integrands of the duplicated
    # surface, so that the duplicate surface is treated as one, like in the
    # previous paragraph.
    masks = cond(
        has_endpoint_dupe,
        lambda _: put(masks, jnp.array([0, -1]), masks[0] | masks[-1]),
        lambda _: masks,
        operand=None,
    )
    spacing = jnp.prod(spacing, axis=1)

    def _surface_integrals(q=jnp.array([1.0])):
        """Compute a surface integral for each surface in the grid.

        Notes
        -----
            It is assumed that the integration surface has area 4π² when the
            surface label is rho and area 2π when the surface label is theta or
            zeta. You may want to multiply the input by the surface area Jacobian.

        Parameters
        ----------
        q : ndarray
            Quantity to integrate.
            The first dimension of the array should have size ``grid.num_nodes``.

            When ``q`` is 1-dimensional, the intention is to integrate,
            over the domain parameterized by rho, theta, and zeta,
            a scalar function over the previously mentioned domain.

            When ``q`` is 2-dimensional, the intention is to integrate,
            over the domain parameterized by rho, theta, and zeta,
            a vector-valued function over the previously mentioned domain.

            When ``q`` is 3-dimensional, the intention is to integrate,
            over the domain parameterized by rho, theta, and zeta,
            a matrix-valued function over the previously mentioned domain.

        Returns
        -------
        integrals : ndarray
            Surface integral of the input over each surface in the grid.

        """
        axis_to_move = (jnp.ndim(q) == 3) * 2
        integrands = (spacing * jnp.nan_to_num(q).T).T
        # `integrands` may have shape (g.size, f.size, v.size), where
        #     g is the grid function depending on the integration variables
        #     f is a function which may be independent of the integration variables
        #     v is the vector of components of f (or g).
        # The intention is to integrate `integrands` which is a
        #     vector-valued            (with v.size components)
        #     function-valued          (with image size of f.size)
        #     function over the grid   (with domain size of g.size = grid.num_nodes)
        # over each surface in the grid.

        # The distinction between f and v is semantic.
        # We may alternatively consider an `integrands` of shape (g.size, f.size) to
        # represent a vector-valued (with f.size components) function over the grid.
        # Likewise, we may alternatively consider an `integrands` of shape
        # (g.size, v.size) to represent a function-valued (with image size v.size)
        # function over the grid. When `integrands` has dimension one, it is a
        # scalar function over the grid. That is, a
        #     vector-valued            (with 1 component),
        #     function-valued          (with image size of 1)
        #     function over the grid   (with domain size of g.size = grid.num_nodes)

        # The integration is performed by applying `masks`, the surface
        # integral operator, to `integrands`. This operator hits the matrix formed
        # by the last two dimensions of `integrands`, for every element along the
        # previous dimension of `integrands`. Therefore, when `integrands` has three
        # dimensions, the second must hold g. We may choose which of the first and
        # third dimensions hold f and v. The choice below transposes `integrands` to
        # shape (v.size, g.size, f.size). As we expect f.size >> v.size, the
        # integration is in theory faster since numpy optimizes large matrix
        # products. However, timing results showed no difference.
        integrals = jnp.moveaxis(
            masks @ jnp.moveaxis(integrands, axis_to_move, 0), 0, axis_to_move
        )
        return grid.expand(integrals, surface_label) if expand_out else integrals

    return _surface_integrals


def surface_averages(
    grid,
    q,
    sqrt_g=jnp.array([1.0]),
    surface_label="rho",
    denominator=None,
    expand_out=True,
):
    """Compute a surface average for each surface in the grid.

    Notes
    -----
        Implements the flux-surface average formula given by equation 4.9.11 in
        W.D. D'haeseleer et al. (1991) doi:10.1007/978-3-642-75595-8.

    Parameters
    ----------
    grid : Grid
        Collocation grid containing the nodes to evaluate at.
    q : ndarray
        Quantity to average.
        The first dimension of the array should have size ``grid.num_nodes``.

        When ``q`` is 1-dimensional, the intention is to average,
        over the domain parameterized by rho, theta, and zeta,
        a scalar function over the previously mentioned domain.

        When ``q`` is 2-dimensional, the intention is to average,
        over the domain parameterized by rho, theta, and zeta,
        a vector-valued function over the previously mentioned domain.

        When ``q`` is 3-dimensional, the intention is to average,
        over the domain parameterized by rho, theta, and zeta,
        a matrix-valued function over the previously mentioned domain.
    sqrt_g : ndarray
        Coordinate system Jacobian determinant; see ``data_index["sqrt(g)"]``.
    surface_label : str
        The surface label of rho, theta, or zeta to compute the average over.
    denominator : ndarray
        By default, the denominator is computed as the surface integral of
        ``sqrt_g``. This parameter can optionally be supplied to avoid
        redundant computations or to use a different denominator to compute
        the average. This array should broadcast with arrays of size
        ``grid.num_nodes`` (``grid.num_surface_label``) if ``expand_out``
        is true (false).
    expand_out : bool
        Whether to expand the output array so that the output has the same
        shape as the input. Defaults to true so that the output may be
        broadcast in the same way as the input. Setting to false will save
        memory.

    Returns
    -------
    averages : ndarray
        Surface average of the input over each surface in the grid.
        By default, the returned array has the same shape as the input.

    """
    return surface_averages_map(grid, surface_label, expand_out)(q, sqrt_g, denominator)


def surface_averages_map(grid, surface_label="rho", expand_out=True):
    """Returns a method to compute any surface average for each surface in the grid.

    Parameters
    ----------
    grid : Grid
        Collocation grid containing the nodes to evaluate at.
    surface_label : str
        The surface label of rho, theta, or zeta to compute the average over.
    expand_out : bool
        Whether to expand the output array so that the output has the same
        shape as the input. Defaults to true so that the output may be
        broadcast in the same way as the input. Setting to false will save
        memory.

    Returns
    -------
    function : callable
        Method to compute any surface average of the input ``q`` and optionally
        the volume Jacobian ``sqrt_g`` over each surface in the grid with code:
        ``function(q, sqrt_g)``.

    """
    compute_surface_integrals = surface_integrals_map(grid, surface_label, False)

    def _surface_averages(q, sqrt_g=jnp.array([1.0]), denominator=None):
        """Compute a surface average for each surface in the grid.

        Notes
        -----
            Implements the flux-surface average formula given by equation 4.9.11 in
            W.D. D'haeseleer et al. (1991) doi:10.1007/978-3-642-75595-8.

        Parameters
        ----------
        q : ndarray
            Quantity to average.
            The first dimension of the array should have size ``grid.num_nodes``.

            When ``q`` is 1-dimensional, the intention is to average,
            over the domain parameterized by rho, theta, and zeta,
            a scalar function over the previously mentioned domain.

            When ``q`` is 2-dimensional, the intention is to average,
            over the domain parameterized by rho, theta, and zeta,
            a vector-valued function over the previously mentioned domain.

            When ``q`` is 3-dimensional, the intention is to average,
            over the domain parameterized by rho, theta, and zeta,
            a matrix-valued function over the previously mentioned domain.
        sqrt_g : ndarray
            Coordinate system Jacobian determinant; see ``data_index["sqrt(g)"]``.
        denominator : ndarray
            By default, the denominator is computed as the surface integral of
            ``sqrt_g``. This parameter can optionally be supplied to avoid
            redundant computations or to use a different denominator to compute
            the average. This array should broadcast with arrays of size
            ``grid.num_nodes`` (``grid.num_surface_label``) if ``expand_out``
            is true (false).

        Returns
        -------
        averages : ndarray
            Surface average of the input over each surface in the grid.

        """
        q = jnp.atleast_1d(q)
        sqrt_g = jnp.atleast_1d(sqrt_g)
        numerator = compute_surface_integrals((sqrt_g * q.T).T)
        # memory optimization to call expand() at most once
        if denominator is None:
            # skip integration if constant
            denominator = (
                (4 * jnp.pi**2 if surface_label == "rho" else 2 * jnp.pi) * sqrt_g
                if sqrt_g.size == 1
                else compute_surface_integrals(sqrt_g)
            )
            averages = (numerator.T / denominator).T
            if expand_out:
                averages = grid.expand(averages, surface_label)
        else:
            if expand_out:
                # implies denominator given with size grid.num_nodes
                numerator = grid.expand(numerator, surface_label)
            averages = (numerator.T / denominator).T
        return averages

    return _surface_averages


def surface_integrals_transform(grid, surface_label="rho"):
    """Returns a method to compute any integral transform over each surface in grid.

    The returned method takes an array input ``q`` and returns an array output.

    Given a set of kernel functions in ``q``, each parameterized by at most
    five variables, the returned method computes an integral transform,
    reducing ``q`` to a set of functions of at most three variables.

    Define the domain D = u₁ × u₂ × u₃ and the codomain C = u₄ × u₅ × u₆.
    For every surface of constant u₁ in the domain, the returned method
    evaluates the transform Tᵤ₁ : u₂ × u₃ × C → C, where Tᵤ₁ projects
    away the parameters u₂ and u₃ via an integration of the given kernel
    function Kᵤ₁ over the corresponding surface of constant u₁.

    Notes
    -----
        It is assumed that the integration surface has area 4π² when the
        surface label is rho and area 2π when the surface label is theta or
        zeta. You may want to multiply the input ``q`` by the surface area
        Jacobian.

    Parameters
    ----------
    grid : Grid
        Collocation grid containing the nodes to evaluate at.
    surface_label : str
        The surface label of rho, theta, or zeta to compute the integration over.
        These correspond to the domain parameters discussed in this method's
        description. In particular, ``surface_label`` names u₁.

    Returns
    -------
    function : callable
        Method to compute any surface integral transform of the input ``q`` over
        each surface in the grid with code: ``function(q)``.

        The first dimension of ``q`` should always discretize some function, g,
        over the domain, and therefore, have size ``grid.num_nodes``.
        The second dimension may discretize some function, f, over the
        codomain, and therefore, have size that matches the desired number of
        points at which the output is evaluated.
        If the integrand is vector-valued then the third dimension may
        hold the components of size v.size.

        This method can also be used to compute the output one point at a time.
        In this case, ``q`` will be at most two-dimensional, and the second
        dimension may hold the vector components.

        There is technically no difference between the labels f and v, so their
        roles may be swapped if this is more convenient.

        Input
        -----
        If ``q`` is one-dimensional, then it should have shape
        (``grid.num_nodes``, ).
        If ``q`` is two-dimensional, then either
            1) g and f are scalar functions, so the input should have shape
               (``grid.num_nodes``, f.size).
            2) g (or f) is a vector-valued function, and f has been evaluated at
               only one point, so the input should have shape
               (``grid.num_nodes``, v.size).
        If ``q`` is three-dimensional, then it should have shape
        (``grid.num_nodes``, f.size, v.size).

        Output
        ------
        Each element along the first dimension of the returned array, stores
        Tᵤ₁ for a particular surface of constant u₁ in the given grid.
        The order is sorted in increasing order of the values which specify u₁.

        If ``q`` is one-dimensional, the returned array has shape
        (grid.num_surface_label, ).
        If ``q`` is two-dimensional, the returned array has shape
        (grid.num_surface_label, (f or v).size), depending on whether f or v is
        the relevant label.
        If ``q`` is three-dimensional, the returned array has shape
        (grid.num_surface_label, f.size, v.size).

    """
    # Although this method seems to duplicate surface_integrals(), the
    # intentions of these methods may be to implement different algorithms.
    # We can rely on surface_integrals() for the computation because its current
    # implementation is flexible enough to implement both algorithms.
    # Expansion should not occur here. The typical use case of this method is to
    # transform into the computational domain, so the second dimension that
    # discretizes f over the codomain will typically have size grid.num_nodes
    # to broadcast with quantities in data_index.
    return surface_integrals_map(grid, surface_label, expand_out=False)


def surface_variance(
    grid,
    q,
    weights=jnp.array([1.0]),
    bias=False,
    surface_label="rho",
    expand_out=True,
):
    """Compute the weighted sample variance of ``q`` on each surface of the grid.

    Computes nₑ / (nₑ − b) * (∑ᵢ₌₁ⁿ (qᵢ − q̅)² wᵢ) / (∑ᵢ₌₁ⁿ wᵢ).
    wᵢ is the weight assigned to qᵢ given by the product of ``weights[i]`` and
       the differential surface area element (not already weighted by the area
       Jacobian) at the node where qᵢ is evaluated,
    q̅ is the weighted mean of q,
    b is 0 if the biased sample variance is to be returned and 1 otherwise,
    n is the number of samples on a surface, and
    nₑ ≝ (∑ᵢ₌₁ⁿ wᵢ)² / ∑ᵢ₌₁ⁿ wᵢ² is the effective number of samples.

    As the weights wᵢ approach each other, nₑ approaches n, and the output
    converges to ∑ᵢ₌₁ⁿ (qᵢ − q̅)² / (n − b).

    Notes
    -----
        There are three different methods to unbias the variance of a weighted
        sample so that the computed variance better estimates the true variance.
        Whether the method is correct for a particular use case depends on what
        the weights assigned to each sample represent.

        This function implements the first case, where the weights are not random
        and are intended to assign more weight to some samples for reasons
        unrelated to differences in uncertainty between samples. See
        https://en.wikipedia.org/wiki/Weighted_arithmetic_mean#Reliability_weights.

        The second case is when the weights are intended to assign more weight
        to samples with less uncertainty. See
        https://en.wikipedia.org/wiki/Inverse-variance_weighting.
        The unbiased sample variance for this case is obtained by replacing the
        effective number of samples in the formula this function implements,
        nₑ, with the actual number of samples n.

        The third case is when the weights denote the integer frequency of each
        sample. See
        https://en.wikipedia.org/wiki/Weighted_arithmetic_mean#Frequency_weights.
        This is indeed a distinct case from the above two because here the
        weights encode additional information about the distribution.

    Parameters
    ----------
    grid : Grid
        Collocation grid containing the nodes to evaluate at.
    q : ndarray
        Quantity to compute the sample variance.
    weights : ndarray
        Weight assigned to each sample of ``q``.
        A good candidate for this parameter is the surface area Jacobian.
    bias : bool
        If this condition is true, then the biased estimator of the sample
        variance is returned. This is desirable if you are only concerned with
        computing the variance of the given set of numbers and not the
        distribution the numbers are (potentially) sampled from.
    surface_label : str
        The surface label of rho, theta, or zeta to compute the variance over.
    expand_out : bool
        Whether to expand the output array so that the output has the same
        shape as the input. Defaults to true so that the output may be
        broadcast in the same way as the input. Setting to false will save
        memory.

    Returns
    -------
    variance : ndarray
        Variance of the given weighted sample over each surface in the grid.
        By default, the returned array has the same shape as the input.

    """
    _, _, spacing, _ = _get_grid_surface(grid, surface_label)
    integrate = surface_integrals_map(grid, surface_label, expand_out=False)

    v1 = integrate(weights)
    v2 = integrate(weights**2 * jnp.prod(spacing, axis=-1))
    # effective number of samples per surface
    n_e = v1**2 / v2
    # analogous to Bessel's bias correction
    correction = n_e / (n_e - (not bias))

    q = jnp.atleast_1d(q)
    # compute variance in two passes to avoid catastrophic round off error
    mean = (integrate((weights * q.T).T).T / v1).T
    mean = grid.expand(mean, surface_label)
    variance = (correction * integrate((weights * ((q - mean) ** 2).T).T).T / v1).T
    return grid.expand(variance, surface_label) if expand_out else variance


def surface_max(grid, x, surface_label="rho"):
    """Get the max of x for each surface in the grid.

    Parameters
    ----------
    grid : Grid
        Collocation grid containing the nodes to evaluate at.
    x : ndarray
        Quantity to find max.
        The array should have size grid.num_nodes.
    surface_label : str
        The surface label of rho, theta, or zeta to compute max over.

    Returns
    -------
    maxs : ndarray
        Maximum of x over each surface in grid.
        The returned array has the same shape as the input.

    """
    return -surface_min(grid, -x, surface_label)


def surface_min(grid, x, surface_label="rho"):
    """Get the min of x for each surface in the grid.

    Parameters
    ----------
    grid : Grid
        Collocation grid containing the nodes to evaluate at.
    x : ndarray
        Quantity to find min.
        The array should have size grid.num_nodes.
    surface_label : str
        The surface label of rho, theta, or zeta to compute min over.

    Returns
    -------
    mins : ndarray
        Minimum of x over each surface in grid.
        The returned array has the same shape as the input.

    """
    unique_size, inverse_idx, _, _ = _get_grid_surface(grid, surface_label)
    inverse_idx = jnp.asarray(inverse_idx)
    x = jnp.asarray(x)
    mins = jnp.full(unique_size, jnp.inf)

    def body(i, mins):
        mins = put(mins, inverse_idx[i], jnp.minimum(x[i], mins[inverse_idx[i]]))
        return mins

    mins = fori_loop(0, inverse_idx.size, body, mins)
    # The above implementation was benchmarked to be more efficient than
    # alternatives without explicit loops in GitHub pull request #501.
    return grid.expand(mins, surface_label)


# probably best to add these to interpax
def cubic_poly_roots(coef, shift=jnp.array([0])):
    """Roots of cubic polynomial.

    Parameters
    ----------
    coef : ndarray
        First axis should store coefficients of a polynomial. For a polynomial
        given by c₁ x³ + c₂ x² + c₃ x + c₄, ``coef[i]`` should store cᵢ.
        It is assumed that c₁ is nonzero.
    shift : ndarray, shape(shift.size, )
        Specify to instead find solutions to c₁ x³ + c₂ x² + c₃ x + c₄ = ``shift``.

    Returns
    -------
    xi : ndarray, shape(shift.size, coef.shape, 3)
        If shift has one element, the first axis will be squeezed out.
        The three roots of the cubic polynomial, sorted by real part then imaginary.

    """
    # https://en.wikipedia.org/wiki/Cubic_equation#General_cubic_formula
    # The common libraries use root-finding which isn't compatible with JAX.
    a, b, c, d = coef
    d = jnp.squeeze((d[jnp.newaxis, :].T - shift).T)
    t_0 = b**2 - 3 * a * c
    t_1 = 2 * b**3 - 9 * a * b * c + 27 * a**2 * d
    C = ((t_1 + complex_sqrt(t_1**2 - 4 * t_0**3)) / 2) ** (1 / 3)
    C_is_zero = jnp.isclose(C, 0)

    def roots(xi_k):
        t_3 = jnp.where(C_is_zero, 0, t_0 / (xi_k * C))
        r = -(b + xi_k * C + t_3) / (3 * a)
        return r

    xi_1 = (-1 + (-3) ** 0.5) / 2
    xi_2 = xi_1**2
    xi_3 = 1
    xi = jnp.sort(jnp.stack([roots(xi_1), roots(xi_2), roots(xi_3)], axis=-1), axis=-1)
    return xi


def polyint(coef):
    """Coefficients for the primitives of the given set of polynomials.

    Parameters
    ----------
    coef : ndarray
        First axis should store coefficients of a polynomial.
        For a polynomial given by ∑ᵢⁿ cᵢ xⁱ, where n is ``coef.shape[0] - 1``,
        coefficient cᵢ should be stored at ``coef[n - i]``.

    Returns
    -------
    poly : ndarray
        Coefficients of polynomial primitive, ignoring the arbitrary constant.
        That is, ``poly[i]`` stores the coefficient of the monomial xⁿ⁻ⁱ⁺¹,
        where n is ``coef.shape[0] - 1``.

    """
    poly = (coef.T / jnp.arange(coef.shape[0], 0, -1)).T
    return poly


def polyder(coef):
    """Coefficients for the derivatives of the given set of polynomials.

    Parameters
    ----------
    coef : ndarray
        First axis should store coefficients of a polynomial.
        For a polynomial given by ∑ᵢⁿ cᵢ xⁱ, where n is ``coef.shape[0] - 1``,
        coefficient cᵢ should be stored at ``coef[n - i]``.

    Returns
    -------
    poly : ndarray
        Coefficients of polynomial derivative, ignoring the arbitrary constant.
        That is, ``poly[i]`` stores the coefficient of the monomial xⁿ⁻ⁱ⁻¹,
        where n is ``coef.shape[0] - 1``.

    """
    poly = (coef[:-1].T * jnp.arange(coef.shape[0] - 1, 0, -1)).T
    return poly


def polyeval(coef, x):
    """Evaluate the set of polynomials at the points x.

    Parameters
    ----------
    coef : ndarray
        First axis should store coefficients of a polynomial.
        For a polynomial given by ∑ᵢⁿ cᵢ xⁱ, where n is ``coef.shape[0] - 1``,
        coefficient cᵢ should be stored at ``coef[n - i]``.
    x : ndarray
        Coordinates at which to evaluate the set of polynomials.
        The first ``coef.ndim`` axes should have shape ``coef.shape[1:]``.

    Returns
    -------
    f : ndarray
        ``f[j, k, ...]`` is the polynomial with coefficients ``coef[:, j, k, ...]``
        evaluated at the point ``x[j, k, ...]``.

    """
    X = (x[jnp.newaxis, :].T ** jnp.arange(coef.shape[0] - 1, -1, -1)).T
    alphabet = "abcdefghijklmnopqrstuvwxyz"
    sub = alphabet[: coef.ndim]
    f = jnp.einsum(f"{sub},{sub}...->{sub[1:]}...", coef, X)
    return f


def bounce_integral(eq, rho=None, alpha=None, zeta_max=10 * jnp.pi, resolution=20):
    """Returns a method to compute the bounce integral of any quantity.

    The bounce integral is defined as F_ℓ(λ) = ∫ f(ℓ) / √(1 − λ |B|) dℓ, where
        dℓ parameterizes the distance along the field line,
        λ is a constant proportional to the magnetic moment over energy,
        |B| is the norm of the magnetic field,
        f(ℓ) is the quantity to integrate along the field line,
        and the endpoints of the integration are at the bounce points.
    For a particle with fixed λ, bounce points are defined to be the location
    on the field line such that the particle's velocity parallel to the
    magnetic field is zero, i.e. λ |B| = 1.

    The bounce integral is defined up to a sign.
    We choose the sign that corresponds the particle's guiding center trajectory
    traveling in the direction of increasing field-line-following label.

    Parameters
    ----------
    eq : Equilibrium
        Equilibrium on which the bounce integral is defined.
    rho : ndarray
        Unique flux surface label coordinates.
    alpha : ndarray
        Unique field line label coordinates over a constant rho surface.
    zeta_max : float
        Max value for field line following coordinate.
    resolution : int
        Number of quadrature points used to compute the bounce integral.

    Returns
    -------
    bi : callable
        This callable method computes the bounce integral F_ℓ(λ) for every
        specified field line ℓ (constant rho and alpha), for every λ value in
        ``lambda_pitch``.

    Examples
    --------
    .. code-block:: python

        bi = bounce_integral(eq)
        F = bi(name, lambda_pitch)

    """
    if rho is None:
        rho = jnp.linspace(0, 1, 10)
    if alpha is None:
        alpha = jnp.linspace(0, (2 - eq.sym) * jnp.pi, 20)

    zeta = np.linspace(0, zeta_max, resolution)
    grid, data = field_line_to_desc_coords(rho, alpha, zeta, eq)
    data = eq.compute(
        ["B^zeta", "|B|", "|B|_z constant rho alpha"], grid=grid, data=data
    )
    # TODO: https://github.com/f0uriest/interpax/issues/19
    coef = CubicHermiteSpline(
        zeta,
        data["|B|"].reshape(alpha.size, rho.size, zeta.size),
        data["|B|_z constant rho alpha"].reshape(alpha.size, rho.size, zeta.size),
        axis=-1,
        extrapolate="periodic",
    ).c
    # Enforce a periodic boundary condition to compute bounce integrals
    # of particles trapped outside this snapshot of the field lines.
    coef = jnp.append(coef, coef[:, 0][:, jnp.newaxis], axis=1)
    der = polyder(coef)
    # There are zeta.size splines per field line.
    # The last spline is a duplicate of the first.
    assert coef.shape == (4, zeta.size, alpha.size, rho.size)
    assert der.shape == (3, zeta.size, alpha.size, rho.size)

    def _bounce_integral(name, lambda_pitch):
        """Compute the bounce integral of the named quantity.

        Parameters
        ----------
        name : ndarray
            Name of quantity in ``data_index`` to compute the bounce integral of.
        lambda_pitch : ndarray
            λ values to evaluate the bounce integral at.

        Returns
        -------
        F : ndarray, shape(lambda_pitch.size, resolution, alpha.size, rho.size, 2)
            Axes with size one will be squeezed out.
            Bounce integrals evaluated at ``lambda_pitch`` for every field line.

        """
        # Gauss-Quadrature is expensive to perform because evaluating the integrand
        # at the optimal quadrature points along the field line would require
        # root finding to map field line coordinates to desc coordinates.
        # Newton-Cotes quadrature is inaccurate as the bounce points are not
        # guaranteed to be near the fixed quadrature points. Instead, we
        # construct interpolating cubic splines of the integrand and integrate
        # the spline exactly between the bounce points. This should give
        # comparable results to a composite Simpson Newton-Cotes with quadrature
        # points near bounce points.
        lambda_pitch = jnp.atleast_1d(lambda_pitch)
        bp = cubic_poly_roots(coef, 1 / lambda_pitch).reshape(
            lambda_pitch.size, zeta.size, alpha.size, rho.size, 3
        )
        real_bp = jnp.real(bp)
        b_norm_z = polyeval(der[:, jnp.newaxis], real_bp)
        is_well = (b_norm_z[..., :-1] <= 0) & (b_norm_z[..., 1:] >= 0)
        is_real = jnp.isreal(bp[..., :-1]) & jnp.isreal(bp[..., 1:])
        # Can precompute everything above if lambda_pitch given to parent function.

        # Goal: Integrate between potential wells with real bounce points.
        # Strategy: 1. Integrate between real parts of all complex bounce points.
        #           2. Sum integrals between real bounce points.
        #           3. Keep only results with two real bounce points in a well.
        y = jnp.nan_to_num(
            eq.compute(name, grid=grid, override_grid=False, data=data)[name]
            / (
                data["B^zeta"]
                * jnp.sqrt(1 - lambda_pitch[:, jnp.newaxis] * data["|B|"])
            )
        ).reshape(lambda_pitch.size, alpha.size, rho.size, zeta.size)
        y = CubicSpline(zeta, y, axis=-1, extrapolate="periodic").c
        # Enforce a periodic boundary condition to compute bounce integrals
        # of particles trapped outside this snapshot of the field lines.
        y = jnp.append(y, y[:, 0][:, jnp.newaxis], axis=1)
        Y = jnp.swapaxes(polyint(y), 1, 2)
        Y = polyeval(Y, real_bp)
        integral = Y[..., 1:] - Y[..., :-1]
        # TODO: sum across real bounce points
        F = jnp.squeeze((is_well & is_real) * integral)
        return F

    return _bounce_integral


def bounce_average(eq, rho=None, alpha=None, resolution=20):
    """Returns a method to compute the bounce average of any quantity.

    The bounce average is defined as
    G_ℓ(λ) = (∫ g(ℓ) / √(1 − λ |B|) dℓ) / (∫ 1 / √(1 − λ |B|) dℓ), where
        dℓ parameterizes the distance along the field line,
        λ is a constant proportional to the magnetic moment over energy,
        |B| is the norm of the magnetic field,
        g(ℓ) is the quantity to integrate along the field line,
        and the endpoints of the integration are at the bounce points.
    For a particle with fixed λ, bounce points are defined to be the location
    on the field line such that the particle's velocity parallel to the
    magnetic field is zero, i.e. λ |B| = 1.

    The bounce integral is defined up to a sign.
    We choose the sign that corresponds the particle's guiding center trajectory
    traveling in the direction of increasing field-line-following label.

    Parameters
    ----------
    eq : Equilibrium
        Equilibrium on which the bounce integral is defined.
    rho : ndarray
        Unique flux surface label coordinates.
    alpha : ndarray
        Unique field line label coordinates over a constant rho surface.
    resolution : int
        Number of quadrature points used to compute the bounce integral.

    Returns
    -------
    ba : callable
        This callable method computes the bounce integral G_ℓ(λ) for every
        specified field line ℓ (constant rho and alpha), for every λ value in
        ``lambdas``.

    Examples
    --------
    .. code-block:: python

        ba = bounce_average(eq)
        G = ba(name, lambda_pitch)

    """
    bi = bounce_integral(eq, rho, alpha, resolution)

    def _bounce_average(name, lambda_pitch):
        """Compute the bounce average of the named quantity.

        Parameters
        ----------
        name : ndarray
            Name of quantity in ``data_index`` to compute the bounce average of.
        lambda_pitch : ndarray
            λ values to evaluate the bounce integral at.

        Returns
        -------
        G : ndarray, shape(lambda_pitch.size, resolution - 1, alpha.size, rho.size, 2)
            Bounce average evaluated at ``lambdas`` for every field line.

        """
        return bi(name, lambda_pitch) / bi("1", lambda_pitch)

    return _bounce_average


def field_line_to_desc_coords(rho, alpha, zeta, eq):
    """Get desc grid from unique field line coords."""
    r, a, z = jnp.meshgrid(rho, alpha, zeta, indexing="ij")
    r, a, z = r.ravel(), a.ravel(), z.ravel()
    # Now we map these Clebsch-Type field-line coordinates to DESC coordinates.
    # Note that the rotational transform can be computed apriori because it is a single
    # variable function of rho, and the coordinate mapping does not change rho. Once
    # this is known, it is simple to compute theta_PEST from alpha. Then we transform
    # from straight field-line coordinates to DESC coordinates with the method
    # compute_theta_coords. This is preferred over transforming from Clebsch-Type
    # coordinates to DESC coordinates directly with the more general method
    # map_coordinates. That method requires an initial guess to be compatible with JIT,
    # and generating a reasonable initial guess requires computing the rotational
    # transform to approximate theta_PEST and the poloidal stream function anyway.
    # TODO: In general, Linear Grid construction is not jit compatible.
    #  This issue can be worked around with a specific routine for this.
    lg = LinearGrid(rho=rho, M=eq.M_grid, N=eq.N_grid, NFP=eq.NFP, sym=eq.sym)
    lg_data = eq.compute("iota", grid=lg)
    data = {
        d: _meshgrid_expand(lg.compress(lg_data[d]), rho.size, alpha.size, zeta.size)
        for d in lg_data
        if data_index["desc.equilibrium.equilibrium.Equilibrium"][d]["coordinates"]
        == "r"
    }
    sfl_coords = jnp.column_stack([r, a + data["iota"] * z, z])
    desc_coords = eq.compute_theta_coords(sfl_coords)
    grid = Grid(desc_coords, jitable=True)
    return grid, data


# defines the order in which objective arguments get concatenated into the state vector
arg_order = (
    "R_lmn",
    "Z_lmn",
    "L_lmn",
    "p_l",
    "i_l",
    "c_l",
    "Psi",
    "Te_l",
    "ne_l",
    "Ti_l",
    "Zeff_l",
    "a_lmn",
    "Ra_n",
    "Za_n",
    "Rb_lmn",
    "Zb_lmn",
)
# map from profile name to equilibrium parameter name
profile_names = {
    "pressure": "p_l",
    "iota": "i_l",
    "current": "c_l",
    "electron_temperature": "Te_l",
    "electron_density": "ne_l",
    "ion_temperature": "Ti_l",
    "atomic_number": "Zeff_l",
    "anisotropy": "a_lmn",
}
