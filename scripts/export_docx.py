#!/usr/bin/env python3
"""export_docx.py — Stap 7 van de transcriptiepijplijn.

Converteert een GEPSEUDONIMISEERD markdowntranscript naar .docx via pandoc, met
behoud van het sprekerformat (**Naam** *[tijd]*), zodat Atlas.ti per spreker kan
auto-coderen.

PRIVACY: exporteer alleen bestanden waarvan de restscan uit stap 6 schoon is.
Alleen bestanden uit output/ mogen gedeeld worden. Geen audio-import in Atlas.ti
(audio bevat echte namen).

Vereist: pandoc (brew install pandoc).

CLI:
    python export_docx.py output/i01_pseudo.md
    python export_docx.py output/i01_pseudo.md -o output/i01_pseudo.docx
    python export_docx.py output/i01_pseudo.md --reference-doc stijl.docx
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def build_pandoc_command(
    src: Path, dest: Path, reference_doc: Path | None
) -> list[str]:
    command = [
        "pandoc",
        str(src),
        "--from=markdown",
        "--to=docx",
        "-o",
        str(dest),
    ]
    if reference_doc is not None:
        command.append(f"--reference-doc={reference_doc}")
    return command


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Exporteer een gepseudonimiseerd markdowntranscript naar .docx "
        "voor Atlas.ti."
    )
    parser.add_argument(
        "input", type=Path, help="pad naar het gepseudonimiseerde .md (uit output/)"
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="pad voor de .docx (standaard: naast de input, zelfde naam)",
    )
    parser.add_argument(
        "--reference-doc",
        type=Path,
        default=None,
        help="optioneel .docx-stijlsjabloon voor pandoc",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="exporteer ook als de bestandsnaam niet op _pseudo eindigt",
    )
    args = parser.parse_args(argv)

    if shutil.which("pandoc") is None:
        parser.error("pandoc niet gevonden. Installeer het met: brew install pandoc")

    if not args.input.is_file():
        parser.error(f"inputbestand niet gevonden: {args.input}")

    if args.reference_doc is not None and not args.reference_doc.is_file():
        parser.error(f"reference-doc niet gevonden: {args.reference_doc}")

    # Veiligheidscheck: waarschuw als dit niet op een gepseudonimiseerd bestand lijkt.
    if not args.input.stem.endswith("_pseudo") and not args.force:
        parser.error(
            f"'{args.input.name}' lijkt niet gepseudonimiseerd (verwacht *_pseudo.md). "
            "Exporteer alleen na een schone restscan (stap 6). "
            "Weet je het zeker? Gebruik --force."
        )

    output = args.output or args.input.with_suffix(".docx")
    output.parent.mkdir(parents=True, exist_ok=True)

    command = build_pandoc_command(args.input, output, args.reference_doc)
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as error:
        print("pandoc-fout:", file=sys.stderr)
        print(error.stderr, file=sys.stderr)
        return 1

    print(f"Docx geschreven naar {output}", file=sys.stderr)
    print(
        "Klaar voor import in Atlas.ti. Herinnering: geen audio importeren "
        "(audio bevat echte namen).",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
