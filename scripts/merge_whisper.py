#!/usr/bin/env python3
"""
merge_whisper.py — stap 3-hulpmiddel

Injecteert de whisper.cpp-tekst in de structuur van het Teams-transcript
(sprekerlabels + timestamps blijven van Teams; de woorden komen van whisper
waar de twee verschillen). Deterministisch, geen LLM.

Schrijft TWEE bestanden naast het Teams-transcript:

  <naam>_gecorrigeerd.md   schone versie: whisper-variant toegepast
  <naam>_gemarkeerd.md     zelfde inhoud, wijzigingen gemarkeerd (CriticMarkup):
                             {~~teams~>whisper~~}   vervangen
                             {++whisper++}          door Teams gemist
                             {--teams--}            alleen in Teams

Werkwijze stap 3: open de gemarkeerde versie, luister de audio alléén op de
gemarkeerde plekken na, en werk de schone versie bij waar whisper het ook
fout had. Het origineel wordt nooit overschreven.

Gebruik:
    python scripts/merge_whisper.py transcripts/i01.md raw/i01_whisper.txt
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from difflib import SequenceMatcher

SPEAKER_RE = re.compile(r"^\*\*(?P<sp>.+?)\*\*\s*\*\[(?P<ts>\d{1,2}:\d{2}:\d{2})\]\*\s*$")
WHISPER_TS_RE = re.compile(
    r"\[?\d{1,2}:\d{2}:\d{2}[.,]\d{3}\s*-->\s*\d{1,2}:\d{2}:\d{2}[.,]\d{3}\]?"
)
WORD_RE = re.compile(r"[\w'’]+", re.UNICODE)


def norm(w: str) -> str:
    return w.lower().replace("’", "'")


def parse_teams(path: Path):
    """Turns: list van dicts {header, text}; tokens: (norm, turn_idx, start, end)."""
    turns: list[dict] = []
    tokens: list[tuple[str, int, int, int]] = []
    cur: list[str] = []
    header = None

    def flush():
        nonlocal cur, header
        if header is not None:
            turns.append({"header": header, "text": "\n".join(cur).strip("\n")})
        cur, header_ = [], None

    for line in path.read_text(encoding="utf-8").splitlines():
        m = SPEAKER_RE.match(line.strip())
        if m:
            if header is not None:
                turns.append({"header": header, "text": "\n".join(cur).strip("\n")})
            header, cur = line.strip(), []
        elif header is not None:
            cur.append(line)
    if header is not None:
        turns.append({"header": header, "text": "\n".join(cur).strip("\n")})

    if not turns:
        sys.exit(f"Geen spreekbeurten gevonden in {path} — is dit output van vtt_to_md.py?")

    for ti, turn in enumerate(turns):
        for m in WORD_RE.finditer(turn["text"]):
            tokens.append((norm(m.group()), ti, m.start(), m.end()))
    return turns, tokens


def parse_whisper(path: Path) -> list[str]:
    text = WHISPER_TS_RE.sub(" ", path.read_text(encoding="utf-8", errors="replace"))
    words = [m.group() for m in WORD_RE.finditer(text)]
    if not words:
        sys.exit(f"Geen tekst gevonden in {path}.")
    return words


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("teams_md", type=Path)
    ap.add_argument("whisper_txt", type=Path)
    ap.add_argument("-o", "--output-dir", type=Path, default=None,
                    help="Outputmap (default: naast het Teams-transcript)")
    args = ap.parse_args()

    turns, t_tokens = parse_teams(args.teams_md)
    w_words = parse_whisper(args.whisper_txt)
    w_norm = [norm(w) for w in w_words]
    t_norm = [t[0] for t in t_tokens]

    sm = SequenceMatcher(a=w_norm, b=t_norm, autojunk=False)

    # edits per turn: (start, end, teams_str, whisper_str, soort)
    edits: dict[int, list[tuple[int, int, str, str, str]]] = {}
    n_replace = n_insert = n_delete = 0

    def add(turn_idx, start, end, teams_str, whisper_str, soort):
        edits.setdefault(turn_idx, []).append((start, end, teams_str, whisper_str, soort))

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        wtxt = " ".join(w_words[i1:i2])
        if tag == "replace":
            n_replace += 1
            # groepeer Teams-tokens per turn; whisper-woorden gaan naar het
            # eerste deel als de span een beurtgrens kruist (zeldzaam)
            span = t_tokens[j1:j2]
            by_turn: dict[int, list] = {}
            for tok in span:
                by_turn.setdefault(tok[1], []).append(tok)
            first = True
            for ti, toks in by_turn.items():
                s, e = toks[0][2], toks[-1][3]
                ttxt = turns[ti]["text"][s:e]
                if first:
                    add(ti, s, e, ttxt, wtxt, "replace")
                    first = False
                else:
                    add(ti, s, e, ttxt, "", "delete")
        elif tag == "delete":  # whisper heeft het, Teams niet → invoegen
            n_insert += 1
            if j1 > 0:
                _, ti, _, e = t_tokens[j1 - 1]
                add(ti, e, e, "", wtxt, "insert")
            else:
                _, ti, s, _ = t_tokens[0]
                add(ti, s, s, "", wtxt, "insert")
        elif tag == "insert":  # alleen in Teams → verwijderen
            n_delete += 1
            span = t_tokens[j1:j2]
            by_turn: dict[int, list] = {}
            for tok in span:
                by_turn.setdefault(tok[1], []).append(tok)
            for ti, toks in by_turn.items():
                s, e = toks[0][2], toks[-1][3]
                add(ti, s, e, turns[ti]["text"][s:e], "", "delete")

    def render(marked: bool) -> str:
        out_turns = []
        for ti, turn in enumerate(turns):
            text = turn["text"]
            for s, e, ttxt, wtxt, soort in sorted(edits.get(ti, []), reverse=True):
                if soort == "replace":
                    rep = f"{{~~{ttxt}~>{wtxt}~~}}" if marked else wtxt
                elif soort == "insert":
                    rep = f" {{++{wtxt}++}}" if marked else f" {wtxt}"
                else:  # delete
                    rep = f"{{--{ttxt}--}}" if marked else ""
                text = text[:s] + rep + text[e:]
            if not marked:
                text = re.sub(r"[ \t]{2,}", " ", text)
                text = re.sub(r" +([,.;:!?])", r"\1", text)
            out_turns.append(f"{turn['header']}\n\n{text.strip()}")
        return "\n\n".join(out_turns) + "\n"

    out_dir = args.output_dir or args.teams_md.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = args.teams_md.stem
    clean_path = out_dir / f"{stem}_gecorrigeerd.md"
    marked_path = out_dir / f"{stem}_gemarkeerd.md"
    clean_path.write_text(render(marked=False), encoding="utf-8")
    marked_path.write_text(render(marked=True), encoding="utf-8")

    total = n_replace + n_insert + n_delete
    print(f"Wijzigingen toegepast : {total} (vervangen {n_replace}, "
          f"ingevoegd {n_insert}, verwijderd {n_delete})")
    print(f"Schoon    → {clean_path}")
    print(f"Gemarkeerd→ {marked_path}")
    print("Let op: whisper is referentie, geen waarheid — loop de markeringen "
          "na tegen de audio en corrigeer in de schone versie.")


if __name__ == "__main__":
    main()
