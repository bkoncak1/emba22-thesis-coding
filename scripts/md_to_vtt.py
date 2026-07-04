#!/usr/bin/env python3
"""md_to_vtt.py — Markdowntranscript terug naar Teams-stijl WebVTT.

Zet een markdowntranscript (zoals geproduceerd door vtt_to_md.py, daarna
handmatig gecorrigeerd) om naar een .vtt-bestand dat Atlas.ti als
tijd-gesynchroniseerd transcript kan importeren.

Let op de beperking: vtt_to_md.py voegt opeenvolgende cues van dezelfde spreker
samen, dus de oorspronkelijke per-cue timings en eindtijden zijn niet meer
beschikbaar. Elke spreekbeurt wordt hier één VTT-cue:
- starttijd  = het tijdstempel uit de markdownkop (het anker);
- eindtijd    = de starttijd van de volgende beurt (aaneengesloten transcript);
- de laatste beurt krijgt een vaste duur (zie --last-cue-seconds).

Privacy: gebruik dit pas op een tekst waarvan je weet welke fase het is. Een
gecorrigeerd markdownbestand bevat nog echte namen (pseudonimisering is stap 6).

CLI:
    python md_to_vtt.py transcript.md -o transcript.vtt
    python md_to_vtt.py transcript.md -o transcript.vtt --last-cue-seconds 15
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Sprekerkop: **Naam** *[HH:MM:SS]*  (uur is optioneel: ook [MM:SS] wordt geaccepteerd)
HEADER_RE = re.compile(
    r"^\*\*(?P<speaker>.+?)\*\*\s*\*\[(?P<ts>(?:\d{1,2}:)?\d{1,2}:\d{2})\]\*\s*$"
)


@dataclass
class Turn:
    speaker: str
    start_seconds: int
    lines: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        # Regels binnen een beurt samenvoegen tot één cue-tekst.
        return " ".join(line.strip() for line in self.lines if line.strip())


def parse_timestamp(ts: str) -> int:
    """Zet [HH:MM:SS] of [MM:SS] om naar hele seconden."""
    parts = [int(p) for p in ts.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    hours, minutes, seconds = parts[-3], parts[-2], parts[-1]
    return hours * 3600 + minutes * 60 + seconds


def format_vtt_timestamp(total_seconds: int) -> str:
    """Formatteer seconden als HH:MM:SS.000 (VTT vereist milliseconden)."""
    hours, rem = divmod(total_seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.000"


def parse_markdown(content: str) -> list[Turn]:
    """Parse het markdowntranscript naar spreekbeurten."""
    turns: list[Turn] = []
    current: Turn | None = None

    for line in content.splitlines():
        match = HEADER_RE.match(line.strip())
        if match:
            current = Turn(
                speaker=match.group("speaker").strip(),
                start_seconds=parse_timestamp(match.group("ts")),
            )
            turns.append(current)
        elif current is not None:
            current.lines.append(line)
        # Regels vóór de eerste kop (bijv. een titel) worden genegeerd.

    return [t for t in turns if t.text]


def render_vtt(turns: list[Turn], last_cue_seconds: int) -> str:
    """Render spreekbeurten als WebVTT met <v Naam>-sprekerlabels."""
    blocks = ["WEBVTT", ""]
    for index, turn in enumerate(turns):
        start = turn.start_seconds
        if index + 1 < len(turns):
            end = turns[index + 1].start_seconds
            # Beschermen tegen niet-oplopende timestamps (bijv. na correctie).
            if end <= start:
                end = start + last_cue_seconds
        else:
            end = start + last_cue_seconds

        blocks.append(
            f"{format_vtt_timestamp(start)} --> {format_vtt_timestamp(end)}"
        )
        blocks.append(f"<v {turn.speaker}>{turn.text}</v>")
        blocks.append("")

    return "\n".join(blocks)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Zet een markdowntranscript om naar een WebVTT-bestand voor Atlas.ti."
    )
    parser.add_argument("input", type=Path, help="pad naar het markdownbestand")
    parser.add_argument(
        "-o", "--output", type=Path, required=True, help="pad voor het .vtt-bestand"
    )
    parser.add_argument(
        "--last-cue-seconds",
        type=int,
        default=10,
        metavar="N",
        help="duur (in seconden) van de laatste cue, want een eindtijd ontbreekt "
        "(standaard: 10)",
    )
    args = parser.parse_args(argv)

    if not args.input.is_file():
        parser.error(f"inputbestand niet gevonden: {args.input}")

    content = args.input.read_text(encoding="utf-8-sig")
    turns = parse_markdown(content)

    if not turns:
        print(
            "Waarschuwing: geen sprekerbeurten gevonden. Klopt het markdownformat "
            "(**Naam** *[HH:MM:SS]*)?",
            file=sys.stderr,
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_vtt(turns, args.last_cue_seconds), encoding="utf-8")
    print(
        f"{len(turns)} cues geschreven naar {args.output}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
