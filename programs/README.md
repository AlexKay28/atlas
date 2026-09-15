# Programs

TAHOE programs for the project's experiments and plans.

**Why**: every experiment has (a) its plan as a TAHOE program — reviewable,
diffable, and parseable by the real grammar — and (b) a RUN.md with exact
reproduction commands, data pointers, results, and caveats.

```
programs/
├── experiments/<date-<study>>/
│   ├── program.think     the experiment plan in TAHOE notation (parser-valid)
│   └── RUN.md            reproduction commands + data pointers + caveats
└── plans/                strategic plans (session/research arcs)
```

**Guarantee**: every `program.think` parses with the reference grammar
(`src/tahoe/syntax/parser.py`) — enforced by `tests/test_programs.py`.

Note: this directory holds TAHOE-language programs. The Python package
implementing the language lives at `src/tahoe/` (kept separate to avoid a
namespace clash).
