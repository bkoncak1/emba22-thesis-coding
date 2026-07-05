#!/usr/bin/env python3
"""build_mapping.py — bouwt de centrale mappingtabel voor stap 6.

Aggregeert de kandidatenlijsten uit entities/ (entities_<interview>.csv) tot één
mapping.csv met de kolommen die pseudonymize.py verwacht:

    echte_naam, varianten, pseudoniem, type

Wat het script doet:
  - alle entities_*.csv inlezen en dedupliceren over interviews heen
    (gelijke oppervlaktevorm = zelfde entiteit, tellingen worden opgeteld);
  - HTML-artefacten opschonen (bijv. "&#199;" -> "Ç");
  - varianten conservatief groeperen: een naam waarvan de tokens een echte
    deelverzameling zijn van een andere naam wordt als variant daaronder gehangen
    (bijv. "Lucien" onder "Lucien van den Enden", "Henk" onder "Henk Samson");
  - de interviewer (standaard "Bekir Koncak") herkennen en pseudoniem "Bekir"
    geven — die blijft behouden, niet vervangen (zie PLAN, stap 6);
  - overige personen pseudoniem P1, P2, ... geven op aflopende frequentie;
  - organisaties pseudoniem LEEG laten (open beslissing, stap 6). Een lege
    pseudoniem is in pseudonymize.py inactief = behouden. Met --org-pseudoniemen
    krijgen ze O1, O2, ...

Dit is een DRAFT ter review: de groepering is heuristisch en conservatief.
Typefouten-varianten ("Samsom" vs "Samson") en organisatievarianten worden
bewust NIET automatisch samengevoegd — dat controleer je met de hand voordat je
pseudonymize.py draait.

CLI:
    python build_mapping.py
    python build_mapping.py --entities entities --output mapping/mapping.csv
    python build_mapping.py --interviewer "Bekir Koncak" --org-pseudoniemen
    python build_mapping.py --force   # bestaande mapping.csv overschrijven
"""

from __future__ import annotations

import argparse
import csv
import html
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

WANTED_TYPES = {"PERSON", "ORG"}

_WS_RE = re.compile(r"\s+")
# Tokeniseren: letters (incl. accenten) en cijfers; komma's/punten vallen weg.
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def clean_surface(raw: str) -> str:
    """HTML-entiteiten ontsleutelen en witruimte normaliseren."""
    return _WS_RE.sub(" ", html.unescape(raw)).strip()


def tokens_of(surface: str) -> frozenset[str]:
    """Woord-tokens (lowercase, zonder leestekens) voor deelverzameling-matching."""
    return frozenset(_TOKEN_RE.findall(surface.lower()))


@dataclass
class Entity:
    surface: str
    label: str
    count: int
    tokens: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not self.tokens:
            self.tokens = tokens_of(self.surface)


@dataclass
class Group:
    head: Entity
    variants: list[Entity] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.head.count + sum(v.count for v in self.variants)

    @property
    def variant_surfaces(self) -> list[str]:
        # Aflopend op frequentie zodat de meest voorkomende variant vooraan staat.
        ordered = sorted(self.variants, key=lambda e: (-e.count, e.surface.lower()))
        return [v.surface for v in ordered]


def load_entities(entities_dir: Path) -> list[Entity]:
    """Lees alle entities_*.csv en dedupliceer op (oppervlaktevorm, type)."""
    files = sorted(entities_dir.glob("entities_*.csv"))
    if not files:
        raise FileNotFoundError(
            f"geen entities_*.csv gevonden in {entities_dir}"
        )

    # Sleutel op (genormaliseerde oppervlaktevorm, type); tellingen optellen.
    merged: dict[tuple[str, str], Entity] = {}
    for path in files:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            required = {"entiteit", "type", "aantal_voorkomens"}
            missing = required - set(reader.fieldnames or [])
            if missing:
                raise ValueError(
                    f"{path.name} mist kolom(men): {', '.join(sorted(missing))}"
                )
            for row in reader:
                surface = clean_surface(row.get("entiteit") or "")
                label = (row.get("type") or "").strip().upper()
                if not surface or label not in WANTED_TYPES:
                    continue
                try:
                    count = int(row.get("aantal_voorkomens") or 0)
                except ValueError:
                    count = 0
                key = (surface.lower(), label)
                if key in merged:
                    merged[key].count += count
                else:
                    merged[key] = Entity(surface=surface, label=label, count=count)
    return list(merged.values())


