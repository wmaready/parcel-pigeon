# Parcel Pigeon: engineering guide

For engineers taking over or extending Parcel Pigeon. The README is the operator's guide (setup, daily use); this file
explains how the system is built, which rules keep it accurate, and where it is weakest.

## What it is

A U.S. small-parcel intelligence app: news, a rate clock, fuel, carrier documents, a market map of ~470 companies, and a
pricing history since 2018. It has no server and no database:

- **The app** is one static page, `index.html` (HTML, CSS and JavaScript, ~9,800 lines), plus a few helper scripts
  (`ask.js`, `company-search.js`, Leaflet for the map). It reads JSON files from `data/` at load time. Hosted on GitHub Pages.
- **The pipeline** is a set of Python scripts in `pipeline/`, run on a schedule by GitHub Actions. They read the web,
  call Claude, and write JSON into `data/`. Each run commits `data/` back to `main` and redeploys the site.
- **`data/` is the database.** Every fact the app shows lives in a JSON file under version control, so every change has
  a commit, and any bad change can be reverted.

## Schedules (`.github/workflows/`)

| Workflow | When | What runs |
|---|---|---|
| `update.yml` "Update Parcel Pigeon" | every 2 h 10:17-22:17 UTC, plus 04:17 UTC, and on push to main | `fuel.py`, `markets.py`, `news.py`, `themes.py`, `brief.py` (12 UTC), `publish.py`, `export_seed.js`, `players.py` (04 UTC), `alerts.py`, audit |
| `watch.yml` "Watch carrier pages" | hourly at :05 | `publish.py`, `watch.py`, `docwatch.py --batch 15`, `news.py --primary` (SEC filings, Federal Register, press wires, newsrooms), `alerts.py`, `audit.py --offline` |
| `sweep.yml` "Sweep" | 03:41, 09:41, 15:41, 21:41 UTC | `sweep.py` (market map: status, facts, vetting, discovery), capped by `PW_SWEEP_CALLS` per UTC day |
| `alerts.yml` | every 15 min and on issue comments | approves and sends major phone alerts |
| `checks.yml` | every pull request | the test suite (below); uses no secrets |
| `setup.yml` | by hand, once | first-time setup |

All scheduled workflows share the concurrency group `parcel-pigeon`, so two runs never write `data/` at the same time.
Most workflow files are written as JSON (valid YAML); keep that style or convert them all at once.

## Pipeline scripts (`pipeline/`)

| Script | Job |
|---|---|
| `news.py` | Collects feeds and Google News searches (`sources.yaml`), screens them (fast model), groups coverage of one event, writes stories (writing model), checks every number against the source text, files documents, deals, companies and storylines. `--primary` reads only the company and regulator sources (`primary:`) and runs hourly. Pages the reader can't open are read once more through Claude's web fetch tool (`claude_read`, at most `PP_CLAUDE_READS` a run, default 6) |
| `scoop.py` | "First to report": checks whether the trade and business press has an event yet |
| `watch.py` | Hourly read of carrier rate, surcharge, fuel, alert and developer pages; diffs against the last copy and spots new PDFs |
| `docwatch.py` | Reads the rate guides, service guides and terms in the Docs library and reports material wording or figure changes |
| `changeaudit.py` | The strict before/after audit both watchers use: every claimed change must be quoted from the old and new text |
| `fetch.py` | Reads carrier pages through bot protection: browser headers, Chrome TLS fingerprint, headless Chromium, optional proxy (`PP_FETCH_PROXY`), Internet Archive. A bot wall raises `Blocked` and is never saved |
| `players.py` | Researches companies proposed by stories (web search), requires two independent sources and a second adversarial check, and only adds market movers |
| `sweep.py` | Keeps the market map current: discovery by segment, vetting, ownership status, and the quarterly facts check (HQ, founding year, ownership, ticker) |
| `themes.py` | Memory across years: adds pricing events from new stories to `almanac.json` and writes weekly year-over-year notes to `patterns.json` |
| `alerts.py` | Phone push (OneSignal), major-alert approval issues, automatic document collection |
| `audit.py` | Consistency checks across all data; safe fixes go to `audit.json`, the rest to one GitHub issue |
| `fuel.py`, `markets.py`, `brief.py`, `guides.py`, `media.py`, `archive.py`, `publish.py`, `mergejson.py` | Fuel and diesel, share prices, the daily brief, guide text, logos and photos, saved document copies, publishing approved drafts, merging data files after a push race |
| `export_seed.js` | Copies the app's built-in lists (players, docs, deals) into `data/seed.json` so Python can read them |
| `common.py` | Shared helpers: `load`/`save`, the Claude call, number checking, source tiers, URL canonicalizing |

## Data files (`data/`)

| File | Holds | Written by |
|---|---|---|
| `news.json` | live stories (newest 250) | `news.py`, `watch.py`, `docwatch.py`, `publish.py` |
| `seed.json` | the app's built-in lists, exported | `export_seed.js` |
| `threads.json` | storylines (subjects followed over months) | `news.py` |
| `docs.json` | the document library (single source of truth for carrier documents) | `news.py`, `watch.py`, `alerts.py`, `archive.py` |
| `players.json` | market-map additions: new `players`, `edges`, dated ownership `moves`, `checks`, checked `facts` | `players.py`, `sweep.py`, `news.py` |
| `almanac.json`, `patterns.json` | pricing history since 2018; year-over-year notes | `themes.py` (seeded by research) |
| `review.json`, `sweep_review.json` | items a person should look at | several |
| `watch_health.json`, `feed_health.json`, `docwatch.json` | what was read, when, how, and what failed | `watch.py`, `news.py`, `docwatch.py` |
| `seen.json`, `*_state.json` | pipeline memory (headlines already screened, cursors, budgets) | several |
| `snapshots/`, `docwatch/` | raw page and document copies for diffing; removed before the site is published | `watch.py`, `docwatch.py` |

