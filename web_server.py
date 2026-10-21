#!/usr/bin/env python3
"""Локальный адаптивный веб-штаб. Журнал хранится в браузере, не в ~/.genshtab.

python web_server.py --port 8000
Не публикуйте сервер в открытом интернете: это статический локальный интерфейс.
"""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'none'; object-src 'none'; base-uri 'none'")
        super().end_headers()

    def list_directory(self, path):
        self.send_error(404)
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--host', default='0.0.0.0')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent / 'web'
    server = ThreadingHTTPServer((args.host, args.port), partial(Handler, directory=str(root)))
    print(f'Генштаб · веб-штаб: http://{args.host}:{args.port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
