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

import functools
import itertools
import os
import stat
import sys

from FSEvents import *

__all__ = ['Watcher', 'ADDED', 'MODIFIED', 'REMOVED']

# Based on http://svn.red-bean.com/pyobjc/branches/pyobjc-20x-branch/pyobjc-framework-FSEvents/Examples/watcher.py

# Time in seconds that the system should wait before noticing an event and
# invoking the callback. Making this bigger improves coalescing.
latency = DEFAULT_LATENCY = 1

ADDED = 'ADDED'
MODIFIED = 'MODIFIED'
REMOVED = 'REMOVED'


class _Stream(object):
    """Wrapper for a Carbon FSEventStream."""

    def __init__(self, path, callback, start=True):
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
        
        if start: self.start()

    def _fsevents_callback(self, stream, client_info, num_events, event_paths,
            event_flags, event_ids):
        # TODO: We should examine event_flags here.
        for each in event_paths:
            for path, what in self.index.rescan(each):
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


class Watcher(object):
    
    def __init__(self, paths, callback):
        pool = NSAutoreleasePool.alloc().init()
        paths = (paths,) if isinstance(paths, basestring) else paths
        self.streams = [_Stream(path, callback, True) for path in paths]

    def watch(self, timeout=None):
        pool = NSAutoreleasePool.alloc().init()
        if timeout is not None:
            CFRunLoopRunInMode(kCFRunLoopDefaultMode, timeout, False)
        else:
            CFRunLoopRun()

    def stop_watching(self):
        pool = NSAutoreleasePool.alloc().init()
        CFRunLoopStop(CFRunLoopGetCurrent())

    def destroy(self):
        pool = NSAutoreleasePool.alloc().init()
        self.stop_watching()
        for stream in self.streams:
            stream.destroy()
        self.streams = []

    def __del__(self):
        self.destroy()


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
            return self._get_changes(path, os.listdir(path))

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
        for path in (os.path.join(dirpath, name) for name in old_contents):
            changes.append((path, REMOVED))
        return changes

    def build(self):
        return self._rescan(self.root, True)

    def rescan(self, path, recursive=False):
        path = os.path.realpath(path)
        assert os.path.commonprefix([self.root, path]) == self.root
        return self._rescan(path, recursive)
