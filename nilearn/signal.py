"""
Preprocessing functions for time series.

All functions in this module should take X matrices with samples x
features
"""
# Authors: Alexandre Abraham, Gael Varoquaux, Philippe Gervais
# License: simplified BSD

import warnings

import numpy as np
import pandas as pd
from scipy import linalg, signal as sp_signal
from scipy.interpolate import CubicSpline
from sklearn.utils import gen_even_slices, as_float_array

from ._utils.numpy_conversions import csv_to_array, as_ndarray
from ._utils import fill_doc
from nilearn._utils.glm import _check_run_sample_masks
from ._utils import stringify_path

availiable_filters = ['butterworth',
                      'cosine'
                      ]


def _standardize(signals, detrend=False, standardize='zscore'):
    """Center and standardize a given signal (time is along first axis).

    Parameters
    ----------
    signals : :class:`numpy.ndarray`
        Timeseries to standardize.

    detrend : :obj:`bool`, optional
        If detrending of timeseries is requested.
        Default=False.

    standardize : {'zscore', 'psc', True, False}, optional
        Strategy to standardize the signal:

            - 'zscore': The signal is z-scored. Timeseries are shifted
              to zero mean and scaled to unit variance.
            - 'psc':  Timeseries are shifted to zero mean value and scaled
              to percent signal change (as compared to original mean signal).
            - True: The signal is z-scored (same as option `zscore`).
              Timeseries are shifted to zero mean and scaled to unit variance.
            - False: Do not standardize the data.

        Default='zscore'.

    Returns
    -------
    std_signals : :class:`numpy.ndarray`
        Copy of signals, standardized.
    """
    if standardize not in [True, False, 'psc', 'zscore']:
        raise ValueError('{} is no valid standardize strategy.'
                         .format(standardize))

    if detrend:
        signals = _detrend(signals, inplace=False)
    else:
        signals = signals.copy()

    if standardize:
        if signals.shape[0] == 1:
            warnings.warn('Standardization of 3D signal has been requested but '
                          'would lead to zero values. Skipping.')
            return signals

        elif (standardize == 'zscore') or (standardize is True):
            if not detrend:
                # remove mean if not already detrended
                signals = signals - signals.mean(axis=0)

            std = signals.std(axis=0)
            std[std < np.finfo(np.float64).eps] = 1.  # avoid numerical problems
            signals /= std

        elif standardize == 'psc':
            mean_signal = signals.mean(axis=0)
            invalid_ix = np.absolute(mean_signal) < np.finfo(np.float64).eps
            signals = (signals - mean_signal) / np.absolute(mean_signal)
            signals *= 100

            if np.any(invalid_ix):
                warnings.warn('psc standardization strategy is meaningless '
                              'for features that have a mean of 0. '
                              'These time series are set to 0.')
                signals[:, invalid_ix] = 0

    return signals


def _mean_of_squares(signals, n_batches=20):
    """Compute mean of squares for each signal.

    This function is equivalent to:

    .. code-block:: python

        var = np.copy(signals)
        var **= 2
        var = var.mean(axis=0)

    but uses a lot less memory.

    Parameters
    ----------
    signals : :class:`numpy.ndarray`, shape (n_samples, n_features)
        Signal whose mean of squares must be computed.

    n_batches : :obj:`int`, optional
        Number of batches to use in the computation.

        .. note::
            Tweaking this value can lead to variation of memory usage
            and computation time. The higher the value, the lower the
            memory consumption.

        Default=20.

    Returns
    -------
    var : :class:`numpy.ndarray`
        1D array holding the mean of squares.
    """
    # No batching for small arrays
    if signals.shape[1] < 500:
        n_batches = 1

    # Fastest for C order
    var = np.empty(signals.shape[1])
    for batch in gen_even_slices(signals.shape[1], n_batches):
        tvar = np.copy(signals[:, batch])
        tvar **= 2
        var[batch] = tvar.mean(axis=0)

    return var


