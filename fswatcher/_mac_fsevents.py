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

import os
import sys

from FSEvents import *

__all__ = ['add_watch', 'remove_watch', 'watch', 'stop_watching']

# Based on http://svn.red-bean.com/pyobjc/branches/pyobjc-20x-branch/pyobjc-framework-FSEvents/Examples/watcher.py

# Time in seconds that the system should wait before noticing an event and
# invoking the callback. Making this bigger improves coalescing.
latency = DEFAULT_LATENCY = 1

runloop_ref = None
streams = []


class Stream(object):

    def __init__(self, path, callback):
        self.path = path
        self.callback = callback
        self.started = False
        self.scheduled = False
        self.index = FileModificationIndex(path)

        context = callback # This will be passed to the callback as client_info.
        since_when = kFSEventStreamEventIdSinceNow
        flags = 0
        stream_ref = FSEventStreamCreate(
            None, _fsevents_callback, context, [path], since_when, latency, flags)
        self.stream = stream_ref

    def start(self, runloop):
        # Schedule the stream to be processed on the given run loop.
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


def _fsevents_callback(
        stream, client_info, num_events, event_paths, event_flags, event_ids):
    # TODO: We should examine event_flags here.
    user_callback = client_info
    for each in event_paths:
        user_callback(each, None)


def add_watch(path, callback):
    pool = NSAutoreleasePool.alloc().init()
    streams.append(Stream(path, callback))

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
    
    for stream in streams:
        stream.start(runloop_ref)

    if timeout is not None:
        CFRunLoopRunInMode(kCFRunLoopDefaultMode, timeout, False)
    else:
        CFRunLoopRun()

    for stream in streams:
        stream.cleanup()
    streams = []

def stop_watching():
    CFRunLoopStop(runloop_ref)


class FileModificationIndex(object):
    """Tracks the modification times of all files in a directory tree."""

    def __init__(self, root):
        self._index = {}
        self.root = root

    def _refresh_index(self, path):
        modified = []
        added = []
        removed = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            old_files = self._index.get(dirpath, {})
            new_files = {}
            for each in filenames:
                filepath = os.path.join(dirpath, each)
                mtime = os.stat(filepath).st_mtime
                files[each] = mtime

                # Keep track of files that were added and modified.
                if each not in old_files:
                    added.append(filepath)
                else:
                    if old_files[each] != mtime:
                        modified.append(filepath)
                    del old_files[each]
            self._index[dirpath] = new_files

            # Any files left in the old dict must have been deleted.
            removed.extend(old_files.iter_keys())
        return (added, removed, modified)

    def build(self):
        self._refresh_index(root)

    def rescan(self, path):
        assert os.path.commonprefix(self.root, path) == len(self.root)
        return self._refresh_index(path)
