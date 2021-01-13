import numpy as np
from termcolor import colored

from desc.backend import put
from desc.io import IOAble
from desc.utils import Tristate, unpack_state
from desc.grid import Grid, LinearGrid, ConcentricGrid
from desc.transform import Transform
from desc.basis import (
    PowerSeries,
    FourierSeries,
    DoubleFourierSeries,
    FourierZernikeBasis,
)

from desc.compute_funs import (
    compute_polar_coords,
    compute_toroidal_coords,
    compute_cartesian_coords,
    compute_profiles,
    compute_covariant_basis,
    compute_contravariant_basis,
    compute_jacobian,
    compute_magnetic_field_magnitude_axis,
    compute_current_density,
    compute_force_error,
    compute_force_error_magnitude,
)


class Configuration(IOAble):
    """Configuration contains information about a plasma state, including the
    shapes of flux surfaces and profile inputs. It can compute additional
    information, such as the magnetic field and plasma currents.
    """

    _io_attrs_ = [
        "_R0_n",
        "_Z0_n",
        "_r_lmn",
        "_l_lmn",
        "_R1_mn",
        "_Z1_mn",
        "_p_l",
        "_i_l",
        "_Psi",
        "_NFP",
        "_R0_basis",
        "_Z0_basis",
        "_r_basis",
        "_l_basis",
        "_R1_basis",
        "_Z1_basis",
        "_p_basis",
        "_i_basis",
    ]

    _object_lib_ = {
        "PowerSeries": PowerSeries,
        "FourierSeries": FourierSeries,
        "DoubleFourierSeries": DoubleFourierSeries,
        "FourierZernikeBasis": FourierZernikeBasis,
        "LinearGrid": LinearGrid,
        "ConcentricGrid": ConcentricGrid,
    }

    def __init__(
        self,
        inputs: dict = None,
        load_from=None,
        file_format: str = "hdf5",
        obj_lib=None,
    ) -> None:
        """Initializes a Configuration

        Parameters
        ----------
        inputs : dict
            Dictionary of inputs with the following required keys:
                Psi : float, total toroidal flux (in Webers) within LCFS
                NFP : int, number of field periods
                L : int, radial resolution
                M : int, poloidal resolution
                N : int, toroidal resolution
                profiles : ndarray, array of profile coeffs [l, p_l, i_l]
                boundary : ndarray, array of boundary coeffs [m, n, R1_mn, Z1_mn]
            And the following optional keys:
                sym : bool, is the problem stellarator symmetric or not, default is False
                index : str, type of Zernike indexing scheme to use, default is 'ansi'
                bdry_mode : str, how to calculate error at bdry, default is 'spectral'
                zeta_ratio : float, Multiplier on the toroidal derivatives. Default = 1.0.
                axis : ndarray, array of magnetic axis coeffs [n, R0_n, Z0_n]
                x : ndarray, state vector [R0_n, Z0_n, r_lmn, l_lmn]
                R0_n : ndarray, spectral coefficients of R0
                Z0_n : ndarray, spectral coefficients of Z0
                r_lmn : ndarray, spectral coefficients of r
                l_lmn : ndarray, spectral coefficients of lambda
        load_from : str file path OR file instance
            file to initialize from
        file_format : str
            file format of file initializing from. Default is 'hdf5'

        Returns
        -------
        None

        """
        self._file_format_ = file_format
        if load_from is None:
            self.inputs = inputs
            self._init_from_inputs_(inputs=inputs)
        else:
            self._init_from_file_(
                load_from=load_from, file_format=file_format, obj_lib=obj_lib
            )
        self._make_labels()

    def _init_from_inputs_(self, inputs: dict = None) -> None:
        # required inputs
        try:
            self._Psi = inputs["Psi"]
            self._NFP = inputs["NFP"]
            self._L = inputs["L"]
            self._M = inputs["M"]
            self._N = inputs["N"]
            profiles = inputs["profiles"]
            boundary = inputs["boundary"]
        except:
            raise ValueError(colored("input dict does not contain proper keys", "red"))

        # optional inputs
        self._sym = inputs.get("sym", False)
        self._index = inputs.get("index", "ansi")
        self._bdry_mode = inputs.get("bdry_mode", "spectral")
        self._zeta_ratio = inputs.get("zeta_ratio", 1.0)

        # stellarator symmetry for bases
        if self._sym:
            self._R_sym = Tristate(True)
            self._Z_sym = Tristate(False)
        else:
            self._R_sym = Tristate(None)
            self._Z_sym = Tristate(None)

        # create bases
        self._R0_basis = FourierSeries(N=self._N, NFP=self._NFP, sym=self._R_sym)
        self._Z0_basis = FourierSeries(N=self._N, NFP=self._NFP, sym=self._Z_sym)
        self._r_basis = FourierZernikeBasis(
            L=self._L,
            M=self._M,
            N=self._N,
            NFP=self._NFP,
            sym=self._R_sym,
            index=self._index,
        )
        self._l_basis = FourierZernikeBasis(
            L=self._L,
            M=self._M,
            N=self._N,
            NFP=self._NFP,
            sym=self._Z_sym,
            index=self._index,
        )
        self._R1_basis = DoubleFourierSeries(
            M=int(np.max(np.abs(boundary[:, 0]))),
            N=int(np.max(np.abs(boundary[:, 1]))),
            NFP=self._NFP,
            sym=self._R_sym,
        )
        self._Z1_basis = DoubleFourierSeries(
            M=int(np.max(np.abs(boundary[:, 0]))),
            N=int(np.max(np.abs(boundary[:, 1]))),
            NFP=self._NFP,
            sym=self._Z_sym,
        )
        self._p_basis = PowerSeries(L=int(np.max(profiles[:, 0])))
        self._i_basis = PowerSeries(L=int(np.max(profiles[:, 0])))

        # format profiles
        self._p_l, self._i_l = format_profiles(profiles, self._p_basis, self._i_basis)

        # format boundary
        self._R1_mn, self._Z1_mn = format_boundary(
            boundary, self._R1_basis, self._Z1_basis, self._bdry_mode
        )

        # check if state vector is provided
        try:
            self._x = inputs["x"]
            self._R0_n, self._Z0_n, self._r_lmn, self._l_lmn = unpack_state(
                self._x,
                self._R0_basis.num_modes,
                self._Z0_basis.num_modes,
                self._r_basis.num_modes,
                self._l_basis.num_modes,
            )
        except:
            # check if magnetic axis is provided
            try:
                self._R0_n = inputs["R0_n"]
                self._Z0_n = inputs["Z0_n"]

            except:
                axis = inputs.get(
                    "axis", boundary[np.where(boundary[:, 0] == 0)[0], 1:]
                )
                self._R0_n, self._Z0_n = format_axis(
                    axis, self._R0_basis, self._Z0_basis
                )
            # check if radius is provided
            try:
                self._r_lmn = inputs["r_lmn"]
            except:
                self._r_lmn = np.zeros((self._r_basis.num_modes,))
                try:
                    # index of m = n = 0 modes with l <= 4
                    idx = np.where(
                        np.logical_and.reduce(
                            (
                                self._r_basis.modes[:, 0] <= 4,
                                self._r_basis.modes[:, 1] == 0,
                                self._r_basis.modes[:, 2] == 0,
                            )
                        )
                    )[0]
                    self._r_lmn = put(self._r_lmn, idx, np.array([0.65, 0.5, -0.15]))
                except:
                    # index of m = n = 0 modes with l <= 2
                    idx = np.where(
                        np.logical_and.reduce(
                            (
                                self._r_basis.modes[:, 0] <= 2,
                                self._r_basis.modes[:, 1] == 0,
                                self._r_basis.modes[:, 2] == 0,
                            )
                        )
                    )[0]
                    self._r_lmn = put(self._r_lmn, idx, np.array([0.5, 0.5]))

            # check if lambda is provided
            try:
                self._l_lmn = inputs["l_lmn"]
            except:
                self._l_lmn = np.zeros((self._l_basis.num_modes,))
            self._x = np.concatenate([self._R0_n, self._Z0_n, self._r_lmn, self._l_lmn])

    def change_resolution(
        self, L: int = None, M: int = None, N: int = None, *args, **kwargs
    ) -> None:

        L_change = M_change = N_change = False
        if L is not None and L != self._L:
            L_change = True
            self._L = L
        if M is not None and M != self._M:
            M_change = True
            self._M = M
        if N is not None and N != self._N:
            N_change = True
            self._N = N

        if not np.any([L_change, M_change, N_change]):
            return

        old_modes_R0 = self._R0_basis.modes
        old_modes_Z0 = self._Z0_basis.modes
        old_modes_r = self._r_basis.modes
        old_modes_l = self._l_basis.modes
        old_modes_R1 = self._R1_basis.modes
        old_modes_Z1 = self._Z1_basis.modes

        # create bases
        self._R0_basis = FourierSeries(N=self._N, NFP=self._NFP, sym=self._R_sym)
        self._Z0_basis = FourierSeries(N=self._N, NFP=self._NFP, sym=self._Z_sym)
        self._r_basis = FourierZernikeBasis(
            L=self._L,
            M=self._M,
            N=self._N,
            NFP=self._NFP,
            sym=self._R_sym,
            index=self._index,
        )
        self._l_basis = FourierZernikeBasis(
            L=self._L,
            M=self._M,
            N=self._N,
            NFP=self._NFP,
            sym=self._Z_sym,
            index=self._index,
        )
        self._R1_basis = DoubleFourierSeries(
            M=self._M, N=self._N, NFP=self._NFP, sym=self._R_sym
        )
        self._Z1_basis = DoubleFourierSeries(
            M=self._M, N=self._N, NFP=self._NFP, sym=self._Z_sym
        )

        def copy_coeffs(c_old, modes_old, modes_new):
            num_modes = modes_new.shape[0]
            c_new = np.zeros((num_modes,))

            for i in range(num_modes):
                idx = np.where(
                    np.all(
                        np.array(
                            [
                                np.array(modes_old[:, 0] == modes_new[i, 0]),
                                np.array(modes_old[:, 1] == modes_new[i, 1]),
                                np.array(modes_old[:, 2] == modes_new[i, 2]),
                            ]
                        ),
                        axis=0,
                    )
                )[0]
                if len(idx):
                    c_new[i] = c_old[idx[0]]
            return c_new

        self._R0_n = copy_coeffs(self._R0_n, old_modes_R0, self._R0_basis.modes)
        self._Z0_n = copy_coeffs(self._Z0_n, old_modes_Z0, self._Z0_basis.modes)
        self._r_lmn = copy_coeffs(self._r_lmn, old_modes_r, self._r_basis.modes)
        self._l_lmn = copy_coeffs(self._l_lmn, old_modes_l, self._l_basis.modes)
        self._R1_mn = copy_coeffs(self._R1_mn, old_modes_R1, self._R1_basis.modes)
        self._Z1_mn = copy_coeffs(self._Z1_mn, old_modes_Z1, self._Z1_basis.modes)

        # state vector
        self._x = np.concatenate([self._R0_n, self._Z0_n, self._r_lmn, self._l_lmn])
        self._make_labels()

    @property
    def sym(self) -> bool:
        return self._sym

    @property
    def x(self):
        return self._x

    @x.setter
    def x(self, x) -> None:
        self._x = x
        self._R0_n, self._Z0_n, self._r_lmn, self._l_lmn = unpack_state(
            self._x,
            self._R0_basis.num_modes,
            self._Z0_basis.num_modes,
            self._r_basis.num_modes,
            self._l_basis.num_modes,
        )

    @property
    def R0_n(self):
        """ spectral coefficients of R """
        return self._R0_n

    @R0_n.setter
    def R0_n(self, R0_n) -> None:
        self._R0_n = R0_n
        self._x = np.concatenate([self._R0_n, self._Z0_n, self._r_lmn, self._l_lmn])

    @property
    def Z0_n(self):
        """ spectral coefficients of Z """
        return self._Z0_n

    @Z0_n.setter
    def Z0_n(self, Z0_n) -> None:
        self._Z0_n = Z0_n
        self._x = np.concatenate([self._R0_n, self._Z0_n, self._r_lmn, self._l_lmn])

    @property
    def r_lmn(self):
        """ spectral coefficients of r """
        return self._r_lmn

    @r_lmn.setter
    def r_lmn(self, r_lmn) -> None:
        self._r_lmn = r_lmn
        self._x = np.concatenate([self._R0_n, self._Z0_n, self._r_lmn, self._l_lmn])

    @property
    def l_lmn(self):
        """ spectral coefficients of lambda """
        return self._l_lmn

    @l_lmn.setter
    def l_lmn(self, l_lmn) -> None:
        self._l_lmn = l_lmn
        self._x = np.concatenate([self._R0_n, self._Z0_n, self._r_lmn, self._l_lmn])

    @property
    def R1_mn(self):
        """ spectral coefficients of R at the boundary"""
        return self._R1_mn

    @R1_mn.setter
    def R1_mn(self, R1_mn) -> None:
        self._R1_mn = R1_mn

    @property
    def Z1_mn(self):
        """ spectral coefficients of Z at the boundary"""
        return self._Z1_mn

    @Z1_mn.setter
    def Z1_mn(self, Z1_mn) -> None:
        self._Z1_mn = Z1_mn

    @property
    def p_l(self):
        """ spectral coefficients of pressure """
        return self._p_l

    @p_l.setter
    def p_l(self, p_l) -> None:
        self._p_l = p_l

    @property
    def i_l(self):
        """ spectral coefficients of iota """
        return self._i_l

    @i_l.setter
    def i_l(self, i_l) -> None:
        self._i_l = i_l

    @property
    def Psi(self) -> float:
        """ float, total toroidal flux (in Webers) within LCFS"""
        return self._Psi

    @Psi.setter
    def Psi(self, Psi) -> None:
        self._Psi = Psi

    @property
    def NFP(self) -> int:
        """ int, number of field periods"""
        return self._NFP

    @NFP.setter
    def NFP(self, NFP) -> None:
        self._NFP = NFP

    @property
    def L(self) -> int:
        return self._L

    @property
    def M(self) -> int:
        return self._M

    @property
    def N(self) -> int:
        return self._N

    @property
    def R0_basis(self) -> FourierSeries:
        """
        Spectral basis for R0

        Returns
        -------
        FourierSeries

        """
        return self._R0_basis

    @R0_basis.setter
    def R0_basis(self, R0_basis: FourierSeries) -> None:
        self._R0_basis = R0_basis
        self._make_labels()

    @property
    def Z0_basis(self) -> FourierSeries:
        """
        Spectral basis for Z0

        Returns
        -------
        FourierSeries

        """
        return self._Z0_basis

    @Z0_basis.setter
    def Z0_basis(self, Z0_basis: FourierSeries) -> None:
        self._Z0_basis = Z0_basis
        self._make_labels()

    @property
    def r_basis(self) -> FourierZernikeBasis:
        """
        Spectral basis for r

        Returns
        -------
        FourierZernikeBasis

        """
        return self._r_basis

    @r_basis.setter
    def r_basis(self, r_basis: FourierZernikeBasis) -> None:
        self._r_basis = r_basis
        self._make_labels()

    @property
    def l_basis(self) -> FourierZernikeBasis:
        """
        Spectral basis for lambda

        Returns
        -------
        FourierZernikeBasis

        """
        return self._l_basis

    @l_basis.setter
    def l_basis(self, l_basis: FourierZernikeBasis) -> None:
        self._l_basis = l_basis
        self._make_labels()

    @property
    def R1_basis(self) -> DoubleFourierSeries:
        """
        Spectral basis for R at the boundary

        Returns
        -------
        DoubleFourierSeries

        """
        return self._R1_basis

    @R1_basis.setter
    def R1_basis(self, R1_basis: DoubleFourierSeries) -> None:
        self._R1_basis = R1_basis

    @property
    def Z1_basis(self) -> DoubleFourierSeries:
        """
        Spectral basis for Z at the boundary

        Returns
        -------
        DoubleFourierSeries

        """
        return self._Z1_basis

    @Z1_basis.setter
    def Z1_basis(self, Z1_basis: DoubleFourierSeries) -> None:
        self._Z1_basis = Z1_basis

    @property
    def p_basis(self) -> PowerSeries:
        """
        Spectral basis for pressure

        Returns
        -------
        PowerSeries

        """
        return self._p_basis

    @p_basis.setter
    def p_basis(self, p_basis: PowerSeries) -> None:
        self._p_basis = p_basis

    @property
    def i_basis(self) -> PowerSeries:
        """
        Spectral basis for rotational transform

        Returns
        -------
        PowerSeries

        """
        return self._i_basis

    @i_basis.setter
    def i_basis(self, i_basis: PowerSeries) -> None:
        self._i_basis = i_basis

    def _make_labels(self):
        R0_label = ["R0_{}".format(n) for n in self._R0_basis.modes[:, 2]]
        Z0_label = ["Z0_{}".format(n) for n in self._Z0_basis.modes[:, 2]]
        r_label = ["r_{},{},{}".format(l, m, n) for l, m, n in self._r_basis.modes]
        l_label = ["l_{},{},{}".format(l, m, n) for l, m, n in self._l_basis.modes]

        x_label = R0_label + Z0_label + r_label + l_label

        self.xlabel = {i: val for i, val in enumerate(x_label)}
        self.rev_xlabel = {val: i for i, val in self.xlabel.items()}

    def get_xlabel_by_idx(self, idx):
        """Find which mode corresponds to a given entry in x"""

        idx = np.atleast_1d(idx)
        labels = [self.xlabel.get(i, None) for i in idx]
        return labels

    def get_idx_by_xlabel(self, labels):
        """Find which index of x corresponds to a given mode"""

        if not isinstance(labels, (list, tuple)):
            labels = list(labels)
        idx = [self.rev_xlabel.get(label, None) for label in labels]
        return np.array(idx)

    def compute_polar_coords(self, grid: Grid) -> dict:
        """Transforms spectral coefficients of polar coordinates to real space.

        Parameters
        ----------
        grid : Grid
            Collocation grid containing the (rho, theta, zeta) coordinates of
            the nodes to evaluate at.

        Returns
        -------
        polar_coords : dict
            dictionary of ndarray, shape(num_nodes,) of polar coordinates.
            Keys are of the form 'X_y' meaning the derivative of X wrt to y.

        """
        R0_transform = Transform(grid, self._R0_basis, derivs=2)
        Z0_transform = Transform(grid, self._Z0_basis, derivs=2)
        r_transform = Transform(grid, self._r_basis, derivs=2)
        l_transform = Transform(grid, self._l_basis, derivs=2)
        R1_transform = Transform(grid, self._R1_basis, derivs=2)
        Z1_transform = Transform(grid, self._Z1_basis, derivs=2)
        p_transform = Transform(grid, self._p_basis, derivs=0)
        i_transform = Transform(grid, self._i_basis, derivs=1)

        (
            current_density,
            magnetic_field,
            profiles,
            jacobian,
            cov_basis,
            toroidal_coords,
            polar_coords,
        ) = compute_current_density(
            self._Psi,
            self._R0_n,
            self._Z0_n,
            self._r_lmn,
            self._l_lmn,
            self._R1_mn,
            self._Z1_mn,
            self._p_l,
            self._i_l,
            R0_transform,
            Z0_transform,
            r_transform,
            l_transform,
            R1_transform,
            Z1_transform,
            p_transform,
            i_transform,
            self._zeta_ratio,
        )

        return polar_coords

    def compute_toroidal_coords(self, grid: Grid) -> dict:
        """Computes toroidal coordinates from polar coordinates.

        Parameters
        ----------
        grid : Grid
            Collocation grid containing the (rho, theta, zeta) coordinates of
            the nodes to evaluate at.

        Returns
        -------
        toroidal_coords : dict
            dictionary of ndarray, shape(num_nodes,) of toroidal coordinates.
            Keys are of the form 'X_y' meaning the derivative of X wrt to y.

        """
        R0_transform = Transform(grid, self._R0_basis, derivs=2)
        Z0_transform = Transform(grid, self._Z0_basis, derivs=2)
        r_transform = Transform(grid, self._r_basis, derivs=2)
        l_transform = Transform(grid, self._l_basis, derivs=2)
        R1_transform = Transform(grid, self._R1_basis, derivs=2)
        Z1_transform = Transform(grid, self._Z1_basis, derivs=2)
        p_transform = Transform(grid, self._p_basis, derivs=0)
        i_transform = Transform(grid, self._i_basis, derivs=1)

        (
            current_density,
            magnetic_field,
            profiles,
            jacobian,
            cov_basis,
            toroidal_coords,
            polar_coords,
        ) = compute_current_density(
            self._Psi,
            self._R0_n,
            self._Z0_n,
            self._r_lmn,
            self._l_lmn,
            self._R1_mn,
            self._Z1_mn,
            self._p_l,
            self._i_l,
            R0_transform,
            Z0_transform,
            r_transform,
            l_transform,
            R1_transform,
            Z1_transform,
            p_transform,
            i_transform,
            self._zeta_ratio,
        )

        return toroidal_coords

    def compute_cartesian_coords(self, grid: Grid) -> dict:
        """Computes cartesian coordinates from toroidal coordinates.

        Parameters
        ----------
        grid : Grid
            Collocation grid containing the (rho, theta, zeta) coordinates of
            the nodes to evaluate at.

        Returns
        -------
        toroidal_coords : dict
            dictionary of ndarray, shape(num_nodes,) of toroidal coordinates.
            Keys are of the form 'X_y' meaning the derivative of X wrt to y.

        """
        R0_transform = Transform(grid, self._R0_basis, derivs=0)
        Z0_transform = Transform(grid, self._Z0_basis, derivs=0)
        r_transform = Transform(grid, self._r_basis, derivs=0)
        l_transform = Transform(grid, self._l_basis, derivs=0)
        R1_transform = Transform(grid, self._R1_basis, derivs=0)
        Z1_transform = Transform(grid, self._Z1_basis, derivs=0)
        p_transform = Transform(grid, self._p_basis, derivs=0)
        i_transform = Transform(grid, self._i_basis, derivs=0)

        (cartesian_coords, toroidal_coords, polar_coords) = compute_cartesian_coords(
            self._Psi,
            self._R0_n,
            self._Z0_n,
            self._r_lmn,
            self._l_lmn,
            self._R1_mn,
            self._Z1_mn,
            self._p_l,
            self._i_l,
            R0_transform,
            Z0_transform,
            r_transform,
            l_transform,
            R1_transform,
            Z1_transform,
            p_transform,
            i_transform,
            self._zeta_ratio,
        )

        return cartesian_coords

    def compute_profiles(self, grid: Grid) -> dict:
        """Computes magnetic flux, pressure, and rotational transform profiles.

        Parameters
        ----------
        grid : Grid
            Collocation grid containing the (rho, theta, zeta) coordinates of
            the nodes to evaluate at.

        Returns
        -------
        profiles : dict
            dictionary of ndarray, shape(num_nodes,) of profiles.
            Keys are of the form 'X_y' meaning the derivative of X wrt to y.

        """
        R0_transform = Transform(grid, self._R0_basis, derivs=2)
        Z0_transform = Transform(grid, self._Z0_basis, derivs=2)
        r_transform = Transform(grid, self._r_basis, derivs=2)
        l_transform = Transform(grid, self._l_basis, derivs=2)
        R1_transform = Transform(grid, self._R1_basis, derivs=2)
        Z1_transform = Transform(grid, self._Z1_basis, derivs=2)
        p_transform = Transform(grid, self._p_basis, derivs=1)
        i_transform = Transform(grid, self._i_basis, derivs=1)

        (
            force_error,
            current_density,
            magnetic_field,
            profiles,
            jacobian,
            cov_basis,
            toroidal_coords,
            polar_coords,
        ) = compute_force_error(
            self._Psi,
            self._R0_n,
            self._Z0_n,
            self._r_lmn,
            self._l_lmn,
            self._R1_mn,
            self._Z1_mn,
            self._p_l,
            self._i_l,
            R0_transform,
            Z0_transform,
            r_transform,
            l_transform,
            R1_transform,
            Z1_transform,
            p_transform,
            i_transform,
            self._zeta_ratio,
        )

        return profiles

    def compute_covariant_basis(self, grid: Grid) -> dict:
        """Computes covariant basis vectors.

        Parameters
        ----------
        grid : Grid
            Collocation grid containing the (rho, theta, zeta) coordinates of
            the nodes to evaluate at.

        Returns
        -------
        cov_basis : dict
            dictionary of ndarray, shape(3,num_nodes), of covariant basis vectors.
            Keys are of the form 'e_x_y', meaning the covariant basis vector in
            the x direction, differentiated wrt to y.

        """
        R0_transform = Transform(grid, self._R0_basis, derivs=1)
        Z0_transform = Transform(grid, self._Z0_basis, derivs=1)
        r_transform = Transform(grid, self._r_basis, derivs=1)
        l_transform = Transform(grid, self._l_basis, derivs=0)
        R1_transform = Transform(grid, self._R1_basis, derivs=1)
        Z1_transform = Transform(grid, self._Z1_basis, derivs=1)
        p_transform = Transform(grid, self._p_basis, derivs=0)
        i_transform = Transform(grid, self._i_basis, derivs=0)

        (cov_basis, toroidal_coords, polar_coords) = compute_covariant_basis(
            self._Psi,
            self._R0_n,
            self._Z0_n,
            self._r_lmn,
            self._l_lmn,
            self._R1_mn,
            self._Z1_mn,
            self._p_l,
            self._i_l,
            R0_transform,
            Z0_transform,
            r_transform,
            l_transform,
            R1_transform,
            Z1_transform,
            p_transform,
            i_transform,
            self._zeta_ratio,
        )

        return cov_basis

    def compute_contravariant_basis(self, grid: Grid) -> dict:
        """Computes contravariant basis vectors.

        Parameters
        ----------
        grid : Grid
            Collocation grid containing the (rho, theta, zeta) coordinates of
            the nodes to evaluate at.

        Returns
        -------
        con_basis : dict
            dictionary of ndarray, shape(3,num_nodes), of contravariant basis vectors.
            Keys are of the form 'e^x_y', meaning the contravariant basis vector
            in the x direction, differentiated wrt to y.

        """
        R0_transform = Transform(grid, self._R0_basis, derivs=1)
        Z0_transform = Transform(grid, self._Z0_basis, derivs=1)
        r_transform = Transform(grid, self._r_basis, derivs=1)
        l_transform = Transform(grid, self._l_basis, derivs=0)
        R1_transform = Transform(grid, self._R1_basis, derivs=1)
        Z1_transform = Transform(grid, self._Z1_basis, derivs=1)
        p_transform = Transform(grid, self._p_basis, derivs=0)
        i_transform = Transform(grid, self._i_basis, derivs=0)

        (
            con_basis,
            jacobian,
            cov_basis,
            toroidal_coords,
            polar_coords,
        ) = compute_contravariant_basis(
            self._Psi,
            self._R0_n,
            self._Z0_n,
            self._r_lmn,
            self._l_lmn,
            self._R1_mn,
            self._Z1_mn,
            self._p_l,
            self._i_l,
            R0_transform,
            Z0_transform,
            r_transform,
            l_transform,
            R1_transform,
            Z1_transform,
            p_transform,
            i_transform,
            self._zeta_ratio,
        )

        return con_basis

    def compute_jacobian(self, grid: Grid) -> dict:
        """Computes coordinate system jacobian.

        Parameters
        ----------
        grid : Grid
            Collocation grid containing the (rho, theta, zeta) coordinates of
            the nodes to evaluate at.

        Returns
        -------
        jacobian : dict
            dictionary of ndarray, shape(num_nodes,), of coordinate system jacobian.
            Keys are of the form 'g_x' meaning the x derivative of the coordinate
            system jacobian g.

        """
        R0_transform = Transform(grid, self._R0_basis, derivs=1)
        Z0_transform = Transform(grid, self._Z0_basis, derivs=1)
        r_transform = Transform(grid, self._r_basis, derivs=1)
        l_transform = Transform(grid, self._l_basis, derivs=0)
        R1_transform = Transform(grid, self._R1_basis, derivs=1)
        Z1_transform = Transform(grid, self._Z1_basis, derivs=1)
        p_transform = Transform(grid, self._p_basis, derivs=0)
        i_transform = Transform(grid, self._i_basis, derivs=0)

        (jacobian, cov_basis, toroidal_coords, polar_coords) = compute_jacobian(
            self._Psi,
            self._R0_n,
            self._Z0_n,
            self._r_lmn,
            self._l_lmn,
            self._R1_mn,
            self._Z1_mn,
            self._p_l,
            self._i_l,
            R0_transform,
            Z0_transform,
            r_transform,
            l_transform,
            R1_transform,
            Z1_transform,
            p_transform,
            i_transform,
            self._zeta_ratio,
        )

        return jacobian

    def compute_magnetic_field(self, grid: Grid) -> dict:
        """Computes magnetic field components.

        Parameters
        ----------
        grid : Grid
            Collocation grid containing the (rho, theta, zeta) coordinates of
            the nodes to evaluate at.

        Returns
        -------
        magnetic_field: dict
            dictionary of ndarray, shape(num_nodes,) of magnetic field components.
            Keys are of the form 'B_x_y' or 'B^x_y', meaning the covariant (B_x)
            or contravariant (B^x) component of the magnetic field, with the
            derivative wrt to y.

        """
        R0_transform = Transform(grid, self._R0_basis, derivs=1)
        Z0_transform = Transform(grid, self._Z0_basis, derivs=1)
        r_transform = Transform(grid, self._r_basis, derivs=2)
        l_transform = Transform(grid, self._l_basis, derivs=1)
        R1_transform = Transform(grid, self._R1_basis, derivs=1)
        Z1_transform = Transform(grid, self._Z1_basis, derivs=1)
        p_transform = Transform(grid, self._p_basis, derivs=0)
        i_transform = Transform(grid, self._i_basis, derivs=0)

        (
            magnetic_field,
            profiles,
            jacobian,
            cov_basis,
            toroidal_coords,
            polar_coords,
        ) = compute_magnetic_field_magnitude_axis(
            self._Psi,
            self._R0_n,
            self._Z0_n,
            self._r_lmn,
            self._l_lmn,
            self._R1_mn,
            self._Z1_mn,
            self._p_l,
            self._i_l,
            R0_transform,
            Z0_transform,
            r_transform,
            l_transform,
            R1_transform,
            Z1_transform,
            p_transform,
            i_transform,
            self._zeta_ratio,
        )

        return magnetic_field

    def compute_current_density(self, grid: Grid) -> dict:
        """Computes current density field components.

        Parameters
        ----------
        grid : Grid
            Collocation grid containing the (rho, theta, zeta) coordinates of
            the nodes to evaluate at.

        Returns
        -------
        current_density : dict
            dictionary of ndarray, shape(num_nodes,), of current density components.
            Keys are of the form 'J^x_y' meaning the contravariant (J^x)
            component of the current, with the derivative wrt to y.

        """
        R0_transform = Transform(grid, self._R0_basis, derivs=2)
        Z0_transform = Transform(grid, self._Z0_basis, derivs=2)
        r_transform = Transform(grid, self._r_basis, derivs=2)
        l_transform = Transform(grid, self._l_basis, derivs=2)
        R1_transform = Transform(grid, self._R1_basis, derivs=2)
        Z1_transform = Transform(grid, self._Z1_basis, derivs=2)
        p_transform = Transform(grid, self._p_basis, derivs=0)
        i_transform = Transform(grid, self._i_basis, derivs=1)

        (
            current_density,
            magnetic_field,
            profiles,
            jacobian,
            cov_basis,
            toroidal_coords,
            polar_coords,
        ) = compute_current_density(
            self._Psi,
            self._R0_n,
            self._Z0_n,
            self._r_lmn,
            self._l_lmn,
            self._R1_mn,
            self._Z1_mn,
            self._p_l,
            self._i_l,
            R0_transform,
            Z0_transform,
            r_transform,
            l_transform,
            R1_transform,
            Z1_transform,
            p_transform,
            i_transform,
            self._zeta_ratio,
        )

        return current_density

    def compute_force_error(self, grid: Grid) -> dict:
        """Computes force errors and magnitude.

        Parameters
        ----------
        grid : Grid
            Collocation grid containing the (rho, theta, zeta) coordinates of
            the nodes to evaluate at.

        Returns
        -------
        force_error : dict
            dictionary of ndarray, shape(num_nodes,), of force error components.
            Keys are of the form 'F_x' meaning the covariant (F_x) component of the
            force error.

        """
        R0_transform = Transform(grid, self._R0_basis, derivs=2)
        Z0_transform = Transform(grid, self._Z0_basis, derivs=2)
        r_transform = Transform(grid, self._r_basis, derivs=2)
        l_transform = Transform(grid, self._l_basis, derivs=2)
        R1_transform = Transform(grid, self._R1_basis, derivs=2)
        Z1_transform = Transform(grid, self._Z1_basis, derivs=2)
        p_transform = Transform(grid, self._p_basis, derivs=1)
        i_transform = Transform(grid, self._i_basis, derivs=1)

        (
            force_error,
            current_density,
            magnetic_field,
            profiles,
            con_basis,
            jacobian,
            cov_basis,
            toroidal_coords,
            polar_coords,
        ) = compute_force_error_magnitude(
            self._Psi,
            self._R0_n,
            self._Z0_n,
            self._r_lmn,
            self._l_lmn,
            self._R1_mn,
            self._Z1_mn,
            self._p_l,
            self._i_l,
            R0_transform,
            Z0_transform,
            r_transform,
            l_transform,
            R1_transform,
            Z1_transform,
            p_transform,
            i_transform,
            self._zeta_ratio,
        )

        return force_error


