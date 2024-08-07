from typing import List, Dict, Any, Optional

import torch

from e3nn.util._argtools import _get_device

from nequip.data import AtomicDataDict

from ._graph_mixin import GraphModuleMixin


class GraphModel(GraphModuleMixin, torch.nn.Module):
    """Top-level module for any complete `nequip` model.

    Manages top-level rescaling, dtypes, and more.

    Args:

    """

    model_dtype: torch.dtype
    model_input_fields: List[str]

    def __init__(
        self,
        model: GraphModuleMixin,
        model_dtype: Optional[torch.dtype] = None,
        model_input_fields: Dict[str, Any] = {},
    ) -> None:
        super().__init__()
        irreps_in = {
            # Things that always make sense as inputs:
            AtomicDataDict.POSITIONS_KEY: "1o",
            AtomicDataDict.EDGE_INDEX_KEY: None,
            AtomicDataDict.EDGE_CELL_SHIFT_KEY: None,
            AtomicDataDict.CELL_KEY: "1o",  # 3 of them, but still
            AtomicDataDict.BATCH_KEY: None,
            AtomicDataDict.NUM_NODES_KEY: None,
            AtomicDataDict.ATOM_TYPE_KEY: None,
        }
        model_input_fields = AtomicDataDict._fix_irreps_dict(model_input_fields)
        assert len(set(irreps_in.keys()).intersection(model_input_fields.keys())) == 0
        irreps_in.update(model_input_fields)
        self._init_irreps(irreps_in=irreps_in, irreps_out=model.irreps_out)
        for k, irreps in model.irreps_in.items():
            if self.irreps_in.get(k, None) != irreps:
                raise RuntimeError(
                    f"Model has `{k}` in its irreps_in with irreps `{irreps}`, but `{k}` is missing from/has inconsistent irreps in model_input_fields of `{self.irreps_in.get(k, 'missing')}`"
                )
        self.model = model
        self.model_dtype = (
            model_dtype if model_dtype is not None else torch.get_default_dtype()
        )
        self.model_input_fields = list(self.irreps_in.keys())
        self.register_buffer(
            "_model_dtype_example", torch.as_tensor(0.0, dtype=model_dtype)
        )

    # == Inference ==

    def forward(self, data: AtomicDataDict.Type) -> AtomicDataDict.Type:
        # restrict the input data to allowed keys, and cast to model_dtype
        # this also prevents the model from direclty using the dict from the outside,
        # preventing weird pass-by-reference bugs
        new_data: AtomicDataDict.Type = {}
        for k, v in data.items():
            if k in self.model_input_fields:
                # Allow input position and position-related
                # fields to be maintained in their original dtype
                if v.is_floating_point() and k not in (
                    AtomicDataDict.POSITIONS_KEY,
                    AtomicDataDict.CELL_KEY,
                    AtomicDataDict.EDGE_CELL_SHIFT_KEY,
                ):
                    v = v.to(dtype=self.model_dtype)
                new_data[k] = v
        # Store the model dtype indicator tensor in all input data dicts
        new_data[AtomicDataDict.MODEL_DTYPE_KEY] = self._model_dtype_example
        # run the model
        data = self.model(new_data)
        return data

    # == Helpers ==

    @torch.jit.unused
    def get_device(self) -> torch.device:
        return _get_device(self)
