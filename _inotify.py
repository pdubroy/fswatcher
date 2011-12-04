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

from fcntl import ioctl
from termios import FIONREAD

import ctypes
import errno
import os
import select
import struct

# Constants defined by sys/inotify.h.
IN_ACCESS           = 0x00000001
IN_MODIFY           = 0x00000002
IN_ATTRIB           = 0x00000004
IN_CLOSE_WRITE      = 0x00000008
IN_CLOSE_NOWRITE    = 0x00000010
IN_CLOSE            = (IN_CLOSE_WRITE | IN_CLOSE_NOWRITE)
IN_OPEN	            = 0x00000020
IN_MOVED_FROM	    = 0x00000040
IN_MOVED_TO         = 0x00000080
IN_MOVE	            = (IN_MOVED_FROM | IN_MOVED_TO)
IN_CREATE	        = 0x00000100
IN_DELETE	        = 0x00000200
IN_DELETE_SELF      = 0x00000400
IN_MOVE_SELF        = 0x00000800

# Description (as used by the 'struct' module) for the inotify_event struct.
INOTIFY_EVENT_DESC = 'iIII'

libc = ctypes.cdll.LoadLibrary('libc.so.6')
inotify_fd = libc.inotify_init()
if inotify_fd == -1:
    raise Exception('Failed to initialize inotify: %s' % geterr())

watches = {}

class Struct(object):
    def __init__(self, **entries): self.__dict__.update(entries)

# A hacky way to get at the errno global inside libc.
libc.__errno_location.restype = ctypes.POINTER(ctypes.c_int)
def geterr():
    return errno.errorcode[libc.__errno_location().contents.value]

def _inotify_add_watch(path, flags):
    wd = libc.inotify_add_watch(inotify_fd, path, flags)
    if wd == -1:
        raise Exception(
            'Failed to add watch for %s: %s' % (path, geterr()))
    return wd

def _inotify_rm_watch(wd):
    if libc.inotify_rm_watch(inotify_fd, wd) == -1:
        print 'inotify_rm_watch returned error:', geterr()

def add_watch(watchdir_path, callback):
    watch_info = Struct(path=watchdir_path, callback=callback)

    # Find all subdirectories, and watch them individually.
    watchdirs = [watchdir_path]
    for path, dirnames, filenames in os.walk(watchdir_path):
        watchdirs.extend(os.path.join(path, each) for each in dirnames)

    # Watch for any new or removed files or directories.
    flags = IN_CREATE | IN_DELETE | IN_MOVED_FROM | IN_MOVED_TO

    for each in watchdirs:
        wd = _inotify_add_watch(os.path.join(path, each), flags)
        assert wd != -1
        watches[wd] = watch_info

def _read_events(fd):
    """Return a list of (wd, mask) extracted from the inotify_event
    structs that are available.
    """
    events = []
    
    # Figure out how many bytes are ready for reading.
    data_size = ctypes.c_int(0)
    result = ioctl(inotify_fd, FIONREAD, data_size)
    assert result != -1, 'Unexpected return value from ioctl: %s' % result

    # Read one or more inotify_event structs from the file descriptor.
    # See http://www.linuxjournal.com/article/8478?page=0,1
    data = os.read(inotify_fd, data_size.value)
    
    event_struct_size = struct.calcsize(INOTIFY_EVENT_DESC)
    offset = 0
    while offset < len(data):
        event = data[offset:offset+event_struct_size]
        wd, mask, cookie, name_len = struct.unpack(INOTIFY_EVENT_DESC, event)
        events.append((wd, mask))
        # Skip over the filename in the byte stream. We don't bother reading
        # it since we only support watches on directories.
        offset += event_struct_size + name_len
    return events

def watch():
    while True:
        read_list = select.select([inotify_fd], [], [])[0]
        if len(read_list) == 0:
            continue
        for wd, mask in _read_events(inotify_fd):
            # TODO: Put a watch on new directories when they are created. 
            watchinfo = watches[wd]

            # This will pass the root path that was passed to add_watch,
            # rather than the specific directory that the change occurred.
            # TODO: Is that what we want?
            watchinfo.callback(watchinfo.path)

def remove_watch(watchdir_path, callback):
    # Find all the matching watches.
    matching_keys = []
    for wd, watchinfo in watches.iteritems():
        if watchinfo.path == watchdir_path and watchinfo.callback == callback:
            _inotify_rm_watch(wd)
            matching_keys.append(wd)
    assert len(matching_keys) > 0, 'No matching watches found for %s' % watchdir_path

    for k in matching_keys:
        del watches[k]
