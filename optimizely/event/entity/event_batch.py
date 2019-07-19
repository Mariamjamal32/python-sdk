# Copyright 2019 Optimizely
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


class EventBatch(object):
  def __init__(self, account_id, project_id, revision, client_name, client_version,
               anonymize_ip, enrich_decisions, visitors=None):
    self.account_id = account_id
    self.project_id = project_id
    self.revision = revision
    self.client_name = client_name
    self.client_version = client_version
    self.anonymize_ip = anonymize_ip
    self.enrich_decisions = enrich_decisions
    self.visitors = visitors
