"""
cli.py — the `pygit <command>` command-line interface.

Run as: python -m pygit <command> [args]
"""

import argparse
import os
import sys

from . import base
from . import data
from . import diff as diff_module


def main():
    try:
        args = parse_args()
        args.func(args)
    except (AssertionError, ValueError, FileNotFoundError) as e:
        print(f'Error: {e}', file=sys.stderr)
        sys.exit(1)


def parse_args():
    parser = argparse.ArgumentParser(prog='pygit', description='A Git implementation built from scratch.')
    commands = parser.add_subparsers(dest='command', metavar='command')
    commands.required = True

    oid = base.get_oid  # shorthand used as an argparse `type=` converter

    init_parser = commands.add_parser('init', help='create an empty repository')
    init_parser.set_defaults(func=init)

    hash_object_parser = commands.add_parser('hash-object', help='store a file as a blob object')
    hash_object_parser.set_defaults(func=hash_object)
    hash_object_parser.add_argument('file')

    cat_file_parser = commands.add_parser('cat-file', help='print an object\'s content')
    cat_file_parser.set_defaults(func=cat_file)
    cat_file_parser.add_argument('object', type=oid)

    write_tree_parser = commands.add_parser('write-tree', help='snapshot the working directory')
    write_tree_parser.set_defaults(func=write_tree)

    read_tree_parser = commands.add_parser('read-tree', help='restore working directory from a tree')
    read_tree_parser.set_defaults(func=read_tree)
    read_tree_parser.add_argument('tree', type=oid)

    commit_parser = commands.add_parser('commit', help='record a snapshot of the working directory')
    commit_parser.set_defaults(func=commit)
    commit_parser.add_argument('-m', '--message', required=True)

    log_parser = commands.add_parser('log', help='show commit history')
    log_parser.set_defaults(func=log)
    log_parser.add_argument('oid', default='@', type=oid, nargs='?')

    show_parser = commands.add_parser('show', help='show a commit and its diff')
    show_parser.set_defaults(func=show)
    show_parser.add_argument('oid', default='@', type=oid, nargs='?')

    diff_parser = commands.add_parser('diff', help='show changes vs a commit (default: HEAD)')
    diff_parser.set_defaults(func=_diff)
    diff_parser.add_argument('commit', nargs='?')

    checkout_parser = commands.add_parser('checkout', help='switch to a branch or commit')
    checkout_parser.set_defaults(func=checkout)
    checkout_parser.add_argument('commit')

    tag_parser = commands.add_parser('tag', help='create a tag')
    tag_parser.set_defaults(func=tag)
    tag_parser.add_argument('name')
    tag_parser.add_argument('oid', default='@', type=oid, nargs='?')

    branch_parser = commands.add_parser('branch', help='list or create branches')
    branch_parser.set_defaults(func=branch)
    branch_parser.add_argument('name', nargs='?')
    branch_parser.add_argument('start_point', default='@', type=oid, nargs='?')

    k_parser = commands.add_parser('k', help='dump the commit graph as a Graphviz .dot file')
    k_parser.set_defaults(func=k)

    status_parser = commands.add_parser('status', help='show current branch and changed files')
    status_parser.set_defaults(func=status)

    reset_parser = commands.add_parser('reset', help='move HEAD to a commit')
    reset_parser.set_defaults(func=reset)
    reset_parser.add_argument('commit', type=oid)

    merge_parser = commands.add_parser('merge', help='merge a branch/commit into the current branch')
    merge_parser.set_defaults(func=merge)
    merge_parser.add_argument('commit', type=oid)

    merge_base_parser = commands.add_parser('merge-base', help='find the common ancestor of two commits')
    merge_base_parser.set_defaults(func=merge_base)
    merge_base_parser.add_argument('commit1', type=oid)
    merge_base_parser.add_argument('commit2', type=oid)

    return parser.parse_args()


