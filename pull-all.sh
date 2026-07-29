#!/usr/bin/env bash
# 로컬에 있는 5개 브랜치(main, develop, feature/voice, feature/vital,
# feature/dashboard)를 한 번에 최신 상태로 맞춘다.
#
# 현재 체크아웃된 브랜치만 실제로 작업 디렉터리를 건드리는 `git pull`을 쓰고,
# 나머지는 체크아웃하지 않고 브랜치 포인터만 fast-forward한다. 그래서 다른
# 브랜치에 커밋 안 한 변경사항이 있어도 "덮어써질 수 있다"며 막히지 않는다
# (그 경우는 현재 브랜치에서만 발생 가능하고, 그건 원래 git pull이 알아서
# 알려준다).
#
# 사용법: ./pull-all.sh

set -euo pipefail

BRANCHES=(main develop feature/voice feature/vital feature/dashboard)
CURRENT=$(git branch --show-current)

echo "=== fetch ==="
git fetch --all --prune

for b in "${BRANCHES[@]}"; do
  if [ "$b" = "$CURRENT" ]; then
    echo ""
    echo "=== $b (현재 브랜치) ==="
    git pull origin "$b"
  else
    echo ""
    echo "=== $b ==="
    if git fetch origin "$b:$b" 2>&1; then
      echo "  -> 최신 상태로 업데이트됨"
    else
      echo "  -> fast-forward 불가 (로컬에 origin과 다른 커밋이 있음)."
      echo "     수동으로 확인하세요: git checkout $b && git pull"
    fi
  fi
done

echo ""
echo "=== 최종 동기화 상태 (behind ahead) ==="
for b in "${BRANCHES[@]}"; do
  status=$(git rev-list --left-right --count "origin/$b...$b" 2>/dev/null || echo "?")
  echo "$b: $status"
done
