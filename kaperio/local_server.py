"""Bound connections and perform TLS handshakes outside the accept loop."""
import socket
import ssl
import threading
from http.server import ThreadingHTTPServer


class LocalHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    request_timeout = 30
    handshake_timeout = 5

    def __init__(self, address, handler, *, max_connections=32):
        super().__init__(address, handler)
        self.tls_context = None
        self.slots = threading.BoundedSemaphore(max_connections)
        self.connections = set()
        self.connection_lock = threading.Lock()

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        with self.connection_lock:
            self.connections.add(request)
        try:
            if self.tls_context:
                request.settimeout(self.handshake_timeout)
                with self.connection_lock:
                    self.connections.discard(request)
                    request = self.tls_context.wrap_socket(request, server_side=True,
                                                           do_handshake_on_connect=False)
                    self.connections.add(request)
                request.do_handshake()
            request.settimeout(self.request_timeout)
            self.finish_request(request, client_address)
        except (OSError, ssl.SSLError):
            pass
        finally:
            with self.connection_lock:
                self.connections.discard(request)
            self.shutdown_request(request)
            self.slots.release()

    def server_close(self):
        with self.connection_lock:
            for request in self.connections:
                try:
                    request.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                request.close()
        super().server_close()
