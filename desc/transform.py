import numpy as np
from itertools import permutations, combinations_with_replacement
from termcolor import colored
import warnings
from desc.backend import jnp
from desc.utils import equals, issorted, isalmostequal, islinspaced
from desc.grid import Grid
from desc.basis import Basis
from desc.io import IOAble


class Transform(IOAble):
    """Transform

    Attributes
    ----------
    grid : Grid
        DESCRIPTION
    basis : Basis
        DESCRIPTION
    rcond : float
        relative cutoff for singular values in least squares fit
    derivatives : ndarray
        combinations of derivatives needed
        Each row is one set, columns represent the order of derivatives
        for [rho, theta, zeta]
    matrices : ndarray
        DESCRIPTION
    pinv : ndarray
        DESCRIPTION

    """

    _io_attrs_ = ["_grid", "_basis", "_derives", "_matrices"]

    def __init__(
        self,
        grid: Grid = None,
        basis: Basis = None,
        derivs=0,
        rcond=1e-6,
        build=True,
        build_pinv=False,
        method="fft",
        load_from=None,
        file_format=None,
        obj_lib=None,
    ) -> None:
        """Initializes a Transform

         Parameters
         ----------
         grid : Grid
             DESCRIPTION
         basis : Basis
             DESCRIPTION
         derivs : int or array-like
             order of derivatives needed, if an int (Default = 0)
             OR
             array of derivative orders, shape (N,3)
             [dr, dt, dz]
        rcond : float
             relative cutoff for singular values in least squares fit
        build : bool
            whether to precompute the transforms now or do it later
        build_pinv : bool
            whether to precompute the pseudoinverse now or do it later
        method : str
            one of 'direct', or 'fft'. 'direct' uses full matrices and can handle arbitrary
            node patterns and spectral basis. 'fft' uses fast fourier transforms in the zeta direction,
            and so must have equally spaced toroidal nodes, and the same node pattern on each zeta plane

         Returns
         -------
         None

        """
        self._file_format_ = file_format

        if load_from is None:
            self._grid = grid
            self._basis = basis
            self._rcond = rcond
            self._built = False
            self._built_pinv = False
            self._matrices = {
                i: {j: {k: {} for k in range(4)} for j in range(4)} for i in range(4)
            }
            self._derivatives = self._get_derivatives(derivs)

            self._sort_derivatives()
            if method in ["direct", "fft"]:
                self.method = method
            else:
                raise ValueError(
                    colored("Unknown Transform method '{}'".format(method), "red")
                )
            if self.method == "fft":
                self._check_inputs_fft(self._grid, self._basis)
            if build:
                self.build()
            if build_pinv:
                self.build_pinv()
        else:
            self._init_from_file_(
                load_from=load_from, file_format=file_format, obj_lib=obj_lib
            )

    def __eq__(self, other) -> bool:
        """Overloads the == operator

        Parameters
        ----------
        other : Transform
            another Transform object to compare to

        Returns
        -------
        bool
            True if other is a Transform with the same attributes as self
            False otherwise

        """
        if self.__class__ != other.__class__:
            return False
        return equals(self.__dict__, other.__dict__)

    def _get_derivatives(self, derivs):
        """Get array of derivatives needed for calculating objective function

        Parameters
        ----------
        derivs : int or string
            order of derivatives needed, if an int (Default = 0)
            OR
            type of calculation being performed, if a string
            ``'force'``: all of the derivatives needed to calculate an
            equilibrium from the force balance equations
            ``'qs'``: all of the derivatives needed to calculate quasi-
            symmetry from the triple-product equation

        Returns
        -------
        derivatives : ndarray
            combinations of derivatives needed
            Each row is one set, columns represent the order of derivatives
            for [rho, theta, zeta]

        """
        if isinstance(derivs, int) and derivs >= 0:
            derivatives = np.array([[]])
            combos = combinations_with_replacement(range(derivs + 1), 3)
            for combo in list(combos):
                perms = set(permutations(combo))
                for perm in list(perms):
                    if derivatives.shape[1] == 3:
                        derivatives = np.vstack([derivatives, np.array(perm)])
                    else:
                        derivatives = np.array([perm])

        elif np.atleast_1d(derivs).ndim == 1 and len(derivs) == 3:
            derivatives = np.asarray(derivs).reshape((1, 3))
        elif np.atleast_2d(derivs).ndim == 2 and np.atleast_2d(derivs).shape[1] == 3:
            derivatives = np.atleast_2d(derivs)
        else:
            raise NotImplementedError(
                colored(
                    "derivs should be array-like with 3 columns, or a non-negative int",
                    "red",
                )
            )

        return derivatives

    def _sort_derivatives(self) -> None:
        """Sorts derivatives

        Returns
        -------
        None

        """
        sort_idx = np.lexsort(
            (self._derivatives[:, 0], self._derivatives[:, 1], self._derivatives[:, 2])
        )
        self._derivatives = self._derivatives[sort_idx]

    def _check_inputs_fft(self, grid, basis):
        """helper function to check that inputs are formatted correctly for fft method"""
        zeta_vals, zeta_cts = np.unique(grid.nodes[:, 2], return_counts=True)

        if not issorted(grid.nodes[:, 2]):
            warnings.warn(
                colored(
                    "fft method requires nodes to be sorted by toroidal angle in ascending order, falling back to direct method",
                    "yellow",
                )
            )
            self.method = "direct"
            return

        if not isalmostequal(zeta_cts):
            warnings.warn(
                colored(
                    "fft method requires the same number of nodes on each zeta plane, falling back to direct method",
                    "yellow",
                )
            )
            self.method = "direct"
            return

        if len(zeta_vals) > 1:
            if not islinspaced(zeta_vals):
                warnings.warn(
                    colored(
                        "fft method requires nodes to be equally spaced in zeta, falling back to direct method",
                        "yellow",
                    )
                )
                self.method = "direct"
                return

            if not isalmostequal(
                grid.nodes[:, :2].T.reshape((2, zeta_cts[0], -1), order="F")
            ):
                warnings.warn(
                    colored(
                        "fft method requires that node pattern is the same on each zeta plane, falling back to direct method",
                        "yellow",
                    )
                )
                self.method = "direct"
                return

            if not abs((zeta_vals[-1] + zeta_vals[1]) * grid.NFP - 2 * np.pi) < 1e-14:
                warnings.warn(
                    colored(
                        "fft method requires that nodes complete 1 full field period, falling back to direct method",
                        "yellow",
                    )
                )
                self.method = "direct"
                return

        id2 = np.lexsort((basis.modes[:, 1], basis.modes[:, 0], basis.modes[:, 2]))
        if not issorted(id2):
            warnings.warn(
                colored(
                    "fft method requires zernike indices to be sorted by toroidal mode number, falling back to direct method",
                    "yellow",
                )
            )
            self.method = "direct"
            return

        n_vals, n_cts = np.unique(basis.modes[:, 2], return_counts=True)
        if not isalmostequal(n_cts):
            warnings.warn(
                colored(
                    "fft method requires that there are the same number of poloidal modes for each toroidal mode, falling back to direct method",
                    "yellow",
                )
            )
            self.method = "direct"
            return

        if len(n_vals) > 1:
            if not islinspaced(n_vals):
                warnings.warn(
                    colored(
                        "fft method requires the toroidal modes are equally spaced in n, falling back to direct method",
                        "yellow",
                    )
                )
                self.method = "direct"
                return

            if not isalmostequal(
                basis.modes[:, 0].reshape((n_cts[0], -1), order="F")
            ) or not isalmostequal(
                basis.modes[:, 1].reshape((n_cts[0], -1), order="F")
            ):
                warnings.warn(
                    colored(
                        "fft method requires that the poloidal modes are the same for each toroidal mode, falling back to direct method",
                        "yellow",
                    )
                )
                self.method = "direct"
                return

        if not len(zeta_vals) >= len(n_vals):
            warnings.warn(
                colored(
                    "fft method can not undersample in zeta, num_zeta_vals={}, num_n_vals={}, falling back to direct method".format(
                        len(zeta_vals), len(n_vals)
                    ),
                    "yellow",
                )
            )
            self.method = "direct"
            return

        self.method = "fft"
        self.numFour = len(n_vals)  # number of toroidal modes
        self.numFournodes = len(zeta_vals)  # number of toroidal nodes
        self.zeta_pad = (self.numFournodes - self.numFour) // 2
        self.pol_zern_idx = basis.modes[: basis.num_modes // self.numFour, :2]
        pol_nodes = np.hstack(
            [
                grid.nodes[:, :2][: grid.num_nodes // self.numFournodes],
                np.zeros((grid.num_nodes // self.numFournodes, 1)),
            ]
        )
        self.pol_grid = Grid(pol_nodes)

    def build(self) -> None:
        """Builds the transform matrices for each derivative order"""
        if self._built:
            return
        if self.method == "direct":
            for d in self._derivatives:
                self._matrices[d[0]][d[1]][d[2]] = self._basis.evaluate(
                    self._grid.nodes, d
                )

        elif self.method == "fft":
            temp_d = np.hstack(
                [self.derivatives[:, :2], np.zeros((len(self.derivatives), 1))]
            )
            n0 = np.argwhere(self.basis.modes[:, 2] == 0).flatten()
            for d in temp_d:
                self.matrices[d[0]][d[1]][d[2]] = self._basis.evaluate(
                    self.pol_grid.nodes, d
                )[:, n0]

        self._built = True

    def build_pinv(self):
        """build pseudoinverse for fitting"""
        if self._built_pinv:
            return
        A = self._basis.evaluate(self._grid.nodes, np.array([0, 0, 0]))
        if A.size:
            self._pinv = np.linalg.pinv(A, rcond=self._rcond)
        else:
            self._pinv = np.zeros_like(A.T)
        self._built_pinv = True

    def transform(self, c, dr=0, dt=0, dz=0):
        """Transform from spectral domain to physical

        Parameters
        ----------
        c : ndarray, shape(N_coeffs,)
            spectral coefficients, indexed as (lm,n) flattened in row major order
        dr : int
            order of radial derivative
        dt : int
            order of poloidal derivative
        dz : int
            order of toroidal derivative

        Returns
        -------
        x : ndarray, shape(N_nodes,)
            array of values of function at node locations

        """
        if not self._built:
            raise AttributeError(
                "Transform must be built with Transform.build() before it can be used"
            )

        if self.method == "direct":
            A = self._matrices[dr][dt][dz]
            if type(A) is dict:
                raise ValueError(
                    colored("Derivative orders are out of initialized bounds", "red")
                )
            if self.basis.num_modes != c.size:
                raise ValueError(
                    colored(
                        "Coefficients dimension ({}) is incompatible with the number of basis modes({})".format(
                            c.size, self.basis.num_modes
                        ),
                        "red",
                    )
                )
            return jnp.matmul(A, c)

        elif self.method == "fft":
            A = self._matrices[dr][dt][0]
            if type(A) is dict:
                raise ValueError(
                    colored("Derivative orders are out of initialized bounds", "red")
                )
            if self.basis.num_modes != c.size:
                raise ValueError(
                    colored(
                        "Coefficients dimension ({}) is incompatible with the number of basis modes({})".format(
                            c.size, self.basis.num_modes
                        ),
                        "red",
                    )
                )

            c_pad = jnp.pad(
                c.reshape((-1, self.numFour), order="F"),
                ((0, 0), (self.zeta_pad, self.zeta_pad)),
                mode="constant",
            )
            dk = self.basis.NFP * jnp.arange(
                -(self.numFournodes // 2), (self.numFournodes // 2) + 1
            ).reshape((1, -1))
            c_pad = c_pad[:, :: (-1) ** dz] * dk ** dz * (-1) ** (dz > 1)
            cfft = self._four2phys(c_pad)
            return jnp.matmul(A, cfft).flatten(order="F")

    def _four2phys(self, c):
        """helper function to do ffts"""
        K, L = c.shape
        N = (L - 1) // 2
        # pad with negative wavenumbers
        a = c[:, N:]
        b = c[:, :N][:, ::-1]
        a = jnp.hstack([a[:, 0][:, jnp.newaxis], a[:, 1:] / 2, a[:, 1:][:, ::-1] / 2])
        b = jnp.hstack([jnp.zeros((K, 1)), -b[:, 0:] / 2, b[:, ::-1] / 2])
        # inverse Fourier transform
        a = a * L
        b = b * L
        c = a + 1j * b
        x = jnp.real(jnp.fft.ifft(c, None, 1))
        return x

    def fit(self, x):
        """Transform from physical domain to spectral using least squares fit

        Parameters
        ----------
        x : ndarray, shape(N_nodes,)
            values in real space at coordinates specified by self.grid

        Returns
        -------
        c : ndarray, shape(N_coeffs,)
            spectral coefficients in self.basis

        """
        if not self._built_pinv:
            raise AttributeError(
                "inverse transform must be built with Transform.build_pinv() before it can be used"
            )
        return jnp.matmul(self._pinv, x)

    def change_resolution(
        self,
        grid: Grid = None,
        basis: Basis = None,
        build: bool = True,
        build_pinv: bool = False,
    ) -> None:
        """Re-builds the matrices with a new grid and basise

        Parameters
        ----------
        grid : Grid, optional
            DESCRIPTION
        basis : Basis, optional
            DESCRIPTION
        build : bool
            whether to recompute matrices now or wait until requested

        Returns
        -------
        None

        """
        if grid is None:
            grid = self._grid
        if basis is None:
            basis = self._basis

        if self._grid != grid:
            self._grid = grid
            self._built = False
            self._built_pinv = False
        if self._basis != basis:
            self._basis = basis
            self._built = False
            self._built_pinv = False
        if self.method == "fft":
            self._check_inputs_fft(self._grid, self._basis)
        if build:
            self.build()
        if build_pinv:
            self.build_pinv()

    @property
    def grid(self):
        return self._grid

    @grid.setter
    def grid(self, grid: Grid) -> None:
        """Changes the grid and updates the matrices accordingly

        Parameters
        ----------
        grid : Grid
            DESCRIPTION

        Returns
        -------
        None

        """
        if self._grid != grid:
            self._grid = grid
            if self.method == "fft":
                self._check_inputs_fft(self._grid, self._basis)
            if self._built:
                self._built = False
                self.build()
            if self._built_pinv:
                self._built_pinv = False
                self.build_pinv()

    @property
    def basis(self):
        return self._basis

    @basis.setter
    def basis(self, basis: Basis) -> None:
        """Changes the basis and updates the matrices accordingly

        Parameters
        ----------
        basis : Basis
            DESCRIPTION

        Returns
        -------
        None

        """
        if self._basis != basis:
            self._basis = basis
            if self.method == "fft":
                self._check_inputs_fft(self._grid, self._basis)
            if self._built:
                self._built = False
                self.build()
            if self._built_pinv:
                self._built_pinv = False
                self.build_pinv()

    @property
    def derivatives(self):
        return self._derivatives

    def change_derivatives(self, derivs, build=True) -> None:
        """Changes the order and updates the matrices accordingly

        Doesn't delete any old orders, only adds new ones if not already there

        Parameters
        ----------
         derivs : int or array-like
             order of derivatives needed, if an int (Default = 0)
             OR
             array of derivative orders, shape (N,3)
             [dr, dt, dz]
        build : bool
            whether to build transforms immediately or wait

        Returns
        -------
        None

        """
        new_derivatives = self._get_derivatives(derivs)
        new_not_in_old = (new_derivatives[:, None] == self.derivatives).all(-1).any(-1)
        derivs_to_add = new_derivatives[~new_not_in_old]
        self._derivatives = np.vstack([self.derivatives, derivs_to_add])
        self._sort_derivatives()

        if build:
            # we don't update self._built here because if it was built before it still is
            # but if it wasn't it still might have unbuilt matrices
            for d in derivs_to_add:
                self._matrices[d[0]][d[1]][d[2]] = self._basis.evaluate(
                    self._grid.nodes, d
                )
        elif len(derivs_to_add):
            # if we actually added derivatives and didn't build them, then its not built
            self._built = False

    @property
    def matrices(self):
        return self._matrices

    @property
    def num_nodes(self):
        return self._grid.num_nodes

    @property
    def num_modes(self):
        return self._basis.num_modes

    @property
    def built(self):
        return self._built

    @property
    def built_pinv(self):
        return self._built_pinv
