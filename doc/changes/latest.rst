.. currentmodule:: nilearn

.. include:: names.rst

0.9.3.dev
=========

NEW
---

- New classes :class:`~maskers.MultiNiftiLabelsMasker` and :class:`~maskers.MultiNiftiMapsMasker` create maskers to extract signals from a list of subjects with 4D images using parallelization (:gh:`3237` by `Yasmin Mzayek`_).

Fixes
-----

- Fix off-by-one error when setting ticks in :func:`~plotting.plot_surf` (:gh:`3105` by `Dimitri Papadopoulos Orfanos`_).
- Regressor names can now be invalid identifiers but will raise an error with :meth:`~glm.first_level.FirstLevelModel.compute_contrast` if combined to make an invalid expression (:gh:`3374` by `Yasmin Mzayek`_).
- Fix :func:`~plotting.plot_connectome` which was raising a ``ValueError`` when ``vmax < 0`` (:gh:`3390` by `Paul Bogdan`_).
- Change the order of applying ``sample_masks`` in :func:`~signal.clean` based on different filtering options (:gh:`3385` by `Hao-Ting Wang`_).
- When using cosine filter and ``sample_masks`` is used, :func:`~signal.clean` generates the cosine discrete regressors using the full time series (:gh:`3385` by `Hao-Ting Wang`_).
- Description of the ``opening`` parameter added to ``compute_multi_epi_mask`` docs (:gh:`3412` by `Natasha Clarke`_).
- Fix display of colorbar in matrix plots. Colorbar was overlapping in :func:`~matplotlib.pyplot.subplots` due to a hardcoded adjustment value in the subplot (:gh:`3403` by `Raphael Meudec`_).
- Pass values with correct type to scikit-learn estimator parameters and remove deprecated parameter (:gh:`3430` by `Yasmin Mzayek`_).

Enhancements
------------

- :func:`~signal.clean` imputes scrubbed volumes (defined through ``sample_masks``) with cubic spline function before applying butterworth filter (:gh:`3385` by `Hao-Ting Wang`_). 
- As part of making the User Guide more user-friendly, the introduction was reworked (:gh:`3380` by `Alexis Thual`_)
- Added instructions for maintainers to make sure LaTeX dependencies are installed before building and deploying the stable docs (:gh:`3426` by `Yasmin Mzayek`_).

Changes
-------

- Private functions ``nilearn.regions.rena_clustering.weighted_connectivity_graph`` and ``nilearn.regions.rena_clustering.nearest_neighbor_grouping`` have been renamed with a leading "_", while function :func:`~regions.recursive_neighbor_agglomeration` has been added to the public API (:gh:`3347` by `Ahmad Chamma`_).
- Numpy deprecated type aliases are replaced by equivalent builtin types (:gh:`3422` by `Yasmin Mzayek`_).
- Function ``nilearn.masking.compute_multi_gray_matter_mask`` has been removed
  since it has been deprecated and replaced by :func:`~masking.compute_multi_brain_mask` (:gh:`3427` by `Yasmin Mzayek`_).
- :mod:`~nilearn.glm` will no longer warn that the module is experimental (:gh:`3424` by `Yasmin Mzayek`_).
- Python ``3.6`` is no longer supported. Support for Python ``3.7`` is deprecated and will be removed in release ``0.12`` (:gh:`3429` by `Yasmin Mzayek`_).
- The function ``_safe_cache`` is removed because it was deemed outdated and not necessary anymore (:gh:`3375` by `Yasmin Mzayek`_).
- Minimum supported versions of packages have been bumped up:

    * Numpy -- v1.19.0
    * SciPy -- v1.6.0
    * Scikit-learn -- v1.0.0
    * Nibabel -- v3.2.0
    * Pandas -- v1.1.5
    * Joblib -- v1.0.0

  (:gh:`3440` by `Yasmin Mzayek`_).
- In release ``0.10.0`` the default resolution for loaded MNI152 templates will be 1mm instead of 2mm (:gh:`3433` by `Yasmin Mzayek`_).
