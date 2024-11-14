from e3nn.util.test import assert_auto_jitable

from nequip.utils.test import assert_AtomicData_equivariant
from nequip.nn import SequentialGraphNetwork
from nequip.nn.embedding import (
    PolynomialCutoff,
    OneHotAtomEncoding,
    SphericalHarmonicEdgeAttrs,
    EdgeLengthNormalizer,
    BesselEdgeLengthEncoding,
)
from nequip.utils import dtype_from_name, torch_default_dtype


def test_onehot(model_dtype, CH3CHO):
    _, data = CH3CHO
    with torch_default_dtype(dtype_from_name(model_dtype)):
        oh = OneHotAtomEncoding(
            type_names=["A", "B", "C"],
        )
    assert_auto_jitable(oh)
    assert_AtomicData_equivariant(oh, data)


def test_spharm(model_dtype, CH3CHO):
    _, data = CH3CHO
    with torch_default_dtype(dtype_from_name(model_dtype)):
        sph = SphericalHarmonicEdgeAttrs(irreps_edge_sh="0e + 1o + 2e")
    assert_auto_jitable(sph)
    assert_AtomicData_equivariant(sph, data)


def test_radial_basis(model_dtype, CH3CHO):
    _, data = CH3CHO

    with torch_default_dtype(dtype_from_name(model_dtype)):
        rad = SequentialGraphNetwork(
            {
                "edge_norm": EdgeLengthNormalizer(r_max=5.0, type_names=[0, 1, 2]),
                "bessel": BesselEdgeLengthEncoding(cutoff=PolynomialCutoff(6)),
            }
        )
    assert_auto_jitable(rad.edge_norm)
    assert_auto_jitable(rad.bessel)
    assert_AtomicData_equivariant(rad, data)
