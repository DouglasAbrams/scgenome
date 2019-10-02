import umap
import hdbscan
import seaborn
import pandas as pd
import numpy as np
import matplotlib as mpl
import matplotlib.pyplot as plt
from adjustText import adjust_text
from scgenome.jointcnmodels import get_variances, get_tr_probs
from itertools import combinations
from .TNode import TNode
from .constants import ALPHA, MAX_CN, VALUE_IDS, LINKAGE_COLS, BHC_ID, \
    DEBUG_LINKAGE_COLS
from .utils import cn_data_to_mat_data_ids
from scipy.spatial.distance import pdist, cdist
from scipy.stats import pearsonr
from scgenome import utils, jointcnmodels


def umap_hdbscan_cluster(
        cn,
        n_components=2,
        n_neighbors=15,
        min_dist=0.1,
):
    """ Cluster using umap and hdbscan.

    Args:
        cn: data frame columns as cell ids, rows as segments

    Returns:
        data frame with columns:
            cluster_id
            cell_id
            umap1
            umap2

    """
    embedding = umap.UMAP(
        n_neighbors=n_neighbors,
        min_dist=min_dist,
        n_components=n_components,
        random_state=42,
        metric='euclidean',
    ).fit_transform(cn.fillna(0).values.T)

    clusters = hdbscan.HDBSCAN(
        min_samples=10,
        min_cluster_size=30,
    ).fit_predict(embedding)

    df = pd.DataFrame({
        'cell_id': cn.columns, 'cluster_id': clusters,
        'umap1': embedding[:, 0], 'umap2': embedding[:, 1]
    })
    df = df[['cell_id', 'cluster_id', 'umap1', 'umap2']]
    df = df.dropna()

    return df


def get_cluster_palette(n_col):
    if n_col <= 10:
        palette = plt.get_cmap("tab10")
    else:
        palette = mpl.colors.ListedColormap([
            '#1d1d1d', '#ebce2b', '#702c8c', '#db6917', '#96cde6', '#ba1c30',
            '#c0bd7f', '#7f7e80', '#5fa641', '#d485b2', '#4277b6', '#df8461',
            '#463397', '#e1a11a', '#91218c', '#e8e948', '#7e1510', '#92ae31',
            '#6f340d', '#d32b1e', '#2b3514'
        ])
    return palette


def get_cluster_color_map(cluster_ids):
    num_colors = len(np.unique(cluster_ids[cluster_ids >= 0]))
    pal = get_cluster_palette(num_colors)

    color_map = {}
    idx = 0.
    for cluster_id in np.sort(np.unique(cluster_ids)):
        if cluster_id < 0:
            color_map[cluster_id] = (0.75, 0.75, 0.75, 1.0)
        else:
            color_map[cluster_id] = pal((idx) / (num_colors - 1))
            idx += 1

    return color_map


def get_cluster_colors(cluster_ids):
    color_map = get_cluster_color_map(cluster_ids)

    color_mat = []
    for cluster_id in cluster_ids:
        color_mat.append(color_map[cluster_id])

    return color_mat


def cluster_labels(cluster_ids):
    counts = cluster_ids.value_counts().astype(str)
    labels = counts.index.to_series().astype(str) + ' (' + counts + ')'
    if -1 in labels:
        labels.at[-1] = labels[-1].replace('-1', 'Filt.')
    return dict(list(zip(counts.index, labels)))


def plot_umap_clusters(ax, df):
    """ Scatter plot of umap clusters.

    Args:
        ax: matplotlib axis
        df: clusters dataframe with columns:
            cluster_id
            umap1
            umap2

    """
    labels = cluster_labels(df['cluster_id'])
    color_map = get_cluster_color_map(df['cluster_id'].values)

    if -1 in labels:
        df_noise = df[df['cluster_id'] < 0]
        ax.scatter(
            df_noise['umap1'].values,
            df_noise['umap2'].values,
            c=color_map[-1],
            s=2,
            label=labels[-1],
        )

    text_labels = []
    for cluster_id, cluster_df in df[df['cluster_id'] >= 0].groupby('cluster_id'):
        ax.scatter(
            cluster_df['umap1'].values,
            cluster_df['umap2'].values,
            c=color_map[cluster_id],
            s=2,
            label=labels[int(cluster_id)],
        )

    label_pos = df.groupby('cluster_id').mean()
    text_labels = [
        ax.text(label_pos.at[c, 'umap1'], label_pos.at[c, 'umap2'], c)
        for c in list(labels.keys()) if c >= 0
    ]
    adjust_text(
        text_labels, ax=ax, x=df['umap1'], y=df['umap2'],
        force_points=(0.1, 0.1)
    )

    ax.legend(
        frameon=False, markerscale=5,
        scatterpoints=1, bbox_to_anchor=(0.96, 0.85))
    ax.set_xlabel('Comp. 1')
    ax.set_ylabel('Comp. 2')
    seaborn.despine(ax=ax, offset=0, trim=True)


