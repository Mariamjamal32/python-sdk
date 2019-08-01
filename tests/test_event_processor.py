# Copyright 2019, Optimizely
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
import json
import mock
import time
from datetime import timedelta
from six.moves import queue

from . import base
from optimizely.logger import SimpleLogger
from optimizely.event.log_event import LogEvent
from optimizely.event.entity.visitor import Visitor
from optimizely.event.entity.decision import Decision
from optimizely.event.event_factory import EventFactory
from optimizely.event.user_event_factory import UserEventFactory
from optimizely.event.event_processor import BatchEventProcessor
from optimizely.event.event_processor import ForwardingEventProcessor
from optimizely.helpers import enums


class CanonicalEvent(object):

  def __init__(self, experiment_id, variation_id, event_name, visitor_id, attributes, tags):
    self._experiment_id = experiment_id
    self._variation_id = variation_id
    self._event_name = event_name
    self._visitor_id = visitor_id
    self._attributes = attributes or {}
    self._tags = tags or {}

  def __eq__(self, other):
    if other is None:
      return False

    return (self._experiment_id == other._experiment_id and
                 self._variation_id == other._variation_id and
                 self._event_name == other._event_name and
                 self._visitor_id == other._visitor_id and
                 self._attributes == other._attributes and
                 self._tags == other._tags)


class TestEventDispatcher(object):

  IMPRESSION_EVENT_NAME = 'campaign_activated'

  def __init__(self, countdown_event=None):
    self.countdown_event = countdown_event
    self.expected_events = list()
    self.actual_events = list()

  def compare_events(self):
    if len(self.expected_events) != len(self.actual_events):
      return False

    for index, event in enumerate(self.expected_events):
      expected_event = event
      actual_event = self.actual_events[index]

      if not expected_event == actual_event:
        return False

    return True

  def dispatch_event(self, actual_log_event):
    visitors = []
    log_event_params = json.loads(actual_log_event.params)

    if 'visitors' in log_event_params:

      for visitor in log_event_params['visitors']:
        visitor_instance = Visitor(**visitor)
        visitors.append(visitor_instance)

    if len(visitors) == 0:
      return

    for visitor in visitors:
      for snapshot in visitor.snapshots:
        decisions = snapshot.get('decisions') or [Decision(None, None, None)]
        for decision in decisions:
          for event in snapshot.get('events'):
            attributes = visitor.attributes

            self.actual_events.append(CanonicalEvent(decision.experiment_id, decision.variation_id,
                                                     event.get('key'), visitor.visitor_id, attributes,
                                                     event.get('event_tags')))

  def expect_impression(self, experiment_id, variation_id, user_id, attributes=None):
    self._expect(experiment_id, variation_id, self.IMPRESSION_EVENT_NAME, user_id, None)

  def expect_conversion(self, event_name, user_id, attributes=None, event_tags=None):
    self._expect(None, None, event_name, user_id, attributes, event_tags)

  def _expect(self, experiment_id, variation_id, event_name, visitor_id, attributes, tags):
    expected_event = CanonicalEvent(experiment_id, variation_id, event_name, visitor_id, attributes, tags)
    self.expected_events.append(expected_event)


