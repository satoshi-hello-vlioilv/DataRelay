"""XLSXの書き出しと検査 ―― ZIP/XMLとして直接組み立てる。

openpyxlのセル逐次appendが環境によって極端に遅くなるため、XLSXをZIPとXMLとして
そのまま作っている。中身は既定でinline string（読み取った文字をそのまま残すため）で、
読取マスタで型を決めた列だけ、本物の数値セル・日付セルにする。

app.py から分けてある。本体の状態は一切見ない（受け取るのは書き出す先と、値と、型だけ）。
外から見える名前は分ける前と同じ（app からも読める）。
"""
import time,zipfile,re
from datetime import date,datetime
from navi_log import log
from navi_output import normalize_column_type,NUMERIC_TYPES

def _xlsx_col_name(index):
 name=''
 while index:
  index,rem=divmod(index-1,26); name=chr(65+rem)+name
 return name or 'A'
def _xlsx_xml_text(value):
 s='' if value is None else str(value)
 s=''.join(ch for ch in s if ch in ('\t','\n','\r') or ord(ch)>=32)
 return s.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
# Excelの日付は「1899-12-30からの日数」。1900年をうるう年として数える昔の誤りごと
# 揃えるため、起点を12/31ではなく12/30に置くのが通例（1900-03-01以降はこれで一致する）。
_XLSX_EPOCH=date(1899,12,30)
# 書式の番号。styles.xml の cellXfs の並びと合わせてある（0=既定 1=日付 2=日時）。
_XLSX_STYLE_PLAIN,_XLSX_STYLE_DATE,_XLSX_STYLE_DATETIME=0,1,2
def _xlsx_serial(value,with_time):
 """ISO文字列（2026-08-14 / 2026-08-14 09:30:00）をExcelの日付の数へ。読めなければ None。"""
 s=str(value or '').strip()
 if not s:return None
 try:
  d=datetime.strptime(s,'%Y-%m-%d %H:%M:%S') if with_time else datetime.strptime(s,'%Y-%m-%d')
 except ValueError:
  try:d=datetime.strptime(s[:10],'%Y-%m-%d')
  except ValueError:return None
 n=(d.date()-_XLSX_EPOCH).days
 if not with_time:return str(n)
 frac=(d.hour*3600+d.minute*60+d.second)/86400.0
 return f'{n+frac:.10f}'.rstrip('0').rstrip('.') or str(n)
def _xlsx_cell(ref,value,kind):
 """1つのセル。文字はinlineStr、数値と日付は本物の数値セル（右寄せ・計算・並べ替えが効く）。

 空欄はセルごと書かない ―― 空文字を置くと、Excelでは「空ではない」扱いになり、
 数式の COUNTBLANK や末尾行の判定がずれる。"""
 if kind=='text':
  return f'<c r="{ref}" t="inlineStr"><is><t>{_xlsx_xml_text(value)}</t></is></c>'
 s='' if value is None else str(value).strip()
 if not s:return ''
 if kind in NUMERIC_TYPES:
  try:float(s)
  except ValueError:return f'<c r="{ref}" t="inlineStr"><is><t>{_xlsx_xml_text(value)}</t></is></c>'
  return f'<c r="{ref}"><v>{s}</v></c>'
 serial=_xlsx_serial(s,kind=='datetime')
 if serial is None:return f'<c r="{ref}" t="inlineStr"><is><t>{_xlsx_xml_text(value)}</t></is></c>'
 style=_XLSX_STYLE_DATETIME if kind=='datetime' else _XLSX_STYLE_DATE
 return f'<c r="{ref}" s="{style}"><v>{serial}</v></c>'
