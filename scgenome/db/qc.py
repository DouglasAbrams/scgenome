import os
import logging
import dbclients.tantalus
import datamanagement.transfer_files

import scgenome.loaders.align
import scgenome.loaders.hmmcopy
import scgenome.loaders.qc


def cache_qc_results(
        ticket_id,
        local_cache_directory,
        full_dataset=False,
        results_storage_name='singlecellresults',
    ):
    tantalus_api = dbclients.tantalus.TantalusApi()

    ticket_results = tantalus_api.list('results', analysis__jira_ticket=ticket_id)

    for results in ticket_results:
        logging.info(f'found results {results["id"]} with type {results["results_type"]} for ticket {ticket_id}')

        if full_dataset:
            csv_suffixes = ((None,None),)
        
        else:
            if results['results_type'] == 'alignment':
                csv_suffixes = scgenome.loaders.align.table_suffixes[results['results_version']] + ((None, 'metadata.yaml'),)

            elif results['results_type'] == 'hmmcopy':
                csv_suffixes = scgenome.loaders.hmmcopy.table_suffixes[results['results_version']] + ((None, 'metadata.yaml'),)

            elif results['results_type'] == 'annotation':
                csv_suffixes = scgenome.loaders.annotation.table_suffixes[results['results_version']] + ((None, 'metadata.yaml'),)

            elif results['results_type'] == 'cell_state_prediction':
                csv_suffixes = ((None,None),)

            else:
                continue

        for _, csv_suffix in csv_suffixes:
            filepaths = datamanagement.transfer_files.cache_dataset(
                tantalus_api,
                results['id'],
                'resultsdataset',
                results_storage_name,
                local_cache_directory,
                suffix_filter=csv_suffix,
            )

            if csv_suffix is not None and len(filepaths) != 1:
                raise Exception(f'found {len(filepaths)} filepaths for {csv_suffix}, results {results["id"]}')





def get_qc_data_from_filenames(annotation_metrics_list, hmmcopy_reads_list, hmmcopy_segs_list, 
    hmmcopy_metrics_list, alignment_metrics_list, gc_metrics_list, 
    sample_ids=None, additional_hmmcopy_reads_cols=None
):

    results_tables = {}

    data = zip(annotation_metrics_list, hmmcopy_reads_list, hmmcopy_segs_list, 
        hmmcopy_metrics_list, alignment_metrics_list, gc_metrics_list
    )

    for ann_metrics, hmm_reads, hmm_segs, hmm_metrics, align_metrics, gc_metrics in data:
        
        qc_results = scgenome.loaders.qc.load_qc_data_from_files(hmm_reads, hmm_segs, 
            hmm_metrics, align_metrics, gc_metrics, annotation_metrics=ann_metrics, 
            sample_id=sample_ids, additional_hmmcopy_reads_cols=additional_hmmcopy_reads_cols
        )

        results_tables = _aggregate_results_tables(results_tables, qc_results)

    results_tables = _concat_results_tables(results_tables)

    scgenome.utils.union_categories(results_tables.values())

    return results_tables


def get_qc_data(
        ticket_ids,
        local_directory,
        sample_ids=None,
        additional_hmmcopy_reads_cols=None,
        do_caching=False,
    ):

    results_tables = {}

    for ticket_id in ticket_ids:
        if do_caching:
            cache_qc_results(ticket_id, local_directory)

        ticket_directory = os.path.join(local_directory, ticket_id)

        ticket_results = scgenome.loaders.qc.load_qc_data(
            ticket_directory, sample_ids=sample_ids,
            additional_hmmcopy_reads_cols=additional_hmmcopy_reads_cols)

        results_tables = _aggregate_results_tables(results_tables, ticket_results)
   
    results_tables = _concat_results_tables(results_tables)

    scgenome.utils.union_categories(results_tables.values())

    return results_tables


def _concat_results_tables(results_tables):
    for table_name, table_data in results_tables.items():
        results_tables[table_name] = scgenome.utils.concat_with_categories(table_data)
    return results_tables


def _aggregate_results_tables(results_tables, ticket_results):
    for table_name, table_data in ticket_results.items():
        if table_name not in results_tables:
            results_tables[table_name] = []
        results_tables[table_name].append(table_data)
    
    return results_tables
