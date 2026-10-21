# Parcel Pigeon

Small parcel news and resources, covering every carrier, deal and player: a rate clock, fuel tracker, market map, carrier documents and stocks.
Runs free on GitHub. The only cost is the Claude API (set a $20 monthly limit).

## How it works
Every 2 hours a GitHub Action:
1. reads the news sources in `pipeline/sources.yaml`
2. keeps all small parcel news, including opinion, analysis and industry news with no price change, and merges coverage of the same event from different outlets into one story with every source listed (Claude Haiku), writes each story with an "effect on shippers" (Claude Sonnet)
3. checks every number in a story against the article; anything that doesn't match goes to `data/review.json` instead of the site
4. updates fuel (`data/fuel.json`) and drafts the Monday brief
5. publishes the site to GitHub Pages

Every hour a second Action, **Watch carrier pages**, reads the carriers' own rate guides, surcharge, fuel, billing,
service-alert and developer pages (list in `pipeline/sources.yaml` under `watch:`). It compares each one word-for-word
with the last copy and spots newly posted PDFs. When something material changes, an agent writes a Parcel Pigeon story
from the carrier's own page and opens a **GitHub issue** with the draft. You get the GitHub notification on your phone:
- **Publish:** add the `publish` label. It goes live within the hour, marked "Spotted by Parcel Pigeon".
- **Edit first:** change the TITLE / SUMMARY / EFFECT / TODO lines in the issue, then add `publish`.
- **Discard:** close the issue.
The first run only saves a baseline copy of each page; alerts start with the second run.

### When a carrier's site turns the reader away
UPS and FedEx use bot protection that often answers a script with an "Access Denied" page. `pipeline/fetch.py` recognizes
those pages and never saves one as a rate guide. It tries a browser-like request, a Chrome-like connection, a real headless
Chrome, an optional unblocking proxy and finally the Internet Archive's latest copy (marked with its capture date). If all of
them are refused, the page counts as a failed read and the audit opens a **watch-blocked** item. For dependable UPS and FedEx
coverage, add an unblocking proxy (ScraperAPI, ZenRows, Bright Data and similar, about $30-50 a month) as the secret
`PP_FETCH_PROXY`, written as the provider's request address with `{url}` where the page address goes, e.g.
`https://api.scraperapi.com/?api_key=YOUR_KEY&url={url}`.

### First to report
When a story comes only from a primary source (a carrier or company newsroom, a press release wire, a filing, or a
carrier page the watcher read), the pipeline searches Google News for the same event across the trade and business press.
If no outlet has it, the story is held back and you get a **[First to report]** GitHub issue with the draft, labeled
`first-to-report`. Add `publish` to post it under Parcel Pigeon, edit it first, or close it. For an instant phone alert
as well, install the free ntfy app, subscribe to a private topic name, and save that name as the secret `NTFY_TOPIC`.

### Fuel
The Fuel tab charts every weekly carrier fuel rate since 2017 (UPS and FedEx ground, air and international) with the weekly U.S. diesel price on a second axis. `fuel.py` refreshes diesel each run from EIA (with `EIA_API_KEY`) or, without a key, from FRED's copy of the same EIA series. It also reads EIA's weekly spot price table (no key) for U.S. Gulf Coast jet fuel, the index UPS and FedEx air and international fuel follow, and WTI and Brent crude, stored under `spot` in `fuel.json`. DHL Express export and import fuel comes from DHL's U.S. surcharges page.

### TransImpact posts and competitors
Our own blog (transimpact.com/blog RSS) is part of the news sweep like any outlet: a post can become a story (usually Analysis) or be added as "TransImpact analysis" on a story it covers. Articles from other parcel consultancies and audit firms (`COMPETITOR_DOMAINS` in `news.py`) can only be added as extra sources on a story; they never become stories of their own.

### Document library (the source of truth)
`data/docs.json` is the single list of official carrier, USPS and regulator documents: rate guides, service guides, surcharge and fuel tables, GRI notices, delivery-area ZIP lists, tariffs and filings, current and past. The Docs tab shows it by carrier, then year, then document type, every drop-down closed until a reader opens it; each carrier opens with its next and last earnings call, and its earnings reports sit inside each year. When the news agent finds a new official document in a story's sources it adds it here, and the auditor checks a rotating batch of these links every run. UPS EZ Rates has no public UPS document yet; it is listed as "Not public" and the agent searches for it.