class BatchEventProcessorTest(base.BaseTest):

  DEFAULT_QUEUE_CAPACITY = 1000
  MAX_BATCH_SIZE = 10
  MAX_DURATION_MS = 1000
  MAX_TIMEOUT_INTERVAL_MS = 5000

  def setUp(self, *args, **kwargs):
    base.BaseTest.setUp(self, 'config_dict_with_multiple_experiments')
    self.test_user_id = 'test_user'
    self.event_name = 'test_event'
    self.event_queue = queue.Queue(maxsize=self.DEFAULT_QUEUE_CAPACITY)
    self.optimizely.logger = SimpleLogger()
    self.notification_center = self.optimizely.notification_center

  def tearDown(self):
    self._event_processor.stop()

  def _build_conversion_event(self, event_name, project_config=None):
    config = project_config or self.project_config
    return UserEventFactory.create_conversion_event(config, event_name, self.test_user_id, {}, {})

  def _set_event_processor(self, event_dispatcher, logger):
    self._event_processor = BatchEventProcessor(event_dispatcher,
                                                 logger,
                                                 True,
                                                 self.event_queue,
                                                 self.optimizely.notification_center,
                                                 self.MAX_BATCH_SIZE,
                                                 timedelta(milliseconds=self.MAX_DURATION_MS),
                                                 timedelta(milliseconds=self.MAX_TIMEOUT_INTERVAL_MS)
                                                )

  def test_drain_on_close(self):
    event_dispatcher = TestEventDispatcher()

    with mock.patch.object(self.optimizely, 'logger') as mock_config_logging:
      self._set_event_processor(event_dispatcher, mock_config_logging)

    user_event = self._build_conversion_event(self.event_name)
    self._event_processor.process(user_event)
    mock_config_logging.debug.assert_called_with('Received user_event: ' + str(user_event))
    event_dispatcher.expect_conversion(self.event_name, self.test_user_id)

    time.sleep(5)

    self.assertStrictTrue(event_dispatcher.compare_events())
    self.assertEqual(0, self._event_processor.event_queue.qsize())
    mock_config_logging.debug.assert_called_with('Deadline exceeded; flushing current batch.')

  def test_flush_on_max_timeout(self):
    event_dispatcher = TestEventDispatcher()

    with mock.patch.object(self.optimizely, 'logger') as mock_config_logging:
      self._set_event_processor(event_dispatcher, mock_config_logging)

    user_event = self._build_conversion_event(self.event_name)
    self._event_processor.process(user_event)
    mock_config_logging.debug.assert_called_with('Received user_event: ' + str(user_event))
    event_dispatcher.expect_conversion(self.event_name, self.test_user_id)

    time.sleep(1.5)

    self.assertStrictTrue(event_dispatcher.compare_events())
    self.assertEqual(0, self._event_processor.event_queue.qsize())
    mock_config_logging.debug.assert_called_with('Deadline exceeded; flushing current batch.')

  def test_flush_max_batch_size(self):
    event_dispatcher = TestEventDispatcher()

    with mock.patch.object(self.optimizely, 'logger') as mock_config_logging:
      self._set_event_processor(event_dispatcher, mock_config_logging)

    for i in range(0, self.MAX_BATCH_SIZE):
      user_event = self._build_conversion_event(self.event_name)
      self._event_processor.process(user_event)
      mock_config_logging.debug.assert_called_with('Received user_event: ' + str(user_event))
      event_dispatcher.expect_conversion(self.event_name, self.test_user_id)

    time.sleep(1)

    self.assertStrictTrue(event_dispatcher.compare_events())
    self.assertEqual(0, self._event_processor.event_queue.qsize())

  def test_flush(self):
    event_dispatcher = TestEventDispatcher()

    with mock.patch.object(self.optimizely, 'logger') as mock_config_logging:
      self._set_event_processor(event_dispatcher, mock_config_logging)

    user_event = self._build_conversion_event(self.event_name)
    self._event_processor.process(user_event)
    mock_config_logging.debug.assert_called_with('Received user_event: ' + str(user_event))
    self._event_processor.flush()
    event_dispatcher.expect_conversion(self.event_name, self.test_user_id)

    self._event_processor.process(user_event)
    mock_config_logging.debug.assert_called_with('Received user_event: ' + str(user_event))
    self._event_processor.flush()
    event_dispatcher.expect_conversion(self.event_name, self.test_user_id)

    time.sleep(1.5)

    self.assertStrictTrue(event_dispatcher.compare_events())
    self.assertEqual(0, self._event_processor.event_queue.qsize())

  def test_flush_on_mismatch_revision(self):
    event_dispatcher = TestEventDispatcher()

    with mock.patch.object(self.optimizely, 'logger') as mock_config_logging:
      self._set_event_processor(event_dispatcher, mock_config_logging)

    self.project_config.revision = 1
    self.project_config.project_id = 'X'

    user_event_1 = self._build_conversion_event(self.event_name, self.project_config)
    self._event_processor.process(user_event_1)
    mock_config_logging.debug.assert_called_with('Received user_event: ' + str(user_event_1))
    event_dispatcher.expect_conversion(self.event_name, self.test_user_id)

    self.project_config.revision = 2
    self.project_config.project_id = 'X'

    user_event_2 = self._build_conversion_event(self.event_name, self.project_config)
    self._event_processor.process(user_event_2)
    mock_config_logging.debug.assert_called_with('Received user_event: ' + str(user_event_2))
    event_dispatcher.expect_conversion(self.event_name, self.test_user_id)

    time.sleep(1.5)

    self.assertStrictTrue(event_dispatcher.compare_events())
    self.assertEqual(0, self._event_processor.event_queue.qsize())

  def test_flush_on_mismatch_project_id(self):
    event_dispatcher = TestEventDispatcher()

    with mock.patch.object(self.optimizely, 'logger') as mock_config_logging:
      self._set_event_processor(event_dispatcher, mock_config_logging)

    self.project_config.revision = 1
    self.project_config.project_id = 'X'

    user_event_1 = self._build_conversion_event(self.event_name, self.project_config)
    self._event_processor.process(user_event_1)
    mock_config_logging.debug.assert_called_with('Received user_event: ' + str(user_event_1))
    event_dispatcher.expect_conversion(self.event_name, self.test_user_id)

    self.project_config.revision = 1
    self.project_config.project_id = 'Y'

    user_event_2 = self._build_conversion_event(self.event_name, self.project_config)
    self._event_processor.process(user_event_2)
    mock_config_logging.debug.assert_called_with('Received user_event: ' + str(user_event_2))
    event_dispatcher.expect_conversion(self.event_name, self.test_user_id)

    time.sleep(1.5)

    self.assertStrictTrue(event_dispatcher.compare_events())
    self.assertEqual(0, self._event_processor.event_queue.qsize())

  def test_stop_and_start(self):
    event_dispatcher = TestEventDispatcher()

    with mock.patch.object(self.optimizely, 'logger') as mock_config_logging:
      self._set_event_processor(event_dispatcher, mock_config_logging)

    user_event = self._build_conversion_event(self.event_name, self.project_config)
    self._event_processor.process(user_event)
    mock_config_logging.debug.assert_called_with('Received user_event: ' + str(user_event))
    event_dispatcher.expect_conversion(self.event_name, self.test_user_id)

    time.sleep(1.5)

    self.assertStrictTrue(event_dispatcher.compare_events())
    self._event_processor.stop()

    self._event_processor.process(user_event)
    mock_config_logging.debug.assert_called_with('Received user_event: ' + str(user_event))
    event_dispatcher.expect_conversion(self.event_name, self.test_user_id)

    self._event_processor.start()
    self.assertStrictTrue(self._event_processor.is_started)

    self._event_processor.stop()
    mock_config_logging.warning.assert_called_with('Stopping Scheduler.')
    self.assertStrictFalse(self._event_processor.is_started)

    self.assertEqual(0, self._event_processor.event_queue.qsize())

  def test_notification_center(self):

    mock_event_dispatcher = mock.Mock()
    callback_hit = [False]

    def on_log_event(log_event):
      self.assertStrictTrue(isinstance(log_event, LogEvent))
      callback_hit[0] = True

    self.optimizely.notification_center.add_notification_listener(
      enums.NotificationTypes.LOG_EVENT, on_log_event
    )

    with mock.patch.object(self.optimizely, 'logger') as mock_config_logging:
      self._set_event_processor(mock_event_dispatcher, mock_config_logging)

    user_event = self._build_conversion_event(self.event_name, self.project_config)
    self._event_processor.process(user_event)

    self._event_processor.stop()

    self.assertEqual(True, callback_hit[0])
    self.assertEqual(1, len(self.optimizely.notification_center.notification_listeners[
      enums.NotificationTypes.LOG_EVENT
    ]))


