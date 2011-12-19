import os
import shutil
import tempfile
import time
import unittest

from nose.tools import assert_equal
from os.path import join, realpath

import fswatcher

fswatcher.latency = 0.001

def touch(path):
    if os.path.exists(path):
        os.utime(path, None)
    else:
        open(path, 'w').close()    


def check_change(change, expected):
    change_path, change_event = change
    path, event = expected

    assert_equal(realpath(path), realpath(change_path))
    assert_equal(event, change_event)
    

def no_more_changes(watcher):
    return watcher.next_change(timeout=2) is None


class BasicTests(unittest.TestCase):

    def setUp(self):
        self.testdir = tempfile.mkdtemp(prefix='fswatcher-test-')
        self.watcher = fswatcher.Watcher(self.testdir)

    def tearDown(self):
        assert 'fswatcher-test' in self.testdir
        shutil.rmtree(self.testdir)

    def test_new_file(self):
        path = join(self.testdir, 'blah')
        touch(path)

        change = self.watcher.next_change(timeout=2)
        check_change(change, (path, fswatcher.ADDED))

        assert no_more_changes(self.watcher)
    
    def test_delete_file(self):
        path = join(self.testdir, 'blah')
        touch(path)

        change = self.watcher.next_change(timeout=2)
        check_change(change, (path, fswatcher.ADDED))

        os.unlink(path)
        change = self.watcher.next_change(timeout=2)
        check_change(change, (path, fswatcher.REMOVED))
        
        assert no_more_changes(self.watcher)

    def test_new_dir(self):
        path = join(self.testdir, 'some_dir')
        os.mkdir(path)

        change = self.watcher.next_change(timeout=2)
        check_change(change, (path, fswatcher.ADDED))
        
        assert no_more_changes(self.watcher)


def wait_for_index_size(conn, expected_size):
    MAX_WAIT_TIME = 4

    start_time = time.time()
    size = 0
    while size < expected_size:
        conn.send("get_index_size")
        size = conn.recv()
        if time.time() - start_time >= MAX_WAIT_TIME:
            assert_equal(size, count)
        time.sleep(1)


class ConcurrentTests(unittest.TestCase):

    def setUp(self):
        self.connections = []
        self.testdir = tempfile.mkdtemp(prefix='fswatcher-test-')

    def tearDown(self):
        if os.path.exists(self.testdir):
            assert 'fswatcher-test' in self.testdir
            shutil.rmtree(self.testdir)

    def create_files(self, path, count, depth, top_level=True):
        """Recursively creates a bunch of files and directories, and    
        returns the number of files and directories that were created.
        
        At each iteration of the top-level loop, a new watcher is created.
        """
        if depth <= 0:
            return 0

        entries = 0
        for i in xrange(count):
            if top_level:
                conn = fswatcher.watch_concurrently(self.testdir)
                self.connections.append(conn)

            touch(join(path, 'file%d' % i))
            dirpath = join(path, 'dir%d' % i)
            os.mkdir(dirpath)
            entries += 1 + self.create_files(dirpath, count, depth - 1, False)

        return entries

    def test_concurrency(self):

        # Create a bunch of files and directories, and create
        # several watchers at regular intervals.
        count = self.create_files(self.testdir, 4, 6)

        # Check that all the watchers eventually achieve the right count.
        for conn in self.connections:
            wait_for_index_size(conn, count)

        shutil.rmtree(self.testdir)

        for conn in self.connections:
            wait_for_index_size(conn, 0)

        for conn in self.connections:
            conn.send("stop")
            conn.recv() # Wait for the thread to stop.
