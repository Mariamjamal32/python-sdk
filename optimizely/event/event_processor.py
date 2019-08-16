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

import abc
import threading
import time

from datetime import timedelta
from six.moves import queue

from .entity.user_event import UserEvent
from .event_factory import EventFactory
from ..closeable import Closeable
from ..event_dispatcher import EventDispatcher as default_event_dispatcher
from ..helpers import enums
from ..logger import NoOpLogger

ABC = abc.ABCMeta('ABC', (object,), {'__slots__': ()})


class EventProcessor(ABC):
  """ Class encapsulating event_processor functionality. Override with your own processor
  providing process method. """

  @abc.abstractmethod
  def process(user_event):
    pass


class BatchEventProcessor(EventProcessor, Closeable):
  """
  BatchEventProcessor is a batched implementation of the EventProcessor.

  The BatchEventProcessor maintains a single consumer thread that pulls events off of
  the blocking queue and buffers them for either a configured batch size or for a
  maximum duration before the resulting LogEvent is sent to the EventDispatcher.
  """

  _DEFAULT_QUEUE_CAPACITY = 1000
  _DEFAULT_BATCH_SIZE = 10
  _DEFAULT_FLUSH_INTERVAL = timedelta(seconds=30)
  _DEFAULT_TIMEOUT_INTERVAL = timedelta(seconds=5)
  _SHUTDOWN_SIGNAL = object()
  _FLUSH_SIGNAL = object()
  LOCK = threading.Lock()

  def __init__(self,
                event_dispatcher,
                logger,
                default_start=False,
                event_queue=None,
                batch_size=None,
                flush_interval=None,
                timeout_interval=None,
                notification_center=None):
    self.event_dispatcher = event_dispatcher or default_event_dispatcher
    self.logger = logger or NoOpLogger()
    self.event_queue = event_queue or queue.Queue(maxsize=self._DEFAULT_QUEUE_CAPACITY)
    self.batch_size = batch_size if batch_size is not None and batch_size > 0 else self._DEFAULT_BATCH_SIZE
    self.flush_interval = timedelta(milliseconds=flush_interval) if flush_interval is not None and flush_interval > 0 \
                            else self._DEFAULT_FLUSH_INTERVAL
    self.timeout_interval = timedelta(milliseconds=timeout_interval) if timeout_interval is not None and \
                            timeout_interval > 0 else self._DEFAULT_TIMEOUT_INTERVAL
    self.notification_center = notification_center
    self._disposed = False
    self._is_started = False
    self._current_batch = list()

    if default_start is True:
      self.start()

  @property
  def is_started(self):
    return self._is_started

  @property
  def disposed(self):
    return self._disposed

  def _get_time_in_ms(self, _time=None):
    return int(round((_time or time.time()) * 1000))

  def start(self):
    if self.is_started and not self.disposed:
      self.logger.warning('Service already started')
      return

    self.flushing_interval_deadline = self._get_time_in_ms() + self._get_time_in_ms(self.flush_interval.total_seconds())
    self.executor = threading.Thread(target=self._run)
    self.executor.setDaemon(True)
    self.executor.start()

    self._is_started = True

  def _run(self):
    """ Scheduler method that periodically flushes events queue. """
    try:
      while True:
        if self._get_time_in_ms() > self.flushing_interval_deadline:
          self.logger.debug('Deadline exceeded; flushing current batch.')
          self._flush_queue()

        try:
          item = self.event_queue.get(True, 0.05)

        except queue.Empty:
          self.logger.debug('Empty queue, sleeping for 50ms.')
          time.sleep(0.05)
          continue

        if item == self._SHUTDOWN_SIGNAL:
          self.logger.debug('Received shutdown signal.')
          break

        if item == self._FLUSH_SIGNAL:
          self.logger.debug('Received flush signal.')
          self._flush_queue()
          continue

        if isinstance(item, UserEvent):
          self._add_to_batch(item)

    except Exception, exception:
      self.logger.error('Uncaught exception processing buffer. Error: ' + str(exception))

    finally:
      self.logger.info('Exiting processing loop. Attempting to flush pending events.')
      self._flush_queue()

  def flush(self):
    """ Adds flush signal to event_queue. """

    self.event_queue.put(self._FLUSH_SIGNAL)

  def _flush_queue(self):
    """ Flushes event_queue by dispatching events. """

    if len(self._current_batch) == 0:
      return

    with self.LOCK:
      to_process_batch = list(self._current_batch)
      self._current_batch = list()

    log_event = EventFactory.create_log_event(to_process_batch, self.logger)

    if self.notification_center is not None:
      self.notification_center.send_notifications(
        enums.NotificationTypes.LOG_EVENT,
        log_event
      )

    try:
      self.event_dispatcher.dispatch_event(log_event)
    except Exception, e:
      self.logger.error('Error dispatching event: ' + str(log_event) + ' ' + str(e))

  def process(self, user_event):
    if not isinstance(user_event, UserEvent):
      self.logger.error('Provided event is in an invalid format.')
      return

    self.logger.debug('Received user_event: ' + str(user_event))

    try:
      self.event_queue.put_nowait(user_event)
    except queue.Full:
      self.logger.debug('Payload not accepted by the queue. Current size: {}'.format(str(self.event_queue.qsize())))

  def _add_to_batch(self, user_event):
    if self._should_split(user_event):
      self._flush_queue()
      self._current_batch = list()

    # Reset the deadline if starting a new batch.
    if len(self._current_batch) == 0:
      self.flushing_interval_deadline = self._get_time_in_ms() + \
        self._get_time_in_ms(self.flush_interval.total_seconds())

    with self.LOCK:
      self._current_batch.append(user_event)
    if len(self._current_batch) >= self.batch_size:
      self._flush_queue()

  def _should_split(self, user_event):
    if len(self._current_batch) == 0:
      return False

    current_context = self._current_batch[-1].event_context
    new_context = user_event.event_context

    if current_context.revision != new_context.revision:
      return True

    if current_context.project_id != new_context.project_id:
      return True

    return False

  def close(self):
    """ Stops and disposes batch event processor. """
    self.logger.info('Start close.')

    self.event_queue.put(self._SHUTDOWN_SIGNAL)
    self.executor.join(self.timeout_interval.total_seconds())

    if self.executor.isAlive():
      self.logger.error('Timeout exceeded while attempting to close for ' + self.timeout_interval + ' ms.')

    self.logger.warning('Stopping Scheduler.')
    self._is_started = False


class ForwardingEventProcessor(EventProcessor):

  def __init__(self, event_dispatcher, logger, notification_center=None):
    self.event_dispatcher = event_dispatcher
    self.logger = logger
    self.notification_center = notification_center

  def process(self, user_event):
    if not isinstance(user_event, UserEvent):
      self.logger.error('Provided event is in an invalid format.')
      return

    self.logger.debug('Received user_event: ' + str(user_event))

    log_event = EventFactory.create_log_event(user_event, self.logger)

    if self.notification_center is not None:
      self.notification_center.send_notifications(
        enums.NotificationTypes.LOG_EVENT,
        log_event
      )

    try:
      self.event_dispatcher.dispatch_event(log_event)
    except Exception, e:
      self.logger.exception('Error dispatching event: ' + str(log_event) + ' ' + str(e))