def build_groups(entities: list[Entity]) -> list[Group]:
    """Groepeer conservatief: strikte token-deelverzamelingen worden varianten.

    Kandidaat-heads worden eerst verwerkt (hoogste frequentie, dan meeste
    tokens), zodat volledige namen als head fungeren en kortere vormen daaronder
    aanhaken.
    """
    ordered = sorted(
        entities, key=lambda e: (-e.count, -len(e.tokens), e.surface.lower())
    )
    groups: list[Group] = []
    for entity in ordered:
        candidates = [
            g
            for g in groups
            if entity.tokens
            and entity.tokens < g.head.tokens  # strikte deelverzameling
        ]
        if candidates:
            # Meest voorkomende passende head wint bij ambiguïteit.
            best = max(candidates, key=lambda g: g.total)
            best.variants.append(entity)
        else:
            groups.append(Group(head=entity))
    return groups


def is_interviewer(group: Group, interviewer_tokens: frozenset[str]) -> bool:
    """Herken de interviewer aan de achternaam (laatste token van --interviewer)."""
    if not interviewer_tokens:
        return False
    surname = list(interviewer_tokens)[-1]
    forms = [group.head, *group.variants]
    return any(surname in e.tokens for e in forms)


def assign_and_sort(
    groups: list[Group], interviewer: str, org_pseudonyms: bool
) -> list[tuple[Group, str]]:
    """Ken pseudoniemen toe en bepaal de rijvolgorde."""
    interviewer_tokens = tokens_of(interviewer)

    interviewer_groups: list[Group] = []
    persons: list[Group] = []
    orgs: list[Group] = []
    for group in groups:
        if group.head.label == "PERSON" and is_interviewer(group, interviewer_tokens):
            interviewer_groups.append(group)
        elif group.head.label == "PERSON":
            persons.append(group)
        else:
            orgs.append(group)

    persons.sort(key=lambda g: (-g.total, g.head.surface.lower()))
    orgs.sort(key=lambda g: (-g.total, g.head.surface.lower()))

    rows: list[tuple[Group, str]] = []
    # Interviewer bovenaan, blijft "Bekir" (of de meegegeven naam). Alle
    # interviewervormen (bijv. "Bekir Koncak" en "Koncak, Bekir") in één rij.
    keep_name = interviewer.split()[0] if interviewer.split() else "Interviewer"
    if interviewer_groups:
        interviewer_groups.sort(key=lambda g: (-g.total, g.head.surface.lower()))
        primary, *rest = interviewer_groups
        for group in rest:
            primary.variants.extend([group.head, *group.variants])
        rows.append((primary, keep_name))
    for index, group in enumerate(persons, start=1):
        rows.append((group, f"P{index}"))
    for index, group in enumerate(orgs, start=1):
        rows.append((group, f"O{index}" if org_pseudonyms else ""))
    return rows


def write_mapping(rows: list[tuple[Group, str]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["echte_naam", "varianten", "pseudoniem", "type"])
        for group, pseudoniem in rows:
            writer.writerow(
                [
                    group.head.surface,
                    "; ".join(group.variant_surfaces),
                    pseudoniem,
                    group.head.label,
                ]
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bouw mapping.csv uit de kandidatenlijsten in entities/."
    )
    parser.add_argument(
        "--entities",
        type=Path,
        default=Path("entities"),
        help="map met entities_*.csv (standaard: entities)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("mapping") / "mapping.csv",
        help="pad voor de mappingtabel (standaard: mapping/mapping.csv)",
    )
    parser.add_argument(
        "--interviewer",
        default="Bekir Koncak",
        help="naam van de interviewer; blijft behouden (standaard: 'Bekir Koncak')",
    )
    parser.add_argument(
        "--org-pseudoniemen",
        dest="org_pseudonyms",
        action="store_true",
        help="ook ORG pseudonimiseren (O1, O2, ...) i.p.v. lege pseudoniem",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="bestaande mapping.csv overschrijven",
    )
    args = parser.parse_args(argv)

    if not args.entities.is_dir():
        parser.error(f"entities-map niet gevonden: {args.entities}")
    if args.output.exists() and not args.force:
        parser.error(
            f"{args.output} bestaat al. Gebruik --force om te overschrijven "
            "(let op: handmatige aanvullingen gaan dan verloren)."
        )

    try:
        entities = load_entities(args.entities)
    except (FileNotFoundError, ValueError) as error:
        parser.error(str(error))

    groups = build_groups(entities)
    rows = assign_and_sort(groups, args.interviewer, args.org_pseudonyms)
    write_mapping(rows, args.output)

    n_person = sum(1 for _, p in rows if p and not p.startswith("O"))
    n_org = sum(1 for g, _ in rows if g.head.label == "ORG")
    print(f"mapping.csv geschreven naar {args.output}", file=sys.stderr)
    print(
        f"  {len(rows)} rijen: {n_person} personen (incl. interviewer), "
        f"{n_org} organisaties.",
        file=sys.stderr,
    )
    print(
        "  DRAFT — controleer de groepering (varianten) en vul indirecte "
        "identificatoren aan vóór je pseudonymize.py draait.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
