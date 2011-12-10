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

__all__ = ['add_watch', 'remove_watch', 'watch', 'stop_watching']

# Based on http://svn.red-bean.com/pyobjc/branches/pyobjc-20x-branch/pyobjc-framework-FSEvents/Examples/watcher.py

# Time in seconds that the system should wait before noticing an event and
# invoking the callback. Making this bigger improves coalescing.
latency = DEFAULT_LATENCY = 1

runloop_ref = None
streams = []

class Struct(object):
    def __init__(self, **entries): self.__dict__.update(entries)


def _cleanup_stream(streaminfo):
    stream = streaminfo.stream
    if streaminfo.started:
        FSEventStreamStop(stream)
        streaminfo.started = False
    if streaminfo.scheduled:
        FSEventStreamInvalidate(stream)
        streaminfo.scheduled = False
    FSEventStreamRelease(stream)
    streaminfo.stream = None

def _fsevents_callback(
        stream, client_info, num_events, event_paths, event_flags, event_ids):
    # TODO: We should examine event_flags here.
    user_callback = client_info
    for each in event_paths:
        user_callback(each, None)

def add_watch(path, callback):
    pool = NSAutoreleasePool.alloc().init()

    context = callback # This will be passed to our callback as client_info.
    since_when = kFSEventStreamEventIdSinceNow
    flags = 0
    stream = FSEventStreamCreate(
        None, _fsevents_callback, context, [path], since_when, latency, flags)
    streams.append(Struct(stream=stream, path=path, callback=callback,
        started=False, scheduled=False))

def remove_watch(path, callback):
    match = None
    for streaminfo in streams:
        if streaminfo.path == path and streaminfo.callback == callback:
            match = streaminfo
    streams.remove(match)
    _cleanup_stream(match)

def watch(path=None, callback=None, timeout=None):
    global runloop_ref, streams

    pool = NSAutoreleasePool.alloc().init()

    if path is not None:
        assert callback is not None
        add_watch(path, callback)

    runloop_ref = CFRunLoopGetCurrent()
    
    for streaminfo in streams:
        # Schedule the stream to be processed on the current run loop.
        FSEventStreamScheduleWithRunLoop(
            streaminfo.stream, runloop_ref, kCFRunLoopDefaultMode)
        streaminfo.scheduled = True
        if not FSEventStreamStart(streaminfo.stream):
            raise Exception('Failed to start event stream')
        streaminfo.started = True

    if timeout is not None:
        CFRunLoopRunInMode(kCFRunLoopDefaultMode, timeout, False)
    else:
        CFRunLoopRun()

    for streaminfo in streams:
        _cleanup_stream(streaminfo)
    streams = []

def stop_watching():
    CFRunLoopStop(runloop_ref)
