# pygit — Git, built from scratch

A working reimplementation of Git's core internals in plain Python (standard
library only — no external packages, no `diff`/`diff3` system binaries).
It stores real content-addressed objects, builds trees and commits, and
supports branching, checkout, and merging (including conflict detection),
exactly the way Git does internally — just simplified and readable.

## Why

Git's day-to-day commands (`add`, `commit`, `branch`, `merge`, ...) are a thin
CLI wrapped around a surprisingly small set of ideas: a content-addressed
object store, trees that snapshot directories, commits that chain trees
together, and refs that are just named pointers to commits. This project
implements those ideas directly, to understand *why* Git behaves the way it
does rather than only *how* to use it.

## Architecture

```
pygit/
  data.py   — the object store: hash_object/get_object (blobs, trees, commits
              stored as sha1-addressed, zlib-compressed files), plus refs
              (HEAD, branches, tags) as plain text files under .pygit/refs/.
  base.py   — the semantic layer: write_tree/read_tree, commit/get_commit,
              branches, checkout, and 3-way merge, all built only out of
              data.py's primitives.
  diff.py   — pure-Python diff/merge using difflib (unified diffs, and a
              3-way merge that emits <<<<<<< HEAD conflict markers when two
              branches change the same file differently).
  cli.py    — the `pygit <command>` argument parser and command handlers.
tests/
  test_pygit.py — end-to-end tests that run the real CLI in a temp directory.
```

There's no staging area / index (unlike real Git) — `commit` always snapshots
the whole working directory, the same way the very first Git prototypes
worked. This keeps the mental model small while still covering every core
concept: objects, trees, commits, refs, branches, checkout, and merge.

## Requirements

Python 3.8+. Nothing else — no `pip install`, no system `diff`/`diff3`
binaries required (this was a deliberate choice so it behaves identically on
Windows, macOS, and Linux).

## Usage

Run every command as `python -m pygit <command>` from inside your project
directory.

```bash
python -m pygit init                    # create .pygit/
python -m pygit hash-object file.txt    # store a file, print its oid
python -m pygit cat-file <oid>          # print a stored object's content
python -m pygit write-tree              # snapshot the working dir -> tree oid
python -m pygit read-tree <oid>         # restore working dir from a tree

python -m pygit commit -m "message"     # snapshot + commit
python -m pygit log                     # commit history from HEAD
python -m pygit show <oid>              # a commit + its diff
python -m pygit diff [<oid>]            # working dir vs a commit (default HEAD)
python -m pygit status                  # current branch + changed files

python -m pygit branch                  # list branches
python -m pygit branch <name> [<oid>]   # create a branch
python -m pygit checkout <name-or-oid>  # switch branch / commit
python -m pygit tag <name> [<oid>]      # tag a commit
python -m pygit reset <oid>             # move HEAD (like `git reset --soft`)

python -m pygit merge <name-or-oid>     # merge into the current branch
python -m pygit merge-base <a> <b>      # common ancestor of two commits
python -m pygit k                       # dump commit graph to a .dot file
```

Names like `main`, `HEAD`, `@` (shorthand for HEAD), tag names, and full or
unambiguous short sha1 prefixes (e.g. `b4f6f8`) are all accepted anywhere a
commit is expected.

## How merging works

`merge` finds the common ancestor of the two branches (`merge-base`):

- If the current branch hasn't moved since the ancestor, it's a
  **fast-forward** — HEAD just jumps to the other commit, no new commit needed.
- Otherwise it's a real **3-way merge**: for every file, if only one side
  changed it, that side wins; if both sides changed it identically, that's
  used; if both changed it *differently*, `pygit` writes a conflict block
  (`<<<<<<< HEAD ... ======= ... >>>>>>> MERGE_HEAD`) into the file instead of
  guessing, exactly like real Git does. Resolve the markers by hand, then
  `commit` to finish the merge.

This is a whole-file conflict marker (not Git's line-level 3-way diff3
merge) — a deliberate simplification to keep the merge logic easy to reason
about and bug-free, while still handling the common cases (non-overlapping
changes, identical changes, one-sided changes) exactly like Git would.

## Running the tests

```bash
python -m unittest discover -s tests -v
```

11 end-to-end tests cover object storage, commits, checkout, branching,
fast-forward and conflicting merges, diff, and status.

## What's simplified vs. real Git

- No staging area/index — every commit snapshots the full working directory.
- No remotes (`push`/`fetch`/`clone` over a network) — everything is local.
- Merge conflicts are whole-file, not line-level.
- `k` writes a Graphviz `.dot` file instead of opening a GUI (paste it into
  https://dreampuf.github.io/GraphvizOnline/ to view it, or run
  `dot -Tpng pygit-graph.dot -o graph.png` if you have Graphviz installed).

These were conscious trade-offs to keep the implementation small, dependency-free,
and correct, rather than trying to match Git feature-for-feature.
