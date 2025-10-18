"""
CLI entry point for the Network Performance Measurement Toolkit.

Provides commands for measurement, traffic generation, visualization,
and report generation via the click framework.
"""

import json
import os
import sys

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn

from config import DEFAULT_CONFIG
from utils import save_results, load_results, ensure_output_dir, setup_logging

console = Console()


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose (DEBUG) logging.")
def cli(verbose):
    """Network Performance Measurement Toolkit.

    A comprehensive tool for benchmarking network latency, jitter,
    packet loss, and throughput across distributed hosts.
    """
    if verbose:
        setup_logging("DEBUG")


# ---------------------------------------------------------------------------
# Measurement commands
# ---------------------------------------------------------------------------

@cli.group()
def measure():
    """Run network measurements."""
    pass


@measure.command()
@click.option("--host", "-h", required=True, help="Target host address.")
@click.option("--count", "-c", default=100, help="Number of probes.")
@click.option("--timeout", "-t", default=2.0, help="Probe timeout in seconds.")
@click.option("--interval", "-i", default=0.1, help="Inter-probe interval in seconds.")
@click.option("--tcp", is_flag=True, help="Use TCP SYN probes instead of ICMP.")
@click.option("--port", "-p", default=80, help="TCP port for TCP probes.")
@click.option("--output", "-o", default=None, help="Output file for results (JSON).")
def latency(host, count, timeout, interval, tcp, port, output):
    """Measure network latency (RTT) to a target host."""
    from measurements.latency import LatencyMeasurer

    console.print(Panel(
        f"[bold]Latency Measurement[/bold]\n"
        f"Target: {host} | Probes: {count} | Mode: {'TCP' if tcp else 'ICMP'}",
        border_style="blue",
    ))

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Measuring latency...", total=count)

        measurer = LatencyMeasurer(
            host=host, count=count, timeout=timeout,
            interval=interval, use_tcp=tcp, tcp_port=port,
        )
        result = measurer.run()
        progress.update(task, completed=count)

    # Display results
    table = Table(title="Latency Results", show_header=True, header_style="bold cyan")
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")
    data = result.to_dict()
    table.add_row("Host", f"{data['host']} ({data['resolved_ip']})")
    table.add_row("Probes", f"{data['successful_probes']}/{data['probe_count']}")
    table.add_row("Min RTT", f"{data['min_rtt_ms']:.3f} ms")
    table.add_row("Mean RTT", f"{data['mean_rtt_ms']:.3f} ms")
    table.add_row("Median RTT", f"{data['median_rtt_ms']:.3f} ms")
    table.add_row("Max RTT", f"{data['max_rtt_ms']:.3f} ms")
    table.add_row("Std Dev", f"{data['stddev_rtt_ms']:.3f} ms")
    table.add_row("P95 RTT", f"{data['p95_rtt_ms']:.3f} ms")
    table.add_row("P99 RTT", f"{data['p99_rtt_ms']:.3f} ms")
    table.add_row("Loss", f"{data['loss_percent']:.2f}%")
    console.print(table)

    if output:
        save_results(data, output)
        console.print(f"\n[green]Results saved to {output}[/green]")


