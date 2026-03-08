#!/usr/bin/env python3
"""
Generate the asciinema .cast file for the Spectral README demo.

The recording is fully scripted — no real CLI execution needed.

Usage:
    python demo/generate_cast.py                    # → demo/demo.cast
    asciinema play demo/demo.cast                   # preview locally
    asciinema upload demo/demo.cast                 # upload to asciinema.org
    agg demo/demo.cast assets/demo.gif              # convert to GIF (needs agg)
"""

import json
from pathlib import Path
import sys

COLS = 96
ROWS = 24

# ANSI escape codes
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
MAGENTA = "\033[35m"
RESET = "\033[0m"


class Cast:
    """Builds an asciinema v2 .cast recording."""

    def __init__(self):
        self._events: list[list] = []
        self._t = 0.0

    # -- primitives -----------------------------------------------------------

    def wait(self, s: float):
        self._t += s

    def out(self, text: str):
        self._events.append([round(self._t, 4), "o", text])

    def nl(self):
        self.out("\r\n")

    def line(self, text: str = "", pause: float = 0.015):
        self.out(text + "\r\n")
        self.wait(pause)

    def type(self, text: str, delay: float = 0.032):
        for ch in text:
            self.out(ch)
            self.wait(delay)

    # -- higher-level ---------------------------------------------------------

    def cmd(self, command: str, pre: float = 0.4):
        """Shell prompt + typed command."""
        self.wait(pre)
        self.out(f"{GREEN}${RESET} ")
        self.wait(0.12)
        self.type(command)
        self.wait(0.08)
        self.nl()
        self.wait(0.3)

    def user_prompt(self, text: str, pre: float = 0.8):
        """Claude Code '>' prompt with user typing."""
        self.wait(pre)
        self.out(f"{CYAN}>{RESET} ")
        self.wait(0.3)
        self.type(text, delay=0.038)
        self.wait(0.15)
        self.nl()
        self.nl()

    def tool_call(self, name: str, params: str, pre: float = 0.8):
        """Claude Code MCP tool call — matches real Claude Code output."""
        self.wait(pre)
        self.out(f"  {MAGENTA}●{RESET} spectral - {name} {DIM}(MCP){RESET}({params})\r\n")
        self.wait(0.3)
        self.out(f"    {DIM}└ Running…{RESET}")
        self.wait(1.0)
        # Overwrite "Running…" with result
        self.out(f"\r    └ HTTP 200\r\n")
        self.wait(0.3)

    def response(self, first: str, *rest: str, pre: float = 0.3):
        """Claude response lines — green dot on first line like real Claude Code."""
        self.wait(pre)
        self.line(f"  {GREEN}●{RESET} {first}", pause=0.025)
        for l in rest:
            self.line(f"    {l}", pause=0.025)

    # -- serialization --------------------------------------------------------

    def serialize(self, title: str) -> str:
        header = {
            "version": 2,
            "width": COLS,
            "height": ROWS,
            "env": {"TERM": "xterm-256color", "SHELL": "/bin/bash"},
            "title": title,
        }
        return (
            "\n".join(
                [json.dumps(header)] + [json.dumps(e) for e in self._events]
            )
            + "\n"
        )


# =============================================================================
# Demo script
# =============================================================================


