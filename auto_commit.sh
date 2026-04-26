#!/bin/bash

WATCH_DIR="/Users/ryon/dev/sandbox/scripts/tbt"

echo "監視開始: $WATCH_DIR"

fswatch -o "$WATCH_DIR" --exclude="\.git" --exclude="output" | while read; do
  cd "$WATCH_DIR"
  if ! git diff --quiet || git ls-files --others --exclude-standard | grep -q .; then
    git add .
    git commit -m "Auto commit: $(date '+%Y-%m-%d %H:%M:%S')"
    git push origin main
    echo "Push完了: $(date '+%Y-%m-%d %H:%M:%S')"
  fi
done
