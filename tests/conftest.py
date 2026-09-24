# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ivan Pinatti
"""Make coverage of the spawned interpreters deterministic.

This suite grades diffs by running `src/pin_only.py` as a real command, which
is the interface consumers use and the reason the tests are worth having. That
work happens in a child interpreter, so in-process coverage cannot see it, and
whether it is counted at all depends on the installed pytest-cov: Ubuntu's
package enables subprocess measurement, the pip install in CI did not, and the
identical suite reported 94 percent here and 38 percent there. A number that
moves with the environment is worse than no number.

Setting COVERAGE_PROCESS_START and putting the sitecustomize beside it on
PYTHONPATH is coverage's own documented mechanism, and it does not care which
version of pytest-cov is installed. Both variables are set for the whole
session, and every subprocess inherits them.
"""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_RC = ROOT / ".coveragerc"
_SITE = ROOT / "tools" / "coverage_subprocess"


def pytest_configure(config):
    if not _RC.is_file():
        return
    os.environ["COVERAGE_PROCESS_START"] = str(_RC)
    existing = os.environ.get("PYTHONPATH", "")
    parts = [str(_SITE)] + ([existing] if existing else [])
    os.environ["PYTHONPATH"] = os.pathsep.join(parts)
