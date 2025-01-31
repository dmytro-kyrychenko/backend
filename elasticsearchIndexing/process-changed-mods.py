# Copyright The IETF Trust 2021, All Rights Reserved
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

__author__ = 'Miroslav Kovac, Joe Clarke'
__copyright__ = 'Copyright 2018 Cisco and its affiliates'
__license__ = 'Apache License, Version 2.0'
__email__ = 'miroslav.kovac@pantheon.tech, jclarke@cisco.com'

import argparse
import json
import logging
import os
import shutil
import sys
import typing as t

import requests
from utility import log, repoutil
from utility.create_config import create_config
from utility.scriptConfig import Arg, BaseScriptConfig
from utility.util import fetch_module_by_schema, validate_revision

from elasticsearchIndexing.build_yindex import build_indices
from elasticsearchIndexing.es_manager import ESManager
from elasticsearchIndexing.models.es_indices import ESIndices


class ScriptConfig(BaseScriptConfig):

    def __init__(self):
        help = 'Process changed modules in a git repo'
        args: t.List[Arg] = [
            {
                'flag': '--config-path',
                'help': 'Set path to config file',
                'type': str,
                'default': os.environ['YANGCATALOG_CONFIG_PATH']
            },
        ]
        super().__init__(help, args, None if __name__ == '__main__' else [])


