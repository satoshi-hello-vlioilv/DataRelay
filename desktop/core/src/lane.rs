//! 何を、どの順で、いくつ同時に流すか ―― ラインの割り当ての決まり（2.37.0〜）。lib/navi_lane.py と、lib/navi_order.py の
//! order_jobs・upstream_of・reason_text と同じ答えを返す。
//!
//! 大まかな順番は RNE → テキスト・クエリ → 結合（材料も結合なら、さらに後ろ）。ただし「上から順に1つずつ」ではない。
//! 順番が要るのは、材料を作る側と使う側のあいだだけ。決めるのは2つ:
//!   - その対象の材料はそろっているか（そろっていないものは、まだ流さない）
//!   - そろっているものが複数あるとき、どれを先に流すか
//!
//! 時計もスレッドもファイルも触らない（Rust の実行役の黒板が、これを使って配る）。
use serde_json::Value;
use std::collections::{BTreeSet, HashMap};

/// 種類ごとの大まかな順番（KIND_TIER。小さいほど先）と、材料も結合の結合の順番。
fn kind_tier(kind: &str) -> u8 {
    match kind {
        "rne" => 0,
        "text" | "mquery" => 1,
        _ => 2,
    }
}
const TIER_JOIN_CHAIN: u8 = 3;

fn tier_label(t: u8) -> &'static str {
    match t {
        0 => "RNE",
        1 => "テキスト・クエリ",
        2 => "結合",
        _ => "結合（材料も結合）",
    }
}

/// 手元の処理へ既定で何本ぶん割り当てるか（自動のとき）。
const LOCAL_LINES_AUTO_MAX: i64 = 4;

/// 手元の処理の種類（LOCAL_KINDS）。
pub const LOCAL_KINDS: [&str; 3] = ["text", "join", "mquery"];

/// 計画の1件（build_plan の1行）。
#[derive(Debug, Clone, PartialEq)]
pub struct Entry {
    pub id: String,
    pub name: String,
    pub kind: String,
    pub order: usize,
    /// 待つ相手（この実行に入っている物だけ）
    pub needs: BTreeSet<String>,
    pub tier: u8,
}

/// build_plan（対象1件ごとに「種類・順位・待つ相手」を決める。並び順は増やしも減らしもしない）。
/// jobs は (id, 名前) の並び。kinds に無い対象は rne。
pub fn build_plan(jobs: &[(String, String)], deps: &HashMap<String, BTreeSet<String>>, kinds: &HashMap<String, String>) -> Vec<Entry> {
    let ids: BTreeSet<&String> = jobs.iter().map(|(i, _)| i).collect();
    let mut plan: Vec<Entry> = jobs
        .iter()
        .enumerate()
        .map(|(n, (id, name))| {
            let needs = deps.get(id).map(|d| d.iter().filter(|x| ids.contains(x) && *x != id).cloned().collect()).unwrap_or_default();
            let kind = kinds.get(id).filter(|k| !k.is_empty()).cloned().unwrap_or_else(|| "rne".into());
            Entry { id: id.clone(), name: name.clone(), kind, order: n, needs, tier: 0 }
        })
        .collect();
    // dict の {e['id']: e}（同じ id は後の行が勝つ）
    let kind_of: HashMap<String, String> = plan.iter().map(|e| (e.id.clone(), e.kind.clone())).collect();
    for e in &mut plan {
        let mut t = kind_tier(&e.kind);
        if t == kind_tier("join") && e.needs.iter().any(|d| kind_of.get(d).is_some_and(|k| k == "join")) {
            t = TIER_JOIN_CHAIN;
        }
        e.tier = t;
    }
    plan
}

fn by_turn(mut v: Vec<&Entry>) -> Vec<&Entry> {
    v.sort_by_key(|e| (e.tier, e.order));
    v
}

