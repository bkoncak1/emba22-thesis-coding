#!/usr/bin/env python3
"""vtt_to_md.py — Stap 1 van de transcriptiepijplijn.

Zet een Teams `.vtt`-captionbestand om naar een markdowntranscript.

Regels (zie PLAN.md, stap 1):
- Sprekerlabels staan per cue in `<v Naam>tekst</v>`-tags.
- Opeenvolgende cues van dezelfde spreker worden samengevoegd tot één beurt;
  het tijdstempel is de starttijd van de eerste cue van die beurt.
- Tijdformat is [HH:MM:SS], zonder milliseconden.
- Echte namen blijven behouden (pseudonimisering komt pas in stap 6).
- VTT-artefacten worden opgeschoond: cue-id's, align/position-attributen en
  dubbele tekstdelen door caption-overlap (Teams herhaalt soms tekst in
  opeenvolgende cues).

CLI:
    python vtt_to_md.py input.vtt -o output.md
    python vtt_to_md.py input.vtt --preview 20
"""

from __future__ import annotations

import argparse
import re
import string
import sys
from dataclasses import dataclass, field
from pathlib import Path

# --- Regex-patronen ----------------------------------------------------------

# Tijdcoderegel, bijv. "00:00:04.860 --> 00:00:07.640 align:start position:0%"
TIMESTAMP_RE = re.compile(
    r"^\s*(?P<start>(?:\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{1,3})\s*-->\s*"
    r"(?P<end>(?:\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{1,3})"
)

# Sprekerlabel in een cue: <v Naam> ... (evt. zonder sluittag)
SPEAKER_RE = re.compile(r"<v\s+([^>]+?)\s*>", re.IGNORECASE)

# Elke overgebleven tag (</v>, <c>, <i>, position-achtige rommel binnen tekst)
TAG_RE = re.compile(r"</?[^>]+>")

_PUNCT = str.maketrans("", "", string.punctuation)


# --- Datamodel ---------------------------------------------------------------


@dataclass
class Turn:
    """Eén samengevoegde sprekerbeurt."""

    speaker: str
    start_seconds: int
    words: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(self.words)


# --- Hulpfuncties ------------------------------------------------------------


def parse_timestamp(ts: str) -> int:
    """Zet een VTT-tijdcode om naar hele seconden (milliseconden vervallen)."""
    ts = ts.replace(",", ".")
    time_part = ts.split(".")[0]
    parts = [int(p) for p in time_part.split(":")]
    while len(parts) < 3:  # "MM:SS" -> "00:MM:SS"
        parts.insert(0, 0)
    hours, minutes, seconds = parts[-3], parts[-2], parts[-1]
    return hours * 3600 + minutes * 60 + seconds


def format_timestamp(total_seconds: int) -> str:
    """Formatteer seconden als [HH:MM:SS]."""
    hours, rem = divmod(total_seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _norm(word: str) -> str:
    """Normaliseer een woord voor overlapvergelijking (case/punctuatie negeren)."""
    return word.lower().translate(_PUNCT)


def merge_words(acc: list[str], new: list[str]) -> list[str]:
    """Voeg `new` toe aan `acc` en verwijder caption-overlap.

    Teams toont captions als een schuivend venster: opeenvolgende cues herhalen
    de laatste woorden van de vorige cue. We zoeken de langste suffix van `acc`
    die gelijk is aan een prefix van `new` en plakken alleen de rest erachter.
    """
    if not acc:
        return list(new)
    if not new:
        return acc

    acc_norm = [_norm(w) for w in acc]
    new_norm = [_norm(w) for w in new]

    max_k = min(len(acc), len(new))
    for k in range(max_k, 0, -1):
        if acc_norm[-k:] == new_norm[:k]:
            return acc + new[k:]
    return acc + new


# --- Kern: VTT -> beurten ----------------------------------------------------


def iter_cues(lines: list[str]):
    """Genereer (start_seconds, text) per cue uit de ruwe VTT-regels."""
    i = 0
    n = len(lines)
    while i < n:
        match = TIMESTAMP_RE.match(lines[i])
        if not match:
            i += 1
            continue
        start_seconds = parse_timestamp(match.group("start"))
        i += 1
        text_lines: list[str] = []
        while i < n and lines[i].strip() != "" and not TIMESTAMP_RE.match(lines[i]):
            text_lines.append(lines[i].strip())
            i += 1
        yield start_seconds, " ".join(text_lines).strip()


def parse_vtt(content: str) -> list[Turn]:
    """Parse VTT-inhoud naar een lijst samengevoegde sprekerbeurten."""
    lines = content.splitlines()
    turns: list[Turn] = []
    last_speaker: str | None = None

    for start_seconds, raw_text in iter_cues(lines):
        if not raw_text:
            continue

        speaker_match = SPEAKER_RE.search(raw_text)
        if speaker_match:
            speaker = speaker_match.group(1).strip()
        else:
            # Cue zonder sprekertag = voortzetting van de vorige spreker.
            speaker = last_speaker
        if speaker is None:
            # Tekst voordat een spreker bekend is; sla over (meestal ruis).
            continue

        text = TAG_RE.sub("", raw_text).strip()
        if not text:
            continue
        words = text.split()

        if turns and turns[-1].speaker == speaker:
            turns[-1].words = merge_words(turns[-1].words, words)
        else:
            turns.append(Turn(speaker=speaker, start_seconds=start_seconds, words=words))

        last_speaker = speaker

    return turns


def render_markdown(turns: list[Turn]) -> str:
    """Render beurten in het afgesproken markdownformat."""
    blocks = [
        f"**{t.speaker}** *[{format_timestamp(t.start_seconds)}]*\n\n{t.text}"
        for t in turns
    ]
    return "\n\n".join(blocks) + "\n"


# --- CLI ---------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Zet een Teams .vtt-captionbestand om naar een markdowntranscript."
    )
    parser.add_argument("input", type=Path, help="pad naar het .vtt-bestand")
    parser.add_argument(
        "-o", "--output", type=Path, default=None, help="pad voor het markdownbestand"
    )
    parser.add_argument(
        "--preview",
        type=int,
        metavar="N",
        default=None,
        help="print de eerste N sprekerbeurten naar stdout",
    )
    args = parser.parse_args(argv)

    if args.output is None and args.preview is None:
        parser.error("geef -o/--output op en/of --preview N")

    if not args.input.is_file():
        parser.error(f"inputbestand niet gevonden: {args.input}")

    content = args.input.read_text(encoding="utf-8-sig")
    turns = parse_vtt(content)

    if not turns:
        print("Waarschuwing: geen sprekerbeurten gevonden in de VTT.", file=sys.stderr)

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(render_markdown(turns), encoding="utf-8")
        print(
            f"{len(turns)} sprekerbeurten geschreven naar {args.output}",
            file=sys.stderr,
        )

    if args.preview is not None:
        preview = turns[: args.preview]
        print(render_markdown(preview), end="")
        if len(turns) > args.preview:
            print(
                f"\n… ({len(turns) - args.preview} beurten meer)",
                file=sys.stderr,
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
