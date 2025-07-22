"""
Throughput benchmarking module.

Provides iperf-style throughput measurement for TCP and UDP protocols.
Includes a built-in server mode for easy testing and support for
parallel streams and configurable buffer sizes.
"""

import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

from utils import (
    high_res_timer,
    validate_host,
    validate_port,
    format_bytes,
    format_bps,
    logger,
)


@dataclass
class ThroughputSample:
    """A single throughput sample taken during measurement."""
    timestamp: float       # epoch time
    interval_sec: float    # duration of this sample interval
    bytes_transferred: int
    bits_per_second: float


@dataclass
class ThroughputResult:
    """Container for throughput measurement results."""
    host: str
    resolved_ip: str
    protocol: str
    duration: float
    total_bytes: int
    total_bits_per_second: float
    samples: List[ThroughputSample] = field(default_factory=list)
    mean_throughput_bps: float = 0.0
    max_throughput_bps: float = 0.0
    min_throughput_bps: float = 0.0
    stddev_throughput_bps: float = 0.0
    parallel_streams: int = 1

    def compute_stats(self):
        """Compute aggregate throughput statistics from samples."""
        if not self.samples:
            return
        bps_values = np.array([s.bits_per_second for s in self.samples])
        self.mean_throughput_bps = float(np.mean(bps_values))
        self.max_throughput_bps = float(np.max(bps_values))
        self.min_throughput_bps = float(np.min(bps_values))
        self.stddev_throughput_bps = float(np.std(bps_values))

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "host": self.host,
            "resolved_ip": self.resolved_ip,
            "protocol": self.protocol,
            "duration_sec": round(self.duration, 2),
            "total_bytes": self.total_bytes,
            "total_throughput": format_bps(self.total_bits_per_second),
            "mean_throughput": format_bps(self.mean_throughput_bps),
            "max_throughput": format_bps(self.max_throughput_bps),
            "min_throughput": format_bps(self.min_throughput_bps),
            "stddev_throughput": format_bps(self.stddev_throughput_bps),
            "parallel_streams": self.parallel_streams,
            "samples": [
                {
                    "interval_sec": round(s.interval_sec, 3),
                    "bytes": s.bytes_transferred,
                    "bps": round(s.bits_per_second, 2),
                }
                for s in self.samples
            ],
        }


class ThroughputMeasurer:
    """
    Measures network throughput using TCP or UDP bulk transfer.

    In TCP mode, connects to a server and sends data as fast as possible,
    sampling throughput at 1-second intervals.

    In UDP mode, sends data at a target rate and measures actual achieved throughput.

    Usage:
        measurer = ThroughputMeasurer(host="192.168.1.1", port=5001, duration=10)
        result = measurer.run()
        print(result.total_bits_per_second)
    """

    SAMPLE_INTERVAL = 1.0  # seconds between throughput samples

    def __init__(
        self,
        host: str,
        port: int = 5001,
        duration: float = 10.0,
        buffer_size: int = 131072,
        protocol: str = "tcp",
        parallel_streams: int = 1,
        target_bandwidth_mbps: float = 0.0,
    ):
        self.host = host
        self.resolved_ip = validate_host(host)
        self.port = validate_port(port)
        self.duration = duration
        self.buffer_size = buffer_size
        self.protocol = protocol.lower()
        self.parallel_streams = max(1, parallel_streams)
        self.target_bandwidth_mbps = target_bandwidth_mbps

    def run(self) -> ThroughputResult:
        """Execute throughput measurement."""
        if self.protocol == "udp":
            return self._run_udp()
        return self._run_tcp()

    def _run_tcp(self) -> ThroughputResult:
        """Measure TCP throughput by bulk data transfer."""
        result = ThroughputResult(
            host=self.host,
            resolved_ip=self.resolved_ip,
            protocol="tcp",
            duration=self.duration,
            total_bytes=0,
            total_bits_per_second=0.0,
            parallel_streams=self.parallel_streams,
        )

        send_buf = bytes(self.buffer_size)
        stream_bytes = [0] * self.parallel_streams
        sockets: List[Optional[socket.socket]] = []

        # Open connections
        for i in range(self.parallel_streams):
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.settimeout(self.duration + 5.0)
            try:
                sock.connect((self.resolved_ip, self.port))
                sockets.append(sock)
                logger.debug("Stream %d connected to %s:%d", i, self.resolved_ip, self.port)
            except OSError as exc:
                logger.error("Stream %d connection failed: %s", i, exc)
                sock.close()
                sockets.append(None)

        active_sockets = [(i, s) for i, s in enumerate(sockets) if s is not None]
        if not active_sockets:
            logger.error("No streams connected. Aborting throughput test.")
            return result

        # Transfer data, sampling throughput each interval
        overall_start = high_res_timer()
        interval_start = overall_start
        interval_bytes = 0
        stop_event = threading.Event()

        def send_loop(idx: int, sock: socket.socket):
            """Send data continuously on a single stream."""
            nonlocal interval_bytes
            while not stop_event.is_set():
                try:
                    sent = sock.send(send_buf)
                    stream_bytes[idx] += sent
                except OSError:
                    break

        # Start sender threads for each stream
        threads = []
        for idx, sock in active_sockets:
            t = threading.Thread(target=send_loop, args=(idx, sock), daemon=True)
            t.start()
            threads.append(t)

        # Sample throughput at intervals
        try:
            while True:
                time.sleep(self.SAMPLE_INTERVAL)
                now = high_res_timer()
                elapsed = now - overall_start

                current_total = sum(stream_bytes)
                interval_transferred = current_total - (result.total_bytes if result.total_bytes else 0)
                interval_duration = now - interval_start
                bps = (interval_transferred * 8) / interval_duration if interval_duration > 0 else 0.0

                result.samples.append(ThroughputSample(
                    timestamp=time.time(),
                    interval_sec=interval_duration,
                    bytes_transferred=interval_transferred,
                    bits_per_second=bps,
                ))

                result.total_bytes = current_total
                interval_start = now

                if elapsed >= self.duration:
                    break
        finally:
            stop_event.set()
            for t in threads:
                t.join(timeout=2.0)
            for _, sock in active_sockets:
                sock.close()

        overall_elapsed = high_res_timer() - overall_start
        result.duration = overall_elapsed
        result.total_bits_per_second = (
            (result.total_bytes * 8) / overall_elapsed if overall_elapsed > 0 else 0.0
        )
        result.compute_stats()
        return result

    def _run_udp(self) -> ThroughputResult:
        """Measure UDP throughput at a target rate."""
        result = ThroughputResult(
            host=self.host,
            resolved_ip=self.resolved_ip,
            protocol="udp",
            duration=self.duration,
            total_bytes=0,
            total_bits_per_second=0.0,
            parallel_streams=1,
        )

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        payload = bytes(self.buffer_size)

        # Calculate inter-packet interval from target bandwidth
        if self.target_bandwidth_mbps > 0:
            target_bps = self.target_bandwidth_mbps * 1_000_000
            packet_bits = self.buffer_size * 8
            pps = target_bps / packet_bits
            inter_packet = 1.0 / pps if pps > 0 else 0.001
        else:
            inter_packet = 0.0  # send as fast as possible

        overall_start = high_res_timer()
        interval_start = overall_start
        interval_bytes = 0
        total_bytes = 0

        try:
            while True:
                now = high_res_timer()
                if now - overall_start >= self.duration:
                    break

                try:
                    sent = sock.sendto(payload, (self.resolved_ip, self.port))
                    total_bytes += sent
                    interval_bytes += sent
                except OSError as exc:
                    logger.debug("UDP send error: %s", exc)

                # Check if it's time to record a sample
                interval_elapsed = high_res_timer() - interval_start
                if interval_elapsed >= self.SAMPLE_INTERVAL:
                    bps = (interval_bytes * 8) / interval_elapsed
                    result.samples.append(ThroughputSample(
                        timestamp=time.time(),
                        interval_sec=interval_elapsed,
                        bytes_transferred=interval_bytes,
                        bits_per_second=bps,
                    ))
                    interval_start = high_res_timer()
                    interval_bytes = 0

                if inter_packet > 0:
                    time.sleep(inter_packet)
        finally:
            sock.close()

        overall_elapsed = high_res_timer() - overall_start
        result.total_bytes = total_bytes
        result.duration = overall_elapsed
        result.total_bits_per_second = (
            (total_bytes * 8) / overall_elapsed if overall_elapsed > 0 else 0.0
        )
        result.compute_stats()
        return result


