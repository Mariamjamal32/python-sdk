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


class LogEvent(object):
  """ Representation of an event which can be sent to the Optimizely logging endpoint. """

  def __init__(self, url, params, http_verb=None, headers=None):
    self.url = url
    self.params = params
    self.http_verb = http_verb or 'GET'
    self.headers = headers