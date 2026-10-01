# gsc-wrapper (for AI agents)

This repo is the `gsc` command-line tool for Google Search Console.

- **To use it:** run `gsc skill show` (full usage guide, recipes, output contract) and
  `gsc commands` (machine-readable list of commands, options, valid values, exit codes).
  Run `gsc doctor` to check setup. `gsc login` needs a human - never attempt it yourself.
- **To change it:** source is in `src/gsc_cli/`, tests in `tests/` (`python -m pytest`).
  The agent usage guide lives in `src/gsc_cli/skill/SKILL.md`; keep it in sync with any
  CLI change (a test checks that every command is mentioned in it).
