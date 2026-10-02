# Tasks for this repository.
#
# checkmake reads only the first physical line of a .PHONY declaration and
# silently drops backslash continuations, so every .PHONY here is written on
# one line. Splitting one across lines leaves the trailing targets invisible
# to it, and the phonydeclared and minphony rules then report them as
# undeclared. Tracked upstream as checkmake#280.
.PHONY: all help test coverage workbench-help

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
		'  coverage                    Python and shell coverage in containers, 100% or fail.' \
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

# Coverage of everything this repository writes, held at 100%: the Python
# under src/ and tools/ (lines and branches, .coveragerc) under coverage.py,
# and tools/fetch-originals.sh (lines; kcov reports no branches for bash)
# under kcov, with curl replaced by a stub. Writes the two reports SonarQube
# Cloud reads, $(COVERAGE_DIR)/coverage.xml and $(COVERAGE_DIR)/shell.xml, and
# fails if either language is under 100%. .github/workflows/sonarqube.yml
# runs this, and so does the `coverage` pre-push hook. The bash inline in the
# workflows is not measured: it only runs inside GitHub Actions.
#
# The Python container fetches the originals first, with
# tools/fetch-originals.sh, and stops if that fails: the suite reads fixture
# trees out of them as well as comparing against them, so without them it
# fails rather than measures.
#
# Both tools run in containers that cannot see this checkout. The files git
# would commit (tracked, plus new ones not ignored) go in on standard input
# as a tar stream, and the only host path either container gets is an empty
# scratch directory for its report. Nothing else is mounted: no home
# directory, no SSH agent, no token, and podman passes no environment
# variable that is not named. Both drop every capability; kcov also gets no
# network and a read only root filesystem. The Python container needs the
# network for its pip install and the fetch. It is the full python image
# rather than the slim one because the suite builds real `git diff` output
# and the fetch uses curl, and slim has neither. The images are pinned by digest, and Renovate moves the digests.
#
# The scratch directory comes from mktemp, so it lands in TMPDIR. In a
# devcontainer-airlock workbench run this as `l2 --engine --net -- make
# coverage`: the engine can only mount paths under the TMPDIR it sets.
#
# Both reports are written before either verdict is given, so CI can still
# hand SonarQube the report of a run that falls short.
COVERAGE_DIR ?= coverage
PODMAN ?= $(if $(CONTAINER_HOST),podman-remote,podman)
# renovate: datasource=docker depName=docker.io/library/python
PYTHON_IMAGE ?= docker.io/library/python:3.12-trixie@sha256:4d1caded1f729ae443eb803f26ffde7b61e696aeaef62f099abb6dd6b14257c7
# renovate: datasource=docker depName=docker.io/kcov/kcov
KCOV_IMAGE ?= docker.io/kcov/kcov:latest@sha256:481289ae32e55e5b733019515acd10948a4f76dfed381765577db909664fc603
SHELL_SCRIPTS := tools/fetch-originals.sh

# Builds $$out/src.tar: the files git would commit (tracked, plus new ones
# not ignored), minus any deleted in the working tree, each step checked,
# so the containers never measure a partial tree.
_sources := git ls-files -z --cached --others --exclude-standard --deduplicate \
		>"$$out/all" || exit 1; \
	xargs -0 sh -c 'for f do if [ -e "$$f" ] || [ -L "$$f" ]; then printf "%s\0" "$$f"; fi; done' sh \
		<"$$out/all" >"$$out/list" || exit 1; \
	tar --create --owner=0 --group=0 --numeric-owner --null --files-from="$$out/list" --file="$$out/src.tar" || exit 1
_unpack := set -e; mkdir /tmp/w; tar -x --no-same-owner -C /tmp/w; cd /tmp/w
_locked := --cap-drop=ALL --security-opt no-new-privileges

coverage:
	@set -u; out="$$(mktemp -d)"; trap 'rm -rf "$$out"' EXIT; \
	$(_sources); \
	mkdir "$$out/python" "$$out/shell"; py=0; sh=0; \
	$(PODMAN) run <"$$out/src.tar" --rm --interactive $(_locked) \
		-v "$$out/python:/out:rw,Z" "$(PYTHON_IMAGE)" sh -c '$(_unpack); \
			pip install --quiet --disable-pip-version-check --root-user-action=ignore \
				--require-hashes --only-binary=:all: -r tests/requirements.txt; \
			tools/fetch-originals.sh >/dev/null; \
			python3 -m pytest tests -q --cov-report=xml:/out/coverage.xml' || py=$$?; \
	$(PODMAN) run <"$$out/src.tar" --rm --interactive $(_locked) \
		--network=none --read-only --tmpfs /tmp \
		-v "$$out/shell:/out:rw,Z" "$(KCOV_IMAGE)" sh -c '$(_unpack); \
			kcov --include-path=$(addprefix /tmp/w/,$(SHELL_SCRIPTS)) /out/kcov \
				tests/fetch-originals.test.sh; \
			python3 tools/kcov_to_sonar.py /tmp/w /out/kcov/fetch-originals.test.sh.*/cobertura.xml \
				/out/shell.xml $(SHELL_SCRIPTS)' || sh=$$?; \
	mkdir -p "$(COVERAGE_DIR)" && rm -f "$(COVERAGE_DIR)/coverage.xml" "$(COVERAGE_DIR)/shell.xml" || exit 1; \
	for report in "$$out/python/coverage.xml" "$$out/shell/shell.xml"; do \
		if [ -f "$$report" ]; then cp "$$report" "$(COVERAGE_DIR)"/ || exit 1; fi; \
	done; \
	test "$$py" -eq 0 && test "$$sh" -eq 0

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
