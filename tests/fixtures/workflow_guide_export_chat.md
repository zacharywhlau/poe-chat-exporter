User:

Draft git and GitHub workflow for teamwork developing python projects, make sure the procedure are clear with explanations to the syntax and explain the benefits of the steps/workflow over other methods. Please also mention how common guidelines or house rules  such how to name a project. This should be a document and guideline for professional team, clear, comprehensive and self contained

---

Claude-Fable-5:

# Git & GitHub Team Workflow for Python Projects

**A professional team guideline — clear procedures, syntax explanations, and rationale**

---

## 1. Purpose and Scope

This document defines how our team uses Git and GitHub to collaborate on Python projects. It covers naming conventions, the day-to-day development cycle, pull requests and code review, merging strategy, releases, and Python-specific repository hygiene. Every command is explained so that new team members can follow the procedure without prior deep Git knowledge, and each rule includes the reasoning behind it so the workflow is understood rather than merely obeyed.

The workflow we use is a **feature-branch workflow with pull requests**, commonly known as *GitHub Flow*. In short: the `main` branch is always stable and deployable, all work happens on short-lived branches, and nothing reaches `main` without an approved pull request and passing automated checks.

---

## 2. Why This Workflow

Before describing the procedure, it is worth understanding what we are choosing *against*, because the benefits only make sense by comparison.

The simplest alternative is a **centralized workflow**, where everyone commits directly to `main`. This requires no process, but it means a single careless push can break the build for the whole team, there is no review step, and untangling who changed what becomes painful. It does not scale beyond one or two developers.

A heavier alternative is **Git Flow**, which adds long-lived `develop`, `release/*`, and `hotfix/*` branches alongside `main`. Git Flow is well suited to software with scheduled, versioned releases and multiple versions maintained in parallel (for example, a library supporting v1.x and v2.x simultaneously). For typical Python services and applications that deploy continuously, however, Git Flow introduces ceremony and long-lived branches that drift apart and produce large, risky merges.

A third alternative is **trunk-based development**, where developers push very small commits directly to `main` behind feature flags. This is powerful for mature teams with excellent automated test coverage, but it removes the pull-request review gate that most teams rely on for quality and knowledge sharing.

GitHub Flow sits in the practical middle. Feature branches isolate work in progress so `main` stays releasable at all times. Pull requests create a natural checkpoint for code review, automated testing, and discussion, which spreads knowledge across the team and catches defects before they land. Short-lived branches (days, not weeks) keep merges small and conflicts rare. Finally, the entire history of *why* a change was made is preserved in the pull request record, which is invaluable when debugging six months later.

For open-source projects with outside contributors, we use the **forking variant**: external contributors fork the repository and open pull requests from their fork, since they have no write access. Internally, the procedure below applies unchanged.

---

## 3. Naming Conventions (House Rules)

Consistent names make repositories searchable, automation predictable, and history readable. The following rules are mandatory.

**Repository names** are lowercase with hyphens (kebab-case), descriptive, and free of the organization name or the word "python": `customer-api`, `data-pipeline`, `billing-service`, not `AcmeCustomerAPI` or `python_stuff`. Hyphens are the GitHub convention and read well in URLs.

**Python package names** (the importable directory inside the repo) use lowercase with underscores (snake_case), per PEP 8: the repository `customer-api` contains the package `customer_api`. This split exists because hyphens are illegal in Python import statements, while underscores are awkward in URLs; PyPI treats the two as equivalent when resolving package names.

**Branch names** follow the pattern `type/ticket-id-short-description`, all lowercase with hyphens: `feature/PROJ-142-user-auth`, `fix/PROJ-201-null-response`, `chore/upgrade-ruff`, `docs/api-examples`. The type prefix lets anyone see the intent at a glance and allows automation (for example, labeling PRs by branch prefix). The ticket ID links the code to the issue tracker. Branches belong to one person and one task; they are never shared for parallel work.

