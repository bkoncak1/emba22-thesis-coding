# PLAN.md — Transcriptiepijplijn interviews (thesis Open Innovation)

**Doel:** Teams-interviewopnames omzetten naar gecorrigeerde, gepseudonimiseerde transcripts in een consistent markdownformat, klaar voor import in Atlas.ti en voor Gioia-codering (Chapter 4).

**Context:** Semi-gestructureerde interviews (Nederlands) via MS Teams. Per interview zijn beschikbaar: `.mp4` (alleen audio), `.docx` (Teams-transcript) en `.vtt` (Teams-captions met sprekerlabels en tijdcodes).
 
---

## Pijplijn (volgorde is bindend)

1. **VTT parsen naar markdown** (script: `vtt_to_md.py`)
2. **Pilot: kwaliteitscheck Teams-transcriptie** (handmatig, één interview)
3. **Correctie tegen audio** (handmatig, mét echte namen — corrigeren gaat sneller met context)
4. **Kandidatenlijst identificatoren genereren** (script: `find_entities.py`, spaCy)
5. **Handmatige aanvulling kandidatenlijst** (indirecte identificatoren)
6. **Pseudonimiseren** (script: `pseudonymize.py`, mappingtabel)
7. **Export voor Atlas.ti** (gepseudonimiseerde .docx of .txt)
   Whisper.cpp is een **fallback**, geen standaardstap. Alleen bouwen als de pilot (stap 2) uitwijst dat de Teams-transcriptie onvoldoende is (richtlijn: minder dan ~90% bruikbaar / correctie kost meer dan ~2x de interviewduur).

---

## Stap 1 — vtt_to_md.py

**Input:** Teams `.vtt`-bestand. Sprekerlabels staan per cue in `<v Naam>tekst</v>`-tags.

**Output:** markdownbestand, exact dit format:

```
**Bekir** *[00:00:04]*
 
Ja, nou, opname gestart. Dag meneer ...
 
**Jan de Vries** *[00:02:10]*
 
Ik ben operationeel verantwoordelijk voor ...
```

**Regels:**
- Opeenvolgende cues van dezelfde spreker samenvoegen tot één beurt; tijdstempel = starttijd van de eerste cue van die beurt.
- Tijdformat `[HH:MM:SS]`, geen milliseconden.
- Echte namen in deze fase behouden (pseudonimisering komt in stap 6).
- Lege regel tussen sprekerkop en tekst, en tussen beurten (zie voorbeeld).
- VTT-artefacten opschonen: cue-nummers, `align`/`position`-attributen, dubbele regels door caption-overlap (Teams herhaalt soms tekstdelen in opeenvolgende cues — dedupliceren).
- CLI: `python vtt_to_md.py input.vtt -o output.md`, plus optie `--preview N` om de eerste N sprekerbeurten naar stdout te printen.
  **Eerste run (pilot):** eerste 20 sprekerbeurten tonen en vergelijken met de audio. Beslismoment whisper ja/nee.

## Stap 4 — find_entities.py

- spaCy met model `nl_core_news_lg` (installeren indien nodig).
- Extraheer entiteiten van type PERSON en ORG uit het gecorrigeerde markdownbestand.
- Output: `entities_<interview>.csv` met kolommen: `entiteit, type, aantal_voorkomens, voorbeeldzin`.
- Gededupliceerd, gesorteerd op frequentie. Dit is een **kandidatenlijst** ter review, geen automatische vervanging.
- Let op: spaCy mist indirecte identificatoren (projectnamen, locaties, unieke functietitels). Die vul ik handmatig aan in de CSV vóór stap 6.
## Stap 6 — pseudonymize.py

- **Input:** gecorrigeerd markdownbestand + centrale mappingtabel `mapping.csv` met kolommen: `echte_naam, varianten, pseudoniem, type`.
    - `varianten`: puntkomma-gescheiden (bijv. `Jan de Vries; Jan; meneer De Vries; dhr. De Vries`).
    - Pseudoniemen personen: `P1, P2, ...` (interviewer blijft "Interviewer" of "Bekir", nader te bepalen).
- **Vervanging:** whole-word, hoofdletterongevoelig matchen, langste variant eerst (anders vervangt "Jan" binnen "Jan de Vries").
- Ook de **sprekerkoppen** (`**Naam**`) vervangen.
- **Output:** `<interview>_pseudo.md` in een aparte outputmap; het origineel blijft onaangeroerd.
- **Verificatierapport** na afloop: alle vervangingen geteld, plus een restscan (draai find_entities.py nogmaals op de output en rapporteer overgebleven PERSON/ORG-entiteiten).
- **Open beslissing (Route 1, bevestiging Bekir pending):** organisatienamen (ProRail, RET, Enexis, Alliander) wel of niet behouden. Script moet beide aankunnen: ORG-regels in mapping.csv kunnen leeg gelaten worden (= behouden) of ingevuld (= vervangen door bijv. `RailOrg1`, `EnergyOrg1`). Tot de beslissing valt: ORG-mapping klaarzetten maar niet activeren.
## Stap 7 — Export Atlas.ti

- Gepseudonimiseerde markdown converteren naar `.docx` (via pandoc) met behoud van het sprekerformat, zodat auto-coding per spreker in Atlas.ti mogelijk is.
- Geen audio-import in Atlas.ti (audio bevat echte namen).
---

## Mapstructuur

```
thesis-interviews/
├── PLAN.md
├── scripts/            # vtt_to_md.py, find_entities.py, pseudonymize.py
├── raw/                # originele .vtt, .docx, .mp4 — NOOIT wijzigen
├── transcripts/        # markdown, gecorrigeerd, echte namen
├── entities/           # kandidatenlijsten per interview
└── output/             # gepseudonimiseerde transcripts + docx voor Atlas.ti
```

**Privacyregels (hard):**
- `mapping.csv` staat BUITEN deze projectmap, op een aparte beveiligde locatie, en wordt nooit gesynct of gedeeld. Scripts accepteren het pad als CLI-argument.
- `raw/` en `transcripts/` verlaten deze machine niet.
- Alleen bestanden uit `output/` mogen gedeeld worden, en pas na de restscan uit stap 6.
- Geen transcripts (ook geen fragmenten) naar externe API's of clouddiensten sturen vanuit deze scripts.
## Technische randvoorwaarden

- Python 3.11+, macOS. Virtual environment in de projectmap.
- Dependencies minimaal houden: `spacy` + `nl_core_news_lg`; verder standaardbibliotheek. Pandoc voor de docx-export.
- Alles Nederlandstalige tekst; let op encoding (UTF-8) en Nederlandse namen met tussenvoegsels bij matching.
- Elke stap moet los draaibaar zijn per interview (er komen er meerdere, gespreid in de tijd).
## Definitie van klaar (per interview)

1. Markdown-transcript gecorrigeerd tegen audio.
2. Kandidatenlijst gereviewd en aangevuld.
3. Gepseudonimiseerde versie gegenereerd, restscan schoon.
4. Docx in `output/` geïmporteerd in Atlas.ti.
