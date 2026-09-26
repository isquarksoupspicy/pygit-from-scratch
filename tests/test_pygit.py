"""
End-to-end tests for pygit. Each test runs the actual CLI (via `python -m pygit`)
inside a fresh temporary directory, exactly like a real user would.

Run with:  python -m unittest discover -s tests -v
"""

import os
import subprocess
import sys
import tempfile
import unittest

PYTHON = sys.executable
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(*args, cwd):
    result = subprocess.run(
        [PYTHON, '-m', 'pygit', *args],
        cwd=cwd, capture_output=True, text=True,
        env={**os.environ, 'PYTHONPATH': PROJECT_ROOT},
    )
    return result


class PygitTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name, content):
        with open(os.path.join(self.dir, name), 'w') as f:
            f.write(content)

    def read(self, name):
        with open(os.path.join(self.dir, name)) as f:
            return f.read()


class TestInit(PygitTestCase):
    def test_init_creates_repo(self):
        r = run('init', cwd=self.dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.isdir(os.path.join(self.dir, '.pygit')))
        self.assertTrue(os.path.isdir(os.path.join(self.dir, '.pygit', 'objects')))

    def test_init_twice_fails_cleanly(self):
        run('init', cwd=self.dir)
        r = run('init', cwd=self.dir)
        self.assertNotEqual(r.returncode, 0)


class TestHashObject(PygitTestCase):
    def test_hash_and_cat_roundtrip(self):
        run('init', cwd=self.dir)
        self.write('hello.txt', 'hello world\n')
        r = run('hash-object', 'hello.txt', cwd=self.dir)
        oid = r.stdout.strip()
        self.assertEqual(len(oid), 40)  # sha1 hex digest

        r2 = run('cat-file', oid, cwd=self.dir)
        self.assertEqual(r2.stdout, 'hello world\n')

    def test_same_content_same_oid(self):
        run('init', cwd=self.dir)
        self.write('a.txt', 'same content')
        self.write('b.txt', 'same content')
        oid_a = run('hash-object', 'a.txt', cwd=self.dir).stdout.strip()
        oid_b = run('hash-object', 'b.txt', cwd=self.dir).stdout.strip()
        self.assertEqual(oid_a, oid_b)


class TestTreeAndCommit(PygitTestCase):
    def test_write_tree_and_commit(self):
        run('init', cwd=self.dir)
        self.write('a.txt', 'A')
        os.makedirs(os.path.join(self.dir, 'sub'))
        with open(os.path.join(self.dir, 'sub', 'b.txt'), 'w') as f:
            f.write('B')

        r = run('commit', '-m', 'first commit', cwd=self.dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        oid = r.stdout.strip()
        self.assertEqual(len(oid), 40)

        log = run('log', cwd=self.dir)
        self.assertIn('first commit', log.stdout)
        self.assertIn(oid, log.stdout)

    def test_checkout_restores_files(self):
        run('init', cwd=self.dir)
        self.write('a.txt', 'version 1')
        c1 = run('commit', '-m', 'v1', cwd=self.dir).stdout.strip()

        self.write('a.txt', 'version 2')
        run('commit', '-m', 'v2', cwd=self.dir)
        self.assertEqual(self.read('a.txt'), 'version 2')

        run('checkout', c1, cwd=self.dir)
        self.assertEqual(self.read('a.txt'), 'version 1')


class TestBranchAndMerge(PygitTestCase):
    def test_fast_forward_merge(self):
        run('init', cwd=self.dir)
        self.write('a.txt', '1')
        c1 = run('commit', '-m', 'c1', cwd=self.dir).stdout.strip()
        run('branch', 'feature', c1, cwd=self.dir)
        run('checkout', 'feature', cwd=self.dir)

        self.write('a.txt', '2')
        run('commit', '-m', 'c2 on feature', cwd=self.dir)

        run('checkout', 'main', cwd=self.dir)
        r = run('merge', 'feature', cwd=self.dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('Fast-forwarded', r.stdout)
        self.assertEqual(self.read('a.txt'), '2')

    def test_conflicting_merge_produces_markers(self):
        run('init', cwd=self.dir)
        self.write('a.txt', 'base\n')
        c1 = run('commit', '-m', 'base commit', cwd=self.dir).stdout.strip()

        run('branch', 'feature', c1, cwd=self.dir)

        self.write('a.txt', 'main change\n')
        run('commit', '-m', 'change on main', cwd=self.dir)

        run('checkout', 'feature', cwd=self.dir)
        self.write('a.txt', 'feature change\n')
        run('commit', '-m', 'change on feature', cwd=self.dir)

        run('checkout', 'main', cwd=self.dir)
        r = run('merge', 'feature', cwd=self.dir)
        self.assertIn('CONFLICT', r.stdout.upper())
        content = self.read('a.txt')
        self.assertIn('<<<<<<< HEAD', content)
        self.assertIn('main change', content)
        self.assertIn('feature change', content)

    def test_branch_listing_marks_current(self):
        run('init', cwd=self.dir)
        self.write('a.txt', '1')
        run('commit', '-m', 'c1', cwd=self.dir)
        r = run('branch', cwd=self.dir)
        self.assertIn('* main', r.stdout)


class TestDiffAndStatus(PygitTestCase):
    def test_status_shows_new_file(self):
        run('init', cwd=self.dir)
        self.write('a.txt', 'hi')
        r = run('status', cwd=self.dir)
        self.assertIn('a.txt', r.stdout)
        self.assertIn('new file', r.stdout)

    def test_diff_shows_change(self):
        run('init', cwd=self.dir)
        self.write('a.txt', 'line1\n')
        run('commit', '-m', 'c1', cwd=self.dir)
        self.write('a.txt', 'line1\nline2\n')
        r = run('diff', cwd=self.dir)
        self.assertIn('+line2', r.stdout)


if __name__ == '__main__':
    unittest.main()
