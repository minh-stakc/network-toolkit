"""
Utility functions shared across the toolkit.

Provides timestamping, result serialization, network helpers,
logging setup, and common validation routines.
"""

import json
import logging
import os
import socket
import struct
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Configure and return the toolkit's root logger."""
    logger = logging.getLogger("network_toolkit")
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    return logger


logger = setup_logging()


def timestamp_iso() -> str:
    """Return the current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def timestamp_epoch() -> float:
    """Return the current time as a high-resolution epoch float."""
    return time.time()


def high_res_timer() -> float:
    """Return a monotonic high-resolution timer value for interval measurements."""
    return time.perf_counter()


def resolve_host(host: str) -> str:
    """Resolve a hostname to an IPv4 address. Returns the IP string."""
    try:
        return socket.gethostbyname(host)
    except socket.gaierror as exc:
        raise ValueError(f"Cannot resolve host '{host}': {exc}") from exc


def validate_port(port: int) -> int:
    """Validate that a port number is within the valid range."""
    if not (1 <= port <= 65535):
        raise ValueError(f"Port {port} is out of valid range (1-65535)")
    return port


def validate_host(host: str) -> str:
    """Validate and resolve a host, returning its IP address."""
    resolved = resolve_host(host)
    logger.debug("Resolved %s -> %s", host, resolved)
    return resolved


def compute_checksum(data: bytes) -> int:
    """
    Compute an Internet checksum (RFC 1071) for the given data.

    Used for ICMP packet construction when scapy is not available.
    """
    if len(data) % 2:
        data += b"\x00"
    checksum = 0
    for i in range(0, len(data), 2):
        word = (data[i] << 8) + data[i + 1]
        checksum += word
    checksum = (checksum >> 16) + (checksum & 0xFFFF)
    checksum += checksum >> 16
    return ~checksum & 0xFFFF


def build_icmp_echo_request(identifier: int, sequence: int, payload_size: int = 56) -> bytes:
    """
    Build a raw ICMP Echo Request packet.

    Args:
        identifier: ICMP identifier field.
        sequence: ICMP sequence number.
        payload_size: Number of payload bytes.

    Returns:
        Complete ICMP packet as bytes.
    """
    icmp_type = 8  # Echo Request
    icmp_code = 0
    checksum_placeholder = 0
    payload = bytes(range(payload_size % 256)) * (payload_size // 256 + 1)
    payload = payload[:payload_size]

    header = struct.pack(
        "!BBHHH",
        icmp_type,
        icmp_code,
        checksum_placeholder,
        identifier,
        sequence,
    )
    packet = header + payload
    chk = compute_checksum(packet)
    header = struct.pack("!BBHHH", icmp_type, icmp_code, chk, identifier, sequence)
    return header + payload


def parse_icmp_echo_reply(data: bytes) -> Dict[str, int]:
    """
    Parse an ICMP Echo Reply from raw IP packet data.

    Returns dict with type, code, checksum, identifier, sequence.
    """
    # Skip IP header (first 20 bytes for standard IPv4)
    ip_header_len = (data[0] & 0x0F) * 4
    icmp_data = data[ip_header_len:]
    if len(icmp_data) < 8:
        raise ValueError("ICMP packet too short")
    icmp_type, code, checksum, ident, seq = struct.unpack("!BBHHH", icmp_data[:8])
    return {
        "type": icmp_type,
        "code": code,
        "checksum": checksum,
        "identifier": ident,
        "sequence": seq,
    }


def save_results(results: Dict[str, Any], filepath: str) -> str:
    """
    Save measurement results to a JSON file.

    Creates parent directories if needed. Returns the absolute path written.
    """
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)

    output = {
        "timestamp": timestamp_iso(),
        "results": results,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=str)

    logger.info("Results saved to %s", path.resolve())
    return str(path.resolve())


def load_results(filepath: str) -> Dict[str, Any]:
    """Load measurement results from a JSON file."""
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def format_bytes(num_bytes: float) -> str:
    """Format a byte count into a human-readable string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:.2f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.2f} PB"


def format_bps(bits_per_second: float) -> str:
    """Format a bits-per-second value into a human-readable string."""
    for unit in ("bps", "Kbps", "Mbps", "Gbps"):
        if abs(bits_per_second) < 1000.0:
            return f"{bits_per_second:.2f} {unit}"
        bits_per_second /= 1000.0
    return f"{bits_per_second:.2f} Tbps"


def format_duration(seconds: float) -> str:
    """Format a duration in seconds into a human-readable string."""
    if seconds < 0.001:
        return f"{seconds * 1_000_000:.1f} us"
    if seconds < 1.0:
        return f"{seconds * 1000:.2f} ms"
    if seconds < 60.0:
        return f"{seconds:.2f} s"
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"{minutes}m {secs:.1f}s"


def ensure_output_dir(path: str) -> Path:
    """Ensure an output directory exists, creating it if necessary."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p