@measure.command()
@click.option("--host", "-h", required=True, help="Target host address.")
@click.option("--count", "-c", default=100, help="Number of probes.")
@click.option("--interval", "-i", default=0.05, help="Inter-probe interval in seconds.")
@click.option("--port", "-p", default=80, help="TCP port for probes.")
@click.option("--output", "-o", default=None, help="Output file for results (JSON).")
def jitter(host, count, interval, port, output):
    """Measure network jitter (inter-packet delay variation)."""
    from measurements.jitter import JitterMeasurer

    console.print(Panel(
        f"[bold]Jitter Measurement[/bold]\n"
        f"Target: {host} | Probes: {count}",
        border_style="magenta",
    ))

    with Progress(
        SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
        BarColumn(), TimeElapsedColumn(), console=console,
    ) as progress:
        task = progress.add_task("Measuring jitter...", total=count)
        measurer = JitterMeasurer(host=host, count=count, interval=interval, port=port)
        result = measurer.run()
        progress.update(task, completed=count)

    table = Table(title="Jitter Results", show_header=True, header_style="bold magenta")
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")
    data = result.to_dict()
    table.add_row("Host", data["host"])
    table.add_row("Probes", str(data["successful_probes"]))
    table.add_row("Mean Jitter", f"{data['mean_jitter_ms']:.4f} ms")
    table.add_row("Max Jitter", f"{data['max_jitter_ms']:.4f} ms")
    table.add_row("Min Jitter", f"{data['min_jitter_ms']:.4f} ms")
    table.add_row("Std Dev", f"{data['stddev_jitter_ms']:.4f} ms")
    table.add_row("P95 Jitter", f"{data['p95_jitter_ms']:.4f} ms")
    table.add_row("P99 Jitter", f"{data['p99_jitter_ms']:.4f} ms")
    table.add_row("RFC 3550 Jitter", f"{data['rfc3550_jitter_ms']:.4f} ms")
    console.print(table)

    if output:
        save_results(data, output)


@measure.command("packet-loss")
@click.option("--host", "-h", required=True, help="Target host address.")
@click.option("--count", "-c", default=200, help="Number of probes.")
@click.option("--timeout", "-t", default=2.0, help="Probe timeout in seconds.")
@click.option("--interval", "-i", default=0.05, help="Inter-probe interval in seconds.")
@click.option("--port", "-p", default=80, help="TCP port for probes.")
@click.option("--burst", is_flag=True, help="Use burst-mode probing.")
@click.option("--burst-size", default=10, help="Packets per burst in burst mode.")
@click.option("--output", "-o", default=None, help="Output file for results (JSON).")
def packet_loss(host, count, timeout, interval, port, burst, burst_size, output):
    """Measure packet loss rate and detect burst loss patterns."""
    from measurements.packet_loss import PacketLossMeasurer

    console.print(Panel(
        f"[bold]Packet Loss Measurement[/bold]\n"
        f"Target: {host} | Probes: {count} | Mode: {'Burst' if burst else 'Continuous'}",
        border_style="red",
    ))

    with Progress(
        SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
        BarColumn(), TimeElapsedColumn(), console=console,
    ) as progress:
        task = progress.add_task("Measuring packet loss...", total=count)
        measurer = PacketLossMeasurer(
            host=host, count=count, timeout=timeout,
            interval=interval, port=port, burst_size=burst_size,
        )
        result = measurer.run_burst_mode() if burst else measurer.run()
        progress.update(task, completed=count)

    table = Table(title="Packet Loss Results", show_header=True, header_style="bold red")
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")
    data = result.to_dict()
    table.add_row("Host", f"{data['host']} ({data['resolved_ip']})")
    table.add_row("Sent", str(data["total_sent"]))
    table.add_row("Received", str(data["total_received"]))
    table.add_row("Lost", str(data["total_lost"]))
    table.add_row("Loss Rate", f"{data['loss_percent']:.2f}%")
    table.add_row("Max Burst Loss", str(data["max_burst_loss"]))
    table.add_row("Mean Burst Length", f"{data['mean_loss_burst_length']:.1f}")
    console.print(table)

    if output:
        save_results(data, output)


