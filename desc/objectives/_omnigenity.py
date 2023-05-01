"""Objectives for targeting quasisymmetry."""

import warnings

import numpy as np

from desc.backend import jnp
from desc.basis import DoubleFourierSeries
from desc.compute import compute as compute_fun
from desc.compute import get_params, get_profiles, get_transforms
from desc.grid import LinearGrid
from desc.interpolate import interp1d
from desc.utils import Timer
from desc.vmec_utils import ptolemy_linear_transform

from .normalization import compute_scaling_factors
from .objective_funs import _Objective


class QuasisymmetryBoozer(_Objective):
    """Quasi-symmetry Boozer harmonics error.

    Parameters
    ----------
    eq : Equilibrium, optional
        Equilibrium that will be optimized to satisfy the Objective.
    target : float, ndarray, optional
        Target value(s) of the objective. Only used if bounds is None.
        len(target) must be equal to Objective.dim_f
    bounds : tuple, optional
        Lower and upper bounds on the objective. Overrides target.
        len(bounds[0]) and len(bounds[1]) must be equal to Objective.dim_f
    weight : float, ndarray, optional
        Weighting to apply to the Objective, relative to other Objectives.
        len(weight) must be equal to Objective.dim_f
    normalize : bool
        Whether to compute the error in physical units or non-dimensionalize.
    normalize_target : bool
        Whether target and bounds should be normalized before comparing to computed
        values. If `normalize` is `True` and the target is in physical units,
        this should also be set to True.
    grid : Grid, ndarray, optional
        Collocation grid containing the nodes to evaluate at.
        Must be a LinearGrid with a single flux surface and sym=False.
    helicity : tuple, optional
        Type of quasi-symmetry (M, N). Default = quasi-axisymmetry (1, 0).
    M_booz : int, optional
        Poloidal resolution of Boozer transformation. Default = 2 * eq.M.
    N_booz : int, optional
        Toroidal resolution of Boozer transformation. Default = 2 * eq.N.
    name : str
        Name of the objective function.

    """

    _scalar = False
    _linear = False
    _units = "(T)"
    _print_value_fmt = "Quasi-symmetry Boozer error: {:10.3e} "

    def __init__(
        self,
        eq=None,
        target=0,
        bounds=None,
        weight=1,
        normalize=True,
        normalize_target=True,
        grid=None,
        helicity=(1, 0),
        M_booz=None,
        N_booz=None,
        name="QS Boozer",
    ):

        assert len(helicity) == 2
        assert (int(helicity[0]) == helicity[0]) and (int(helicity[1]) == helicity[1])
        self._grid = grid
        self.helicity = helicity
        self.M_booz = M_booz
        self.N_booz = N_booz
        super().__init__(
            eq=eq,
            target=target,
            bounds=bounds,
            weight=weight,
            normalize=normalize,
            normalize_target=normalize_target,
            name=name,
        )

        self._print_value_fmt = (
            "Quasi-symmetry ({},{}) Boozer error: ".format(
                self.helicity[0], self.helicity[1]
            )
            + "{:10.3e} "
        )

    def build(self, eq, use_jit=True, verbose=1):
        """Build constant arrays.

        Parameters
        ----------
        eq : Equilibrium, optional
            Equilibrium that will be optimized to satisfy the Objective.
        use_jit : bool, optional
            Whether to just-in-time compile the objective and derivatives.
        verbose : int, optional
            Level of output.

        """
        M_booz = self.M_booz or 2 * eq.M
        N_booz = self.N_booz or 2 * eq.N

        if self._grid is None:
            grid = LinearGrid(M=2 * M_booz, N=2 * N_booz, NFP=eq.NFP, sym=False)
        else:
            grid = self._grid

        self._data_keys = ["|B|_mn"]
        self._args = get_params(self._data_keys)

        assert grid.sym is False
        assert grid.num_rho == 1

        timer = Timer()
        if verbose > 0:
            print("Precomputing transforms")
        timer.start("Precomputing transforms")

        self._profiles = get_profiles(self._data_keys, eq=eq, grid=grid)
        self._transforms = get_transforms(
            self._data_keys,
            eq=eq,
            grid=grid,
            M_booz=M_booz,
            N_booz=N_booz,
        )
        self._matrix, self._modes, self._idx = ptolemy_linear_transform(
            self._transforms["B"].basis.modes,
            helicity=self.helicity,
            NFP=self._transforms["B"].basis.NFP,
        )

        timer.stop("Precomputing transforms")
        if verbose > 1:
            timer.disp("Precomputing transforms")

        self._dim_f = np.sum(self._idx)

        if self._normalize:
            scales = compute_scaling_factors(eq)
            self._normalization = scales["B"]

        super().build(eq=eq, use_jit=use_jit, verbose=verbose)

    def compute(self, *args, **kwargs):
        """Compute quasi-symmetry Boozer harmonics error.

        Parameters
        ----------
        R_lmn : ndarray
            Spectral coefficients of R(rho,theta,zeta) -- flux surface R coordinate (m).
        Z_lmn : ndarray
            Spectral coefficients of Z(rho,theta,zeta) -- flux surface Z coordinate (m).
        L_lmn : ndarray
            Spectral coefficients of lambda(rho,theta,zeta) -- poloidal stream function.
        i_l : ndarray
            Spectral coefficients of iota(rho) -- rotational transform profile.
        c_l : ndarray
            Spectral coefficients of I(rho) -- toroidal current profile.
        Psi : float
            Total toroidal magnetic flux within the last closed flux surface (Wb).

        Returns
        -------
        f : ndarray
            Quasi-symmetry flux function error at each node (T^3).

        """
        params = self._parse_args(*args, **kwargs)
        data = compute_fun(
            self._data_keys,
            params=params,
            transforms=self._transforms,
            profiles=self._profiles,
        )
        B_mn = self._matrix @ data["|B|_mn"]
        return B_mn[self._idx]

    @property
    def helicity(self):
        """tuple: Type of quasi-symmetry (M, N)."""
        return self._helicity

    @helicity.setter
    def helicity(self, helicity):
        assert (
            (len(helicity) == 2)
            and (int(helicity[0]) == helicity[0])
            and (int(helicity[1]) == helicity[1])
        )
        if hasattr(self, "_helicity") and self._helicity != helicity:
            self._built = False
            warnings.warn("Re-build objective after changing the helicity!")
        self._helicity = helicity
        if hasattr(self, "_print_value_fmt"):
            units = "(T)"
            self._print_value_fmt = (
                "Quasi-symmetry ({},{}) Boozer error: ".format(
                    self.helicity[0], self.helicity[1]
                )
                + "{:10.3e} "
            )