def _require_repo():
    if not data.repo_exists():
        print('Not a pygit repository (no .pygit directory found). Run `python -m pygit init` first.',
              file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Command implementations
# ---------------------------------------------------------------------------

def init(args):
    base.init()
    print(f'Initialized empty pygit repository in {os.path.join(os.getcwd(), data.GIT_DIR)}')


def hash_object(args):
    _require_repo()
    with open(args.file, 'rb') as f:
        print(data.hash_object(f.read()))


def cat_file(args):
    _require_repo()
    sys.stdout.flush()
    sys.stdout.buffer.write(data.get_object(args.object, expected=None))


def write_tree(args):
    _require_repo()
    print(base.write_tree())


def read_tree(args):
    _require_repo()
    base.read_tree(args.tree, update_working=True)


def commit(args):
    _require_repo()
    print(base.commit(args.message))


def _print_commit(oid, commit_obj, refs=None):
    refs_str = f' ({", ".join(refs)})' if refs else ''
    print(f'commit {oid}{refs_str}')
    for line in commit_obj.message.splitlines():
        print(f'    {line}')
    print()


def log(args):
    _require_repo()
    refs = {}
    for refname, ref in data.iter_refs():
        refs.setdefault(ref.value, []).append(refname)

    for oid in base.iter_commits_and_parents({args.oid}):
        _print_commit(oid, base.get_commit(oid), refs.get(oid))


def show(args):
    _require_repo()
    if not args.oid:
        return
    commit_obj = base.get_commit(args.oid)
    parent_tree = base.get_commit(commit_obj.parents[0]).tree if commit_obj.parents else None

    _print_commit(args.oid, commit_obj)
    result = diff_module.diff_trees(base.get_tree(parent_tree), base.get_tree(commit_obj.tree))
    sys.stdout.flush()
    sys.stdout.buffer.write(result)


def _diff(args):
    _require_repo()
    oid = base.get_oid(args.commit) if args.commit else data.get_ref('HEAD').value
    tree_oid = base.get_commit(oid).tree if oid else None
    result = diff_module.diff_trees(base.get_tree(tree_oid), base.get_working_tree())
    sys.stdout.flush()
    sys.stdout.buffer.write(result)


def checkout(args):
    _require_repo()
    base.checkout(args.commit)


def tag(args):
    _require_repo()
    base.create_tag(args.name, args.oid)


def branch(args):
    _require_repo()
    if not args.name:
        current = base.get_branch_name()
        for name in base.iter_branch_names():
            prefix = '*' if name == current else ' '
            print(f'{prefix} {name}')
    else:
        base.create_branch(args.name, args.start_point)
        print(f'Branch {args.name} created at {args.start_point[:10]}')


def k(args):
    _require_repo()
    dot = 'digraph commits {\n'
    oids = set()
    for refname, ref in data.iter_refs(deref=False):
        dot += f'  "{refname}" [shape=note]\n'
        dot += f'  "{refname}" -> "{ref.value}"\n'
        if not ref.symbolic:
            oids.add(ref.value)

    for oid in base.iter_commits_and_parents(oids):
        commit_obj = base.get_commit(oid)
        dot += f'  "{oid}" [shape=box style=filled label="{oid[:10]}"]\n'
        for parent in commit_obj.parents:
            dot += f'  "{oid}" -> "{parent}"\n'
    dot += '}\n'

    out_path = 'pygit-graph.dot'
    with open(out_path, 'w') as f:
        f.write(dot)
    print(f'Commit graph written to {out_path}')
    print('View it at https://dreampuf.github.io/GraphvizOnline/ or with `dot -Tpng` if Graphviz is installed.')


def status(args):
    _require_repo()
    HEAD = data.get_ref('HEAD').value
    branch_name = base.get_branch_name()
    if branch_name:
        print(f'On branch {branch_name}')
    elif HEAD:
        print(f'HEAD detached at {HEAD[:10]}')
    else:
        print('On branch main (no commits yet)')

    MERGE_HEAD = data.get_ref('MERGE_HEAD').value
    if MERGE_HEAD:
        print(f'Merging with {MERGE_HEAD[:10]}')

    HEAD_tree = base.get_commit(HEAD).tree if HEAD else None
    print('\nChanges since last commit:\n')
    changes = list(diff_module.iter_changed_files(base.get_tree(HEAD_tree), base.get_working_tree()))
    if not changes:
        print('  (nothing changed)')
    for path, action in changes:
        print(f'  {action:>10}: {path}')


def reset(args):
    _require_repo()
    base.reset(args.commit)


def merge(args):
    _require_repo()
    result = base.merge(args.commit)
    if result.get('fast_forward'):
        print('Fast-forwarded — no commit needed.')
    elif result.get('already_up_to_date'):
        print('Already up to date.')
    elif result.get('conflict'):
        print('Merged with CONFLICTS. Resolve the <<<<<<< markers, then commit.')
    else:
        print('Merged cleanly in the working tree. Run `commit` to record it.')


def merge_base(args):
    _require_repo()
    print(base.get_merge_base(args.commit1, args.commit2))
