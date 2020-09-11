import matplotlib.pyplot as plt
import numpy as np
from zernike import ZernikeTransform, eval_double_fourier
from backend import presfun, get_needed_derivatives, iotafun, presfun, dot, rms, put, unpack_x
from input_output import vmec_interpolate
from field_components import compute_coordinate_derivatives, compute_covariant_basis, compute_contravariant_basis, compute_jacobian
from field_components import compute_B_field, compute_J_field, compute_F_magnitude

colorblind_colors = [(0.0000, 0.4500, 0.7000), # blue
                     (0.8359, 0.3682, 0.0000), # vermillion
                     (0.0000, 0.6000, 0.5000), # bluish green
                     (0.9500, 0.9000, 0.2500), # yellow
                     (0.3500, 0.7000, 0.9000), # sky blue
                     (0.8000, 0.6000, 0.7000), # reddish purple
                     (0.9000, 0.6000, 0.0000)] # orange
dashes = [(1.0, 0.0, 0.0, 0.0, 0.0, 0.0), # solid
          (3.7, 1.6, 0.0, 0.0, 0.0, 0.0), # dashed
          (1.0, 1.6, 0.0, 0.0, 0.0, 0.0), # dotted
          (6.4, 1.6, 1.0, 1.6, 0.0, 0.0), # dot dash
          (3.0, 1.6, 1.0, 1.6, 1.0, 1.6), # dot dot dash
          (6.0, 4.0, 0.0, 0.0, 0.0, 0.0), # long dash
          (1.0, 1.6, 3.0, 1.6, 3.0, 1.6)] # dash dash dot
import matplotlib
from matplotlib import rcParams, cycler
matplotlib.rcdefaults()
rcParams['font.family'] = 'DejaVu Serif'
rcParams['mathtext.fontset'] = 'cm'
rcParams['font.size'] = 10
rcParams['figure.facecolor'] = (1,1,1,1)
rcParams['figure.figsize'] = (6,4)
rcParams['figure.dpi'] = 141
rcParams['axes.spines.top'] = False
rcParams['axes.spines.right'] = False
rcParams['axes.labelsize'] =  'small'
rcParams['axes.titlesize'] = 'medium'
rcParams['lines.linewidth'] = 1
rcParams['lines.solid_capstyle'] = 'round'
rcParams['lines.dash_capstyle'] = 'round'
rcParams['lines.dash_joinstyle'] = 'round'
rcParams['xtick.labelsize'] = 'x-small'
rcParams['ytick.labelsize'] = 'x-small'
# rcParams['text.usetex']=True
color_cycle = cycler(color=colorblind_colors)
dash_cycle = cycler(dashes=dashes)
rcParams['axes.prop_cycle'] =  color_cycle



def print_coeffs(cR,cZ,cL,zern_idx,lambda_idx):
    """prints coeffs to the terminal"""
    
    print('Fourier-Zernike coefficients:')
    for k, lmn in enumerate(zern_idx):
        print('l: {:3d}, m: {:3d}, n: {:3d}, cR: {:16.8e}, cZ: {:16.8e}'.format(lmn[0],lmn[1],lmn[2],cR[k],cZ[k]))

    print('Lambda coefficients')
    for k, mn in enumerate(lambda_idx):
        print('m: {:3d}, n: {:3d}, cL: {:16.8e}'.format(mn[0],mn[1],cL[k]))
        

def plot_coord_surfaces(cR,cZ,zern_idx,NFP,nr=10,nt=12,ax=None,bdryR=None,bdryZ=None, **kwargs):
    """Plots solutions (currently only zeta=0 plane)

    Args:
        cR (ndarray, shape(N_coeffs,)): spectral coefficients of R
        cZ (ndarray, shape(N_coeffs,)): spectral coefficients of Z
        zern_idx (ndarray, shape(Nc,3)): indices for R,Z spectral basis, ie an array of [l,m,n] for each spectral coefficient
        NFP (int): number of field periods
        nr (int): number of flux surfaces to show
        nt (int): number of theta lines to show
        ax (matplotlib.axes): axes to plot on. If None, a new figure is created.
    
    Returns:
        ax (matplotlib.axes): handle to axes used for the plot
    """
    
    Nr = 100
    Nt = 361
    rstep = Nr//nr
    tstep = Nt//nt
    zeta = kwargs.get('zeta',0)
    r = np.linspace(0,1,Nr)
    t = np.linspace(0,2*np.pi,Nt)
    r,t = np.meshgrid(r,t,indexing='ij')
    r = r.flatten()
    t = t.flatten()
    z = zeta*np.ones_like(r)
    zernt = ZernikeTransform([r,t,z],zern_idx,NFP)

    R = zernt.transform(cR,0,0,0).reshape((Nr,Nt))
    Z = zernt.transform(cZ,0,0,0).reshape((Nr,Nt))

    if ax is None:
        fig, ax = plt.subplots()
    # plot desired bdry
    if (bdryR is not None) and (bdryZ is not None):
        ax.plot(bdryR,bdryZ,color=colorblind_colors[1],lw=2,alpha=.5,dashes=(None,None))
    # plot r contours
    ax.plot(R.T[:,::rstep],Z.T[:,::rstep],color=colorblind_colors[0],lw=.5, dashes=(None,None))
    # plot actual bdry
    ax.plot(R.T[:,-1],Z.T[:,-1],color=colorblind_colors[0],lw=.5, dashes=(None,None))
    # plot theta contours
    ax.plot(R[:,::tstep],Z[:,::tstep],color=colorblind_colors[0],lw=.5,dashes=dashes[2]);
    ax.axis('equal')
    ax.set_xlabel('$R$')
    ax.set_ylabel('$Z$')
    ax.set_title(kwargs.get('title'))
    return ax


