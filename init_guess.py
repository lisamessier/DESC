import numpy as np
from backend import put, sign

def get_initial_guess_scale_bdry(axis,bdry,zern_idx,NFP,mode='spectral',rcond=1e-6):
    """Generate initial guess by scaling boundary shape
    
    Args:
        bdryR (ndarray, shape(N_bdry_vals,)): R coordinates of boundary, or spectral coefficients of boundary R shape
        bdryZ (ndarray, shape(N_bdry_vals,)): Z coordinates of boundary, or spectral coefficients of boundary Z shape
        poloidal (ndarray, shape(N_bdry_vals,)): poloidal coordinates where bdryR,bdryZ are given, or poloidal mode numbers
        toroidal (ndarray, shape(N_bdry_vals,)): toroidal coordinates where bdryR,bdryZ are given, or toroidal mode numbers
        zern_idx (ndarray, shape(Nc,3)): indices for spectral basis, ie an array of [l,m,n] for each spectral coefficient
        NFP (int): number of field periods
        mode (str): one of 'real', 'spectral' - which format is being used for bdryR,bdryZ,poloidal,toroidal
        nr (int): number of radial points to use when generating guess
        rcond (float): relative limit on singular values for least squares fit to Zernike basis
    Returns:
        cR (ndarray, shape(N_coeffs,)): Fourier-Zernike coefficients for R, following indexing given in zern_idx
        cZ (ndarray, shape(N_coeffs,)): Fourier-Zernike coefficients for Z, following indexing given in zern_idx
    """
    if mode == 'spectral':
        dimZern = np.shape(zern_idx)[0]
        cR = np.zeros((dimZern,))
        cZ = np.zeros((dimZern,))
        
        for m,n,bR,bZ in bdry:
            sgn = 1
            if sign(n) < 0:
                sgn = -1
            if m == 0:
                idx = np.where(axis[:,0]==n)
                if idx[0].size == 0:
                    aR = bR
                    aZ = bZ
                else:
                    aR = axis[idx,1]
                    aZ = axis[idx,2]
                cR = put(cR, np.where(np.logical_and.reduce((zern_idx[:,0]==0, zern_idx[:,1]==0, zern_idx[:,2]==n)))[0], sgn*(bR+aR)/2)
                cZ = put(cZ, np.where(np.logical_and.reduce((zern_idx[:,0]==0, zern_idx[:,1]==0, zern_idx[:,2]==n)))[0], sgn*(bZ+aZ)/2)
                cR = put(cR, np.where(np.logical_and.reduce((zern_idx[:,0]==2, zern_idx[:,1]==0, zern_idx[:,2]==n)))[0], sgn*(bR-aR)/2)
                cZ = put(cZ, np.where(np.logical_and.reduce((zern_idx[:,0]==2, zern_idx[:,1]==0, zern_idx[:,2]==n)))[0], sgn*(bZ-aZ)/2)
            else:
                cR = put(cR, np.where(np.logical_and.reduce((zern_idx[:,0]==np.absolute(m), zern_idx[:,1]==m, zern_idx[:,2]==n)))[0], sgn*bR)
                cZ = put(cZ, np.where(np.logical_and.reduce((zern_idx[:,0]==np.absolute(m), zern_idx[:,1]==m, zern_idx[:,2]==n)))[0], sgn*bZ)
    
    else:
        print("I can't compute the initial guess in real space!")
    
    return cR, cZ