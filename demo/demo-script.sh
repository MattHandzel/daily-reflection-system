#!/usr/bin/env bash
# Demo script for asciinema recording
# Simulates the pipeline output (uses cached data so it's fast)

set -e

echo "$ daily-reflect 2026-04-08"
echo ""
sleep 1

cd /home/matth/Projects/daily-reflection-system
nix-shell shell.nix --run "python3 -m daily_reflect.main 2026-04-08 --no-inject" 2>&1

sleep 2

echo ""
echo "# Let's see the reflection output:"
echo "$ head -30 reflections/2026-04-08.md"
echo ""
sleep 1

head -30 /home/matth/Obsidian/Main/projects/daily-reflection-system/reflections/2026-04-08.md

sleep 2

echo ""
echo "# Category summary:"
echo "$ tail -20 reflections/2026-04-08.md"
echo ""
sleep 1

tail -20 /home/matth/Obsidian/Main/projects/daily-reflection-system/reflections/2026-04-08.md

sleep 3