def plot_coeffs(cR,cZ,cL,zern_idx,lambda_idx,cR_init=None,cZ_init=None,cL_init=None, **kwargs):
    """Scatter plots of zernike and lambda coefficients, before and after solving
    
    Args:
        cR (ndarray, shape(N_coeffs,)): spectral coefficients of R
        cZ (ndarray, shape(N_coeffs,)): spectral coefficients of Z
        cL (ndarray, shape(2M+1)*(2N+1)): spectral coefficients of lambda
        zern_idx (ndarray, shape(N_coeffs,3)): array of (l,m,n) indices for each spectral R,Z coeff
        lambda_idx (ndarray, shape(Nlambda,2)): indices for lambda spectral basis, ie an array of [m,n] for each spectral coefficient        
        cR_init (ndarray, shape(N_coeffs,)): initial spectral coefficients of R
        cZ_init (ndarray, shape(N_coeffs,)): initial spectral coefficients of Z
        cL_init (ndarray, shape(2M+1)*(2N+1)): initial spectral coefficients of lambda
        
    Returns:
        fig (matplotlib.figure): handle to the figure
        ax (ndarray of matplotlib.axes): handle to axes
    """
    nRZ = len(cR)
    nL = len(cL)
    fig, ax = plt.subplots(1,3, figsize=(cR.size//5,6))
    ax = ax.flatten()

    ax[0].scatter(cR,np.arange(nRZ),s=2, label='Final')
    if cR_init is not None:
        ax[0].scatter(cR_init,np.arange(nRZ),s=2, label='Init')
    ax[0].set_yticks(np.arange(nRZ))
    ax[0].set_yticklabels([str(i) for i in zern_idx]);
    ax[0].set_xlabel('$R$')
    ax[0].set_ylabel('[l,m,n]')
    ax[0].axvline(0,c='k',lw=.25)
    ax[0].legend(loc='upper right')

    ax[1].scatter(cZ,np.arange(nRZ),s=2, label='Final')
    if cZ_init is not None:
        ax[1].scatter(cZ_init,np.arange(nRZ),s=2, label='Init')
    ax[1].set_yticks(np.arange(nRZ))
    ax[1].set_yticklabels([str(i) for i in zern_idx]);
    ax[1].set_xlabel('$Z$')
    ax[1].set_ylabel('[l,m,n]')
    ax[1].axvline(0,c='k',lw=.25)
    ax[1].legend()

    ax[2].scatter(cL,np.arange(nL),s=2, label='Final')
    if cL_init is not None:
        ax[2].scatter(cL_init,np.arange(nL),s=2, label='Init')
    ax[2].set_yticks(np.arange(nL))
    ax[2].set_yticklabels([str(i) for i in lambda_idx]);
    ax[2].set_xlabel('$\lambda$')
    ax[2].set_ylabel('[m,n]')
    ax[2].axvline(0,c='k',lw=.25)
    ax[2].legend()

    plt.subplots_adjust(wspace=.5)

    return fig, ax


def plot_fb_err(cR,cZ,cP,cI,zern_idx,NFP,Psi_total,
                domain='real',normalize='local',log=True,cmap='plasma',**kwargs):
    """Plots force balance error
    
    Args:
        cR (ndarray, shape(N_coeffs,)): spectral coefficients of R
        cZ (ndarray, shape(N_coeffs,)): spectral coefficients of Z
        cP (array-like): coefficients to pass to pressure function
        cI (array-like): coefficients to pass to rotational transform function
        zern_idx (ndarray, shape(N_coeffs,3)): array of (l,m,n) indices for each spectral R,Z coeff
        NFP (int): number of field periods
        Psi_total (float): total toroidal flux in the plasma
        domain (str): one of 'real', 'sfl'. What basis to use for plotting, 
            real (R,Z) coordinates or straight field line (rho,vartheta)
        normalize (str, bool): Whether and how to normalize values
            None, False - no normalization, values plotted are force error in Newtons/m^3
            'local' - normalize by local pressure gradient
            'global' - normalize by pressure gradient at rho=0.5
            True - same as 'global'
        log (bool): plot logarithm of error or absolute value
        cmap (str,matplotlib.colors.Colormap): colormap to use
    
    Returns:
        Nothing, makes plot
    """
    
    if np.max(zern_idx[:,2])==0:
        Nz = 1
        rows = 1
    else:
        Nz = 6
        rows = 2
    
    Nr = kwargs.get('Nr',100)
    Nv = kwargs.get('Nv',100)
    Nlevels = kwargs.get('Nlevels',100)
    
    r = np.linspace(0,1,Nr)
    v = np.linspace(0,2*np.pi,Nv)
    z = np.linspace(0,2*np.pi/NFP,Nz)
    rr,vv,zz = np.meshgrid(r,v,z,indexing='ij')
    rr = rr.flatten()
    vv = vv.flatten()
    zz = zz.flatten()
    nodes = [rr,vv,zz]
    derivatives = get_needed_derivatives('all')
    zernt = ZernikeTransform(nodes,zern_idx,NFP,derivatives)
    
    # compute fields components
    coord_der = compute_coordinate_derivatives(cR,cZ,zernt)
    cov_basis = compute_covariant_basis(coord_der)
    jacobian  = compute_jacobian(coord_der,cov_basis)
    con_basis = compute_contravariant_basis(coord_der,cov_basis,jacobian,nodes)
    B_field   = compute_B_field(cov_basis,jacobian,cI,Psi_total,nodes)
    J_field   = compute_J_field(coord_der,cov_basis,jacobian,B_field,cI,Psi_total,nodes)
    F_mag,p_mag = compute_F_magnitude(coord_der,cov_basis,con_basis,jacobian,B_field,J_field,cP,cI,Psi_total,nodes)
    
    if domain == 'real':
        xlabel = r'R'
        ylabel = r'Z'
        R = zernt.transform(cR,0,0,0).reshape((Nr,Nv,Nz))
        Z = zernt.transform(cZ,0,0,0).reshape((Nr,Nv,Nz))
    elif domain == 'sfl':
        xlabel = r'$\vartheta$'
        ylabel = r'$\rho$'
        R = vv.reshape((Nr,Nv,Nz))
        Z = rr.reshape((Nr,Nv,Nz))
    else:
        raise ValueError("domain must be either 'real' or 'sfl'")
    
    if normalize == 'local':
        label = r'||F||/$\nabla$p'
        norm_errF = F_mag / p_mag
    elif normalize == 'global':
        label = r'||F||/$\nabla$p($\rho$=0.5)'
        halfn = np.where(rr == r[Nr//2])[0][0]
        norm_errF = F_mag / p_mag[halfn]
    else:
        label = r'||F||'
        norm_errF = F_mag
    
    if log:
        label = r'$\mathregular{log}_{10}$('+label+')'
        norm_errF = np.log10(norm_errF)
    
    norm_errF = norm_errF.reshape((Nr,Nv,Nz))
    
    plt.figure()
    for k in range(Nz):
        ax = plt.subplot(rows,Nz/rows,k+1)
        cf = ax.contourf(R[:,:,k],Z[:,:,k],norm_errF[:,:,k],cmap=cmap,extend='both',levels=Nlevels)
        if domain == 'real':
            ax.axis('equal')
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        cbar = plt.colorbar(cf)
        if k == 0:
            cbar.ax.set_ylabel(label)
    plt.show()
    


def plot_accel_err(cR,cZ,zernt,zern_idx,NFP,presfun_params,iotafun_params,Psi_total,domain='real',log=False,cmap='plasma'):
    """Plots acceleration error
    
    Args:
        cR (ndarray, shape(N_coeffs,)): spectral coefficients of R
        cZ (ndarray, shape(N_coeffs,)): spectral coefficients of Z
        cL (ndarray, shape(2M+1)*(2N+1)): spectral coefficients of lambda
        zern_idx (ndarray, shape(N_coeffs,3)): array of (l,m,n) indices for each spectral R,Z coeff
        lambda_idx (ndarray, shape(Nlambda,2)): indices for lambda spectral basis, ie an array of [m,n] for each spectral coefficient        
        NFP (int): number of field periods
        iotafun_params (array-like): paramters to pass to rotational transform function
        presfun_params (array-like): parameters to pass to pressure function
        Psi_total (float): total toroidal flux in the plasma
        domain (str): one of 'real', 'sfl'. What basis to use for plotting, 
            real (R,Z) coordinates or straight field line (rho,vartheta)
        normalize (str, bool): Whether and how to normalize values
            None, False - no normalization, values plotted are force error in Newtons/m^3
            'local' - normalize by local pressure gradient
            'global' - normalize by pressure gradient at rho=0.5
            True - same as 'global'
        log (bool): plot logarithm of error or absolute value
        cmap (str,matplotlib.colors.Colormap): colormap to use
    
    Returns:
        ax (matplotlib.axes): handle to axes used for plotting
        im (TriContourSet): handle to contourf plot
    """

    if domain not in ['real','sfl']:
        raise ValueError("domain expected one of 'real', 'sfl'")
    
    nr = 100
    nv = 100
    r = np.linspace(0,1,nr)
    v = np.linspace(0,2*np.pi,nv)
    z = 0
    r,v,z = np.meshgrid(r,v,z,indexing='ij')
    r = r.flatten()
    v = v.flatten()
    z = z.flatten()
    
    nodes = np.stack([r,v,z])
    derivatives = get_needed_derivatives('force')
    zernt = ZernikeTransform(nodes,zern_idx,NFP,derivatives)
    axn = np.where(r == 0)[0]
    
    mu0 = 4*np.pi*1e-7
    presr = presfun(r,1, presfun_params)
    iota = iotafun(r,0, iotafun_params)
    iotar = iotafun(r,1, iotafun_params)
    
    coord_der = compute_coordinate_derivatives(cR,cZ,zernt)
    
    R_zz = -(Psi_total**2*coord_der['R_r']**2*coord_der['Z_v']**2*coord_der['Z_z']**2*r**2 + Psi_total**2*coord_der['R_v']**2*coord_der['Z_r']**2*coord_der['Z_z']**2*r**2 - Psi_total**2*coord_der['R']**3*coord_der['R_r']*coord_der['Z_v']**2*r + Psi_total**2*coord_der['R_r']**2*coord_der['Z_v']**4*r**2*iota**2 + Psi_total**2*coord_der['R']**3*coord_der['R_rr']*coord_der['Z_v']**2*r**2 + Psi_total**2*coord_der['R']**3*coord_der['R_vv']*coord_der['Z_r']**2*r**2 - Psi_total**2*coord_der['R']**2*coord_der['R_r']**2*coord_der['Z_v']**2*r**2 - Psi_total**2*coord_der['R']**2*coord_der['R_v']**2*coord_der['Z_r']**2*r**2 - Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['Z_v']**4*r*iota**2 + Psi_total**2*coord_der['R']**3*coord_der['R_v']*coord_der['Z_r']*coord_der['Z_v']*r + Psi_total**2*coord_der['R_v']**2*coord_der['Z_r']**2*coord_der['Z_v']**2*r**2*iota**2 - coord_der['R']**3*coord_der['R_r']**3*coord_der['Z_v']**4*mu0*np.pi**2*presr + Psi_total**2*coord_der['R']*coord_der['R_rr']*coord_der['Z_v']**4*r**2*iota**2 + 2*Psi_total**2*coord_der['R_r']**2*coord_der['Z_v']**3*coord_der['Z_z']*r**2*iota - Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_z']**2*coord_der['Z_v']**2*r - Psi_total**2*coord_der['R']**3*coord_der['R_r']*coord_der['Z_r']*coord_der['Z_vv']*r**2 + Psi_total**2*coord_der['R']**3*coord_der['R_r']*coord_der['Z_rv']*coord_der['Z_v']*r**2 - 2*Psi_total**2*coord_der['R']**3*coord_der['R_rv']*coord_der['Z_r']*coord_der['Z_v']*r**2 + Psi_total**2*coord_der['R']**3*coord_der['R_v']*coord_der['Z_r']*coord_der['Z_rv']*r**2 - Psi_total**2*coord_der['R']**3*coord_der['R_v']*coord_der['Z_rr']*coord_der['Z_v']*r**2 - Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['Z_v']**2*coord_der['Z_z']**2*r + Psi_total**2*coord_der['R']*coord_der['R_rr']*coord_der['R_z']**2*coord_der['Z_v']**2*r**2 + Psi_total**2*coord_der['R']*coord_der['R_vv']*coord_der['R_z']**2*coord_der['Z_r']**2*r**2 + Psi_total**2*coord_der['R']*coord_der['R_rr']*coord_der['Z_v']**2*coord_der['Z_z']**2*r**2 + Psi_total**2*coord_der['R']*coord_der['R_vv']*coord_der['Z_r']**2*coord_der['Z_z']**2*r**2 - 2*Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['Z_v']**3*coord_der['Z_z']*r*iota + Psi_total**2*coord_der['R']*coord_der['R_rr']*coord_der['R_v']**2*coord_der['Z_v']**2*r**2*iota**2 + Psi_total**2*coord_der['R']*coord_der['R_r']**2*coord_der['R_vv']*coord_der['Z_v']**2*r**2*iota**2 + Psi_total**2*coord_der['R']*coord_der['R_vv']*coord_der['Z_r']**2*coord_der['Z_v']**2*r**2*iota**2 - Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['Z_v']**3*coord_der['Z_z']*r**2*iotar + Psi_total**2*coord_der['R']*coord_der['R_v']*coord_der['Z_r']*coord_der['Z_v']**3*r*iota**2 + Psi_total**2*coord_der['R']*coord_der['R_v']**3*coord_der['Z_r']*coord_der['Z_v']*r*iota**2 - Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['Z_v']**3*coord_der['Z_rz']*r**2*iota + 2*Psi_total**2*coord_der['R']*coord_der['R_rr']*coord_der['Z_v']**3*coord_der['Z_z']*r**2*iota - Psi_total**2*coord_der['R']*coord_der['R_v']**3*coord_der['Z_r']*coord_der['Z_rz']*r**2*iota + Psi_total**2*coord_der['R']*coord_der['R_v']*coord_der['R_z']**2*coord_der['Z_r']*coord_der['Z_v']*r + Psi_total**2*coord_der['R']*coord_der['R_v']*coord_der['Z_r']*coord_der['Z_v']*coord_der['Z_z']**2*r + coord_der['R']**3*coord_der['R_v']**3*coord_der['Z_r']**3*coord_der['Z_v']*mu0*np.pi**2*presr - Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['Z_v']**4*r**2*iota*iotar - Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_v']**2*coord_der['Z_v']**2*r*iota**2 + 2*Psi_total**2*coord_der['R']*coord_der['R_r']**2*coord_der['R_vz']*coord_der['Z_v']**2*r**2*iota - 2*Psi_total**2*coord_der['R']*coord_der['R_rv']*coord_der['Z_r']*coord_der['Z_v']**3*r**2*iota**2 - Psi_total**2*coord_der['R']*coord_der['R_v']*coord_der['Z_rr']*coord_der['Z_v']**3*r**2*iota**2 - Psi_total**2*coord_der['R']*coord_der['R_v']**3*coord_der['Z_rr']*coord_der['Z_v']*r**2*iota**2 - 2*Psi_total**2*coord_der['R_r']*coord_der['R_v']*coord_der['Z_r']*coord_der['Z_v']**3*r**2*iota**2 + 2*Psi_total**2*coord_der['R_v']**2*coord_der['Z_r']**2*coord_der['Z_v']*coord_der['Z_z']*r**2*iota - 2*Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_z']*coord_der['R_rz']*coord_der['Z_v']**2*r**2 - 2*Psi_total**2*coord_der['R']*coord_der['R_v']*coord_der['R_z']*coord_der['R_vz']*coord_der['Z_r']**2*r**2 + 2*Psi_total**2*coord_der['R']**2*coord_der['R_r']*coord_der['R_v']*coord_der['Z_r']*coord_der['Z_v']*r**2 - Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_z']**2*coord_der['Z_r']*coord_der['Z_vv']*r**2 + Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_z']**2*coord_der['Z_rv']*coord_der['Z_v']*r**2 - 2*Psi_total**2*coord_der['R']*coord_der['R_rv']*coord_der['R_z']**2*coord_der['Z_r']*coord_der['Z_v']*r**2 + Psi_total**2*coord_der['R']*coord_der['R_v']*coord_der['R_z']**2*coord_der['Z_r']*coord_der['Z_rv']*r**2 - Psi_total**2*coord_der['R']*coord_der['R_v']*coord_der['R_z']**2*coord_der['Z_rr']*coord_der['Z_v']*r**2 - Psi_total**2*coord_der['R']*coord_der['R_v']**2*coord_der['R_z']*coord_der['Z_r']*coord_der['Z_rz']*r**2 - Psi_total**2*coord_der['R']*coord_der['R_r']**2*coord_der['R_z']*coord_der['Z_v']*coord_der['Z_vz']*r**2 - Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['Z_r']*coord_der['Z_vv']*coord_der['Z_z']**2*r**2 + Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['Z_rv']*coord_der['Z_v']*coord_der['Z_z']**2*r**2 - 2*Psi_total**2*coord_der['R']*coord_der['R_rv']*coord_der['Z_r']*coord_der['Z_v']*coord_der['Z_z']**2*r**2 + Psi_total**2*coord_der['R']*coord_der['R_v']*coord_der['Z_r']*coord_der['Z_rv']*coord_der['Z_z']**2*r**2 - Psi_total**2*coord_der['R']*coord_der['R_v']*coord_der['Z_rr']*coord_der['Z_v']*coord_der['Z_z']**2*r**2 - Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['Z_v']**2*coord_der['Z_z']*coord_der['Z_rz']*r**2 - Psi_total**2*coord_der['R']*coord_der['R_v']*coord_der['Z_r']**2*coord_der['Z_z']*coord_der['Z_vz']*r**2 - 2*Psi_total**2*coord_der['R_r']*coord_der['R_v']*coord_der['Z_r']*coord_der['Z_v']*coord_der['Z_z']**2*r**2 - 2*Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_rv']*coord_der['R_v']*coord_der['Z_v']**2*r**2*iota**2 + Psi_total**2*coord_der['R']*coord_der['R_v']*coord_der['Z_r']*coord_der['Z_v']**3*r**2*iota*iotar + Psi_total**2*coord_der['R']*coord_der['R_v']**3*coord_der['Z_r']*coord_der['Z_v']*r**2*iota*iotar + 2*Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_v']**2*coord_der['Z_rv']*coord_der['Z_v']*r**2*iota**2 - Psi_total**2*coord_der['R']*coord_der['R_r']**2*coord_der['R_v']*coord_der['Z_v']*coord_der['Z_vv']*r**2*iota**2 + 2*Psi_total**2*coord_der['R']*coord_der['R_v']*coord_der['Z_r']*coord_der['Z_rv']*coord_der['Z_v']**2*r**2*iota**2 - Psi_total**2*coord_der['R']*coord_der['R_v']*coord_der['Z_r']**2*coord_der['Z_v']*coord_der['Z_vv']*r**2*iota**2 - 3*coord_der['R']**3*coord_der['R_r']*coord_der['R_v']**2*coord_der['Z_r']**2*coord_der['Z_v']**2*mu0*np.pi**2*presr - 2*Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_v']*coord_der['R_z']*coord_der['Z_v']**2*r*iota + 2*Psi_total**2*coord_der['R']*coord_der['R_v']**2*coord_der['R_z']*coord_der['Z_r']*coord_der['Z_v']*r*iota + 2*Psi_total**2*coord_der['R']*coord_der['R_v']*coord_der['Z_r']*coord_der['Z_v']**2*coord_der['Z_z']*r*iota - Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_v']**2*coord_der['Z_v']**2*r**2*iota*iotar - Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_v']*coord_der['R_z']*coord_der['Z_v']**2*r**2*iotar + Psi_total**2*coord_der['R']*coord_der['R_v']**2*coord_der['R_z']*coord_der['Z_r']*coord_der['Z_v']*r**2*iotar + Psi_total**2*coord_der['R']*coord_der['R_v']*coord_der['Z_r']*coord_der['Z_v']**2*coord_der['Z_z']*r**2*iotar - 2*Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_rv']*coord_der['R_z']*coord_der['Z_v']**2*r**2*iota - 2*Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_v']*coord_der['R_rz']*coord_der['Z_v']**2*r**2*iota + 2*Psi_total**2*coord_der['R']*coord_der['R_rr']*coord_der['R_v']*coord_der['R_z']*coord_der['Z_v']**2*r**2*iota + Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_v']**2*coord_der['Z_r']*coord_der['Z_vz']*r**2*iota + Psi_total**2*coord_der['R']*coord_der['R_v']**2*coord_der['R_z']*coord_der['Z_r']*coord_der['Z_rv']*r**2*iota + Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_v']**2*coord_der['Z_v']*coord_der['Z_rz']*r**2*iota - 2*Psi_total**2*coord_der['R']*coord_der['R_v']**2*coord_der['R_z']*coord_der['Z_rr']*coord_der['Z_v']*r**2*iota + 2*Psi_total**2*coord_der['R']*coord_der['R_v']**2*coord_der['R_rz']*coord_der['Z_r']*coord_der['Z_v']*r**2*iota - Psi_total**2*coord_der['R']*coord_der['R_r']**2*coord_der['R_v']*coord_der['Z_v']*coord_der['Z_vz']*r**2*iota - Psi_total**2*coord_der['R']*coord_der['R_r']**2*coord_der['R_z']*coord_der['Z_v']*coord_der['Z_vv']*r**2*iota + Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['Z_r']*coord_der['Z_v']**2*coord_der['Z_vz']*r**2*iota + Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['Z_rv']*coord_der['Z_v']**2*coord_der['Z_z']*r**2*iota - 4*Psi_total**2*coord_der['R']*coord_der['R_rv']*coord_der['Z_r']*coord_der['Z_v']**2*coord_der['Z_z']*r**2*iota + Psi_total**2*coord_der['R']*coord_der['R_v']*coord_der['Z_r']*coord_der['Z_v']**2*coord_der['Z_rz']*r**2*iota - 2*Psi_total**2*coord_der['R']*coord_der['R_v']*coord_der['Z_rr']*coord_der['Z_v']**2*coord_der['Z_z']*r**2*iota - Psi_total**2*coord_der['R']*coord_der['R_v']*coord_der['Z_r']**2*coord_der['Z_v']*coord_der['Z_vz']*r**2*iota - Psi_total**2*coord_der['R']*coord_der['R_v']*coord_der['Z_r']**2*coord_der['Z_vv']*coord_der['Z_z']*r**2*iota + 2*Psi_total**2*coord_der['R']*coord_der['R_vv']*coord_der['Z_r']**2*coord_der['Z_v']*coord_der['Z_z']*r**2*iota - 4*Psi_total**2*coord_der['R_r']*coord_der['R_v']*coord_der['Z_r']*coord_der['Z_v']**2*coord_der['Z_z']*r**2*iota + Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_v']*coord_der['R_z']*coord_der['Z_r']*coord_der['Z_vz']*r**2 + 2*Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_z']*coord_der['R_vz']*coord_der['Z_r']*coord_der['Z_v']*r**2 + Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_v']*coord_der['R_z']*coord_der['Z_v']*coord_der['Z_rz']*r**2 + 2*Psi_total**2*coord_der['R']*coord_der['R_v']*coord_der['R_z']*coord_der['R_rz']*coord_der['Z_r']*coord_der['Z_v']*r**2 + Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['Z_r']*coord_der['Z_v']*coord_der['Z_z']*coord_der['Z_vz']*r**2 + Psi_total**2*coord_der['R']*coord_der['R_v']*coord_der['Z_r']*coord_der['Z_v']*coord_der['Z_z']*coord_der['Z_rz']*r**2 + 3*coord_der['R']**3*coord_der['R_r']**2*coord_der['R_v']*coord_der['Z_r']*coord_der['Z_v']**3*mu0*np.pi**2*presr - Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_v']*coord_der['R_z']*coord_der['Z_r']*coord_der['Z_vv']*r**2*iota + 3*Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_v']*coord_der['R_z']*coord_der['Z_rv']*coord_der['Z_v']*r**2*iota - 2*Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_v']*coord_der['R_vz']*coord_der['Z_r']*coord_der['Z_v']*r**2*iota + 2*Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_vv']*coord_der['R_z']*coord_der['Z_r']*coord_der['Z_v']*r**2*iota - 2*Psi_total**2*coord_der['R']*coord_der['R_rv']*coord_der['R_v']*coord_der['R_z']*coord_der['Z_r']*coord_der['Z_v']*r**2*iota - Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['Z_r']*coord_der['Z_v']*coord_der['Z_vv']*coord_der['Z_z']*r**2*iota + 3*Psi_total**2*coord_der['R']*coord_der['R_v']*coord_der['Z_r']*coord_der['Z_rv']*coord_der['Z_v']*coord_der['Z_z']*r**2*iota) / (Psi_total**2*coord_der['R']*r**2*(coord_der['R_r']*coord_der['Z_v'] - coord_der['R_v']*coord_der['Z_r'])**2)
    Z_zz = (Psi_total**2*coord_der['R']**3*coord_der['R_v']**2*coord_der['Z_r']*r - Psi_total**2*coord_der['R']**3*coord_der['R_v']**2*coord_der['Z_rr']*r**2 - Psi_total**2*coord_der['R']**3*coord_der['R_r']**2*coord_der['Z_vv']*r**2 + Psi_total**2*coord_der['R']*coord_der['R_v']**4*coord_der['Z_r']*r*iota**2 - Psi_total**2*coord_der['R']**3*coord_der['R_r']*coord_der['R_v']*coord_der['Z_v']*r + coord_der['R']**3*coord_der['R_v']**4*coord_der['Z_r']**3*mu0*np.pi**2*presr - Psi_total**2*coord_der['R']*coord_der['R_v']**4*coord_der['Z_rr']*r**2*iota**2 + Psi_total**2*coord_der['R_r']**2*coord_der['R_z']*coord_der['Z_v']**3*r**2*iota + Psi_total**2*coord_der['R_v']**3*coord_der['Z_r']**2*coord_der['Z_z']*r**2*iota - Psi_total**2*coord_der['R']**3*coord_der['R_r']*coord_der['R_rv']*coord_der['Z_v']*r**2 + 2*Psi_total**2*coord_der['R']**3*coord_der['R_r']*coord_der['R_v']*coord_der['Z_rv']*r**2 + Psi_total**2*coord_der['R']**3*coord_der['R_r']*coord_der['R_vv']*coord_der['Z_r']*r**2 - Psi_total**2*coord_der['R']**3*coord_der['R_rv']*coord_der['R_v']*coord_der['Z_r']*r**2 + Psi_total**2*coord_der['R']**3*coord_der['R_rr']*coord_der['R_v']*coord_der['Z_v']*r**2 + Psi_total**2*coord_der['R']*coord_der['R_v']**2*coord_der['R_z']**2*coord_der['Z_r']*r + Psi_total**2*coord_der['R']*coord_der['R_v']**2*coord_der['Z_r']*coord_der['Z_z']**2*r + Psi_total**2*coord_der['R_r']**2*coord_der['R_v']*coord_der['Z_v']**3*r**2*iota**2 + Psi_total**2*coord_der['R_v']**3*coord_der['Z_r']**2*coord_der['Z_v']*r**2*iota**2 - Psi_total**2*coord_der['R']*coord_der['R_v']**2*coord_der['R_z']**2*coord_der['Z_rr']*r**2 - Psi_total**2*coord_der['R']*coord_der['R_r']**2*coord_der['R_z']**2*coord_der['Z_vv']*r**2 - Psi_total**2*coord_der['R']*coord_der['R_v']**2*coord_der['Z_rr']*coord_der['Z_z']**2*r**2 - Psi_total**2*coord_der['R']*coord_der['R_r']**2*coord_der['Z_vv']*coord_der['Z_z']**2*r**2 + Psi_total**2*coord_der['R_r']**2*coord_der['R_z']*coord_der['Z_v']**2*coord_der['Z_z']*r**2 + Psi_total**2*coord_der['R_v']**2*coord_der['R_z']*coord_der['Z_r']**2*coord_der['Z_z']*r**2 + 2*Psi_total**2*coord_der['R']*coord_der['R_v']**3*coord_der['R_z']*coord_der['Z_r']*r*iota - Psi_total**2*coord_der['R']*coord_der['R_r']**2*coord_der['R_v']**2*coord_der['Z_vv']*r**2*iota**2 - Psi_total**2*coord_der['R']*coord_der['R_v']**2*coord_der['Z_rr']*coord_der['Z_v']**2*r**2*iota**2 - Psi_total**2*coord_der['R']*coord_der['R_v']**2*coord_der['Z_r']**2*coord_der['Z_vv']*r**2*iota**2 - 2*Psi_total**2*coord_der['R_r']*coord_der['R_v']**2*coord_der['Z_r']*coord_der['Z_v']**2*r**2*iota**2 + Psi_total**2*coord_der['R']*coord_der['R_v']**3*coord_der['R_z']*coord_der['Z_r']*r**2*iotar - Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_v']*coord_der['Z_v']**3*r*iota**2 - Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_v']**3*coord_der['Z_v']*r*iota**2 + Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_rz']*coord_der['Z_v']**3*r**2*iota - 2*Psi_total**2*coord_der['R']*coord_der['R_v']**3*coord_der['R_z']*coord_der['Z_rr']*r**2*iota + Psi_total**2*coord_der['R']*coord_der['R_v']**3*coord_der['R_rz']*coord_der['Z_r']*r**2*iota - Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_v']*coord_der['R_z']**2*coord_der['Z_v']*r - Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_v']*coord_der['Z_v']*coord_der['Z_z']**2*r - coord_der['R']**3*coord_der['R_r']**3*coord_der['R_v']*coord_der['Z_v']**3*mu0*np.pi**2*presr + Psi_total**2*coord_der['R']*coord_der['R_v']**4*coord_der['Z_r']*r**2*iota*iotar + 2*Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_v']**3*coord_der['Z_rv']*r**2*iota**2 + Psi_total**2*coord_der['R']*coord_der['R_rr']*coord_der['R_v']*coord_der['Z_v']**3*r**2*iota**2 + Psi_total**2*coord_der['R']*coord_der['R_rr']*coord_der['R_v']**3*coord_der['Z_v']*r**2*iota**2 + Psi_total**2*coord_der['R']*coord_der['R_v']**2*coord_der['Z_r']*coord_der['Z_v']**2*r*iota**2 - 2*Psi_total**2*coord_der['R']*coord_der['R_v']**2*coord_der['Z_r']**2*coord_der['Z_vz']*r**2*iota + Psi_total**2*coord_der['R_r']**2*coord_der['R_v']*coord_der['Z_v']**2*coord_der['Z_z']*r**2*iota + Psi_total**2*coord_der['R_v']**2*coord_der['R_z']*coord_der['Z_r']**2*coord_der['Z_v']*r**2*iota - Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_rv']*coord_der['R_z']**2*coord_der['Z_v']*r**2 + 2*Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_v']*coord_der['R_z']**2*coord_der['Z_rv']*r**2 + Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_vv']*coord_der['R_z']**2*coord_der['Z_r']*r**2 - Psi_total**2*coord_der['R']*coord_der['R_rv']*coord_der['R_v']*coord_der['R_z']**2*coord_der['Z_r']*r**2 + Psi_total**2*coord_der['R']*coord_der['R_rr']*coord_der['R_v']*coord_der['R_z']**2*coord_der['Z_v']*r**2 + Psi_total**2*coord_der['R']*coord_der['R_v']**2*coord_der['R_z']*coord_der['R_rz']*coord_der['Z_r']*r**2 + Psi_total**2*coord_der['R']*coord_der['R_r']**2*coord_der['R_z']*coord_der['R_vz']*coord_der['Z_v']*r**2 - Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_rv']*coord_der['Z_v']*coord_der['Z_z']**2*r**2 + 2*Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_v']*coord_der['Z_rv']*coord_der['Z_z']**2*r**2 + Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_vv']*coord_der['Z_r']*coord_der['Z_z']**2*r**2 - Psi_total**2*coord_der['R']*coord_der['R_rv']*coord_der['R_v']*coord_der['Z_r']*coord_der['Z_z']**2*r**2 + Psi_total**2*coord_der['R']*coord_der['R_rr']*coord_der['R_v']*coord_der['Z_v']*coord_der['Z_z']**2*r**2 + Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_rz']*coord_der['Z_v']**2*coord_der['Z_z']*r**2 + Psi_total**2*coord_der['R']*coord_der['R_v']*coord_der['R_vz']*coord_der['Z_r']**2*coord_der['Z_z']*r**2 + 2*Psi_total**2*coord_der['R']*coord_der['R_v']**2*coord_der['Z_r']*coord_der['Z_z']*coord_der['Z_rz']*r**2 + 2*Psi_total**2*coord_der['R']*coord_der['R_r']**2*coord_der['Z_v']*coord_der['Z_z']*coord_der['Z_vz']*r**2 - Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_v']*coord_der['Z_v']**3*r**2*iota*iotar - Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_v']**3*coord_der['Z_v']*r**2*iota*iotar - 2*Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_rv']*coord_der['R_v']**2*coord_der['Z_v']*r**2*iota**2 + Psi_total**2*coord_der['R']*coord_der['R_r']**2*coord_der['R_v']*coord_der['R_vv']*coord_der['Z_v']*r**2*iota**2 - 2*Psi_total**2*coord_der['R']*coord_der['R_rv']*coord_der['R_v']*coord_der['Z_r']*coord_der['Z_v']**2*r**2*iota**2 + Psi_total**2*coord_der['R']*coord_der['R_v']*coord_der['R_vv']*coord_der['Z_r']**2*coord_der['Z_v']*r**2*iota**2 + 2*Psi_total**2*coord_der['R']*coord_der['R_v']**2*coord_der['Z_r']*coord_der['Z_rv']*coord_der['Z_v']*r**2*iota**2 + 3*coord_der['R']**3*coord_der['R_r']**2*coord_der['R_v']**2*coord_der['Z_r']*coord_der['Z_v']**2*mu0*np.pi**2*presr - 2*Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_v']**2*coord_der['R_z']*coord_der['Z_v']*r*iota - 2*Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_v']*coord_der['Z_v']**2*coord_der['Z_z']*r*iota + 2*Psi_total**2*coord_der['R']*coord_der['R_v']**2*coord_der['Z_r']*coord_der['Z_v']*coord_der['Z_z']*r*iota + Psi_total**2*coord_der['R']*coord_der['R_v']**2*coord_der['Z_r']*coord_der['Z_v']**2*r**2*iota*iotar - Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_v']**2*coord_der['R_z']*coord_der['Z_v']*r**2*iotar - Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_v']*coord_der['Z_v']**2*coord_der['Z_z']*r**2*iotar + Psi_total**2*coord_der['R']*coord_der['R_v']**2*coord_der['Z_r']*coord_der['Z_v']*coord_der['Z_z']*r**2*iotar + 4*Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_v']**2*coord_der['R_z']*coord_der['Z_rv']*r**2*iota - Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_v']**2*coord_der['R_vz']*coord_der['Z_r']*r**2*iota - Psi_total**2*coord_der['R']*coord_der['R_rv']*coord_der['R_v']**2*coord_der['R_z']*coord_der['Z_r']*r**2*iota - Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_v']**2*coord_der['R_rz']*coord_der['Z_v']*r**2*iota + 2*Psi_total**2*coord_der['R']*coord_der['R_rr']*coord_der['R_v']**2*coord_der['R_z']*coord_der['Z_v']*r**2*iota - 2*Psi_total**2*coord_der['R']*coord_der['R_r']**2*coord_der['R_v']*coord_der['R_z']*coord_der['Z_vv']*r**2*iota + Psi_total**2*coord_der['R']*coord_der['R_r']**2*coord_der['R_v']*coord_der['R_vz']*coord_der['Z_v']*r**2*iota + Psi_total**2*coord_der['R']*coord_der['R_r']**2*coord_der['R_vv']*coord_der['R_z']*coord_der['Z_v']*r**2*iota - Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_rv']*coord_der['Z_v']**2*coord_der['Z_z']*r**2*iota - Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_vz']*coord_der['Z_r']*coord_der['Z_v']**2*r**2*iota - 2*Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_v']*coord_der['Z_v']**2*coord_der['Z_rz']*r**2*iota + 2*Psi_total**2*coord_der['R']*coord_der['R_rr']*coord_der['R_v']*coord_der['Z_v']**2*coord_der['Z_z']*r**2*iota - Psi_total**2*coord_der['R']*coord_der['R_v']*coord_der['R_rz']*coord_der['Z_r']*coord_der['Z_v']**2*r**2*iota + Psi_total**2*coord_der['R']*coord_der['R_v']*coord_der['R_vv']*coord_der['Z_r']**2*coord_der['Z_z']*r**2*iota + Psi_total**2*coord_der['R']*coord_der['R_v']*coord_der['R_vz']*coord_der['Z_r']**2*coord_der['Z_v']*r**2*iota - 2*Psi_total**2*coord_der['R_r']*coord_der['R_v']*coord_der['R_z']*coord_der['Z_r']*coord_der['Z_v']**2*r**2*iota + 2*Psi_total**2*coord_der['R']*coord_der['R_v']**2*coord_der['Z_r']*coord_der['Z_rv']*coord_der['Z_z']*r**2*iota + 2*Psi_total**2*coord_der['R']*coord_der['R_v']**2*coord_der['Z_r']*coord_der['Z_v']*coord_der['Z_rz']*r**2*iota - 2*Psi_total**2*coord_der['R']*coord_der['R_v']**2*coord_der['Z_rr']*coord_der['Z_v']*coord_der['Z_z']*r**2*iota - 2*Psi_total**2*coord_der['R_r']*coord_der['R_v']**2*coord_der['Z_r']*coord_der['Z_v']*coord_der['Z_z']*r**2*iota - Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_v']*coord_der['R_z']*coord_der['R_vz']*coord_der['Z_r']*r**2 - Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_v']*coord_der['R_z']*coord_der['R_rz']*coord_der['Z_v']*r**2 - 2*Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_v']*coord_der['Z_r']*coord_der['Z_z']*coord_der['Z_vz']*r**2 - Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_vz']*coord_der['Z_r']*coord_der['Z_v']*coord_der['Z_z']*r**2 - 2*Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_v']*coord_der['Z_v']*coord_der['Z_z']*coord_der['Z_rz']*r**2 - Psi_total**2*coord_der['R']*coord_der['R_v']*coord_der['R_rz']*coord_der['Z_r']*coord_der['Z_v']*coord_der['Z_z']*r**2 - 2*Psi_total**2*coord_der['R_r']*coord_der['R_v']*coord_der['R_z']*coord_der['Z_r']*coord_der['Z_v']*coord_der['Z_z']*r**2 - 3*coord_der['R']**3*coord_der['R_r']*coord_der['R_v']**3*coord_der['Z_r']**2*coord_der['Z_v']*mu0*np.pi**2*presr - 3*Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_rv']*coord_der['R_v']*coord_der['R_z']*coord_der['Z_v']*r**2*iota + Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_v']*coord_der['R_vv']*coord_der['R_z']*coord_der['Z_r']*r**2*iota + 2*Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_v']*coord_der['Z_r']*coord_der['Z_v']*coord_der['Z_vz']*r**2*iota - 2*Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_v']*coord_der['Z_r']*coord_der['Z_vv']*coord_der['Z_z']*r**2*iota + 2*Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_v']*coord_der['Z_rv']*coord_der['Z_v']*coord_der['Z_z']*r**2*iota + Psi_total**2*coord_der['R']*coord_der['R_r']*coord_der['R_vv']*coord_der['Z_r']*coord_der['Z_v']*coord_der['Z_z']*r**2*iota - 3*Psi_total**2*coord_der['R']*coord_der['R_rv']*coord_der['R_v']*coord_der['Z_r']*coord_der['Z_v']*coord_der['Z_z']*r**2*iota) / (Psi_total**2*coord_der['R']*r**2*(coord_der['R_r']*coord_der['Z_v'] - coord_der['R_v']*coord_der['Z_r'])**2)
    
    put(R_zz,axn,(24*Psi_total**2*coord_der['R_rv']**2*coord_der['Z_r']**2*coord_der['R']**2 - 24*Psi_total**2*coord_der['Z_z']**2*coord_der['Z_rv']**2*coord_der['R_r']**2 - 24*Psi_total**2*coord_der['R_rv']**2*coord_der['Z_z']**2*coord_der['Z_r']**2 + 24*Psi_total**2*coord_der['Z_rv']**2*coord_der['R_r']**2*coord_der['R']**2 - 24*Psi_total**2*coord_der['R_rr']*coord_der['Z_rv']**2*coord_der['R']**3 - 12*Psi_total**2*coord_der['R_rrvv']*coord_der['Z_r']**2*coord_der['R']**3 + 24*Psi_total**2*coord_der['R_z']**2*coord_der['Z_rvv']*coord_der['R_r']**2*coord_der['Z_r'] - 24*Psi_total**2*coord_der['Z_z']**2*coord_der['R_rvv']*coord_der['R_r']*coord_der['Z_r']**2 - 12*Psi_total**2*coord_der['R_rrvv']*coord_der['Z_z']**2*coord_der['Z_r']**2*coord_der['R'] + 24*Psi_total**2*coord_der['Z_z']**2*coord_der['Z_rvv']*coord_der['R_r']**2*coord_der['Z_r'] - 72*Psi_total**2*coord_der['R_rvv']*coord_der['R_r']*coord_der['Z_r']**2*coord_der['R']**2 + 72*Psi_total**2*coord_der['Z_rvv']*coord_der['R_r']**2*coord_der['Z_r']*coord_der['R']**2 + 12*Psi_total**2*coord_der['Z_rrvv']*coord_der['R_r']*coord_der['Z_r']*coord_der['R']**3 + 24*Psi_total**2*coord_der['R_rr']*coord_der['Z_rvv']*coord_der['Z_r']*coord_der['R']**3 + 24*Psi_total**2*coord_der['R_rv']*coord_der['Z_rr']*coord_der['Z_rv']*coord_der['R']**3 - 12*Psi_total**2*coord_der['R_rv']*coord_der['Z_rrv']*coord_der['Z_r']*coord_der['R']**3 - 48*Psi_total**2*coord_der['Z_rr']*coord_der['R_rvv']*coord_der['Z_r']*coord_der['R']**3 + 24*Psi_total**2*coord_der['Z_rr']*coord_der['Z_rvv']*coord_der['R_r']*coord_der['R']**3 + 24*Psi_total**2*coord_der['Z_rv']*coord_der['R_rrv']*coord_der['Z_r']*coord_der['R']**3 - 12*Psi_total**2*coord_der['Z_rv']*coord_der['Z_rrv']*coord_der['R_r']*coord_der['R']**3 - 24*Psi_total**2*coord_der['R_z']**2*coord_der['R_rr']*coord_der['Z_rv']**2*coord_der['R'] - 24*Psi_total**2*coord_der['R_rr']*coord_der['Z_z']**2*coord_der['Z_rv']**2*coord_der['R'] - 24*Psi_total**2*coord_der['R_z']**2*coord_der['R_rvv']*coord_der['R_r']*coord_der['Z_r']**2 - 12*Psi_total**2*coord_der['R_rrvv']*coord_der['R_z']**2*coord_der['Z_r']**2*coord_der['R'] + 24*Psi_total**2*iota*coord_der['Z_z']*coord_der['Z_rv']**3*coord_der['R_r']*coord_der['R'] + 12*Psi_total**2*coord_der['Z_rrvv']*coord_der['R_z']**2*coord_der['R_r']*coord_der['Z_r']*coord_der['R'] + 48*Psi_total**2*coord_der['R_z']*coord_der['R_rv']*coord_der['R_rvz']*coord_der['Z_r']**2*coord_der['R'] - 48*Psi_total**2*coord_der['R_z']*coord_der['R_rz']*coord_der['R_rvv']*coord_der['Z_r']**2*coord_der['R'] + 24*Psi_total**2*coord_der['R_z']**2*coord_der['R_rr']*coord_der['Z_rvv']*coord_der['Z_r']*coord_der['R'] + 24*Psi_total**2*coord_der['R_z']**2*coord_der['R_rv']*coord_der['Z_rr']*coord_der['Z_rv']*coord_der['R'] - 12*Psi_total**2*coord_der['R_z']**2*coord_der['R_rv']*coord_der['Z_rrv']*coord_der['Z_r']*coord_der['R'] - 48*Psi_total**2*coord_der['R_z']**2*coord_der['Z_rr']*coord_der['R_rvv']*coord_der['Z_r']*coord_der['R'] + 24*Psi_total**2*coord_der['R_z']**2*coord_der['Z_rr']*coord_der['Z_rvv']*coord_der['R_r']*coord_der['R'] + 24*Psi_total**2*coord_der['R_z']**2*coord_der['Z_rv']*coord_der['R_rrv']*coord_der['Z_r']*coord_der['R'] - 12*Psi_total**2*coord_der['R_z']**2*coord_der['Z_rv']*coord_der['Z_rrv']*coord_der['R_r']*coord_der['R'] + 48*Psi_total**2*coord_der['R_rv']*coord_der['Z_z']**2*coord_der['Z_rv']*coord_der['R_r']*coord_der['Z_r'] + 12*Psi_total**2*coord_der['Z_rrvv']*coord_der['Z_z']**2*coord_der['R_r']*coord_der['Z_r']*coord_der['R'] + 24*Psi_total**2*coord_der['R_z']*coord_der['Z_rv']*coord_der['Z_rvz']*coord_der['R_r']**2*coord_der['R'] + 24*Psi_total**2*coord_der['R_rr']*coord_der['Z_z']**2*coord_der['Z_rvv']*coord_der['Z_r']*coord_der['R'] + 24*Psi_total**2*coord_der['R_rv']*coord_der['Z_z']**2*coord_der['Z_rr']*coord_der['Z_rv']*coord_der['R'] - 12*Psi_total**2*coord_der['R_rv']*coord_der['Z_z']**2*coord_der['Z_rrv']*coord_der['Z_r']*coord_der['R'] - 48*Psi_total**2*coord_der['Z_z']**2*coord_der['Z_rr']*coord_der['R_rvv']*coord_der['Z_r']*coord_der['R'] + 24*Psi_total**2*coord_der['Z_z']**2*coord_der['Z_rr']*coord_der['Z_rvv']*coord_der['R_r']*coord_der['R'] + 24*Psi_total**2*coord_der['Z_z']**2*coord_der['Z_rv']*coord_der['R_rrv']*coord_der['Z_r']*coord_der['R'] - 12*Psi_total**2*coord_der['Z_z']**2*coord_der['Z_rv']*coord_der['Z_rrv']*coord_der['R_r']*coord_der['R'] + 24*Psi_total**2*coord_der['R_rv']*coord_der['Z_z']*coord_der['Z_rvz']*coord_der['Z_r']**2*coord_der['R'] - 48*Psi_total**2*coord_der['Z_z']*coord_der['Z_rz']*coord_der['R_rvv']*coord_der['Z_r']**2*coord_der['R'] - 48*Psi_total**2*coord_der['R_rv']*coord_der['Z_rv']*coord_der['R_r']*coord_der['Z_r']*coord_der['R']**2 + 48*Psi_total**2*coord_der['R_z']*coord_der['R_rz']*coord_der['Z_rv']**2*coord_der['R_r']*coord_der['R'] + 24*Psi_total**2*coord_der['R_z']*coord_der['R_rv']**2*coord_der['Z_rz']*coord_der['Z_r']*coord_der['R'] + 24*Psi_total**2*coord_der['Z_z']*coord_der['Z_rv']**2*coord_der['Z_rz']*coord_der['R_r']*coord_der['R'] + 24*Psi_total**2*iota*coord_der['R_z']*coord_der['R_rv']*coord_der['Z_rv']**2*coord_der['R_r']*coord_der['R'] - 24*Psi_total**2*iota*coord_der['R_z']*coord_der['R_rv']**2*coord_der['Z_rv']*coord_der['Z_r']*coord_der['R'] - 24*Psi_total**2*iota*coord_der['R_rv']*coord_der['Z_z']*coord_der['Z_rv']**2*coord_der['Z_r']*coord_der['R'] - 48*Psi_total**2*coord_der['R_z']*coord_der['R_rv']*coord_der['R_rz']*coord_der['Z_rv']*coord_der['Z_r']*coord_der['R'] - 24*Psi_total**2*coord_der['R_z']*coord_der['R_rv']*coord_der['Z_rv']*coord_der['Z_rz']*coord_der['R_r']*coord_der['R'] - 24*Psi_total**2*coord_der['R_z']*coord_der['R_rv']*coord_der['Z_rvz']*coord_der['R_r']*coord_der['Z_r']*coord_der['R'] + 48*Psi_total**2*coord_der['R_z']*coord_der['R_rz']*coord_der['Z_rvv']*coord_der['R_r']*coord_der['Z_r']*coord_der['R'] - 48*Psi_total**2*coord_der['R_z']*coord_der['Z_rv']*coord_der['R_rvz']*coord_der['R_r']*coord_der['Z_r']*coord_der['R'] - 24*Psi_total**2*coord_der['R_rv']*coord_der['Z_z']*coord_der['Z_rv']*coord_der['Z_rz']*coord_der['Z_r']*coord_der['R'] - 24*Psi_total**2*coord_der['Z_z']*coord_der['Z_rv']*coord_der['Z_rvz']*coord_der['R_r']*coord_der['Z_r']*coord_der['R'] + 48*Psi_total**2*coord_der['Z_z']*coord_der['Z_rz']*coord_der['Z_rvv']*coord_der['R_r']*coord_der['Z_r']*coord_der['R'] + 24*Psi_total**2*iota*coord_der['R_z']*coord_der['Z_rv']*coord_der['Z_rvv']*coord_der['R_r']**2*coord_der['R'] + 24*Psi_total**2*iota*coord_der['R_rv']*coord_der['Z_z']*coord_der['Z_rvv']*coord_der['Z_r']**2*coord_der['R'] - 48*Psi_total**2*iota*coord_der['Z_z']*coord_der['Z_rv']*coord_der['R_rvv']*coord_der['Z_r']**2*coord_der['R'] + 24*Psi_total**2*iota*coord_der['R_z']*coord_der['R_rv']*coord_der['Z_rvv']*coord_der['R_r']*coord_der['Z_r']*coord_der['R'] - 48*Psi_total**2*iota*coord_der['R_z']*coord_der['Z_rv']*coord_der['R_rvv']*coord_der['R_r']*coord_der['Z_r']*coord_der['R'] + 24*Psi_total**2*iota*coord_der['Z_z']*coord_der['Z_rv']*coord_der['Z_rvv']*coord_der['R_r']*coord_der['Z_r']*coord_der['R']) / (24*Psi_total**2*(coord_der['R_rv']*coord_der['Z_r'] - coord_der['Z_rv']*coord_der['R_r'])**2*coord_der['R']))
    put(Z_zz,axn,(24*Psi_total**2*coord_der['Z_z']**2*coord_der['R_rvv']*coord_der['R_r']**2*coord_der['Z_r'] - 24*Psi_total**2*coord_der['Z_z']**2*coord_der['Z_rvv']*coord_der['R_r']**3 - 24*Psi_total**2*coord_der['R_rv']**2*coord_der['Z_rr']*coord_der['R']**3 - 72*Psi_total**2*coord_der['Z_rvv']*coord_der['R_r']**3*coord_der['R']**2 - 12*Psi_total**2*coord_der['Z_rrvv']*coord_der['R_r']**2*coord_der['R']**3 - 24*Psi_total**2*coord_der['R_z']**2*coord_der['Z_rvv']*coord_der['R_r']**3 - 12*Psi_total**2*coord_der['Z_rrvv']*coord_der['Z_z']**2*coord_der['R_r']**2*coord_der['R'] + 72*Psi_total**2*coord_der['R_rvv']*coord_der['R_r']**2*coord_der['Z_r']*coord_der['R']**2 + 12*Psi_total**2*coord_der['R_rrvv']*coord_der['R_r']*coord_der['Z_r']*coord_der['R']**3 + 24*Psi_total**2*coord_der['R_rr']*coord_der['R_rv']*coord_der['Z_rv']*coord_der['R']**3 + 24*Psi_total**2*coord_der['R_rr']*coord_der['R_rvv']*coord_der['Z_r']*coord_der['R']**3 - 48*Psi_total**2*coord_der['R_rr']*coord_der['Z_rvv']*coord_der['R_r']*coord_der['R']**3 - 12*Psi_total**2*coord_der['R_rv']*coord_der['R_rrv']*coord_der['Z_r']*coord_der['R']**3 + 24*Psi_total**2*coord_der['R_rv']*coord_der['Z_rrv']*coord_der['R_r']*coord_der['R']**3 + 24*Psi_total**2*coord_der['Z_rr']*coord_der['R_rvv']*coord_der['R_r']*coord_der['R']**3 - 12*Psi_total**2*coord_der['Z_rv']*coord_der['R_rrv']*coord_der['R_r']*coord_der['R']**3 - 24*Psi_total**2*coord_der['R_z']**2*coord_der['R_rv']**2*coord_der['Z_rr']*coord_der['R'] - 24*Psi_total**2*coord_der['R_rv']**2*coord_der['Z_z']**2*coord_der['Z_rr']*coord_der['R'] + 24*Psi_total**2*coord_der['R_z']**2*coord_der['R_rvv']*coord_der['R_r']**2*coord_der['Z_r'] + 24*Psi_total**2*coord_der['R_z']*coord_der['Z_z']*coord_der['Z_rv']**2*coord_der['R_r']**2 + 24*Psi_total**2*coord_der['R_z']*coord_der['R_rv']**2*coord_der['Z_z']*coord_der['Z_r']**2 - 12*Psi_total**2*coord_der['Z_rrvv']*coord_der['R_z']**2*coord_der['R_r']**2*coord_der['R'] + 24*Psi_total**2*iota*coord_der['R_z']*coord_der['R_rv']**3*coord_der['Z_r']*coord_der['R'] + 12*Psi_total**2*coord_der['R_rrvv']*coord_der['R_z']**2*coord_der['R_r']*coord_der['Z_r']*coord_der['R'] + 24*Psi_total**2*coord_der['R_z']**2*coord_der['R_rr']*coord_der['R_rv']*coord_der['Z_rv']*coord_der['R'] + 24*Psi_total**2*coord_der['R_z']**2*coord_der['R_rr']*coord_der['R_rvv']*coord_der['Z_r']*coord_der['R'] - 48*Psi_total**2*coord_der['R_z']**2*coord_der['R_rr']*coord_der['Z_rvv']*coord_der['R_r']*coord_der['R'] - 12*Psi_total**2*coord_der['R_z']**2*coord_der['R_rv']*coord_der['R_rrv']*coord_der['Z_r']*coord_der['R'] + 24*Psi_total**2*coord_der['R_z']**2*coord_der['R_rv']*coord_der['Z_rrv']*coord_der['R_r']*coord_der['R'] + 24*Psi_total**2*coord_der['R_z']**2*coord_der['Z_rr']*coord_der['R_rvv']*coord_der['R_r']*coord_der['R'] - 12*Psi_total**2*coord_der['R_z']**2*coord_der['Z_rv']*coord_der['R_rrv']*coord_der['R_r']*coord_der['R'] + 12*Psi_total**2*coord_der['R_rrvv']*coord_der['Z_z']**2*coord_der['R_r']*coord_der['Z_r']*coord_der['R'] - 48*Psi_total**2*coord_der['R_z']*coord_der['R_rz']*coord_der['Z_rvv']*coord_der['R_r']**2*coord_der['R'] + 24*Psi_total**2*coord_der['R_z']*coord_der['Z_rv']*coord_der['R_rvz']*coord_der['R_r']**2*coord_der['R'] + 24*Psi_total**2*coord_der['R_rr']*coord_der['R_rv']*coord_der['Z_z']**2*coord_der['Z_rv']*coord_der['R'] + 24*Psi_total**2*coord_der['R_rr']*coord_der['Z_z']**2*coord_der['R_rvv']*coord_der['Z_r']*coord_der['R'] - 48*Psi_total**2*coord_der['R_rr']*coord_der['Z_z']**2*coord_der['Z_rvv']*coord_der['R_r']*coord_der['R'] - 12*Psi_total**2*coord_der['R_rv']*coord_der['Z_z']**2*coord_der['R_rrv']*coord_der['Z_r']*coord_der['R'] + 24*Psi_total**2*coord_der['R_rv']*coord_der['Z_z']**2*coord_der['Z_rrv']*coord_der['R_r']*coord_der['R'] + 24*Psi_total**2*coord_der['Z_z']**2*coord_der['Z_rr']*coord_der['R_rvv']*coord_der['R_r']*coord_der['R'] - 12*Psi_total**2*coord_der['Z_z']**2*coord_der['Z_rv']*coord_der['R_rrv']*coord_der['R_r']*coord_der['R'] + 24*Psi_total**2*coord_der['R_rv']*coord_der['Z_z']*coord_der['R_rvz']*coord_der['Z_r']**2*coord_der['R'] + 48*Psi_total**2*coord_der['Z_z']*coord_der['Z_rv']*coord_der['Z_rvz']*coord_der['R_r']**2*coord_der['R'] - 48*Psi_total**2*coord_der['Z_z']*coord_der['Z_rz']*coord_der['Z_rvv']*coord_der['R_r']**2*coord_der['R'] + 24*Psi_total**2*coord_der['R_z']*coord_der['R_rv']**2*coord_der['R_rz']*coord_der['Z_r']*coord_der['R'] + 24*Psi_total**2*coord_der['Z_z']*coord_der['R_rz']*coord_der['Z_rv']**2*coord_der['R_r']*coord_der['R'] + 48*Psi_total**2*coord_der['R_rv']**2*coord_der['Z_z']*coord_der['Z_rz']*coord_der['Z_r']*coord_der['R'] - 48*Psi_total**2*coord_der['R_z']*coord_der['R_rv']*coord_der['Z_z']*coord_der['Z_rv']*coord_der['R_r']*coord_der['Z_r'] - 24*Psi_total**2*iota*coord_der['R_z']*coord_der['R_rv']**2*coord_der['Z_rv']*coord_der['R_r']*coord_der['R'] - 24*Psi_total**2*iota*coord_der['R_rv']*coord_der['Z_z']*coord_der['Z_rv']**2*coord_der['R_r']*coord_der['R'] + 24*Psi_total**2*iota*coord_der['R_rv']**2*coord_der['Z_z']*coord_der['Z_rv']*coord_der['Z_r']*coord_der['R'] - 24*Psi_total**2*coord_der['R_z']*coord_der['R_rv']*coord_der['R_rz']*coord_der['Z_rv']*coord_der['R_r']*coord_der['R'] - 24*Psi_total**2*coord_der['R_z']*coord_der['R_rv']*coord_der['R_rvz']*coord_der['R_r']*coord_der['Z_r']*coord_der['R'] + 48*Psi_total**2*coord_der['R_z']*coord_der['R_rz']*coord_der['R_rvv']*coord_der['R_r']*coord_der['Z_r']*coord_der['R'] - 24*Psi_total**2*coord_der['R_rv']*coord_der['Z_z']*coord_der['R_rz']*coord_der['Z_rv']*coord_der['Z_r']*coord_der['R'] - 48*Psi_total**2*coord_der['R_rv']*coord_der['Z_z']*coord_der['Z_rv']*coord_der['Z_rz']*coord_der['R_r']*coord_der['R'] - 48*Psi_total**2*coord_der['R_rv']*coord_der['Z_z']*coord_der['Z_rvz']*coord_der['R_r']*coord_der['Z_r']*coord_der['R'] - 24*Psi_total**2*coord_der['Z_z']*coord_der['Z_rv']*coord_der['R_rvz']*coord_der['R_r']*coord_der['Z_r']*coord_der['R'] + 48*Psi_total**2*coord_der['Z_z']*coord_der['Z_rz']*coord_der['R_rvv']*coord_der['R_r']*coord_der['Z_r']*coord_der['R'] - 48*Psi_total**2*iota*coord_der['R_z']*coord_der['R_rv']*coord_der['Z_rvv']*coord_der['R_r']**2*coord_der['R'] + 24*Psi_total**2*iota*coord_der['R_z']*coord_der['Z_rv']*coord_der['R_rvv']*coord_der['R_r']**2*coord_der['R'] + 24*Psi_total**2*iota*coord_der['R_rv']*coord_der['Z_z']*coord_der['R_rvv']*coord_der['Z_r']**2*coord_der['R'] + 24*Psi_total**2*iota*coord_der['R_z']*coord_der['R_rv']*coord_der['R_rvv']*coord_der['R_r']*coord_der['Z_r']*coord_der['R'] - 48*Psi_total**2*iota*coord_der['R_rv']*coord_der['Z_z']*coord_der['Z_rvv']*coord_der['R_r']*coord_der['Z_r']*coord_der['R'] + 24*Psi_total**2*iota*coord_der['Z_z']*coord_der['Z_rv']*coord_der['R_rvv']*coord_der['R_r']*coord_der['Z_r']*coord_der['R']) / (24*Psi_total**2*(coord_der['R_rv']*coord_der['Z_r'] - coord_der['Z_rv']*coord_der['R_r'])**2*coord_der['R']))
    
    R_zz_err = coord_der['R_zz'] - R_zz
    Z_zz_err = coord_der['Z_zz'] - Z_zz
    if log:
        R_zz_err = np.log10(np.abs(R_zz_err))
        Z_zz_err = np.log10(np.abs(Z_zz_err))
    
    fig, ax = plt.subplots(1,2,figsize=(6,3))
    
    if domain == 'real':
        R = zernt.transform(cR,0,0,0)
        Z = zernt.transform(cZ,0,0,0)
        levels=100
        imR = ax[0].tricontourf(R,Z,R_zz_err,levels=levels,cmap=cmap)
        imZ = ax[1].tricontourf(R,Z,Z_zz_err,levels=levels,cmap=cmap)
        ax[0].set_xlabel(r'$R$')
        ax[1].set_xlabel(r'$R$')
        ax[0].set_ylabel(r'$Z$')
        ax[1].set_ylabel(r'$Z$')
        ax[0].set_aspect('equal')
        ax[1].set_aspect('equal')
    elif domain == 'sfl':
        levels=100
        imR = ax[0].tricontourf(v,r,R_zz_err,levels=levels,cmap=cmap)
        imZ = ax[1].tricontourf(v,r,Z_zz_err,levels=levels,cmap=cmap)
        ax[0].set_xticks([0,np.pi/2,np.pi,3/2*np.pi,2*np.pi])
        ax[1].set_xticks([0,np.pi/2,np.pi,3/2*np.pi,2*np.pi])
        ax[0].set_xticklabels(['$0$',r'$\frac{\pi}{2}$',r'$\pi$',r'$\frac{3\pi}{2}$', r'$2\pi$'])
        ax[1].set_xticklabels(['$0$',r'$\frac{\pi}{2}$',r'$\pi$',r'$\frac{3\pi}{2}$', r'$2\pi$'])
        ax[0].set_xlabel(r'$\theta$')
        ax[1].set_xlabel(r'$\theta$')
        ax[0].set_ylabel(r'$\rho$')
        ax[1].set_ylabel(r'$\rho$')
    
    if log:
        ax[0].set_title('$log_{10}(|\partial_{\zeta\zeta}R error|)$')
        ax[1].set_title('$log_{10}(|\partial_{\zeta\zeta}Z error|)$')
    else:
        ax[0].set_title('$\partial_{\zeta\zeta}R$ error')
        ax[1].set_title('$\partial_{\zeta\zeta}Z$ error')
    
    plt.colorbar(imR,ax=ax[0])
    plt.colorbar(imZ,ax=ax[1])
    plt.show()
    
    return ax,imR,imZ


