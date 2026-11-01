//! 抽出期間（処理日時を基準にした相対の期間）の決まり。lib/navi_period.py と同じ答えを返す（2.15.0 で移した）。
//!
//! 期間を当てる先は2通り:
//!   - point = RNE の時間型の管理ポイント（NaviChangePeriod）。両端が要るので、範囲の形は「期間（〜から〜まで）」だけ
//!   - cond  = 条件欄の日付の項目（NaviChangeConditionDI の範囲指定）。「期間」「以降」「以前」を選べる
//!
//! 日付の書き方は、RNE に入っている日付（sample）と同じ形にそろえる（例: 2026/1/1 → 2026/7/27）。
//! 月を単位にするとき、条件欄の日付は「始まりの月の1日」〜「終わりの月の末日」にする。
//! 日付は Python の date と同じく 1〜9999 年。範囲を出る計算は Python と同じく失敗（`Fail`）にする。

use crate::pyish::{self, TooLarge};
use serde_json::{json, Map, Value};

pub const TARGETS: [&str; 2] = ["point", "cond"];
/// 期間（〜から〜まで）・以降（〜から）・以前（〜まで）
pub const RANGES: [&str; 3] = ["between", "from", "to"];
pub const UNITS: [&str; 2] = ["month", "day"];

/// 計算できない（年が 1〜9999 を出る・数が大きすぎる）。Python では ValueError・OverflowError で、画面へは 500 になる。
#[derive(Debug, PartialEq)]
pub struct Fail;

impl From<TooLarge> for Fail {
    fn from(_: TooLarge) -> Self {
        Fail
    }
}

/// 日付（1〜9999 年）。
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub struct Date {
    pub year: i64,
    pub month: u32,
    pub day: u32,
}

impl Date {
    /// Python の date(year, month, day)。正しくない日付は None。
    pub fn new(year: i64, month: u32, day: u32) -> Option<Date> {
        ((1..=9999).contains(&year) && (1..=12).contains(&month) && day >= 1 && day <= last_day(year, month)).then_some(Date {
            year,
            month,
            day,
        })
    }

    /// 0001-01-01 からの日数（Python の toordinal() − 1）。
    fn days(self) -> i64 {
        // Howard Hinnant の days_from_civil（1970-01-01 起点）を 0001-01-01 起点へずらす
        let y = self.year - i64::from(self.month <= 2);
        let era = y.div_euclid(400);
        let yoe = y - era * 400;
        let mp = (i64::from(self.month) + 9) % 12;
        let doy = (153 * mp + 2) / 5 + i64::from(self.day) - 1;
        let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
        era * 146097 + doe - 306
    }

    fn from_days(n: i64) -> Option<Date> {
        let z = n + 306;
        let era = z.div_euclid(146097);
        let doe = z - era * 146097;
        let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
        let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
        let mp = (5 * doy + 2) / 153;
        let day = (doy - (153 * mp + 2) / 5 + 1) as u32;
        let month = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
        let year = yoe + era * 400 + i64::from(month <= 2);
        Date::new(year, month, day)
    }

    /// Python の date + timedelta(days=n)。範囲を出れば None（OverflowError）。
    pub fn add_days(self, n: i64) -> Option<Date> {
        if n.abs() > 999_999_999 {
            return None; // timedelta そのものが作れない大きさ
        }
        Date::from_days(self.days() + n)
    }

    /// isoformat()。
    pub fn iso(self) -> String {
        format!("{:04}-{:02}-{:02}", self.year, self.month, self.day)
    }
}

fn leap(y: i64) -> bool {
    y % 4 == 0 && (y % 100 != 0 || y % 400 == 0)
}

/// calendar.monthrange(y, m)[1]。
pub fn last_day(y: i64, m: u32) -> u32 {
    match m {
        2 if leap(y) => 29,
        2 => 28,
        4 | 6 | 9 | 11 => 30,
        _ => 31,
    }
}

/// 年と月を delta か月ずらす（Python の切り捨ての割り算と同じ。負の年にもなる）。
pub fn add_months(year: i64, month: u32, delta: i64) -> Result<(i64, u32), Fail> {
    let idx = year.checked_mul(12).and_then(|v| v.checked_add(i64::from(month) - 1)).and_then(|v| v.checked_add(delta)).ok_or(Fail)?;
    Ok((idx.div_euclid(12), idx.rem_euclid(12) as u32 + 1))
}

/// 保存の形（navi_period.normalize）。
#[derive(Debug, Clone, PartialEq)]
pub struct Period {
    pub enabled: bool,
    pub target: &'static str,
    pub control_point: String,
    pub cond_item: String,
    pub range: &'static str,
    pub unit: &'static str,
    pub from_offset: i64,
    pub to_offset: i64,
}

