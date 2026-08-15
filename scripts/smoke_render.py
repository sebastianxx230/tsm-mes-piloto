"""Small post-deploy smoke test that uses only the Python standard library."""

import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def _request(base_url, path, expect_json=False):
    request = Request(
        f"{base_url.rstrip('/')}{path}",
        headers={'User-Agent': 'tsm-mes-deploy-smoke/1.0'},
    )
    with urlopen(request, timeout=20) as response:
        body = response.read()
        if response.status < 200 or response.status >= 400:
            raise RuntimeError(f'{path} devolvio HTTP {response.status}')
        if expect_json:
            return json.loads(body.decode('utf-8'))
        return response.status


def main():
    parser = argparse.ArgumentParser(description='Valida un despliegue Render del MES.')
    parser.add_argument('base_url', help='Ejemplo: https://tsm-mes-piloto.onrender.com')
    args = parser.parse_args()

    parsed = urlparse(args.base_url)
    if parsed.username or parsed.password:
        parser.error('No incluya credenciales en la URL.')
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
        parser.error('La URL debe incluir http:// o https:// y un hostname.')
    if parsed.scheme != 'https' and parsed.hostname not in {'127.0.0.1', 'localhost'}:
        parser.error('Los despliegues remotos deben verificarse mediante HTTPS.')

    try:
        live = _request(args.base_url, '/health/live', expect_json=True)
        if live != {'status': 'ok', 'service': 'tsm-mes'}:
            raise RuntimeError(f'Respuesta de liveness inesperada: {live!r}')

        ready = _request(args.base_url, '/health', expect_json=True)
        if ready != {'status': 'ok', 'database': 'available'}:
            raise RuntimeError(f'Respuesta de PostgreSQL inesperada: {ready!r}')

        _request(args.base_url, '/')
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, RuntimeError) as error:
        print(f'FALLO: {error}', file=sys.stderr)
        return 1

    print('OK: contenedor, HTTPS, Flask y PostgreSQL responden correctamente.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
