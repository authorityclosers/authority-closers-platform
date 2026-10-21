#!/bin/bash
# bench-push <tree-dir> <suffix>: push <tree-dir> as a commit to refs/heads/${PREFIX:-bench}/<suffix> of the public
# repo (fictional benchmark data and research workflows only; nothing else is in the tree). Prints the commit.
set -euo pipefail
tree_dir=$(cd "$1" && pwd); suffix=$2; prefix=${PREFIX:-bench}
BARE=/home/acdev/research/analysis-cost-20261020/gh.git
URL=https://github.com/authorityclosers/authority-closers-platform.git
[ -d "$BARE" ] || git init -q --bare "$BARE"
export GIT_DIR=$BARE GIT_WORK_TREE=$tree_dir GIT_INDEX_FILE=$BARE/index-$prefix-$suffix
git add -A .
tree=$(git write-tree)
ref="refs/heads/$prefix/$suffix"
parent=$(git rev-parse -q --verify "$ref" || true)
msg="bench: analysis-cost research, fictional benchmark data and research workflow ($prefix/$suffix)"
commit=$(GIT_AUTHOR_NAME="analysis-cost research" GIT_AUTHOR_EMAIL="workbench@authorityclosers.com" \
  GIT_COMMITTER_NAME="analysis-cost research" GIT_COMMITTER_EMAIL="workbench@authorityclosers.com" \
  git commit-tree "$tree" ${parent:+-p $parent} -m "$msg")
git update-ref "$ref" "$commit"
git -c credential.helper= -c 'credential.helper=!/home/acdev/.local/bin/gh auth git-credential' push -q "$URL" "+$commit:$ref" 2>&1 | grep -v '^remote:' || true
echo "$commit"