class QuasisymmetryTwoTerm(_Objective):
    """Quasi-symmetry two-term error.

    Parameters
    ----------
    eq : Equilibrium, optional
        Equilibrium that will be optimized to satisfy the Objective.
    target : float, ndarray, optional
        Target value(s) of the objective. Only used if bounds is None.
        len(target) must be equal to Objective.dim_f
    bounds : tuple, optional
        Lower and upper bounds on the objective. Overrides target.
        len(bounds[0]) and len(bounds[1]) must be equal to Objective.dim_f
    weight : float, ndarray, optional
        Weighting to apply to the Objective, relative to other Objectives.
        len(weight) must be equal to Objective.dim_f
    normalize : bool
        Whether to compute the error in physical units or non-dimensionalize.
    normalize_target : bool
        Whether target and bounds should be normalized before comparing to computed
        values. If `normalize` is `True` and the target is in physical units,
        this should also be set to True.
    grid : Grid, ndarray, optional
        Collocation grid containing the nodes to evaluate at.
    helicity : tuple, optional
        Type of quasi-symmetry (M, N).
    name : str
        Name of the objective function.

    """

    _scalar = False
    _linear = False
    _units = "(T^3)"
    _print_value_fmt = "Quasi-symmetry two-term error: {:10.3e} "

    def __init__(
        self,
        eq=None,
        target=0,
        bounds=None,
        weight=1,
        normalize=True,
        normalize_target=True,
        grid=None,
        helicity=(1, 0),
        name="QS two-term",
    ):

        self._grid = grid
        self.helicity = helicity
        super().__init__(
            eq=eq,
            target=target,
            bounds=bounds,
            weight=weight,
            normalize=normalize,
            normalize_target=normalize_target,
            name=name,
        )

        self._print_value_fmt = (
            "Quasi-symmetry ({},{}) two-term error: ".format(
                self.helicity[0], self.helicity[1]
            )
            + "{:10.3e} "
        )

    def build(self, eq, use_jit=True, verbose=1):
        """Build constant arrays.

        Parameters
        ----------
        eq : Equilibrium, optional
            Equilibrium that will be optimized to satisfy the Objective.
        use_jit : bool, optional
            Whether to just-in-time compile the objective and derivatives.
        verbose : int, optional
            Level of output.

        """
        if self._grid is None:
            grid = LinearGrid(M=eq.M_grid, N=eq.N_grid, NFP=eq.NFP, sym=eq.sym)
        else:
            grid = self._grid

        self._dim_f = grid.num_nodes
        self._data_keys = ["f_C"]
        self._args = get_params(self._data_keys)

        timer = Timer()
        if verbose > 0:
            print("Precomputing transforms")
        timer.start("Precomputing transforms")

        self._profiles = get_profiles(self._data_keys, eq=eq, grid=grid)
        self._transforms = get_transforms(self._data_keys, eq=eq, grid=grid)

        timer.stop("Precomputing transforms")
        if verbose > 1:
            timer.disp("Precomputing transforms")

        if self._normalize:
            scales = compute_scaling_factors(eq)
            self._normalization = scales["B"] ** 3

        super().build(eq=eq, use_jit=use_jit, verbose=verbose)

    def compute(self, *args, **kwargs):
        """Compute quasi-symmetry two-term errors.

        Parameters
        ----------
        R_lmn : ndarray
            Spectral coefficients of R(rho,theta,zeta) -- flux surface R coordinate (m).
        Z_lmn : ndarray
            Spectral coefficients of Z(rho,theta,zeta) -- flux surface Z coordinate (m).
        L_lmn : ndarray
            Spectral coefficients of lambda(rho,theta,zeta) -- poloidal stream function.
        i_l : ndarray
            Spectral coefficients of iota(rho) -- rotational transform profile.
        c_l : ndarray
            Spectral coefficients of I(rho) -- toroidal current profile.
        Psi : float
            Total toroidal magnetic flux within the last closed flux surface (Wb).

        Returns
        -------
        f : ndarray
            Quasi-symmetry flux function error at each node (T^3).

        """
        params = self._parse_args(*args, **kwargs)
        data = compute_fun(
            self._data_keys,
            params=params,
            transforms=self._transforms,
            profiles=self._profiles,
            helicity=self.helicity,
        )
        return data["f_C"]

    def compute_scaled(self, *args, **kwargs):
        """Compute and apply the target/bounds, weighting, and normalization."""
        return super().compute_scaled(*args, **kwargs) * jnp.sqrt(
            self._transforms["grid"].weights
        )

    @property
    def helicity(self):
        """tuple: Type of quasi-symmetry (M, N)."""
        return self._helicity

    @helicity.setter
    def helicity(self, helicity):
        assert (
            (len(helicity) == 2)
            and (int(helicity[0]) == helicity[0])
            and (int(helicity[1]) == helicity[1])
        )
        if hasattr(self, "_helicity") and self._helicity != helicity:
            self._built = False
        self._helicity = helicity
        if hasattr(self, "_print_value_fmt"):
            units = "(T^3)"
            self._print_value_fmt = (
                "Quasi-symmetry ({},{}) error: ".format(
                    self.helicity[0], self.helicity[1]
                )
                + "{:10.3e} "
                + units
            )


