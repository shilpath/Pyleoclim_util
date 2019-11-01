#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Apr 27 11:08:39 2017

@author: deborahkhider

Basic manipulation of timeseries for the pyleoclim module
"""

import numpy as np
import pandas as pd
import warnings
import copy
from scipy import special
import sys
from scipy import signal
from pyhht import EMD
from scipy.stats.mstats import mquantiles
from tqdm import tqdm
from scipy.stats.mstats import gmean

from pyleoclim import Spectral
from pyleoclim import Stats
from nitime import algorithms as alg

class Causality(object):

    def liang_causality(self, y1, y2, npt=1):
        '''
        Estimate the Liang information transfer from series y2 to series y1

        Args:
            y1, y2 (array): vectors of (real) numbers with identical length, no NaNs allowed
            npt (int >=1 ): time advance in performing Euler forward differencing,
                            e.g., 1, 2. Unless the series are generated with a highly chaotic deterministic system,
                            npt=1 should be used.

        Returns:
            T21: info flow from y2 to y1	(Note: not y1 -> y2!)
            tau21: the standardized info flow fro y2 to y1
            Z: the total info

        References:
            - Liang, X.S. (2013) The Liang-Kleeman Information Flow: Theory and
                Applications. Entropy, 15, 327-360, doi:10.3390/e15010327
            - Liang, X.S. (2014) Unraveling the cause-efect relation between timeseries.
                Physical review, E 90, 052150
            - Liang, X.S. (2015) Normalizing the causality between time series.
                Physical review, E 92, 022126
            - Liang, X.S. (2016) Information flow and causality as rigorous notions ab initio.
                Physical review, E 94, 052201
        '''
        dt = 1
        nm = np.size(y1)

        grad1 = (y1[0+npt:] - y1[0:-npt]) / (npt*dt)
        grad2 = (y2[0+npt:] - y2[0:-npt]) / (npt*dt)

        y1 = y1[:-npt]
        y2 = y2[:-npt]

        N = nm - npt
        C = np.cov(y1, y2)
        detC = np.linalg.det(C)

        dC = np.ndarray((2, 2))
        dC[0, 0] = np.sum((y1-np.mean(y1))*(grad1-np.mean(grad1)))
        dC[0, 1] = np.sum((y1-np.mean(y1))*(grad2-np.mean(grad2)))
        dC[1, 0] = np.sum((y2-np.mean(y2))*(grad1-np.mean(grad1)))
        dC[1, 1] = np.sum((y2-np.mean(y2))*(grad2-np.mean(grad2)))

        dC /= N-1

        a11 = C[1, 1]*dC[0, 0] - C[0, 1]*dC[1, 0]
        a12 = -C[0, 1]*dC[0, 0] + C[0, 0]*dC[1, 0]

        a11 /= detC
        a12 /= detC

        f1 = np.mean(grad1) - a11*np.mean(y1) - a12*np.mean(y2)
        R1 = grad1 - (f1 + a11*y1 + a12*y2)
        Q1 = np.sum(R1*R1)
        b1 = np.sqrt(Q1*dt/N)

        NI = np.ndarray((4, 4))
        NI[0, 0] = N*dt/b1**2
        NI[1, 1] = dt/b1**2*np.sum(y1*y1)
        NI[2, 2] = dt/b1**2*np.sum(y2*y2)
        NI[3, 3] = 3*dt/b1**4*np.sum(R1*R1) - N/b1**2
        NI[0, 1] = dt/b1**2*np.sum(y1)
        NI[0, 2] = dt/b1**2*np.sum(y2)
        NI[0, 3] = 2*dt/b1**3*np.sum(R1)
        NI[1, 2] = dt/b1**2*np.sum(y1*y2)
        NI[1, 3] = 2*dt/b1**3*np.sum(R1*y1)
        NI[2, 3] = 2*dt/b1**3*np.sum(R1*y2)

        NI[1, 0] = NI[0, 1]
        NI[2, 0] = NI[0, 2]
        NI[2, 1] = NI[1, 2]
        NI[3, 0] = NI[0, 3]
        NI[3, 1] = NI[1, 3]
        NI[3, 2] = NI[2, 3]

        invNI = np.linalg.pinv(NI)
        var_a12 = invNI[2, 2]
        T21 = C[0, 1]/C[0, 0] * (-C[1, 0]*dC[0, 0] + C[0, 0]*dC[1, 0]) / detC
        var_T21 = (C[0, 1]/C[0, 0])**2 * var_a12

        dH1_star= a11
        dH1_noise = b1**2 / (2*C[0, 0])

        Z = np.abs(T21) + np.abs(dH1_star) + np.abs(dH1_noise)

        tau21 = T21 / Z
        dH1_star = dH1_star / Z
        dH1_noise = dH1_noise / Z

        res_dict = {
            'T21': T21,
            'tau21': tau21,
            'Z': Z,
            'dH1_star': dH1_star,
            'dH1_noise': dH1_noise,
        }

        return res_dict

    def signif_isopersist(self, y1, y2, method='liang',
                          nsim=1000, qs=[0.005, 0.025, 0.05, 0.95, 0.975, 0.995],
                          **kwargs):
        ''' significance test with AR(1) with same persistence

        Args:
            y1, y2 (array): vectors of (real) numbers with identical length, no NaNs allowed
            method (str): only "liang" for now
            npt (int >=1 ):  time advance in performing Euler forward differencing,
                             e.g., 1, 2. Unless the series are generated with a highly chaotic deterministic system,
                             npt=1 should be used.
            nsim (int): the number of AR(1) surrogates for significance test
            qs (list): the quantiles for significance test

        Returns:
            res_dict (dict): A dictionary with the following information:
                T21_noise_qs (list) - the quantiles of the information flow from noise2 to noise1 for significance testing
                tau21_noise_qs (list) - the quantiles of the standardized information flow from noise2 to noise1 for significance testing

        '''
        stat = Stats.Correlation()
        g1 = stat.ar1_fit(y1)
        g2 = stat.ar1_fit(y2)
        sig1 = np.std(y1)
        sig2 = np.std(y2)
        n = np.size(y1)
        noise1 = stat.ar1_sim(n, nsim, g1, sig1)
        noise2 = stat.ar1_sim(n, nsim, g2, sig2)

        if method == 'liang':
            npt = kwargs['npt'] if 'npt' in kwargs else 1
            T21_noise = []
            tau21_noise = []
            for i in tqdm(range(nsim), desc='Calculating causality between surrogates'):
                res_noise = self.liang_causality(noise1[:, i], noise2[:, i], npt=npt)
                tau21_noise.append(res_noise['tau21'])
                T21_noise.append(res_noise['T21'])
            tau21_noise = np.array(tau21_noise)
            T21_noise = np.array(T21_noise)
            tau21_noise_qs = mquantiles(tau21_noise, qs)
            T21_noise_qs = mquantiles(T21_noise, qs)

            res_dict = {
                'tau21_noise_qs': tau21_noise_qs,
                'T21_noise_qs': T21_noise_qs,
            }
        else:
            raise KeyError(f'{method} is not a valid method')

        return res_dict

    def signif_isospec(self, y1, y2, method='liang',
                       nsim=1000, qs=[0.005, 0.025, 0.05, 0.95, 0.975, 0.995],
                       **kwargs):
        ''' significance test with surrogates with randomized phases

        Args:
            y1, y2 (array): vectors of (real) numbers with identical length, no NaNs allowed
            method (str): only "liang" for now
            npt (int >=1 ):  time advance in performing Euler forward differencing,
                             e.g., 1, 2. Unless the series are generated with a highly chaotic deterministic system,
                             npt=1 should be used.
            nsim (int): the number of surrogates for significance test
            qs (list): the quantiles for significance test

        Returns:
            res_dict (dict): A dictionary with the following information:
                T21_noise_qs (list) - the quantiles of the information flow from noise2 to noise1 for significance testing
                tau21_noise_qs (list) - the quantiles of the standardized information flow from noise2 to noise1 for significance testing

        '''
        stat = Stats.Correlation()
        noise1 = stat.phaseran(y1, nsim)
        noise2 = stat.phaseran(y2, nsim)

        if method == 'liang':
            npt = kwargs['npt'] if 'npt' in kwargs else 1
            T21_noise = []
            tau21_noise = []
            for i in tqdm(range(nsim), desc='Calculating causality between surrogates'):
                res_noise = self.liang_causality(noise1[:, i], noise2[:, i], npt=npt)
                tau21_noise.append(res_noise['tau21'])
                T21_noise.append(res_noise['T21'])
            tau21_noise = np.array(tau21_noise)
            T21_noise = np.array(T21_noise)
            tau21_noise_qs = mquantiles(tau21_noise, qs)
            T21_noise_qs = mquantiles(T21_noise, qs)

            res_dict = {
                'tau21_noise_qs': tau21_noise_qs,
                'T21_noise_qs': T21_noise_qs,
            }
        else:
            raise KeyError(f'{method} is not a valid method')

        return res_dict



class Decomposition(object):
    def pca():
        #TODO
        return

    def ssa(self, ys, ts, M, MC=1000, f=0.3, method='SSA', prep_args={}:
        '''
        Args:
            ys: time series
            ts: time axis
            M: window size
            MC: Number of iteration in the Monte-Carlo process
            f: fraction (0<f<=1) of good data points for identifying
            method (str, {'SSA', 'MSSA'}): perform SSA or MSSA

            prep_args (dict): the arguments for preprocess, including
                - detrend (str): 'none' - the original time series is assumed to have no trend;
                                 'linear' - a linear least-squares fit to `ys` is subtracted;
                                 'constant' - the mean of `ys` is subtracted
                                 'savitzy-golay' - ys is filtered using the Savitzky-Golay
                                     filters and the resulting filtered series is subtracted from y.
                                 'hht' - detrending with Hilbert-Huang Transform
                - params (list): The paramters for the Savitzky-Golay filters. The first parameter
                                 corresponds to the window size (default it set to half of the data)
                                 while the second parameter correspond to the order of the filter
                                 (default is 4). The third parameter is the order of the derivative
                                 (the default is zero, which means only smoothing.)
                - gaussianize (bool): If True, gaussianizes the timeseries
                - standardize (bool): If True, standardizes the timeseries

        Returns:
            res_dict (dict): the result dictionary, including
                - deval : eigenvalue spectrum
                - eig_vec : eigenvalue vector
                - q05: The 5% percentile of eigenvalues
                - q95: The 95% percentile of eigenvalues
                - pc: matrix of principal components
                - rc: matrix of RCs (nrec,N,nrec*M) (only if K>0)
        '''

        wa = WaveletAnalysis()
        ys, ts = Timeseries.clean_ts(ys, ts)
        ys = wa.preprocess(ys, ts, **prep_args)

        ssa_func = {
            'SSA': self.ssa_all,
            'MSSA': self.MSSA,
        }
        deval, eig_vec, q05, q95, pc, rc = ssa_func[method](ys, M, MC=MC, f=f)

        res_dict = {
            'deval': deval,
            'eig_vec': eig_vec,
            'q05': q05,
            'q95': q95,
            'pc': pc,
            'rc': rc,
        }

        return res_dict

    def standardize(self, x):
        if np.any(np.isnan(x)):
            x_ex = x[np.logical_not(np.isnan(x))]
            xm = np.mean(x_ex)
            xs = np.std(x_ex, ddof=1)
        else:
            xm = np.mean(x)
            xs = np.std(x, ddof=1)
        xstd = (x - xm) / xs
        return xstd

    def mssa(self, data, M, MC=1000, f=0.3):
        '''Multi-channel SSA analysis
        (applicable for data including missing values)
        and test the significance by Monte-Carlo method
        Input:
        data: multiple time series (dimension: length of time series x total number of time series)
        M: window size
        MC: Number of iteration in the Monte-Carlo process
        f: fraction (0<f<=1) of good data points for identifying
        significant PCs [f = 0.3]
        Output:
        deval : eigenvalue spectrum
        q05: The 5% percentile of eigenvalues
        q95: The 95% percentile of eigenvalues
        PC      : matrix of principal components
        RC      : matrix of RCs (nrec,N,nrec*M) (only if K>0)
        '''
        N = len(data[:, 0])
        nrec = len(data[0, :])
        Y = np.zeros((N - M + 1, nrec * M))
        for irec in np.arange(nrec):
            for m in np.arange(0, M):
                Y[:, m + irec * M] = data[m:N - M + 1 + m, irec]

        C = np.dot(np.nan_to_num(np.transpose(Y)), np.nan_to_num(Y)) / (N - M + 1)
        eig_val, eig_vec = eigh(C)

        sort_tmp = np.sort(eig_val)
        deval = sort_tmp[::-1]
        sortarg = np.argsort(-eig_val)

        eig_vec = eig_vec[:, sortarg]

        # test the signifiance using Monte-Carlo
        Ym = np.zeros((N - M + 1, nrec * M))
        noise = np.zeros((nrec, N, MC))
        for irec in np.arange(nrec):
            noise[irec, 0, :] = data[0, irec]
        Lamda_R = np.zeros((nrec * M, MC))
        # estimate coefficents of ar1 processes, and then generate ar1 time series (noise)
        for irec in np.arange(nrec):
            Xr = data[:, irec]
            coefs_est, var_est = alg.AR_est_YW(Xr[~np.isnan(Xr)], 1)
            sigma_est = np.sqrt(var_est)

            for jt in range(1, N):
                noise[irec, jt, :] = coefs_est * noise[irec, jt - 1, :] + sigma_est * np.random.randn(1, MC)

        for m in range(MC):
            for irec in np.arange(nrec):
                noise[irec, :, m] = (noise[irec, :, m] - np.mean(noise[irec, :, m])) / (
                    np.std(noise[irec, :, m], ddof=1))
                for im in np.arange(0, M):
                    Ym[:, im + irec * M] = noise[irec, im:N - M + 1 + im, m]
            Cn = np.dot(np.nan_to_num(np.transpose(Ym)), np.nan_to_num(Ym)) / (N - M + 1)
            # Lamda_R[:,m] = np.diag(np.dot(np.dot(eig_vec,Cn),np.transpose(eig_vec)))
            Lamda_R[:, m] = np.diag(np.dot(np.dot(np.transpose(eig_vec), Cn), eig_vec))

        q95 = np.percentile(Lamda_R, 95, axis=1)
        q05 = np.percentile(Lamda_R, 5, axis=1)


        # determine principal component time series
        PC = np.zeros((N - M + 1, nrec * M))
        PC[:, :] = np.nan
        for k in np.arange(nrec * M):
            for i in np.arange(0, N - M + 1):
                #   modify for nan
                prod = Y[i, :] * eig_vec[:, k]
                ngood = sum(~np.isnan(prod))
                #   must have at least m*f good points
                if ngood >= M * f:
                    PC[i, k] = sum(prod[~np.isnan(prod)])  # the columns of this matrix are Ak(t), k=1 to M (T-PCs)

        # compute reconstructed timeseries
        Np = N - M + 1

        RC = np.zeros((nrec, N, nrec * M))

        for k in np.arange(nrec):
            for im in np.arange(M):
                x2 = np.dot(np.expand_dims(PC[:, im], axis=1), np.expand_dims(eig_vec[0 + k * M:M + k * M, im], axis=0))
                x2 = np.flipud(x2)

                for n in np.arange(N):
                    RC[k, n, im] = np.diagonal(x2, offset=-(Np - 1 - n)).mean()

        return deval, eig_vec, q95, q05, PC, RC

    def ssa_all(self, data, M, MC=1000, f=0.3):
        '''SSA analysis for a time series
        (applicable for data including missing values)
        and test the significance by Monte-Carlo method
        Input:
        data: time series
        M: window size
        MC: Number of iteration in the Monte-Carlo process
        f: fraction (0<f<=1) of good data points for identifying
        significant PCs [f = 0.3]
        Output:
        deval : eigenvalue spectrum
        q05: The 5% percentile of eigenvalues
        q95: The 95% percentile of eigenvalues
        PC      : matrix of principal components
        RC      : matrix of RCs (N*M, nmode) (only if K>0)
        '''


        Xr = self.standardize(data)
        N = len(data)
        c = np.zeros(M)

        for j in range(M):
            prod = Xr[0:N - j] * Xr[j:N]
            c[j] = sum(prod[~np.isnan(prod)]) / (sum(~np.isnan(prod)) - 1)


        C = toeplitz(c[0:M])

        eig_val, eig_vec = eigh(C)

        sort_tmp = np.sort(eig_val)
        deval = sort_tmp[::-1]
        sortarg = np.argsort(-eig_val)

        eig_vec = eig_vec[:, sortarg]

        coefs_est, var_est = alg.AR_est_YW(Xr[~np.isnan(Xr)], 1)
        sigma_est = np.sqrt(var_est)

        noise = np.zeros((N, MC))
        noise[0, :] = Xr[0]
        Lamda_R = np.zeros((M, MC))

        for jt in range(1, N):
            noise[jt, :] = coefs_est * noise[jt - 1, :] + sigma_est * np.random.randn(1, MC)

        for m in range(MC):
            noise[:, m] = (noise[:, m] - np.mean(noise[:, m])) / (np.std(noise[:, m], ddof=1))
            Gn = np.correlate(noise[:, m], noise[:, m], "full")
            lgs = np.arange(-N + 1, N)
            Gn = Gn / (N - abs(lgs))
            Cn = toeplitz(Gn[N - 1:N - 1 + M])
            # Lamda_R[:,m] = np.diag(np.dot(np.dot(eig_vec,Cn),np.transpose(eig_vec)))
            Lamda_R[:, m] = np.diag(np.dot(np.dot(np.transpose(eig_vec), Cn), eig_vec))

        q95 = np.percentile(Lamda_R, 95, axis=1)
        q05 = np.percentile(Lamda_R, 5, axis=1)

        # determine principal component time series
        PC = np.zeros((N - M + 1, M))
        PC[:, :] = np.nan
        for k in np.arange(M):
            for i in np.arange(0, N - M + 1):
                #   modify for nan
                prod = Xr[i:i + M] * eig_vec[:, k]
                ngood = sum(~np.isnan(prod))
                #   must have at least m*f good points
                if ngood >= M * f:
                    PC[i, k] = sum(
                        prod[~np.isnan(prod)]) * M / ngood  # the columns of this matrix are Ak(t), k=1 to M (T-PCs)

        # compute reconstructed timeseries
        Np = N - M + 1

        RC = np.zeros((N, M))

        for im in np.arange(M):
            x2 = np.dot(np.expand_dims(PC[:, im], axis=1), np.expand_dims(eig_vec[0:M, im], axis=0))
            x2 = np.flipud(x2)

            for n in np.arange(N):
                RC[n, im] = np.diagonal(x2, offset=-(Np - 1 - n)).mean()

        return deval, eig_vec, q05, q95, PC, RC


def causality_est(y1, y2, method='liang', signif_test='isospec', nsim=1000,\
                  qs=[0.005, 0.025, 0.05, 0.95, 0.975, 0.995], **kwargs):
    '''Information flow

        Estimate the information transfer from series y2 to series y1

        Args:
            y1, y2 (array): vectors of (real) numbers with identical length, no NaNs allowed
            method (str): only "liang" for now
            signif_test (str): the method for significance test
            nsim (int): the number of AR(1) surrogates for significance test
            qs (list): the quantiles for significance test
            kwargs, includes:
                npt: the number of time advance in performing Euler forward differencing in "liang" method

        Returns:
            res_dict (dict): A dictionary with the following information:
                T21 (float) - The infor flow from y2 to y1
                tau21 (float) - the standardized info flow from y2 to y1, tau21 = T21/Z
                Z (float) - The total information flow
                qs (list) - the significance test quantile levels
                t21_noise (list) - the quantiles of the information flow from noise2 to noise1 for significance testing
                tau21_noise (list) - the quantiles of the standardized information flow from noise2 to noise1 for significance testing
    '''
    ca = Causality()
    if method == 'liang':
        npt = kwargs['npt'] if 'npt' in kwargs else 1
        res_dict = ca.liang_causality(y1, y2, npt=npt)
        tau21 = res_dict['tau21']
        T21 = res_dict['T21']
        Z = res_dict['Z']

        signif_test_func = {
            'isopersist': ca.signif_isopersist,
            'isospec': ca.signif_isospec,
        }

        signif_dict = signif_test_func[signif_test](y1, y2, nsim=nsim, qs=qs, npt=npt)

        T21_noise_qs = signif_dict['T21_noise_qs']
        tau21_noise_qs = signif_dict['tau21_noise_qs']
        res_dict = {
            'T21': T21,
            'tau21': tau21,
            'Z': Z,
            'signif_qs': qs,
            'T21_noise': T21_noise_qs,
            'tau21_noise': tau21_noise_qs,
        }
    else:
        raise KeyError(f'{method} is not a valid method')

    return res_dict


def binvalues(x, y, bin_size=None, start=None, end=None):
    """ Bin the values

    Args:
        x (array): the x-axis series.
        y (array): the y-axis series.
        bin_size (float): The size of the bins. Default is the average resolution
        start (float): Where/when to start binning. Default is the minimum
        end (float): When/where to stop binning. Defulat is the maximum

    Returns:
        binned_values - the binned output \n
        bins - the bins (centered on the median, i.e., the 100-200 bin is 150) \n
        n - number of data points in each bin \n
        error -  the standard error on the mean in each bin

    """

    # Make sure x and y are numpy arrays
    x = np.array(x, dtype='float64')
    y = np.array(y, dtype='float64')

    # Get the bin_size if not available
    if bin_size is None:
        bin_size = np.nanmean(np.diff(x))

    # Get the start/end if not given
    if start is None:
        start = np.nanmin(x)
    if end is None:
        end = np.nanmax(x)

    # Set the bin medians
    bins = np.arange(start+bin_size/2, end + bin_size/2, bin_size)

    # Perform the calculation
    binned_values = []
    n = []
    error = []
    for val in np.nditer(bins):
        idx = [idx for idx, c in enumerate(x) if c >= (val-bin_size/2) and c < (val+bin_size/2)]
        if y[idx].size == 0:
            binned_values.append(np.nan)
            n.append(np.nan)
            error.append(np.nan)
        else:
            binned_values.append(np.nanmean(y[idx]))
            n.append(y[idx].size)
            error.append(np.nanstd(y[idx]))

    return bins, binned_values, n, error


def interp(x,y,interp_step=None,start=None,end=None):
    """ Linear interpolation onto a new x-axis

    Args:
        x (array): the x-axis
        y (array): the y-axis
        interp_step (float): the interpolation step. Default is mean resolution.
        start (float): where/when to start the interpolation. Default is min..
        end (float): where/when to stop the interpolation. Default is max.

    Returns:
        xi - the interpolated x-axis \n
        interp_values - the interpolated values
        """

    #Make sure x and y are numpy arrays
    x = np.array(x,dtype='float64')
    y = np.array(y,dtype='float64')

    # get the interpolation step if not available
    if interp_step is None:
        interp_step = np.nanmean(np.diff(x))

    # Get the start and end point if not given
    if start is None:
        start = np.nanmin(np.asarray(x))
    if end is None:
        end = np.nanmax(np.asarray(x))

    # Get the interpolated x-axis.
    xi = np.arange(start,end,interp_step)

    #Make sure the data is increasing
    data = pd.DataFrame({"x-axis": x, "y-axis": y}).sort_values('x-axis')

    interp_values = np.interp(xi,data['x-axis'],data['y-axis'])

    return xi, interp_values


def onCommonAxis(x1, y1, x2, y2, method = 'interpolation', step=None, start=None, end=None):
    """Places two timeseries on a common axis

    Args:
        x1 (array): x-axis values of the first timeseries
        y1 (array): y-axis values of the first timeseries
        x2 (array): x-axis values of the second timeseries
        y2 (array): y-axis values of the second timeseries
        method (str): Which method to use to get the timeseries on the same x axis.
            Valid entries: 'interpolation' (default), 'bin', 'None'. 'None' only
            cuts the timeseries to the common period but does not attempt
            to generate a common time axis
        step (float): The interpolation step. Default is mean resolution
        of lowest resolution series
        start (float): where/when to start. Default is the maximum of the minima of
        the two timeseries
        end (float): Where/when to end. Default is the minimum of the maxima of
        the two timeseries

    Returns:
        xi1, xi2 -  the interpolated x-axis \n
        interp_values1, interp_values2 -  the interpolated y-values
        """



    # make sure that x1, y1, x2, y2 are numpy arrays
    x1 = np.array(x1, dtype='float64')
    y1 = np.array(y1, dtype='float64')
    x2 = np.array(x2, dtype='float64')
    y2 = np.array(y2, dtype='float64')

    # Find the mean/max x-axis is not provided
    if start is None:
        start = np.nanmax([np.nanmin(x1), np.nanmin(x2)])
    if end is None:
        end = np.nanmin([np.nanmax(x1), np.nanmax(x2)])

    # Get the interp_step
    if step is None:
        step = np.nanmin([np.nanmean(np.diff(x1)), np.nanmean(np.diff(x2))])

    if method == 'interpolation':
    # perform the interpolation
        xi1, interp_values1 = interp(x1, y1, interp_step=step, start=start,
                                end=end)
        xi2, interp_values2 = interp(x2, y2, interp_step=step, start=start,
                                end=end)
    elif method == 'bin':
        xi1, interp_values1, n, error = binvalues(x1, y1, bin_size=step, start=start,
                                end=end)
        xi2, interp_values2, n, error = binvalues(x2, y2, bin_size=step, start=start,
                                end=end)
    elif method == None:
        min_idx1 = np.where(x1>=start)[0][0]
        min_idx2 = np.where(x2>=start)[0][0]
        max_idx1 = np.where(x1<=end)[0][-1]
        max_idx2 = np.where(x2<=end)[0][-1]

        xi1 = x1[min_idx1:max_idx1+1]
        xi2 = x2[min_idx2:max_idx2+1]
        interp_values1 = y1[min_idx1:max_idx1+1]
        interp_values2 = y2[min_idx2:max_idx2+1]

    else:
        raise KeyError('Not a valid interpolation method')

    return xi1, xi2, interp_values1, interp_values2


def standardize(x, scale=1, axis=0, ddof=0, eps=1e-3):
    """ Centers and normalizes a given time series. Constant or nearly constant time series not rescaled.

    Args:
        x (array): vector of (real) numbers as a time series, NaNs allowed
        scale (real): a scale factor used to scale a record to a match a given variance
        axis (int or None): axis along which to operate, if None, compute over the whole array
        ddof (int): degress of freedom correction in the calculation of the standard deviation
        eps (real): a threshold to determine if the standard deviation is too close to zero

    Returns:
        z (array): the standardized time series (z-score), Z = (X - E[X])/std(X)*scale, NaNs allowed
        mu (real): the mean of the original time series, E[X]
        sig (real): the standard deviation of the original time series, std[X]

    References:
        1. Tapio Schneider's MATLAB code: http://www.clidyn.ethz.ch/imputation/standardize.m
        2. The zscore function in SciPy: https://github.com/scipy/scipy/blob/master/scipy/stats/stats.py

    @author: fzhu
    """
    x = np.asanyarray(x)
    assert x.ndim <= 2, 'The time series x should be a vector or 2-D array!'

    mu = np.nanmean(x, axis=axis)  # the mean of the original time series
    sig = np.nanstd(x, axis=axis, ddof=ddof)  # the std of the original time series

    mu2 = np.asarray(np.copy(mu))  # the mean used in the calculation of zscore
    sig2 = np.asarray(np.copy(sig) / scale)  # the std used in the calculation of zscore

    if np.any(np.abs(sig) < eps):  # check if x contains (nearly) constant time series
        warnings.warn('Constant or nearly constant time series not rescaled.')
        where_const = np.abs(sig) < eps  # find out where we have (nearly) constant time series

        # if a vector is (nearly) constant, keep it the same as original, i.e., substract by 0 and divide by 1.
        mu2[where_const] = 0
        sig2[where_const] = 1

    if axis and mu.ndim < x.ndim:
        z = (x - np.expand_dims(mu2, axis=axis)) / np.expand_dims(sig2, axis=axis)
    else:
        z = (x - mu2) / sig2

    return z, mu, sig


def ts2segments(ys, ts, factor=10):
    ''' Chop a time series into several segments based on gap detection.

    The rule of gap detection is very simple:
        we define the intervals between time points as dts, then if dts[i] is larger than factor * dts[i-1],
        we think that the change of dts (or the gradient) is too large, and we regard it as a breaking point
        and chop the time series into two segments here

    Args:
        ys (array): a time series, NaNs allowed
        ts (array): the time points
        factor (float): the factor that adjusts the threshold for gap detection

    Returns:
        seg_ys (list): a list of several segments with potentially different lengths
        seg_ts (list): a list of the time axis of the several segments
        n_segs (int): the number of segments

    @author: fzhu
    '''

    ys, ts = clean_ts(ys, ts)

    nt = np.size(ts)
    dts = np.diff(ts)

    seg_ys, seg_ts = [], []  # store the segments with lists

    n_segs = 1
    i_start = 0
    for i in range(1, nt-1):
        if np.abs(dts[i]) > factor*np.abs(dts[i-1]):
            i_end = i + 1
            seg_ys.append(ys[i_start:i_end])
            seg_ts.append(ts[i_start:i_end])
            i_start = np.copy(i_end)
            n_segs += 1

    seg_ys.append(ys[i_start:nt])
    seg_ts.append(ts[i_start:nt])

    return seg_ys, seg_ts, n_segs


def clean_ts(ys, ts):
    ''' Delete the NaNs in the time series and sort it with time axis ascending

    Args:
        ys (array): a time series, NaNs allowed
        ts (array): the time axis of the time series, NaNs allowed

    Returns:
        ys (array): the time series without nans
        ts (array): the time axis of the time series without nans

    '''
    # delete NaNs if there is any
    ys = np.asarray(ys, dtype=np.float)
    ts = np.asarray(ts, dtype=np.float)
    assert ys.size == ts.size, 'The size of time axis and data value should be equal!'

    ys_tmp = np.copy(ys)
    ys = ys[~np.isnan(ys_tmp)]
    ts = ts[~np.isnan(ys_tmp)]
    ts_tmp = np.copy(ts)
    ys = ys[~np.isnan(ts_tmp)]
    ts = ts[~np.isnan(ts_tmp)]

    # sort the time series so that the time axis will be ascending
    sort_ind = np.argsort(ts)
    ys = ys[sort_ind]
    ts = ts[sort_ind]

    return ys, ts


def annualize(ys, ts):
    ''' Annualize a time series whose time resolution is finer than 1 year

    Args:
        ys (array): a time series, NaNs allowed
        ts (array): the time axis of the time series, NaNs allowed

    Returns:
        ys_ann (array): the annualized time series
        year_int (array): the time axis of the annualized time series

    '''
    year_int = list(set(np.floor(ts)))
    year_int = np.sort(list(map(int, year_int)))
    n_year = len(year_int)
    year_int_pad = list(year_int)
    year_int_pad.append(np.max(year_int)+1)
    ys_ann = np.zeros(n_year)

    for i in range(n_year):
        t_start = year_int_pad[i]
        t_end = year_int_pad[i+1]
        t_range = (ts >= t_start) & (ts < t_end)
        ys_ann[i] = np.average(ys[t_range], axis=0)

    return ys_ann, year_int


def gaussianize(X):
    """ Transforms a (proxy) timeseries to Gaussian distribution.

    Originator: Michael Erb, Univ. of Southern California - April 2017
    """

    # Give every record at least one dimensions, or else the code will crash.
    X = np.atleast_1d(X)

    # Make a blank copy of the array, retaining the data type of the original data variable.
    Xn = copy.deepcopy(X)
    Xn[:] = np.NAN

    if len(X.shape) == 1:
        Xn = gaussianize_single(X)
    else:
        for i in range(X.shape[1]):
            Xn[:, i] = gaussianize_single(X[:, i])

    return Xn


def gaussianize_single(X_single):
    """ Transforms a single (proxy) timeseries to Gaussian distribution.

    Originator: Michael Erb, Univ. of Southern California - April 2017
    """
    # Count only elements with data.

    n = X_single[~np.isnan(X_single)].shape[0]

    # Create a blank copy of the array.
    Xn_single = copy.deepcopy(X_single)
    Xn_single[:] = np.NAN

    nz = np.logical_not(np.isnan(X_single))
    index = np.argsort(X_single[nz])
    rank = np.argsort(index)
    CDF = 1.*(rank+1)/(1.*n) - 1./(2*n)
    Xn_single[nz] = np.sqrt(2)*special.erfinv(2*CDF - 1)

    return Xn_single


def detrend(y, x = None, method = "hht", params = ["default",4,0,1], SNR_threshold=0.4, extreme_pts_threshold=3, verbose=False):
    """Detrend a timeseries according to three methods

    Detrending methods include, "linear", "constant", and using a low-pass
        Savitzky-Golay filters (default).

    Args:
        y (array): The series to be detrended.
        x (array): The time axis for the timeseries. Necessary for use with
            the Savitzky-Golay filters method since the series should be evenly spaced.
        method (str): The type of detrending. If linear (default), the result of
            a linear least-squares fit to y is subtracted from y. If constant,
            only the mean of data is subtrated. If "savitzy-golay", y is filtered
            using the Savitzky-Golay filters and the resulting filtered series
            is subtracted from y.
        params (list): The paramters for the Savitzky-Golay filters. The first parameter
            corresponds to the window size (default it set to half of the data)
            while the second parameter correspond to the order of the filter
            (default is 4). The third parameter is the order of the derivative
            (the default is zero, which means only smoothing.)

    Returns:
        ys (array) - the detrended timeseries.
    """
    y = np.array(y)

    if x is not None:
        x = np.array(x)

    if method == "linear":
        ys = signal.detrend(y,type='linear')
    elif method == 'constant':
        ys = signal.detrend(y,type='constant')
    elif method == "savitzy-golay":
        # Check that the timeseries is uneven and interpolate if needed
        if x is None:
            sys.exit("A time axis is needed for use with the Savitzky-Golay filters method")
        # Check whether the timeseries is unvenly-spaced and interpolate if needed
        if len(np.unique(np.diff(x)))>1:
            warnings.warn("Timeseries is not evenly-spaced, interpolating...")
            interp_step = np.nanmean(np.diff(x))
            start = np.nanmin(x)
            end = np.nanmax(x)
            x_interp, y_interp = interp(x,y,interp_step=interp_step,\
                                             start=start,end=end)
        else:
            x_interp = x
            y_interp = y
        if params[0] == "default":
            l = len(y) # Use the length of the timeseries for the window side
            l = np.ceil(l)//2*2+1 # Make sure this is an odd number
            l = int(l) # Make sure that the type is int
            o = int(params[1]) # Make sure the order is type int
            d = int(params[2])
            e = int(params[3])
        else:
            #Assume the users know what s/he is doing and just force to type int
            l = int(params[0])
            o = int(params[1])
            d = int(params[2])
            e = int(params[3])
        # Now filter
        y_filt = Spectral.Filter.savitzky_golay(y_interp,l,o,d,e)
        # Put it all back on the original x axis
        y_filt_x = np.interp(x,x_interp,y_filt)
        ys = y-y_filt_x
    elif method == "hht":
        imfs = EMD(y).decompose()
        trend = imfs[-1]
        ys = y - trend
    else:
        raise KeyError('Not a valid detrending method')

    return ys

