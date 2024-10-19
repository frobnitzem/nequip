import pytest

import numpy as np
from pathlib import Path

import ase
import ase.io
import ase.data

import torch

from nequip.data.transforms import (
    ChemicalSpeciesToAtomTypeMapper,
    NeighborListTransform,
)
from nequip.data import AtomicDataDict
from nequip.model import model_from_config
from nequip.ase import NequIPCalculator
from nequip.utils import Config
from nequip.utils.unittests.model_tests import BaseEnergyModelTests


class TestNequIPModel(BaseEnergyModelTests):
    @pytest.fixture
    def strict_locality(self):
        return True

    @pytest.fixture(
        params=[False, True],
        scope="class",
    )
    def config(self, request):
        do_scale = request.param
        config = {
            "model_builders": [
                "nequip.model.PairPotential",
                "nequip.model.ForceOutput",
                "nequip.model.RescaleEnergyEtc",
            ],
            "global_rescale_scale": 3.7777 if do_scale else None,
            "pair_style": "ZBL",
            "units": "metal",
            "r_max": 5.0,
            "type_names": ["H", "C", "O"],
            "ZBL_chemical_species": ["H", "C", "O"],
            "seed": 123,
        }
        return config, [
            AtomicDataDict.TOTAL_ENERGY_KEY,
            AtomicDataDict.FORCE_KEY,
            AtomicDataDict.PER_ATOM_ENERGY_KEY,
        ]

    def test_lammps_repro(self, config):
        if torch.get_default_dtype() != torch.float64:
            pytest.skip()
        config, _ = config
        config = config.copy()
        r_max: float = 8.0  # see zbl_data.lmps
        config.update(
            {
                "model_dtype": "float64",
                "r_max": r_max + 1,  # To make cutoff envelope irrelevant
                "PolynomialCutoff_p": 80,  # almost a step function
            }
        )
        config["type_names"] = ["H", "O", "C", "N", "Cu", "Au"]
        config["ZBL_chemical_species"] = ["H", "O", "C", "N", "Cu", "Au"]
        transforms = [
            ChemicalSpeciesToAtomTypeMapper(
                chemical_symbols=config["ZBL_chemical_species"],
            ),
            NeighborListTransform(r_max=r_max),
        ]
        ZBL_model = model_from_config(Config.from_dict(config), initialize=True)
        ZBL_model.eval()
        # make test system of two atoms:
        atoms = ase.Atoms(positions=np.zeros((2, 3)), symbols=["H", "H"])
        atoms.calc = NequIPCalculator(ZBL_model, device="cpu", transforms=transforms)
        # == load precomputed reference data ==
        # To regenerate this data, run
        # $ lmp -in zbl_data.lmps
        # $ python -c "import numpy as np; d = np.loadtxt('zbl.dat', skiprows=1); np.save('zbl.npy', d)"
        refdata = np.load(Path(__file__).parent / "zbl.npy")
        for r, Zi, Zj, pe, fxi, fxj in refdata:
            if r >= r_max:
                continue
            atoms.positions[1, 0] = r
            atoms.set_atomic_numbers([int(Zi), int(Zj)])
            # ZBL blows up for atoms being close, so the numerics differ to ours
            # 1e-5 == 0.01 meV / Å
            assert np.allclose(atoms.get_forces()[0, 0], fxi, atol=1e-5)
            assert np.allclose(atoms.get_forces()[1, 0], fxj, atol=1e-5)
            # 1e-4 == 0.1 meV system, 0.05 meV / atom
            assert np.allclose(atoms.get_potential_energy(), pe, atol=1e-4)
