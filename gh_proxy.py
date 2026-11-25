"""本地 CONNECT 代理：把被污染的域名解析到真实 IP，其他流量直连。

用法：python gh_proxy.py [端口]
默认 8899。仅用于本机 git 推送。
"""
from __future__ import annotations

import socket
import socketserver
import sys
import threading

# 被污染域名 → 真实 IP
OVERRIDES = {
    "github.com": "140.82.112.3",
    "www.github.com": "140.82.112.3",
    "codeload.github.com": "140.82.112.3",
    "api.github.com": "20.205.243.168",
    "raw.githubusercontent.com": "185.199.108.133",
    "objects.githubusercontent.com": "185.199.108.133",
}

BUFSIZE = 65536


class Tunnel(socketserver.BaseRequestHandler):
    def handle(self):
        client = self.request
        try:
            head = b""
            while b"\r\n\r\n" not in head:
                chunk = client.recv(BUFSIZE)
                if not chunk:
                    return
                head += chunk
                if len(head) > 65536:
                    return

            line = head.split(b"\r\n", 1)[0].decode("latin-1")
            parts = line.split()
            if len(parts) < 2 or parts[0].upper() != "CONNECT":
                client.sendall(b"HTTP/1.1 405 Only CONNECT\r\n\r\n")
                return

            host, _, port = parts[1].partition(":")
            port = int(port or 443)
            ip = OVERRIDES.get(host, host)

            upstream = socket.create_connection((ip, port), timeout=20)
            client.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")

            self._relay(client, upstream)
        except Exception:
            try:
                client.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            except Exception:
                pass
        finally:
            try:
                client.close()
            except Exception:
                pass

    @staticmethod
    def _relay(a: socket.socket, b: socket.socket):
        """双向转发，用两个线程，避免半关闭时误断开。"""
        def pump(src, dst):
            try:
                while True:
                    data = src.recv(BUFSIZE)
                    if not data:
                        break
                    dst.sendall(data)
            except Exception:
                pass
            finally:
                try:
                    dst.shutdown(socket.SHUT_WR)
                except Exception:
                    pass

        t = threading.Thread(target=pump, args=(b, a), daemon=True)
        t.start()
        pump(a, b)
        t.join(timeout=300)


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8899
    with Server(("127.0.0.1", port), Tunnel) as srv:
        print(f"代理已启动 127.0.0.1:{port}", flush=True)
        print("覆盖:", ", ".join(f"{k}→{v}" for k, v in OVERRIDES.items()), flush=True)
        srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
