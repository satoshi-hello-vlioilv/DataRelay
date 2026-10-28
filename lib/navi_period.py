"""抽出期間（処理日時を基準にした相対の期間）の決まり（2.14.0 で条件欄の日付と、以降・以前を足した）。

期間を当てる先は2通り:
・point = RNE の時間型の管理ポイント（NaviChangePeriod）。両端が要るので、範囲の形は「期間（〜から〜まで）」だけ
・cond  = 条件欄の日付の項目（NaviChangeConditionDI の範囲指定）。時間型の管理ポイントが無い RNE で、
          条件欄に日付を直接入れてある形（例: 払出日: 2026/1/1 -->）に使う。「期間」「以降」「以前」を選べる

日付の書き方は、RNE に入っている日付（読み出した値）と同じ形にそろえる（例: 2026/1/1 → 2026/7/27）。
月を単位にするとき、条件欄の日付は「始まりの月の1日」〜「終わりの月の末日」にする。
画面にも中身にも出てこない決まりはここに置き、app.py と navi_web.py はここを呼ぶ。
"""
import calendar
import re
from datetime import date, datetime, timedelta

TARGETS=('point','cond')
RANGES=('between','from','to')     # 期間（〜から〜まで）・以降（〜から）・以前（〜まで）
RANGE_LABEL={'between':'期間','from':'以降','to':'以前'}
UNITS=('month','day')
_DATE=re.compile(r'^\s*(\d{4})([/\-.]?)(\d{1,2})\2(\d{1,2})')


def _int(v,default=0):
 try:return int(v)
 except (TypeError,ValueError):return default


def normalize(d):
 """保存の形にそろえる。昔の保存（target・range が無い）は「管理ポイント・期間」として読む。"""
 d=d if isinstance(d,dict) else {}
 target=d.get('target') if d.get('target') in TARGETS else 'point'
 rng=d.get('range') if d.get('range') in RANGES else 'between'
 if target=='point':rng='between'   # NaviChangePeriod は両端が要る
 return {'enabled':bool(d.get('enabled',False)),'target':target,
         'control_point':str(d.get('control_point') or '').strip(),'cond_item':str(d.get('cond_item') or '').strip(),
         'range':rng,'unit':d.get('unit') if d.get('unit') in UNITS else 'month',
         'from_offset':_int(d.get('from_offset')),'to_offset':_int(d.get('to_offset'))}


def add_months(year,month,delta):
 idx=year*12+(month-1)+int(delta);return idx//12,idx%12+1


def parse_date(s):
 """'2026/1/1'・'2026-01-01'・'20260101'（後ろに時刻があってもよい）を日付にする。読めなければ None。"""
 m=_DATE.match(str(s or ''))
 if not m:return None
 try:return date(int(m.group(1)),int(m.group(3)),int(m.group(4)))
 except ValueError:return None


def format_like(sample,d):
 """sample と同じ書き方で d を書く。区切り（/ - . なし）と、月日の0埋めを sample に合わせる。sample が日付でなければ 2026/1/1 の形。"""
 m=_DATE.match(str(sample or ''))
 if not m:return f'{d.year}/{d.month}/{d.day}'
 sep=m.group(2);pad=(len(m.group(3))==2 and len(m.group(4))==2) or not sep
 return f'{d.year}{sep}{d.month:02d}{sep}{d.day:02d}' if pad else f'{d.year}{sep}{d.month}{sep}{d.day}'


def cond_dates(period,now):
 """条件欄の日付の両端（date）。月を単位にすると、始まりは月の1日・終わりは月の末日。"""
 fo,to=period['from_offset'],period['to_offset']
 if period['unit']=='month':
  fy,fm=add_months(now.year,now.month,fo);ty,tm=add_months(now.year,now.month,to)
  return date(fy,fm,1),date(ty,tm,calendar.monthrange(ty,tm)[1])
 return now.date()+timedelta(days=fo),now.date()+timedelta(days=to)


def summary(period,lo,hi):
 """画面と記録に出す一言。"""
 r=period['range']
 if r=='from':return f'{lo} 以降'
 if r=='to':return f'{hi} 以前'
 return f'{lo} ～ {hi}'


def compute(period,now=None,sample=''):
 """期間を計算する。無効なら None。

 point → {'kind':'point','condition':0（月度）/1（年月日）,'from_time','to_time',…}（NaviChangePeriod へ渡す形）
 cond  → {'kind':'cond','range':'between'/'from'/'to','lvalue','rvalue',…}（日付は sample の書き方）
 """
 p=normalize(period);now=now or datetime.now()
 if not p['enabled']:return None
 base={'unit':p['unit'],'from_offset':p['from_offset'],'to_offset':p['to_offset'],'range':p['range']}
 if p['target']=='cond':
  fd,td=cond_dates(p,now)
  if p['range']=='between' and fd>td:fd,td=td,fd
  lo=format_like(sample,fd) if p['range']!='to' else '';hi=format_like(sample,td) if p['range']!='from' else ''
  return {**base,'kind':'cond','item':p['cond_item'],'lvalue':lo,'rvalue':hi,'from_date':fd.isoformat(),'to_date':td.isoformat(),
          'summary':summary(p,lo,hi)}
 if p['unit']=='month':
  fy,fm=add_months(now.year,now.month,p['from_offset']);ty,tm=add_months(now.year,now.month,p['to_offset'])
  return {**base,'kind':'point','condition':0,'from_time':f'{fy:04d}{fm:02d}00','to_time':f'{ty:04d}{tm:02d}00',
          'summary':f'{fy}年{fm}月度 ～ {ty}年{tm}月度'}
 fd,td=now.date()+timedelta(days=p['from_offset']),now.date()+timedelta(days=p['to_offset'])
 return {**base,'kind':'point','condition':1,'from_time':fd.strftime('%Y%m%d'),'to_time':td.strftime('%Y%m%d'),
         'summary':f'{fd:%Y-%m-%d} ～ {td:%Y-%m-%d}'}


def cond_readback(spec,got):
 """条件欄の日付を読み戻した値（navigator_api.get_condition_di の戻り値）を、頼んだ期間と比べる。
 → 'match'／'differs'／'unknown'（読めない）。日付として比べる（書き方の違い 2026/7/1 と 2026/07/01 は同じ）。"""
 if not got:return 'unknown'
 want=(parse_date(spec.get('lvalue')),parse_date(spec.get('rvalue')))
 have=(parse_date(got.get('lvalue')),parse_date(got.get('rvalue')))
 r=spec.get('range')
 if r=='from':return 'match' if have[0] and have[0]==want[0] else ('unknown' if not got.get('lvalue') else 'differs')
 if r=='to':return 'match' if have[1] and have[1]==want[1] else ('unknown' if not got.get('rvalue') else 'differs')
 if have[0] is None and have[1] is None:return 'unknown'
 return 'match' if have==want else 'differs'