def plot_IC(cR_init, cZ_init, zern_idx, NFP, nodes, presfun_params, iotafun_params, **kwargs):
    """Plot initial conditions, such as the initial guess for flux surfaces,
    node locations, and profiles.
    
    Args:
        cR_init (ndarray, shape(N_coeffs,)): spectral coefficients of R
        cZ_init (ndarray, shape(N_coeffs,)): spectral coefficients of Z
        zern_idx (ndarray, shape(N_coeffs,3)): array of (l,m,n) indices for each spectral R,Z coeff
        NFP (int): number of field periods
        iotafun_params (array-like): paramters to pass to rotational transform function
        presfun_params (array-like): parameters to pass to pressure function

    Returns:
        fig (matplotlib.figure): handle to figure used for plotting
        ax (ndarray of matplotlib.axes): handles to axes used for plotting
    """
    
    fig = plt.figure(figsize=kwargs.get('figsize',(9,3)))
    gs = matplotlib.gridspec.GridSpec(2, 3) 
    ax0 = plt.subplot(gs[:,0])
    ax1 = plt.subplot(gs[:,1],projection='polar')
    ax2 = plt.subplot(gs[0,2])
    ax3 = plt.subplot(gs[1,2])
    
    # coordinate surfaces
    plot_coord_surfaces(cR_init,cZ_init,zern_idx,NFP,nr=10,nt=12,ax=ax0)
    ax0.axis('equal');
    ax0.set_title(r'Initial guess, $\zeta=0$ plane')
    
    # node locations
    ax1.scatter(nodes[1],nodes[0],s=1)
    ax1.set_ylim(0,1)
    ax1.set_xticks([0, np.pi/4, np.pi/2, 3/4*np.pi, 
                    np.pi, 5/4*np.pi, 3/2*np.pi, 7/4*np.pi])
    ax1.set_xticklabels(['$0$', r'$\frac{\pi}{4}$', r'$\frac{\pi}{2}$', r'$\frac{3\pi}{4}$',
                        r'$\pi$', r'$\frac{4\pi}{4}$', r'$\frac{3\pi}{2}$', r'$2\pi$'])
    ax1.set_yticklabels([])
    ax1.set_title(r'Node locations, $\zeta=0$ plane',pad=20)
    
    # profiles
    xx = np.linspace(0,1,100)
    ax2.plot(xx,presfun(xx,0,presfun_params),lw=1)
    ax2.set_ylabel(r'$p$')
    ax2.set_xticklabels([])
    ax2.set_title('Profiles')
    ax3.plot(xx,iotafun(xx,0,iotafun_params),lw=1)
    ax3.set_ylabel(r'$\iota$')
    ax3.set_xlabel(r'$\rho$')
    plt.subplots_adjust(wspace=0.5, hspace=0.3)
    ax = np.array([ax0,ax1,ax2,ax3])
    
    return fig, ax