@measure.command()
@click.option("--host", "-h", required=True, help="Target host address.")
@click.option("--port", "-p", default=5001, help="Server port.")
@click.option("--duration", "-d", default=10.0, help="Test duration in seconds.")
@click.option("--protocol", type=click.Choice(["tcp", "udp"]), default="tcp", help="Protocol.")
@click.option("--streams", "-P", default=1, help="Number of parallel streams (TCP).")
@click.option("--bandwidth", "-b", default=0.0, help="Target bandwidth in Mbps (UDP).")
@click.option("--buffer-size", default=131072, help="Send buffer size in bytes.")
@click.option("--output", "-o", default=None, help="Output file for results (JSON).")
def throughput(host, port, duration, protocol, streams, bandwidth, buffer_size, output):
    """Measure network throughput (iperf-style benchmark)."""
    from measurements.throughput import ThroughputMeasurer

    console.print(Panel(
        f"[bold]Throughput Benchmark[/bold]\n"
        f"Target: {host}:{port} | Protocol: {protocol.upper()} | Duration: {duration}s",
        border_style="green",
    ))

    with Progress(
        SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(), console=console,
    ) as progress:
        task = progress.add_task("Benchmarking throughput...", total=None)
        measurer = ThroughputMeasurer(
            host=host, port=port, duration=duration,
            buffer_size=buffer_size, protocol=protocol,
            parallel_streams=streams, target_bandwidth_mbps=bandwidth,
        )
        result = measurer.run()
        progress.update(task, completed=1, total=1)

    table = Table(title="Throughput Results", show_header=True, header_style="bold green")
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")
    data = result.to_dict()
    table.add_row("Host", f"{data['host']} ({data['resolved_ip']})")
    table.add_row("Protocol", data["protocol"].upper())
    table.add_row("Duration", f"{data['duration_sec']}s")
    table.add_row("Total Throughput", data["total_throughput"])
    table.add_row("Mean Throughput", data["mean_throughput"])
    table.add_row("Max Throughput", data["max_throughput"])
    table.add_row("Min Throughput", data["min_throughput"])
    table.add_row("Streams", str(data["parallel_streams"]))
    console.print(table)

    if output:
        save_results(data, output)


# ---------------------------------------------------------------------------
# Traffic generation commands
# ---------------------------------------------------------------------------

@cli.group()
def traffic():
    """Generate network traffic with configurable patterns."""
    pass


@traffic.command("tcp")
@click.option("--host", "-h", required=True, help="Target host address.")
@click.option("--port", "-p", default=5001, help="Target TCP port.")
@click.option("--duration", "-d", default=30.0, help="Duration in seconds.")
@click.option("--payload-size", default=1024, help="Payload size in bytes.")
@click.option("--profile", type=click.Choice(["steady", "ramp", "burst", "sine", "step"]), default="steady")
@click.option("--rate", default=10.0, help="Base rate (packets/sec for steady).")
@click.option("--persistent", is_flag=True, help="Use a single persistent connection.")
@click.option("--output", "-o", default=None, help="Output file for stats (JSON).")
def traffic_tcp(host, port, duration, payload_size, profile, rate, persistent, output):
    """Generate TCP traffic with configurable patterns."""
    from traffic.tcp_generator import TCPTrafficGenerator
    from traffic.load_profiles import LoadProfile

    lp = LoadProfile.from_name(profile, rate=rate, start_rate=1.0, end_rate=rate)
    console.print(Panel(
        f"[bold]TCP Traffic Generation[/bold]\n"
        f"Target: {host}:{port} | Profile: {profile} | Duration: {duration}s",
        border_style="yellow",
    ))

    gen = TCPTrafficGenerator(
        host=host, port=port, duration=duration,
        payload_size=payload_size, profile=lp, persistent=persistent,
    )

    with Progress(
        SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(), console=console,
    ) as progress:
        task = progress.add_task("Generating TCP traffic...", total=None)
        stats = gen.run()
        progress.update(task, completed=1, total=1)

    data = stats.to_dict()
    console.print(f"[bold]Connections:[/bold] {data['successful_connections']}/{data['total_connections']}")
    console.print(f"[bold]Data sent:[/bold] {data['total_bytes_sent_human']}")
    console.print(f"[bold]Duration:[/bold] {data['duration_sec']}s")
    console.print(f"[bold]Errors:[/bold] {data['error_count']}")

    if output:
        save_results(data, output)


