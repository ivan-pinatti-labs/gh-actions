# Tasks for this repository.
#
# checkmake reads only the first physical line of a .PHONY declaration and
# silently drops backslash continuations, so every .PHONY here is written on
# one line. Splitting one across lines leaves the trailing targets invisible
# to it, and the phonydeclared and minphony rules then report them as
# undeclared. Tracked upstream as checkmake#280.
.PHONY: all help test workbench-help

# Bare `make` shows the target list rather than doing something surprising.
# checkmake's minphony rule also wants `all` declared phony; see checkmake.ini.
all: help

help:
	@printf '%s\n' \
		'Usage:' \
		'  make <target>' \
		'' \
		'Targets:' \
		'  help                        Show this message.' \
		'  test                        Fetch the originals and run the equivalence suite, in L2.' \
		''
	@$(MAKE) --no-print-directory workbench-help

# The test suite, in L2 rather than in the workbench: `l2 --net` gives it the
# working tree and a way out through the egress proxy, for the originals the
# equivalence tests compare against (public files on GitHub, fetched without
# a token), and nothing else. Outside a workbench there is no l2, and the
# same commands run as they are.
#
# `;` rather than `&&` after the fetch on purpose. The equivalence tests skip
# when the originals are absent, so a developer with no network still gets the
# rest of the suite. CI keeps the fetch as its own step, where a failure is
# loud, because there a skipped comparison is exactly what must not pass
# silently.
L2_NET := $(if $(shell command -v l2 2>/dev/null),l2 --net --,)
test:
	@$(L2_NET) bash -c 'tools/fetch-originals.sh; python3 -m pytest tests/ -v'

# The workbench targets (make claude, make codex, make unlock and the rest)
# come from a devcontainer-airlock clone, by default the one next to this
# repository's main clone, so every worktree finds the same one. See
# .devcontainer/README.md.
WORKBENCH_HOME ?= $(abspath $(dir $(shell git rev-parse --path-format=absolute --git-common-dir 2>/dev/null))../devcontainer-airlock)
-include $(WORKBENCH_HOME)/host/workbench.mk

ifeq ($(wildcard $(WORKBENCH_HOME)/host/workbench.mk),)
workbench-help:
	@printf '%s\n' \
		'Workbench: no devcontainer-airlock clone at $(WORKBENCH_HOME).' \
		'  Clone ivan-pinatti-labs/devcontainer-airlock there, or set WORKBENCH_HOME,' \
		'  for make claude, make codex, make unlock and the rest (.devcontainer/README.md).'
endif