`data/earnings.json` holds the UPS and FedEx quarterly results archive (release, call recording, transcript, filing). `markets.py` refreshes the UPS and FedEx share prices on the Today tab every run (free, no key).

### Rate guide and terms change watch (priority)
`docwatch.py` runs hourly. It reads the current rate guides, service guides and tariffs in the library every run, and rotates through the other surcharge, peak and program documents. It keeps a text copy of each and, when one changes, asks Claude whether the change is material: a new or removed surcharge, a changed trigger or threshold (weight, size, density/cube, zones, ZIPs, dates), changed amounts, or new contract language such as "EZ". Material changes post as an Alert under Docs & alerts › Alerts and in News. If no outlet has reported it, it is marked First to report and you get a GitHub issue (label `guide-change` + `first-to-report`) and a phone push.

When the watcher flags a change, the phone push opens the app at `#alert=<id>`. Coop flies into the carrier's HQ, picks up the document from the desk, and drops it on that alert in Docs & alerts. Changes you haven't seen yet play the same delivery the first time you open the Alerts view. To preview it, open the app with `#alert=demo`. The app address comes from your repository name; set a `SITE_URL` secret if you use a custom domain.

### Market reports
Releases of parcel and e-commerce shipping reports and indexes (Pitney Bowes, ShipMatrix, Adobe, Deloitte, NRF, Narvar, the Logistics Managers' Index, USPS OIG, PRC and similar) are news stories and are saved to the library under Reports.

### M&A and the market map
The M&A tab has three views. **Deals** shows every deal with Coop's explainer. **Market map** sorts about 100 companies into ten realms: carriers, regional and last-mile, gig, retail, 3PL, global, software and returns, cold chain, drones and EVs, and investors. Lines show who owns, bought, invested in or partners with whom, and every company and connection links to its source. **Players** is the same list A to Z.
In "My map", companies stay faded until you read a story or deal that mentions them. A story counts as read once it has been on screen for a few seconds, or when you open it or play its explainer. The tab shows a "+N" badge for new companies. Your reading history is saved in your browser only.
Each deal's walkthrough stays current on its own: any later story that names the deal's companies shows up on the card as "Latest" and as an update step in Coop's walkthrough, and a follow-up M&A story that changes the status (for example Pending to Closed) updates the deal itself. When news.py writes a new deal, it adds any companies that aren't on the map yet, plus the deal itself, to `data/players.json`. New companies are marked `"auto": true`. Check their one-line description, and add the owner if it's missing.

### Coop, the guide
Coop flies in when the app opens and perches in the bottom corner. He is also the search: on News, M&A and the Docs library, typing in his box filters that page (press / on a keyboard). Tap him to jump to the brief, the next rate change, fuel, the market map, documents or earnings, or type a few letters to find any story, company or document.

### The auditor
After every run, `audit.py` checks that the pieces line up:
- Every price or fee story has an effective date, and that date is on the rate clock (it links or adds it automatically).
- Every rate clock entry points to a real story; dead links are removed.
- No duplicate or superseded stories, and no broken source links.
- Each story is led by the carrier's own page or release. When the carrier and the press disagree, the carrier wins; press articles stay listed under "Also reported by".
- Pending M&A deals are re-checked monthly; doc library items still "pending" get flagged; fuel data that's more than 9 days old gets flagged.
- Numbers in each summary match the source (spot-checked with Claude).

Fixes it can make safely go into `data/audit.json` and the app applies them on load. Anything that needs a person opens or updates one GitHub issue titled **Parcel Pigeon audit** (label `audit`) and, if `NTFY_TOPIC` is set, pings your phone.

## Set it up (about 20 minutes)
1. **GitHub**: create a free account, then a new **public** repository named `parcel-pigeon`
   (public keeps the scheduled runs free). Upload every file in this folder, keeping the folders.
   Some computers hide the `.github` folder when uploading. If it's missing afterward, use Add file → Create new file,
   name it `.github/workflows/update.yml`, and paste in that file's contents. Do the same for `.github/workflows/watch.yml`.
2. **Claude API key**: at console.anthropic.com create a key, add $10–20 of credit, and set a monthly
   spend limit of $20 under Billing → Limits.
3. **Add the key to GitHub**: repo → Settings → Secrets and variables → Actions → New repository secret.
   Name `ANTHROPIC_API_KEY`, paste the key.
4. **Optional free keys** (same place): `EIA_API_KEY` from eia.gov/opendata (weekly diesel) and
   `OILPRICE_API_KEY` from oilpriceapi.com (UPS and FedEx weekly fuel). Without them, those panels keep their last values.
5. **Optional phone push for "first to report" alerts**: install the free ntfy app, subscribe to a hard-to-guess topic name
   (e.g. `parcelwatch-walter-7k2q`), and add it as a secret named `NTFY_TOPIC`.
6. **Turn on the site**: Settings → Pages → Source: **GitHub Actions**.
7. **Phone alerts**: install the GitHub mobile app and turn on notifications for this repository (Watch → All activity),
   so new drafts reach you right away.
8. **First run**: Actions tab → "Update Parcel Pigeon" → Run workflow. When it finishes, your site is at
   `https://<your-username>.github.io/parcel-pigeon/`. Share that link with testers; on a phone,
   "Add to Home Screen" installs it like an app.

## Your weekly 10 minutes
- Open `data/review.json` on GitHub. It lists stories that failed the number check, headlines the bot couldn't read,
  and carrier documents that changed. Fix or delete each item; to publish a fixed story, move it into `data/news.json`.
- Mondays: edit `data/brief.json` if you want to reword the 60-second brief.
- Add or remove sources any time in `pipeline/sources.yaml`.

## Costs and schedule
GitHub, GitHub Pages and the scheduler are free for a public repository. The only bill is the Claude API.

| Job | When | Uses Claude |
|---|---|---|
| News, fuel, stocks | Every 2 hours, 6 a.m. to 8 p.m. Eastern, plus one overnight sweep (9 runs a day) | Only when new items turn up: a fast model screens them, a writing model drafts at most `MAX_NEW_PER_RUN` (10) stories |
| 60-second brief | Once a day, 8 a.m. Eastern | One call |
| Full audit (links and fact checks) | Once a day, overnight | A few calls; quick offline checks run every other time |
| Carrier page and document watch | Every hour | Only when a page or document actually changed |

Expect roughly $10–25 a month in a normal news week. To spend less, lower `MAX_NEW_PER_RUN` in `pipeline/news.py`, or set the `PW_MODEL_WRITE` variable to the fast model (cheaper, slightly plainer writing). The $20 monthly limit in the Anthropic console is the hard stop either way. A custom domain is optional (~$12/year).

## Notes
- Stories are original summaries linking to the source; the bot never republishes articles.
- The first run's feed URLs come from each publisher's standard RSS address; if one fails, the log says so and the rest keep working.

### Rate clock explainers
Each rate clock entry shows its effective date on a calendar tile, a plain "Takes effect …" line and a countdown. Entries with figures get a **Show me what this does** button: Coop walks through the change in two or three animated slides, using templates for general rate increases, peak surcharges, USPS holiday prices, per-pound fees, new fees, zone changes, delivery-area list changes and fuel table changes. Figures come from `RCX_MAP` in the app (with sources) or from the `fx` field the news agent fills on new dates, only from numbers stated in its sources. An entry without figures gets no animation.

### Layout check
`tools/layoutcheck.py` is the app's layout auditor. It opens every section and view at phone (390px) and desktop (1280px) widths and flags anything out of line: sideways scrolling, panels sticking out of the content column, side-by-side columns that don't end on the same line, uneven gaps between stacked panels, and anything past the right edge. Run it after any design change: `pip install playwright && python tools/layoutcheck.py $PWD/index.html`. It should print `layout findings: 0`.

### World map
The market map opens on a U.S. map with every company at its headquarters city, colored by category. Tap a company and the map frames it with its ownership family (parents, subsidiaries and companies it bought), zooming out to the world only when one of them is abroad. Partnerships and investments stay off the map and are listed in the profile instead. Tap a crowded spot to zoom in. City coordinates live in `HQGEO` (per-company overrides in `HQGEO_ID`); a company with no listed city sits at its parent's headquarters, and one with neither stays off the map until a city is added.

## Phone alerts

Web push through OneSignal (free plan: no subscriber cap on web push, 10,000 per send, 6 tags per reader).

**Regular alerts** go out after each run, filtered by each reader's settings in Docs & alerts > Alerts:
carriers (tag `cm`, a 5-bit number: UPS 1, FedEx 2, USPS 4, Amazon 8, OnTrac/DHL/regionals 16), topics
(`t_rates`, `t_docs`, `t_deals`, `t_news`), and a fuel threshold (`ft`, 0 = off). Nothing goes out between
9 p.m. and 7 a.m. Eastern; those wait for the morning run. At most 6 pushes per run, bundled by topic and carrier.

**Major alerts** (a dated price change for most shippers, a big-four GRI/surcharge, or M&A involving UPS, FedEx,
USPS or Amazon) open a GitHub issue labeled `alert-review` that @mentions you (email) and push to your own phone
(`PP_ADMIN_IDS`). Reply `send` to push it to everyone, `hold` to stop it, or edit the Title/Message first.
With no reply it goes out after 2 hours (`PP_AUTO_SEND_HOURS`), never overnight. `alerts.yml` checks every
15 minutes and right after you reply. Only the repo owner's replies count.

Secrets: `ONESIGNAL_APP_ID`, `ONESIGNAL_API_KEY`, `PP_ADMIN_IDS` (your device ID: open the installed app,
turn alerts on, then copy it from "Device ID" at the bottom of the Alerts panel). State lives in `data/alerts_state.json`;
the first run only records what's already published, so nobody gets a backlog.

**`send docs`**: reply `send docs` (or `send docs ontrac` to choose the carrier) on a major-alert issue and the next
hourly run reads the story's sources, has Claude pick the official carrier documents (guides, notices, surcharge and
fuel tables, terms, filings), and adds them to the Docs tab. It comments on the issue with what it added. `hold docs`
adds the documents without sending the alert.