def plot_comparison(x0,x1,zern_idx,NFP,label0='x0',label1='x1',**kwargs):
    """Plots force balance error
    
    Args:
        
        zern_idx (ndarray, shape(N_coeffs,3)): array of (l,m,n) indices for each spectral R,Z coeff
        NFP (int): number of field periods
        
    
    Returns:
        Nothing, makes plot
    """
    
    cR0,cZ0,cL0 = unpack_x(x0,len(zern_idx))
    cR1,cZ1,cL1 = unpack_x(x1,len(zern_idx))
    
    if np.max(zern_idx[:,2])==0:
        Nz = 1
        rows = 1
    else:
        Nz = 6
        rows = 2
    
    Nr = kwargs.get('Nr',8)
    Nv = kwargs.get('Nv',13)
    
    NNr = 100
    NNv = 360
    
    # constant rho surfaces
    r = np.linspace(0,1,Nr)
    v = np.linspace(0,2*np.pi,NNv)
    z = np.linspace(0,2*np.pi/NFP,Nz)
    rr,vv,zz = np.meshgrid(r,v,z,indexing='ij')
    rr = rr.flatten()
    vv = vv.flatten()
    zz = zz.flatten()
    nodes = [rr,vv,zz]
    zernt_r = ZernikeTransform(nodes,zern_idx,NFP)
    
    # constant theta surfaces
    r = np.linspace(0,1,NNr)
    v = np.linspace(0,2*np.pi,Nv)
    z = np.linspace(0,2*np.pi/NFP,Nz)
    rr,vv,zz = np.meshgrid(r,v,z,indexing='ij')
    rr = rr.flatten()
    vv = vv.flatten()
    zz = zz.flatten()
    nodes = [rr,vv,zz]
    zernt_v = ZernikeTransform(nodes,zern_idx,NFP)
    
    R0r = zernt_r.transform(cR0,0,0,0).reshape((Nr,NNv,Nz))
    Z0r = zernt_r.transform(cZ0,0,0,0).reshape((Nr,NNv,Nz))
    R1r = zernt_r.transform(cR1,0,0,0).reshape((Nr,NNv,Nz))
    Z1r = zernt_r.transform(cZ1,0,0,0).reshape((Nr,NNv,Nz))
    
    R0v = zernt_v.transform(cR0,0,0,0).reshape((NNr,Nv,Nz))
    Z0v = zernt_v.transform(cZ0,0,0,0).reshape((NNr,Nv,Nz))
    R1v = zernt_v.transform(cR1,0,0,0).reshape((NNr,Nv,Nz))
    Z1v = zernt_v.transform(cZ1,0,0,0).reshape((NNr,Nv,Nz))
    
    plt.figure()
    for k in range(Nz):
        ax = plt.subplot(rows,Nz/rows,k+1)
        
        ax.plot(R0r[0,0,k],Z0r[0,0,k],'bo')
        s0 = ax.plot(R0r[:,:,k].T,Z0r[:,:,k].T,'b-')
        ax.plot(R0v[:,:,k],Z0v[:,:,k],'b:')
        
        ax.plot(R1r[0,0,k],Z1r[0,0,k],'ro')
        s1 = ax.plot(R1r[:,:,k].T,Z1r[:,:,k].T,'r-')
        ax.plot(R1v[:,:,k],Z1v[:,:,k],'r:')
        
        ax.axis('equal')
        ax.set_xlabel('R')
        ax.set_ylabel('Z')
        if k == 0:
            s0[0].set_label(label0)
            s1[0].set_label(label1)
            ax.legend(fontsize='xx-small')
    plt.show()
    