class TestForwardingEventDispatcher(object):

  def __init__(self, is_updated=False):
    self.is_updated = is_updated

  def dispatch_event(self, log_event):
    if log_event.http_verb == 'POST' and log_event.url == EventFactory.EVENT_ENDPOINT:
      self.is_updated = True
    return self.is_updated


class ForwardingEventProcessorTest(base.BaseTest):

  def setUp(self, *args, **kwargs):
    base.BaseTest.setUp(self, 'config_dict_with_multiple_experiments')
    self.test_user_id = 'test_user'
    self.event_name = 'test_event'
    self.optimizely.logger = SimpleLogger()
    self.notification_center = self.optimizely.notification_center
    self.event_dispatcher = TestForwardingEventDispatcher(is_updated=False)

    with mock.patch.object(self.optimizely, 'logger') as mock_config_logging:
      self._event_processor = ForwardingEventProcessor(self.event_dispatcher,
                                                        mock_config_logging,
                                                        self.notification_center
                                                       )

  def _build_conversion_event(self, event_name):
    return UserEventFactory.create_conversion_event(self.project_config,
                                                    event_name,
                                                    self.test_user_id,
                                                    {},
                                                    {}
                                                    )

  def test_event_processor__dispatch_raises_exception(self):
    """ Test that process logs dispatch failure gracefully. """

    user_event = self._build_conversion_event(self.event_name)
    log_event = EventFactory.create_log_event(user_event, self.optimizely.logger)

    with mock.patch.object(self.optimizely, 'logger') as mock_client_logging, \
        mock.patch.object(self.event_dispatcher, 'dispatch_event',
                          side_effect=Exception('Failed to send.')):

      event_processor = ForwardingEventProcessor(self.event_dispatcher, mock_client_logging, self.notification_center)
      event_processor.process(user_event)

    mock_client_logging.exception.assert_called_once_with(
      'Error dispatching event: ' + str(log_event) + ' Failed to send.'
    )

  def test_event_processor__with_test_event_dispatcher(self):
    user_event = self._build_conversion_event(self.event_name)
    self._event_processor.process(user_event)
    self.assertStrictTrue(self.event_dispatcher.is_updated)

  def test_notification_center(self):

    callback_hit = [False]

    def on_log_event(log_event):
      self.assertStrictTrue(isinstance(log_event, LogEvent))
      callback_hit[0] = True

    self.optimizely.notification_center.add_notification_listener(
      enums.NotificationTypes.LOG_EVENT, on_log_event
    )

    user_event = self._build_conversion_event(self.event_name)
    self._event_processor.process(user_event)

    self.assertEqual(True, callback_hit[0])
    self.assertEqual(1, len(self.optimizely.notification_center.notification_listeners[
      enums.NotificationTypes.LOG_EVENT
    ]))