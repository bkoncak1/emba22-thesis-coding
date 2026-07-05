#!/usr/bin/env python3
"""pseudonymize.py — Stap 6 van de transcriptiepijplijn.

Vervangt echte namen (en varianten) in een gecorrigeerd markdowntranscript door
pseudoniemen, op basis van een centrale mappingtabel. Draait daarna een
verificatierapport met een restscan (find_entities.py) over de output.

PRIVACY: de mappingtabel in de projectmap mapping en wordt als CLI-argument
meegegeven. Het origineel blijft onaangeroerd; er wordt een nieuw bestand
geschreven in de outputmap.

mapping.csv-kolommen: echte_naam, varianten, pseudoniem, type
  - varianten : puntkomma-gescheiden, bijv. "Jan de Vries; Jan; meneer De Vries"
  - pseudoniem: doelwaarde (bijv. P1). LEEG = behouden (regel is inactief).
                Zo blijven ORG-namen behouden tot het besluit valt (stap 6, PLAN).
  - type      : PERSON of ORG (informatief; bepaalt niets aan de vervanging).

Vervangingsregels:
  - whole-word, hoofdletterongevoelig;
  - langste variant eerst (zodat "Jan" niet binnen "Jan de Vries" vervangt);
  - één enkele pass, dus een ingevoegd pseudoniem wordt niet opnieuw geraakt;
  - sprekerkoppen (**Naam**) worden meegenomen (staan gewoon in de tekst).

CLI:
    python pseudonymize.py transcript.md --mapping mapping/mapping.csv
    python pseudonymize.py transcript.md --mapping map.csv -o output/l01_pseudo.md
    python pseudonymize.py transcript.md --mapping map.csv --no-restscan
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

# find_entities.py staat in dezelfde map; herbruik parser + NER voor de restscan.
sys.path.insert(0, str(Path(__file__).resolve().parent))


@dataclass
class MappingRow:
    echte_naam: str
    varianten: list[str]
    pseudoniem: str
    type: str

    @property
    def active(self) -> bool:
        return bool(self.pseudoniem)

    @property
    def forms(self) -> list[str]:
        """Alle te matchen oppervlaktevormen (echte naam + varianten)."""
        forms = [self.echte_naam, *self.varianten]
        return [f.strip() for f in forms if f.strip()]


@dataclass
class Report:
    counts: Counter = field(default_factory=Counter)  # pseudoniem -> aantal
    inactive: list[MappingRow] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)


def load_mapping(path: Path, delimiter: str) -> list[MappingRow]:
    rows: list[MappingRow] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        required = {"echte_naam", "varianten", "pseudoniem", "type"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(
                f"mapping mist kolom(men): {', '.join(sorted(missing))}. "
                f"Gevonden: {reader.fieldnames}"
            )
        for raw in reader:
            varianten = (raw.get("varianten") or "").split(";")
            rows.append(
                MappingRow(
                    echte_naam=(raw.get("echte_naam") or "").strip(),
                    varianten=varianten,
                    pseudoniem=(raw.get("pseudoniem") or "").strip(),
                    type=(raw.get("type") or "").strip().upper(),
                )
            )
    return rows


def build_replacer(rows: list[MappingRow], report: Report):
    """Bouw één regex + lookup voor alle actieve vervangingen (langste eerst)."""
    lookup: dict[str, str] = {}  # variant (lowercase) -> pseudoniem
    for row in rows:
        if not row.active:
            report.inactive.append(row)
            continue
        for form in row.forms:
            key = form.lower()
            if key in lookup and lookup[key] != row.pseudoniem:
                report.conflicts.append(
                    f"variant {form!r} verwijst naar zowel {lookup[key]!r} "
                    f"als {row.pseudoniem!r}"
                )
            lookup[key] = row.pseudoniem

    if not lookup:
        return None, lookup

    # Langste variant eerst: regex-alternation kiest de eerste passende tak.
    keys = sorted(lookup.keys(), key=len, reverse=True)
    pattern = re.compile(
        r"(?<!\w)(" + "|".join(re.escape(k) for k in keys) + r")(?!\w)",
        re.IGNORECASE,
    )

    def repl(match: re.Match) -> str:
        pseudoniem = lookup[match.group(0).lower()]
        report.counts[pseudoniem] += 1
        return pseudoniem

    return pattern, repl


def pseudonymize(content: str, rows: list[MappingRow], report: Report) -> str:
    pattern, repl = build_replacer(rows, report)
    if pattern is None:
        return content
    return pattern.sub(repl, content)


def restscan(output_path: Path) -> list:
    """Draai NER opnieuw over de output en geef overgebleven PERSON/ORG terug."""
    import find_entities
    import spacy

    nlp = spacy.load(find_entities.MODEL)
    content = output_path.read_text(encoding="utf-8")
    turns = find_entities.parse_markdown(content)
    return find_entities.collect_entities(turns, nlp)


def print_report(report: Report, entities, restscan_done: bool) -> None:
    print("\n=== Verificatierapport ===")

    if report.conflicts:
        print("\nWAARSCHUWING — dubbelzinnige varianten in mapping:")
        for message in report.conflicts:
            print(f"  ! {message}")

    total = sum(report.counts.values())
    print(f"\nVervangingen ({total} totaal):")
    if report.counts:
        for pseudoniem, count in sorted(
            report.counts.items(), key=lambda kv: (-kv[1], kv[0])
        ):
            print(f"  {pseudoniem:<16} {count}")
    else:
        print("  (geen)")

    if report.inactive:
        print("\nInactieve regels (pseudoniem leeg = behouden):")
        for row in report.inactive:
            print(f"  {row.echte_naam or '(leeg)':<24} type={row.type or '-'}")

    if not restscan_done:
        print("\nRestscan: overgeslagen (--no-restscan).")
        return

    remaining = [e for e in entities if e.label in {"PERSON", "ORG"}]
    print(f"\nRestscan — overgebleven PERSON/ORG in de output ({len(remaining)}):")
    if remaining:
        for entity in remaining:
            print(f"  {entity.surface:<28} {entity.label:<8} {entity.count}x")
        print(
            "\n  Controleer deze: false positives mogen blijven, maar echte namen "
            "die hier nog staan moeten alsnog in de mapping."
        )
    else:
        print("  (schoon)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Pseudonimiseer een markdowntranscript met een mappingtabel."
    )
    parser.add_argument("input", type=Path, help="pad naar het gecorrigeerde .md")
    parser.add_argument(
        "--mapping",
        type=Path,
        required=True,
        help="pad naar mapping.csv",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="pad voor de output (standaard: output/<interview>_pseudo.md)",
    )
    parser.add_argument(
        "--delimiter",
        default=",",
        help="CSV-scheidingsteken van mapping.csv (standaard: ',')",
    )
    parser.add_argument(
        "--no-restscan",
        action="store_true",
        help="sla de spaCy-restscan over",
    )
    args = parser.parse_args(argv)

    if not args.input.is_file():
        parser.error(f"inputbestand niet gevonden: {args.input}")
    if not args.mapping.is_file():
        parser.error(f"mappingbestand niet gevonden: {args.mapping}")

    output = args.output or Path("output") / f"{args.input.stem}_pseudo.md"
    if output.resolve() == args.input.resolve():
        parser.error("output mag niet gelijk zijn aan input (origineel blijft intact)")

    try:
        rows = load_mapping(args.mapping, args.delimiter)
    except ValueError as error:
        parser.error(str(error))

    content = args.input.read_text(encoding="utf-8-sig")
    report = Report()
    result = pseudonymize(content, rows, report)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(result, encoding="utf-8")
    print(f"Gepseudonimiseerd transcript geschreven naar {output}", file=sys.stderr)

    entities = []
    restscan_done = not args.no_restscan
    if restscan_done:
        try:
            entities = restscan(output)
        except OSError as error:
            print(f"Restscan overgeslagen (model/laadfout): {error}", file=sys.stderr)
            restscan_done = False

    print_report(report, entities, restscan_done)

    # Exitcode 2 als er nog namen kunnen staan, zodat scripts erop kunnen acteren.
    if restscan_done and any(e.label in {"PERSON", "ORG"} for e in entities):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
