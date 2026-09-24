# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ivan Pinatti
"""Start coverage in a subprocess the suite spawns.

Most of this suite grades diffs by running `src/pin_only.py` as a real
command, which is the interface consumers actually use. In-process coverage
sees none of that, so the measured figure depends on whether the installed
pytest-cov happens to enable subprocess measurement: Ubuntu's package does,
a pip install in CI did not, and the same suite reported 94 percent locally
and 38 percent in CI.

`coverage.process_startup()` is the documented, version independent way to
make it deterministic. It is a no-op unless COVERAGE_PROCESS_START is set,
which conftest.py sets only while the suite runs.
"""

try:
    import coverage
except ImportError:  # pragma: no cover - coverage absent means nothing to start
    pass
else:  # pragma: no cover - exercised only inside the spawned interpreter
    coverage.process_startup()
