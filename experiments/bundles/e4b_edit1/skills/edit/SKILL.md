---
name: edit
description: Replaces a block of lines in a source file, ignoring differences in indentation and spacing, then checks the file still parses and shows the result. Use it for every change to existing code instead of edit_file.
---

# edit

`edit_file` refuses an edit when `old_string` differs from the file by one space. This does not.

Call `run_skill_script` with `skill_name` "edit", `file_path` "scripts/edit.py" and `args`, in one of two forms.

By text (copy the lines to replace, one to ten lines; indentation and spacing do not have to match):

{"file": "pkg/mod.py", "old": "if x > 1:\n    return a", "new": "if x >= 1:\n    return a"}

By line numbers (lines N to M inclusive, as shown by `read_file` or `sed -n`):

{"file": "pkg/mod.py", "start": "40", "end": "41", "new": "if x >= 1:\n    return a"}

`new` replaces the whole block. Give it with any indentation: it is moved to the indentation of the first replaced line, and the lines after the first keep their position relative to it.

The output is either `edited FILE, now lines A-B` followed by those lines with numbers, or `NOT EDITED` and the reason. Reasons: the old text was not found (the closest lines are shown), it matches several places (their line numbers are shown), or a Python file would no longer parse (the file is left unchanged). Test files are refused.

It costs one tool call. Read the printed lines to check the edit before moving on.
