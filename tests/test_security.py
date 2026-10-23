"""脆弱性の確認（2026-10-23）で見つけたもののうち、コードで直したところ（2.5.3）。

・読み込む DLL: 共有（ネットワーク）上・名前だけの指定は読まない。DLL の場所は既定の設定で配らない
・利用者ごとのフォルダー・C:\\ 直下の作業フォルダー: 作るときに本人だけのアクセス権にし、持ち主が違えば知らせる
・置き場の型: 値が .. でも型の外（1つ上）へ書かない
・枠（窓と中身のやり取り）・取り込む ZIP・M の式: 大きさの上限
・画面: ID・予定の種類などをエスケープしてから HTML に入れる。計算列の正規表現で、繰り返しの中の繰り返しを断る
窓（Rust）の直し（file: を外へ渡さない・新しい窓を断る・CSP）は desktop/src の cargo test で確かめる。
実行: python -m unittest tests.test_security -v
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / 'lib')]
import navigator_api as N  # noqa: E402
import navi_bundle  # noqa: E402
import navi_defaults  # noqa: E402
import navi_m as M  # noqa: E402
import navi_mimport  # noqa: E402
import navi_msource  # noqa: E402
import navi_paths  # noqa: E402
import sidecar  # noqa: E402


class DllTest(unittest.TestCase):
    def test_network_and_bare_names_are_refused(self):
        for p in (r'\\srv\share\NAVIAP\SymNaviA.dll', '//srv/share/SymNaviA.dll', r'\\?\UNC\srv\share\SymNaviA.dll'):
            self.assertTrue(N.is_network_path(p), p)
            self.assertIn('共有（ネットワーク）上の DLL は読み込みません', N.dll_refusal(p), p)
        self.assertIn('名前だけの指定は読み込みません', N.dll_refusal('SymNaviA.dll'), '作業フォルダー・PATH から読まれうる')
        for p in (r'C:\NAVIAP\dllVC14x64\SymNaviA.dll', r'\\?\C:\NAVIAP\SymNaviA.dll'):
            self.assertFalse(N.is_network_path(p), p)
            self.assertEqual(N.dll_refusal(p), '', f'手元の DLL は読む: {p}')

    def test_mapped_network_drive_is_refused(self):
        real = N._drive_is_remote
        N._drive_is_remote = lambda d: d.upper() == 'Z:'
        try:
            self.assertIn('共有（ネットワーク）上', N.dll_refusal(r'Z:\Apps\DataRelay\Config\NAVIAP\SymNaviA.dll'), '割り当てたドライブ')
            self.assertEqual(N.dll_refusal(r'C:\NAVIAP\SymNaviA.dll'), '')
        finally:
            N._drive_is_remote = real

    def test_bare_name_is_no_longer_a_candidate(self):
        with tempfile.TemporaryDirectory() as d:
            got = [str(x) for x in N.candidate_dlls(None, [Path(d)], local_root=Path(d) / 'none')]
        self.assertNotIn('SymNaviA.dll', got, '名前だけの候補（Windows の探し方に任せる）を最後に足さない')

    def test_dll_location_is_not_handed_out_by_defaults(self):
        for k in ('navigator_api_dll', 'navigator_api_search_roots'):
            self.assertNotIn(k, navi_defaults.COMMON_KEYS, f'{k} を置き場の既定の設定で配らない（全員の DLL を差し替えられる）')


class PrivateDirTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.real = (navi_paths._run, navi_paths.my_sid, navi_paths.owner_sid)
        navi_paths._run = lambda args: self.calls.append(args) or subprocess.CompletedProcess(args, 0, '処理済み', '')
        navi_paths.my_sid = lambda: 'S-1-5-21-1'
        navi_paths.PRIVATE_NOTES.clear()

    def tearDown(self):
        navi_paths._run, navi_paths.my_sid, navi_paths.owner_sid = self.real
        navi_paths.PRIVATE_NOTES.clear()

    def test_new_folder_is_made_private(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'users' / 'sato'
            navi_paths.ensure_private_dir(p, windows=True)
            self.assertTrue(p.is_dir())
        self.assertEqual(len(self.calls), 1)
        args = self.calls[0]
        self.assertEqual(args[:4], ['icacls', str(p), '/inheritance:r', '/grant:r'], '親からの引き継ぎを切って付け直す')
        self.assertEqual(args[4:], ['*S-1-5-21-1:(OI)(CI)F', '*S-1-5-18:(OI)(CI)F', '*S-1-5-32-544:(OI)(CI)F'],
                         '本人・SYSTEM・Administrators だけ')
        self.assertIn('本人だけのアクセス権にしました', navi_paths.PRIVATE_NOTES[0][1])

    def test_existing_folder_owned_by_someone_else_is_reported_not_changed(self):
        navi_paths.owner_sid = lambda p: 'S-1-5-21-999'
        with tempfile.TemporaryDirectory() as d:
            navi_paths.ensure_private_dir(Path(d), windows=True)
        self.assertEqual(self.calls, [], 'すでにあるフォルダーのアクセス権は変えない（管理者が先に作った場合もある）')
        self.assertIn('持ち主が本人ではありません', navi_paths.PRIVATE_NOTES[0][1])

    def test_own_existing_folder_is_quiet_and_other_os_does_nothing(self):
        navi_paths.owner_sid = lambda p: 'S-1-5-21-1'
        with tempfile.TemporaryDirectory() as d:
            navi_paths.ensure_private_dir(Path(d), windows=True)
            navi_paths.ensure_private_dir(Path(d) / 'new', windows=False)
            self.assertTrue((Path(d) / 'new').is_dir())
        self.assertEqual((self.calls, navi_paths.PRIVATE_NOTES), ([], []))

    def test_failure_is_reported(self):
        navi_paths._run = lambda args: subprocess.CompletedProcess(args, 5, '', 'アクセスが拒否されました')
        with tempfile.TemporaryDirectory() as d:
            navi_paths.ensure_private_dir(Path(d) / 'x', windows=True)
        self.assertIn('本人だけのアクセス権にできませんでした（アクセスが拒否されました）', navi_paths.PRIVATE_NOTES[0][1])


# 置き場の型（値ごとに分けて出す）: 値が .. でも、型の外へ出ない
TEMPLATE = r"""
import json,sys
sys.path[:0]=[sys.argv[1],sys.argv[1]+'/lib']
import app
out={v:app.render_path_template(r'D:\出力\{値}',job={'_variant_value':v}) for v in ['..','.',' . ','LS4','a.b','..x']}
print(json.dumps(out,ensure_ascii=False))
"""


class PathTemplateTest(unittest.TestCase):
    def test_dot_values_stay_inside(self):
        with tempfile.TemporaryDirectory() as d:
            env = dict(os.environ, NAVI_LOCAL_ROOT=str(Path(d) / 'local'), NAVI_DATA_ROOT=str(Path(d) / 'data'),
                       NAVI_CONFIG_DIR=str(Path(d) / 'data' / 'Config'), NAVI_SECRET_FILE=str(Path(d) / 'local' / 's.json'),
                       DATARELAY_NO_BOOT='1', PYTHONIOENCODING='utf-8')
            r = subprocess.run([sys.executable, '-c', TEMPLATE, str(ROOT)], env=env, capture_output=True, text=True,
                               encoding='utf-8', timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        got = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(got['..'], r'D:\出力\_', '.. は 1つ上のフォルダーになるので _ にする')
        self.assertEqual((got['.'], got[' . ']), (r'D:\出力\_', r'D:\出力\_'))
        self.assertEqual((got['LS4'], got['a.b'], got['..x']), (r'D:\出力\LS4', r'D:\出力\a.b', r'D:\出力\..x'), 'ふつうの値はそのまま')


class FrameTest(unittest.TestCase):
    def test_bad_frames_are_errors_not_huge_reads(self):
        with self.assertRaises(ValueError):
            sidecar.read_frame(io.BytesIO(json.dumps({'len': sidecar.MAX_BODY + 1}).encode() + b'\n'))
        with self.assertRaises(ValueError):
            sidecar.read_frame(io.BytesIO(b'{"len":-5}\n'))
        with self.assertRaises(ValueError):
            sidecar.read_frame(io.BytesIO(b'[1,2]\n'))
        with self.assertRaises(ValueError):
            sidecar.read_frame(io.BytesIO(b'x' * (sidecar.MAX_HEAD + 5)))
        self.assertEqual(sidecar.read_frame(io.BytesIO(b'{"len":3,"id":1}\nabc')), ({'len': 3, 'id': 1}, b'abc'))


class SizeLimitTest(unittest.TestCase):
    def ev(self, src, **kw):
        return M.force(M.Document.from_text(src).evaluate(host_=M.Host(**kw)))

    def test_m_functions_refuse_huge_values(self):
        for src in ('Text.Repeat("x", 1000000000)', 'List.Repeat({1,2}, 100000000)', 'List.Numbers(1, 100000000)',
                    'Text.PadStart("a", 1000000000)', 'Text.PadEnd("a", 1000000000)'):
            with self.assertRaises(M.MError, msg=src) as e:
                self.ev(src)
            self.assertIn('大きすぎます', str(e.exception))
        self.assertEqual(self.ev('Text.Repeat("ab", 3)'), 'ababab')
        self.assertEqual(self.ev('List.Repeat({1}, 3)'), [1, 1, 1])
        self.assertEqual(self.ev('Text.PadStart("7", 3, "0")'), '007')

    def test_folder_files_stops_at_the_cap(self):
        real = navi_msource.FOLDER_FILES_MAX
        navi_msource.FOLDER_FILES_MAX = 3
        try:
            with tempfile.TemporaryDirectory() as d:
                for i in range(5):
                    Path(d, f'{i}.csv').write_text('a', encoding='utf-8')
                with self.assertRaises(M.MError) as e:
                    self.ev(f'Folder.Files("{Path(d).as_posix()}")')
            self.assertIn('件を超えました', str(e.exception))
        finally:
            navi_msource.FOLDER_FILES_MAX = real

    def test_zip_parts_over_the_limit_are_refused(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr(navi_bundle.PART_FILE[next(iter(navi_bundle.PART_FILE))], b'0' * 5000)
        real = navi_bundle.ZIP_PART_MAX
        navi_bundle.ZIP_PART_MAX = 1000
        try:
            out, _, bad = navi_bundle.read_zip(buf.getvalue())
        finally:
            navi_bundle.ZIP_PART_MAX = real
        self.assertEqual(out, {})
        self.assertTrue(any('大きすぎます' in x for x in bad), bad)
        with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as z:
            real = navi_mimport.ZIP_PART_MAX
            navi_mimport.ZIP_PART_MAX = 1000
            try:
                with self.assertRaises(ValueError):
                    navi_mimport._read_part(z, z.namelist()[0])
            finally:
                navi_mimport.ZIP_PART_MAX = real


class ScreenTest(unittest.TestCase):
    def test_ids_and_types_are_escaped(self):
        js = (ROOT / 'static' / 'app.js').read_text(encoding='utf-8')
        raw = re.findall(r'"\$\{[a-z]\.(?:id|job_id)\}"', js)
        self.assertEqual(raw, [], 'ID を HTML の属性へ、E() を通さずに入れない')
        self.assertNotRegex(js, r'\$\{typeName\(', '予定の種類（知らない値はそのまま返す）も E() を通す')
        self.assertIn('data-iso="${E(x)}">${E(x)}', js)

    @unittest.skipUnless(shutil.which('node'), 'node がありません')
    def test_nested_quantifier_regex_is_refused(self):
        model = ROOT / 'static' / 'viewer-model.js'
        code = (f"const M=require({json.dumps(str(model))});const out={{}};"
                "for(const s of ['match([a],\"(a+)+$\")','extract([a],\"(\\\\w*)*x\")','match([a],\"^(\\\\d{4})-(\\\\d{2})$\")']){"
                "try{out[s]=String(M.compile(s).run(n=>'2026-10'))}catch(e){out[s]='ERR:'+e.message}}"
                "console.log(JSON.stringify(out))")
        r = subprocess.run(['node', '-e', code], capture_output=True, text=True, encoding='utf-8', timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        vals = list(got.values())
        self.assertIn('繰り返しの中に繰り返し', vals[0])
        self.assertIn('繰り返しの中に繰り返し', vals[1])
        self.assertNotIn('繰り返しの中に繰り返し', vals[2], 'ふつうの正規表現は使える')


if __name__ == '__main__':
    unittest.main()
