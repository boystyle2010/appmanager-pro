#!/usr/bin/env python3
"""
Tạo commit trên nhánh qua GitHub GraphQL API (createCommitOnBranch) để GitHub tự KÝ commit
(hiện nhãn "Verified"). Dùng token của workflow (biến GH_TOKEN), cần `gh` CLI (có sẵn trên runner).

  python scripts/signed_commit.py --branch main --message "chore(deps): ..." --files-from release/changed_files.txt
In ra mã commit mới (oid).
"""
import argparse
import base64
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MUTATION = """
mutation($input: CreateCommitOnBranchInput!) {
  createCommitOnBranch(input: $input) { commit { oid url } }
}
"""


def gh_api(args: list[str], stdin: str | None = None) -> str:
    r = subprocess.run(["gh", "api", *args], input=stdin, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"gh api lỗi: {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--branch", default="main")
    ap.add_argument("--message", required=True)
    ap.add_argument("--files-from", required=True)
    a = ap.parse_args()

    repo = os.environ["GITHUB_REPOSITORY"]
    head = gh_api([f"repos/{repo}/git/ref/heads/{a.branch}", "--jq", ".object.sha"]).strip()
    paths = [p.strip() for p in Path(a.files_from).read_text(encoding="utf-8").splitlines() if p.strip()]
    additions = [
        {"path": p, "contents": base64.b64encode((ROOT / p).read_bytes()).decode()}
        for p in paths if (ROOT / p).is_file()
    ]
    headline, _, body = a.message.partition("\n\n")
    inp = {
        "branch": {"repositoryNameWithOwner": repo, "branchName": a.branch},
        "message": {"headline": headline, **({"body": body} if body else {})},
        "expectedHeadOid": head,
        "fileChanges": {"additions": additions},
    }
    out = gh_api(["graphql", "--input", "-"], json.dumps({"query": MUTATION, "variables": {"input": inp}}))
    data = json.loads(out)
    if "errors" in data:
        sys.exit(f"GraphQL lỗi: {data['errors']}")
    print(data["data"]["createCommitOnBranch"]["commit"]["oid"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
