# Wakako (for AI agents)

This repo is `wakako`, a command-line tool for Google Search Console and Google Analytics 4
(`gsc` still works as a short alias).

- **To use it:** run `wakako skill show` (full usage guide, recipes, output contract) and
  `wakako commands` (machine-readable list of commands, options, valid values, exit codes).
  Run `wakako doctor` to check setup. `wakako login` needs a human - never attempt it yourself.
- **To change it:** source is in `src/wakako/`, tests in `tests/` (`python -m pytest`).
  The agent usage guide lives in `src/wakako/skill/SKILL.md`; keep it in sync with any
  CLI change (a test checks that every command is mentioned in it).