@traffic.command("udp")
@click.option("--host", "-h", required=True, help="Target host address.")
@click.option("--port", "-p", default=5002, help="Target UDP port.")
@click.option("--duration", "-d", default=30.0, help="Duration in seconds.")
@click.option("--payload-size", default=1024, help="Payload size in bytes.")
@click.option("--profile", type=click.Choice(["steady", "ramp", "burst", "sine", "step"]), default="steady")
@click.option("--rate", default=10.0, help="Base rate (packets/sec).")
@click.option("--output", "-o", default=None, help="Output file for stats (JSON).")
def traffic_udp(host, port, duration, payload_size, profile, rate, output):
    """Generate UDP traffic with configurable rates."""
    from traffic.udp_generator import UDPTrafficGenerator
    from traffic.load_profiles import LoadProfile

    lp = LoadProfile.from_name(profile, rate=rate, start_rate=1.0, end_rate=rate)
    console.print(Panel(
        f"[bold]UDP Traffic Generation[/bold]\n"
        f"Target: {host}:{port} | Profile: {profile} | Duration: {duration}s",
        border_style="yellow",
    ))

    gen = UDPTrafficGenerator(
        host=host, port=port, duration=duration,
        payload_size=payload_size, profile=lp, rate=rate,
    )

    with Progress(
        SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(), console=console,
    ) as progress:
        task = progress.add_task("Generating UDP traffic...", total=None)
        stats = gen.run()
        progress.update(task, completed=1, total=1)

    data = stats.to_dict()
    console.print(f"[bold]Packets sent:[/bold] {data['total_packets_sent']}")
    console.print(f"[bold]Data sent:[/bold] {data['total_bytes_sent_human']}")
    console.print(f"[bold]Duration:[/bold] {data['duration_sec']}s")
    console.print(f"[bold]Mean rate:[/bold] {data['mean_send_rate_pps']} pps")

    if output:
        save_results(data, output)


# ---------------------------------------------------------------------------
# Server command (for throughput/traffic testing)
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--port", "-p", default=5001, help="Listen port.")
@click.option("--protocol", type=click.Choice(["tcp", "udp"]), default="tcp")
def server(port, protocol):
    """Start a sink server for throughput/traffic testing."""
    from measurements.throughput import ThroughputServer

    console.print(Panel(
        f"[bold]{protocol.upper()} Sink Server[/bold]\n"
        f"Listening on port {port}. Press Ctrl+C to stop.",
        border_style="cyan",
    ))

    srv = ThroughputServer(port=port, protocol=protocol)
    try:
        srv.start()
    except KeyboardInterrupt:
        srv.stop()
        console.print("\n[yellow]Server stopped.[/yellow]")


