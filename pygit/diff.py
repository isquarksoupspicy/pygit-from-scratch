"""
diff.py — comparing and merging trees/blobs.

Deliberately dependency-free: uses Python's built-in `difflib` instead
of shelling out to the system `diff`/`diff3` binaries, so this works
identically on Windows, macOS and Linux with nothing extra installed.
"""

import difflib
from collections import defaultdict

from . import data


def compare_trees(*trees):
    """Given several {path: oid} dicts, yield (path, oid_in_tree1, oid_in_tree2, ...)
    for every path that appears in ANY of the trees (missing = None)."""
    entries = defaultdict(lambda: [None] * len(trees))
    for i, tree in enumerate(trees):
        for path, oid in tree.items():
            entries[path][i] = oid

    for path, oids in entries.items():
        yield (path, *oids)


def iter_changed_files(t_from, t_to):
    for path, o_from, o_to in compare_trees(t_from, t_to):
        if o_from != o_to:
            action = ('new file' if not o_from else
                       'deleted' if not o_to else
                       'modified')
            yield path, action


def _read_lines(oid):
    if not oid:
        return []
    content = data.get_object(oid)
    try:
        text = content.decode('utf-8')
    except UnicodeDecodeError:
        return None  # binary file, can't line-diff it
    return text.splitlines(keepends=True)


def diff_blobs(o_from, o_to, path='file'):
    from_lines = _read_lines(o_from)
    to_lines = _read_lines(o_to)

    if from_lines is None or to_lines is None:
        if o_from == o_to:
            return b''
        return f'Binary files a/{path} and b/{path} differ\n'.encode()

    diff = difflib.unified_diff(
        from_lines, to_lines,
        fromfile=f'a/{path}', tofile=f'b/{path}',
    )
    return ''.join(diff).encode()


def diff_trees(t_from, t_to):
    output = b''
    for path, o_from, o_to in compare_trees(t_from, t_to):
        if o_from != o_to:
            output += diff_blobs(o_from, o_to, path)
    return output


def merge_trees(t_base, t_head, t_other):
    """3-way merge two trees against their common base. Returns {path: content_bytes}."""
    tree = {}
    for path, o_base, o_head, o_other in compare_trees(t_base, t_head, t_other):
        tree[path] = merge_blobs(o_base, o_head, o_other, path)
    return tree


def merge_blobs(o_base, o_head, o_other, path='file'):
    """Merge one file's three versions. If only one side changed, take it.
    If both sides changed the same way, take it. Otherwise, emit
    git-style conflict markers so nothing is silently lost."""
    if o_head == o_other:
        return data.get_object(o_head) if o_head else b''
    if o_base == o_head:
        return data.get_object(o_other) if o_other else b''
    if o_base == o_other:
        return data.get_object(o_head) if o_head else b''

    head_lines = _read_lines(o_head)
    other_lines = _read_lines(o_other)

    # Both sides changed, and differently: emit a git-style conflict block
    # rather than guessing. This is intentionally simple (whole-file,
    # not line-level) so it is predictable and has no edge cases.
    head_text = ''.join(head_lines) if head_lines is not None else (
        data.get_object(o_head).decode(errors='replace') if o_head else '')
    other_text = ''.join(other_lines) if other_lines is not None else (
        data.get_object(o_other).decode(errors='replace') if o_other else '')
    if head_text and not head_text.endswith('\n'):
        head_text += '\n'
    if other_text and not other_text.endswith('\n'):
        other_text += '\n'
    merged_text = (
        f'<<<<<<< HEAD\n{head_text}'
        f'=======\n{other_text}'
        f'>>>>>>> MERGE_HEAD\n'
    )
    return merged_text.encode()
