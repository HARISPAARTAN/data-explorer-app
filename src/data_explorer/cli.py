"""Command line: ``data-explorer run`` starts the app with Streamlit, ``samples`` copies the samples.

The module imports only the standard library, click and the package version, so ``--version`` and
``--help`` answer without loading pandas or Streamlit.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import click

from data_explorer import __version__

PACKAGE = Path(__file__).resolve().parent
APP = PACKAGE / "app" / "streamlit_app.py"
SAMPLES_DIR = PACKAGE / "samples"
SAMPLE_FILES = ("retail_orders.csv", "sensor_readings.csv", "client_survey.xlsx")
CONFIG_FLAGS = (
    "--server.maxUploadSize=50",
    "--server.runOnSave=false",
    "--client.toolbarMode=viewer",
    "--client.showSidebarNavigation=false",
    "--browser.gatherUsageStats=false",
    "--theme.base=dark",
    "--theme.primaryColor=#F2A93B",
    "--theme.backgroundColor=#0B0F14",
    "--theme.secondaryBackgroundColor=#121820",
    "--theme.textColor=#E6EDF3",
)


def streamlit_command(host: str, port: int) -> list[str]:
    """The command that starts the packaged app, with the settings of ``.streamlit/config.toml``."""
    return [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(APP),
        f"--server.address={host}",
        f"--server.port={port}",
        "--server.headless=true",
        *CONFIG_FLAGS,
    ]


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="data-explorer-app", message="%(prog)s %(version)s")
def main() -> None:
    """Meridian Data Explorer: profile, check, filter, chart and export CSV and Excel files."""


@main.command()
@click.option("--host", default="127.0.0.1", show_default=True, help="Address the server listens on.")
@click.option(
    "--port",
    default=8501,
    show_default=True,
    type=click.IntRange(1, 65535),
    help="Port the server listens on.",
)
@click.option("--dry-run", is_flag=True, help="Print the Streamlit command instead of running it.")
@click.pass_context
def run(ctx: click.Context, host: str, port: int, dry_run: bool) -> None:
    """Start the app on a local Streamlit server."""
    command = streamlit_command(host, port)
    if dry_run:
        click.echo(shlex.join(command))
        return
    try:
        process = subprocess.Popen(command)
    except OSError as exc:
        raise click.ClickException(f"Could not start Streamlit: {exc}") from exc
    try:
        code = process.wait()
    except KeyboardInterrupt:
        code = process.wait()
    ctx.exit(code)


@main.command()
@click.option(
    "--out",
    required=True,
    type=click.Path(path_type=Path),
    help="Folder for the three sample files; created if missing, must be empty.",
)
def samples(out: Path) -> None:
    """Copy the three sample datasets into a folder."""
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise click.ClickException(f"{out} is not an empty folder.")
    try:
        out.mkdir(parents=True, exist_ok=True)
        for name in SAMPLE_FILES:
            shutil.copyfile(SAMPLES_DIR / name, out / name)
            click.echo(f"Wrote {out / name}")
    except OSError as exc:
        raise click.ClickException(f"Could not write the samples: {exc}") from exc
