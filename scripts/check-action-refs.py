"""Verify every `uses:` reference in the workflows resolves to a real ref.

A non-existent action ref fails the job at "Set up job", before a single line of
the pipeline runs, and the error names the action rather than the thing you
changed. Two real examples from this repo:

  * `aquasecurity/trivy-action@0.28.0` -- the tag list is v-prefixed.
  * `aquasecurity/trivy-action@v0.28.0` -- resolves, but that release calls
    `aquasecurity/setup-trivy@v0.2.1`, and setup-trivy only ever published
    v0.2.6, v0.3.0 and v0.3.1. So the pin looked fine and was still broken.
    v0.32.0+ pin setup-trivy by commit SHA instead.

The second case is why this checks transitive pins too, and why the trivy
version is chosen by reading each release's action.yaml rather than by picking
the newest tag.
"""

import json
import re
import sys
import urllib.error
import urllib.request

WORKFLOWS = [
    ".github/workflows/ci.yml",
    ".github/workflows/cd.yml",
    ".github/workflows/release.yml",
]

UA = {"User-Agent": "civicpulse-ci-audit"}


def api(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def raw(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", "replace")


def ref_exists(repo, ref):
    if re.fullmatch(r"[0-9a-f]{40}", ref):
        try:
            api(f"https://api.github.com/repos/{repo}/commits/{ref}")
            return True, "commit sha"
        except urllib.error.HTTPError:
            return False, "commit sha not found"
    for path in (f"git/ref/tags/{ref}", f"git/ref/heads/{ref}"):
        try:
            api(f"https://api.github.com/repos/{repo}/{path}")
            return True, "tag/branch"
        except urllib.error.HTTPError:
            continue
    return False, "no such tag, branch or sha"


def action_yaml(repo, ref):
    for name in ("action.yaml", "action.yml"):
        try:
            return raw(f"https://raw.githubusercontent.com/{repo}/{ref}/{name}")
        except urllib.error.HTTPError:
            continue
    return None


problems = []
checked = set()

for wf in WORKFLOWS:
    try:
        text = open(wf, encoding="utf-8").read()
    except FileNotFoundError:
        print(f"MISSING {wf}")
        problems.append(f"{wf} does not exist")
        continue

    refs = re.findall(r"uses:\s*([A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-/]+)@(\S+)", text)
    print(f"=== {wf}: {len(refs)} action reference(s) ===")
    for repo, ref in sorted(set(refs)):
        if (repo, ref) in checked:
            continue
        checked.add((repo, ref))
        ok, how = ref_exists(repo, ref)
        status = "OK " if ok else "BROKEN"
        print(f"  {status} {repo}@{ref}  ({how})")
        if not ok:
            problems.append(f"{repo}@{ref} does not resolve ({how})")
            continue

        # Transitive pins: composite actions call other actions with their own
        # `uses:`, and a broken pin there fails just as hard.
        body = action_yaml(repo, ref)
        if not body:
            print(f"       (no action.yaml, skipping transitive check)")
            continue
        for sub_repo, sub_ref in re.findall(
            r"uses:\s*([A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-/]+)@(\S+)", body
        ):
            if sub_repo.startswith("./"):
                continue
            sub_ok, sub_how = ref_exists(sub_repo, sub_ref)
            sub_status = "OK " if sub_ok else "BROKEN"
            print(f"       -> {sub_status} {sub_repo}@{sub_ref}  ({sub_how})")
            if not sub_ok:
                problems.append(
                    f"{repo}@{ref} transitively pins {sub_repo}@{sub_ref} "
                    f"which does not resolve ({sub_how}) -- pick a different "
                    f"version of {repo}"
                )

print()
if problems:
    print("PROBLEMS:")
    for p in problems:
        print(f"  - {p}")
    sys.exit(1)
print("All action references, including transitive pins, resolve.")
