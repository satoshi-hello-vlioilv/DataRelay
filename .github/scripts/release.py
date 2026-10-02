"""main に入った版を配る形にする（.github/workflows/desktop.yml の release から呼ぶ）。

  python .github/scripts/release.py package --exe DataRelay.exe --out out [--ref HEAD]
    out/DataRelay.zip … アプリのフォルダー一式（DataRelay/ の下）＋ DataRelay.exe。展開すればそのまま動く
    out/DataRelay.exe … exe だけを差し替えたいとき用
    out/notes.md      … Release の本文（更新履歴のいまの版）
    標準出力の最後の行に version=… を出す（GITHUB_OUTPUT へ足す）

zip の中身は git archive に任せる。入れないものは .gitattributes の export-ignore にだけ書く
（ここで別に並べると、片方だけ直して食い違う）。ファイル名に版を入れないのは、
「最新版」のダウンロード先（releases/latest/download/DataRelay.zip）をいつも同じにするため。
"""
import argparse,html,re,shutil,subprocess,sys,zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
PREFIX='DataRelay/'


def version_info():
 sys.path.insert(0,str(ROOT/'lib'))
 import navi_version,navi_changelog
 entry=next((x for x in navi_changelog.CHANGELOG if x['version']==navi_version.APP_VERSION),None)
 return navi_version.APP_VERSION,navi_version.APP_VERSION_TITLE,navi_version.APP_RELEASED_AT,entry


def to_markdown(text):
 """更新履歴の1項目（画面用の HTML の断片）を Markdown にする。<b>→太字・<code>→コード、ほかのタグは外す。

 >>> to_markdown('<b>exe</b> と <code>&lt;PC&gt;</code>・&lt;PC&gt;')
 '**exe** と `<PC>`・&lt;PC&gt;'
 """
 text=re.sub(r'</?b>','**',text)
 text=re.sub(r'</?code>','`',text)
 text=re.sub(r'<br\s*/?>',' ',text)
 text=re.sub(r'<[^>]+>','',text)
 # &lt;PC&gt; などは文字として残す。コードの外で生の < を出すと、GitHub が HTML のタグとして扱って消してしまう
 parts=html.unescape(text).split('`')
 return '`'.join(x if i%2 else x.replace('<','&lt;').replace('>','&gt;') for i,x in enumerate(parts)).strip()


def notes(version,title,released,entry,sha):
 lines=[f'## {version} {title}','',f'リリース日: {released or "（記録なし）"}　／　作ったコミット: {sha[:12]}','',
        '**配り方**: `DataRelay.zip` を展開したフォルダーごと置き、`DataRelay.exe` をダブルクリックします。'
        'exe だけを差し替えるときは、窓を閉じて（通知領域の「終了」まで）から `DataRelay.exe` を置き換えます。','']
 for n in (entry or {}).get('notes',[]):lines+=[f'- {to_markdown(n)}']
 return '\n'.join(lines)+'\n'


def package(exe,out,ref='HEAD'):
 out.mkdir(parents=True,exist_ok=True)
 z=out/'DataRelay.zip'
 subprocess.run(['git','-C',str(ROOT),'archive','--format=zip',f'--prefix={PREFIX}','-o',str(z.resolve()),ref],check=True)
 with zipfile.ZipFile(z,'a',zipfile.ZIP_DEFLATED) as f:f.write(exe,PREFIX+'DataRelay.exe')
 shutil.copyfile(exe,out/'DataRelay.exe')
 version,title,released,entry=version_info()
 sha=subprocess.run(['git','-C',str(ROOT),'rev-parse',ref],check=True,capture_output=True,text=True).stdout.strip()
 (out/'notes.md').write_text(notes(version,title,released,entry,sha),encoding='utf-8')
 return version,title


def main():
 ap=argparse.ArgumentParser();sub=ap.add_subparsers(dest='cmd',required=True)
 p=sub.add_parser('package');p.add_argument('--exe',required=True,type=Path);p.add_argument('--out',required=True,type=Path);p.add_argument('--ref',default='HEAD')
 a=ap.parse_args()
 version,title=package(a.exe,a.out,a.ref)
 print(f'title=v{version} {title}')
 print(f'version={version}')
 return 0


if __name__=='__main__':sys.exit(main())
