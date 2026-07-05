# Transcriptiepijplijn interviews

Scripts om MS Teams-interviewopnames om te zetten naar gecorrigeerde,
gepseudonimiseerde transcripts in een consistent markdownformat, klaar voor
import in Atlas.ti en Gioia-codering.

Onderdeel van een thesis over Open Innovation (semi-gestructureerde,
Nederlandstalige interviews). Het volledige plan en de motivatie staan in
[`PLAN.md`](PLAN.md); dit bestand is de praktische handleiding.

> ⚠️ **Privacy eerst.** Deze repo verwerkt persoonsgegevens. Lees eerst
> [Privacyregels](#privacyregels). `raw/`, `transcripts/`,
> `entities/`, `output/` en elke `mapping*.csv` staan in `.gitignore` en mogen
> **nooit** gecommit of gedeeld worden.

## Installatie

Vereisten: Python 3.13, [uv](https://docs.astral.sh/uv/), en
[pandoc](https://pandoc.org/) (voor stap 7).

```bash
# Python-dependencies (spaCy) in de projectvenv
uv sync

# Nederlands spaCy-model (~560 MB, eenmalig)
uv pip install "https://github.com/explosion/spacy-models/releases/download/nl_core_news_lg-3.8.0/nl_core_news_lg-3.8.0-py3-none-any.whl"

# pandoc (macOS)
brew install pandoc
```

Draai de scripts met de venv-interpreter, bijv. `.venv/bin/python scripts/...`
(of `uv run python scripts/...`).

## Mapstructuur

```
thesis-coding/
├── scripts/        # de pijplijnscripts
├── raw/            # originele .vtt/.docx/.mp4
├── mapping/        # de vertaalde namen
├── transcripts/    # markdown, gecorrigeerd, echte namen — niet in git
├── entities/       # kandidatenlijsten per interview — niet in git
└── output/         # gepseudonimiseerde transcripts + docx — niet in git
```

## De pijplijn

De volgorde is bindend. Elke stap draait los, per interview.

| Stap | Script | Handmatig? | Doel |
|------|--------|:----------:|------|
| 1 | `vtt_to_md.py` | | Teams `.vtt` → markdowntranscript |
| 2 | — | ✅ | Pilot: kwaliteitscheck Teams-transcriptie |
| 3 | — | ✅ | Correctie tegen audio (mét echte namen) |
| 4 | `find_entities.py` | | Kandidatenlijst identificatoren (spaCy) |
| 5 | — | ✅ | Kandidatenlijst aanvullen (indirecte identificatoren) |
| 6 | `pseudonymize.py` | | Pseudonimiseren + restscan |
| 7 | `export_docx.py` | | Export `.docx` voor Atlas.ti |

Whisper.cpp is een **fallback**, geen standaardstap — alleen bouwen als de pilot
(stap 2) uitwijst dat de Teams-transcriptie onvoldoende is.

### End-to-end voorbeeld

```bash
PY=.venv/bin/python

# 1. VTT → markdown (toon eerste 20 beurten voor de pilot)
$PY scripts/vtt_to_md.py raw/i01.vtt -o transcripts/i01.md --preview 20

# 3. transcripts/i01.md handmatig corrigeren tegen de audio

# 4. Kandidatenlijst identificatoren
$PY scripts/find_entities.py transcripts/i01.md

# 5. entities/entities_i01.csv reviewen en aanvullen, daarna verwerken in mapping.csv

# 6. Pseudonimiseren (+ automatische restscan)
$PY scripts/pseudonymize.py transcripts/i01.md --mapping "mapping/mapping.csv"

# 7. Export naar docx voor Atlas.ti
$PY scripts/export_docx.py output/i01_pseudo.md
```

## Scripts

### `vtt_to_md.py` — stap 1

Parseert een Teams `.vtt` (sprekerlabels in `<v Naam>`-tags) naar markdown.
Voegt opeenvolgende cues van dezelfde spreker samen, ruimt VTT-artefacten en
caption-overlap op, en gebruikt de starttijd van de eerste cue als tijdstempel.

```bash
python scripts/vtt_to_md.py input.vtt -o output.md
python scripts/vtt_to_md.py input.vtt --preview 20      # eerste 20 beurten naar stdout
```

Format van de output:

```
**Bekir** *[00:00:04]*

Ja, nou, opname gestart. Dag meneer ...

**Jan de Vries** *[00:02:10]*

Ik ben operationeel verantwoordelijk voor ...
```

### `find_entities.py` — stap 4

Extraheert `PERSON`- en `ORG`-kandidaten uit een (gecorrigeerd)
markdowntranscript met spaCy (`nl_core_news_lg`). Sprekerlabels worden
meegenomen als PERSON.

```bash
python scripts/find_entities.py transcripts/i01.md
```

Output-CSV: `entiteit, type, aantal_voorkomens, voorbeeldzin`, gededupliceerd en
gesorteerd op frequentie. Dit is een **kandidatenlijst ter review** — geen
automatische vervanging. spaCy mist indirecte identificatoren (projectnamen,
locaties, functietitels) en produceert false positives; beide corrigeer je
handmatig vóór stap 6.

### `pseudonymize.py` — stap 6

Vervangt echte namen (en varianten) door pseudoniemen op basis van een
mappingtabel, en draait daarna een verificatierapport met restscan.

```bash
python scripts/pseudonymize.py transcripts/i01.md --mapping mapping/mapping.csv
```

`mapping.csv`-kolommen: `echte_naam, varianten, pseudoniem, type`.

- `varianten`: puntkomma-gescheiden, bijv. `Jan de Vries; Jan; meneer De Vries`.
- `pseudoniem`: doelwaarde (bijv. `P1`). **Leeg = behouden** (regel inactief) —
  zo blijven organisatienamen staan tot dat besluit valt.
- Vervanging is whole-word, hoofdletterongevoelig, langste variant eerst, in één
  pass. Ook de sprekerkoppen worden vervangen.

Het origineel blijft onaangeroerd; de output komt in `output/<interview>_pseudo.md`.
Exitcode `2` betekent dat de restscan nog `PERSON`/`ORG` vond (pseudoniemen en
false positives tellen mee — controleer of er geen echte namen tussen staan).

### `export_docx.py` — stap 7

Converteert een gepseudonimiseerd transcript naar `.docx` via pandoc, met behoud
van het sprekerformat zodat Atlas.ti per spreker kan auto-coderen.

```bash
python scripts/export_docx.py output/i01_pseudo.md
```

Weigert input die niet op `_pseudo.md` eindigt (override met `--force`). Importeer
in Atlas.ti **geen audio** — die bevat echte namen.

### `md_to_vtt.py` — hulpmiddel

Zet een (gecorrigeerd) markdowntranscript terug naar WebVTT, zodat Atlas.ti het
als tijd-gesynchroniseerd transcript kan importeren. Eén cue per spreekbeurt, met
de kop-tijd als anker.

```bash
python scripts/md_to_vtt.py transcript.md -o transcript.vtt
```

Let op: door het samenvoegen in stap 1 zijn de fijne per-cue timings weg; je
krijgt grovere blokken terug.

## Privacyregels

Hard, niet-onderhandelbaar:

- **`mapping/`, `raw/` en `transcripts/` verlaten deze machine niet.**
- Alleen bestanden uit **`output/`** mogen gedeeld worden, en pas **nadat de
  restscan uit stap 6 schoon is**.
- **Geen transcripts (ook geen fragmenten) naar externe API's of clouddiensten.**
  Alle scripts draaien volledig lokaal.
- `raw/`, `transcripts/`, `entities/`, `output/` en `mapping*.csv` staan
  in `.gitignore`. Nieuwe documentatie-`.md` wordt standaard ook genegeerd; voeg
  een `!bestand.md`-regel toe om die wél te committen.

## Definitie van klaar (per interview)

1. Markdown-transcript gecorrigeerd tegen audio.
2. Kandidatenlijst gereviewd en aangevuld.
3. Gepseudonimiseerde versie gegenereerd, restscan schoon.
4. Docx in `output/` geïmporteerd in Atlas.ti.