/// ready（いま流してよいものを、流す順に。材料がそろっていて、まだ誰も取っていないもの）。kinds があればその種類だけ。
pub fn ready<'a>(plan: &'a [Entry], done: &BTreeSet<String>, started: &BTreeSet<String>, kinds: Option<&[&str]>) -> Vec<&'a Entry> {
    by_turn(
        plan.iter()
            .filter(|e| !started.contains(&e.id) && !done.contains(&e.id))
            .filter(|e| kinds.is_none_or(|k| k.contains(&e.kind.as_str())))
            .filter(|e| e.needs.is_subset(done))
            .collect(),
    )
}

/// unreachable（材料が失敗したので、もう走れないもの。孫まで数える）。
pub fn unreachable<'a>(plan: &'a [Entry], failed: &BTreeSet<String>, done: &BTreeSet<String>) -> Vec<&'a Entry> {
    let mut bad = failed.clone();
    loop {
        let mut changed = false;
        for e in plan {
            if bad.contains(&e.id) || done.contains(&e.id) {
                continue;
            }
            if !e.needs.is_disjoint(&bad) {
                bad.insert(e.id.clone());
                changed = true;
            }
        }
        if !changed {
            break;
        }
    }
    by_turn(plan.iter().filter(|e| bad.contains(&e.id) && !failed.contains(&e.id) && !done.contains(&e.id)).collect())
}

/// names_of（id の一覧を、流す順の名前の一覧へ。計画に無い id は落とす）。
pub fn names_of(ids: &BTreeSet<String>, plan: &[Entry]) -> Vec<String> {
    let by: HashMap<&str, &Entry> = plan.iter().map(|e| (e.id.as_str(), e)).collect();
    let mut known: Vec<&Entry> = ids.iter().filter_map(|i| by.get(i.as_str()).copied()).collect();
    known.sort_by_key(|e| (e.tier, e.order));
    known.into_iter().map(|e| e.name.clone()).collect()
}

/// blocking_names（その対象が、いま誰を待っているのか）。
pub fn blocking_names(entry: &Entry, plan: &[Entry], done: &BTreeSet<String>) -> Vec<String> {
    names_of(&entry.needs.difference(done).cloned().collect(), plan)
}

/// local_lines（手元の処理へ何本ぶん割り当てるか。0 なら並列ライン数に合わせて控えめに）。
/// configured は設定の値そのもの（int() で読めなければ 0 と同じ）。
pub fn local_lines(configured: &Value, batch_lines: i64, local_count: i64) -> i64 {
    let n = if crate::pyish::truthy(configured) { crate::pyish::int_opt(configured).ok().flatten().unwrap_or(0) } else { 0 };
    let n = if n <= 0 { LOCAL_LINES_AUTO_MAX.min(if batch_lines == 0 { 1 } else { batch_lines }.max(1)) } else { n };
    let count = if local_count == 0 { 1 } else { local_count };
    1.max(n.min(count.max(1)))
}

/// plan_text（並べ方を1行で。ログを読む人が「なぜこの順なのか」を追えるように）。
pub fn plan_text(plan: &[Entry]) -> String {
    let mut groups: Vec<(u8, Vec<&str>)> = Vec::new();
    for e in by_turn(plan.iter().collect()) {
        match groups.iter_mut().find(|(t, _)| *t == e.tier) {
            Some((_, v)) => v.push(&e.name),
            None => groups.push((e.tier, vec![&e.name])),
        }
    }
    groups.sort_by_key(|(t, _)| *t);
    groups.iter().map(|(t, v)| format!("{}: {}", tier_label(*t), v.join("・"))).collect::<Vec<_>>().join(" → ")
}

/// wait_text（材料を待つ対象と、その相手）。
pub fn wait_text(plan: &[Entry]) -> String {
    let by: HashMap<&str, &Entry> = plan.iter().map(|e| (e.id.as_str(), e)).collect();
    by_turn(plan.iter().filter(|e| !e.needs.is_empty()).collect())
        .iter()
        .map(|e| {
            let who: Vec<&str> = e.needs.iter().filter_map(|d| by.get(d.as_str()).map(|x| x.name.as_str())).collect();
            format!("{}←{}", e.name, who.join("・"))
        })
        .collect::<Vec<_>>()
        .join("／")
}

