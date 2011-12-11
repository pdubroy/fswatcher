import os
import Queue
import shutil
import tempfile
import threading
import unittest

from nose.tools import *
from os.path import join, realpath

import fswatcher

fswatcher.latency = 0.001

def touch(path):
    if os.path.exists(path):
        os.utime(path, None)
    else:
        open(path, 'w').close()    


def assert_paths_equal(one, other):
    assert_equal(realpath(one), realpath(other))


class BasicTests(unittest.TestCase):

    def setUp(self):
        self.testdir = tempfile.mkdtemp(prefix='fswatcher-testing-')
        self.changes = []
        self.watcher = fswatcher.Watcher(self.testdir, self.change_callback)

    def tearDown(self):
        shutil.rmtree(self.testdir)

    def change_callback(self, path, what):
        self.changes.append((path, what))
        self.watcher.destroy()

    def test_new_file(self):
        path = join(self.testdir, 'blah')
        touch(path)
        self.watcher.watch()

        assert_equal(len(self.changes), 1)
        change_path, event = self.changes.pop()
        assert_paths_equal(path, change_path)
    
    def test_delete_file(self):
        path = join(self.testdir, 'blah')
        touch(path)
        self.watcher.watch()

        watcher = fswatcher.Watcher(self.testdir, self.change_callback)
        os.unlink(path)
        watcher.watch()
        
        change_path, event = self.changes.pop()
        assert_paths_equal(path, change_path)
        assert_equal(event, fswatcher.REMOVED)

    def test_new_dir(self):
        path = join(self.testdir, 'some_dir')
        os.mkdir(path)
        self.watcher.watch()

        assert_equal(len(self.changes), 1)
        change_path, event = self.changes.pop()
        assert_paths_equal(path, change_path)

    def test_remove_watcher(self):
        self.watcher.destroy()
        touch(join(self.testdir, 'a_file'))

        # Unfortunately, this is kind of racey. It can pass simply because
        # the watcher hasn't picked up the change yet. A two second timeout
        # seems to work reliably though.
        self.watcher = fswatcher.Watcher(self.testdir, self.change_callback)
        self.watcher.watch(timeout=2)
        assert_equal(len(self.changes), 0)

        # Add a new watch and destroy the watcher inside the callback.

        def change_callback(path, what):
            self.changes.append((path, what))
            self.watcher.destroy()
            touch(join(self.testdir, 'file2'))

        watcher = fswatcher.Watcher(self.testdir, change_callback)
        touch(join(self.testdir, 'file1'))
        watcher.watch(timeout=2)
        
        # We should only ever see the first change.
        assert_equal(len(self.changes), 1)