class QuasisymmetryTripleProduct(_Objective):
    """Quasi-symmetry triple product error.

    Parameters
    ----------
    eq : Equilibrium, optional
        Equilibrium that will be optimized to satisfy the Objective.
    target : float, ndarray, optional
        Target value(s) of the objective. Only used if bounds is None.
        len(target) must be equal to Objective.dim_f
    bounds : tuple, optional
        Lower and upper bounds on the objective. Overrides target.
        len(bounds[0]) and len(bounds[1]) must be equal to Objective.dim_f
    weight : float, ndarray, optional
        Weighting to apply to the Objective, relative to other Objectives.
        len(weight) must be equal to Objective.dim_f
    normalize : bool
        Whether to compute the error in physical units or non-dimensionalize.
    normalize_target : bool
       Whether target and bounds should be normalized before comparing to computed
        values. If `normalize` is `True` and the target is in physical units,
        this should also be set to True.
    grid : Grid, ndarray, optional
        Collocation grid containing the nodes to evaluate at.
    name : str
        Name of the objective function.

    """

    _scalar = False
    _linear = False
    _units = "(T^4/m^2)"
    _print_value_fmt = "Quasi-symmetry error: {:10.3e} "

    def __init__(
        self,
        eq=None,
        target=0,
        bounds=None,
        weight=1,
        normalize=True,
        normalize_target=True,
        grid=None,
        name="QS triple product",
    ):

        self._grid = grid
        super().__init__(
            eq=eq,
            target=target,
            bounds=bounds,
            weight=weight,
            normalize=normalize,
            normalize_target=normalize_target,
            name=name,
        )

    def build(self, eq, use_jit=True, verbose=1):
        """Build constant arrays.

        Parameters
        ----------
        eq : Equilibrium, optional
            Equilibrium that will be optimized to satisfy the Objective.
        use_jit : bool, optional
            Whether to just-in-time compile the objective and derivatives.
        verbose : int, optional
            Level of output.

        """
        if self._grid is None:
            grid = LinearGrid(M=eq.M_grid, N=eq.N_grid, NFP=eq.NFP, sym=eq.sym)
        else:
            grid = self._grid

        self._dim_f = grid.num_nodes
        self._data_keys = ["f_T"]
        self._args = get_params(self._data_keys)

        timer = Timer()
        if verbose > 0:
            print("Precomputing transforms")
        timer.start("Precomputing transforms")

        self._profiles = get_profiles(self._data_keys, eq=eq, grid=grid)
        self._transforms = get_transforms(self._data_keys, eq=eq, grid=grid)

        timer.stop("Precomputing transforms")
        if verbose > 1:
            timer.disp("Precomputing transforms")

        if self._normalize:
            scales = compute_scaling_factors(eq)
            self._normalization = scales["B"] ** 4 / scales["a"] ** 2

        super().build(eq=eq, use_jit=use_jit, verbose=verbose)

    def compute(self, *args, **kwargs):
        """Compute quasi-symmetry triple product errors.

        Parameters
        ----------
        R_lmn : ndarray
            Spectral coefficients of R(rho,theta,zeta) -- flux surface R coordinate (m).
        Z_lmn : ndarray
            Spectral coefficients of Z(rho,theta,zeta) -- flux surface Z coordinate (m).
        L_lmn : ndarray
            Spectral coefficients of lambda(rho,theta,zeta) -- poloidal stream function.
        i_l : ndarray
            Spectral coefficients of iota(rho) -- rotational transform profile.
        c_l : ndarray
            Spectral coefficients of I(rho) -- toroidal current profile.
        Psi : float
            Total toroidal magnetic flux within the last closed flux surface (Wb).

        Returns
        -------
        f : ndarray
            Quasi-symmetry flux function error at each node (T^4/m^2).

        """
        params = self._parse_args(*args, **kwargs)
        data = compute_fun(
            self._data_keys,
            params=params,
            transforms=self._transforms,
            profiles=self._profiles,
        )
        return data["f_T"]

    def compute_scaled(self, *args, **kwargs):
        """Compute and apply the target/bounds, weighting, and normalization."""
        return super().compute_scaled(*args, **kwargs) * jnp.sqrt(
            self._transforms["grid"].weights
        )


