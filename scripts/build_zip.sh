#!/usr/bin/env bash
# Builds dist/skip-the-comment.zip for claude.ai (Customize → Skills → + → Upload a skill). Zip root = skill folder.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$root/dist"
rm -f "$root/dist/skip-the-comment.zip"
cd "$root/plugins/skip-the-comment/skills"
zip -qr "$root/dist/skip-the-comment.zip" skip-the-comment -x '*/__pycache__/*' '*.pyc'
unzip -l "$root/dist/skip-the-comment.zip"
