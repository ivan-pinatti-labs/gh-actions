# Contributing

Thanks for considering a contribution. This file is a generic starting
point shipped by the `github-template` template repository; adjust it once
the project created from this template has its own conventions.

## Before you start

- Search open issues and pull requests first, so effort is not duplicated.
- For a change of any size, open an issue describing what you want to do
  before writing code, so the approach can be discussed up front.

## Making a change

1. Fork the repository and create a branch off `main`.
2. Install pre-commit and the hooks this repo wires up:

   ```shell
   pip install pre-commit
   pre-commit install
   ```

   Or work in a devcontainer-airlock workbench, where the hooks run in an
   L2 container that already carries pre-commit and every tool they need;
   see [.devcontainer/README.md](.devcontainer/README.md).

3. Make your change, and run the checks locally before opening a pull
   request:

   ```shell
   pre-commit run --all-files
   ```

   In a workbench, `l2-pre-commit run --all-files` instead: the workbench
   has no `pre-commit` of its own, and this runs the hooks in L2.

   `make coverage` runs the Python tests under coverage.py and the shell
   tests under kcov, each in a podman container, and fails unless both reach
   100%: the Python by lines and branches, the shell by lines. It needs
   podman on `PATH`, and it also runs as a pre-push hook, so run
   `pre-commit install` again in an existing clone to pick up that stage. A
   new script ships with tests that reach every line of it.

4. Commit using [Conventional Commits](https://www.conventionalcommits.org/),
   for example `fix: correct a typo in the README`. No ticket prefix is
   required by default.
5. Open a pull request against `main` using the template in
   [.github/PULL_REQUEST_TEMPLATE.md](.github/PULL_REQUEST_TEMPLATE.md). Open
   it as a draft first if the checks take a while to run, and mark it ready
   once they are green.

## License

By contributing, you agree that your contributions will be licensed under
this repository's [Apache License 2.0](LICENSE.md). A project created from
this template that changes its license should update this line to match.

## Code of Conduct

Participation in this project is governed by
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Security issues

Do not open a public issue for a security vulnerability. See
[SECURITY.md](SECURITY.md) instead.

## Updating the test dependencies

`tests/requirements.in` carries the exact pins. `tests/requirements.txt` is a
lock compiled from it with every hash, which `pip install --require-hashes`
checks. Renovate bumps both. To change one by hand, edit the `.in` file and
regenerate the lock in a container, from `tests/`:

```bash
podman run --rm -v "$PWD:/w:rw,Z" -w /w ghcr.io/astral-sh/uv:python3.12-trixie-slim \
  uv pip compile --generate-hashes --python-version=3.12 --exclude-newer=P7D \
  --output-file=requirements.txt requirements.in
```

That is the command in the lock's own header, which Renovate replays.
`--exclude-newer=P7D` leaves out anything released in the last seven days,
dependencies of dependencies included.

### A security fix younger than seven days

The seven day window also holds back a security release, and Renovate
cannot make an exception: it replays the header's command as written, so its
pull request for a vulnerability alert fails to regenerate the lock and says
so. Update that one package by hand, in the same container and from the
lock's directory, letting it past the window and asking for its newest
release (`--upgrade-package`; without it, uv keeps the version already in the
lock, so a vulnerable dependency of a dependency would not move):

```bash
podman run --rm -v "$PWD:/w:rw,Z" -w /w ghcr.io/astral-sh/uv:python3.12-trixie-slim \
  uv pip compile --generate-hashes --python-version=3.12 --exclude-newer=P7D \
  --exclude-newer-package "<package>=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --upgrade-package "<package>" \
  --output-file=requirements.txt requirements.in
```

Then edit the lock's header back to the standard command above, by hand,
removing `--exclude-newer-package` (uv does not record `--upgrade-package`
there). Left in, the per package date is fixed, so it would hold that
package at today's releases for good. The rest of the lock does not change,
and the next Renovate update replays the standard command once the fix is
past the window.
