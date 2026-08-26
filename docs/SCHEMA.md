# supply_chain.json — schema v2

The supply-chain map started as input to one panel in one app. This schema is the
first step in treating it as a dataset in its own right: something a third party
could licence, audit, and rely on without ever running Windrose.

That ambition sets the bar. A dataset is worth paying for when a buyer can answer
*"how do you know?"* about any single row. Everything below exists to make that
question answerable, and to make it obvious when the answer is "we don't".

## The rule the rest of the schema serves

**An unverified edge is a legitimate row. A fabricated citation is not.**

Forty edges with a real filing behind them and 489 marked honestly as unverified
is a saleable dataset. Five hundred and twenty-nine edges with plausible-looking
sources, some of which were reconstructed from memory, is a liability — because
the buyer cannot tell which is which, so none of it can be trusted.

`confidence` therefore defaults to `unverified`, and a field being absent always
means "we have not established this", never "assume the good case".

## Backward compatibility

Every edge in the file today is valid under v2 with nothing added:

```json
{ "from": "ASML", "to": "TSM", "rel": "EUV & DUV lithography" }
```

Reading it under v2 yields `confidence: "unverified"`, no criticality, no sources,
and unbounded validity. That is a truthful description of what we actually know
about that row right now. All 529 existing edges are legacy rows in exactly this
sense.

Rules that keep it that way:

- **Every v2 field is optional.** `from`, `to` remain the only required keys.
  (`rel` is strongly recommended but was already optional in practice.)
- **Absence is meaningful and always conservative.** Missing `confidence` is
  `unverified`; missing `criticality` is unknown, *not* `minor`; missing
  `valid_to` is "still current, as far as we know".
- **Consumers must treat unrecognised enum values as the conservative case** — an
  unknown `confidence` reads as `unverified`, an unknown `criticality` as unknown.
  This is what lets a future v3 add a value without breaking a v2 reader.
- Top-level `schema_version` is an integer. A file without one is version 1.

## The edge, in full

```json
{
  "id": "semiconductors:ASML>TSM:2010",
  "from": "ASML",
  "to": "TSM",
  "rel": "EUV & DUV lithography",

  "criticality": "sole-source",
  "confidence": "verified",

  "valid_from": "2010-01-01",
  "valid_to": null,

  "sources": [
    {
      "url": "https://www.sec.gov/Archives/edgar/data/937966/...",
      "doc_type": "20-F",
      "filer_cik": "0000937966",
      "accession": "0000937966-24-000012",
      "filed": "2024-02-14",
      "retrieved": "2026-08-25",
      "quote": "we are currently the sole supplier of EUV lithography systems",
      "supports": ["criticality", "rel"]
    }
  ]
}
```

### Identity

| Field | Type | Notes |
| --- | --- | --- |
| `id` | string | Optional, stable, globally unique. Needed because `(from, to)` is **not** unique once temporal validity exists — a supplier relationship that ended in 2019 and resumed in 2023 is two rows. Recommended form `network:FROM>TO:startyear`. Absent means the row is identified positionally; a consumer that needs stable ids should synthesise and persist them. |
| `from`, `to` | string | **Required.** Node ids within the same network. |
| `rel` | string | Human-readable description of the relationship. Rendered in the UI. |

### Criticality

`criticality`: one of `sole-source`, `major`, `minor`.

| Value | Means |
| --- | --- |
| `sole-source` | No qualified alternative supplier exists today. Losing this link stops production. The bar is high and it should be rare. |
| `major` | A named, material dependency — but substitutable, typically at cost or on a timescale of quarters. |
| `minor` | A real relationship that would not, on its own, disrupt the downstream company. |

Deliberately **not** a number. A 0–1 weight would imply a precision no filing
supports, and would invite averaging things that should not be averaged. Three
ordered buckets is what the evidence can actually carry. This is the same
discipline the chokepoints panel already states about itself: structure, not
revenue.

Criticality is a property of the *link*, not of either company. ASML being
critical to TSMC says nothing about the reverse direction.

### Confidence

`confidence`: `verified` or `unverified`. Default `unverified`.

An edge may be marked **`verified` only if all of the following hold**:

1. A primary source document was **actually fetched** during verification — not
   recalled, not inferred from a summary, not reconstructed from training data.
2. The `quote` appears **verbatim** in that document.
3. The quote **supports the specific claims** named in `supports`. A filing that
   establishes a relationship exists does not thereby establish it is
   sole-source.
4. The source is identified precisely enough that a third party can re-fetch it
   and find the same sentence.
5. `retrieved` records when it was fetched.

There is no partial credit. An edge with a source that establishes `rel` but not
`criticality` is verified for `rel` and simply carries no `criticality`.

### Temporal validity

| Field | Type | Notes |
| --- | --- | --- |
| `valid_from` | `YYYY-MM-DD` or null | When the relationship is known to have begun, or the earliest date we have evidence for. Null means unknown-but-current. |
| `valid_to` | `YYYY-MM-DD` or null | **Null means current.** A date means the relationship ended — acquisition, contract expiry, supplier switch, bankruptcy. |

This is the field that stops the map rotting. Today an acquisition silently
corrupts the graph: the acquired company's edges keep implying a live
relationship that no longer exists, and nothing records that it ever did. Under
v2 that event is an edit to `valid_to`, and the history stays intact.

**Consumer rule:** default to "as of today" — include an edge when `valid_to` is
null or in the future. A consumer wanting a historical view passes an as-of date
and filters on the interval. Windrose's own reader does not filter yet; that
lands with the validator in step 2, so that expired edges do not quietly change
what the chokepoints panel says before anyone has looked at the numbers.

