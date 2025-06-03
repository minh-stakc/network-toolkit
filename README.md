# Network Performance Measurement Toolkit

A comprehensive Python toolkit for benchmarking network performance across distributed
hosts. Measures latency, jitter, packet loss, and throughput with automated traffic
generation and visualization capabilities.

## Features

- **Latency Measurement**: ICMP and TCP-based RTT measurement with statistical analysis
- **Jitter Analysis**: Inter-packet delay variation measurement and reporting
- **Packet Loss Detection**: Configurable probe-based packet loss measurement
- **Throughput Benchmarking**: iperf-style TCP/UDP throughput testing
- **Traffic Generation**: Configurable TCP/UDP traffic with load profiles (ramp, burst, steady)
- **Visualization**: Matplotlib plots and HTML report generation
- **Congestion Analysis**: Automated congestion detection from measurement data

## Installation

```bash
pip install -e .
```

Or install dependencies directly:

```bash
pip install -r requirements.txt
```

## Usage

The toolkit provides a CLI via `main.py`:

```bash
# Run latency measurement against a host
python main.py measure latency --host 192.168.1.1 --count 100

# Run jitter measurement
python main.py measure jitter --host 192.168.1.1 --count 50

# Run packet loss test
python main.py measure packet-loss --host 192.168.1.1 --count 200

# Run throughput benchmark
python main.py measure throughput --host 192.168.1.1 --port 5001 --duration 10

# Generate TCP traffic with a ramp profile
python main.py traffic tcp --host 192.168.1.1 --port 5001 --profile ramp --duration 30

# Generate UDP traffic at a fixed rate
python main.py traffic udp --host 192.168.1.1 --port 5001 --rate 10.0 --duration 20

# Run a full benchmark suite
python main.py benchmark --host 192.168.1.1 --output results/

# Generate visualization plots from results
python main.py visualize --input results/ --output plots/

# Generate an HTML report
python main.py report --input results/ --output report.html
```

## Configuration

Edit `config.py` to set default target hosts, ports, and test parameters.

## Project Structure

```
network_toolkit/
  config.py              - Configuration defaults
  main.py                - CLI entry point (click)
  utils.py               - Shared utility functions
  setup.py               - Package setup
  requirements.txt       - Dependencies
  measurements/
    latency.py           - ICMP/TCP latency measurement
    jitter.py            - Jitter measurement and analysis
    packet_loss.py       - Packet loss detection
    throughput.py        - Throughput benchmarking
  traffic/
    tcp_generator.py     - TCP traffic generation
    udp_generator.py     - UDP traffic generation
    load_profiles.py     - Load profile definitions
  analysis/
    statistics.py        - Statistical analysis
    congestion.py        - Congestion detection
  visualization/
    plots.py             - Matplotlib visualizations
    reports.py           - HTML report generation
```

## Requirements

- Python 3.8+
- Root/administrator privileges for ICMP measurements (uses raw sockets)
- A listening server on the target host for throughput and traffic tests

## License

MIT