**Automatic document collection**: every run, `alerts.py` reads the sources of up to 6 new stories that cite a carrier,
USPS or regulator page (or are about pricing or guides), follows the document links one click deep, has Claude keep the
real shipper documents, and adds them to the Docs tab under the carrier whose site hosts them. The first run after
install sweeps the last 45 days (up to 40 stories). Everything added is also watched for later revisions.

## What needs your OK (and what doesn't)

Everything publishes on its own (stories, carrier-page and guide changes, documents, rate clock dates, deals, map links,
regular phone alerts) **except**:

| You're asked | Why | Reply |
|---|---|---|
| "Worth running?" | numbers not found in the sources, possibly off-topic for small parcel (triage `fit: edge`), or big and nobody else has reported it | `run` (publish, edits to TITLE/SUMMARY/EFFECT kept) or `skip`; no reply = stays off the site |
| "Major alert" | big story already on the site; the phone push to everyone waits for you | `send`, `send docs`, `hold`; no reply = sends after 2 hours |

A story you OK with `run` that is also big gets its phone alert without a second approval. Only the repo owner's
replies count. Old `draft` issues work the same way (reply `run` or `skip`, or add the `publish` label).

## Change audits (carrier pages and guides)

`changeaudit.py` explains every change before anything is published: it pairs a newly posted file with the one it replaced
(same name, different year), compares old and new text, and keeps a change only if its "before" is quoted from the old
version and its "after" from the new one (numbers checked too; differences and % moves computed from proven pairs are
allowed). Re-listings and cosmetic edits are filed quietly, not published. Cache-busting link stamps (`?v=...`) are ignored.
Stories show a **What changed** before/after table. New files always join the Docs library and are watched from then on.

