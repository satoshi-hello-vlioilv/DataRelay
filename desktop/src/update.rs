//! exe を手元に置いた形（locate::Place::Local）の自己更新。
//!
//! 手元の exe は、共有のアプリのフォルダーが新しい版に置き換わっても古いまま残る。起動のたびに
//! 共有の版（lib/navi_version.py の APP_VERSION）と自分の版を比べ、食い違っていれば共有の DataRelay.exe で
//! 自分を入れ替えて起こし直す。新しいほうへ進めるだけでなく、共有を前の版へ戻したときも共有に合わせる。
//! 入れ替えは窓を作る前に行う（1つだけ起動の仕組みにも触れない）。Windows では動いている exe を消せないが、
//! 名前は変えられるので、自分を DataRelay.old.exe へよけてから新しいものを置く。よけたものは次の起動で消す。

use std::path::{Path, PathBuf};

/// 共有のアプリのフォルダーの版。読めなければ None。
pub fn program_version(program: &Path) -> Option<String> {
    let text = std::fs::read_to_string(program.join("lib").join("navi_version.py")).ok()?;
    let rest = &text[text.find("APP_VERSION=")? + "APP_VERSION=".len()..];
    let quote = rest.chars().next().filter(|c| *c == '\'' || *c == '"')?;
    let body = &rest[1..];
    Some(body[..body.find(quote)?].to_string()).filter(|v| !v.is_empty())
}

#[derive(Debug, PartialEq)]
pub enum Decision {
    /// 同じ版（または共有の版が読めない）。そのまま動く
    Keep,
    /// 食い違う。共有の exe で入れ替える
    Update,
    /// 食い違うが、共有に exe が無い（中身だけ置き換えた）。そのまま動き、記録に残す
    NoSource,
}

pub fn decide(own: &str, shared: Option<&str>, source_exists: bool) -> Decision {
    match shared {
        Some(v) if v != own => {
            if source_exists {
                Decision::Update
            } else {
                Decision::NoSource
            }
        }
        _ => Decision::Keep,
    }
}

/// よけた古い exe の置き場（DataRelay.exe → DataRelay.old.exe）。
pub fn old_path(exe: &Path) -> PathBuf {
    let stem = exe.file_stem().map(|s| s.to_string_lossy().into_owned()).unwrap_or_else(|| "DataRelay".into());
    let ext = exe.extension().map(|e| format!(".{}", e.to_string_lossy())).unwrap_or_default();
    exe.with_file_name(format!("{stem}.old{ext}"))
}

/// 自分（exe）を source で入れ替える。写せなかったら元へ戻す（手元に exe が無い、にはしない）。
pub fn swap(exe: &Path, source: &Path) -> Result<(), String> {
    let old = old_path(exe);
    let _ = std::fs::remove_file(&old);
    std::fs::rename(exe, &old).map_err(|e| format!("いまの exe をよけられません（{}）: {e}", old.display()))?;
    if let Err(e) = std::fs::copy(source, exe) {
        let _ = std::fs::remove_file(exe);
        let _ = std::fs::rename(&old, exe);
        return Err(format!("共有の exe を写せません（{} → {}）: {e}", source.display(), exe.display()));
    }
    Ok(())
}

/// 前回よけた古い exe を消す（まだ動いていて消せなければ、次の機会に）。
pub fn cleanup(exe: &Path) {
    let _ = std::fs::remove_file(old_path(exe));
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tmp(name: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!("dr-update-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&d);
        std::fs::create_dir_all(d.join("lib")).unwrap();
        d
    }

    #[test]
    fn reads_the_shared_version() {
        let d = tmp("ver");
        std::fs::write(d.join("lib").join("navi_version.py"), "\"\"\"版\"\"\"\nAPP_VERSION='1.97.0'; APP_VERSION_TITLE='x'\n").unwrap();
        assert_eq!(program_version(&d).as_deref(), Some("1.97.0"));
        std::fs::write(d.join("lib").join("navi_version.py"), "APP_VERSION = 1\n").unwrap();
        assert_eq!(program_version(&d), None, "読めない形なら None（入れ替えない）");
        assert_eq!(program_version(&d.join("none")), None);
        std::fs::remove_dir_all(&d).ok();
    }

    #[test]
    fn follows_the_shared_version_either_way() {
        assert_eq!(decide("1.96.0", Some("1.96.0"), true), Decision::Keep);
        assert_eq!(decide("1.96.0", Some("1.97.0"), true), Decision::Update, "共有が新しい");
        assert_eq!(decide("1.97.0", Some("1.96.0"), true), Decision::Update, "共有を前の版へ戻した");
        assert_eq!(decide("1.96.0", Some("1.97.0"), false), Decision::NoSource);
        assert_eq!(decide("1.96.0", None, true), Decision::Keep, "共有の版が読めないときは触らない");
    }

    #[test]
    fn swaps_and_restores_on_failure() {
        let d = tmp("swap");
        let (exe, src) = (d.join("DataRelay.exe"), d.join("new.exe"));
        std::fs::write(&exe, "古い").unwrap();
        std::fs::write(&src, "新しい").unwrap();
        swap(&exe, &src).unwrap();
        assert_eq!(std::fs::read_to_string(&exe).unwrap(), "新しい");
        assert_eq!(std::fs::read_to_string(old_path(&exe)).unwrap(), "古い");
        assert_eq!(old_path(&exe), d.join("DataRelay.old.exe"));
        cleanup(&exe);
        assert!(!old_path(&exe).exists());
        // 写す元が無い → 元の exe に戻る
        assert!(swap(&exe, &d.join("none.exe")).is_err());
        assert_eq!(std::fs::read_to_string(&exe).unwrap(), "新しい", "失敗しても手元の exe は残る");
        std::fs::remove_dir_all(&d).ok();
    }
}
