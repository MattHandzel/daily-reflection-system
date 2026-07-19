# Mistakes log (newest first)

## 2026-07-18 — `pkill -f run_bench.py` self-killed the wrapping shell (MAT-1461)
**What:** To stop the background benchmark I ran `pkill -f run_bench.py`. The `-f` pattern also matched the zsh command that *contained* the string `run_bench.py`, so pkill signalled its own wrapping shell and the whole command aborted (exit 144) before it swapped the manifest — leaving the run alive and no backup made.
**Fix:** Never use a `pkill -f` pattern broad enough to match the invoking shell (global CLAUDE.md says exactly this). Stop background jobs by numeric PID (`pgrep` → `kill <pid>`), or scope the pattern to a fragment the wrapper can't contain. Verify death with `test -d /proc/<pid>`.
