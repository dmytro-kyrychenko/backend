# Copyright The IETF Trust 2022, All Rights Reserved
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

__author__ = 'Slavomir Mazur'
__copyright__ = 'Copyright The IETF Trust 2022, All Rights Reserved'
__license__ = 'Apache License, Version 2.0'
__email__ = 'slavomir.mazur@pantheon.tech'

"""
This script contains functionality,
which re-index Elasticsearch indices
after ES update from version 6.8 to
version 7.10 (done in April 2022).
"""

import time

import utility.log as log
from elasticsearchIndexing.es_manager import ESManager
from elasticsearchIndexing.models.es_indices import ESIndices
from utility.create_config import create_config
from utility.staticVariables import SDOS


def _track_progress(es_manager: ESManager, task_id: str) -> None:
    while True:
        task_info = es_manager.es.tasks.get(task_id=task_id)
        LOGGER.info('{} out of {}'.format(
            task_info['task']['status']['updated'],
            task_info['task']['status']['total'])
        )
        if task_info['completed']:
            break
        time.sleep(10)
    LOGGER.info('Updating by query completed')


def main():
    config = create_config()
    log_directory = config.get('Directory-Section', 'logs', fallback='/var/yang/logs')

    global LOGGER
    LOGGER = log.get_logger('es_reindex', '{}/sandbox.log'.format(log_directory))
    # ----------------------------------------------------------------------------------------------
    # INIT ALL INDICES
    # ----------------------------------------------------------------------------------------------
    es_manager = ESManager()
    for index in ESIndices:
        if index == ESIndices.TEST:
            continue
        if not es_manager.index_exists(index):
            create_result = es_manager.create_index(index)
            LOGGER.info(create_result)
    # ----------------------------------------------------------------------------------------------
    # GET ALL MODULES FROM 'modules' INDEX
    # ----------------------------------------------------------------------------------------------
    all_es_modules = {}
    if es_manager.index_exists(ESIndices.MODULES):
        all_es_modules = es_manager.match_all(ESIndices.MODULES)
    LOGGER.info('Total number of modules retreived from "modules" index: {}'.format(len(all_es_modules)))
    # ----------------------------------------------------------------------------------------------
    # FILL 'autocomplete' INDEX
    # ----------------------------------------------------------------------------------------------
    autocomplete_count = es_manager.get_documents_count(ESIndices.AUTOCOMPLETE)
    modules_count = es_manager.get_documents_count(ESIndices.MODULES)
    if modules_count > autocomplete_count:
        # If data from 'modules' index are missing in 'autocomplete' index
        for module in all_es_modules.values():
            try:
                name = module['name']
            except KeyError:
                name = module['module']
            document = {
                'name': name,
                'revision': module['revision'],
                'organization': module['organization']
            }
            es_manager.delete_from_index(ESIndices.AUTOCOMPLETE, document)
            index_result = es_manager.index_module(ESIndices.AUTOCOMPLETE, document)
            if index_result['result'] != 'created':
                LOGGER.info(index_result)
    # ----------------------------------------------------------------------------------------------
    # PUT MAPPING IN 'yindex' INDEX
    # ----------------------------------------------------------------------------------------------
    yindex_mapping = es_manager.get_index_mapping(ESIndices.YINDEX)
    sdo_property = None
    try:
        sdo_property = yindex_mapping['yindex']['mappings']['properties']['sdo']
    except KeyError:
        LOGGER.info('sdo property not defined yet')
    if not sdo_property:
        update_mapping = {
            'properties': {
                'sdo': {'type': 'boolean'}
            }
        }
        put_result = es_manager.put_index_mapping(ESIndices.YINDEX, update_mapping)
        LOGGER.info('Put mapping result:\n{}'.format(put_result))

        # ----------------------------------------------------------------------------------------------
        # SET 'sdo' FIELD FOR NON-SDOS
        # ----------------------------------------------------------------------------------------------
        update_query = {
            'script': 'ctx._source.sdo = false',
            'query': {
                'bool': {
                    'must_not': {
                        'terms': {
                            'organization.keyword': SDOS
                        }
                    }
                }

            }
        }
        update_result = es_manager.es.update_by_query(
            index=ESIndices.YINDEX.value, body=update_query, conflicts='proceed', wait_for_completion=False)
        task_id = update_result.get('task')
        _track_progress(es_manager, task_id)
        # ----------------------------------------------------------------------------------------------
        # SET 'sdo' FIELD FOR SDOS
        # ----------------------------------------------------------------------------------------------
        update_query = {
            'script': 'ctx._source.sdo = true',
            'query': {
                'terms': {
                    'organization.keyword': SDOS
                }
            }
        }
        update_result = es_manager.es.update_by_query(
            index=ESIndices.YINDEX.value, body=update_query, conflicts='proceed', wait_for_completion=False)
        task_id = update_result.get('task')
        _track_progress(es_manager, task_id)


if __name__ == '__main__':
    main()