## Rate clock

Only cost changes and big events get dates (`clock_worthy` in common.py, mirrored in the app): never court dates,
sentencing, hearings, conferences or earnings calls.

## New players

Stories nominate companies they're about (`orgs`); deals add their parties. `players.py` (run from alerts.py, 3 per run)
researches each with web search, drops anything that isn't a parcel player, fills the profile (HQ with map coordinates,
owner, site) and links it only to companies already on the map, each link with a source. New companies get a "New" chip
on the Market map and a Deals alert.

## Docs library

Carrier first, then kind of document (rate guides, GRI announcements, peak, special pricing programs, surcharges, fuel,
zones, service guides and terms, filings, other). Every document added by the pipeline records why (`why` field):
a new file on a carrier page, a file that replaced an older one, a re-linked old file, linked in a story, or added by the
editor. The app shows that line, plus any audited change to the document.

## Reactions, comments and Ask Coop

Built in the app; they switch on when `config.json` (`{"api": "..."}`) points at the Cloudflare worker in `cloudflare/`
(see `cloudflare/SETUP.md`). Reactions are Coop faces (Like, Love, Dislike, Shocked). Comments use a display name and an
automatic screen (spam, abuse, personal info, accusations, confidential contract rates), no approval queue.
Ask Coop: `guides.py` (run from alerts.py) publishes the text of the library's guides as `data/guides/<carrier>.json`;
the app picks the best passages plus matching stories, rate clock, fuel and company data and sends only those; the worker
answers from them with sources, drops any source it wasn't given, caches repeats for 24 hours, and enforces per-reader,
daily and monthly caps.

