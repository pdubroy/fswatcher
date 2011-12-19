# Copyright (c) 2011, Patrick Dubroy
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# Redistributions of source code must retain the above copyright notice, this
# list of conditions and the following disclaimer.
#
# Redistributions in binary form must reproduce the above copyright notice,
# this list of conditions and the following disclaimer in the documentation
# and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

import errno
import functools
import itertools
import multiprocessing
import os
import stat
import sys
import threading

import objc

from FSEvents import *

# Based on http://svn.red-bean.com/pyobjc/branches/pyobjc-20x-branch/pyobjc-framework-FSEvents/Examples/watcher.py

# Time in seconds that the system should wait before noticing an event and
# invoking the callback. Making this bigger improves coalescing.
latency = DEFAULT_LATENCY = 1

ADDED = 'ADDED'
MODIFIED = 'MODIFIED'
REMOVED = 'REMOVED'


def watch_concurrently(paths):
    master_conn, slave_conn = multiprocessing.Pipe()

    # The master side of the pipe needs a reference to the watcher thread's
    # run loop, in order to wake the thread when there's a message ready.
    run_loop = threading.Event()

    def thread_main():
        # Store the value in the Event object, and signal the master thread.
        run_loop.value = CFRunLoopGetCurrent()
        run_loop.set()

        watcher = Watcher(paths, slave_conn)
        for change in watcher.get_changes():
            pass
        slave_conn.send(None)

    threading.Thread(target=thread_main).start()

    # Wait for the watcher thread to store the run_loop.
    run_loop.wait()

    # Return a proxy for the master end of the pipe.
    return _ConnectionProxy(master_conn, run_loop.value)


def get_changes(paths, timeout=None):
    return Watcher(path).get_changes(timeout)


class _ConnectionProxy(object):
    """Proxy class for multiprocessing.Connection, used on one side of a Pipe
    when the thread on the other end is running a Core Foundation run loop.
    """

    def __init__(self, conn, run_loop):
        """Create a proxy for the given connection object. `run_loop` is a
        reference to the other thread's run loop.
        """
        self._conn = conn
        self._run_loop = run_loop

    def send(self, obj):
        """Send a message and wake the run loop."""
        self._conn.send(obj)
        CFRunLoopWakeUp(self._run_loop)

    def send_bytes(self, *args, **kwargs):
        """Send a message and wake the run loop."""
        self._conn.send_bytes(*args, **kwargs)
        CFRunLoopWakeUp(self._run_loop)

    def __getattr__(self, name):
        """Proxy everything else to the Connection instance."""
        return getattr(self._conn, name)


class _Stream(object):
    """Wrapper for a Core Foundation FSEventStream."""

    def __init__(self, path, callback):
        self.path = path
        self.callback = callback
        self.started = False
        self.scheduled = False
        self.index = FileModificationIndex(path)

        context = None # Passed to the callback as client_info.
        since_when = kFSEventStreamEventIdSinceNow
        flags = 0
        stream_ref = FSEventStreamCreate(None, self._fsevents_callback,
            context, [path], since_when, latency, flags)
        self.stream = stream_ref
        
        self.start()

    def _fsevents_callback(self, stream, client_info, num_events, event_paths,
            event_flags, event_ids):
        # TODO: We should examine event_flags here.
        for each in event_paths:
            for path, what in self.index.rescan(each):
                if self.callback:
                    self.callback(path, what)

    def start(self, runloop=None):
        # Schedule the stream to be processed on the given run loop,
        # or the current run loop if none was specified.
        if runloop is None:
            runloop = CFRunLoopGetCurrent()
        FSEventStreamScheduleWithRunLoop(
            self.stream, runloop, kCFRunLoopDefaultMode)
        self.scheduled = True
        if not FSEventStreamStart(self.stream):
            raise Exception('Failed to start event stream')
        self.started = True

        # Build the index that is used to determine which file or directory
        # was added, modified, or deleted. The index should be built after
        # starting the stream, otherwise some state may be lost.
        self.index.build()

    def destroy(self):
        stream_ref = self.stream
        if self.started:
            FSEventStreamStop(stream_ref)
            self.started = False
        if self.scheduled:
            FSEventStreamInvalidate(stream_ref)
            self.scheduled = False
        FSEventStreamRelease(stream_ref)
        self.stream = None


class _ChangeIterator(object):

    def __init__(self, watcher, timeout):
        self.watcher = watcher
        self.timeout = timeout

    def __iter__(self):
        return self

    def next(self):
        return self.watcher.next_change(self.timeout)


