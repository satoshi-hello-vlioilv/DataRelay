"""Excel が書き出したファイルから、Power Query の式を取り出す（2.4.0）。

- .odc（Office データ接続ファイル。「接続ファイルのエクスポート」）: HTML の中の <odc:PowerQueryMashupData> に、
  クエリごとの名前と式（<Query Name><Formula>）がある。出すクエリは接続文字列の Location=…。
  古い形では、接続文字列の Extended Properties に式の包み（下）を base64 で入れている。
- .xlsx・.xlsm（ブックそのもの）: customXml の <DataMashup> に式の包みが base64 で入っている。
  出すクエリは、シートに読み込んでいるもの（xl/queryTables の接続 → xl/connections.xml の Location）。
- 式の包み（MS-QDEFF）: 版4バイト・長さ4バイト・ZIP（中の Formulas/Section1.m が section の形の式）・…

ここはファイルを読むだけ（DB も画面も触らない）。取り出した式を1つのクエリにまとめるのは navi_mrun。
"""
import base64
import html
import io
import re
import struct
import zipfile
from xml.etree import ElementTree

import navi_m as M

NS = '{http://schemas.microsoft.com/DataMashup}'


def kind_of(blob):
    """'workbook'・'odc'・'json'・'text' のどれか（拡張子ではなく中身で見分ける。名前を変えただけの物が来るため）。"""
    if blob[:2] == b'PK':
        return 'workbook'
    head = blob[:4000].decode('utf-8', errors='replace').lstrip('\ufeff').lstrip().lower()
    if 'x-ms-odc' in head or b'PowerQueryMashupData' in blob or b'Microsoft.Mashup' in blob:
        return 'odc'
    if head.startswith(('{', '[')):
        return 'json'
    return 'text'


def blocks(pairs, main=None):
    """[(名前, 式)] → 「// 名前」で区切った1つの式（詳細エディターの中身と同じ書き方。出すクエリを先頭に）。"""
    order = sorted(pairs, key=lambda q: 0 if q[0] == main else 1)
    return '\n\n'.join(f'// {name}\n{str(text).strip()}' for name, text in order) + '\n'


def from_section(text):
    """Section1.m（section Section1; shared 名前 = 式;）→ [(名前, 式)]。"""
    return [(q.name, q.text) for q in M.read_queries(text)]


def from_package(raw):
    """式の包み（MS-QDEFF）か ZIP そのものから、Section1.m の式を読む。"""
    body = raw
    if raw[:4] != b'PK\x03\x04' and len(raw) > 8:
        _ver, n = struct.unpack_from('<II', raw, 0)
        body = raw[8:8 + n]
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        name = next((n for n in z.namelist() if n.lower().endswith('formulas/section1.m')), None)
        if not name:
            raise ValueError('Power Query の式（Formulas/Section1.m）が入っていません')
        return from_section(z.read(name).decode('utf-8-sig'))


def _decode_odc(blob):
    m = re.search(rb'charset=([A-Za-z0-9_\-]+)', blob[:2000])
    enc = m.group(1).decode('ascii') if m else 'utf-8'
    for e in (enc, 'utf-8', 'cp932'):
        try:
            return blob.decode(e).lstrip('\ufeff')
        except (LookupError, UnicodeDecodeError):
            continue
    return blob.decode('utf-8', errors='replace')


def from_odc(blob):
    """.odc → ([(名前, 式)], 出すクエリ)。"""
    text = _decode_odc(blob)
    loc = re.search(r'Location=([^;<]+?)(?:;|</)', text)
    main = html.unescape(loc.group(1)).strip().strip('"') if loc else ''
    m = re.search(r'<odc:PowerQueryMashupData>(.*?)</odc:PowerQueryMashupData>', text, re.S)
    if m:
        root = ElementTree.fromstring(html.unescape(m.group(1)))
        out = []
        for q in root.iter(NS + 'Query'):
            f = q.find(NS + 'Formula')
            if f is not None and (f.text or '').strip():
                out.append((q.get('Name') or f'クエリ{len(out) + 1}', f.text))
        if not out:
            raise ValueError('Power Query の式が入っていません')
        return out, main
    m = re.search(r'Extended Properties=(?:&quot;|")([A-Za-z0-9+/=]{40,})', text)
    if m:
        return from_package(base64.b64decode(m.group(1))), main
    raise ValueError('Power Query の式が入っていません（Power Query の接続ではない .odc です）')


SHEET_NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'


def _location(conn):
    """接続文字列の Location=… （名前に ; や空白があると "…" で囲まれる）。"""
    m = re.search(r'Location=("(?:[^"]|"")*"|[^;]*)', conn or '')
    if not m:
        return ''
    v = m.group(1).strip()
    return v[1:-1].replace('""', '"') if v.startswith('"') and v.endswith('"') else v


def _loaded(z):
    """ブックのシートに読み込んでいるクエリの名前（xl/queryTables の接続 → xl/connections.xml の Location）。
    ヘルパー（サンプル ファイル など）は「接続のみ」なので、ここに入るのは出すクエリだけ。"""
    names = z.namelist()
    if 'xl/connections.xml' not in names:
        return []
    try:
        conns = {c.get('id'): _location((c.find(SHEET_NS + 'dbPr').get('connection') if c.find(SHEET_NS + 'dbPr') is not None else ''))
                 for c in ElementTree.fromstring(z.read('xl/connections.xml')).iter(SHEET_NS + 'connection')}
    except ElementTree.ParseError:
        return []
    out = []
    for n in sorted(x for x in names if x.lower().startswith('xl/querytables/') and x.lower().endswith('.xml')):
        try:
            cid = ElementTree.fromstring(z.read(n)).get('connectionId')
        except ElementTree.ParseError:
            continue
        if conns.get(cid) and conns[cid] not in out:
            out.append(conns[cid])
    return out


def from_workbook(blob):
    """Excel のブック（.xlsx・.xlsm）→ ([(名前, 式)], 出すクエリ（シートに読み込んでいるもの。無ければ空）)。"""
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for n in z.namelist():
            low = n.lower()
            if not (low.startswith('customxml/item') and low.endswith('.xml')):
                continue
            try:
                root = ElementTree.fromstring(z.read(n))
            except ElementTree.ParseError:
                continue
            if root.tag == NS + 'DataMashup' and (root.text or '').strip():
                pairs = from_package(base64.b64decode(root.text.strip()))
                have = {name for name, _ in pairs}
                return pairs, next((x for x in _loaded(z) if x in have), '')
    raise ValueError('このブックには Power Query のクエリが入っていません')


def extract(blob):
    """ファイルの中身 → ([(名前, 式)], 出すクエリ（分からなければ空）)。"""
    k = kind_of(blob)
    if k == 'workbook':
        return from_workbook(blob)
    if k == 'odc':
        return from_odc(blob)
    raise ValueError('Excel のブック・.odc ではありません')
