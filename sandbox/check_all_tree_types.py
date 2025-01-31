"""
This sandbox script runs one part of ModulesComplicatedAlgorithms over all the modules in YANG Catalog.
Script checks the tree type for each module and updates it if necessary.
"""
import sys
import time

import requests
import utility.log as log
from parseAndPopulate.modulesComplicatedAlgorithms import \
    ModulesComplicatedAlgorithms
from utility.create_config import create_config


def main():
    start = time.time()
    config = create_config()
    temp_dir = config.get('Directory-Section', 'temp', fallback='/var/yang/tmp')
    log_directory = config.get('Directory-Section', 'logs', fallback='/var/yang/logs')
    save_file_dir = config.get('Directory-Section', 'save-file-dir', fallback='/var/yang/all_modules')
    yang_models = config.get('Directory-Section', 'yang-models-dir', fallback='/var/yang/nonietf/yangmodels/yang')
    credentials = config.get('Secrets-Section', 'confd-credentials').strip('"').split(' ')
    json_ytree = config.get('Directory-Section', 'json-ytree', fallback='/var/yang/ytrees')
    yangcatalog_api_prefix = config.get('Web-Section', 'yangcatalog-api-prefix')

    LOGGER = log.get_logger('sandbox', '{}/sandbox.log'.format(log_directory))

    url = '{}/search/modules'.format(yangcatalog_api_prefix)
    LOGGER.info('Getting all the modules from: {}'.format(url))
    response = requests.get(url, headers={'Accept': 'application/json'})

    all_existing_modules = response.json()

    # Initialize ModulesComplicatedAlgorithms
    direc = '/var/yang/tmp'

    num_of_modules = len(all_existing_modules['module'])
    chunk_size = 100
    chunks = (num_of_modules - 1) // chunk_size + 1
    for i in range(chunks):
        try:
            LOGGER.info('Proccesing chunk {} out of {}'.format(i, chunks))
            batch = all_existing_modules['module'][i * chunk_size:(i + 1) * chunk_size]
            batch_modules = {'module': batch}

            recursion_limit = sys.getrecursionlimit()
            sys.setrecursionlimit(50000)
            complicated_algorithms = ModulesComplicatedAlgorithms(log_directory, yangcatalog_api_prefix, credentials,
                                                                  save_file_dir, direc, batch_modules, yang_models,
                                                                  temp_dir, json_ytree)
            complicated_algorithms.parse_non_requests()
            sys.setrecursionlimit(recursion_limit)
            complicated_algorithms.populate()
        except Exception:
            LOGGER.exception('Exception occured during running ModulesComplicatedAlgorithms')
            continue

    end = time.time()
    LOGGER.info('Populate took {} seconds with the main and complicated algorithm'.format(int(end - start)))


if __name__ == '__main__':
    main()
