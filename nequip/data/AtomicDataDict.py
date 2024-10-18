"""AtomicDataDict

A "static class" (set of functions) operating on `Dict[str, torch.Tensor]`,
aliased here as `AtomicDataDict.Type`.  By avoiding a custom object wrapping
this simple type we avoid unnecessary abstraction and ensure compatibility
with a broad range of PyTorch features and libraries (including TorchScript)
that natively handle dictionaries of tensors.

Each function in this module is sort of like a method on the `AtomicDataDict`
class, if there was such a class---"self" is just passed explicitly:

    AtomicDataDict.some_method(my_data)

Some standard fields:

    pos (Tensor [n_nodes, 3]): Positions of the nodes.
    edge_index (LongTensor [2, n_edges]): ``edge_index[0]`` is the per-edge
        index of the source node and ``edge_index[1]`` is the target node.
    edge_cell_shift (Tensor [n_edges, 3], optional): which periodic image
        of the target point each edge goes to, relative to the source point.
    cell (Tensor [1, 3, 3], optional): the periodic cell for
        ``edge_cell_shift`` as the three triclinic cell vectors.
    node_features (Tensor [n_atom, ...]): the input features of the nodes, optional
    node_attrs (Tensor [n_atom, ...]): the attributes of the nodes, for instance the atom type, optional
    batch (Tensor [n_atom]): the graph to which the node belongs, optional
    atomic_numbers (Tensor [n_atom]): optional
    atom_type (Tensor [n_atom]): optional
"""

from typing import Dict, Union, Tuple, List, Optional, Any

import torch
from e3nn import o3

# Make the keys available in this module
from ._keys import *  # noqa: F403, F401

# Also import the module to use in TorchScript, this is a hack to avoid bug:
# https://github.com/pytorch/pytorch/issues/52312
from . import _keys

from . import _nl, _key_registry

# Define a type alias
Type = Dict[str, torch.Tensor]
# A type representing ASE-style periodic boundary condtions, which can be partial (the tuple case)
PBCType = Union[bool, Tuple[bool, bool, bool]]

# == Irrep checking ==

_SPECIAL_IRREPS = [None]


def _fix_irreps_dict(d: Dict[str, Any]):
    return {k: (i if i in _SPECIAL_IRREPS else o3.Irreps(i)) for k, i in d.items()}


def _irreps_compatible(ir1: Dict[str, o3.Irreps], ir2: Dict[str, o3.Irreps]):
    return all(ir1[k] == ir2[k] for k in ir1 if k in ir2)


# == JIT-unsafe "methods" for general data processing ==


def from_dict(data: dict) -> Type:
    return _key_registry._process_dict(data)


def to_(
    data: Type,
    device: Optional[torch.device],
) -> Type:
    """Move an AtomicDataDict to a device"""
    for k, v in data.items():
        data[k] = v.to(device=device)
    return data


def batched_from_list(data_list: List[Type]) -> Type:
    """Batch multiple AtomicDataDict.Type into one.

    Entries in the input data_list can be batched AtomicDataDict's.
    """
    # == Safety Checks ==
    num_data = len(data_list)
    if num_data == 0:
        raise RuntimeError("Cannot batch empty list of AtomicDataDict.Type")
    elif num_data == 1:
        # Short circuit
        return with_batch_(data_list[0].copy())

    # first make sure every AtomicDataDict is batched (even if trivially so)
    # with_batch_() is a no-op if data already has BATCH_KEY and NUM_NODES_KEY
    data_list = [with_batch_(data.copy()) for data in data_list]

    # now every data entry should have BATCH_KEY and NUM_NODES_KEY
    # check for inconsistent keys over the AtomicDataDicts in the list
    dict_keys = data_list[0].keys()
    assert all(
        [dict_keys == data_list[i].keys() for i in range(len(data_list))]
    ), "Found inconsistent keys across AtomicDataDict list to be batched."

    # == Batching Procedure ==
    out = {}

    # get special keys that are related to edge indices (neighborlist)
    edge_idxs = {}
    for k in dict_keys:
        if "edge_index" in k:
            edge_idxs[k] = []

    # first handle edge indices and batch properties separately
    cum_nodes: int = 0  # for edge indices
    cum_frames: int = 0  # for batch
    batches = []
    for idx in range(num_data):
        for key in edge_idxs.keys():
            edge_idxs[key].append(data_list[idx][key] + cum_nodes)
        batches.append(data_list[idx][_keys.BATCH_KEY] + cum_frames)
        cum_frames += num_frames(data_list[idx])
        cum_nodes += num_nodes(data_list[idx])

    for key in edge_idxs.keys():
        out[key] = torch.cat(edge_idxs[key], dim=1)  # (2, num_edges)

    out[_keys.BATCH_KEY] = torch.cat(batches, dim=0)

    # then handle the rest
    ignore = set(edge_idxs.keys()) | {_keys.BATCH_KEY}
    for k in dict_keys:
        # ignore these since handled previously
        if k in ignore:
            continue
        elif k in (
            _key_registry._GRAPH_FIELDS
            | _key_registry._NODE_FIELDS
            | _key_registry._EDGE_FIELDS
        ):
            out[k] = torch.cat([d[k] for d in data_list], dim=0)
        else:
            raise KeyError(f"Unregistered key {k}")

    return out


