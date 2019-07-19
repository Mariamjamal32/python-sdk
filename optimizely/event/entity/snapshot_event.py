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


class SnapshotEvent(object):
  """ Class representing Snapshot Event. """

  def __init__(self, entity_id, uuid, key, timestamp, revenue=None, value=None, tags=None):
    self.entity_id = entity_id
    self.uuid = uuid
    self.key = key
    self.timestamp = timestamp
    self.revenue = revenue
    self.value = value
    self.tags = tags