def plot_vmec_comparison(vmec_data,cR,cZ,zern_idx,NFP):
    """Plots comparison of VMEC and DESC solutions
    
    Args:
        
    
    Returns:
        
    """
    
    Nr = 8
    Nv = 360
    if np.max(zern_idx[:,2])==0:
        Nz = 1
        rows = 1
    else:
        Nz = 6
        rows = 2
    
    Nr_vmec = vmec_data['rmnc'].shape[0]-1
    s_idx = Nr_vmec % np.floor(Nr_vmec/(Nr-1))
    idxes = np.linspace(s_idx,Nr_vmec,Nr).astype(int)
    if s_idx != 0:
        idxes = np.pad(idxes,(1,0),mode='constant')
    r = np.sqrt(idxes/Nr_vmec)
    v = np.linspace(0,2*np.pi,Nv)
    z = np.linspace(0,2*np.pi/NFP,Nz)
    rr,vv,zz = np.meshgrid(r,v,z,indexing='ij')
    rr = rr.flatten()
    vv = vv.flatten()
    zz = zz.flatten()
    nodes = [rr,vv,zz]
    zernt = ZernikeTransform(nodes,zern_idx,NFP)
    
    R_desc = zernt.transform(cR,0,0,0).reshape((r.size,Nv,Nz))
    Z_desc = zernt.transform(cZ,0,0,0).reshape((r.size,Nv,Nz))
    
    R_vmec,Z_vmec = vmec_interpolate(vmec_data['rmnc'][idxes],vmec_data['zmns'][idxes],vmec_data['xm'],vmec_data['xn'],v,z)
    
    plt.figure()
    for k in range(Nz):
        ax = plt.subplot(rows,Nz/rows,k+1)
        ax.plot(R_vmec[0,0,k],Z_vmec[0,0,k],'bo')
        s_vmec = ax.plot(R_vmec[:,:,k].T,Z_vmec[:,:,k].T,'b-')
        ax.plot(R_desc[0,0,k],Z_desc[0,0,k],'ro')
        s_desc = ax.plot(R_desc[:,:,k].T,Z_desc[:,:,k].T,'r--')
        ax.axis('equal')
        ax.set_xlabel('R')
        ax.set_ylabel('Z')
        if k == 0:
            s_vmec[0].set_label('VMEC')
            s_desc[0].set_label('DESC')
            ax.legend(fontsize='xx-small')
    plt.show()
    