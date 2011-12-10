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
        fswatcher.add_watch(self.testdir, self.change_callback)

    def tearDown(self):
        shutil.rmtree(self.testdir)

    def change_callback(self, path, what):
        self.changes.append((path, what))
        fswatcher.stop_watching()

    def test_new_file(self):
        path = join(self.testdir, 'blah')
        touch(path)
        fswatcher.watch()

        assert_equal(1, len(self.changes))
        change_path, event = self.changes.pop()
        assert_paths_equal(path, change_path)

    def test_new_dir(self):
        path = join(self.testdir, 'some_dir')
        os.mkdir(path)
        fswatcher.watch()

        assert_equal(len(self.changes), 1)
        change_path, event = self.changes.pop()
        assert_paths_equal(path, change_path)

    def test_remove_watch(self):
        fswatcher.remove_watch(self.testdir, self.change_callback)
        touch(join(self.testdir, 'a_file'))

        # Unfortunately, this is kind of racey. It can pass simply because
        # the watcher hasn't picked up the change yet. A two second timeout
        # seems to work reliably though.
        fswatcher.watch(timeout=2)
        assert_equal(len(self.changes), 0)

        # Now try adding a new watch, and removing it inside the callback.

        def change_callback(path, what):
            self.changes.append((path, what))
            fswatcher.remove_watch(self.testdir, change_callback)
            touch(join(self.testdir, 'file2'))

        fswatcher.add_watch(self.testdir, change_callback)
        touch(join(self.testdir, 'file1'))
        fswatcher.watch(timeout=2)
        
        # We should only ever see the first change.
        assert_equal(len(self.changes), 1)