/// order_jobs（材料を作る側が先に来るように並べ替える。輪になっていて決められない残りは、元の順のまま後ろへ）。
/// → (並べ替えた id, 輪になって決められなかった id)。
pub fn order_jobs(ids: &[String], deps: &HashMap<String, BTreeSet<String>>) -> (Vec<String>, Vec<String>) {
    let known: BTreeSet<&String> = ids.iter().collect();
    let want = |i: &String| -> BTreeSet<String> {
        deps.get(i).map(|d| d.iter().filter(|x| known.contains(x)).cloned().collect()).unwrap_or_default()
    };
    let (mut out, mut done, mut rest): (Vec<String>, BTreeSet<String>, Vec<String>) = (Vec::new(), BTreeSet::new(), ids.to_vec());
    while !rest.is_empty() {
        let now: Vec<String> = rest.iter().filter(|i| want(i).is_subset(&done)).cloned().collect();
        if now.is_empty() {
            out.extend(rest.iter().cloned());
            return (out, rest);
        }
        for i in now {
            done.insert(i.clone());
            out.push(i);
        }
        rest.retain(|i| !done.contains(i));
    }
    (out, vec![])
}

/// upstream_of（その対象より前に済ませておくべき対象。材料の材料まで depth 段）。
pub fn upstream_of(id: &str, deps: &HashMap<String, BTreeSet<String>>, depth: usize) -> BTreeSet<String> {
    let mut seen = BTreeSet::new();
    let mut front: BTreeSet<String> = [id.to_string()].into();
    for _ in 0..depth.max(1) {
        let mut next: BTreeSet<String> = front.iter().flat_map(|i| deps.get(i).cloned().unwrap_or_default()).collect();
        next.retain(|x| !seen.contains(x) && x != id);
        if next.is_empty() {
            break;
        }
        seen.extend(next.iter().cloned());
        front = next;
    }
    seen
}

/// reason_text（待つ理由を、そのまま読める1行に。4件まで並べ、残りは数だけ）。
pub fn reason_text(reasons: &[Value]) -> String {
    let label = |k: &str| match k {
        "running" => "いま作成中です".to_string(),
        "queued" => "実行の順番待ちです".to_string(),
        "scheduled" => "まもなく作成が始まります".to_string(),
        "writing" => "公開先へ書き込み中です".to_string(),
        other => other.to_string(),
    };
    let text = |v: Option<&Value>| v.filter(|x| crate::pyish::truthy(x)).map(crate::pyish::py_str).unwrap_or_default();
    let parts: Vec<String> = reasons
        .iter()
        .take(4)
        .map(|r| {
            let at = text(r.get("at"));
            let at = if at.is_empty() { String::new() } else { format!("（{}）", at.replace('T', " ")) };
            format!("{}: {}{at}", text(r.get("job")), label(&text(r.get("kind"))))
        })
        .collect();
    let more = if reasons.len() > 4 { format!(" ほか{}件", reasons.len() - 4) } else { String::new() };
    format!("{}{more}", parts.join("／"))
}

// ==== 待ち合わせ（navi_order.wait_reasons・publishing_now） ==================

/// 書きかけの印の賞味期限（INCOMING_STALE_SECONDS。強制終了で残った印を、いつまでも「書いている最中」と読まないため）。
const INCOMING_STALE_SECONDS: u64 = 900;