def _row_sum_of_squares(signals, n_batches=20):
    """Compute sum of squares for each signal.

    This function is equivalent to:

    .. code-block:: python

        signals **= 2
        signals = signals.sum(axis=0)

    but uses a lot less memory.

    Parameters
    ----------
    signals : :class:`numpy.ndarray`, shape (n_samples, n_features)
        Signal whose sum of squares must be computed.

    n_batches : :obj:`int`, optional
        Number of batches to use in the computation.

        .. note::
            Tweaking this value can lead to variation of memory usage
            and computation time. The higher the value, the lower the
            memory consumption.

        Default=20.

    Returns
    -------
    var : :class:`numpy.ndarray`
        1D array holding the sum of squares.
    """
    # No batching for small arrays
    if signals.shape[1] < 500:
        n_batches = 1

    # Fastest for C order
    var = np.empty(signals.shape[1])
    for batch in gen_even_slices(signals.shape[1], n_batches):
        var[batch] = np.sum(signals[:, batch] ** 2, 0)

    return var


def _detrend(signals, inplace=False, type="linear", n_batches=10):
    """Detrend columns of input array.

    Signals are supposed to be columns of `signals`.
    This function is significantly faster than :func:`scipy.signal.detrend`
    on this case and uses a lot less memory.

    Parameters
    ----------
    signals : :class:`numpy.ndarray`
        This parameter must be two-dimensional.
        Signals to detrend. A signal is a column.

    inplace : :obj:`bool`, optional
        Tells if the computation must be made inplace or not.
        Default=False.

    type : {"linear", "constant"}, optional
        Detrending type, either "linear" or "constant".
        See also :func:`scipy.signal.detrend`.
        Default="linear".

    n_batches : :obj:`int`, optional
        Number of batches to use in the computation.

        .. note::
            Tweaking this value can lead to variation of memory usage
            and computation time. The higher the value, the lower the
            memory consumption.

    Returns
    -------
    detrended_signals : :class:`numpy.ndarray`
        Detrended signals. The shape is that of ``signals``.

    Notes
    -----
    If a signal of length 1 is given, it is returned unchanged.
    """
    signals = as_float_array(signals, copy=not inplace)
    if signals.shape[0] == 1:
        warnings.warn('Detrending of 3D signal has been requested but '
                      'would lead to zero values. Skipping.')
        return signals

    signals -= np.mean(signals, axis=0)
    if type == "linear":
        # Keeping "signals" dtype avoids some type conversion further down,
        # and can save a lot of memory if dtype is single-precision.
        regressor = np.arange(signals.shape[0], dtype=signals.dtype)
        regressor -= regressor.mean()
        std = np.sqrt((regressor ** 2).sum())
        # avoid numerical problems
        if not std < np.finfo(np.float64).eps:
            regressor /= std
        regressor = regressor[:, np.newaxis]

        # No batching for small arrays
        if signals.shape[1] < 500:
            n_batches = 1

        # This is fastest for C order.
        for batch in gen_even_slices(signals.shape[1], n_batches):
            signals[:, batch] -= np.dot(regressor[:, 0], signals[:, batch]
                                        ) * regressor
    return signals


def _check_wn(btype, freq, nyq):
    wn = freq / float(nyq)
    if wn >= 1.:
        # results looked unstable when the critical frequencies are
        # exactly at the Nyquist frequency. See issue at SciPy
        # https://github.com/scipy/scipy/issues/6265. Before, SciPy 1.0.0 ("wn
        # should be btw 0 and 1"). But, after ("0 < wn < 1"). Due to unstable
        # results as pointed in the issue above. Hence, we forced the
        # critical frequencies to be slightly less than 1. but not 1.
        wn = 1 - 10 * np.finfo(1.).eps
        warnings.warn(
            'The frequency specified for the %s pass filter is '
            'too high to be handled by a digital filter (superior to '
            'nyquist frequency). It has been lowered to %.2f (nyquist '
            'frequency).' % (btype, wn))

    if wn < 0.0: # equal to 0.0 is okay
        wn = np.finfo(1.).eps
        warnings.warn(
            'The frequency specified for the %s pass filter is '
            'too low to be handled by a digital filter (must be non-negative).'
            ' It has been set to eps: %.5e' % (btype, wn))

    return wn


