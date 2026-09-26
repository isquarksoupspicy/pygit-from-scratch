"""
base.py — the "meaning" layer on top of data.py.

This is where trees, commits, branches and merges are defined in
terms of the raw object store from data.py.
"""

import itertools
import operator
import os
import string
from collections import namedtuple, deque

from . import data
from . import diff as diff_module

IGNORED_DIRS = {'.pygit', '.git', '__pycache__', '.venv', 'venv', '.idea', '.vscode'}


def init():
    data.init()
    data.update_ref('HEAD', data.RefValue(symbolic=True, value='refs/heads/main'))


# ---------------------------------------------------------------------------
# Trees
# ---------------------------------------------------------------------------

def write_tree(directory='.'):
    """Recursively snapshot `directory` into a tree object and return its oid."""
    entries = []
    with os.scandir(directory) as it:
        for entry in sorted(it, key=lambda e: e.name):
            full = os.path.join(directory, entry.name)
            if is_ignored(full):
                continue
            if entry.is_file(follow_symlinks=False):
                type_ = 'blob'
                with open(full, 'rb') as f:
                    oid = data.hash_object(f.read())
            elif entry.is_dir(follow_symlinks=False):
                type_ = 'tree'
                oid = write_tree(full)
            else:
                continue
            entries.append((entry.name, oid, type_))

    tree_text = ''.join(f'{type_} {oid} {name}\n' for name, oid, type_ in entries)
    return data.hash_object(tree_text.encode(), 'tree')


def _iter_tree_entries(oid):
    if not oid:
        return
    tree_data = data.get_object(oid, 'tree')
    for line in tree_data.decode().splitlines():
        type_, oid_, name = line.split(' ', 2)
        yield type_, oid_, name


def get_tree(oid, base_path=''):
    """Flatten a tree object (and its subtrees) into {full_path: blob_oid}."""
    result = {}
    for type_, oid_, name in _iter_tree_entries(oid):
        path = base_path + name
        if type_ == 'blob':
            result[path] = oid_
        elif type_ == 'tree':
            result.update(get_tree(oid_, f'{path}/'))
        else:
            raise ValueError(f'Unknown tree entry type: {type_}')
    return result


def get_working_tree():
    """Flatten the actual files on disk into {path: blob_oid} (hashing as we go,
    without writing anything — used for `diff` and `status`)."""
    result = {}
    for root, dirnames, filenames in os.walk('.'):
        dirnames[:] = [d for d in dirnames if not is_ignored(os.path.join(root, d))]
        for filename in filenames:
            path = os.path.relpath(os.path.join(root, filename))
            if is_ignored(path):
                continue
            with open(path, 'rb') as f:
                result[path.replace(os.sep, '/')] = data.hash_object(f.read())
    return result


def _empty_current_directory():
    for root, dirnames, filenames in os.walk('.', topdown=False):
        dirnames[:] = [d for d in dirnames if not is_ignored(os.path.join(root, d))]
        for filename in filenames:
            path = os.path.relpath(os.path.join(root, filename))
            if is_ignored(path):
                continue
            os.remove(path)
        for dirname in dirnames:
            path = os.path.join(root, dirname)
            try:
                os.rmdir(path)
            except OSError:
                pass  # not empty (had an ignored file in it) — leave it


def read_tree(tree_oid, update_working=False):
    tree = get_tree(tree_oid)
    if update_working:
        _empty_current_directory()
        for path, oid in tree.items():
            os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
            with open(path, 'wb') as f:
                f.write(data.get_object(oid))
    return tree


def read_tree_merged(base_tree_oid, head_tree_oid, other_tree_oid, update_working=False):
    tree = diff_module.merge_trees(
        get_tree(base_tree_oid),
        get_tree(head_tree_oid),
        get_tree(other_tree_oid),
    )
    if update_working:
        _empty_current_directory()
        for path, blob in tree.items():
            os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
            with open(path, 'wb') as f:
                f.write(blob)
    return tree


# ---------------------------------------------------------------------------
# Commits
# ---------------------------------------------------------------------------

Commit = namedtuple('Commit', ['tree', 'parents', 'message'])


def commit(message):
    commit_lines = [f'tree {write_tree()}']

    HEAD = data.get_ref('HEAD').value
    if HEAD:
        commit_lines.append(f'parent {HEAD}')
    MERGE_HEAD = data.get_ref('MERGE_HEAD').value
    if MERGE_HEAD:
        commit_lines.append(f'parent {MERGE_HEAD}')
        data.delete_ref('MERGE_HEAD', deref=False)

    commit_lines.append('')
    commit_lines.append(message)
    commit_text = '\n'.join(commit_lines)

    oid = data.hash_object(commit_text.encode(), 'commit')
    data.update_ref('HEAD', data.RefValue(symbolic=False, value=oid))
    return oid


def get_commit(oid):
    parents = []
    commit_text = data.get_object(oid, 'commit').decode()
    lines = iter(commit_text.splitlines())

    tree = None
    for line in itertools.takewhile(operator.truth, lines):
        key, value = line.split(' ', 1)
        if key == 'tree':
            tree = value
        elif key == 'parent':
            parents.append(value)
        else:
            raise ValueError(f'Unknown commit field: {key}')

    message = '\n'.join(lines)
    return Commit(tree=tree, parents=parents, message=message)