def frame_from_batched(batched_data: Type, index: int) -> Type:
    """Returns a single frame from batched data."""
    # get data with batches just in case this is called on unbatched data
    if len(batched_data.get(_keys.NUM_NODES_KEY, (None,))) == 1:
        assert index == 0
        return batched_data
    # use zero-indexing as per python norm
    N_frames = num_frames(batched_data)
    assert (
        0 <= index < N_frames
    ), f"Input data consists of {N_frames} frames so index can run from 0 to {N_frames-1} -- but given index of {index}!"
    batches = batched_data[_keys.BATCH_KEY]
    node_idx_offset = (
        0
        if index == 0
        else torch.cumsum(batched_data[_keys.NUM_NODES_KEY], 0)[index - 1]
    )
    if _keys.EDGE_INDEX_KEY in batched_data:
        edge_center_idx = batched_data[_keys.EDGE_INDEX_KEY][0]

    out = {}
    for k, v in batched_data.items():
        if k == _keys.EDGE_INDEX_KEY:
            # special case since shape is (2, num_edges), and to remove edge index offset
            mask = torch.eq(batches[edge_center_idx], index).unsqueeze(0)
            out[k] = torch.masked_select(v, mask).view(2, -1) - node_idx_offset
        elif k in _key_registry._GRAPH_FIELDS:
            # index out relevant frame
            out[k] = v[[index]]  # to ensure batch dimension remains
        elif k in _key_registry._NODE_FIELDS:
            # mask out relevant portion
            out[k] = v[batches == index]
            if k == _keys.BATCH_KEY:
                out[k] = torch.zeros_like(out[k])
        elif k in _key_registry._EDGE_FIELDS:  # excluding edge indices
            out[k] = v[torch.eq(torch.index_select(batches, 0, edge_center_idx), index)]
        else:
            if k != _keys.MODEL_DTYPE_KEY:
                raise KeyError(f"Unregistered key {k}")

    return out


def compute_neighborlist_(data: Type, r_max: float, **kwargs) -> Type:
    """Add a neighborlist to `data` in-place.

    This can be called on alredy-batched data.
    """
    to_batch: List[Type] = []
    for idx in range(num_frames(data)):
        data_per_frame = frame_from_batched(data, idx)

        cell = data_per_frame.get(_keys.CELL_KEY, None)
        if cell is not None:
            cell = cell.view(3, 3)  # remove batch dimension

        pbc = data_per_frame.get(_keys.PBC_KEY, None)
        if pbc is not None:
            pbc = pbc.view(3)  # remove batch dimension

        edge_index, edge_cell_shift, cell = _nl.neighbor_list_and_relative_vec(
            pos=data_per_frame[_keys.POSITIONS_KEY],
            r_max=r_max,
            cell=cell,
            pbc=pbc,
            **kwargs,
        )
        # add neighborlist information
        data_per_frame[_keys.EDGE_INDEX_KEY] = edge_index
        if data.get(_keys.CELL_KEY, None) is not None and edge_cell_shift is not None:
            data_per_frame[_keys.EDGE_CELL_SHIFT_KEY] = edge_cell_shift
        to_batch.append(data_per_frame)

    # rebatch to make sure neighborlist information is in a similar batched format
    return batched_from_list(to_batch)


def without_nodes(data: Type, which_nodes: torch.Tensor) -> Type:
    """Return a copy of ``data`` with ``which_nodes`` removed.
    The returned object may share references to some underlying data tensors with ``data``.

    Args:
        data (AtomicDataDict)     : atomic data dict
        which_nodes (torch.Tensor): index tensor or boolean mask

    Returns:
        A new data object.
    """
    N_nodes = num_nodes(data)
    which_nodes = torch.as_tensor(which_nodes)
    if which_nodes.dtype == torch.bool:
        node_mask = ~which_nodes
    else:
        node_mask = torch.ones(N_nodes, dtype=torch.bool)
        node_mask[which_nodes] = False
    assert node_mask.shape == (N_nodes,)
    n_keeping = node_mask.sum()

    # Only keep edges where both from and to are kept
    edge_idx = data[_keys.EDGE_INDEX_KEY]
    edge_mask = node_mask[edge_idx[0]] & node_mask[edge_idx[1]]
    # Create an index mapping:
    new_index = torch.full((N_nodes,), -1, dtype=torch.long)
    new_index[node_mask] = torch.arange(n_keeping, dtype=torch.long)

    new_dict = {}
    for k, v in data.items():
        if k == _keys.EDGE_INDEX_KEY:
            new_dict[k] = new_index[v[:, edge_mask]]
        elif k in _key_registry._GRAPH_FIELDS:
            new_dict[k] = v
        elif k in _key_registry._NODE_FIELDS:
            new_dict[k] = v[node_mask]
        elif k in _key_registry._EDGE_FIELDS:
            new_dict[k] = v[edge_mask]
        else:
            raise KeyError(f"Unregistered key {k}")

    return new_dict