**Commit messages** follow the *Conventional Commits* standard: a type, an optional scope in parentheses, a colon, and a short imperative summary under about 70 characters, e.g. `feat(auth): add password hashing with bcrypt` or `fix(api): return 404 for missing customer`. Valid types are `feat` (new functionality), `fix` (bug fix), `docs`, `test`, `refactor`, `perf`, `chore` (maintenance, tooling), and `ci`. Use the imperative mood ("add", not "added"), because a commit message completes the sentence "if applied, this commit will…". Longer explanations go in the commit body after a blank line. The benefit is twofold: history becomes scannable, and tools can generate changelogs and version bumps automatically from the types.

**Tags** mark releases and follow Semantic Versioning with a `v` prefix: `v1.4.0`. In `MAJOR.MINOR.PATCH`, increment MAJOR for breaking changes, MINOR for backward-compatible features, and PATCH for backward-compatible fixes. This tells consumers of your code exactly what an upgrade risks.

---

## 4. One-Time Setup

Each developer performs this once per machine and once per project.

Configure your identity globally so every commit is attributable:

```bash
git config --global user.name "Ada Lovelace"
git config --global user.email "ada@acme.com"
```

Here `git config` writes settings; `--global` stores them in your home directory so they apply to all repositories, rather than just the current one. Use your work email so commits link to your GitHub account.

Clone the repository:

```bash
git clone git@github.com:acme/customer-api.git
cd customer-api
```

`git clone` downloads the full repository, including all history, and automatically registers the source as a *remote* named `origin`. The `git@github.com:` form uses SSH authentication, which we prefer over HTTPS because it avoids repeated credential prompts once your SSH key is registered with GitHub.

Create an isolated Python environment and install the project with its development dependencies:

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

The virtual environment lives in `.venv/`, which is ignored by Git (see Section 9) — environments are machine-specific and must never be committed. The `-e` flag installs the package in *editable* mode so code changes take effect without reinstalling, and `[dev]` pulls in the optional development dependencies (test and lint tools) declared in `pyproject.toml`.

Finally, install the shared pre-commit hooks:

```bash
pre-commit install
```

This wires the checks defined in `.pre-commit-config.yaml` (formatting, linting) into Git so they run automatically on every `git commit`. The benefit is that style problems are fixed on the developer's machine in seconds instead of being discovered minutes later by CI or, worse, debated in code review. Review time is then spent on design and correctness, not on whitespace.

---

## 5. The Daily Development Cycle

This is the core procedure, followed for every task, no matter how small. Even a one-line fix goes through a branch and a pull request — consistency is what makes the process trustworthy.

**Start from an up-to-date `main`.** Before creating a branch, synchronize:

```bash
git switch main
git pull origin main
```

`git switch main` moves your working directory to the `main` branch (`switch` is the modern, purpose-built command; older tutorials use `git checkout`, which does the same but is overloaded with other functions). `git pull origin main` contacts the remote named `origin`, downloads new commits on `main`, and merges them into your local copy. Branching from stale code is the most common cause of avoidable merge conflicts, so this step is not optional.

**Create your feature branch:**

```bash
git switch -c feature/PROJ-142-user-auth
```

The `-c` flag (create) makes a new branch starting at your current commit and switches to it in one step. Your work is now fully isolated: nothing you do here can affect `main` or your colleagues until you deliberately open a pull request.

**Work in small, focused commits.** As you complete each coherent piece of the task, stage and commit it:

```bash
git status
git add src/customer_api/auth/hashing.py tests/test_hashing.py
git commit -m "feat(auth): add password hashing with bcrypt"
```

`git status` shows which files are modified, staged, or untracked — run it habitually before staging. `git add <paths>` moves specific files into the *staging area*, the set of changes that the next commit will contain. Prefer naming files explicitly over the catch-all `git add .`, which too easily sweeps in debug prints, scratch files, or unrelated edits. For fine-grained control, `git add -p` (patch mode) walks you through each change hunk and lets you accept or skip it individually; this doubles as a self-review and is the easiest way to keep commits focused on one thing. `git commit -m "..."` then records the staged snapshot with a message. Small commits matter because they make review comprehensible, `git bisect` (binary-searching history for the commit that introduced a bug) effective, and partial reverts possible.

**Push your branch and keep pushing regularly:**

```bash
git push -u origin feature/PROJ-142-user-auth
```