class ProcessChangedMods:
    def __init__(self, script_config: BaseScriptConfig):
        self.args = script_config.args
        self.config = create_config(self.args.config_path)
        self.log_directory = self.config.get('Directory-Section', 'logs')
        self.yang_models = self.config.get('Directory-Section', 'yang-models-dir')
        self.changes_cache_path = self.config.get('Directory-Section', 'changes-cache')
        self.failed_changes_cache_path = self.config.get('Directory-Section', 'changes-cache-failed')
        self.delete_cache_path = self.config.get('Directory-Section', 'delete-cache')
        self.lock_file = self.config.get('Directory-Section', 'lock')
        self.lock_file_cron = self.config.get('Directory-Section', 'lock-cron')
        self.json_ytree = self.config.get('Directory-Section', 'json-ytree')
        self.save_file_dir = self.config.get('Directory-Section', 'save-file-dir')

        self.logger = log.get_logger(
            'process_changed_mods',
            os.path.join(self.log_directory, 'process-changed-mods.log'),
        )

    def start_processing_changed_mods(self):
        self.logger.info('Starting process-changed-mods.py script')

        if os.path.exists(self.lock_file) or os.path.exists(self.lock_file_cron):
            # we can exist since this is run by cronjob every 3 minutes of every day
            self.logger.warning('Temporary lock file used by something else. Exiting script !!!')
            sys.exit()
        self._create_lock_files()

        self.changes_cache = self._load_changes_cache(self.changes_cache_path)
        self.delete_cache = self._load_delete_cache(self.delete_cache_path)

        if not self.changes_cache and not self.delete_cache:
            self.logger.info('No new modules are added or removed. Exiting script!!!')
            os.unlink(self.lock_file)
            os.unlink(self.lock_file_cron)
            sys.exit()

        self._initialize_es_manager()

        self.logger.info('Running cache files backup')
        self._backup_cache_files(self.delete_cache_path)
        self._backup_cache_files(self.changes_cache_path)
        os.unlink(self.lock_file)

        if self.delete_cache:
            self._delete_modules_from_es()
        if self.changes_cache:
            self._change_modules_in_es()

        os.unlink(self.lock_file_cron)
        self.logger.info('Job finished successfully')

    def _create_lock_files(self):
        try:
            open(self.lock_file, 'w').close()
            open(self.lock_file_cron, 'w').close()
        except Exception:
            os.unlink(self.lock_file)
            os.unlink(self.lock_file_cron)
            self.logger.error('Temporary lock file could not be created although it is not locked')
            sys.exit()

    def _initialize_es_manager(self):
        self.es_manager = ESManager()
        self.logger.info('Trying to initialize Elasticsearch indices')
        for index in ESIndices:
            if self.es_manager.index_exists(index):
                continue
            create_result = self.es_manager.create_index(index)
            self.logger.info(f'Index {index.value} created with message:\n{create_result}')
        logging.getLogger('elasticsearch').setLevel(logging.ERROR)

    def _delete_modules_from_es(self):
        for module in self.delete_cache:
            name, rev_org = module.split('@')
            revision, organization = rev_org.split('/')
            revision = validate_revision(revision)
            self.logger.info(f'Deleting {module} from es indices')
            module = {
                'name': name,
                'revision': revision,
                'organization': organization,
            }
            self.es_manager.delete_from_indices(module)

    def _change_modules_in_es(self):
        recursion_limit = sys.getrecursionlimit()
        sys.setrecursionlimit(50000)
        try:
            for module_count, (module_key, module_path) in enumerate(self.changes_cache.items(), 1):
                name, rev_org = module_key.split('@')
                revision, organization = rev_org.split('/')
                revision = validate_revision(revision)
                name_revision = f'{name}@{revision}'

                module = {
                    'name': name,
                    'revision': revision,
                    'organization': organization,
                    'path': module_path
                }
                self.logger.info(
                    f'yindex on module {name_revision}. module {module_count} out of {len(self.changes_cache)}'
                )

                try:
                    self._check_file_availability(module)
                    build_indices(self.es_manager, module, self.save_file_dir, self.json_ytree, self.logger)
                except Exception:
                    self.logger.exception(f'Problem while processing module {module_key}')
                    try:
                        with open(self.failed_changes_cache_path, 'r') as reader:
                            failed_modules = json.load(reader)
                    except (FileNotFoundError, json.decoder.JSONDecodeError):
                        failed_modules = {}
                    if module_key not in failed_modules:
                        failed_modules[module_key] = module_path
                    with open(self.failed_changes_cache_path, 'w') as writer:
                        json.dump(failed_modules, writer)
        except Exception:
            sys.setrecursionlimit(recursion_limit)
            os.unlink(self.lock_file_cron)
            self.logger.exception('Error while running build_yindex.py script')
            self.logger.info('Job failed execution')
            sys.exit()

        sys.setrecursionlimit(recursion_limit)

    def _load_changes_cache(self, changes_cache_path: str):
        changes_cache = {}

        try:
            with open(changes_cache_path, 'r') as reader:
                changes_cache = json.load(reader)
        except (FileNotFoundError, json.decoder.JSONDecodeError):
            with open(changes_cache_path, 'w') as writer:
                json.dump({}, writer)

        return changes_cache

    def _load_delete_cache(self, delete_cache_path: str):
        delete_cache = []

        try:
            with open(delete_cache_path, 'r') as reader:
                delete_cache = json.load(reader)
        except (FileNotFoundError, json.decoder.JSONDecodeError):
            with open(delete_cache_path, 'w') as writer:
                json.dump([], writer)

        return delete_cache

    def _backup_cache_files(self, cache_path: str):
        shutil.copyfile(cache_path, f'{cache_path}.bak')
        empty = {}
        if 'deletes' in cache_path:
            empty = []
        with open(cache_path, 'w') as writer:
            json.dump(empty, writer)

    def _check_file_availability(self, module: dict):
        if os.path.isfile(module['path']):
            return
        url = (
            'https://yangcatalog.org/api/search/modules/'
            f'{module["name"]},{module["revision"]},{module["organization"]}'
        )
        try:
            module_detail = requests.get(url).json().get('module', [])
            schema = module_detail[0].get('schema')
            result = fetch_module_by_schema(schema, module['path'])
            if not result:
                raise Exception
            self.logger.info('File content successfully retrieved from GitHub using module schema')
        except Exception:
            raise Exception(f'Unable to retrieve content of {module["name"]}@{module["revision"]}')


def main(script_config: BaseScriptConfig = ScriptConfig()):
    ProcessChangedMods(script_config).start_processing_changed_mods()


if __name__ == '__main__':
    main()
