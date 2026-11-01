#!/bin/sh
# Linux から Windows 向けに clippy をかける（#[cfg(windows)] の部分を確かめる）。CLAUDE.md §1。
#
# 中身の Rust の側は SQLite を exe に組み込む（libsqlite3-sys の bundled）。その C の組み立てには Windows SDK の
# ヘッダーが要り、Linux には無い。clippy は Rust の型を確かめるだけでつながない（リンクしない）ので、C の組み立ては
# 「出来上がりに空のファイルを置くだけ」の代役に任せる。本物の組み立ては Windows の CI（desktop.yml）が行う。
# 使い方: desktop で sh tools/clippy-windows.sh
set -e
fake=$(mktemp -d)
trap 'rm -rf "$fake"' EXIT
cat > "$fake/clang-cl" <<'SH'
#!/bin/sh
for a in "$@"; do case "$a" in /Fo*|-Fo*) : > "${a#???}";; --version) echo "clang version 18 (clippy の代役)";; esac; done
SH
cat > "$fake/llvm-lib" <<'SH'
#!/bin/sh
for a in "$@"; do case "$a" in /OUT:*|-out:*|/out:*|-OUT:*) : > "${a#*:}";; esac; done
SH
chmod +x "$fake/clang-cl" "$fake/llvm-lib"
CC_x86_64_pc_windows_msvc="$fake/clang-cl" AR_x86_64_pc_windows_msvc="$fake/llvm-lib" \
  cargo clippy --locked --target x86_64-pc-windows-msvc --all-targets -- -D warnings