@fill_doc
def butterworth(signals, sampling_rate, low_pass=None, high_pass=None,
                order=5, copy=False):
    """Apply a low-pass, high-pass or band-pass
    `Butterworth filter <https://en.wikipedia.org/wiki/Butterworth_filter>`_.

    Apply a filter to remove signal below the `low` frequency and above the
    `high` frequency.

    Parameters
    ----------
    signals : :class:`numpy.ndarray` (1D sequence or n_samples x n_sources)
        Signals to be filtered. A signal is assumed to be a column
        of `signals`.

    sampling_rate : :obj:`float`
        Number of samples per time unit (sample frequency).
    %(low_pass)s
    %(high_pass)s
    order : :obj:`int`, optional
        Order of the `Butterworth filter
        <https://en.wikipedia.org/wiki/Butterworth_filter>`_.
        When filtering signals, the filter has a decay to avoid ringing.
        Increasing the order sharpens this decay. Be aware that very high
        orders can lead to numerical instability.
        Default=5.

    copy : :obj:`bool`, optional
        If False, `signals` is modified inplace, and memory consumption is
        lower than for ``copy=True``, though computation time is higher.

    Returns
    -------
    filtered_signals : :class:`numpy.ndarray`
        Signals filtered according to the given parameters.
    """
    if low_pass is None and high_pass is None:
        if copy:
            return signals.copy()
        else:
            return signals

    if low_pass is not None and high_pass is not None \
            and high_pass >= low_pass:
        raise ValueError(
            "High pass cutoff frequency (%f) is greater or equal"
            "to low pass filter frequency (%f). This case is not handled "
            "by this function."
            % (high_pass, low_pass))

    nyq = sampling_rate * 0.5

    critical_freq = []
    if high_pass is not None:
        btype = 'high'
        critical_freq.append(_check_wn(btype, high_pass, nyq))

    if low_pass is not None:
        btype = 'low'
        critical_freq.append(_check_wn(btype, low_pass, nyq))

    if len(critical_freq) == 2:
        btype = 'band'
        # Inappropriate parameter input might lead to coercion of both
        # elements of critical_freq to a value just below 1.
        # Scipy fix now enforces that critical frequencies cannot be equal.
        # See https://github.com/scipy/scipy/pull/15886. If this is the case,
        # we return the signals unfiltered.
        if critical_freq[0] == critical_freq[1]:
            warnings.warn(
                'Signals are returned unfiltered because band-pass critical '
                'frequencies are equal. Please check that inputs for '
                'sampling_rate, low_pass, and high_pass are valid.')
            if copy:
                return signals.copy()
            else:
                return signals
    else:
        critical_freq = critical_freq[0]

    b, a = sp_signal.butter(order, critical_freq, btype=btype, output='ba')
    if signals.ndim == 1:
        # 1D case
        output = sp_signal.filtfilt(b, a, signals)
        if copy:  # filtfilt does a copy in all cases.
            signals = output
        else:
            signals[...] = output
    else:
        if copy:
            # No way to save memory when a copy has been requested,
            # because filtfilt does out-of-place processing
            signals = sp_signal.filtfilt(b, a, signals, axis=0)
        else:
            # Lesser memory consumption, slower.
            for timeseries in signals.T:
                timeseries[:] = sp_signal.filtfilt(b, a, timeseries)

            # results returned in-place

    return signals


