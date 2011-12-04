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

import sys

from FSEvents import *

__all__ = ['add_watch', 'remove_watch', 'watch']

# Based on http://svn.red-bean.com/pyobjc/branches/pyobjc-20x-branch/pyobjc-framework-FSEvents/Examples/watcher.py

# Time in seconds that the system should wait before noticing an event and
# invoking the callback. Making this bigger improves coalescing.
LATENCY = 3

streams = []
watcher_thread = None

class Struct(object):
    def __init__(self, **entries): self.__dict__.update(entries)

def _cleanup_stream(streaminfo):
    stream = streaminfo.stream
    if streaminfo.started:
        FSEventStreamStop(stream)
        streaminfo.started = False
    FSEventStreamInvalidate(stream)
    FSEventStreamRelease(stream)
    streaminfo.stream = None

def _fsevents_callback(
        stream, client_info, num_events, event_paths, event_flags, event_ids):
    # TODO: We should examine event_flags here.
    client_info(event_paths)

def add_watch(dirs, callback):
    pool = NSAutoreleasePool.alloc().init()

    dirs = list(dirs)
    since_when = kFSEventStreamEventIdSinceNow

    flags = 0
    context = callback # This will be passed to our callback as client_info.
    stream = FSEventStreamCreate(None, _fsevents_callback, context, dirs,
        kFSEventStreamEventIdSinceNow, LATENCY, flags)

    # Schedule the stream to be processed on this thread's run loop.
    FSEventStreamScheduleWithRunLoop(
        stream, CFRunLoopGetCurrent(), kCFRunLoopDefaultMode)

    streams.append(
        Struct(stream=stream, dirs=dirs, callback=callback, started=False))

def remove_watch(dirs, callback):
    pass

def watch():
    pool = NSAutoreleasePool.alloc().init()
    for streaminfo in streams:
        if FSEventStreamStart(streaminfo.stream):
            streaminfo.started = True
        else:
            print 'Failed to start event stream for %s' % dirs
            _cleanup_stream(streaminfo)

    while True:
        try:
            # Watch for events with a timeout of 1 second.
            CFRunLoopRunInMode(kCFRunLoopDefaultMode, 1, False)
        except KeyboardInterrupt:
            break

    for streaminfo in streams:
        _cleanup_stream(streaminfo)
