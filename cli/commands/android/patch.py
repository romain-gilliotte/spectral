"""APK patching to trust user CA certificates and bypass cert pinning."""
# pyright: reportMissingTypeStubs=false, reportUnknownVariableType=false

from __future__ import annotations

import asyncio
from pathlib import Path
import tempfile

import click

_MITMPROXY_CERT = Path.home() / ".mitmproxy" / "mitmproxy-ca-cert.pem"


# ── Public API ────────────────────────────────────────────────────


def patch_apk(apk_path: Path, output_path: Path) -> Path:
    """Patch a .apk or .apks bundle to bypass cert pinning for MITM.

    Uses apk-mitm-python for comprehensive patching: network security config,
    smali-level cert pinning bypass (javax, OkHttp), and certificate embedding.
    For .apks bundles, all APKs are re-signed with a shared keystore.
    """
    is_bundle = apk_path.suffix == ".apks"
    asyncio.run(_run_apk_mitm(apk_path, output_path, is_bundle=is_bundle))
    return output_path


# ── Internals ─────────────────────────────────────────────────────


async def _run_apk_mitm(
    input_path: Path, output_path: Path, *, is_bundle: bool = False
) -> None:
    """Run apk-mitm-python's patch pipeline."""
    from apk_mitm.patch_apk import patch_apk as _patch_apk
    from apk_mitm.patch_app_bundle import patch_apks_bundle
    from apk_mitm.tools.apktool import Apktool, ApktoolOptions
    from apk_mitm.tools.uber_apk_signer import UberApkSigner

    cert = str(_MITMPROXY_CERT) if _MITMPROXY_CERT.exists() else None
    patch_fn = patch_apks_bundle if is_bundle else _patch_apk

    with tempfile.TemporaryDirectory(prefix="apk_patch_") as tmp_dir:
        task = patch_fn({
            "input_path": str(input_path),
            "output_path": str(output_path),
            "certificate_path": cert,
            "apktool": Apktool(ApktoolOptions(framework_path=f"{tmp_dir}/framework")),
            "uber_apk_signer": UberApkSigner(),
            "tmp_dir": tmp_dir,
            "is_app_bundle": is_bundle,
            "skip_patches": False,
            "skip_decode": False,
            "debuggable": False,
            "wait": False,
        })
        await task.run()  # pyright: ignore[reportUnknownMemberType]


@click.command()
@click.argument("apk_path", type=click.Path(exists=True))
@click.option(
    "-o",
    "--output",
    default=None,
    help="Output path for the patched file (.apk or .apks)",
)
def patch_cmd(apk_path: str, output: str | None) -> None:
    """Patch a .apk or .apks bundle to bypass cert pinning for MITM."""
    from cli.helpers.console import console

    apk = Path(apk_path)
    out = Path(output) if output else apk.with_stem(apk.stem + "-patched")

    console.print(f"[bold]Patching:[/bold] {apk}")
    patch_apk(apk, out)
    console.print(f"[green]Patched file saved to {out}[/green]")

    console.print()
    console.print("[bold]Next steps:[/bold]")
    console.print(f"  1. Install: spectral android install {out}")
    console.print("  2. Start proxy: spectral capture proxy -d <domain>")