Each company has a full page (`openCompany` in `index.html`, shareable as `#c=<company id>`): the same profile as the
market map panel (`profileHTML`), plus every dated item about the company in one timeline (stories, deals, ownership
changes, almanac pricing events) and its upcoming rate clock dates and storylines.

The app also carries large built-in lists inside `index.html` (`PLAYERS`, the family registry `D`, `HQGEO` city
coordinates, `RCX_MAP`). `data/players.json` is applied on top of them at load: new players, edges, `moves` (in date
order) and `facts` (checked values win over built-in ones).

## The accuracy rules

These are the guardrails that make the content trustworthy. Each has a test in `tests/`.

1. **Every number must be in the source.** `common.numbers_supported` rejects a story, almanac event or pattern note
   whose figures aren't in the text it was written from. Stories get one rewrite; after that they are dropped or held.
2. **The carrier's own word wins.** Sources are ranked by `common.tier`: 0 company or regulator, 1 major business press,
   2 parcel and logistics trade press, 3 everything else. A story leads with its best source, and its date is the
   earliest report of the event, so a late repost on a small site never becomes the story.
3. **No headline is lost.** A headline is marked seen only once it has been screened; events over the per-run writing
   budget wait for the next run.
4. **A bot wall is a failed read, never a reading.** `fetch.is_blocked` recognizes Akamai, Imperva and Cloudflare pages.
   Health files record how each page was read; the audit raises `watch-blocked` / `docs-blocked`.
5. **Market-map facts need a primary source or two independent ones.** Directories (Wikipedia, LinkedIn, Crunchbase,
   PitchBook) never count alone (`sweep.fact_ok`). Ownership changes need two sources on different websites and a date.
6. **Only market movers join the map** (`players.MOVERS`, `news.NOT_MOVER`): no accounting, law, consulting or
   staffing firms, no passive investors.
7. **Some sites are never sources** (`common.NOT_SOURCES`): press-release spam, automated finance write-ups, AI market reports.
8. **Single weak sources are marked.** A price, deal, earnings, legal or rules story resting on one source that is not the
   company, a regulator, the major press or the trade press shows "Unconfirmed" (`news.unconfirmed`). Each run tries to
   confirm up to five with a search for better coverage; the mark clears as soon as a better or second source is listed.
9. **Text read through Claude's web fetch is the tool's copy of the page,** never the model's reply.
10. **Competitors never become stories.** Other parcel consultancies (`news.COMPETITOR_DOMAINS`) only back up a story.

## Claude usage and cost

All calls go through `common.claude` (plain HTTPS to the Messages API, with retries and prompt caching) or
`players.ask` (adds the web search server tool). Models: `PW_MODEL_FAST` (default `claude-haiku-5-5`) screens and
extracts; `PW_MODEL_WRITE` (default `claude-sonnet-5-5`) writes and researches. Each script prints its token usage.
Expect roughly $15-35 a month in a normal news week; the hard stop is the monthly limit set in the Claude Console.

## Secrets (repository settings)

`ANTHROPIC_API_KEY` (required). Optional: `EIA_API_KEY`, `OILPRICE_API_KEY`, `NTFY_TOPIC`, `ONESIGNAL_APP_ID`,
`ONESIGNAL_API_KEY`, `PP_ADMIN_IDS`, `SITE_URL`, `PP_FETCH_PROXY` (an unblocking proxy URL with `{url}` in it),
`SEC_CONTACT` (an email address the SEC asks automated readers to identify themselves with).

## Tests

```
pip install -r requirements.txt pytest playwright && python -m playwright install chromium
python -m pytest tests -q
```

The suite never touches the network or the Claude API and never writes to the real `data/` (each test gets a copy).
It covers block-page detection and fetch fallbacks, source tiers and `sources.yaml`, the news intake (no lost
headlines, best source leads, correct date), the fact and market-mover rules, the almanac's figure check, data-file
consistency, and the app itself: its JavaScript parses, and it opens every tab at 390px and 1280px with no page errors
and no sideways scroll. `checks.yml` runs it on every pull request. `tools/layoutcheck.py` is a deeper visual layout
audit to run after design changes.

## Known weak spots

- **Bot protection.** UPS and FedEx block GitHub's runners. `fetch.py` tries several routes; a paid unblocking proxy
  (`PP_FETCH_PROXY`) is the dependable fix.
- **Paywalls.** WSJ, Bloomberg and Journal of Commerce can't be read. The pipeline looks for the same event at an
  outlet it can read; a licensed news API would close the gap.
- **One large page.** `index.html` holds the whole app. Splitting it into modules with a small build step is the
  first refactor worth doing.
- **Data in git.** Simple and auditable, but the bot commits many times a day and two writers can race
  (`mergejson.py` handles the common case). A real database becomes worthwhile once there are many writers or users.
- **Built-in lists in the page.** Company and document lists live partly in `index.html` and partly in `data/`, joined
  at load. Moving all of them into `data/` would make the pipeline the single writer.
- **Research quality.** The 2018-2027 pricing almanac was researched from search-result summaries; events marked
  `partial` should be checked against the carriers' own documents before anyone quotes them.