`git push` uploads your commits; `origin` is the remote, followed by the branch name. The `-u` flag (`--set-upstream`) records the link between your local branch and the remote branch, so from now on a bare `git push` and `git pull` know where to go. Pushing at least daily means your work is backed up and visible to teammates — a branch that exists only on your laptop is a risk.

**Keep your branch current with `main`.** If your task takes more than a day, or CI reports your branch is behind, replay your work on top of the latest `main`:

```bash
git fetch origin
git rebase origin/main
```

`git fetch` downloads the remote's new commits *without* touching your files — it just updates your local knowledge of the remote (unlike `pull`, which fetches and merges in one step). `git rebase origin/main` then lifts your branch's commits and reapplies them, one by one, on top of the newest `main`. If a conflict occurs, Git pauses; open the conflicted files, resolve the marked sections, then run `git add <file>` and `git rebase --continue` (or `git rebase --abort` to return to the state before the rebase and rethink).

We rebase feature branches rather than merging `main` into them because rebasing produces a clean, linear history — your PR shows only your changes, not noisy "merge main into feature" commits, which makes review and later archaeology far easier. After a rebase your branch's history has been rewritten, so a plain push is rejected; push with:

```bash
git push --force-with-lease
```

`--force-with-lease` overwrites the remote branch **only if** it still matches what you last fetched, refusing if someone else has pushed to it meanwhile. It gives you the necessary power of `--force` with a safety net; plain `--force` is banned in this team. This leads to the single most important Git rule, the **golden rule of rebasing**: *never rebase a branch that others are working on.* Your own feature branch is yours to rewrite; `main` is rewritten by no one, ever.

---

## 6. Pull Requests and Code Review

When the task is complete — code written, tests added, all tests passing locally via `pytest` — open a pull request from your branch into `main`, either through the GitHub web interface or from the terminal with the GitHub CLI:

```bash
gh pr create --title "feat(auth): add user authentication" --body "Closes PROJ-142"
```

`gh pr create` opens the PR without leaving the terminal; `--title` and `--body` set its text. Writing `Closes PROJ-142` (or `Closes #142` for GitHub Issues) in the body links and auto-closes the ticket when the PR merges. If you want early feedback on unfinished work, open a **draft PR** (`gh pr create --draft`), which signals "please look, but don't merge."

Every PR description must state *what* changed, *why*, and *how it was tested*. The reviewer of your PR is anyone on the team who did not write the code; the house rule is **at least one approval, two for changes touching security, data migrations, or public APIs**.

Review etiquette: keep PRs under roughly 400 changed lines — beyond that, reviewer attention measurably degrades and defects slip through, which is the empirical reason we insist on small tasks and small branches. Reviewers respond within one business day. Comments critique the code, never the author, and distinguish blocking concerns from suggestions (prefix optional ideas with "nit:"). The author responds to every comment, pushes fix-up commits to the same branch (the PR updates automatically), and re-requests review.

The benefit of this gate over unreviewed pushes is not just defect-catching: review is how the team develops shared ownership of the codebase, how conventions actually propagate, and how the PR archive becomes documentation of every decision.

---

## 7. Merging Strategy

Once the PR is approved and CI is green, the author merges it using **"Squash and merge"** in GitHub. Squashing compresses all the branch's commits — including the inevitable "fix typo" and "address review comments" — into a single, well-titled commit on `main` (edit the squash message to follow Conventional Commits).

Why squash rather than the alternatives? A plain **merge commit** preserves every intermediate commit plus a merge node, which is maximally faithful but makes `main`'s history a tangle that is hard to read and to bisect. **Rebase-and-merge** keeps individual commits without a merge node, which is fine when every commit in the branch is polished, but that discipline is rare in practice. Squash gives us a `main` where **one commit equals one reviewed feature or fix**: the history reads like a changelog, and reverting a bad feature is a single clean `git revert <commit>`.

After merging, clean up:

```bash
git switch main
git pull origin main
git branch -d feature/PROJ-142-user-auth
```

