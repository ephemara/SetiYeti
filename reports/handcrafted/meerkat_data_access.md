# MeerKAT data access — how to actually get it

Researched 2026-09 (read-only). Bottom line first: **MeerKAT has no public
bulk-download API like Breakthrough Listen's.** Access is portal + request, with
an 18-month proprietary clock. Raw voltage is rare and retained selectively.

## The three front doors

| Front door | URL | What it is | Scriptable? |
|---|---|---|---|
| **MeerKAT Archive** | `https://archive.sarao.ac.za/` | Official public archive — "explore public datasets, browse observation metadata, discover products". Routes: `/observations`, `/search`, `/projects`, `/exports`, `/help` | **No** (yet) |
| **SARAO apps portal** | `https://apps.sarao.ac.za/` | Authenticated portal. Register / sign in with email or SARAO Gmail (SKASA/Keycloak SSO) | account-gated |
| **Archive gateway** | `https://archive-gw-1.kat.ac.za/...` | Token-based file backend (JWT `scopes:["read"]`, `prefix`). Powers the MGCLS download links | token-gated |

**The gap:** `archive.sarao.ac.za/api/*` is a real namespace but only
`/api/clientinfo` is implemented — every data endpoint returns the literal string
*"API documentation will go here"*. So today the public archive is a **web UI**,
not something we can pull from with a script the way `bl_download.py` pulls BL.

## The policy (what becomes public, when)

MeerTime states it plainly and it is the general SARAO model:

> "All data will be made available in annual data releases **within 18 months of
> the end of the semester**. 100% of the data will be stored in the SARAO
> archives and ultimately released to the community."

- **Proprietary period ≈ 18 months**, then public via the SARAO archive.
- Some programmes release products independently (MGCLS does).
- PI data lives in the archive from day one; the clock just gates public access.

## What the pipeline wants vs. what's released

Our battery needs **phase → raw voltage**. MeerKAT's public products are mostly:

- visibilities (`MeasurementSet`) and images (FITS) — not voltage;
- pulsar/transient products: **PSRFITS / filterbank** — power, spectral-subset;
- **baseband/voltage** — retained *selectively* (candidate events, FRBs), not routine.

So for the full battery we need the transient/pulsar side, not the imaging side.

## Transient / pulsar programmes (the interesting ones)

| Programme | What it is | Data access |
|---|---|---|
| **TRAPUM** | Transients & Pulsars with MeerKAT — globular clusters, nearby galaxies, surveys | *"specific data sets retained… may be released upon reasonable request"*; open-access setup with SARAO in progress (`trapum.org`, #data) |
| **MeerTRAP** | Real-time single-pulse / FRB search, voltage dumps on triggers | `meertime.org` — annual releases; stored in SARAO archive + OzSTAR (Swinburne) |
| **MeerTime / Thousand Pulsar Array** | Pulsar timing | Annual releases; TPA data "as soon as validated" |
| **ThunderKAT** | Transient survey | via SARAO archive, proprietary clock |

## Public datasets already out

- **MGCLS** (MeerKAT Galaxy Cluster Legacy Survey) — 115 clusters, L-band
  900–1670 MHz, ~6–10 h each, 2018–2019. DR1 (diffuse filtered maps) is public:
  `https://mgcls.sarao.ac.za/data-releases/`, DOI `10.48479/7epd-w356`.
  (Images, not voltage — but a real public dataset.)
- Other surveys release via `archive.sarao.ac.za/search` as the clock expires.

## Support / requests

- SKA Africa service desk: `https://skaafrica.atlassian.net/servicedesk/customer/portal/1/group/7`
- ESDKB wiki: `https://skaafrica.atlassian.net/wiki/spaces/ESDKB/overview`
- MGCLS queries: Kenda Knowles (address on the MGCLS site).

## The realistic play for SetiYeti

1. **Register** on `apps.sarao.ac.za` — the one account that unlocks the gateway.
2. **Enumerate** `archive.sarao.ac.za/observations` + `/search` for public
   datasets in the water hole (1400–1720 MHz) once the clock expires.
3. **Request TRAPUM/MeerTRAP retained sets** — that is where voltage lives
   (globular-cluster beams, FRB/candidate dumps). This is the match for our
   blind-spot battery.
4. **Grab MGCLS now** if we want a real public MeerKAT product immediately
   (spectral subset only).
5. **Watch for the archive API** — `/api/*` is scaffolded; when it lands we can
   write a `mk_download.py` mirroring `bl_download.py`.

### What MeerKAT buys us
- **RFI:** Karoo is legally protected (Astronomy Geographic Advantage Act) —
  cleaner than anything in the BL set.
- **Band:** L-band 900–1670 MHz covers the water hole 1420–1720 almost exactly.
- **Regime:** wide-field (+ beamformer), modern, multi-beam → RFI rejection by
  direction.
- **Cost:** no bulk API, account + request, 18-month clock. Slow to start, but
  the cleanest long-term well we have.

*No files downloaded during this research.*
