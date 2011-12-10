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

import itertools
import os
import stat
import sys

from FSEvents import *

__all__ = ['add_watch', 'remove_watch', 'watch', 'stop_watching', 'ADDED', 'MODIFIED', 'REMOVED']

# Based on http://svn.red-bean.com/pyobjc/branches/pyobjc-20x-branch/pyobjc-framework-FSEvents/Examples/watcher.py

# Time in seconds that the system should wait before noticing an event and
# invoking the callback. Making this bigger improves coalescing.
latency = DEFAULT_LATENCY = 1

runloop_ref = None
streams = []

ADDED = 'ADDED'
MODIFIED = 'MODIFIED'
REMOVED = 'REMOVED'


class Stream(object):
    """Wrapper for a Carbon FSEventStream."""

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

    def _fsevents_callback(self, stream, client_info, num_events, event_paths,
            event_flags, event_ids):
        # TODO: We should examine event_flags here.
        for each in event_paths:
            for path, what in self.index.rescan(each):
                self.callback(path, what)

    def build_index(self):
        self.index.build()

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

    def cleanup(self):
        stream_ref = self.stream
        if self.started:
            FSEventStreamStop(stream_ref)
            self.started = False
        if self.scheduled:
            FSEventStreamInvalidate(stream_ref)
            self.scheduled = False
        FSEventStreamRelease(stream_ref)
        self.stream = None


def add_watch(path, callback):
    pool = NSAutoreleasePool.alloc().init()
    stream = Stream(path, callback)
    stream.start()
    stream.build_index()
    streams.append(stream)

def remove_watch(path, callback):
    match = None
    for stream in streams:
        if stream.path == path and stream.callback == callback:
            match = stream
    streams.remove(match)
    match.cleanup()

def watch(path=None, callback=None, timeout=None):
    global runloop_ref, streams

    pool = NSAutoreleasePool.alloc().init()

    if path is not None:
        assert callback is not None
        add_watch(path, callback)

    runloop_ref = CFRunLoopGetCurrent()

    if timeout is not None:
        CFRunLoopRunInMode(kCFRunLoopDefaultMode, timeout, False)
    else:
        CFRunLoopRun()

    for stream in streams:
        stream.cleanup()
    streams = []

def stop_watching():
    global runloop_ref
    if runloop_ref:
        CFRunLoopStop(runloop_ref)
    runloop_ref = None


class FileModificationIndex(object):
    """Tracks the modification times of all files in a directory tree."""

    def __init__(self, root):
        self._index = {}
        self.root = os.path.realpath(root)

    def _refresh_index(self, path):
        changes = []
        for dirpath, dirnames, filenames in os.walk(path):
            old_contents = self._index.get(dirpath, {})
            self._index[dirpath] = new_contents = {}
            for name in itertools.chain(filenames, dirnames):
                path = os.path.join(dirpath, name)
                stat_info = os.stat(path)
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
            for path in (os.path.join(name) for name in old_contents):
                changes.append((path, REMOVED))
        return changes

    def build(self):
        return self._refresh_index(self.root)

    def rescan(self, path):
        path = os.path.realpath(path)
        assert os.path.commonprefix([self.root, path]) == self.root
        return self._refresh_index(path)
