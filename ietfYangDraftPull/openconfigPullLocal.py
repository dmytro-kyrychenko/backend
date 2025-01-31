# Copyright The IETF Trust 2019, All Rights Reserved
# Copyright 2018 Cisco and its affiliates
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

"""
Cronjob tool that automatically runs populate.py
for all new openconfig modules.
"""

__author__ = 'Miroslav Kovac'
__copyright__ = 'Copyright 2018 Cisco and its affiliates, Copyright The IETF Trust 2019, All Rights Reserved'
__license__ = 'Apache License, Version 2.0'
__email__ = 'miroslav.kovac@pantheon.tech'

import json
import os
import time
import typing as t
from glob import glob

import requests
import utility.log as log
from utility.create_config import create_config
from utility.scriptConfig import Arg, BaseScriptConfig
from utility.staticVariables import JobLogStatuses, json_headers
from utility.util import job_log, resolve_revision

from ietfYangDraftPull import draftPullUtility

current_file_basename = os.path.basename(__file__)


class ScriptConfig(BaseScriptConfig):

    def __init__(self):
        help = 'Run populate script on all openconfig files to parse all modules and populate the' \
               ' metadata to yangcatalog if there are any new. This runs as a daily cronjob'
        args: t.List[Arg] = [{
            'flag': '--config-path',
            'help': 'Set path to config file',
            'type': str,
            'default': os.environ['YANGCATALOG_CONFIG_PATH']
        }]
        super().__init__(help, args, None if __name__ == '__main__' else [])


def main(scriptConf=None):
    start_time = int(time.time())
    if scriptConf is None:
        scriptConf = ScriptConfig()
    args = scriptConf.args

    config_path = args.config_path
    config = create_config(config_path)
    credentials = config.get('Secrets-Section', 'confd-credentials').strip('"').split(' ')
    config_name = config.get('General-Section', 'repo-config-name')
    config_email = config.get('General-Section', 'repo-config-email')
    log_directory = config.get('Directory-Section', 'logs')
    temp_dir = config.get('Directory-Section', 'temp')
    openconfig_repo_url = config.get('Web-Section', 'openconfig-models-repo-url')
    yangcatalog_api_prefix = config.get('Web-Section', 'yangcatalog-api-prefix')

    LOGGER = log.get_logger('openconfigPullLocal', f'{log_directory}/jobs/openconfig-pull.log')
    LOGGER.info('Starting Cron job openconfig pull request local')
    job_log(start_time, temp_dir, status=JobLogStatuses.IN_PROGRESS, filename=current_file_basename)

    commit_author = {
        'name': config_name,
        'email': config_email
    }
    repo = draftPullUtility.clone_forked_repository(openconfig_repo_url, commit_author, LOGGER)
    assert repo
    modules = []
    try:
        yang_files = glob(f'{repo.local_dir}/release/models/**/*.yang', recursive=True)
        for yang_file in yang_files:
            basename = os.path.basename(yang_file)
            name = basename.split('.')[0].split('@')[0]
            revision = resolve_revision(yang_file)
            path = yang_file.split(f'{repo.local_dir}/')[-1]
            module = {
                'generated-from': 'not-applicable',
                'module-classification': 'unknown',
                'name': name,
                'revision': revision,
                'organization': 'openconfig',
                'source-file': {
                    'owner': 'openconfig',
                    'path': path,
                    'repository': 'public'
                }
            }
            modules.append(module)
        data = json.dumps({'modules': {'module': modules}})
    except Exception as e:
        LOGGER.exception('Exception found while running openconfigPullLocal script')
        job_log(start_time, temp_dir, error=str(e), status=JobLogStatuses.FAIL, filename=current_file_basename)
        raise e
    LOGGER.debug(data)
    api_path = f'{yangcatalog_api_prefix}/modules'
    response = requests.put(api_path, data, auth=(credentials[0], credentials[1]), headers=json_headers)

    status_code = response.status_code
    payload = json.loads(response.text)
    if status_code < 200 or status_code > 299:
        e = f'PUT /api/modules responsed with status code {status_code}'
        job_log(start_time, temp_dir, error=str(e), status=JobLogStatuses.FAIL, filename=current_file_basename)
        LOGGER.info('Job finished, but an error occured while sending PUT to /api/modules')
    else:
        messages = [
            {'label': 'Job ID', 'message': payload['job-id']}
        ]
        job_log(start_time, temp_dir, messages=messages, status=JobLogStatuses.SUCCESS, filename=current_file_basename)
        LOGGER.info('Job finished successfully')


if __name__ == '__main__':
    main()
