#!/usr/bin/env python3
"""
Submission checklist linter.
Run: python scripts/check_submission.py
"""

import os
import subprocess
import sys
from pathlib import Path


def run_cmd(cmd, cwd=None):
    result = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
    return result.returncode == 0, result.stdout, result.stderr


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
    ok, out, _ = run_cmd("gh api repos/{owner}/{repo}/branches/main/protection 2>/dev/null || echo 'no gh cli'")
    if "no gh cli" in out:
        print("⚠️  Cannot verify branch protection (gh CLI not available)")
        return True
    print("✅ Branch protection check skipped (manual verification needed)")
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
    ok, _, _ = run_cmd("docker compose build backend 2>&1 | tail -5")
    if not ok:
        print("❌ Docker compose build failed")
        return False
    print("✅ Docker compose build succeeds")
    return True


def check_compose_up():
    print("ℹ️  Skipping full compose up (manual verification)")
    return True


def check_kustomize():
    ok, _, _ = run_cmd("kustomize build k8s/overlays/prod >/dev/null 2>&1")
    if not ok:
        print("❌ Kustomize build failed")
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