# Beyond Python — Make and Node

Wringer is written in Python, but nothing about it is *for* Python. It runs
the commands a repository already declares, whatever they are. This page is
the receipt for that claim: real captured output from two repos with no
Python in them.

The implementation is Python for the reasons in
[SPEC_VERIFY_V0.md](../SPEC_VERIFY_V0.md#implementation-stack) — ubiquitous,
inspectable, `pipx`-installable. What it verifies is your business.

## A Make project

A shell project: two source files, a `Makefile` with `lint` and `test`
targets, no package manager and no Python anywhere.

```
Makefile
src/greet.sh
tests/run.sh
```

`wring init` reads the Makefile and writes the gates it finds:

```
$ wring init
Wrote .wringer.yaml from Makefile — gates: lint, test
Check they are the commands you want proven, then: wring verify
Added .wringer/ to .gitignore
```

```yaml
version: 1

gates:
  - id: lint
    run: make lint
    timeout: 120

  - id: test
    run: make test
    timeout: 300
```

Note what is **not** there: no `deploy` gate, even though the Makefile could
have one. Verifying must never ship anything.

A healthy tree:

```
$ wring verify
✓ lint passed        0.0s
✓ test passed        0.0s

Evidence written to:
.wringer/runs/20260730-230822-9484/
```

Now break `greet()` so it stops defaulting its argument, and run it again:

```
$ wring verify
✓ lint passed        0.0s
✗ test failed        0.0s

--- gates/002_test/stdout.log ---
ok    greets a name
FAIL  defaults to world
      expected: Hello, world!
      actual:   

--- gates/002_test/stderr.log ---
tests/../src/greet.sh: line 4: $1: unbound variable
make: *** [test] Error 1

Evidence written to:
.wringer/runs/20260730-230831-b002/

Next:
  open .wringer/runs/20260730-230831-b002/summary.md
  rerun wring verify --gate test
```

Exit code `1`, both streams captured, and a bundle on disk — the same
contract a Python repo gets. The test suite here is a shell script with no
framework at all; Wringer neither knows nor cares.

For an agent:

```
$ wring verify --json
{"status": "failed", "failed_gate": "test", "rerun": "wring verify --gate test", "evidence_dir": ".wringer/runs/20260730-230831-2d78"}
```

## A Node project

A `package.json` with four scripts:

```json
{
  "scripts": {
    "lint": "eslint .",
    "test": "vitest run",
    "build": "tsc -p .",
    "dev": "vite"
  }
}
```

```
$ wring init
Wrote .wringer.yaml from package.json — gates: lint, build, test
Check they are the commands you want proven, then: wring verify
Added .wringer/ to .gitignore
```

```yaml
version: 1

gates:
  - id: lint
    run: npm run lint
    timeout: 120

  - id: build
    run: npm run build
    timeout: 300

  - id: test
    run: npm test
    timeout: 300
```

Three things to notice: `test` becomes `npm test` rather than `npm run test`,
gates come out cheapest-first rather than in `package.json` order, and `dev`
is not a gate — a dev server proves nothing and would never exit.

> **Honesty note.** The `wring verify` half of this walkthrough is not shown
> because the machine these transcripts were captured on has no Node
> installed, and this project does not paste output it has not run. What is
> shown above is real. Detection is covered by the test suite
> ([tests/test_detect.py](../tests/test_detect.py)); the gate runner is the
> same code path the Make and Python walkthroughs exercise.

## What detection will not do

`wring init` reports commands your repo has **already written down**. It does
not invent one. When it finds nothing it says so and writes a commented
template rather than guessing — a wrong gate is worse than an absent one,
because it makes `wring verify` prove something nobody asked for.

That rule is load-bearing and has been got wrong once: a `tests/` directory
alone used to be read as "this is a Python project", so a shell repo with
`tests/run.sh` was handed an invented `pytest -q` gate and then failed
verification with *"no tests ran"* on a perfectly healthy tree. Detection now
requires actual Python files. If you find another case where Wringer invents
a command nobody wrote down, that is a bug — please
[open an issue](https://github.com/marcoakes/wringer/issues).

Whatever it writes, read `.wringer.yaml` before trusting it. It is a starting
point, not an oracle.