class Omnigenity(_Objective):
    """Omnigenity error.

    Parameters
    ----------
    eq : Equilibrium, optional
        Equilibrium that will be optimized to satisfy the Objective.
    target : float, ndarray, optional
        Target value(s) of the objective. Only used if bounds is None.
        len(target) must be equal to Objective.dim_f
    bounds : tuple, optional
        Lower and upper bounds on the objective. Overrides target.
        len(bounds[0]) and len(bounds[1]) must be equal to Objective.dim_f
    weight : float, ndarray, optional
        Weighting to apply to the Objective, relative to other Objectives.
        len(weight) must be equal to Objective.dim_f
    normalize : bool
        Whether to compute the error in physical units or non-dimensionalize.
    normalize_target : bool
       Whether target and bounds should be normalized before comparing to computed
        values. If `normalize` is `True` and the target is in physical units,
        this should also be set to True.
    grid : Grid, ndarray, optional
        Collocation grid containing the nodes to evaluate at.
    helicity : tuple, optional
        Type of omnigenity (M, N). Default = quasi-isodynamic (0, 1).
    M_booz : int, optional
        Poloidal resolution of Boozer transformation. Default = 2 * eq.M.
    N_booz : int, optional
        Toroidal resolution of Boozer transformation. Default = 2 * eq.N.
    well_weight : float, optional
        Weight applied to the bottom of the magnetic well (B_min) relative to the top
        of the magnetic well (B_max). Default = 1, which weights all points equally.
    name : str
        Name of the objective function.

    """

    _scalar = False
    _linear = False
    _units = "(T)"
    _print_value_fmt = "Omnigenity error: {:10.3e} "

    def __init__(
        self,
        eq=None,
        target=0,
        bounds=None,
        weight=1,
        normalize=True,
        normalize_target=True,
        grid=None,
        helicity=(0, 1),
        M_booz=None,
        N_booz=None,
        well_weight=1,
        name="omnigenity",
    ):

        assert len(helicity) == 2
        assert (int(helicity[0]) == helicity[0]) and (int(helicity[1]) == helicity[1])
        self._grid = grid
        self.helicity = helicity
        self.M_booz = M_booz
        self.N_booz = N_booz
        self.well_weight = well_weight
        super().__init__(
            eq=eq,
            target=target,
            bounds=bounds,
            weight=weight,
            normalize=normalize,
            normalize_target=normalize_target,
            name=name,
        )

    def build(self, eq, use_jit=True, verbose=1):
        """Build constant arrays.

        Parameters
        ----------
        eq : Equilibrium, optional
            Equilibrium that will be optimized to satisfy the Objective.
        use_jit : bool, optional
            Whether to just-in-time compile the objective and derivatives.
        verbose : int, optional
            Level of output.

        """
        M_booz = self.M_booz or 2 * eq.M
        N_booz = self.N_booz or 2 * eq.N

        if self._grid is None:
            grid = LinearGrid(M=2 * M_booz, N=2 * N_booz, NFP=eq.NFP, sym=False)
        else:
            grid = self._grid

        self._dim_f = grid.num_nodes
        self._data_keys = ["omnigenity"]
        self._args = get_params(self._data_keys)

        assert grid.sym is False
        assert grid.num_rho == 1

        timer = Timer()
        if verbose > 0:
            print("Precomputing transforms")
        timer.start("Precomputing transforms")

        self._profiles = get_profiles(self._data_keys, eq=eq, grid=grid)
        self._transforms = get_transforms(
            self._data_keys,
            eq=eq,
            grid=grid,
            M_booz=self.M_booz,
            N_booz=self.N_booz,
        )

        timer.stop("Precomputing transforms")
        if verbose > 1:
            timer.disp("Precomputing transforms")

        if self._normalize:
            self._normalization = jnp.mean(eq.well_l[:eq.M_well])  # average |B| on axis

        super().build(eq=eq, use_jit=use_jit, verbose=verbose)

    def compute(self, *args, **kwargs):
        """Compute omnigenity errors.

        Parameters
        ----------
        R_lmn : ndarray
            Spectral coefficients of R(rho,theta,zeta) -- flux surface R coordinate (m).
        Z_lmn : ndarray
            Spectral coefficients of Z(rho,theta,zeta) -- flux surface Z coordinate (m).
        L_lmn : ndarray
            Spectral coefficients of lambda(rho,theta,zeta) -- poloidal stream function.
        i_l : ndarray
            Spectral coefficients of iota(rho) -- rotational transform profile.
        c_l : ndarray
            Spectral coefficients of I(rho) -- toroidal current profile.
        Psi : float
            Total toroidal magnetic flux within the last closed flux surface (Wb).
        well_l : ndarray
            Spectral coefficients of B(eta).
        omni_lmn : ndarray
            Spectral coefficients of tilde(zeta)_B(rho, alpha, eta).

        Returns
        -------
        f : ndarray
            Omnigenity error at each node (T).

        """
        params = self._parse_args(*args, **kwargs)
        data = compute_fun(
            self._data_keys,
            params=params,
            transforms=self._transforms,
            profiles=self._profiles,
            helicity=self.helicity,
        )
        weights = (self.well_weight + 1) / 2 + (self.well_weight - 1) / 2 * jnp.cos(
            data["eta"]
        )
        return data["omnigenity"] * weights

    def compute_scaled(self, *args, **kwargs):
        """Compute and apply the target/bounds, weighting, and normalization."""
        return super().compute_scaled(*args, **kwargs) * jnp.sqrt(
            self._transforms["grid"].weights
        )

    @property
    def helicity(self):
        """tuple: Type of omnigenity (M, N)."""
        return self._helicity

    @helicity.setter
    def helicity(self, helicity):
        assert (
            (len(helicity) == 2)
            and (int(helicity[0]) == helicity[0])
            and (int(helicity[1]) == helicity[1])
        )
        if hasattr(self, "_helicity") and self._helicity != helicity:
            self._built = False
            warnings.warn("Re-build objective after changing the helicity!")
        self._helicity = helicity
        if hasattr(self, "_print_value_fmt"):
            units = "(T)"
            self._print_value_fmt = (
                "Omnigenity ({},{}) error: ".format(
                    self.helicity[0], self.helicity[1]
                )
                + "{:10.3e} "
            )


