#!/usr/bin/env python3
"""find_entities.py — Stap 4 van de transcriptiepijplijn.

Extraheert kandidaat-identificatoren (PERSON en ORG) uit een gecorrigeerd
markdowntranscript met spaCy (model nl_core_news_lg).

Output: entities_<interview>.csv met kolommen:
    entiteit, type, aantal_voorkomens, voorbeeldzin

De lijst is gededupliceerd en gesorteerd op frequentie. Dit is een
KANDIDATENLIJST ter review — geen automatische vervanging. spaCy mist indirecte
identificatoren (projectnamen, locaties, unieke functietitels); die vul je
handmatig aan in de CSV vóór stap 6 (pseudonimiseren).

Sprekerlabels (**Naam**) worden ook als PERSON-kandidaat meegenomen, want dat
zijn per definitie identificatoren.

CLI:
    python find_entities.py transcript.md
    python find_entities.py transcript.md -o entities/entities_l01.csv
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

MODEL = "nl_core_news_lg"
WANTED_LABELS = {"PERSON", "ORG"}

# Sprekerkop: **Naam** *[HH:MM:SS]*
HEADER_RE = re.compile(
    r"^\*\*(?P<speaker>.+?)\*\*\s*\*\[(?:\d{1,2}:)?\d{1,2}:\d{2}(?::\d{2})?\]\*\s*$"
)

_WS_RE = re.compile(r"\s+")


@dataclass
class Turn:
    speaker: str
    lines: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(line.strip() for line in self.lines if line.strip())


@dataclass
class Entity:
    surface: str  # weergavevorm (eerste voorkomen)
    label: str
    count: int = 0
    example: str = ""


def normalize(text: str) -> str:
    """Normaliseer voor deduplicatie: witruimte samentrekken, lowercase."""
    return _WS_RE.sub(" ", text).strip().lower()


def parse_markdown(content: str) -> list[Turn]:
    """Split het markdowntranscript in spreekbeurten (spreker + tekst)."""
    turns: list[Turn] = []
    current: Turn | None = None
    for line in content.splitlines():
        match = HEADER_RE.match(line.strip())
        if match:
            current = Turn(speaker=match.group("speaker").strip())
            turns.append(current)
        elif current is not None:
            current.lines.append(line)
    return turns


def collect_entities(turns: list[Turn], nlp) -> list[Entity]:
    """Draai NER over de tekst en verzamel PERSON/ORG-kandidaten."""
    entities: dict[tuple[str, str], Entity] = {}

    def add(surface: str, label: str, example: str) -> None:
        surface = surface.strip()
        if not surface:
            return
        key = (normalize(surface), label)
        entity = entities.get(key)
        if entity is None:
            entity = Entity(surface=surface, label=label)
            entities[key] = entity
        entity.count += 1
        if not entity.example and example:
            entity.example = _WS_RE.sub(" ", example).strip()

    # NER over de gesproken tekst, per beurt (behoudt zinscontext per beurt).
    texts = [turn.text for turn in turns]
    for doc in nlp.pipe(texts):
        for ent in doc.ents:
            if ent.label_ in WANTED_LABELS:
                add(ent.text, ent.label_, ent.sent.text)

    # Sprekerlabels zijn per definitie identificatoren -> altijd als PERSON.
    for turn in turns:
        if turn.speaker:
            add(turn.speaker, "PERSON", f"[sprekerlabel] {turn.speaker}")

    # Sorteren: frequentie aflopend, dan type, dan alfabetisch.
    return sorted(
        entities.values(),
        key=lambda e: (-e.count, e.label, e.surface.lower()),
    )


def write_csv(entities: list[Entity], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["entiteit", "type", "aantal_voorkomens", "voorbeeldzin"])
        for entity in entities:
            writer.writerow([entity.surface, entity.label, entity.count, entity.example])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extraheer PERSON/ORG-kandidaten uit een markdowntranscript (spaCy)."
    )
    parser.add_argument("input", type=Path, help="pad naar het markdownbestand")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="pad voor de CSV (standaard: entities/entities_<interview>.csv)",
    )
    args = parser.parse_args(argv)

    if not args.input.is_file():
        parser.error(f"inputbestand niet gevonden: {args.input}")

    output = args.output or Path("entities") / f"entities_{args.input.stem}.csv"

    try:
        import spacy
    except ImportError:
        parser.error("spaCy is niet geïnstalleerd. Draai: uv add spacy")

    try:
        nlp = spacy.load(MODEL)
    except OSError:
        parser.error(
            f"model '{MODEL}' niet gevonden. Installeer het, bijv.:\n"
            f"  uv pip install "
            f"https://github.com/explosion/spacy-models/releases/download/"
            f"{MODEL}-3.8.0/{MODEL}-3.8.0-py3-none-any.whl"
        )

    content = args.input.read_text(encoding="utf-8-sig")
    turns = parse_markdown(content)
    if not turns:
        print(
            "Waarschuwing: geen sprekerbeurten gevonden. Klopt het markdownformat?",
            file=sys.stderr,
        )

    entities = collect_entities(turns, nlp)
    write_csv(entities, output)

    persons = sum(1 for e in entities if e.label == "PERSON")
    orgs = sum(1 for e in entities if e.label == "ORG")
    print(
        f"{len(entities)} kandidaten ({persons} PERSON, {orgs} ORG) "
        f"geschreven naar {output}",
        file=sys.stderr,
    )
    print(
        "Let op: kandidatenlijst ter review. Vul indirecte identificatoren "
        "(projecten, locaties, functietitels) handmatig aan vóór stap 6.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