def iter_commits_and_parents(oids):
    """Walk commit history breadth-first from a set of starting oids, yielding
    each commit oid exactly once (first parents first, like `git log`)."""
    oids = deque(oids)
    visited = set()
    while oids:
        oid = oids.popleft()
        if not oid or oid in visited:
            continue
        visited.add(oid)
        yield oid
        commit_obj = get_commit(oid)
        oids.extendleft(commit_obj.parents[:1])
        oids.extend(commit_obj.parents[1:])


def iter_objects_in_commits_and_parents(oids):
    visited = set()

    def iter_objects_in_tree(oid):
        visited.add(oid)
        yield oid
        for type_, sub_oid, _ in _iter_tree_entries(oid):
            if sub_oid in visited:
                continue
            if type_ == 'tree':
                yield from iter_objects_in_tree(sub_oid)
            else:
                visited.add(sub_oid)
                yield sub_oid

    for oid in iter_commits_and_parents(oids):
        yield oid
        commit_obj = get_commit(oid)
        if commit_obj.tree not in visited:
            yield from iter_objects_in_tree(commit_obj.tree)


# ---------------------------------------------------------------------------
# Branches, tags, checkout
# ---------------------------------------------------------------------------

def create_branch(name, oid):
    data.update_ref(f'refs/heads/{name}', data.RefValue(symbolic=False, value=oid))


def create_tag(name, oid):
    data.update_ref(f'refs/tags/{name}', data.RefValue(symbolic=False, value=oid))


def iter_branch_names():
    for refname, _ in data.iter_refs('refs/heads/'):
        yield os.path.relpath(refname, 'refs/heads')


def is_branch(name):
    return data.get_ref(f'refs/heads/{name}').value is not None


def get_branch_name():
    HEAD = data.get_ref('HEAD', deref=False)
    if not HEAD.symbolic:
        return None
    assert HEAD.value.startswith('refs/heads/')
    return os.path.relpath(HEAD.value, 'refs/heads')


def get_oid(name):
    """Resolve a name (branch, tag, 'HEAD', '@', or a raw/short sha1) to a full oid."""
    if name == '@':
        name = 'HEAD'

    refs_to_try = [
        name,
        f'refs/{name}',
        f'refs/tags/{name}',
        f'refs/heads/{name}',
    ]
    for ref in refs_to_try:
        if data.get_ref(ref, deref=False).value:
            return data.get_ref(ref).value

    # Not a ref — maybe it's a raw hash (full or unambiguous short form)
    is_hex = all(c in string.hexdigits for c in name)
    if is_hex and len(name) == 40 and data.object_exists(name):
        return name
    if is_hex and 4 <= len(name) < 40:
        matches = [oid for oid in os.listdir(f'{data.GIT_DIR}/objects')
                   if oid.startswith(name)]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValueError(f'Ambiguous short oid {name}: matches {matches}')

    raise ValueError(f'Unknown name: {name}')


def checkout(name):
    oid = get_oid(name)
    commit_obj = get_commit(oid)
    read_tree(commit_obj.tree, update_working=True)

    if is_branch(name):
        HEAD = data.RefValue(symbolic=True, value=f'refs/heads/{name}')
    else:
        HEAD = data.RefValue(symbolic=False, value=oid)
    data.update_ref('HEAD', HEAD, deref=False)


def reset(oid):
    data.update_ref('HEAD', data.RefValue(symbolic=False, value=oid))


# ---------------------------------------------------------------------------
# Merging
# ---------------------------------------------------------------------------

def get_merge_base(oid1, oid2):
    parents1 = set(iter_commits_and_parents({oid1}))
    for oid in iter_commits_and_parents({oid2}):
        if oid in parents1:
            return oid
    return None


def is_ancestor(commit_oid, maybe_ancestor):
    return maybe_ancestor in iter_commits_and_parents({commit_oid})


def merge(other_oid):
    HEAD = data.get_ref('HEAD').value
    assert HEAD, 'No commit on the current branch yet — nothing to merge into'

    merge_base = get_merge_base(other_oid, HEAD)
    c_other = get_commit(other_oid)

    if merge_base == HEAD:
        # Fast-forward: HEAD hasn't diverged, just move it up to `other`.
        read_tree(c_other.tree, update_working=True)
        data.update_ref('HEAD', data.RefValue(symbolic=False, value=other_oid))
        return {'fast_forward': True}

    if merge_base == other_oid:
        return {'fast_forward': False, 'already_up_to_date': True}

    data.update_ref('MERGE_HEAD', data.RefValue(symbolic=False, value=other_oid))
    c_base = get_commit(merge_base)
    c_head = get_commit(HEAD)
    merged_tree = read_tree_merged(c_base.tree, c_head.tree, c_other.tree, update_working=True)

    had_conflict = any(b'<<<<<<< HEAD' in content for content in merged_tree.values())
    return {'fast_forward': False, 'already_up_to_date': False, 'conflict': had_conflict}


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------

def is_ignored(path):
    parts = os.path.normpath(path).split(os.sep)
    return any(part in IGNORED_DIRS for part in parts)
