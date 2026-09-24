"""Kaperio: local file recovery and conversion workbench."""
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import secrets
import shutil
import ssl
import ipaddress
import subprocess
import threading
import time
import uuid
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

from pypdf import PdfReader

from pdf_tools import export_pdf, preview_png
from recovery import CREATE_FLAGS, run_hashcat, validate_plan, write_inputs
from formats import SUPPORTED, contents, get_hash, inspect_file, unlock_file, office_renderer, render_office, discover_zip2john
from runtime import APP_DIR, VERSION, data_directory

DEFAULT_DATA = data_directory()
BUSY = {'queued', 'recovering', 'pausing', 'converting', 'unlocking'}
MAX_UPLOAD = 100 * 1024 * 1024


def acquire_instance(root):
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    handle = (root / 'instance.lock').open('a+b')
    handle.seek(0, 2)
    if handle.tell() == 0:
        handle.write(b'0')
        handle.flush()
    handle.seek(0)
    try:
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return handle
    except OSError:
        handle.close()
        return None


def filename(value):
    value = Path(value.replace('\\', '/')).name
    value = ''.join('_' if c in '<>:"/\\|?*' or ord(c) < 32 else c for c in value)
    return value[:160].strip(' .') or 'document.pdf'


class Library:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.jobs = {}
        self.stops = {}
        self.passwords = {}
        self.recovery_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='hashcat')
        self.export_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='export')
        self.hashcat = self.discover_hashcat()
        config = self.root / 'settings.json'
        try:
            settings = json.loads(config.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            settings = {}
        self.zip2john = discover_zip2john(settings.get('zip2john'))
        for path in self.root.glob('*/job.json'):
            try:
                job = json.loads(path.read_text(encoding='utf-8'))
                if job['id'] != path.parent.name:
                    continue
                if job['state'] in BUSY:
                    job['state'] = 'ready' if job.get('unlocked') else 'paused' if job.get('plan') else 'locked'
                    job['message'] = '前回の処理が中断されました。'
                self.jobs[job['id']] = job
                self.stops[job['id']] = threading.Event()
            except (OSError, ValueError, KeyError):
                continue

    def discover_hashcat(self):
        config = self.root / 'settings.json'
        if config.exists():
            try:
                candidate = Path(json.loads(config.read_text(encoding='utf-8'))['hashcat'])
                if candidate.is_file():
                    return candidate.resolve()
            except (ValueError, KeyError):
                pass
        candidates = [os.environ.get('KAPERIO_HASHCAT', ''),
                      shutil.which('hashcat') or '',
                      APP_DIR.parent / 'work' / 'tools' / 'hashcat-7.1.2' / ('hashcat.exe' if os.name == 'nt' else 'hashcat.bin')]
        return next((Path(x).resolve() for x in candidates if x and Path(x).is_file()), None)

    def folder(self, job_id):
        if job_id not in self.jobs:
            raise ValueError('ファイルが見つかりません。')
        return self.root / job_id

    def save(self, job):
        with self.lock:
            path = self.folder(job['id']) / 'job.json'
            temp = path.with_suffix('.tmp')
            temp.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding='utf-8')
            temp.replace(path)

    def update(self, job_id, **fields):
        with self.lock:
            job = self.jobs[job_id]
            warning = fields.pop('warning', None)
            if warning and warning not in job['warnings']:
                job['warnings'].append(warning)
            job.update(fields)
            self.save(job)

    def snapshot(self):
        with self.lock:
            result = []
            for job in sorted(self.jobs.values(), key=lambda j: j['created'], reverse=True):
                public = {k: v for k, v in job.items() if k not in {'plan', 'unlocked'}}
                public['available'] = bool(job.get('unlocked'))
                public['has_password'] = job['id'] in self.passwords
                public['checkpoint'] = (self.folder(job['id']) / 'session.restore').exists()
                public['can_resume'] = bool(job.get('plan')) and not job.get('unlocked')
                public['has_pdf'] = bool(job.get('unlocked') and (job['info']['format'] == 'pdf' or job.get('rendered')))
                public['can_convert'] = job['info']['format'] == 'pdf' or (job['info']['format'] == 'office' and office_renderer(job['info']['extension']))
                result.append(public)
            return json.loads(json.dumps(result))

    def import_pdf(self, name, content):
        extension = Path(name).suffix.lower()
        if extension not in SUPPORTED:
            raise ValueError('対応形式はPDF、Excel、PowerPoint、Word、ZIPです。')
        digest = hashlib.sha256(content).hexdigest()
        with self.lock:
            for job in self.jobs.values():
                if job['sha256'] == digest:
                    return job['id']
            job_id = uuid.uuid4().hex
            folder = self.root / job_id
            folder.mkdir()
            source = folder / ('source' + extension)
            source.write_bytes(content)
            try:
                info = inspect_file(source, extension, self.zip2john)
            except Exception as exc:
                source.unlink(missing_ok=True)
                folder.rmdir()
                raise ValueError('ファイルを読み取れませんでした: ' + str(exc))
            job = {'id': job_id, 'name': filename(name), 'sha256': digest, 'size': len(content),
                   'created': time.time(), 'state': 'locked', 'info': info, 'outputs': [],
                   'warnings': [], 'message': '', 'metrics': {}, 'unlocked': None,
                   'source': source.name}
            self.jobs[job_id] = job
            self.stops[job_id] = threading.Event()
            if info['empty_password']:
                self._unlock(job_id, '')
            self.save(job)
            return job_id

    def add_output(self, job_id, path, kind):
        job = self.jobs[job_id]
        job['outputs'] = [o for o in job['outputs'] if o['file'] != path.name]
        job['outputs'].append({'file': path.name, 'kind': kind, 'bytes': path.stat().st_size,
                               'created': time.time()})

    def _unlock(self, job_id, password):
        folder = self.folder(job_id)
        job = self.jobs[job_id]
        target = folder / ('unlocked' + job['info']['extension'])
        pages = unlock_file(folder / job['source'], password, target, job['info'])
        with self.lock:
            job['info']['pages'] = pages
            job['unlocked'] = target.name
            self.add_output(job_id, target, 'unlocked')
            if password:
                self.passwords[job_id] = password.decode('utf-8', errors='replace') if isinstance(password, bytes) else password
            if job['info']['format'] != 'pdf':
                job['contents'] = contents(target, job['info'])
            self.update(job_id, state='ready', message='パスワードなしのファイルを保存しました。')

    def known_password(self, job_id, password):
        with self.lock:
            job = self.jobs[job_id]
            if job['state'] in BUSY:
                raise ValueError('実行中の処理が完了してから操作してください。')
            previous = job['state']
            self.update(job_id, state='unlocking', message='パスワードを照合しています。')
        try:
            self._unlock(job_id, password)
        except Exception:
            self.update(job_id, state=previous)
            raise

    def start_recovery(self, job_id, data, resume=False):
        with self.lock:
            job = self.jobs[job_id]
            if job['state'] in BUSY or job.get('unlocked'):
                raise ValueError('このファイルでは探索を開始できません。')
            if not self.hashcat:
                raise ValueError('設定でHashcatの実行ファイルを指定してください。')
            if not job['info']['recoverable']:
                raise ValueError('この暗号方式の復元には対応していません。')
            folder = self.folder(job_id)
            if resume:
                if not job.get('plan'):
                    raise ValueError('再開できる探索がありません。')
                plan = dict(job['plan'])
                if plan['strategy'] == 'dictionary':
                    plan['words'] = [bytes.fromhex(s).decode('utf-8') for s in (folder / 'candidates.hex').read_text().splitlines()]
            else:
                plan = validate_plan(data)
                (folder / 'session.restore').unlink(missing_ok=True)
            hash_value, mode = get_hash(folder / job['source'], job['info'], self.hashcat, self.zip2john)
            (folder / 'source.hash').write_text(hash_value + '\n', encoding='ascii')
            write_inputs(folder, plan)
            stop = threading.Event()
            self.stops[job_id] = stop
            self.update(job_id, state='queued', message='探索待ちです。', metrics={}, warnings=[],
                        plan={k: v for k, v in plan.items() if k != 'words'}, candidates=plan['candidates'])
            self.recovery_pool.submit(self._recover, job_id, mode, plan, resume, stop)

    def _recover(self, job_id, mode, plan, resume, stop):
        with self.lock:
            if stop.is_set():
                return
            self.update(job_id, state='recovering', message='Hashcatを初期化しています。')
        try:
            result = run_hashcat(self.hashcat, self.folder(job_id), mode, plan, stop,
                                 lambda **kw: self.update(job_id, **kw), resume)
            if result['state'] == 'found':
                self._unlock(job_id, result['password'])
                (self.folder(job_id) / 'candidates.hex').unlink(missing_ok=True)
            elif self.jobs[job_id].get('cancel_requested'):
                self.update(job_id, state='cancelled', message='探索を中止しました。')
            elif result['state'] == 'exhausted':
                self.update(job_id, state='exhausted', message='指定した候補内には見つかりませんでした。条件を変更できます。')
            else:
                message = '探索を停止しました。'
                if result.get('reason') == 'time_limit':
                    message = '時間上限に達したため停止しました。'
                message += ' 保存地点から再開できます。' if result.get('checkpoint') else ' 保存地点がないため、再開時は候補の最初から探索します。'
                self.update(job_id, state='paused', message=message)
        except Exception as exc:
            self.update(job_id, state='error', message=str(exc))
        finally:
            self.update(job_id, cancel_requested=False)

    def stop(self, job_id, cancel=False):
        with self.lock:
            job = self.jobs[job_id]
            if job['state'] not in {'queued', 'recovering', 'pausing', 'converting'}:
                raise ValueError('実行中の処理がありません。')
            self.stops[job_id].set()
            state = 'cancelled' if cancel else 'paused'
            if job['state'] == 'queued':
                self.update(job_id, state=state, message='待機を解除しました。')
            else:
                self.update(job_id, state='pausing', cancel_requested=cancel, message='停止処理中です。')

    def start_export(self, job_id, data):
        with self.lock:
            job = self.jobs[job_id]
            if job['state'] in BUSY or not job.get('unlocked'):
                raise ValueError('先にファイルを開封してください。')
            if job['info']['format'] == 'zip':
                raise ValueError('ZIPは解除済みZIPとして保存できます。')
            kind = data.get('kind')
            if kind not in {'pdf', 'image_pdf', 'images', 'word', 'text'}:
                raise ValueError('出力形式が不正です。')
            dpi = int(data.get('dpi', 200))
            if dpi not in (100, 150, 200, 300):
                raise ValueError('解像度が範囲外です。')
            self.stops[job_id].clear()
            self.update(job_id, state='converting', message='書き出しを準備しています。', export_progress=0)
            self.export_pool.submit(self._export, job_id, kind, dpi, bool(data.get('grayscale', False)))

    def _export(self, job_id, kind, dpi, gray):
        folder = self.folder(job_id)
        names = {'pdf': 'rendered.pdf', 'image_pdf': 'image.pdf', 'images': 'pages.zip', 'word': 'pages.docx', 'text': 'text.md'}
        target = folder / names[kind]
        try:
            job = self.jobs[job_id]
            source = folder / 'unlocked.pdf'
            if job['info']['format'] == 'office':
                source = folder / 'rendered.pdf'
                if not source.exists():
                    self.update(job_id, message='Microsoft OfficeでPDFを生成しています。')
                    pages = render_office(folder / job['unlocked'], source, self.stops[job_id].is_set)
                    with self.lock:
                        job['info']['pages'] = pages
                        job['rendered'] = source.name
                        self.add_output(job_id, source, 'pdf')
            if kind == 'pdf':
                if self.stops[job_id].is_set():
                    raise InterruptedError('書き出しを中止しました。')
                if job['info']['format'] == 'pdf':
                    shutil.copyfile(source, target)
            else:
                export_pdf(source, target, kind, dpi, gray,
                       lambda n, total: self.update(job_id, export_progress=n / total * 100,
                                                   message=f'{n} / {total} ページを書き出しています。'),
                       self.stops[job_id].is_set)
            with self.lock:
                self.add_output(job_id, target, kind)
                self.update(job_id, state='ready', message='書き出しが完了しました。')
        except InterruptedError:
            self.update(job_id, state='ready', message='書き出しを中止しました。')
        except Exception as exc:
            self.update(job_id, state='error', message='書き出しエラー: ' + str(exc))

    def close(self):
        for event in self.stops.values():
            event.set()
        self.recovery_pool.shutdown(wait=True)
        self.export_pool.shutdown(wait=True)

    def remove(self, job_id):
        with self.lock:
            if self.jobs[job_id]['state'] in BUSY:
                raise ValueError('処理が終了してから削除してください。')
            folder = self.folder(job_id).resolve()
            if folder.parent != self.root or folder.name != job_id:
                raise ValueError('保存先が不正です。')
            shutil.rmtree(folder)
            del self.jobs[job_id]
            self.stops.pop(job_id, None)
            self.passwords.pop(job_id, None)


