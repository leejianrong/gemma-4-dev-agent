---
name: localize
description: Ranks the functions and classes of the repository against the issue text with BM25 and prints the top 10 with file and line, plus the other definitions in the same files. Use it once at the start of a task to find where to edit.
---

# localize

One call replaces several `grep` and `read_file` rounds when you are looking for the place to edit.

Run `scripts/localize.py --siblings` with the issue text as the argument. Pass the words that
describe the bug: error messages, function and class names, option names. A short query works
better than the whole issue.

It prints up to 10 lines such as:

```
 1. fastapi.routing.APIRoute.get_route_handler  fastapi/routing.py:312
```

Each line is a dotted name and `path:line`. Open the best few with `read_file` and check them
against the issue before you edit. It ranks by word overlap, so it can miss when the issue
describes behaviour without naming the code; then search with `grep` for the error text.

With `--siblings` it then lists, for each of the top 3 hits, the other definitions in the same file
(up to 8 per file, best match first):

```
fastapi/routing.py (near fastapi.routing.APIRoute.get_route_handler):
  fastapi.routing.APIRoute.__init__  :280
```

A patch often edits more than one place in a file, so look at these when the fix touches shared
behaviour. Skip them for a one-line fix.

The whole output stays under 3,000 characters, so it fits the context. It skips tests and docs,
reads only `/workspace`, and writes nothing.