/// publishing_now（その場所へ、いま公開の書き込みが来ているか ―― 隣に新しい .<名前>.*.incoming があるか）。
/// 名前の比べ方は glob と同じく、Windows では大文字小文字を区別しない。
pub fn publishing_now(path: &str) -> bool {
    if crate::pyish::strip(path).is_empty() {
        return false;
    }
    let name = crate::paths::py_name(path);
    let Some(dir) = std::path::Path::new(path).parent() else { return false };
    let dir = if dir.as_os_str().is_empty() { std::path::Path::new(".") } else { dir };
    let Ok(rd) = std::fs::read_dir(dir) else { return false };
    let fold = |s: &str| if cfg!(windows) { s.to_lowercase() } else { s.to_string() };
    let (head, tail) = (fold(&format!(".{name}.")), fold(".incoming"));
    let limit = std::time::SystemTime::now() - std::time::Duration::from_secs(INCOMING_STALE_SECONDS);
    rd.flatten().any(|e| {
        let n = fold(&e.file_name().to_string_lossy());
        n.len() >= head.len() + tail.len()
            && n.starts_with(&head)
            && n.ends_with(&tail)
            && e.metadata().and_then(|m| m.modified()).is_ok_and(|t| t >= limit)
    })
}

/// wait_reasons（いま走ってよいか。待つ理由の一覧。空なら走ってよい）。
/// 材料を作る対象が、実行中・順番待ち・まもなく予定（lookahead 秒以内）か。材料のファイルへ、いま公開の書き込みが来ているか。
#[allow(clippy::too_many_arguments)]
pub fn wait_reasons(
    job_id: &str,
    deps: &HashMap<String, BTreeSet<String>>,
    running: &BTreeSet<String>,
    queued: &BTreeSet<String>,
    next_run_of: impl Fn(&str) -> Option<chrono::NaiveDateTime>,
    inputs: &[String],
    now: chrono::NaiveDateTime,
    lookahead_seconds: i64,
    name_of: impl Fn(&str) -> String,
) -> Vec<Value> {
    use serde_json::json;
    let mut out = Vec::new();
    let limit = now + chrono::Duration::seconds(lookahead_seconds.max(0));
    for owner in deps.get(job_id).into_iter().flatten() {
        if running.contains(owner) {
            out.push(json!({"kind": "running", "job_id": owner, "job": name_of(owner)}));
        } else if queued.contains(owner) {
            out.push(json!({"kind": "queued", "job_id": owner, "job": name_of(owner)}));
        } else if let Some(at) = next_run_of(owner).filter(|t| now <= *t && *t <= limit) {
            out.push(
                json!({"kind": "scheduled", "job_id": owner, "job": name_of(owner), "at": at.format("%Y-%m-%dT%H:%M:%S").to_string()}),
            );
        }
    }
    for p in inputs {
        if publishing_now(p) {
            out.push(json!({"kind": "writing", "path": crate::paths::py_path(p), "job": crate::paths::py_name(p)}));
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn set(v: &[&str]) -> BTreeSet<String> {
        v.iter().map(|x| x.to_string()).collect()
    }

    #[test]
    fn order_and_cycle() {
        let ids: Vec<String> = ["a", "b", "c", "d"].iter().map(|x| x.to_string()).collect();
        let deps: HashMap<String, BTreeSet<String>> =
            [("a".into(), set(&["b"])), ("c".into(), set(&["d"])), ("d".into(), set(&["c"]))].into_iter().collect();
        let (order, cycle) = order_jobs(&ids, &deps);
        assert_eq!(order, ["b", "a", "c", "d"]);
        assert_eq!(cycle, ["c", "d"]);
    }

    #[test]
    fn join_waits_and_fails_with_material() {
        let jobs = vec![("j".to_string(), "結合".to_string()), ("r".to_string(), "RNE".to_string())];
        let deps: HashMap<String, BTreeSet<String>> = [("j".into(), set(&["r"]))].into_iter().collect();
        let kinds: HashMap<String, String> = [("j".into(), "join".into())].into_iter().collect();
        let plan = build_plan(&jobs, &deps, &kinds);
        let ids = |v: Vec<&Entry>| v.iter().map(|e| e.id.clone()).collect::<Vec<_>>();
        assert_eq!(ids(ready(&plan, &set(&[]), &set(&[]), None)), ["r"]);
        assert_eq!(ids(ready(&plan, &set(&["r"]), &set(&[]), None)), ["j"]);
        assert_eq!(ids(unreachable(&plan, &set(&["r"]), &set(&[]))), ["j"]);
        assert_eq!(wait_text(&plan), "結合←RNE");
    }
}
