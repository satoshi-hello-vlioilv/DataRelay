//! Python の基本の振る舞い（`int()`・`str()`・`bool()`・`str.strip()`・正規表現の `\d` `\s`）を、JSON の値に対して同じにする。
//!
//! 移したルートの答えを Python と同じにするための部品。画面から来る値はたいてい文字か数だが、
//! 「全角の数字（２０２６）も数字として読む」「' 3 ' を 3 と読む」といった Python の読み方を、ここで揃える。
//! 数字の範囲は Python 3.12 と同じ Unicode 15.0 の Nd（10 進の数字）。

use serde_json::Value;

/// Unicode の 10 進の数字（Nd）の「0」の位置。どれも 0〜9 が続けて並ぶ（Unicode 15.0・66＋2 か所）。
const ND_ZEROS: &[u32] = &[
    0x30, 0x660, 0x6F0, 0x7C0, 0x966, 0x9E6, 0xA66, 0xAE6, 0xB66, 0xBE6, 0xC66, 0xCE6, 0xD66, 0xDE6, 0xE50, 0xED0, 0xF20, 0x1040, 0x1090,
    0x17E0, 0x1810, 0x1946, 0x19D0, 0x1A80, 0x1A90, 0x1B50, 0x1BB0, 0x1C40, 0x1C50, 0xA620, 0xA8D0, 0xA900, 0xA9D0, 0xA9F0, 0xAA50, 0xABF0,
    0xFF10, 0x104A0, 0x10D30, 0x11066, 0x110F0, 0x11136, 0x111D0, 0x112F0, 0x11450, 0x114D0, 0x11650, 0x116C0, 0x11730, 0x118E0, 0x11950,
    0x11C50, 0x11D50, 0x11DA0, 0x11F50, 0x16A60, 0x16AC0, 0x16B50, 0x1D7CE, 0x1D7D8, 0x1D7E2, 0x1D7EC, 0x1D7F6, 0x1E140, 0x1E2F0, 0x1E4F0,
    0x1E950, 0x1FBF0,
];

/// `\d` に当たる文字なら、その値（0〜9）。
pub fn digit(c: char) -> Option<u32> {
    let c = c as u32;
    ND_ZEROS.iter().find(|&&z| (z..z + 10).contains(&c)).map(|z| c - z)
}

/// `str.isspace()`・正規表現の `\s` に当たる文字（Rust の char::is_whitespace に、区切りの制御文字 0x1C〜0x1F を足した物）。
pub fn is_space(c: char) -> bool {
    c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)
}

/// `str.strip()`。
pub fn strip(s: &str) -> &str {
    s.trim_matches(is_space)
}

/// `bool(v)`。null・false・0・0.0・""・[]・{} が偽。
pub fn truthy(v: &Value) -> bool {
    match v {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Number(n) => n.as_f64().is_some_and(|f| f != 0.0),
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(o) => !o.is_empty(),
    }
}

/// `str(v or '')`（画面から来る値を文字にする書き方）。文字・数・真偽は Python と同じ字にする。
/// 並び・辞書は画面から来ない値なので Python と同じ字は保証しない（JSON の字にする）。
pub fn text_or_empty(v: Option<&Value>) -> String {
    match v {
        Some(v) if truthy(v) => match v {
            Value::String(s) => s.clone(),
            Value::Bool(_) => "True".into(),
            Value::Number(n) => n
                .as_i64()
                .map(|i| i.to_string())
                .or_else(|| n.as_u64().map(|u| u.to_string()))
                .unwrap_or_else(|| float_repr(n.as_f64().unwrap_or(0.0))),
            other => other.to_string(),
        },
        _ => String::new(),
    }
}

/// `repr(float)`。最短で元に戻る桁を、10^-4 以上 10^16 未満は小数で、それ以外は指数（e-05・e+16）で書く。
fn float_repr(f: f64) -> String {
    if !f.is_finite() {
        return if f.is_nan() {
            "nan".into()
        } else if f > 0.0 {
            "inf".into()
        } else {
            "-inf".into()
        };
    }
    let sci = format!("{f:e}"); // 例 "1.5e-5"・"-2e16"
    let (mant, exp) = sci.split_once('e').unwrap_or((&sci, "0"));
    let exp: i32 = exp.parse().unwrap_or(0);
    let neg = mant.starts_with('-');
    let digits: String = mant.chars().filter(char::is_ascii_digit).collect();
    let sign = if neg { "-" } else { "" };
    if (-4..16).contains(&exp) {
        let point = exp + 1; // 小数点の位置（digits の何文字目の後ろか）
        let body = if point <= 0 {
            format!("0.{}{}", "0".repeat((-point) as usize), digits)
        } else if point as usize >= digits.len() {
            format!("{}{}.0", digits, "0".repeat(point as usize - digits.len()))
        } else {
            format!("{}.{}", &digits[..point as usize], &digits[point as usize..])
        };
        format!("{sign}{body}")
    } else {
        let m = if digits.len() > 1 { format!("{}.{}", &digits[..1], &digits[1..]) } else { digits };
        format!("{sign}{m}e{}{:02}", if exp < 0 { '-' } else { '+' }, exp.abs())
    }
}

