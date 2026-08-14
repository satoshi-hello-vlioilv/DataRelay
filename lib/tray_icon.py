"""通知領域（タスクバー右側）常駐アイコン。

ブラウザーのタブを閉じても自動実行の予定・実行キューが残っている場合、アプリは常駐を続ける。
その際に「動いていることが見えない」「止める手段が無い」状態にならないよう、
通知領域へアイコンを出し、そこから画面を開く／終了できるようにする。

Windows専用。pywin32（既存の依存関係）のみを使い、追加パッケージは不要。
利用できない環境では常駐アイコンなしで従来どおり動作する（アプリは止めない）。
"""
from __future__ import annotations
import os, threading

WM_TRAY = 0x0400 + 20          # WM_APP相当。トレイからの通知を受け取る独自メッセージ。
ID_OPEN, ID_STATUS, ID_EXIT = 1001, 1002, 1003


class TrayIcon:
    def __init__(self, app_name, url, icon_path=None, on_open=None, on_exit=None, status_text=None, logger=None):
        self.app_name = app_name
        self.url = url
        self.icon_path = icon_path
        self.on_open = on_open
        self.on_exit = on_exit
        self.status_text = status_text or (lambda: '')
        self.log = logger
        self.hwnd = None
        self._thread = None
        self._ready = threading.Event()
        self.available = False

    # ---- 生成・破棄 -----------------------------------------------------
    def start(self):
        if os.name != 'nt':
            self._note('TRAY_SKIP reason=not_windows')
            return False
        try:
            import win32gui  # noqa: F401  (存在確認のみ)
        except Exception as e:
            self._note('TRAY_SKIP reason=pywin32_unavailable detail=%s' % e)
            return False
        self._thread = threading.Thread(target=self._run, daemon=True, name='tray-icon')
        self._thread.start()
        self._ready.wait(timeout=5)
        return self.available

    def stop(self):
        if not self.hwnd:
            return
        try:
            import win32gui
            win32gui.PostMessage(self.hwnd, 0x0010, 0, 0)  # WM_CLOSE
        except Exception:
            pass

    def notify(self, title, message):
        """バルーン通知。常駐へ切り替わったことをユーザーへ知らせる。"""
        if not self.hwnd:
            return
        try:
            import win32gui
            win32gui.Shell_NotifyIcon(1, (  # NIM_MODIFY
                self.hwnd, 0, win32gui.NIF_INFO, WM_TRAY, self._hicon(),
                self._tip(), message, 10000, title, 0x00000001))  # NIIF_INFO
        except Exception as e:
            self._note('TRAY_NOTIFY_FAILED detail=%s' % e)

    def refresh_tooltip(self):
        if not self.hwnd:
            return
        try:
            import win32gui
            win32gui.Shell_NotifyIcon(1, (self.hwnd, 0, win32gui.NIF_TIP, WM_TRAY, self._hicon(), self._tip()))
        except Exception:
            pass

    # ---- 内部 -----------------------------------------------------------
    def _note(self, message):
        if self.log:
            try:
                self.log.info(message)
            except Exception:
                pass

    def _tip(self):
        # ツールチップは64文字までに切り詰める（超過すると表示されない環境がある）。
        text = '%s\n%s' % (self.app_name, self.status_text() or '')
        return text.strip()[:63]

    def _hicon(self):
        return getattr(self, '_icon_handle', 0)

    def _load_icon(self):
        import win32api, win32con, win32gui
        if self.icon_path and os.path.isfile(self.icon_path):
            try:
                return win32gui.LoadImage(0, str(self.icon_path), win32con.IMAGE_ICON, 0, 0,
                                          win32con.LR_LOADFROMFILE | win32con.LR_DEFAULTSIZE)
            except Exception as e:
                self._note('TRAY_ICON_LOAD_FAILED path=%s detail=%s' % (self.icon_path, e))
        return win32gui.LoadIcon(0, win32con.IDI_APPLICATION)

    def _run(self):
        try:
            import win32api, win32con, win32gui
            wc = win32gui.WNDCLASS()
            wc.hInstance = win32api.GetModuleHandle(None)
            wc.lpszClassName = 'SymfoNaviDataHubTray'
            wc.lpfnWndProc = {
                win32con.WM_DESTROY: self._on_destroy,
                win32con.WM_COMMAND: self._on_command,
                WM_TRAY: self._on_tray,
            }
            try:
                win32gui.UnregisterClass(wc.lpszClassName, wc.hInstance)
            except Exception:
                pass
            atom = win32gui.RegisterClass(wc)
            self.hwnd = win32gui.CreateWindow(atom, self.app_name, win32con.WS_OVERLAPPED,
                                              0, 0, 0, 0, 0, 0, wc.hInstance, None)
            win32gui.UpdateWindow(self.hwnd)
            self._icon_handle = self._load_icon()
            win32gui.Shell_NotifyIcon(0, (  # NIM_ADD
                self.hwnd, 0, win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP,
                WM_TRAY, self._icon_handle, self._tip()))
            self.available = True
            self._note('TRAY_READY hwnd=%s' % self.hwnd)
            self._ready.set()
            win32gui.PumpMessages()
        except Exception as e:
            self._note('TRAY_START_FAILED detail=%s' % e)
            self._ready.set()

    def _on_destroy(self, hwnd, msg, wparam, lparam):
        try:
            import win32gui
            win32gui.Shell_NotifyIcon(2, (hwnd, 0))  # NIM_DELETE
            win32gui.PostQuitMessage(0)
        except Exception:
            pass
        return 0

    def _on_tray(self, hwnd, msg, wparam, lparam):
        import win32con, win32gui
        if lparam == win32con.WM_LBUTTONDBLCLK:
            self._invoke(self.on_open)
        elif lparam == win32con.WM_RBUTTONUP:
            self._show_menu(hwnd)
        return 0

    def _show_menu(self, hwnd):
        import win32con, win32gui
        menu = win32gui.CreatePopupMenu()
        win32gui.AppendMenu(menu, win32con.MF_STRING, ID_OPEN, '画面を開く(&O)')
        win32gui.AppendMenu(menu, win32con.MF_STRING | win32con.MF_GRAYED, ID_STATUS, self.status_text() or '状態を取得中')
        win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, '')
        win32gui.AppendMenu(menu, win32con.MF_STRING, ID_EXIT, 'アプリを終了(&X)')
        pos = win32gui.GetCursorPos()
        win32gui.SetForegroundWindow(hwnd)   # メニュー外クリックで閉じるために必要。
        win32gui.TrackPopupMenu(menu, win32con.TPM_LEFTALIGN, pos[0], pos[1], 0, hwnd, None)
        win32gui.PostMessage(hwnd, win32con.WM_NULL, 0, 0)
        win32gui.DestroyMenu(menu)

    def _on_command(self, hwnd, msg, wparam, lparam):
        import win32api
        item = win32api.LOWORD(wparam)
        if item == ID_OPEN:
            self._invoke(self.on_open)
        elif item == ID_EXIT:
            self._invoke(self.on_exit)
        return 0

    def _invoke(self, fn):
        if not fn:
            return
        # メッセージループを止めないよう、実処理は別スレッドで行う。
        threading.Thread(target=self._safe, args=(fn,), daemon=True, name='tray-action').start()

    def _safe(self, fn):
        try:
            fn()
        except Exception as e:
            self._note('TRAY_ACTION_FAILED detail=%s' % e)
