import sys

from FSEvents import *

# Based on an example from http://svn.red-bean.com/pyobjc/branches/pyobjc-20x-branch/pyobjc-framework-FSEvents/Examples/watcher.py

# Time in seconds that the system should wait before noticing an event and
# invoking the callback. Making this bigger improves coalescing.
LATENCY = 3

streams = []
watcher_thread = None

class Struct(object):
    def __init__(self, **entries):
        self.__dict__.update(entries)

class StreamInfo(Struct): pass

def _cleanup_stream(streaminfo):
    stream = streaminfo.stream
    if streaminfo.started:
        FSEventStreamStop(stream)
        streaminfo.started = False
    FSEventStreamInvalidate(stream)
    FSEventStreamRelease(stream)
    streaminfo.stream = None

def add_watch(dirs, callback):
    pool = NSAutoreleasePool.alloc().init()
    dirs = list(dirs)
    since_when = kFSEventStreamEventIdSinceNow
    flags = 0
    stream = FSEventStreamCreate(
        None, callback, None, dirs, since_when, LATENCY, 0)
    FSEventStreamScheduleWithRunLoop(
        stream, CFRunLoopGetCurrent(), kCFRunLoopDefaultMode)
    streams.append(
        StreamInfo(stream=stream, dirs=dirs, callback=callback, started=False))

def remove_watch(dirs, callback):
    pass

def watch(spawn_thread=False):
    pool = NSAutoreleasePool.alloc().init()
    for streaminfo in streams:
        if FSEventStreamStart(streaminfo.stream):
            streaminfo.started = True
        else:
            print 'Failed to start event stream for %s' % dirs
            _cleanup_stream(streaminfo)

    while True:
        try:
            # Processes a single event, or returns if one second has elapsed.
            CFRunLoopRunInMode(kCFRunLoopDefaultMode, 1, True)
        except KeyboardInterrupt:
            break

    for streaminfo in streams:
        _cleanup_stream(streaminfo)

def main(watch_dirs):
    def callback(*args):
        print 'changes in %s' % (args[3])
    count = len(watch_dirs)
    print 'Watching %s...press Ctrl-C to stop.' % (
        watch_dirs[0] if count == 1 else '%d directories' % count)
    add_watch(watch_dirs, callback)
    watch()

if __name__ == '__main__':
    main(sys.argv[1:])
