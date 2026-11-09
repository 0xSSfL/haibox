# Built-in profiles

The canonical built-in profiles live inside the Python package at:

```text
src/redoubt/data/profiles/
```

User profiles can override them in:

```text
~/.config/redoubt/profiles/<name>.yaml
```

The Web Security profile is the only profile with an image definition in the
first milestone. Its image has not been built or verified yet. The Core,
Network Security, and Full Toolkit profiles are experimental placeholders;
their images are not defined.

A profile is frozen into `engagement.yaml` at creation. Editing a profile later
does not widen an existing engagement.