# ---------------------------------------------------------------------------
# Full benchmark suite
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--host", "-h", required=True, help="Target host address.")
@click.option("--port", "-p", default=80, help="TCP port for latency/jitter/loss probes.")
@click.option("--throughput-port", default=5001, help="Port for throughput test.")
@click.option("--output", "-o", default="results", help="Output directory.")
@click.option("--latency-count", default=100, help="Number of latency probes.")
@click.option("--jitter-count", default=100, help="Number of jitter probes.")
@click.option("--loss-count", default=200, help="Number of loss probes.")
@click.option("--throughput-duration", default=10.0, help="Throughput test duration.")
@click.option("--skip-throughput", is_flag=True, help="Skip throughput test.")
def benchmark(host, port, throughput_port, output, latency_count, jitter_count,
              loss_count, throughput_duration, skip_throughput):
    """Run a full benchmark suite against a target host."""
    from measurements.latency import LatencyMeasurer
    from measurements.jitter import JitterMeasurer
    from measurements.packet_loss import PacketLossMeasurer
    from measurements.throughput import ThroughputMeasurer
    from analysis.statistics import MeasurementAnalyzer
    from analysis.congestion import CongestionAnalyzer
    from visualization.plots import NetworkPlotter
    from visualization.reports import ReportGenerator

    output_dir = ensure_output_dir(output)
    plots_dir = ensure_output_dir(str(output_dir / "plots"))

    console.print(Panel(
        f"[bold]Full Benchmark Suite[/bold]\n"
        f"Target: {host} | Output: {output_dir}",
        border_style="bold blue",
    ))

    all_results = {}

    # --- Latency ---
    console.print("\n[bold cyan]1/4 Latency Measurement[/bold cyan]")
    lat_measurer = LatencyMeasurer(host=host, count=latency_count, use_tcp=True, tcp_port=port)
    lat_result = lat_measurer.run()
    lat_data = lat_result.to_dict()
    all_results["latency"] = lat_data
    save_results(lat_data, str(output_dir / "latency.json"))
    console.print(f"  Mean RTT: {lat_data['mean_rtt_ms']:.3f} ms | Loss: {lat_data['loss_percent']:.1f}%")

    # --- Jitter ---
    console.print("\n[bold magenta]2/4 Jitter Measurement[/bold magenta]")
    jit_measurer = JitterMeasurer(host=host, count=jitter_count, port=port)
    jit_result = jit_measurer.run()
    jit_data = jit_result.to_dict()
    all_results["jitter"] = jit_data
    save_results(jit_data, str(output_dir / "jitter.json"))
    console.print(f"  Mean Jitter: {jit_data['mean_jitter_ms']:.4f} ms")

    # --- Packet Loss ---
    console.print("\n[bold red]3/4 Packet Loss Measurement[/bold red]")
    loss_measurer = PacketLossMeasurer(host=host, count=loss_count, port=port)
    loss_result = loss_measurer.run()
    loss_data = loss_result.to_dict()
    all_results["packet_loss"] = loss_data
    save_results(loss_data, str(output_dir / "packet_loss.json"))
    console.print(f"  Loss: {loss_data['loss_percent']:.2f}% | Max Burst: {loss_data['max_burst_loss']}")

    # --- Throughput ---
    tp_data = None
    if not skip_throughput:
        console.print("\n[bold green]4/4 Throughput Benchmark[/bold green]")
        try:
            tp_measurer = ThroughputMeasurer(
                host=host, port=throughput_port, duration=throughput_duration,
            )
            tp_result = tp_measurer.run()
            tp_data = tp_result.to_dict()
            all_results["throughput"] = tp_data
            save_results(tp_data, str(output_dir / "throughput.json"))
            console.print(f"  Throughput: {tp_data['total_throughput']}")
        except Exception as exc:
            console.print(f"  [yellow]Throughput test failed: {exc}[/yellow]")
    else:
        console.print("\n[dim]4/4 Throughput Benchmark (skipped)[/dim]")

    # --- Analysis ---
    console.print("\n[bold]Running analysis...[/bold]")

    if lat_data.get("rtt_samples_ms"):
        analyzer = MeasurementAnalyzer(lat_data["rtt_samples_ms"])
        stats = analyzer.descriptive_stats()
        trend = analyzer.linear_trend()
        stability = analyzer.stability_index()
        all_results["analysis"] = {
            "descriptive_stats": stats.to_dict(),
            "trend": trend,
            "stability_index": stability,
        }
        console.print(f"  Stability Index: {stability}/100 | Trend: {trend['trend_direction']}")

    # Congestion analysis
    congestion_analyzer = CongestionAnalyzer()
    rtt_samples = lat_data.get("rtt_samples_ms", [])
    loss_flags = [not p["success"] for p in loss_data.get("probe_timeline", [])]
    tp_samples = [s["bps"] for s in (tp_data or {}).get("samples", [])]

    congestion_report = congestion_analyzer.full_analysis(
        rtt=rtt_samples if rtt_samples else None,
        loss=loss_flags if loss_flags else None,
        throughput=tp_samples if tp_samples else None,
    )
    congestion_data = congestion_report.to_dict()
    all_results["congestion"] = congestion_data
    console.print(f"  Congestion: {congestion_data['max_severity']} ({congestion_data['total_events']} events)")

    # --- Visualization ---
    console.print("\n[bold]Generating plots...[/bold]")
    plotter = NetworkPlotter(output_dir=str(plots_dir))

    plot_files = []
    if lat_data.get("rtt_samples_ms"):
        p = plotter.plot_latency(lat_data)
        if p:
            plot_files.append(p)

    if jit_data.get("ipdv_samples_ms"):
        p = plotter.plot_jitter(jit_data)
        if p:
            plot_files.append(p)

    if loss_data.get("probe_timeline"):
        p = plotter.plot_packet_loss(loss_data)
        if p:
            plot_files.append(p)

    if tp_data and tp_data.get("samples"):
        p = plotter.plot_throughput(tp_data)
        if p:
            plot_files.append(p)

    if rtt_samples and congestion_data.get("events"):
        p = plotter.plot_congestion_analysis(rtt_samples, congestion_data["events"])
        if p:
            plot_files.append(p)

    # Dashboard
    p = plotter.plot_dashboard(
        latency_data=lat_data,
        jitter_data=jit_data,
        loss_data=loss_data,
        throughput_data=tp_data,
    )
    if p:
        plot_files.append(p)

    console.print(f"  Generated {len(plot_files)} plots")

    # --- HTML Report ---
    console.print("\n[bold]Generating HTML report...[/bold]")
    report_gen = ReportGenerator()
    report_gen.add_latency(lat_data)
    report_gen.add_jitter(jit_data)
    report_gen.add_packet_loss(loss_data)
    if tp_data:
        report_gen.add_throughput(tp_data)
    report_gen.add_congestion(congestion_data)
    for pf in plot_files:
        report_gen.add_plot(pf)
    report_gen.add_raw_data(all_results, "Complete Raw Data")

    report_path = report_gen.generate(str(output_dir / "report.html"))
    console.print(f"  Report: {report_path}")

    # Save combined results
    save_results(all_results, str(output_dir / "benchmark_results.json"))

    console.print(Panel(
        f"[bold green]Benchmark complete![/bold green]\n"
        f"Results: {output_dir}\n"
        f"Report: {report_path}",
        border_style="green",
    ))