@fill_doc
def high_variance_confounds(series, n_confounds=5, percentile=2.,
                            detrend=True):
    """Return confounds time series extracted from series with highest
    variance.

    Parameters
    ----------
    series : :class:`numpy.ndarray`
        Timeseries. A timeseries is a column in the "series" array.
        shape (sample number, feature number)

    n_confounds : :obj:`int`, optional
        Number of confounds to return. Default=5.

    percentile : :obj:`float`, optional
        Highest-variance series percentile to keep before computing the
        singular value decomposition, 0. <= `percentile` <= 100.
        ``series.shape[0] * percentile / 100`` must be greater
        than ``n_confounds``. Default=2.0.
    %(detrend)s
        Default=True.

    Returns
    -------
    v : :class:`numpy.ndarray`
        Highest variance confounds. Shape: (samples, n_confounds)

    Notes
    -----
    This method is related to what has been published in the literature
    as 'CompCor' :footcite:`Behzadi2007`.

    The implemented algorithm does the following:

    - compute sum of squares for each time series (no mean removal)
    - keep a given percentile of series with highest variances (percentile)
    - compute an svd of the extracted series
    - return a given number (n_confounds) of series from the svd with
      highest singular values.

    References
    ----------
    .. footbibliography::

    See also
    --------
    nilearn.image.high_variance_confounds
    """
    if detrend:
        series = _detrend(series)  # copy

    # Retrieve the voxels|features with highest variance

    # Compute variance without mean removal.
    var = _mean_of_squares(series)
    var_thr = np.nanpercentile(var, 100. - percentile)
    series = series[:, var > var_thr]  # extract columns (i.e. features)
    # Return the singular vectors with largest singular values
    # We solve the symmetric eigenvalue problem here, increasing stability
    s, u = linalg.eigh(series.dot(series.T) / series.shape[0])
    ix_ = np.argsort(s)[::-1]
    u = u[:, ix_[:n_confounds]].copy()
    return u


def _ensure_float(data):
    "Make sure that data is a float type"
    if not data.dtype.kind == 'f':
        if data.dtype.itemsize == '8':
            data = data.astype(np.float64)
        else:
            data = data.astype(np.float32)
    return data