/// 数が Python では扱えても、ここ（i64）では扱えないほど大きい。Python の側もこの先の日付の計算で失敗する大きさなので、処理の失敗（500）として返す。
#[derive(Debug, PartialEq)]
pub struct TooLarge;

/// `int(v)`。読めない（None・並び・"3.5" など）なら `default`（Python の TypeError・ValueError を受けて既定にする書き方）。
/// 文字は前後の空白を外し、符号・Unicode の数字・数字の間の _ を読む。小数は 0 の側へ切り捨てる。
pub fn int_or(v: Option<&Value>, default: i64) -> Result<i64, TooLarge> {
    match v {
        Some(Value::Bool(b)) => Ok(*b as i64),
        Some(Value::Number(n)) => {
            if let Some(i) = n.as_i64() {
                Ok(i)
            } else if n.as_u64().is_some() {
                Err(TooLarge)
            } else {
                let f = n.as_f64().unwrap_or(0.0).trunc();
                if f.abs() < 9.2e18 {
                    Ok(f as i64)
                } else {
                    Err(TooLarge)
                }
            }
        }
        Some(Value::String(s)) => parse_int(s).map(|r| r.unwrap_or(default)),
        _ => Ok(default),
    }
}

/// 文字の `int()`。Ok(None) は読めない（ValueError）。
fn parse_int(s: &str) -> Result<Option<i64>, TooLarge> {
    let s = strip(s);
    let (neg, rest) = match s.chars().next() {
        Some('-') => (true, &s[1..]),
        Some('+') => (false, &s[1..]),
        _ => (false, s),
    };
    let mut value: i64 = 0;
    let mut seen = false;
    let mut prev_underscore = false;
    for c in rest.chars() {
        if c == '_' {
            if !seen || prev_underscore {
                return Ok(None);
            }
            prev_underscore = true;
            continue;
        }
        let Some(d) = digit(c) else { return Ok(None) };
        value = value.checked_mul(10).and_then(|v| v.checked_add(d as i64)).ok_or(TooLarge)?;
        seen = true;
        prev_underscore = false;
    }
    if !seen || prev_underscore {
        return Ok(None);
    }
    Ok(Some(if neg { -value } else { value }))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn int_reads_like_python() {
        let r = |v: Value| int_or(Some(&v), -99);
        assert_eq!(r(json!(" 3 ")), Ok(3));
        assert_eq!(r(json!("-12")), Ok(-12));
        assert_eq!(r(json!("+1_000")), Ok(1000));
        assert_eq!(r(json!("１２")), Ok(12), "全角の数字も数字");
        assert_eq!(r(json!("3.5")), Ok(-99), "小数の字は読めない（ValueError）");
        assert_eq!(r(json!("1__0")), Ok(-99));
        assert_eq!(r(json!("_1")), Ok(-99));
        assert_eq!(r(json!("")), Ok(-99));
        assert_eq!(r(json!(3.9)), Ok(3));
        assert_eq!(r(json!(-3.9)), Ok(-3));
        assert_eq!(r(json!(true)), Ok(1));
        assert_eq!(r(json!(null)), Ok(-99));
        assert_eq!(r(json!([1])), Ok(-99));
        assert_eq!(r(json!("99999999999999999999")), Err(TooLarge));
        assert_eq!(int_or(None, 0), Ok(0));
    }

    #[test]
    fn text_like_python() {
        let t = |v: Value| text_or_empty(Some(&v));
        assert_eq!(t(json!("a")), "a");
        assert_eq!(t(json!(0)), "", "偽の値は空");
        assert_eq!(t(json!(false)), "");
        assert_eq!(t(json!(true)), "True");
        assert_eq!(t(json!(20260101)), "20260101");
        assert_eq!(t(json!(1.0)), "1.0");
        assert_eq!(t(json!(0.1)), "0.1");
        assert_eq!(t(json!(1.5e-5)), "1.5e-05");
        assert_eq!(t(json!(1e16)), "1e+16");
        assert_eq!(t(json!(123456.789)), "123456.789");
        assert_eq!(text_or_empty(None), "");
    }

    #[test]
    fn strip_and_digits() {
        assert_eq!(strip("\u{3000} a \u{1f}"), "a", "全角の空白・区切りの制御文字も外す");
        assert_eq!(digit('７'), Some(7));
        assert_eq!(digit('a'), None);
        assert_eq!(digit('²'), None, "上付きは 10 進の数字（Nd）ではない");
    }
}