`git branch -d` deletes the local branch, and its lowercase `-d` refuses to delete unmerged work (the uppercase `-D` forces deletion and should make you pause). Enable GitHub's repository setting "Automatically delete head branches" so the remote branch is removed on merge. Dead branches are noise; the PR preserves everything.

`main` itself is guarded by **branch protection rules**, configured in the repository settings by the maintainer: pull requests are required (direct pushes rejected), at least one approval is required, the CI status checks must pass, the branch must be up to date with `main` before merging, and force pushes and deletions are disabled for everyone, including administrators. This converts our house rules from good intentions into mechanically enforced guarantees. A `CODEOWNERS` file can additionally auto-request review from the owning team when specific paths change.

---

## 8. Releases and Versioning

Releases are cut from `main` by tagging:

```bash
git tag -a v1.4.0 -m "Release 1.4.0: user authentication, rate limiting"
git push origin v1.4.0
```

`git tag -a` creates an *annotated* tag — a full Git object carrying the tagger, date, and message — as opposed to a lightweight tag, which is a bare pointer; annotated tags are the standard for releases precisely because they carry provenance. Tags are not pushed by default, hence the explicit `git push origin v1.4.0`. From the tag, create a GitHub Release with generated notes (`gh release create v1.4.0 --generate-notes`), which our CI can use to trigger publishing (for a library, building and uploading to PyPI; for a service, deploying).

Because commits follow Conventional Commits, the version bump is mechanical: any `feat` since the last tag means at least a minor bump, any breaking change (marked `feat!:` or with a `BREAKING CHANGE:` footer) a major bump, otherwise patch. Teams that want this fully automated can adopt `python-semantic-release`, which reads the commit history and performs the tag, changelog, and publish steps itself — a benefit unavailable to teams with freeform commit messages.

If a critical bug ships, there is no special hotfix machinery: branch `fix/...` from `main`, PR, review (expedited), squash-merge, tag a patch release. The uniformity is the point — one process to remember, even under pressure.

---

## 9. Python-Specific Repository Hygiene

Every repository starts from the team template and contains `pyproject.toml` (single source of truth for metadata, dependencies, and tool configuration — preferred over legacy `setup.py`/`requirements.txt` splits), a `src/` layout (`src/customer_api/`), `tests/`, `README.md`, and the two files below.

The `.gitignore` keeps generated and local files out of version control:

```gitignore
# Environments & secrets
.venv/
.env

# Bytecode & caches
__pycache__/
*.py[cod]
.pytest_cache/
.mypy_cache/
.ruff_cache/

# Build artifacts
dist/
build/
*.egg-info/

# Coverage & IDE
.coverage
htmlcov/
.idea/
.vscode/
```

Two of these lines are security-critical: `.env` holds local secrets (API keys, database URLs) and **must never be committed** — real secrets live in GitHub Actions Secrets or a vault, and a committed secret is considered leaked and must be rotated immediately, since removing it from history is difficult and the history is public to anyone with repo access. Committing `.venv/` or `__pycache__/` bloats the repository with machine-specific junk and causes spurious diffs.

`.pre-commit-config.yaml` defines the automatic local checks:

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.6.9
    hooks:
      - id: ruff          # lint (includes import sorting)
        args: [--fix]
      - id: ruff-format   # format (Black-compatible)
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-added-large-files
      - id: detect-private-key
```

Formatting is thus a solved, automated problem: the formatter's output is the style guide, and no PR ever contains a style debate. Dependencies are declared with sensible constraints in `pyproject.toml` and pinned exactly in a committed lock file (via `uv` or `poetry`), so that every developer and every CI run installs *identical* versions — eliminating "works on my machine" caused by drifting transitive dependencies.

Continuous integration runs on every PR via GitHub Actions in `.github/workflows/ci.yml`:

```yaml
name: CI
on:
  pull_request:
  push:
    branches: [main]
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: pip install -e ".[dev]"
      - run: ruff check . && ruff format --check .
      - run: pytest --cov=customer_api
