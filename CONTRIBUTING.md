# Contributing

## Setup

```bash
# Install mise (if not already)
curl https://mise.run | sh

# Setup the project
mise trust && mise install
uv sync
```

## Development

```bash
uv run pytest              # run tests
uv run ruff check src/     # lint
uv run ruff format src/    # format
uv run mypy src/           # type check
```

## Commit conventions

This project uses [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` — new feature
- `fix:` — bug fix
- `docs:` — documentation only
- `refactor:` — code change that neither fixes a bug nor adds a feature
- `test:` — adding or updating tests
- `chore:` — maintenance tasks

## Architecture

See [docs/architecture.md](docs/architecture.md) for the full design. Key rules:

1. Import hierarchy is strictly downward (raw → core → extra → utils → ...)
2. Core graph is 100% synchronous — no asyncio in core/
3. Use typed Protocol classes, not integer type tags