Dates are ISO `YYYY-MM-DD`, UTC, no times. Filing dates are day-resolution and
inventing more precision would be false.

### Sources

`sources` is an **array**, because a single edge can rest on more than one
document, and because different attributes of the same edge legitimately come
from different filings.

| Field | Notes |
| --- | --- |
| `url` | Fetchable location. **Only `http://` and `https://` survive loading** — see the security note below. |
| `doc_type` | See vocabulary below. |
| `filer_cik` | SEC Central Index Key, zero-padded to 10. Identifies *who filed*, which is not always the subject company. |
| `accession` | SEC accession number. **The canonical identifier.** URLs rot and EDGAR reorganises; accession numbers are immutable. When both exist, the accession is authoritative. |
| `filed` | Date the document was filed/published. |
| `retrieved` | Date **we** fetched it. Audit trail, and it dates the claim. |
| `quote` | Verbatim supporting phrase, **under 15 words**. Short enough to be unambiguous fair use, long enough to carry the claim. |
| `supports` | Array of the field names this source substantiates. |

`doc_type` vocabulary, in descending evidentiary weight:

- **Filed with a regulator** (legally attested, highest weight): `10-K`, `10-Q`,
  `8-K`, `20-F`, `40-F`, `S-1`, `DEF 14A`
- **Company-published** (attributable, not attested): `earnings-call`,
  `investor-presentation`, `press-release`
- **Third-party** (weakest; use only when nothing better exists): `news`,
  `trade-publication`

The vocabulary is open — an unrecognised `doc_type` is readable, and a consumer
should treat it as third-party weight. The pilot uses SEC filings exclusively.

### `supports` — the reason there is no v3 migration

This is the field that makes the schema extensible without another migration.

A source does not substantiate "the edge". It substantiates *specific claims*
about the edge. Once that is explicit, a new attribute is additive: revenue
concentration arrives as a new optional field plus a source entry whose
`supports` names it. Nothing existing changes shape.

```json
{ "url": "...", "doc_type": "10-K", "quote": "...",
  "supports": ["revenue_share_pct"] }
```

Reserved for later layers, deliberately **not** implemented now:

| Field | Layer |
| --- | --- |
| `revenue_share_pct`, `revenue_basis`, `revenue_period` | Revenue concentration |
| `geography`, `facility_ids`, `chokepoint_region` | Geographic |

Naming them here is not scope creep — it reserves the names so a later layer
cannot collide with something improvised in the meantime.

## Nodes

Unchanged in v2: `id`, `label`, `type`, `ticker`. Node-level provenance and
node-level attributes are out of scope. The interesting claims are about
relationships, and that is where the effort belongs.

## Security: new string fields are an XSS surface

`supply_chain.json` is community-editable and the README invites pull requests
against it. A crafted company label once executed arbitrary JavaScript with
access to the local API holding the user's positions. Adding `url` and `quote` —
both of which render — reopens exactly that surface, and `url` is worse than a
label because it lands in an `href`.

Two changes in `extras._scrub_chain()`:

1. **Scrubbing is now recursive over every string, at any depth, including dict
   keys.** The previous version named the fields to clean (`id`, `label`, `type`,
   `ticker`, `from`, `to`, `rel`), which silently fails open the moment a field is
   added — the failure mode this schema would otherwise have walked straight
   into. Any field added later is scrubbed by default.
2. **URL fields are scheme-checked.** Stripping `<` and `>` does nothing to
   `javascript:alert(1)` in an `href`. Only `http://` and `https://` survive;
   anything else — `javascript:`, `data:`, `vbscript:`, `file:`,
   protocol-relative `//evil.com` — becomes an empty string.

Escaping at render with `esc()` stays. This is the second lock, not a replacement
for the first.

## Worked examples

**A legacy edge.** Valid, honest, and the state of all 529 rows today:

```json
{ "from": "AMAT", "to": "TSM", "rel": "deposition & etch tools" }
```

Reads as: relationship asserted by the curator, criticality unknown, nobody has
checked, assumed current.

**A verified edge**, with the criticality resting on the quoted phrase:

```json
{
  "from": "ASML", "to": "TSM", "rel": "EUV lithography systems",
  "criticality": "sole-source", "confidence": "verified",
  "valid_from": "2010-01-01", "valid_to": null,
  "sources": [{
    "url": "https://www.sec.gov/Archives/edgar/data/937966/...",
    "doc_type": "20-F", "accession": "0000937966-24-000012",
    "filed": "2024-02-14", "retrieved": "2026-08-25",
    "quote": "sole supplier of EUV lithography systems",
    "supports": ["criticality", "rel"]
  }]
}
```

**A historical edge** — an acquisition recorded rather than deleted:

```json
{
  "id": "semiconductors:XLNX>AMD:2022",
  "from": "XLNX", "to": "AMD", "rel": "acquired — FPGA portfolio",
  "confidence": "verified",
  "valid_from": "2000-01-01", "valid_to": "2022-02-14",
  "sources": [{
    "url": "https://www.sec.gov/...", "doc_type": "8-K",
    "filed": "2022-02-14", "retrieved": "2026-08-25",
    "quote": "completed its acquisition of Xilinx",
    "supports": ["valid_to"]
  }]
}
```

Deleting that row would lose the fact. Keeping it with `valid_to` set means a
2021 as-of query still returns the truth about 2021.

## What a buyer would ask first

Coverage — *what fraction is actually verified, and where?* That number is the
product. It is why the validator in step 2 reports verified counts per network
rather than a single headline figure: a dataset that is 90% verified in
semiconductors and 0% everywhere else is worth something specific, and saying so
plainly is worth more than an average that hides it.
