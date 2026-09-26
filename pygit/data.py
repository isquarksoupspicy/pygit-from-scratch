"""
data.py — the lowest layer of pygit.

Everything here deals directly with the on-disk format:
- the object store (.pygit/objects/<sha1>) which holds blobs, trees, commits
- refs (.pygit/HEAD, .pygit/refs/heads/*, .pygit/refs/tags/*)

Nothing in this file knows what a "commit" or "tree" *means* — that
logic lives in base.py. This file only knows how to store and
retrieve bytes by hash, and how to read/write ref files.
"""

import hashlib
import os
import zlib
from collections import namedtuple

GIT_DIR = '.pygit'


def init():
    """Create an empty repository in the current directory."""
    if os.path.isdir(GIT_DIR):
        raise FileExistsError(f'{GIT_DIR} already exists in this directory')
    os.makedirs(GIT_DIR)
    os.makedirs(f'{GIT_DIR}/objects')


def repo_exists():
    return os.path.isdir(GIT_DIR)


# ---------------------------------------------------------------------------
# Refs (HEAD, branches, tags)
# ---------------------------------------------------------------------------

# A ref either points straight at an object id (symbolic=False)
# or points at another ref, e.g. HEAD -> refs/heads/main (symbolic=True)
RefValue = namedtuple('RefValue', ['symbolic', 'value'])


def update_ref(ref, value, deref=True):
    ref = _get_ref_internal(ref, deref)[0]

    assert value.value
    if value.symbolic:
        contents = f'ref: {value.value}'
    else:
        contents = value.value

    ref_path = f'{GIT_DIR}/{ref}'
    os.makedirs(os.path.dirname(ref_path), exist_ok=True)
    with open(ref_path, 'w') as f:
        f.write(contents)


def get_ref(ref, deref=True):
    return _get_ref_internal(ref, deref)[1]


def delete_ref(ref, deref=True):
    ref = _get_ref_internal(ref, deref)[0]
    ref_path = f'{GIT_DIR}/{ref}'
    if os.path.isfile(ref_path):
        os.remove(ref_path)


def _get_ref_internal(ref, deref):
    ref_path = f'{GIT_DIR}/{ref}'
    value = None
    if os.path.isfile(ref_path):
        with open(ref_path) as f:
            value = f.read().strip()

    symbolic = bool(value) and value.startswith('ref:')
    if symbolic:
        value = value.split(':', 1)[1].strip()
        if deref:
            return _get_ref_internal(value, deref=True)

    return ref, RefValue(symbolic=symbolic, value=value)


def iter_refs(prefix='', deref=True):
    """Yield (refname, RefValue) for every existing ref (HEAD, branches, tags)."""
    refs = ['HEAD', 'MERGE_HEAD']
    refs_dir = f'{GIT_DIR}/refs'
    if os.path.isdir(refs_dir):
        for root, _, filenames in os.walk(refs_dir):
            root = os.path.relpath(root, GIT_DIR).replace(os.sep, '/')
            refs.extend(f'{root}/{name}' for name in filenames)

    for refname in refs:
        if not refname.startswith(prefix):
            continue
        ref_value = get_ref(refname, deref=deref)
        if ref_value.value:
            yield refname, ref_value


# ---------------------------------------------------------------------------
# Object store
# ---------------------------------------------------------------------------

def hash_object(data_bytes, type_='blob'):
    """Store `data_bytes` in the object store, tagged with `type_`.
    Returns the sha1 hash (the object id / oid)."""
    obj = type_.encode() + b'\x00' + data_bytes
    oid = hashlib.sha1(obj).hexdigest()
    path = f'{GIT_DIR}/objects/{oid}'
    if not os.path.isfile(path):
        with open(path, 'wb') as out:
            out.write(zlib.compress(obj))
    return oid


def get_object(oid, expected='blob'):
    """Retrieve the raw content of the object with id `oid`.
    If `expected` is given, assert the object's type matches."""
    path = f'{GIT_DIR}/objects/{oid}'
    with open(path, 'rb') as f:
        obj = zlib.decompress(f.read())

    type_, _, content = obj.partition(b'\x00')
    type_ = type_.decode()

    if expected is not None:
        assert type_ == expected, f'Expected {expected}, got {type_}'
    return content


def object_exists(oid):
    return os.path.isfile(f'{GIT_DIR}/objects/{oid}')