@fill_doc
def clean(signals, runs=None, detrend=True, standardize='zscore',
          sample_mask=None, confounds=None, standardize_confounds=True,
          filter='butterworth', low_pass=None, high_pass=None, t_r=2.5,
          ensure_finite=False):
    """Improve :term:`SNR` on masked :term:`fMRI` signals.

    This function can do several things on the input signals. With the default
    options, the procedures are performed in the following order:

    - detrend
    - low- and high-pass butterworth filter
    - remove confounds
    - standardize

    Low-pass filtering improves specificity.

    High-pass filtering should be kept small, to keep some sensitivity.

    Butterworth filtering is only meaningful on evenly-sampled signals.

    When performing scrubbing (censoring high-motion volumes) with butterworth
    filtering, the signal is processed in the following order, based on the
    second recommendation in :footcite:`Lindquist2018`:

    - interpolate high motion volumes with cubic spline interpolation
    - detrend
    - low- and high-pass butterworth filter
    - censor high motion volumes
    - remove confounds
    - standardize

    According to :footcite:`Lindquist2018`, removal of confounds will be done
    orthogonally to temporal filters (low- and/or high-pass filters), if both
    are specified. The censored volumes should be removed in both signals and
    confounds before the nuisance regression.

    When performing scrubbing with cosine drift term filtering, the signal is
    processed in the following order, based on the first recommendation in
    :footcite:`Lindquist2018`:

    - generate cosine drift term
    - censor high motion volumes in both signal and confounds
    - detrend
    - remove confounds
    - standardize

    Parameters
    ----------
    signals : :class:`numpy.ndarray`
        Timeseries. Must have shape (instant number, features number).
        This array is not modified.

    runs : :class:`numpy.ndarray`, optional
        Add a run level to the cleaning process. Each run will be
        cleaned independently. Must be a 1D array of n_samples elements.
        Default is None.

    confounds : :class:`numpy.ndarray`, :obj:`str`, :class:`pathlib.Path`,\
    :class:`pandas.DataFrame` or :obj:`list` of confounds timeseries.
        Shape must be (instant number, confound number), or just
        (instant number,).
        The number of time instants in ``signals`` and ``confounds`` must be
        identical (i.e. ``signals.shape[0] == confounds.shape[0]``).
        If a string is provided, it is assumed to be the name of a csv file
        containing signals as columns, with an optional one-line header.
        If a list is provided, all confounds are removed from the input
        signal, as if all were in the same array.
        Default is None.

    sample_mask : None, :class:`numpy.ndarray`, :obj:`list`,\
    :obj:`tuple`, or :obj:`list` of
        shape: (number of scans - number of volumes removed, )
        Masks the niimgs along time/fourth dimension to perform scrubbing
        (remove volumes with high motion) and/or non-steady-state volumes.
        This masking step is applied before signal cleaning. When supplying run
        information, sample_mask must be a list containing sets of indexes for
        each run.

            .. versionadded:: 0.8.0

        Default is None.
    %(t_r)s
        Default=2.5.
    filter : {'butterworth', 'cosine', False}, optional
        Filtering methods:

            - 'butterworth': perform butterworth filtering.
            - 'cosine': generate discrete cosine transformation drift terms.
            - False: Do not perform filtering.

        Default='butterworth'.
    %(low_pass)s

        .. note::
            `low_pass` is not implemented for filter='cosine'.

    %(high_pass)s
    %(detrend)s
    standardize : {'zscore', 'psc', False}, optional
        Strategy to standardize the signal:

            - 'zscore': The signal is z-scored. Timeseries are shifted
              to zero mean and scaled to unit variance.
            - 'psc':  Timeseries are shifted to zero mean value and scaled
              to percent signal change (as compared to original mean signal).
            - True: The signal is z-scored (same as option `zscore`).
              Timeseries are shifted to zero mean and scaled to unit variance.
            - False: Do not standardize the data.

        Default="zscore".
    %(standardize_confounds)s
    %(ensure_finite)s
        Default=False.

    Returns
    -------
    cleaned_signals : :class:`numpy.ndarray`
        Input signals, cleaned. Same shape as `signals` unless `sample_mask`
        is applied.

    Notes
    -----
    Confounds removal is based on a projection on the orthogonal
    of the signal space. See :footcite:`Friston1994`.

    Orthogonalization between temporal filters and confound removal is based on
    suggestions in :footcite:`Lindquist2018`.

    References
    ----------
    .. footbibliography::

    See Also
    --------
    nilearn.image.clean_img
    """
    # Raise warning for some parameter combinations when confounds present
    confounds = stringify_path(confounds)
    if confounds is not None:
        _check_signal_parameters(detrend, standardize_confounds)
    # check if filter parameters are satisfied and return correct filter
    filter_type = _check_filter_parameters(filter, low_pass, high_pass, t_r)

    # Read confounds and signals
    signals, runs, confounds, sample_mask = _sanitize_inputs(
        signals, runs, confounds, sample_mask, ensure_finite
    )

    # Process each run independently
    if runs is not None:
        return _process_runs(signals, runs, detrend, standardize,
                             confounds, sample_mask,
                             filter_type, low_pass, high_pass, t_r)

    # For the following steps, sample_mask should be either None or index-like

    # Generate cosine drift terms using the full length of the signals
    if filter_type == 'cosine':
        confounds = _create_cosine_drift_terms(signals, confounds, high_pass,
                                               t_r)

    # Interpolation / censoring
    signals, confounds = _handle_scrubbed_volumes(signals, confounds,
                                                  sample_mask, filter_type,
                                                  t_r)

    # Detrend
    # Detrend and filtering should apply to confounds, if confound presents
    # keep filters orthogonal (according to Lindquist et al. (2018))
    # Restrict the signal to the orthogonal of the confounds
    if detrend:
        mean_signals = signals.mean(axis=0)
        signals = _standardize(signals, standardize=False, detrend=detrend)
        if confounds is not None:
            confounds = _standardize(confounds, standardize=False,
                                     detrend=detrend)

    # Butterworth filtering
    if filter_type == 'butterworth':
        signals = butterworth(signals, sampling_rate=1. / t_r,
                              low_pass=low_pass, high_pass=high_pass)
        if confounds is not None:
            # Apply low- and high-pass filters to keep filters orthogonal
            # (according to Lindquist et al. (2018))
            confounds = butterworth(confounds, sampling_rate=1. / t_r,
                                    low_pass=low_pass, high_pass=high_pass)
        # apply sample_mask to remove censored volumes after signal filtering
        if sample_mask is not None:
            signals, confounds = _censor_signals(signals, confounds,
                                                 sample_mask)

    # Remove confounds
    if confounds is not None:
        confounds = _standardize(confounds, standardize=standardize_confounds,
                                 detrend=False)
        if not standardize_confounds:
            # Improve numerical stability by controlling the range of
            # confounds. We don't rely on _standardize as it removes any
            # constant contribution to confounds.
            confound_max = np.max(np.abs(confounds), axis=0)
            confound_max[confound_max == 0] = 1
            confounds /= confound_max

        # Pivoting in qr decomposition was added in scipy 0.10
        Q, R, _ = linalg.qr(confounds, mode='economic', pivoting=True)
        Q = Q[:, np.abs(np.diag(R)) > np.finfo(np.float64).eps * 100.]
        signals -= Q.dot(Q.T).dot(signals)

    # Standardize
    if detrend and (standardize == 'psc'):
        # If the signal is detrended, we have to know the original mean
        # signal to calculate the psc.
        signals = _standardize(signals + mean_signals, standardize=standardize,
                               detrend=False)
    else:
        signals = _standardize(signals, standardize=standardize,
                               detrend=False)

    return signals


