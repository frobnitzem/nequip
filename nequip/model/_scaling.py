from nequip.nn import PerTypeScaleShift as PerTypeScaleShiftModule
from nequip.nn import RescaleOutput as RescaleOutputModule
from nequip.nn import GraphModuleMixin
from nequip.data import AtomicDataDict

import warnings
from typing import List


RESCALE_THRESHOLD = 1e-6


def GlobalRescale(
    model: GraphModuleMixin,
    config,
    initialize: bool,
    module_prefix: str,
    default_scale: float,
    default_scale_keys: List[str],
):
    """Rescales a set of fields."""
    scale = config.get(f"{module_prefix}_scale", default_scale)

    if scale is None:
        warnings.warn(
            f"Module `{module_prefix}` added but scale is `None`. Please check to ensure this is intended. To set scale, `{module_prefix}_scale` must be provided in the config."
        )

    if scale is not None and scale < RESCALE_THRESHOLD:
        raise ValueError(
            f"Global energy scaling was very low: {scale}. If dataset values were used, does the dataset contain insufficient variation? Maybe try disabling global scaling with scale=None."
        )

    assert isinstance(default_scale_keys, list), "keys need to be a list"

    # == Build the model ==
    return RescaleOutputModule(
        model=model,
        scale_keys=[k for k in default_scale_keys if k in model.irreps_out],
        scale_by=scale,
    )


def PerTypeEnergyScaleShift(
    model: GraphModuleMixin,
    config,
    initialize: bool,
):
    """Add per-atom rescaling and shifting for per-atom energies."""
    return _PerTypeScaleShift(
        scales_default=None,
        shifts_default=None,
        field=AtomicDataDict.PER_ATOM_ENERGY_KEY,
        out_field=AtomicDataDict.PER_ATOM_ENERGY_KEY,
        module_prefix="per_type_energy_scale_shift",
        insert_before="total_energy_sum",
        model=model,
        config=config,
    )


def _PerTypeScaleShift(
    scales_default,
    shifts_default,
    field: str,
    out_field: str,
    module_prefix: str,
    insert_before: str,
    model: GraphModuleMixin,
    config,
):
    """Add per-atom rescaling and shifting for a field."""
    scales = config.get(module_prefix + "_scales", scales_default)
    shifts = config.get(module_prefix + "_shifts", shifts_default)

    if scales is None and shifts is None:
        warnings.warn(
            f"Module `{module_prefix}` added but both scales and shifts are `None`. Please check to ensure this is intended. To set scales and/or shifts, `{module_prefix}_scales` and/or `{module_prefix}_shifts` must be provided in the config."
        )

    if isinstance(scales, float):
        scales = [scales]
    if isinstance(shifts, float):
        shifts = [shifts]
    for value in [scales, shifts]:
        assert value is None or isinstance(
            value, list
        ), f"`scales`/`shifts` must only be `float`, `List[float]` or `None`, but found value `{value}` of type {type(value)}"

    # insert in per species shift
    params = dict(
        field=field,
        out_field=out_field,
        shifts=shifts,
        scales=scales,
    )
    model.insert_from_parameters(
        before=insert_before,
        name=module_prefix,
        shared_params=config,
        builder=PerTypeScaleShiftModule,
        params=params,
    )
    return model
