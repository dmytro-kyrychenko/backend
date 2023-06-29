# Copyright The IETF Trust 2023, All Rights Reserved
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

__author__ = 'Dmytro Kyrychenko'
__copyright__ = 'Copyright 2018 Cisco and its affiliates'
__license__ = 'Apache License, Version 2.0'
__email__ = 'dmytro.kyrychenko@pantheon.tech'

import glob
import json
import logging
import os

from opensearch_indexing.models.opensearch_indices import OpenSearchIndices
from opensearch_indexing.opensearch_manager import OpenSearchManager
from utility import log
from utility.create_config import create_config
from utility.util import validate_revision


def check_if_file_is_indexed(osm: OpenSearchManager, filename: str):
    name, revision = filename.split('.yang')[0].split('@')
    res = osm.get_module_by_name_revision(
        index=OpenSearchIndices.YINDEX,
        module={'name': name, 'revision': validate_revision(revision)},
    )
    return True if res else False


def check_if_file_is_cached(cache_data: dict, filename: str):
    return filename in cache_data.keys()


def find_unindexed_missing_modules(
    osm: OpenSearchManager,
    file_dir: str,
    cache_filename: str,
    logger: logging.Logger,
) -> list:
    # Getting info from cache files
    with open(cache_filename, 'r') as f:
        cached_data = json.load(f)
    logger.debug(f'read {cache_filename} which contains {cached_data}')

    # Processing .failed file if it exists
    if os.path.exists(f'{cache_filename}.failed'):
        with open(f'{cache_filename}.failed', 'r') as f:
            cached_failed_data = json.load(f)
        cached_data.update(cached_failed_data)
        logger.debug(f'read {cache_filename}.failed which contains {cached_failed_data}')

    # Removing organization from the keyname
    data = {k.split('/')[0]: v for k, v in cached_data.items()}
    logger.debug(f'processed data looks like this: {data}')

    # Looping over every file in target file_dir
    files = glob.glob(os.path.join(file_dir, '**/*.yang'), recursive=True)
    logger.debug(f'all .yang files in target directory: {files}')

    res = []
    for file in files:
        filename = os.path.basename(file)
        if check_if_file_is_indexed(osm, filename):
            continue
        if check_if_file_is_cached(data, filename):
            continue

        # Adding to list of untracked files
        res.append(file)
    return res


def add_missing_modules_to_opensearch(logger):
    for doc in missing_files:
        opensearch_manager.index_module(index=OpenSearchIndices.YINDEX, document=doc)


if __name__ == '__main__':
    config = create_config()
    log_directory = config.get('Directory-Section', 'logs')
    cache_filename = config.get('Directory-Section', 'changes-cache')
    logger = log.get_logger('index_missing_files', os.path.join(log_directory, 'index_missing_files.log'))

    opensearch_manager = OpenSearchManager()

    # Locating all of the unindexed modules, that are also not in cache file
    missing_files = find_unindexed_missing_modules(
        osm=opensearch_manager,
        file_dir='/var/yang/all_modules',
        cache_filename=cache_filename,
        logger=logger,
    )
    logger.info(f'missing_files: {missing_files}')
    print('missing files:')
    print(missing_files)

    # Adding missing files to opensearch yindex
    # add_missing_modules_to_opensearch(logger)
