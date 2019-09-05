from math import gamma

from scgenome.jointcnmodels import calculate_marginal_ll_simple
from .constants import ALPHA, NO_CHILDREN


class TNode:

    # TODO assert types
    def __init__(self, sample_inds, left_child, right_child, pi, d, ll, log_r,
                 cluster_ind):
        self.sample_inds = sample_inds
        self.left_child = left_child
        self.right_child = right_child
        self.pi = pi
        self.d = d
        self.ll = ll
        self.log_r = log_r
        self.cluster_ind = cluster_ind

    def is_leaf(self):
        return (self.left_child is None and
                self.right_child is None and
                len(self.sample_inds) == 1)

    def get_pi_d(self, alpha=ALPHA):
        if self.left_child is None or self.right_child is None:
            raise ValueError(NO_CHILDREN)

        n_k = len(self.left_child.sample_inds) + len(
            self.right_child.sample_inds)
        gnk = gamma(n_k)
        self.d = alpha * gnk + self.left_child.d * self.right_child.d
        self.pi = alpha * gnk / self.d

        return self.pi, self.d

    # TODO is weird in the case where there is only 1 sample index
    def get_ll(self, measurement, variances, tr_mat):
        self.ll = calculate_marginal_ll_simple(
            measurement[self.sample_inds, :],
            variances[self.sample_inds, :],
            tr_mat
        )
        return self.ll

    def get_log_r(self, measurement, variances, tr_mat):
        self.log_r = calculate_marginal_ll_simple(
            measurement[self.sample_inds, :],
            variances[self.sample_inds, :],
            tr_mat
        )
        return self.log_r

    def get_leaves(self, leaves=None):
        if leaves is None:
            leaves = []
        if self.left_child is None and self.right_child is None:
            leaves.append(self)
            return leaves
        elif self.right_child is None:
            return self.left_child.get_leaves(leaves)
        elif self.left_child is None:
            return self.right_child.get_leaves(leaves)
        else:
            leaves = leaves + self.left_child.get_leaves()
            leaves = leaves + self.right_child.get_leaves()
            return leaves

    def __str__(self):
        return f"sample_inds : {self.sample_inds}, " \
            f"left_child : {self.left_child.__repr__()} " \
            f"right_child : {self.left_child.__repr__()} " \
            f"pi : {self.pi}, " \
            f"d : {self.d}, " \
            f"ll : {self.ll}, " \
            f"log_r : {self.log_r}, " \
            f"cluster_ind : {self.cluster_ind}"

    def __eq__(self, other):
        return (
                self.sample_inds == other.sample_inds and
                self.left_child == other.left_child and
                self.right_child == other.right_child and
                self.pi == other.pi and
                self.d == other.d and
                self.ll == other.ll and
                self.log_r == other.log_r and
                self.cluster_ind == other.cluster_ind
        )