def bayesian_cluster(cn_data,
                     n_states=MAX_CN, alpha=ALPHA,
                     prob_cn_change=0.8, value_ids=VALUE_IDS,
                     clustering_id=BHC_ID, debug=False, print_r=False):
    """
    Performs bayesian hierarchical clustering on copy-number data (defaults
    configured for HMMCopy)

    :param cn_data: `DataFrame` with columns: 'chr', 'start', 'end', 'copy',
    'state', 'cell_id'
    :param n_states: maximum allowed copy number in model
    :param alpha: dirichlet parameter, related to how many clusters are made
    :param prob_cn_change: model parameter, probability that copy number
    DOES NOT change from one bin to another. name is misleading
    :param value_ids: column names in `cn_data` to extract and return in
    `matrix_data`
    :param clustering_id: name of column in cn_data we want to cluster on

    :return: tuple of:
    linkage: `DataFrame` with columns:
        i: cluster index
        j: cluster index
        r_merge: r-value of merging i, j
        naive_dist: naive distance of merging i, j
        log_like: log-likelihood of merging i, j
        i_count: number of samples in i
        j_count: number of samples in j
    root: `TNode` representing root of tree
    cell_ids: cell_ids that correspond to rows of measurement
    matrix_data: `cn_data` columns `value_ids` in `MultiIndex` matrix form
    measurement: `clustering_id` values in matrix form
    """
    # TODO return measurement or allow calling of this function on measurement
    matrix_data, measurement, cell_ids = (
        cn_data_to_mat_data_ids(cn_data, data_id=clustering_id,
                                value_ids=value_ids))
    variances = get_variances(cn_data, matrix_data, n_states)
    no_nan_meas = np.nan_to_num(measurement)
    n_cells = measurement.shape[0]

    transmodel = {"kind": "twoparam", "e0": prob_cn_change,
                  "e1": 1 - prob_cn_change}

    clusters = [TNode([i], None, None, i,
                      0, alpha) for i in range(n_cells)]
    #def __init__(self, sample_inds, left_child, right_child, cluster_ind,
    #             pi=None, d=None, ll=None, tree_ll=None, log_r=None):
    [node.update_vars(measurement, variances, transmodel, alpha)
     for node in clusters]

    if debug:
        link_cols = DEBUG_LINKAGE_COLS
    else:
        link_cols = LINKAGE_COLS
    linkage = pd.DataFrame(data=None, columns=link_cols,
                           index=range(n_cells-1))
    li = 0
    # TODO can stop at 2 and merge the last 2 if it saves time
    cluster_map = {}
    while len(clusters) > 1:
        if debug:
            print(f"li {li}")
        r = np.empty((len(clusters), len(clusters)))
        r.fill(np.nan)
        next_level = [[None for i in range(len(clusters))]
                      for j in range(len(clusters))]
        naive_dist = np.empty((len(clusters), len(clusters)))

        for i, j in combinations(range(len(clusters)), 2):
            left_clst = clusters[i]
            right_clst = clusters[j]

            # (sample_inds, left_child, right_child, cluster_ind)
            merge_inds = clusters[i].sample_inds + clusters[j].sample_inds
            if str(merge_inds) not in cluster_map:
                merge_cluster = TNode(merge_inds, left_clst, right_clst, -1)
                merge_cluster.update_vars(measurement, variances, transmodel,
                                          alpha)
                cluster_map[str(merge_inds)] = merge_cluster
            else:
                merge_cluster = cluster_map[str(merge_inds)]

            r[i, j] = merge_cluster.log_r
            next_level[i][j] = merge_cluster

            naive_dist[i, j] = (
                pdist(no_nan_meas[merge_cluster.sample_inds, :]).min())

        max_r_flat_ind = np.nanargmax(r)
        i_max, j_max = np.unravel_index(max_r_flat_ind, r.shape)
        selected_cluster = next_level[i_max][j_max]
        if print_r:
            print(f"r at li: {li}\n{pd.DataFrame(r)}")
            print(f"i_max, j_max: {i_max}, {j_max}")
            print(f"left_cluster, {selected_cluster.left_child}")
            print(f"right_cluster, {selected_cluster.right_child}")

        selected_cluster.cluster_ind = n_cells + li
        left_ind = selected_cluster.left_child.cluster_ind
        right_ind = selected_cluster.right_child.cluster_ind

        link_row = [left_ind, right_ind, r.flatten()[max_r_flat_ind],
                    naive_dist[i_max, j_max], selected_cluster.ll,
                    len(clusters[i_max].sample_inds),
                    len(clusters[j_max].sample_inds)]
        if debug:
            link_row += debug_additions(selected_cluster)
        linkage.iloc[li] = link_row

        li += 1
        clusters[i_max] = selected_cluster
        del clusters[j_max]
        cluster_map.pop(str(selected_cluster.sample_inds))

    linkage["merge_count"] = linkage["i_count"] + linkage["j_count"]
    return linkage, clusters[0], cell_ids, matrix_data, measurement, variances