class Handler(BaseHTTPRequestHandler):
    server_version = 'Kaperio/0.1'

    def log_message(self, *_):
        pass

    @property
    def library(self):
        return self.server.library

    def send_data(self, status, data, mime='application/json; charset=utf-8', extra=None):
        if not isinstance(data, bytes):
            data = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self' blob:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def authorized(self):
        if self.headers.get('Host') != self.server.authority:
            return False
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get('Cookie', ''))
        except Exception:
            return False
        value = cookie.get('kaperio_session')
        return bool(value and secrets.compare_digest(value.value, self.server.token))

    def do_GET(self):
        try:
            self.get_route()
        except (ValueError, KeyError, OSError) as exc:
            self.send_data(400, {'error': str(exc)})
        except (BrokenPipeError, ConnectionResetError):
            pass

    def get_route(self):
        url = urlsplit(self.path)
        if url.path == '/launch':
            supplied = parse_qs(url.query).get('token', [''])[0]
            if self.headers.get('Host') == self.server.authority and secrets.compare_digest(supplied, self.server.token):
                secure = '; Secure' if self.server.tls else ''
                self.send_data(303, b'', extra={'Location': '/', 'Set-Cookie': f'kaperio_session={self.server.token}; HttpOnly; SameSite=Strict; Path=/' + secure})
                return
        if not self.authorized():
            self.send_data(403, {'error': 'Kaperioからアプリを起動してください。'})
            return
        path = url.path
        if path == '/api/jobs':
            self.send_data(200, {'jobs': self.library.snapshot()})
        elif path == '/api/settings':
            self.send_data(200, {'hashcat': str(self.library.hashcat or ''), 'output_dir': str(self.library.root),
                                 'zip2john': str(self.library.zip2john or ''),
                                 'version': VERSION, 'connection': self.server.origin, 'tls': self.server.tls})
        elif path == '/api/licenses':
            texts = ['Kaperio third-party notices\n' + (APP_DIR / 'THIRD_PARTY.md').read_text(encoding='utf-8'),
                     'Kaperio license\n' + (APP_DIR / 'LICENSE').read_text(encoding='utf-8')]
            for file in sorted((APP_DIR / 'licenses').rglob('*.txt')):
                raw = file.read_bytes()
                try:
                    notice = raw.decode('utf-8')
                except UnicodeDecodeError:
                    notice = raw.decode('latin-1')
                texts.append(file.name + '\n' + notice)
            self.send_data(200, '\n\n'.join(texts).encode('utf-8'), 'text/plain; charset=utf-8')
        elif path.startswith('/api/jobs/'):
            parts = path.strip('/').split('/')
            if len(parts) < 4:
                raise ValueError('URLが不正です。')
            job_id, action = parts[2:4]
            folder = self.library.folder(job_id)
            job = self.library.jobs[job_id]
            if action == 'preview' and job.get('unlocked') and (job['info']['format'] == 'pdf' or job.get('rendered')):
                page = int(parse_qs(url.query).get('page', ['0'])[0])
                source = job.get('rendered') or job['unlocked']
                self.send_data(200, preview_png(folder / source, page), 'image/png')
            elif action == 'download' and len(parts) == 5:
                name = unquote(parts[4])
                if name not in [o['file'] for o in job['outputs']]:
                    raise ValueError('出力ファイルが見つかりません。')
                target = folder / name
                download_name = Path(job['name']).stem + '_' + name
                self.send_data(200, target.read_bytes(), mimetypes.guess_type(name)[0] or 'application/octet-stream',
                               {'Content-Disposition': "attachment; filename*=UTF-8''" + quote(download_name)})
            else:
                self.send_data(404, {'error': '見つかりません。'})
        else:
            static = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css', '/lucide.js': 'lucide.min.js',
                      '/manifest.webmanifest': 'manifest.webmanifest', '/service-worker.js': 'service-worker.js',
                      '/icon-192.png': 'icon-192.png', '/icon-512.png': 'icon-512.png'}
            if path not in static:
                self.send_data(404, {'error': '見つかりません。'})
                return
            file = APP_DIR / 'static' / static[path]
            mime = {'.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.webmanifest': 'application/manifest+json', '.png': 'image/png'}[file.suffix]
            self.send_data(200, file.read_bytes(), mime)

    def do_POST(self):
        if not self.authorized() or self.headers.get('X-Kaperio') != '1':
            self.send_data(403, {'error': 'この操作はアプリ画面から実行してください。'})
            return
        origin = self.headers.get('Origin')
        if origin and origin != self.server.origin:
            self.send_data(403, {'error': 'Origin mismatch'})
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            limit = MAX_UPLOAD if self.path == '/api/import' else 16 * 1024 * 1024
            if length < 1 or length > limit:
                self.send_data(413, {'error': 'ファイルは100MB以内にしてください。'})
                return
            body = self.rfile.read(length)
            if self.path == '/api/import':
                job_id = self.library.import_pdf(unquote(self.headers.get('X-Filename', 'document.pdf')), body)
                self.send_data(200, {'id': job_id})
                return
            data = json.loads(body)
            if not isinstance(data, dict):
                raise ValueError('リクエストが不正です。')
            self.post_route(data)
        except (ValueError, KeyError, TypeError, OSError) as exc:
            self.send_data(400, {'error': str(exc)})
        except Exception as exc:
            self.send_data(500, {'error': '処理に失敗しました: ' + str(exc)})

    def post_route(self, data):
        if self.path == '/api/settings':
            candidate = Path(data['hashcat']).resolve() if data.get('hashcat') else None
            if candidate and (not candidate.is_file() or candidate.name.lower() not in ('hashcat.exe', 'hashcat', 'hashcat.bin')):
                raise ValueError('Hashcatの実行ファイルを指定してください。')
            zip2john = Path(data['zip2john']).resolve() if data.get('zip2john') else None
            if zip2john and (not zip2john.is_file() or zip2john.name.lower() not in ('zip2john', 'zip2john.exe')):
                raise ValueError('zip2johnの実行ファイルを指定してください。')
            if any(j['state'] in {'recovering', 'queued', 'pausing'} for j in self.library.jobs.values()):
                raise ValueError('探索を停止してから設定を変更してください。')
            self.library.hashcat = candidate
            self.library.zip2john = zip2john
            (self.library.root / 'settings.json').write_text(json.dumps({'hashcat': str(candidate or ''), 'zip2john': str(zip2john or '')}), encoding='utf-8')
            for job in self.library.jobs.values():
                if job['info']['format'] == 'zip' and not job.get('unlocked'):
                    job['info'] = inspect_file(self.library.folder(job['id']) / job['source'], '.zip', zip2john)
                    self.library.save(job)
        elif self.path == '/api/diagnostics':
            if not self.library.hashcat:
                raise ValueError('Hashcatが見つかりません。')
            result = subprocess.run([str(self.library.hashcat), '-I'], cwd=self.library.hashcat.parent,
                                    capture_output=True, timeout=45, creationflags=CREATE_FLAGS)
            self.send_data(200, {'text': (result.stdout + result.stderr).decode('utf-8', errors='replace'), 'code': result.returncode})
            return
        elif self.path == '/api/shutdown':
            self.send_data(200, {'ok': True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        else:
            parts = self.path.strip('/').split('/')
            if len(parts) != 4 or parts[:2] != ['api', 'jobs']:
                raise ValueError('URLが不正です。')
            job_id, action = parts[2:]
            self.library.folder(job_id)
            if action == 'unlock':
                self.library.known_password(job_id, str(data.get('password', '')))
            elif action == 'recover':
                self.library.start_recovery(job_id, data)
            elif action == 'resume':
                self.library.start_recovery(job_id, data, resume=True)
            elif action in ('pause', 'cancel'):
                self.library.stop(job_id, cancel=action == 'cancel')
            elif action == 'export':
                self.library.start_export(job_id, data)
            elif action == 'password':
                self.send_data(200, {'password': self.library.passwords.get(job_id, '')})
                return
            elif action == 'remove':
                self.library.remove(job_id)
            else:
                raise ValueError('操作が不正です。')
        self.send_data(200, {'ok': True})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', action='version', version='Kaperio ' + VERSION)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--data', type=Path, default=DEFAULT_DATA)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--tls-cert', type=Path)
    parser.add_argument('--tls-key', type=Path)
    args = parser.parse_args()
    address = ipaddress.ip_address(args.host)
    if address.version != 4 or address.is_unspecified or not address.is_private:
        parser.error('--host must be a loopback or specific private IPv4 address.')
    if not address.is_loopback and not (args.tls_cert and args.tls_key):
        parser.error('LAN access requires --tls-cert and --tls-key. Plain HTTP is loopback-only.')
    instance = acquire_instance(args.data)
    if instance is None:
        if not args.no_browser:
            try:
                existing = json.loads((args.data / 'launch.json').read_text(encoding='utf-8'))
                webbrowser.open(existing['url'])
            except (OSError, ValueError, KeyError):
                pass
        print('Kaperio is already running for this data directory.', flush=True)
        return
    library = Library(args.data)
    server = None
    for port in range(args.port, args.port + 20):
        try:
            server = ThreadingHTTPServer((args.host, port), Handler)
            break
        except OSError:
            continue
    if server is None:
        raise SystemExit('空きポートがありません。')
    server.library, server.token = library, secrets.token_urlsafe(32)
    server.tls = bool(args.tls_cert and args.tls_key)
    if server.tls:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(args.tls_cert, args.tls_key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    server.authority = f'{args.host}:{server.server_port}'
    server.origin = ('https' if server.tls else 'http') + '://' + server.authority
    server.daemon_threads = True
    url = server.origin + '/launch?token=' + server.token
    (library.root / 'launch.json').write_text(json.dumps({'url': url, 'pid': os.getpid()}), encoding='utf-8')
    print('Kaperio is running at ' + server.origin, flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        library.close()
        server.server_close()
        instance.close()


if __name__ == '__main__':
    main()