# these functions are needed to format the input arrays


def format_profiles(profiles, p_basis: PowerSeries, i_basis: PowerSeries):
    """Formats profile input arrays

    Parameters
    ----------
    profiles : ndarray, shape(Nbdry,3)
        array of fourier coeffs [l, p, i]
    p_basis : PowerSeries
        spectral basis for p_l coefficients
    i_basis : PowerSeries
        spectral basis for i_l coefficients

    Returns
    -------
    p_l : ndarray
        spectral coefficients for pressure profile
    i_l : ndarray
        spectral coefficients for rotational transform profile

    """
    p_l = np.zeros((p_basis.num_modes,))
    i_l = np.zeros((i_basis.num_modes,))

    for l, p, i in profiles:
        idx_p = np.where(p_basis.modes[:, 0] == int(l))[0]
        idx_i = np.where(i_basis.modes[:, 0] == int(l))[0]
        p_l = put(p_l, idx_p, p)
        i_l = put(i_l, idx_i, i)

    return p_l, i_l


def format_boundary(
    boundary,
    R1_basis: DoubleFourierSeries,
    Z1_basis: DoubleFourierSeries,
    mode: str = "spectral",
):
    """Formats boundary arrays and converts between real and fourier representations

    Parameters
    ----------
    boundary : ndarray, shape(Nbdry,4)
        array of fourier coeffs [m, n, R1, Z1]
        or array of real space coordinates, [theta, phi, R, Z]
    R1_basis : DoubleFourierSeries
        spectral basis for R1_mn coefficients
    Z1_basis : DoubleFourierSeries
        spectral basis for Z1_mn coefficients
    mode : str
        one of 'real', 'spectral'. Whether bdry is specified in real or spectral space.

    Returns
    -------
    R1_mn : ndarray
        spectral coefficients for R boundary
    Z1_mn : ndarray
        spectral coefficients for Z boundary

    """
    if mode == "real":
        theta = boundary[:, 0]
        phi = boundary[:, 1]
        rho = np.ones_like(theta)

        nodes = np.array([rho, theta, phi]).T
        grid = Grid(nodes)
        R1_tform = Transform(grid, R1_basis)
        Z1_tform = Transform(grid, Z1_basis)

        # fit real data to spectral coefficients
        R1_mn = R1_tform.fit(boundary[:, 2])
        Z1_mn = Z1_tform.fit(boundary[:, 3])

    else:
        R1_mn = np.zeros((R1_basis.num_modes,))
        Z1_mn = np.zeros((Z1_basis.num_modes,))

        for m, n, R1, Z1 in boundary:
            idx_R = np.where(
                np.logical_and(
                    R1_basis.modes[:, 1] == int(m), R1_basis.modes[:, 2] == int(n)
                )
            )[0]
            idx_Z = np.where(
                np.logical_and(
                    Z1_basis.modes[:, 1] == int(m), Z1_basis.modes[:, 2] == int(n)
                )
            )[0]
            R1_mn = put(R1_mn, idx_R, R1)
            Z1_mn = put(Z1_mn, idx_Z, Z1)

    return R1_mn, Z1_mn


def format_axis(axis, R0_basis: FourierSeries, Z0_basis: FourierSeries):
    """Formats magnetic axis input arrays

    Parameters
    ----------
    axis : ndarray, shape(Naxis,3)
        array of fourier coeffs [n, R_n, Z_n]
    R0_basis : FourierSeries
        spectral basis for R0_n coefficients
    Z0_basis : PowerSeries
        spectral basis for Z0_n coefficients

    Returns
    -------
    R0_n : ndarray
        spectral coefficients for magnetic axis R coordinate
    Z0_n : ndarray
        spectral coefficients for magnetic axis Z coordinate

    """
    R0_n = np.zeros((R0_basis.num_modes,))
    Z0_n = np.zeros((Z0_basis.num_modes,))

    for n, R0, Z0 in axis:
        idx_R0 = np.where(R0_basis.modes[:, 2] == int(n))[0]
        idx_Z0 = np.where(Z0_basis.modes[:, 2] == int(n))[0]
        R0_n = put(R0_n, idx_R0, R0)
        Z0_n = put(Z0_n, idx_Z0, Z0)

    return R0_n, Z0_n
