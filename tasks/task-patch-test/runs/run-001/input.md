Modify `sandbox/hello.py`.

Change this line:

```
    print("Hello")
```

to:

```
    print("Hello Agent")
```

Requirements:
- You must use the `patch_file` tool for this edit. Do not use `write_file`.
- Choose `old_text` precisely enough that it matches exactly one location in the file (for example, include enough of the surrounding line rather than just the word `Hello`).
- After applying the patch, use `read_file` to verify the file now contains the updated line.
- Report exactly what you changed.
