"""Serve Round 2 over HTTPS on your Wi-Fi, so real phones can test it.

    cd backend
    python dev_https.py              # then open https://<your-LAN-IP>:8443/team-app/ on a phone

Why: phone browsers only allow the camera (QR scanner) and GPS (radar) on
https:// pages or on localhost. This creates a self-signed certificate for this
computer's LAN address. Each phone shows a one-time warning: tap
"Advanced" -> "Proceed". On Windows, allow Python through the firewall when asked.

If Round 2 is already running on port 8000 (Docker, or uvicorn), this only
puts HTTPS in front of it - same server, same data. Otherwise it starts its
own server on the local database (backend/data/round2.db).

docker-compose runs it too, as the ``https`` service: ``--proxy`` in front of
the ``api`` container, so ``docker compose up`` gives both http://…:8000 and
https://…:8443. Put the computer's Wi-Fi address in ``LAN_IP`` (.env) so the
certificate names it - phones still see the one-time warning either way.

This is for testing only. For the real event, use a proper domain and
certificate (see README), or a tunnel such as
`cloudflared tunnel --url http://localhost:8000`.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import ipaddress
import json
import os
import pathlib
import socket
import ssl
import time
import urllib.request

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

HERE = pathlib.Path(__file__).resolve().parent
CERT_DIR = HERE / "data" / "dev-cert"


def lan_ip() -> str:
    """The address other devices on the Wi-Fi reach this computer at."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("10.255.255.255", 1))  # no packet is sent
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def make_certificate(ip: str) -> tuple[pathlib.Path, pathlib.Path]:
    CERT_DIR.mkdir(parents=True, exist_ok=True)
    cert_path, key_path = CERT_DIR / f"dev-{ip}.crt", CERT_DIR / f"dev-{ip}.key"
    if cert_path.exists() and key_path.exists():
        try:  # reuse it while it has more than two days left, so phones only accept it once
            existing = x509.load_pem_x509_certificate(cert_path.read_bytes())
            if existing.not_valid_after_utc - datetime.datetime.now(datetime.timezone.utc) > datetime.timedelta(days=2):
                return cert_path, key_path
        except (ValueError, AttributeError):
            pass  # unreadable or an old cryptography: make a fresh one
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"Borderland Round 2 dev ({ip})")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=30))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address(ip)), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption())
    )
    return cert_path, key_path


def round2_running_on(port: int, host: str = "127.0.0.1") -> bool:
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/api/v1/health", timeout=2) as res:
            return json.load(res).get("status") == "ok"
    except (OSError, ValueError):
        return False


# --- HTTPS in front of an already-running server ---------------------------
# A plain byte pipe after the TLS handshake, so pages, the API and WebSockets
# all pass through untouched, and the one server process (its live hub and
# team locks) stays the only one.


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except OSError:  # includes ssl.SSLError and connection resets
        pass
    finally:
        writer.close()


def _quiet_disconnects(loop: asyncio.AbstractEventLoop, context: dict) -> None:
    """A phone that hasn't accepted the certificate yet aborts the TLS
    handshake, and closed tabs drop connections - both normal here."""
    if isinstance(context.get("exception"), OSError) or "SSL" in str(context.get("message", "")):
        return
    loop.default_exception_handler(context)


async def _serve_https_proxy(listen_port: int, app_port: int, tls: ssl.SSLContext, app_host: str = "127.0.0.1") -> None:
    async def handle(client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter) -> None:
        try:
            app_reader, app_writer = await asyncio.open_connection(app_host, app_port)
        except OSError:
            client_writer.close()
            return
        await asyncio.gather(_pipe(client_reader, app_writer), _pipe(app_reader, client_writer))

    asyncio.get_running_loop().set_exception_handler(_quiet_disconnects)
    server = await asyncio.start_server(handle, host="0.0.0.0", port=listen_port, ssl=tls, ssl_handshake_timeout=30)
    async with server:
        await server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8443, help="HTTPS port the phones use (default 8443)")
    parser.add_argument("--app-port", type=int, default=8000, help="where an already-running Round 2 server listens (default 8000)")
    parser.add_argument("--app-host", default="127.0.0.1", help="host of that server (docker-compose passes the api service name)")
    parser.add_argument("--ip", default=os.environ.get("LAN_IP") or "", help="the address phones use, for the certificate (default: detected; env LAN_IP)")
    parser.add_argument("--proxy", action="store_true", help="only ever front an existing server: wait for it instead of starting one (docker-compose)")
    args = parser.parse_args()

    ip = args.ip.strip() or lan_ip()
    cert, key = make_certificate(ip)
    in_front = round2_running_on(args.app_port, args.app_host)
    if args.proxy and not in_front:
        print(f"  Waiting for the Round 2 server at {args.app_host}:{args.app_port}...", flush=True)
        for _ in range(60):
            time.sleep(2)
            if round2_running_on(args.app_port, args.app_host):
                break
        in_front = True  # front it regardless; each connection retries on its own
    print("\n  Borderland Round 2 - HTTPS for phones")
    if in_front:
        print(f"  Adding HTTPS to the Round 2 server running at {args.app_host}:{args.app_port}: same data.")
        if not args.ip.strip() and args.proxy:
            print("  Tip: set LAN_IP=<this computer's Wi-Fi address> in .env so the certificate names the address phones use.")
    else:
        print(f"  Nothing is running on port {args.app_port}, so starting a server here (database: backend/data/round2.db).")
    print(f"  Team app  : https://{ip}:{args.port}/team-app/")
    print(f"  Admin app : https://{ip}:{args.port}/admin-app/")
    print("  Phones must be on the same Wi-Fi as this computer. Accept the certificate warning once per phone.")
    print("  Open the admin app at the address above too: its QR codes then point here.")
    print("  Ctrl+C stops it.\n", flush=True)

    if in_front:
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(cert, key)
        try:
            asyncio.run(_serve_https_proxy(args.port, args.app_port, tls, args.app_host))
        except KeyboardInterrupt:
            pass
        return

    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=args.port, ssl_certfile=str(cert), ssl_keyfile=str(key))


if __name__ == "__main__":
    main()