fn pick(v: Option<&Value>, allowed: &[&'static str], default: &'static str) -> &'static str {
    v.and_then(Value::as_str).and_then(|s| allowed.iter().find(|a| **a == s).copied()).unwrap_or(default)
}

/// 保存の形にそろえる。昔の保存（target・range が無い）は「管理ポイント・期間」として読む。
pub fn normalize(d: &Map<String, Value>) -> Result<Period, Fail> {
    let target = pick(d.get("target"), &TARGETS, "point");
    // NaviChangePeriod は両端が要るので、管理ポイントは「期間」だけ
    let range = if target == "point" { "between" } else { pick(d.get("range"), &RANGES, "between") };
    Ok(Period {
        enabled: d.get("enabled").map(pyish::truthy).unwrap_or(false),
        target,
        control_point: pyish::strip(&pyish::text_or_empty(d.get("control_point"))).to_string(),
        cond_item: pyish::strip(&pyish::text_or_empty(d.get("cond_item"))).to_string(),
        range,
        unit: pick(d.get("unit"), &UNITS, "month"),
        from_offset: pyish::int_or(d.get("from_offset"), 0)?,
        to_offset: pyish::int_or(d.get("to_offset"), 0)?,
    })
}

/// 日付の書き方（正規表現 `^\s*(\d{4})([/\-.]?)(\d{1,2})\2(\d{1,2})` に当たった部分）。
struct DateText {
    year: Vec<u32>,
    sep: Option<char>,
    month: Vec<u32>,
    day: Vec<u32>,
}

/// Python の re.match と同じ当て方（区切りは有る方を先に、月は2桁を先に試し、だめなら戻って試し直す）。
fn match_date(s: &str) -> Option<DateText> {
    let c: Vec<char> = s.chars().collect();
    let digits = |from: usize, n: usize| -> Option<Vec<u32>> { (0..n).map(|i| c.get(from + i).and_then(|&x| pyish::digit(x))).collect() };
    let mut i = 0;
    while c.get(i).is_some_and(|&x| pyish::is_space(x)) {
        i += 1;
    }
    let year = digits(i, 4)?;
    let pos = i + 4;
    let seps: Vec<Option<char>> = match c.get(pos) {
        Some(&x) if "/-.".contains(x) => vec![Some(x), None],
        _ => vec![None],
    };
    for sep in seps {
        let p = pos + usize::from(sep.is_some());
        for n in [2, 1] {
            let Some(month) = digits(p, n) else { continue };
            let mut q = p + n;
            if let Some(x) = sep {
                if c.get(q) != Some(&x) {
                    continue;
                }
                q += 1;
            }
            let day: Vec<u32> = (q..q + 2).map_while(|k| c.get(k).and_then(|&x| pyish::digit(x))).collect();
            if !day.is_empty() {
                return Some(DateText { year, sep, month, day });
            }
        }
    }
    None
}

fn number(ds: &[u32]) -> i64 {
    ds.iter().fold(0, |a, d| a * 10 + i64::from(*d))
}

/// '2026/1/1'・'2026-01-01'・'20260101'（後ろに時刻があってもよい）を日付にする。読めなければ None。
pub fn parse_date(s: &str) -> Option<Date> {
    let m = match_date(s)?;
    Date::new(number(&m.year), number(&m.month) as u32, number(&m.day) as u32)
}

/// sample と同じ書き方で d を書く。区切り（/ - . なし）と、月日の0埋めを sample に合わせる。sample が日付でなければ 2026/1/1 の形。
pub fn format_like(sample: &str, d: Date) -> String {
    let Some(m) = match_date(sample) else { return format!("{}/{}/{}", d.year, d.month, d.day) };
    let sep = m.sep.map(String::from).unwrap_or_default();
    let pad = (m.month.len() == 2 && m.day.len() == 2) || m.sep.is_none();
    if pad {
        format!("{}{sep}{:02}{sep}{:02}", d.year, d.month, d.day)
    } else {
        format!("{}{sep}{}{sep}{}", d.year, d.month, d.day)
    }
}

/// 条件欄の日付の両端。月を単位にすると、始まりは月の1日・終わりは月の末日。
pub fn cond_dates(p: &Period, today: Date) -> Result<(Date, Date), Fail> {
    if p.unit == "month" {
        let (fy, fm) = add_months(today.year, today.month, p.from_offset)?;
        let (ty, tm) = add_months(today.year, today.month, p.to_offset)?;
        let from = Date::new(fy, fm, 1).ok_or(Fail)?;
        let to = Date::new(ty, tm, if (1..=9999).contains(&ty) { last_day(ty, tm) } else { 1 }).ok_or(Fail)?;
        return Ok((from, to));
    }
    Ok((today.add_days(p.from_offset).ok_or(Fail)?, today.add_days(p.to_offset).ok_or(Fail)?))
}