```

The `on:` block triggers the workflow for every pull request and every push to `main`; the `matrix` runs the suite across the Python versions we support, catching version-specific breakage before users do. These are the status checks that branch protection requires, which is what makes "main is always green" an enforced property rather than a hope.

---

## 10. House Rules — Summary

For quick reference, the non-negotiables in one place: `main` is always deployable and is never pushed to or force-pushed directly. All work happens on short-lived branches named `type/ticket-short-description`, created from a freshly pulled `main`, and merged only through a reviewed, CI-green pull request using squash-and-merge. Commits follow Conventional Commits in the imperative mood. Feature branches are updated by rebasing onto `origin/main` and pushed with `--force-with-lease` only; shared branches are never rebased. PRs stay under ~400 changed lines, receive at least one approval (two for sensitive areas), and reviewers respond within a business day. Releases are annotated tags `vMAJOR.MINOR.PATCH` cut from `main`. Secrets, virtual environments, and generated files never enter version control, and pre-commit hooks are installed by everyone.

## 11. Command Quick Reference

```bash
# Start a task
git switch main && git pull origin main       # sync main
git switch -c feature/PROJ-142-user-auth      # create branch (-c = create)

# Work
git status                                    # inspect state
git add -p                                    # stage changes interactively
git commit -m "feat(auth): add bcrypt hashing"
git push -u origin feature/PROJ-142-user-auth # -u links branch to remote

# Stay current
git fetch origin && git rebase origin/main    # replay work on latest main
git push --force-with-lease                   # safe push after rebase

# Deliver
gh pr create --title "..." --body "Closes PROJ-142"
# after approval: Squash and merge in GitHub, then:
git switch main && git pull origin main
git branch -d feature/PROJ-142-user-auth      # -d = delete only if merged

# Release
git tag -a v1.4.0 -m "Release 1.4.0" && git push origin v1.4.0
```

---

Adopting this document means every repository looks familiar, every change is reviewed and tested before it lands, history explains itself, and releases are routine. New team members should read it once, then keep Section 11 to hand; questions and proposed amendments go through — naturally — a pull request against this document.

---

User:

recap

---

Claude-Fable-5:

# Recap: Git & GitHub Team Workflow for Python Projects

**The workflow:** GitHub Flow — `main` is always stable and deployable; all work happens on short-lived feature branches merged via reviewed pull requests. Chosen over direct-to-main (no safety/review), Git Flow (too heavy for continuous delivery), and trunk-based development (needs very mature test coverage).

**Naming rules:**
- Repos: kebab-case (`customer-api`); Python packages inside: snake_case (`customer_api`)
- Branches: `type/ticket-description` (e.g., `feature/PROJ-142-user-auth`)
- Commits: Conventional Commits, imperative mood (`feat(auth): add bcrypt hashing`)
- Tags: SemVer with `v` prefix (`v1.4.0`)

**The daily cycle:**
1. Sync: `git switch main && git pull origin main`
2. Branch: `git switch -c feature/...`
3. Commit small and often: `git add -p`, then `git commit -m "..."`
4. Push daily: `git push -u origin <branch>`
5. Stay current by rebasing: `git fetch origin && git rebase origin/main`, then `git push --force-with-lease` (never plain `--force`; never rebase shared branches)

**Pull requests & merging:**
- Every change goes through a PR — state what, why, and how tested; link the ticket with `Closes ...`
- Keep PRs under ~400 lines; at least 1 approval (2 for security/migrations/APIs); review within one business day
- Merge via **squash-and-merge** so `main` reads as one commit per reviewed change; delete branches after merging
- Branch protection enforces all of this mechanically (required reviews, green CI, no direct pushes)

**Releases:** Annotated tags from `main` (`git tag -a v1.4.0 -m "..."` + push the tag); version bumps follow from commit types; hotfixes use the same normal process.

**Python hygiene:**
- `pyproject.toml` + `src/` layout; lock files for identical installs everywhere
- `.gitignore` excludes `.venv/`, `__pycache__/`, build artifacts, and especially `.env` — a committed secret counts as leaked and must be rotated
- Pre-commit hooks (ruff lint/format) kill style debates locally; GitHub Actions CI runs lint + pytest across supported Python versions on every PR

**Core principle:** One uniform process for everything — small branches, reviewed PRs, enforced checks — so `main` is always green, history explains itself, and even hotfixes under pressure follow the same familiar steps.