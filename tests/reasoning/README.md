# Reasoning Tests

> Tests that verify a model understands and correctly applies TAHOE language
> patterns. These are not unit tests of TAHOE code — they test the model's
> comprehension of the thinking framework.

## Structure

Each test presents a TAHOE reasoning scenario and checks:
1. Does the model identify the correct protocol?
2. Does the model use typed refs correctly?
3. Does the model verify before returning?
4. Does the model produce the right answer?

## Running

```bash
PYTHONPATH=src python3 -m pytest tests/reasoning/ -x -q
```

These tests require API access (TAHOE_API_BASE, TAHOE_API_KEY env vars).