def debug_additions(selected_cluster):
    l = [
        selected_cluster.pi,
        selected_cluster.d,
        selected_cluster.cluster_ind,
        selected_cluster.sample_inds,
        selected_cluster.left_child.sample_inds,
        selected_cluster.right_child.sample_inds,
        selected_cluster.left_child.d,
        selected_cluster.right_child.d,
        selected_cluster.left_child.ll,
        selected_cluster.right_child.ll,
        selected_cluster.left_child.pi,
        selected_cluster.right_child.pi,
        selected_cluster.tree_ll,
        selected_cluster.left_child.tree_ll,
        selected_cluster.right_child.tree_ll,
    ]
    return l


def prune_cluster(fclustering, cell_ids, cn_data,
                  cluster_field_name="bhc_cluster_id", inplace=False):
    if not inplace:
        cn_data = cn_data.copy()
    cell_id_to_clst = {cell_ids[i]: fclustering[i]
                       for i in range(len(fclustering))}
    cn_data[cluster_field_name] = cn_data["cell_id"].map(cell_id_to_clst)
    return cn_data


def group_clusters(cn_data, clst_col, data_id="reads", sample_col="sample_id"):
    clusters = cn_data[clst_col].unique()
    cluster_cnds = [cn_data[cn_data[clst_col] == cl] for cl in clusters]
    cluster_mats = [cn_data_to_mat_data_ids(cnd, data_id)[1]
                    for cnd in cluster_cnds]

    samples = list(cn_data[sample_col].unique())
    sample_cnds = [cn_data[cn_data[sample_col] == s] for s in samples]
    sample_mats = [cn_data_to_mat_data_ids(cnd, data_id)[1]
                   for cnd in sample_cnds]

    corrs = np.zeros((len(cluster_mats), len(sample_mats)))
    for i in range(len(cluster_mats)):
        for j in range(len(sample_mats)):
            corr_mat = cdist(cluster_mats[i], sample_mats[j],
                             lambda u, v: abs(pearsonr(u, v)[0]))
            corrs[i, j] = np.mean(corr_mat)
            #corrs[i, j] = np.mean(cdist(cluster_mats[i], sample_mats[j],
            #                            metric="correlation"))

    row_max = np.argmax(corrs, 1)
    clst2sample = {clusters[i]: samples[row_max[i]]
                      for i in range(len(row_max))}
    cluster_samples = [clst2sample[cl] for cl in cn_data[clst_col]]

    return cluster_samples
    #return {'clusters': clusters, 'cluster_mats': cluster_mats,
    #        'samples': samples, 'sample_mats': sample_mats,
    #        "corrs": corrs, "cluster_samples": cluster_samples}


def correlation(u, v):
    return np.corrcoef(u, v)