def record() -> Cast:
    c = Cast()

    # ── Scene 1: we have captures ───────────────────────

    c.cmd("spectral capture list")
    c.wait(0.3)

    c.line(f"{BOLD}Apps{RESET}")
    c.line("┏━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━┓")
    c.line(
        f"┃ {CYAN}Name{RESET}       "
        f"┃ {CYAN}Display Name{RESET}       "
        f"┃ {CYAN}Captures{RESET} "
        f"┃ {CYAN}Last Updated{RESET} ┃"
    )
    c.line("┡━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━┩")
    c.line("│ airbnb     │ Airbnb             │        1 │ 2026-02-19   │")
    c.line("│ spotify    │ Spotify            │        2 │ 2026-02-27   │")
    c.line("│ tado       │ Tado               │        2 │ 2026-03-05   │")
    c.line("│ uber       │ Uber               │        3 │ 2026-03-08   │")
    c.line("└────────────┴────────────────────┴──────────┴──────────────┘")

    # ── Scene 2: analyze ────────────────────────────────

    c.cmd("spectral mcp analyze tado")
    c.wait(0.3)

    c.line(f"{BOLD}Loading captures for app:{RESET} tado")
    c.wait(0.15)
    c.line("  Loaded 2 capture(s): 47 traces, 0 WS connections, 12 contexts")
    c.wait(0.3)
    c.line()

    c.line(f"{BOLD}Generating MCP tools with LLM (claude-sonnet-4-5-20250929)...{RESET}")
    c.wait(0.4)
    c.line("  API base URL: https://my.tado.com")
    c.line("  Kept 43/47 traces under https://my.tado.com")
    c.wait(0.2)
    c.line("  Identifying capabilities and building tools...")
    c.wait(0.3)

    # Trace evaluations — quick glimpse of the pattern
    traces = [
        ("t_001_0001", None),
        ("t_001_0002", "get_home_details"),
        ("t_001_0003", None),
        ("t_001_0004", "list_home_zones"),
        ("t_001_0005", "get_zone_state"),
        ("t_001_0006", None),
    ]
    for tid, tool in traces:
        if tool:
            c.line(
                f"  Evaluating {tid}... useful → building {BOLD}{tool}{RESET}",
                pause=0.1,
            )
        else:
            c.line(f"  Evaluating {tid}... {DIM}skip{RESET}", pause=0.06)

    c.line(f"  {DIM}... (37 more traces){RESET}")
    c.wait(0.2)
    c.line(f"  Extracted 19 tool(s).")
    c.wait(0.3)
    c.line()

    c.line(f"{GREEN}Wrote 19 tool(s) to storage{RESET}")
    tools = [
        ("get_home_details", "GET", "/api/v2/homes/{home_id}"),
        ("list_home_zones", "GET", "/api/v2/homes/{home_id}/zones"),
        ("get_zone_state", "GET", "/api/v2/homes/{home_id}/zones/{zone_id}/state"),
    ]
    for name, method, path in tools:
        c.line(f"  Tool: {name} — {method} {path}", pause=0.02)
    c.line(f"  {DIM}... (16 more tools){RESET}")
    c.line()
    c.line(f"  {DIM}LLM token usage: 142,831 input, 8,429 output (~$0.52){RESET}")

    # ── Scene 3: auth ───────────────────────────────────

    c.cmd("spectral auth login tado")
    c.wait(0.3)
    c.line(f"{BOLD}Logging in to tado...{RESET}")
    c.wait(1.2)
    c.line(f"{GREEN}Login successful. Token saved.{RESET}")

    # ── Scene 4: Claude uses the API ────────────────────

    c.cmd("claude")
    c.wait(0.8)
    c.line()
    c.line(f"  {BOLD}✻ Claude Code{RESET}")
    c.line()

    # First interaction
    c.user_prompt("What's the temperature in my living room?")
    c.tool_call("tado_get_zone_state", 'zone_id: "1"')
    c.response(
        f"The living room is currently at {BOLD}21.3°C{RESET} (target: 22°C).",
        "Humidity is at 45%. The heating is active.",
    )

    c.line()
    c.wait(3.0)

    # Second interaction
    c.user_prompt("Set it to 23 degrees")
    c.tool_call(
        "tado_set_zone_temperature_overlay",
        'zone_id: "1", temperature: 23.0',
    )
    c.response(
        "Done! I've set the living room to 23°C.",
        "The heating will adjust to reach the new target.",
    )

    c.line()
    c.wait(3.0)

    # Third interaction — switch to Uber, show cross-app usage
    c.user_prompt("How much would an Uber cost from SFO to downtown?")
    c.tool_call(
        "uber_get_price_estimate",
        'start: "SFO", end: "Union Square, SF"',
    )
    c.response(
        "Here are the estimates from SFO to Union Square:",
        "",
        f"  {BOLD}UberX{RESET}      $32–41  (24 min)",
        f"  {BOLD}Comfort{RESET}    $40–52  (24 min)",
        f"  {BOLD}UberXL{RESET}     $50–65  (24 min)",
        f"  {BOLD}Black{RESET}      $78–95  (24 min)",
        "",
        "Prices may vary with demand. Want me to request a ride?",
    )

    c.wait(5.0)

    return c


def main():
    c = record()
    cast = c.serialize("Spectral — Turn any app into an API for Claude")

    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "demo.cast"
    out.write_text(cast)

    print(f"✓ Written to {out}")
    print(f"  Preview:  asciinema play {out}")
    print(f"  Upload:   asciinema upload {out}")
    print(f"  To GIF:   agg {out} assets/demo.gif")


if __name__ == "__main__":
    main()