def write_xlsx_direct(dst,sheet_name,headers,body,types=None):
 # Write a minimal XLSX directly as ZIP/XML. Untyped cells are inline strings to preserve values exactly.
 # types（列名→型）を渡すと、数値と日付だけは本物の数値セルにする。渡さなければ従来どおり全部文字。
 sheet_name=(sheet_name or 'Page1')[:31]
 kinds=[normalize_column_type((types or {}).get(h)) for h in headers]
 has_stamp=any(k in ('date','datetime') for k in kinds)
 started=time.perf_counter(); rows_written=0; cell_count=0
 with zipfile.ZipFile(dst,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
  z.writestr('[Content_Types].xml','''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/><Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/><Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/></Types>''')
  z.writestr('_rels/.rels','''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/><Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/></Relationships>''')
  z.writestr('xl/_rels/workbook.xml.rels','''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>''')
  safe_sheet=sheet_name.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('"','&quot;')
  z.writestr('xl/workbook.xml',f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="{safe_sheet}" sheetId="1" r:id="rId1"/></sheets></workbook>''')
  # 日付の列があるときだけ、日付書式を2つ足す（並びは _XLSX_STYLE_* と対応）。
  # 無いときは今までと1バイトも変わらない styles.xml のままにする。
  z.writestr('xl/styles.xml','''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'''
   +('<numFmts count="2"><numFmt numFmtId="176" formatCode="yyyy/mm/dd"/><numFmt numFmtId="177" formatCode="yyyy/mm/dd hh:mm:ss"/></numFmts>' if has_stamp else '')
   +'''<fonts count="1"><font><sz val="11"/><name val="Yu Gothic"/></font></fonts><fills count="1"><fill><patternFill patternType="none"/></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'''
   +('<cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="176" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/><xf numFmtId="177" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs>'
      if has_stamp else '<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>')
   +'</styleSheet>')
  z.writestr('docProps/app.xml','''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"><Application>SymfoNavi Data Hub</Application></Properties>''')
  z.writestr('docProps/core.xml','''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:creator>SymfoNavi Data Hub</dc:creator><cp:lastModifiedBy>SymfoNavi Data Hub</cp:lastModifiedBy></cp:coreProperties>''')
  def row_xml(row_index,row,head=False):
   nonlocal cell_count
   cells=[]
   for c,v in enumerate(row,1):
    ref=f'{_xlsx_col_name(c)}{row_index}'; cell_count+=1
    # 見出しは必ず文字。中身は列の型に従う（型を決めていなければ、これまでどおり文字）。
    xml=_xlsx_cell(ref,v,'text' if head else (kinds[c-1] if c<=len(kinds) else 'text'))
    if xml:cells.append(xml)
   return f'<row r="{row_index}">'+''.join(cells)+'</row>'
  last_col=_xlsx_col_name(len(headers)); last_row=len(body)+1
  with z.open('xl/worksheets/sheet1.xml','w') as f:
   f.write(f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><dimension ref="A1:{last_col}{last_row}"/><sheetData>'.encode('utf-8'))
   f.write(row_xml(1,headers,head=True).encode('utf-8'))
   for r,row in enumerate(body,2):
    f.write(row_xml(r,row).encode('utf-8')); rows_written+=1
   f.write(b'</sheetData></worksheet>')
 return {'sheet':sheet_name,'rows':rows_written,'columns':len(headers),'cells':cell_count,'elapsed':time.perf_counter()-started}
def verify_xlsx_direct(dst,expected_columns):
 started=time.perf_counter()
 with zipfile.ZipFile(dst,'r') as z:
  bad=z.testzip();names=set(z.namelist());required={'[Content_Types].xml','xl/workbook.xml','xl/worksheets/sheet1.xml'};missing=sorted(required-names)
  head=z.read('xl/worksheets/sheet1.xml')[:65536].decode('utf-8',errors='ignore')
 if bad or missing:raise RuntimeError(f'XLSX ZIP構造検査失敗 bad={bad} missing={missing}')
 m=re.search(r'<row[^>]*r="1"[^>]*>(.*?)</row>',head,re.S); header_columns=len(re.findall(r'<c\b',m.group(1))) if m else 0
 log.info('XLSX_LIGHT_VERIFY_DIRECT header_columns=%s expected_columns=%s elapsed=%.2fs',header_columns,expected_columns,time.perf_counter()-started)
 if header_columns!=expected_columns:raise RuntimeError(f'XLSX列数検査失敗 expected={expected_columns} actual={header_columns}')
 log.info('XLSX_ZIP_TEST bad_entry=%s missing_required=%s entries=%s elapsed=%.2fs',bad,missing,len(names),time.perf_counter()-started)

def verify_xlsx_fast(dst,expected_columns):
 started=time.perf_counter()
 with zipfile.ZipFile(dst,'r') as z:
  names=set(z.namelist());required={'[Content_Types].xml','xl/workbook.xml','xl/worksheets/sheet1.xml'};missing=sorted(required-names)
  if missing:raise RuntimeError(f'XLSX必須XML不足 missing={missing}')
  head=z.read('xl/worksheets/sheet1.xml')[:65536].decode('utf-8',errors='ignore')
 m=re.search(r'<row[^>]*r="1"[^>]*>(.*?)</row>',head,re.S); header_columns=len(re.findall(r'<c\b',m.group(1))) if m else 0
 log.info('XLSX_FAST_VERIFY header_columns=%s expected_columns=%s elapsed=%.2fs',header_columns,expected_columns,time.perf_counter()-started)
 if header_columns!=expected_columns:raise RuntimeError(f'XLSX列数検査失敗 expected={expected_columns} actual={header_columns}')
 return header_columns