## Logos and photos

`media.py` (run from alerts.py) saves each company's own logo from its own website to `data/logos/` (re-checked monthly,
shown unaltered on small light tiles: carrier tags, market map lists and cards, profiles, deal explainers, Ask Coop
sources), and, for stories from company sources, the company's own announcement image to `data/img/` as a wide image for
the full story and a square thumbnail for lists. Never trade-press photos; credited "Image: <source>". Needs Pillow
(in requirements.txt).

### Phone alerts: once each
Every push carries a send-once key (OneSignal `idempotency_key`, plus a ledger in `data/alerts_state.json`), so the same story never goes out twice, even if two workflows overlap or a commit is lost. Each new story gets its own push (up to 8 a run; the rest bundle into one "+N more"). Copy is short: a headline of 45 characters or fewer and one sentence (written once by Claude Haiku). Tapping a push opens the story and highlights it; a document change opens Docs on that carrier's folder, with "new" counts on each folder down to the document.

### Saved copies of documents
`archive.py` (run by `alerts.py`) saves the carriers' openly published PDFs and spreadsheets from `data/docs.json` into `data/files/`, unaltered, so the Download button works in one tap and still works if a carrier moves or removes a file. Up to 8 MB a file and 150 MB in total, 6 per run, re-checked every 14 days; a changed file replaces the old copy. Every document still opens the carrier's own copy first. Turn it off with the repository variable or secret `PP_ARCHIVE=0`.

### Connections
Stories, documents, the rate clock and deals are linked from the links themselves: a story shows the library documents among its sources ("From the library"), each document shows the stories that cite it, and Coop offers to jump to the source document, a rate-clock walkthrough or a deal walkthrough when you're reading a story that has one (a few times a visit, never when muted).

### Logos
UPS, FedEx, USPS, Amazon, DHL and a few big retail and gig names use built-in brand marks (Simple Icons path data) so they are always crisp. Every other company's logo is fetched by `media.py` from its own website, preferring the wordmark the site declares or shows in its header (SVG kept as is, sanitized). Companies without a website on file get one looked up by `players.py` (8 per run, `data/sites.json`). `data/logos_missing.json` lists any company still without a logo.

### Hands-off publishing
Up to 18 stories a run from 8 feeds and about 90 Google News searches. Stories publish on their own, including loosely related ones (marked edge, low impact) and ones nobody else has reported yet (marked Spotted first). If a draft uses a number the sources don't contain, the writer gets one rewrite; if the number is still unsupported, a lower-impact story is dropped and only a story that changes prices for most shippers (impact 3) waits for your OK. Phone alerts: only impact-3 stories wait for approval; everything else goes out live.

### Google News links
Google News search results no longer redirect to the article, so `news.py` asks Google for the real address first (googlenewsdecoder, with a built-in fallback) and reads articles with a normal browser header. Items that still can't be read go to `data/review.json` as headline-only and get one more try on the next run.
