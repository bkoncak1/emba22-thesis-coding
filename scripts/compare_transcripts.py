#!/usr/bin/env python3
"""
compare_transcripts.py — stap 2/3-hulpmiddel

Vergelijkt het Teams-transcript (markdown uit stap 1, vtt_to_md.py) met een
whisper.cpp-transcript (.txt) en rapporteert:

  1. Gelijkenispercentage en WER (Word Error Rate) van Teams t.o.v. whisper
     als referentie.
  2. Een markdown-verschillentabel met per verschil de dichtstbijzijnde
     Teams-timestamp, zodat je gericht tegen de audio kunt corrigeren.
  3. Een frequentielijst van woordparen die Teams structureel anders
     interpreteert dan whisper.

De tabel (…_diff.md) kun je daarna door het lokale Ollama-model laten
beoordelen (Modelfile.transcheck) om verschillen te prioriteren.

Draait volledig lokaal, geen dependencies buiten de standaardbibliotheek.

Gebruik:
    python scripts/compare_transcripts.py transcripts/i01.md raw/i01_whisper.txt -o qc/i01
"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
from collections import Counter
from pathlib import Path

SPEAKER_RE = re.compile(r"^\*\*(?P<sp>.+?)\*\*\s*\*\[(?P<ts>\d{1,2}:\d{2}:\d{2})\]\*\s*$")
# whisper.cpp kan met timestamps exporteren: [00:00:00.000 --> 00:00:05.120]
WHISPER_TS_RE = re.compile(
    r"\[?\d{1,2}:\d{2}:\d{2}[.,]\d{3}\s*-->\s*\d{1,2}:\d{2}:\d{2}[.,]\d{3}\]?"
)
TOKEN_SPLIT_RE = re.compile(r"[^\w'’]+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    """Lowercase, interpunctie eruit, splitsen op woorden."""
    text = text.lower().replace("’", "'")
    return [t for t in TOKEN_SPLIT_RE.split(text) if t]


def parse_teams_md(path: Path) -> list[tuple[str, str]]:
    """Geeft lijst van (woord, timestamp) terug; timestamp = kop van de spreekbeurt."""
    words: list[tuple[str, str]] = []
    ts = "00:00:00"
    for line in path.read_text(encoding="utf-8").splitlines():
        m = SPEAKER_RE.match(line.strip())
        if m:
            ts = m.group("ts")
            continue
        for w in tokenize(line):
            words.append((w, ts))
    if not words:
        sys.exit(f"Geen tekst gevonden in {path} — is dit output van vtt_to_md.py?")
    return words


def parse_whisper_txt(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    text = WHISPER_TS_RE.sub(" ", text)
    words = tokenize(text)
    if not words:
        sys.exit(f"Geen tekst gevonden in {path}.")
    return words


def context(words: list[str], start: int, end: int, width: int = 4) -> tuple[str, str]:
    pre = " ".join(words[max(0, start - width) : start])
    post = " ".join(words[end : end + width])
    return pre, post


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("teams_md", type=Path, help="Teams-transcript (markdown, stap 1)")
    ap.add_argument("whisper_txt", type=Path, help="whisper.cpp-transcript (.txt)")
    ap.add_argument("-o", "--output-prefix", type=Path, default=None,
                    help="Prefix voor outputbestanden (default: qc/<naam teams-md>)")
    ap.add_argument("--max-rows", type=int, default=400,
                    help="Maximaal aantal rijen in de verschillentabel (default 400)")
    args = ap.parse_args()

    teams = parse_teams_md(args.teams_md)
    teams_words = [w for w, _ in teams]
    whisper_words = parse_whisper_txt(args.whisper_txt)

    prefix = args.output_prefix or Path("qc") / args.teams_md.stem
    prefix.parent.mkdir(parents=True, exist_ok=True)

    sm = difflib.SequenceMatcher(a=whisper_words, b=teams_words, autojunk=False)
    opcodes = sm.get_opcodes()

    hits = subs = dels = ins = 0
    rows: list[dict] = []
    word_pairs: Counter[tuple[str, str]] = Counter()

    for tag, i1, i2, j1, j2 in opcodes:
        ref_n, hyp_n = i2 - i1, j2 - j1
        if tag == "equal":
            hits += ref_n
            continue
        if tag == "replace":
            subs += min(ref_n, hyp_n)
            dels += max(0, ref_n - hyp_n)
            ins += max(0, hyp_n - ref_n)
            if ref_n == hyp_n:
                for k in range(ref_n):
                    word_pairs[(whisper_words[i1 + k], teams_words[j1 + k])] += 1
        elif tag == "delete":   # in whisper, niet in Teams → Teams mist dit
            dels += ref_n
        elif tag == "insert":   # in Teams, niet in whisper → Teams voegt toe
            ins += hyp_n

        anchor = j1 - 1 if tag == "delete" and j1 > 0 else j1
        ts = teams[min(anchor, len(teams) - 1)][1]
        pre, post = context(whisper_words, i1, i2)
        rows.append({
            "ts": ts,
            "soort": {"replace": "anders", "delete": "ontbreekt in Teams", "insert": "extra in Teams"}[tag],
            "whisper": " ".join(whisper_words[i1:i2]) or "—",
            "teams": " ".join(teams_words[j1:j2]) or "—",
            "context": f"… {pre} **[·]** {post} …".strip(),
        })

    n_ref = len(whisper_words)
    wer = (subs + dels + ins) / n_ref if n_ref else 0.0
    similarity = sm.ratio()

    # --- samenvatting + tabel wegschrijven -------------------------------
    diff_path = prefix.with_name(prefix.name + "_diff.md")
    lines = [
        f"# Transcriptvergelijking: {args.teams_md.name} vs {args.whisper_txt.name}",
        "",
        "## Samenvatting",
        "",
        f"- Woorden whisper (referentie): **{n_ref}**",
        f"- Woorden Teams: **{len(teams_words)}**",
        f"- Overeenkomend: **{hits}** ({hits / n_ref:.1%} van referentie)",
        f"- Gelijkenis (SequenceMatcher): **{similarity:.1%}**",
        f"- WER Teams t.o.v. whisper: **{wer:.1%}** "
        f"(vervangen {subs}, ontbrekend {dels}, extra {ins})",
        "",
        "> Interpretatie: whisper is hier referentie, maar is zelf ook niet",
        "> foutloos. Gebruik de tabel als *zoeklijst* voor de audiocorrectie,",
        "> niet als waarheid.",
        "",
        "## Meest voorkomende woordverschillen (whisper → Teams)",
        "",
        "| whisper | Teams | aantal |",
        "|---|---|---:|",
    ]
    for (w_ref, w_hyp), n in word_pairs.most_common(30):
        lines.append(f"| {w_ref} | {w_hyp} | {n} |")
    if not word_pairs:
        lines.append("| — | — | 0 |")

    lines += [
        "",
        f"## Verschillen op volgorde ({min(len(rows), args.max_rows)} van {len(rows)})",
        "",
        "| Timestamp | Soort | whisper zegt | Teams zegt | Context (whisper) |",
        "|---|---|---|---|---|",
    ]
    for r in rows[: args.max_rows]:
        lines.append(
            f"| {r['ts']} | {r['soort']} | {r['whisper']} | {r['teams']} | {r['context']} |"
        )
    diff_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Whisper-woorden : {n_ref}")
    print(f"Teams-woorden   : {len(teams_words)}")
    print(f"Gelijkenis      : {similarity:.1%}")
    print(f"WER (Teams)     : {wer:.1%}  (S={subs} D={dels} I={ins})")
    print(f"Verschillen     : {len(rows)} blokken → {diff_path}")


if __name__ == "__main__":
    main()