/// 画面と記録に出す一言。
pub fn summary(p: &Period, lo: &str, hi: &str) -> String {
    match p.range {
        "from" => format!("{lo} 以降"),
        "to" => format!("{hi} 以前"),
        _ => format!("{lo} ～ {hi}"),
    }
}

/// 期間を計算する（navi_period.compute）。無効なら None。
///   - point → {kind:'point', condition:0（月度）/1（年月日）, from_time, to_time, …}（NaviChangePeriod へ渡す形）
///   - cond  → {kind:'cond', range, lvalue, rvalue, …}（日付は sample の書き方）
pub fn compute(p: &Period, today: Date, sample: &str) -> Result<Option<Map<String, Value>>, Fail> {
    if !p.enabled {
        return Ok(None);
    }
    let mut out = Map::new();
    out.insert("unit".into(), json!(p.unit));
    out.insert("from_offset".into(), json!(p.from_offset));
    out.insert("to_offset".into(), json!(p.to_offset));
    out.insert("range".into(), json!(p.range));
    let mut put = |k: &str, v: Value| {
        out.insert(k.into(), v);
    };
    if p.target == "cond" {
        let (mut fd, mut td) = cond_dates(p, today)?;
        if p.range == "between" && fd > td {
            std::mem::swap(&mut fd, &mut td);
        }
        let lo = if p.range != "to" { format_like(sample, fd) } else { String::new() };
        let hi = if p.range != "from" { format_like(sample, td) } else { String::new() };
        put("kind", json!("cond"));
        put("item", json!(p.cond_item));
        put("summary", json!(summary(p, &lo, &hi)));
        put("lvalue", json!(lo));
        put("rvalue", json!(hi));
        put("from_date", json!(fd.iso()));
        put("to_date", json!(td.iso()));
    } else if p.unit == "month" {
        let (fy, fm) = add_months(today.year, today.month, p.from_offset)?;
        let (ty, tm) = add_months(today.year, today.month, p.to_offset)?;
        put("kind", json!("point"));
        put("condition", json!(0));
        put("from_time", json!(format!("{fy:04}{fm:02}00")));
        put("to_time", json!(format!("{ty:04}{tm:02}00")));
        put("summary", json!(format!("{fy}年{fm}月度 ～ {ty}年{tm}月度")));
    } else {
        let fd = today.add_days(p.from_offset).ok_or(Fail)?;
        let td = today.add_days(p.to_offset).ok_or(Fail)?;
        put("kind", json!("point"));
        put("condition", json!(1));
        put("from_time", json!(format!("{:04}{:02}{:02}", fd.year, fd.month, fd.day)));
        put("to_time", json!(format!("{:04}{:02}{:02}", td.year, td.month, td.day)));
        put("summary", json!(format!("{} ～ {}", fd.iso(), td.iso())));
    }
    Ok(Some(out))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn period(v: Value) -> Period {
        normalize(v.as_object().unwrap()).unwrap()
    }
    fn d(y: i64, m: u32, day: u32) -> Date {
        Date::new(y, m, day).unwrap()
    }
    fn get(spec: &Map<String, Value>, k: &str) -> String {
        spec[k].as_str().map(String::from).unwrap_or_else(|| spec[k].to_string())
    }

    /// tests/test_cond_period.py の RuleTest と同じ場合（2026-10-27 を基準）。
    #[test]
    fn same_rules_as_python() {
        let today = d(2026, 10, 27);
        let p = period(
            json!({"enabled": true, "target": "cond", "cond_item": "払出日", "range": "between", "unit": "month", "from_offset": -3, "to_offset": -1}),
        );
        let s = compute(&p, today, "2026/1/1").unwrap().unwrap();
        assert_eq!(
            (get(&s, "lvalue"), get(&s, "rvalue"), get(&s, "summary")),
            ("2026/7/1".into(), "2026/9/30".into(), "2026/7/1 ～ 2026/9/30".into())
        );
        let p = period(json!({"enabled": true, "target": "cond", "range": "from", "unit": "day", "from_offset": -90}));
        let s = compute(&p, today, "2026/01/01").unwrap().unwrap();
        assert_eq!((get(&s, "lvalue"), get(&s, "rvalue"), get(&s, "summary")), ("2026/07/29".into(), "".into(), "2026/07/29 以降".into()));
        let p = period(json!({"enabled": true, "target": "cond", "range": "to", "unit": "month", "to_offset": 0}));
        assert_eq!(get(&compute(&p, today, "20260101").unwrap().unwrap(), "rvalue"), "20261031");
        let p = period(json!({"enabled": true, "target": "point", "range": "from", "unit": "month", "from_offset": -2, "to_offset": 0}));
        let s = compute(&p, today, "").unwrap().unwrap();
        assert_eq!(
            (get(&s, "range"), get(&s, "from_time"), get(&s, "to_time")),
            ("between".into(), "20260800".into(), "20261000".into()),
            "管理ポイントは期間だけ"
        );
        let p = period(json!({"enabled": true, "target": "point", "unit": "day", "from_offset": -1, "to_offset": 0}));
        let s = compute(&p, today, "").unwrap().unwrap();
        assert_eq!((get(&s, "from_time"), get(&s, "summary")), ("20261026".into(), "2026-10-26 ～ 2026-10-27".into()));
        assert_eq!(compute(&period(json!({})), today, "").unwrap(), None, "無効なら計算しない");
    }

    #[test]
    fn between_is_swapped_when_reversed() {
        let p = period(json!({"enabled": true, "target": "cond", "unit": "day", "from_offset": 5, "to_offset": -5}));
        let s = compute(&p, d(2026, 1, 10), "2026/1/1").unwrap().unwrap();
        assert_eq!((get(&s, "lvalue"), get(&s, "rvalue")), ("2026/1/5".into(), "2026/1/15".into()));
    }

    #[test]
    fn date_text_like_python_regex() {
        assert_eq!(parse_date("2026/1/1"), Some(d(2026, 1, 1)));
        assert_eq!(parse_date(" 2026-01-31 12:00"), Some(d(2026, 1, 31)));
        assert_eq!(parse_date("20260131"), Some(d(2026, 1, 31)));
        assert_eq!(parse_date("202611"), Some(d(2026, 1, 1)), "区切りなしは 月1桁・日1桁へ戻って当てる");
        assert_eq!(parse_date("2026/11"), None, "区切りが揃わない");
        assert_eq!(parse_date("２０２６／１／１"), None, "全角の区切りは区切りではない");
        assert_eq!(parse_date("２０２６-１-２"), Some(d(2026, 1, 2)), "全角の数字は数字");
        assert_eq!(parse_date("2026/2/30"), None);
        assert_eq!(parse_date("0000/1/1"), None, "0 年は無い");
        assert_eq!(format_like("2026.01.01", d(2026, 7, 1)), "2026.07.01");
        assert_eq!(format_like("2026-1-1", d(2026, 7, 1)), "2026-7-1");
        assert_eq!(format_like("x", d(2026, 7, 1)), "2026/7/1");
        assert_eq!(format_like("2026/1/01", d(2026, 7, 1)), "2026/7/1", "月日の両方が2桁のときだけ0埋め");
    }

    #[test]
    fn calendar_arithmetic() {
        assert_eq!(d(2024, 2, 28).add_days(1), Some(d(2024, 2, 29)));
        assert_eq!(d(2023, 12, 31).add_days(1), Some(d(2024, 1, 1)));
        assert_eq!(d(1, 1, 1).add_days(-1), None, "1 年より前は無い");
        assert_eq!(d(9999, 12, 31).add_days(1), None);
        assert_eq!(d(2026, 10, 27).add_days(-36500), Some(d(1926, 11, 21)));
        for n in [-700_000, -1, 0, 59, 365 * 400] {
            let x = d(2000, 3, 1).add_days(n).unwrap();
            assert_eq!(x.add_days(-n), Some(d(2000, 3, 1)), "{n}");
        }
        assert_eq!(add_months(2026, 1, -1).unwrap(), (2025, 12));
        assert_eq!(add_months(0, 1, -1).unwrap(), (-1, 12), "Python の切り捨ての割り算");
    }

    #[test]
    fn out_of_range_fails_like_python() {
        let p = period(json!({"enabled": true, "target": "cond", "unit": "month", "from_offset": -30000}));
        assert_eq!(compute(&p, d(2026, 1, 1), ""), Err(Fail));
        let p = period(json!({"enabled": true, "target": "point", "unit": "month", "from_offset": -30000}));
        let s = compute(&p, d(2026, 1, 1), "").unwrap().unwrap();
        assert_eq!(get(&s, "from_time"), "-4740100", "管理ポイントの月は日付にしないので、Python と同じ字のまま");
    }
}