# == JIT-safe "methods" for use in model code ==


def num_frames(data: Type) -> int:
    if _keys.NUM_NODES_KEY not in data:
        return 1
    else:
        return len(data[_keys.NUM_NODES_KEY])


def num_nodes(data: Type) -> int:
    return len(data[_keys.POSITIONS_KEY])


def num_edges(data: Type) -> int:
    # will not check if neighborlist is present
    return data[_keys.EDGE_INDEX_KEY].shape[1]


def with_edge_vectors(
    data: Type,
    with_lengths: bool = True,
    edge_index_field: str = _keys.EDGE_INDEX_KEY,
    edge_cell_shift_field: str = _keys.EDGE_CELL_SHIFT_KEY,
    edge_vec_field: str = _keys.EDGE_VECTORS_KEY,
    edge_len_field: str = _keys.EDGE_LENGTH_KEY,
) -> Type:
    """Compute the edge displacement vectors for a graph.

    If ``data.pos.requires_grad`` and/or ``data.cell.requires_grad``, this
    method will return edge vectors correctly connected in the autograd graph.

    The availability of various custom field options enables reuse of this function
    for nonconventional field options.

    Returns:
        Tensor [n_edges, 3] edge displacement vectors
    """
    if edge_vec_field in data:
        if with_lengths and edge_len_field not in data:
            data[edge_len_field] = torch.linalg.norm(data[edge_vec_field], dim=-1)
        return data
    else:
        # Build it dynamically
        # Note that this is backwardable, because everything (pos, cell, shifts) is Tensors.
        pos = data[_keys.POSITIONS_KEY]
        edge_index = data[edge_index_field]
        edge_vec = torch.index_select(pos, 0, edge_index[1]) - torch.index_select(
            pos, 0, edge_index[0]
        )
        if _keys.CELL_KEY in data:
            # ^ note that to save time we don't check that the edge_cell_shifts are trivial if no cell is provided; we just assume they are either not present or all zero.
            # -1 gives a batch dim no matter what
            cell = data[_keys.CELL_KEY].view(-1, 3, 3)
            edge_cell_shift = data[edge_cell_shift_field]
            if cell.shape[0] > 1:
                batch = data[_keys.BATCH_KEY]
                # Cell has a batch dimension
                # note the ASE cell vectors as rows convention
                edge_vec = edge_vec + torch.einsum(
                    "ni,nij->nj",
                    edge_cell_shift,
                    cell[batch[edge_index[0]]],
                )
                # TODO: is there a more efficient way to do the above without
                # creating an [n_edge] and [n_edge, 3, 3] tensor?
            else:
                # Cell has either no batch dimension, or a useless one,
                # so we can avoid creating the large intermediate cell tensor.
                # Note that we do NOT check that the batch array, if it is present,
                # is trivial — but this does need to be consistent.
                edge_vec = edge_vec + torch.einsum(
                    "ni,ij->nj",
                    edge_cell_shift,
                    cell.squeeze(0),  # remove batch dimension
                )
        data[edge_vec_field] = edge_vec
        if with_lengths:
            data[edge_len_field] = torch.linalg.norm(edge_vec, dim=-1)
        return data


def with_batch_(data: Type) -> Type:
    """Get batch Tensor.

    If this AtomicDataPrimitive has no ``batch``, one of all zeros will be
    allocated and returned.
    """
    if _keys.BATCH_KEY in data:
        assert _keys.NUM_NODES_KEY in data
        return data
    else:
        # This is a single frame, so put in info for the trivial batch
        pos = data[_keys.POSITIONS_KEY]
        # Use .expand here to avoid allocating num nodes worth of memory
        # https://pytorch.org/docs/stable/generated/torch.Tensor.expand.html
        data[_keys.BATCH_KEY] = torch.zeros(
            1, dtype=torch.long, device=pos.device
        ).expand(len(pos))
        data[_keys.NUM_NODES_KEY] = torch.full(
            (1,), len(pos), dtype=torch.long, device=pos.device
        )
        return data


# For autocomplete in IDEs, don't expose our various imports
__all__ = [
    to_,
    from_dict,
    without_nodes,
    compute_neighborlist_,
    num_nodes,
    num_edges,
    with_batch_,
    with_edge_vectors,
] + _keys.ALLOWED_KEYS
