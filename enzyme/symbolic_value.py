###############################################################################
#                                                                              #
#   sa2d_decomp_value.py copyright(c) Qiqi Wang 2015 (qiqi.wang@gmail.com)     #
#                                                                              #
################################################################################

import os
import sys
import time
import collections
import copy as copymodule
from subprocess import Popen, PIPE
from io import BytesIO

import numpy as np

def _is_like_sa_value(a):
    '''
    Check attributes of stencil array value
    '''
    if hasattr(a, 'owner'):
        return a.owner is None or hasattr(a.owner, 'access_neighbor')
    else:
        return False

# ============================================================================ #
#                             stencil_array value                              #
# ============================================================================ #

class stencil_array_value(object):
    def __init__(self, shape=(), owner=None):
        self.shape = tuple(shape)
        self.owner = owner

    def __repr__(self):
        if self.owner:
            return 'Dependent value of shape {0} generated by {1}'.format(
                    self.shape, self.owner)
        else:
            return 'Independent value of shape {0}'.format(self.shape)

    # --------------------------- properties ------------------------------ #

    @property
    def ndim(self):
        return len(self.shape)

    @property
    def size(self):
        return int(np.prod(self.shape))

    def __len__(self):
        return 1 if not self.shape else self.shape[0]


class builtin:
    ZERO = stencil_array_value()
    I = stencil_array_value()
    J = stencil_array_value()
    K = stencil_array_value()


# ============================================================================ #
#                                atomic stage                                  #
# ============================================================================ #

def discover_values(source_values, sink_values):
    discovered_values = []
    discovered_triburary_values = []
    def discover_values_from(v):
        if not hasattr(v, 'owner'):
            return
        if v in source_values:
            return
        if v.owner is None:
            if v not in discovered_triburary_values:
                discovered_triburary_values.append(v)
        elif v not in discovered_values:
            discovered_values.append(v)
            for v_inp in v.owner.inputs:
                discover_values_from(v_inp)
    for v in sink_values:
        discover_values_from(v)
    return discovered_values, discovered_triburary_values

def sort_values(sorted_values, unsorted_values):
    def is_computable(v):
        return (not _is_like_sa_value(v) or
                v in sorted_values or
                v.owner is None)
    while len(unsorted_values):
        removed_any = False
        for v in unsorted_values:
            if all([is_computable(v_inp) for v_inp in v.owner.inputs]):
                unsorted_values.remove(v)
                sorted_values.append(v)
                removed_any = True
        assert removed_any

class AtomicStage(object):
    '''
    Immutable compact stage
    '''
    def __init__(self, source_values, sink_values):
        sorted_values = copymodule.copy(source_values)
        unsorted_values, self.triburary_values = discover_values(
                source_values, sink_values)
        sort_values(sorted_values, unsorted_values)
        assert unsorted_values == []
        self.source_values = sorted_values[:len(source_values)]
        self.sorted_values = sorted_values[len(source_values):]
        self.sink_values = copymodule.copy(sink_values)

    def __call__(self, source_values, triburary):
        if not isinstance(source_values, (tuple, list)):
            source_values = [source_values]
        source_values = list(source_values)
        assert len(self.source_values) == len(source_values)
        if hasattr(triburary, '__call__'):
            triburary_values = [triburary(v) for v in self.triburary_values]
        elif hasattr(triburary, '__getitem__'):
            triburary_values = [triburary[v] for v in self.triburary_values]
        values = self.source_values + self.triburary_values
        tmp_values = source_values + triburary_values
        # _tmp attributes are assigned to inputs
        assert len(values) == len(tmp_values)
        for v, v_tmp in zip(values, tmp_values):
            assert not hasattr(v, '_tmp')
            v._tmp = v_tmp
        # _tmp attributes are computed to each value
        _tmp = lambda v : v._tmp if _is_like_sa_value(v) else v
        for v in self.sorted_values:
            assert not hasattr(v, '_tmp')
            inputs_tmp = [_tmp(v_inp) for v_inp in v.owner.inputs]
            v._tmp = v.owner.perform(inputs_tmp)
        # _tmp attributes are extracted from outputs then deleted from all
        sink_values = tuple(v._tmp for v in self.sink_values)
        values += self.sorted_values
        for v in values:
            del v._tmp
        return sink_values

    def __hash__(self):
        return id(self)

# ============================================================================ #
#                                decomposition                                 #
# ============================================================================ #

def build_graph(all_values):
    weights = []
    for i, v in enumerate(all_values):
        v._value_id = i
        weights.append(v.size)
    weights.append(1)
    edges = []
    for i, v in enumerate(all_values):
        if not v.owner: continue
        for v_inp in v.owner.inputs:
            if hasattr(v_inp, '_value_id'):
                e = (v_inp._value_id, v._value_id, v.owner.access_neighbor)
                edges.append(e)
    for v in all_values:
        del v._value_id
    return np.array(weights, int), np.array(edges, int)

def decompose_graph(weights, edges):
    my_path = os.path.dirname(os.path.abspath(__file__))
    bin_path = os.path.abspath(os.path.join(my_path, '..', 'bin'))
    quarkflow_bin = os.path.join(bin_path, 'quarkflow')
    p = Popen(quarkflow_bin, stdin=PIPE, stdout=PIPE, stderr=PIPE)
    first_line = '{0} {1}'.format(len(weights) - 1, len(edges))
    weights = ['{0}'.format(w) for w in weights]
    edges = ['{0} {1} {2}'.format(i, j, s) for i, j, s in edges]
    inp = '\n'.join([first_line] + weights + edges)
    out, err = p.communicate(inp.encode())
    assert len(err.strip()) == 0
    return np.loadtxt(BytesIO(out), int).T

def decompose(source_values, sink_values, verbose=True):
    values, _ = discover_values(source_values, sink_values)
    all_values = list(values) + list(source_values)
    weights, edges = build_graph(all_values)
    c, d, e = decompose_graph(weights, edges)
    num_stages = d.max()
    for i, v in enumerate(all_values):
        v.create_stage = c[i]
        v.discard_stage = d[i]
    stages = []
    stage_source = list(source_values)
    for k in range(1, num_stages):
        next_stage_source = [v for v in all_values
                               if v.create_stage <= k and v.discard_stage > k]
        stages.append(AtomicStage(stage_source, next_stage_source))
        stage_source = next_stage_source
    stages.append(AtomicStage(stage_source, list(sink_values)))
    return stages

################################################################################
################################################################################
################################################################################