class ThroughputServer:
    """
    Simple TCP/UDP sink server for throughput testing.

    Accepts connections and discards incoming data, reporting
    the received throughput.
    """

    def __init__(self, port: int = 5001, protocol: str = "tcp"):
        self.port = validate_port(port)
        self.protocol = protocol.lower()
        self._stop = threading.Event()

    def start(self):
        """Start the server in the current thread."""
        if self.protocol == "udp":
            self._serve_udp()
        else:
            self._serve_tcp()

    def start_background(self) -> threading.Thread:
        """Start the server in a background thread."""
        t = threading.Thread(target=self.start, daemon=True)
        t.start()
        return t

    def stop(self):
        """Signal the server to stop."""
        self._stop.set()

    def _serve_tcp(self):
        """Accept TCP connections and sink data."""
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.settimeout(1.0)
        server.bind(("0.0.0.0", self.port))
        server.listen(5)
        logger.info("TCP throughput server listening on port %d", self.port)

        while not self._stop.is_set():
            try:
                conn, addr = server.accept()
                logger.info("Connection from %s:%d", *addr)
                t = threading.Thread(
                    target=self._handle_tcp_client, args=(conn, addr), daemon=True
                )
                t.start()
            except socket.timeout:
                continue
        server.close()

    def _handle_tcp_client(self, conn: socket.socket, addr):
        """Handle a single TCP client connection -- sink data."""
        total = 0
        start = high_res_timer()
        try:
            while True:
                data = conn.recv(131072)
                if not data:
                    break
                total += len(data)
        except OSError:
            pass
        finally:
            elapsed = high_res_timer() - start
            bps = (total * 8) / elapsed if elapsed > 0 else 0
            logger.info(
                "Client %s:%d: %s in %.2fs (%s)",
                addr[0], addr[1], format_bytes(total), elapsed, format_bps(bps),
            )
            conn.close()

    def _serve_udp(self):
        """Receive UDP packets and discard them."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(1.0)
        sock.bind(("0.0.0.0", self.port))
        logger.info("UDP throughput server listening on port %d", self.port)

        total = 0
        start = high_res_timer()
        while not self._stop.is_set():
            try:
                data, addr = sock.recvfrom(65536)
                total += len(data)
            except socket.timeout:
                continue
        elapsed = high_res_timer() - start
        bps = (total * 8) / elapsed if elapsed > 0 else 0
        logger.info("UDP server: received %s in %.2fs (%s)", format_bytes(total), elapsed, format_bps(bps))
        sock.close()