class Watcher(object):
    
    def __init__(self, paths, conn=None):
        self.paths = (paths,) if isinstance(paths, basestring) else paths
        self.conn = conn
        self.changes = []
        self._start()

    def _thread_check(self):
        if hasattr(self, '_thread_local'):
            assert hasattr(self._thread_local, 'is_owner')
        else:
            self._thread_local = threading.local()
            self._thread_local.is_owner = True

    def _start(self):
        pool = NSAutoreleasePool.alloc().init()

        assert not hasattr(self, 'streams'), 'Watcher already started.'
        self._thread_check()

        callback = lambda path, what: self.changes.append((path, what))
        self.streams = [_Stream(path, callback) for path in self.paths]

        run_loop = CFRunLoopGetCurrent()

        def before_waiting(*args):
            # Stop the run loop if there are any changes to process.
            if len(self.changes) > 0:
                CFRunLoopStop(run_loop)
            self._process_messages()
        
        observer = CFRunLoopObserverCreate(
            objc.NULL, kCFRunLoopBeforeWaiting, YES, 0, before_waiting, None)
        CFRunLoopAddObserver(run_loop, observer, kCFRunLoopCommonModes)

    def _process_messages(self):
        # Process any messages on the connection.
        conn = self.conn
        while conn and conn.poll():
            message = self.conn.recv()
            if message == "stop":
                CFRunLoopStop(CFRunLoopGetCurrent())
                conn.send(None)
            elif message == 'get_index_size':
                conn.send(self.index_size())

    def next_change(self, timeout=None):
        # If there are pending chanages, return right away.
        if self.changes:
            return self.changes.pop()

        # Enter the run loop until a change is found or the timeout expires.
        if timeout is not None:
            CFRunLoopRunInMode(kCFRunLoopDefaultMode, timeout, False)
        else:
            CFRunLoopRun()

        return self.changes.pop() if self.changes else None

    def get_changes(self, timeout=None):
        pool = NSAutoreleasePool.alloc().init()
        self._thread_check()
        return _ChangeIterator(self, timeout)

    def destroy(self):
        pool = NSAutoreleasePool.alloc().init()
        self._thread_check()
        CFRunLoopObserverInvalidate(observer)
        for stream in self.streams:
            stream.destroy()
        self.streams = []

    def __del__(self):
        self.destroy()

    def index_size(self):
        if len(self.streams) > 0:
            assert len(self.streams) == 1
            return self.streams[0].index.size()
        return 0


class FileModificationIndex(object):
    """Tracks the modification times of all items in a directory tree."""

    def __init__(self, root):
        self._index = {}
        self.root = os.path.realpath(root)

    def _rescan(self, path, recursive=False):
        """Rescan the directory rooted at path and determine which files and
        directories have changed. Returns a list of tuples (path, change)
        where change is one of ADDED, MODIFIED, or REMOVED.
        """
        if not recursive:
            # Ignore an exception caused by the directory being deleted.
            try:
                return self._get_changes(path, os.listdir(path))
            except OSError, e:
                if e.errno == errno.ENOENT:
                    return []
                raise

        changes = []
        for dirpath, dirnames, filenames in os.walk(path):
            entries = itertools.chain(dirnames, filenames)
            changes.extend(self._get_changes(dirpath, entries))
        return changes

    def _get_changes(self, dirpath, entries):
        """Determine what changes have occurred in the given directory."""
        changes = []
        old_contents = self._index.get(dirpath, {})
        self._index[dirpath] = new_contents = {}
        for name in entries:
            path = os.path.join(dirpath, name)
            try:
                stat_info = os.stat(path)
            except OSError as e:
                # File no longer exists -- not much we can do about it.
                if e.errno == errno.ENOENT:
                    continue
                raise
                
            new_contents[name] = stat_info.st_mtime
            isdir = stat.S_ISDIR(stat_info.st_mode)

            # Keep track of files and dirs that were added. For files,
            # also watch for modifications.
            if name not in old_contents:
                changes.append((path, ADDED))
            else:
                if not isdir and old_contents[name] != new_contents[name]:
                    changes.append((path, MODIFIED))
                del old_contents[name]
        # Any items left in the old dict must have been deleted.
        for path in (os.path.join(dirpath, name) for name in old_contents):
            changes.append((path, REMOVED))
        return changes

    def build(self):
        return self._rescan(self.root, True)

    def rescan(self, path, recursive=False):
        path = os.path.realpath(path)
        assert os.path.commonprefix([self.root, path]) == self.root
        return self._rescan(path, recursive)

    def size(self):
        return sum(len(entries) for entries in self._index.values())