def _handle_scrubbed_volumes(signals, confounds, sample_mask, filter_type,
                             t_r):
    """Interpolate or censor scrubbed volumes."""
    if sample_mask is None:
        return signals, confounds

    if filter_type == 'butterworth':
        signals = _interpolate_volumes(signals, sample_mask, t_r)
        if confounds is not None:
            confounds = _interpolate_volumes(confounds, sample_mask, t_r)
    else:  # Or censor when no filtering, or cosine filter
        signals, confounds = _censor_signals(signals, confounds, sample_mask)
    return signals, confounds


def _censor_signals(signals, confounds, sample_mask):
    """Apply sample masks to data."""
    signals = signals[sample_mask, :]
    if confounds is not None:
        confounds = confounds[sample_mask, :]
    return signals, confounds


def _interpolate_volumes(volumes, sample_mask, t_r):
    """Interpolate censored volumes in signals/confounds."""
    frame_times = np.arange(volumes.shape[0]) * t_r
    remained_vol = frame_times[sample_mask]
    remained_x = volumes[sample_mask, :]
    cubic_spline_fitter = CubicSpline(remained_vol, remained_x)
    volumes_interpolated = cubic_spline_fitter(frame_times)
    volumes[~sample_mask, :] = volumes_interpolated[~sample_mask, :]
    return volumes


def _create_cosine_drift_terms(signals, confounds, high_pass, t_r):
    """Create cosine drift terms, append to confounds regressors."""
    from nilearn.glm.first_level.design_matrix import _cosine_drift
    frame_times = np.arange(signals.shape[0]) * t_r
    # remove constant, as the signal is mean centered
    cosine_drift = _cosine_drift(high_pass, frame_times)[:, :-1]
    confounds = _check_cosine_by_user(confounds, cosine_drift)
    return confounds


def _check_cosine_by_user(confounds, cosine_drift):
    """Check if cosine term exists, based on correlation > 0.9. """
    # stack consine drift terms if there's no cosine drift term in data
    n_cosines = cosine_drift.shape[1]

    if n_cosines == 0:
        warnings.warn(
            "Cosine filter was not created. The time series might be too "
            "short or the high pass filter is not suitable for the data."
        )
        return confounds

    if confounds is None:
        return cosine_drift.copy()

    # check if cosine drift term is supplied by user
    # given the threshold and timeseries length, there can be no cosine drift
    # term
    corr_cosine = np.corrcoef(cosine_drift.T, confounds.T)
    np.fill_diagonal(corr_cosine, 0)
    cosine_exists = sum(corr_cosine[:n_cosines, :].flatten() > 0.9) > 0

    if cosine_exists:
        warnings.warn(
            "Cosine filter(s) exist in user supplied confounds."
            "Use user supplied regressors only."
        )
        return confounds

    return np.hstack((confounds, cosine_drift))