class Isodynamicity(_Objective):
    """Isodynamicity metric for cross field transport.

    Note: This is NOT the same as Quasi-isodynamicity (QI), which is a more general
    condition. This specifically penalizes the local cross field transport, rather than
    just the average.

    Parameters
    ----------
    eq : Equilibrium, optional
        Equilibrium that will be optimized to satisfy the Objective.
    target : float, ndarray, optional
        Target value(s) of the objective. Only used if bounds is None.
        len(target) must be equal to Objective.dim_f
    bounds : tuple, optional
        Lower and upper bounds on the objective. Overrides target.
        len(bounds[0]) and len(bounds[1]) must be equal to Objective.dim_f
    weight : float, ndarray, optional
        Weighting to apply to the Objective, relative to other Objectives.
        len(weight) must be equal to Objective.dim_f
    normalize : bool
        Whether to compute the error in physical units or non-dimensionalize.
        Has no effect for this objective.
    normalize_target : bool
       Whether target and bounds should be normalized before comparing to computed
        values. If `normalize` is `True` and the target is in physical units,
        this should also be set to True.
        Has no effect for this objective.
    grid : Grid, ndarray, optional
        Collocation grid containing the nodes to evaluate at.
    name : str
        Name of the objective function.

    """

    _scalar = False
    _linear = False
    _units = "(dimensionless)"
    _print_value_fmt = "Isodynamicity error: {:10.3e} "

    def __init__(
        self,
        eq=None,
        target=0,
        bounds=None,
        weight=1,
        normalize=False,
        normalize_target=False,
        grid=None,
        name="Isodynamicity",
    ):

        self._grid = grid
        super().__init__(
            eq=eq,
            target=target,
            bounds=bounds,
            weight=weight,
            normalize=normalize,
            normalize_target=normalize_target,
            name=name,
        )

    def build(self, eq, use_jit=True, verbose=1):
        """Build constant arrays.

        Parameters
        ----------
        eq : Equilibrium, optional
            Equilibrium that will be optimized to satisfy the Objective.
        use_jit : bool, optional
            Whether to just-in-time compile the objective and derivatives.
        verbose : int, optional
            Level of output.

        """
        if self._grid is None:
            grid = LinearGrid(M=eq.M_grid, N=eq.N_grid, NFP=eq.NFP, sym=eq.sym)
        else:
            grid = self._grid

        self._dim_f = grid.num_nodes
        self._data_keys = ["isodynamicity"]
        self._args = get_params(self._data_keys)

        timer = Timer()
        if verbose > 0:
            print("Precomputing transforms")
        timer.start("Precomputing transforms")

        self._profiles = get_profiles(self._data_keys, eq=eq, grid=grid)
        self._transforms = get_transforms(self._data_keys, eq=eq, grid=grid)

        timer.stop("Precomputing transforms")
        if verbose > 1:
            timer.disp("Precomputing transforms")

        super().build(eq=eq, use_jit=use_jit, verbose=verbose)

    def compute(self, *args, **kwargs):
        """Compute isodynamicity errors.

        Parameters
        ----------
        R_lmn : ndarray
            Spectral coefficients of R(rho,theta,zeta) -- flux surface R coordinate (m).
        Z_lmn : ndarray
            Spectral coefficients of Z(rho,theta,zeta) -- flux surface Z coordinate (m).
        L_lmn : ndarray
            Spectral coefficients of lambda(rho,theta,zeta) -- poloidal stream function.
        i_l : ndarray
            Spectral coefficients of iota(rho) -- rotational transform profile.
        c_l : ndarray
            Spectral coefficients of I(rho) -- toroidal current profile.
        Psi : float
            Total toroidal magnetic flux within the last closed flux surface (Wb).

        Returns
        -------
        f : ndarray
            Isodynamicity error at each node (~).

        """
        params = self._parse_args(*args, **kwargs)
        data = compute_fun(
            self._data_keys,
            params=params,
            transforms=self._transforms,
            profiles=self._profiles,
        )
        return data["isodynamicity"]

    def compute_scaled(self, *args, **kwargs):
        """Compute and apply the target/bounds, weighting, and normalization."""
        return super().compute_scaled(*args, **kwargs) * jnp.sqrt(
            self._transforms["grid"].weights
        )
