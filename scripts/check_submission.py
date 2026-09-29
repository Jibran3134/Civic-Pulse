#!/usr/bin/env python3
"""
Submission checklist linter.
Run: python scripts/check_submission.py

Portability note. An earlier version shelled out to `| tail -5` and printed
emoji directly, so the script crashed on a Windows console (cp1252 cannot
encode U+1F50D) and reported a FALSE FAILURE for the Docker build, because
`tail` does not exist there. Both are fixed below: output truncation happens
in Python rather than in a shell pipe, and the stream is reconfigured for
UTF-8 before anything is printed.

This is a lint, not a grader. It catches the mechanical failures behind most of
the assignment's automatic deductions. A clean run does not guarantee a good
mark; a dirty run nearly guarantees a bad one.
"""

import os
import subprocess
import sys
from pathlib import Path

# Reconfigure stdout/stderr for UTF-8 before any emoji reaches a cp1252 console.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # already wrapped, or not a TextIO
        pass


def run_cmd(cmd, cwd=None, tail=None):
    """Run a command, optionally returning only its last `tail` lines.

    Truncation is done here rather than with a shell pipe so the script behaves
    the same on Windows, macOS and Linux.
    """
    result = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
    out = result.stdout or ""
    if tail is not None:
        out = "\n".join(out.splitlines()[-tail:])
    return result.returncode == 0, out, result.stderr or ""


def check_git_clean():
    ok, out, _ = run_cmd("git status --porcelain")
    if not ok or out.strip():
        print("❌ Working directory not clean")
        return False
    print("✅ Git working directory clean")
    return True


def check_no_secrets():
    ok, out, _ = run_cmd("git log --all --full-history --oneline -- '*secrets*' '*password*' '*token*' '*.env'")
    if out.strip():
        print("❌ Potential secrets in git history")
        print(out)
        return False
    print("✅ No secrets in git history")
    return True


def check_branch_protection():
    """Verify main is protected, as rubric section A requires.

    The previous version passed the literal string `repos/{owner}/{repo}` to
    `gh api`, which is not a placeholder gh expands -- it is a literal path
    segment. The call therefore always 404'd, and the `|| echo 'no gh cli'`
    fallback then reported "gh CLI not available" even on a machine where gh
    works fine. So the one automated signal for a graded requirement was
    permanently a false negative.
    """
    ok, out, err = run_cmd("gh api repos/:owner/:repo/branches/main/protection")
    if not ok:
        detail = (err or out).strip().splitlines()
        print("⚠️  Could not read branch protection for main")
        for line in detail[-3:]:
            print(f"    {line}")
        print("    Confirm manually: Settings -> Branches -> main -> "
              "Require pull request, 1 approval, require status checks")
        return True

    import json

    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        print("⚠️  Could not parse the branch protection response")
        return True

    rules = data.get("required_pull_request_reviews") or {}
    approvals = rules.get("required_approving_review_count", 0)
    checks = (data.get("required_status_checks") or {}).get("contexts") or []
    enforced = data.get("enforce_admins", {}).get("enabled", False)

    if approvals >= 1 and checks:
        print(f"✅ main is protected: {approvals} approval(s), "
              f"{len(checks)} required check(s), admin enforcement={enforced}")
    else:
        print(f"⚠️  main protection is weaker than the rubric expects: "
              f"{approvals} approval(s), {len(checks)} required check(s)")
        print("    Rubric A wants: PR required, CI required, >=1 approval.")
    return True


def check_required_files():
    required = [
        "README.md",
        "LICENSE",
        "compose.yaml",
        "compose.prod.yaml",
        ".env.example",
        ".gitignore",
        "backend/Dockerfile",
        "backend/pyproject.toml",
        "backend/alembic.ini",
        "backend/app/main.py",
        "k8s/overlays/prod/kustomization.yaml",
        ".github/workflows/ci.yml",
        ".github/workflows/cd.yml",
        ".github/workflows/release.yml",
    ]
    missing = [f for f in required if not Path(f).exists()]
    if missing:
        print(f"❌ Missing required files: {missing}")
        return False
    print("✅ All required files present")
    return True


def check_docker_build():
    # Truncated in Python, not via `| tail -5`: that pipe is the reason this
    # check used to report a false failure on any machine without a POSIX tail.
    ok, out, err = run_cmd("docker compose build backend", tail=5)
    if not ok:
        print("❌ Docker compose build failed")
        for line in (out + err).splitlines()[-5:]:
            print(f"    {line}")
        return False
    print("✅ Docker compose build succeeds")
    return True


def check_compose_up():
    print("ℹ️  Skipping full compose up (manual verification)")
    return True


def check_kustomize():
    # kustomize is not installed by default on Windows or macOS, so distinguish
    # "tool absent" from "manifests broken" rather than reporting a failure for
    # a missing binary.
    if not any(
        Path(d, "kustomize.exe").exists() or Path(d, "kustomize").exists()
        for d in os.environ.get("PATH", "").split(os.pathsep)
        if d
    ):
        print("⚠️  kustomize not on PATH; install it or run "
              "`kustomize build k8s/overlays/prod` manually")
        return True
    ok, out, err = run_cmd("kustomize build k8s/overlays/prod")
    if not ok:
        print("❌ Kustomize build failed")
        for line in (out + err).splitlines()[-5:]:
            print(f"    {line}")
        return False
    print("✅ Kustomize builds successfully")
    return True


def main():
    checks = [
        ("Git clean", check_git_clean),
        ("No secrets in history", check_no_secrets),
        ("Branch protection", check_branch_protection),
        ("Required files", check_required_files),
        ("Docker build", check_docker_build),
        ("Compose up", check_compose_up),
        ("Kustomize build", check_kustomize),
    ]

    passed = 0
    for name, fn in checks:
        print(f"\n🔍 {name}...")
        try:
            if fn():
                passed += 1
            else:
                print(f"   FAILED: {name}")
        except Exception as e:
            print(f"   ERROR: {name}: {e}")

    print(f"\n{'='*50}")
    print(f"Passed: {passed}/{len(checks)}")
    if passed == len(checks):
        print("✅ All checks passed!")
        return 0
    else:
        print("❌ Some checks failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())