def _process_runs(signals, runs, detrend, standardize, confounds, sample_mask,
                  filter, low_pass, high_pass, t_r):
    """Process each run independently."""
    if len(runs) != len(signals):
        raise ValueError(
            (
                'The length of the run vector (%i) '
                'does not match the length of the signals (%i)'
            ) % (len(runs), len(signals))
        )
    cleaned_signals = []
    for i, run in enumerate(np.unique(runs)):
        run_confounds = None
        run_sample_mask = None
        if confounds is not None:
            run_confounds = confounds[runs == run]
        if sample_mask is not None:
            run_sample_mask = sample_mask[i]
        run_signals = \
            clean(signals[runs == run],
                  detrend=detrend, standardize=standardize,
                  confounds=run_confounds, sample_mask=run_sample_mask,
                  filter=filter, low_pass=low_pass,
                  high_pass=high_pass, t_r=t_r)
        cleaned_signals.append(run_signals)
    return np.vstack(cleaned_signals)


def _sanitize_inputs(signals, runs, confounds, sample_mask, ensure_finite):
    """Clean up signals and confounds before processing."""
    n_time = len(signals)  # original length of the signal
    n_runs, runs = _sanitize_runs(n_time, runs)
    confounds = _sanitize_confounds(n_time, n_runs, confounds)
    sample_mask = _sanitize_sample_mask(n_time, n_runs, runs, sample_mask)
    signals = _sanitize_signals(signals, ensure_finite)
    return signals, runs, confounds, sample_mask


def _sanitize_confounds(n_time, n_runs, confounds):
    """Check confounds are the correct type. When passing multiple runs, ensure the
    number of runs matches the sets of confound regressors.
    """
    if confounds is None:
        return confounds

    if not isinstance(confounds, (list, tuple, str, np.ndarray, pd.DataFrame)):
        raise TypeError(
            "confounds keyword has an unhandled type: %s" % confounds.__class__
        )

    if not isinstance(confounds, (list, tuple)):
        confounds = (confounds,)

    all_confounds = []
    for confound in confounds:
        confound = _sanitize_confound_dtype(n_time, confound)
        all_confounds.append(confound)
    confounds = np.hstack(all_confounds)
    return _ensure_float(confounds)


def _sanitize_sample_mask(n_time, n_runs, runs, sample_mask):
    """Check sample_mask is the right data type and matches the run index."""
    if sample_mask is None:
        return sample_mask

    sample_mask = _check_run_sample_masks(n_runs, sample_mask)

    if runs is None:
        runs = np.zeros(n_time)

    # check sample mask of each run
    for i, current_mask in enumerate(sample_mask):
        _check_sample_mask_index(i, n_runs, runs, current_mask)

    return sample_mask[0] if sum(runs) == 0 else sample_mask


def _check_sample_mask_index(i, n_runs, runs, current_mask):
    """Ensure the index in sample mask is valid."""
    len_run = sum(i == runs)
    len_current_mask = len(current_mask)
    # sample_mask longer than signal
    if len_current_mask > len_run:
        raise IndexError(
            "sample_mask {} of {} is has more timepoints than the current "
            "run ;sample_mask contains {} index but the run has {} "
            "timepoints.".format(
                (i + 1), n_runs, len_current_mask, len_run
            )
        )
    # sample_mask index exceed signal timepoints
    invalid_index = current_mask[current_mask > len_run]
    if invalid_index.size > 0:
        raise IndexError(
            "sample_mask {} of {} contains invalid index {}; "
            "The signal contains {} time points.".format(
                (i + 1), n_runs, invalid_index, len_run
            )
        )