# ---------------------------------------------------------------------------
# Visualization commands
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--input", "-i", "input_dir", required=True, help="Directory with measurement JSON files.")
@click.option("--output", "-o", default="plots", help="Output directory for plots.")
def visualize(input_dir, output):
    """Generate visualization plots from saved measurement results."""
    from visualization.plots import NetworkPlotter

    plotter = NetworkPlotter(output_dir=output)
    input_path = ensure_output_dir(input_dir)
    generated = []

    for filename in ["latency.json", "jitter.json", "packet_loss.json", "throughput.json"]:
        filepath = input_path / filename
        if filepath.exists():
            data = load_results(str(filepath)).get("results", {})
            method_name = filename.replace(".json", "")
            plot_method = getattr(plotter, f"plot_{method_name}", None)
            if plot_method:
                path = plot_method(data)
                if path:
                    generated.append(path)
                    console.print(f"  [green]Generated:[/green] {path}")

    console.print(f"\n[bold]Generated {len(generated)} plots in {output}/[/bold]")


@cli.command()
@click.option("--input", "-i", "input_dir", required=True, help="Directory with measurement JSON files.")
@click.option("--output", "-o", default="report.html", help="Output HTML file.")
def report(input_dir, output):
    """Generate an HTML report from saved measurement results."""
    from visualization.reports import ReportGenerator

    input_path = ensure_output_dir(input_dir)
    report_gen = ReportGenerator()

    for filename, method in [
        ("latency.json", "add_latency"),
        ("jitter.json", "add_jitter"),
        ("packet_loss.json", "add_packet_loss"),
        ("throughput.json", "add_throughput"),
    ]:
        filepath = input_path / filename
        if filepath.exists():
            data = load_results(str(filepath)).get("results", {})
            getattr(report_gen, method)(data)

    # Embed any plots
    plots_dir = input_path / "plots"
    if plots_dir.exists():
        for png in sorted(plots_dir.glob("*.png")):
            report_gen.add_plot(str(png))

    path = report_gen.generate(output)
    console.print(f"[bold green]Report generated:[/bold green] {path}")


if __name__ == "__main__":
    cli()