def _sanitize_runs(n_time, runs):
    """Check runs are supplied in the correct format and detect the number of
    unique runs.
    """
    if runs is not None and len(runs) != n_time:
        raise ValueError(
            (
                "The length of the run vector (%i) "
                "does not match the length of the signals (%i)"
            )
            % (len(runs), n_time)
        )
    n_runs = 1 if runs is None else len(np.unique(runs))
    return n_runs, runs


def _sanitize_confound_dtype(n_signal, confound):
    """Check confound is the correct datatype."""
    if isinstance(confound, pd.DataFrame):
        confound = confound.values
    if isinstance(confound, str):
        filename = confound
        confound = csv_to_array(filename)
        if np.isnan(confound.flat[0]):
            # There may be a header
            confound = csv_to_array(filename, skip_header=1)
        if confound.shape[0] != n_signal:
            raise ValueError(
                "Confound signal has an incorrect length"
                "Signal length: {0}; confound length: {1}".format(
                    n_signal, confound.shape[0])
            )
    elif isinstance(confound, np.ndarray):
        if confound.ndim == 1:
            confound = np.atleast_2d(confound).T
        elif confound.ndim != 2:
            raise ValueError("confound array has an incorrect number "
                             "of dimensions: %d" % confound.ndim)
        if confound.shape[0] != n_signal:
            raise ValueError(
                "Confound signal has an incorrect length"
                "Signal length: {0}; confound length: {1}".format(
                    n_signal, confound.shape[0])
            )

    else:
        raise TypeError("confound has an unhandled type: %s"
                        % confound.__class__)
    return confound


def _check_filter_parameters(filter, low_pass, high_pass, t_r):
    """Check all filter related parameters are set correctly."""
    if not filter:
        if any(isinstance(item, float) for item in [low_pass, high_pass]):
            warnings.warn(
                "No filter type selected but cutoff frequency provided."
                "Will not perform filtering."
            )
        return False
    elif filter in availiable_filters:
        if filter == 'cosine' and not all(isinstance(item, float)
                                          for item in [t_r, high_pass]):
            raise ValueError(
                "Repetition time (t_r) and low cutoff frequency "
                "(high_pass) must be specified for cosine filtering."
                "t_r='{0}', high_pass='{1}'".format(t_r, high_pass)
            )
        if filter == 'butterworth':
            if all(item is None for item in [low_pass, high_pass, t_r]):
                # Butterworth was switched off by passing
                # None to all these parameters
                return False
            if t_r is None:
                raise ValueError("Repetition time (t_r) must be specified for "
                                 "butterworth filtering.")
            if any(isinstance(item, bool) for item in [low_pass, high_pass]):
                raise TypeError(
                    "high/low pass must be float or None but you provided "
                    "high_pass='{0}', low_pass='{1}'"
                    .format(high_pass, low_pass)
                )
        return filter
    else:
        raise ValueError("Filter method {} not implemented.".format(filter))


def _sanitize_signals(signals, ensure_finite):
    """Ensure signals are in the correct state."""
    if not isinstance(ensure_finite, bool):
        raise ValueError("'ensure_finite' must be boolean type True or False "
                         "but you provided ensure_finite={0}"
                         .format(ensure_finite))
    signals = signals.copy()
    if not isinstance(signals, np.ndarray):
        signals = as_ndarray(signals)
    if ensure_finite:
        mask = np.logical_not(np.isfinite(signals))
        if mask.any():
            signals[mask] = 0
    return _ensure_float(signals)


def _check_signal_parameters(detrend, standardize_confounds):
    """Raise warning if the combination is illogical"""
    if not detrend and not standardize_confounds:
        warnings.warn("When confounds are provided, one must perform detrend "
                      "and/or standardize confounds. You provided "
                      "detrend={0}, standardize_confounds={1}. If confounds "
                      "were not standardized or demeaned before passing to "
                      "signal.clean signal will not be correctly "
                      "cleaned. ".format(
                          detrend, standardize_confounds)
                      )
