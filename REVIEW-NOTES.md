# Review notes: outside review brief v5 (Oct 24, 2026)

All 35 fixes from `CLAUDE-BRIEF.md` (version 5) were worked on branch `claude/review-v5`. That branch merges four work
branches: `claude/rv5-robots` (robots), `claude/rv5-data` (data), `claude/rv5-app` (app) and `claude/rv5-earnings`
(stock cards, earnings and navigation). All 230 tests and `py_compile` pass on the merged branch.

**Important:** the sandbox this was built in could not open ups.com, fedex.com, usps.com, ontrac.com, dhl.com, gls or
shipveho. Every new figure therefore comes from the brief's own Oct 24 fact check and is stored with the brief's source
link. The "check by hand" column lists what a person should open before the demo.

| Fix | Status | Commit(s) | Check by hand |
|---|---|---|---|
| B1 Doc watcher rotation | done | fa29e72 | The rotation gets 15 slots of its own on top of the 37 priority documents, with never-checked documents first. About 52 documents per hourly run now, so watch the run time. |
| B2 UPS SBR page watch and story | done | 85c758b (watch), 30843c9 (story) | Open the UPS SBR page and confirm 4.5%, the 5% fuel surcharge and 40→50 lb. The story has no announcement date because the source states none. |
| B3 Program promises baseline | done | 9eeffe7 | `data/programs.json` holds the SBR record only (brief wording, checked Oct 24). No other program could be sourced from here. |
| B4 Calendar drops stories sharing an address | done | 627d1b4 | `data/rates.ics` now includes the UPS Dec 21 increase and the SBR change. Re-subscribe or refresh the calendar once. |
| B5 Truncated clock labels / 5.9% | done | 9eeffe7 (robot), 30843c9 (data), 1b93d38 (sub-items shown) | Labels are no longer cut. The year appears only when the source text states it. |
| B6 Close "not yet published" placeholders | done | 9c6515e (rule), 69f844c, f3bf98d (app) | The Docs entry reads "Announced Oct 23, 2026 · effective Dec 21 · Rate previews not yet published by UPS". Story 07 is retired. |
| B7 Built-in clock wording | partly done | 69f844c, 30843c9 | e09, e13, e15 and the "minimum billable weight" title are fixed. e11 (USPS Jan 16 vs 17) is unchanged: Notice 123 gives no end date, and PRC Order 9703 says prices roll back Jan 17, 2027, which matches the existing Jan 16 last day. The DHL "Elevated Risk" wording (e15) could not be checked against DHL's page. |
| B8 Fuel tab stale / inconsistent | partly done | 20d9652 | Done: each carrier shows its own week, "last confirmed week of …" in amber after 8 days, the ticker matches the Fuel tab, the next week is shown separately, and the UPS Nov 2 table change appears as a dated notice. Not done: the fallback reader for the FedEx/UPS pages (their page structure couldn't be seen from here). **Confirm the `OILPRICE_API_KEY` secret has a value.** |
| B9 Robot wording leaks | done | 9eeffe7, 85c758b | Stories that still contain robot notes are held for a person instead of published. |
| B10 Dedupe merges distinct events | done | 85c758b, 627d1b4, 1b93d38 | Different effective dates, services or impacts are never merged. |
| B11 Failures hidden as success | done | fa29e72 | A failed step shows an error, the run still saves and deploys, then turns red. Expect red runs until the broken steps are fixed. **Add the `SEC_CONTACT` secret** (e.g. "TransImpact Parcel Pigeon you@transimpact.com"). Until then SEC reads are skipped, with one reminder issue a day. |
| B12 Deal and story corrections | done | 31793f9, 30843c9 | The C.H. Robinson $5.8B value is attached to the existing joint release. Confirm the wording against the C.H. Robinson release. |
| B13 Failing tests | done | bfe59a8, 627d1b4 | Both tests were reading live saved data. Only the tests changed. |
| B14 Ask Coop vs rate clock | done | 7c58829 (almanac), 9ba1079 (Ask Coop) | Ask "UPS 2027 rate increase", "Small Business Rates fuel", "FedEx dim divisor". The announcement date is stored as Oct 23: UPS prints no posting date, and Oct 23 is when our watcher found it. |
| B15 Stock card daily change | done | 8af7fdf, d7c8c0e | Until the next market update, cards show "—" for the change. A move over 15% stays hidden until approved in review.json. DHL is the Xetra listing, in EUR. |
| B16 2018 Amazon story | done | 30843c9 (data), db6570f (rule) | Old articles now go to review instead of the feed. |
| B17 Story linked to an unrelated page | done (story kept) | 30843c9, db6570f | The Germany link is removed. Open the Supply Chain 24/7 link to confirm it is the Larsen interview. |
| B18 Storyline "where it stands" | done | 30843c9 | FedEx Freight spin-off story added (June 1, 2026). About 10 storyline lines were rewritten from their member stories. Read them once. |
| B19 USPS holiday headline | done | 30843c9 | Labeled "Reminder"; the USPS Sept 22 release is the lead source. |
| B20 Map assets folder | done | 75bdddc | Files are moved to `map-assets/`, with the root fallback kept for one release. A post-deploy live check isn't added. |
| B21 Docs links landing on the wrong page | done | 15f21e1 (checker), 31793f9 (data) | No current addresses were found for the GLS/Veho documents. They are marked retired ("last seen date not on file"). |
| B22 OnTrac national vs West Coast | not done | – | OnTrac's page is blocked from here, so this couldn't be confirmed. Per the brief, nothing was changed. |
| B23 Deal/history dates | done | 4565a04 | InPost–Yodel, Canada Post history and FedEx's retained 19.9% of FedEx Freight. The Canada Post line still cites Wikipedia; add the official page. |
| B24 Map coverage line | done | 544c247 | Reads e.g. "78 of 392 companies have a mapped location. Headquarters only, not service coverage." |
| B25 Phone first screen | done | 842a9a4 | The tour sits in the page flow, and a Help row was added at the foot of Today. The header collapses on scroll, and Presentation mode was added. Try both on a real phone and a boardroom screen. |
| B26 Offline / freshness | done | 33f3302 | Cache version pp-v35. Test offline on a phone. |
| B27 Consultancy companies | done | 1aafad2, 33f3302 | `company-foundation.js` is unchanged (hash-checked). "Shipware" no longer matches Costco. No map positions are inferred. |
| B28 Earnings data fields | partly done | 3c4d598 | Only the brief's checked figures are filled in (UPS Q2 2026; FedEx FY26 Q4 reaction and 12.6%). Everything else is null; see the list below. |
| B29 Earnings chart | done | 62ab42c | Look at all three views on a real phone. Eight bars fit with a sliver of scroll. |
| B30 Stock watch earnings line | replaced (owner's call, Oct 25) | d7c8c0e | Stock watch is gone from Today. Stock prices stay on the ticker and sit beside each carrier's logo in Docs; Today ends with a fixed "Latest earnings" panel (UPS and FedEx revenue, packages a day, revenue per package). The earnings page no longer shows stock reactions or a stock chart. |
| B31 Earnings opens the right company | done | 62ab42c | FedEx Freight's company page gets an Earnings button too. |
| B32 New quarters added automatically | partly done | 3c4d598 | The release is read twice and the quarter added as `checked:false`. Package figures from the 10-Q are requested in review.json, not read automatically. **After Oct 27, enter UPS Q3 2026 package figures from the 10-Q.** FedEx Freight has no automatic lookup. Confirm the FedEx transition period length from the release. |
| B33 Back and exit | done | 6339eeb | Try every Back sequence on a real phone, including the installed app. |
| B34 Don't-add-bugs checklist | done | all | |
| B35 Dated page pictures | done | fa29e72 (robot), f3bf98d (app) | At most 8 pictures per run and one per document per day. **Pictures are published on the live site; decide before any external sale whether they should stay public.** |

Also fixed during the merge: two new lines in the app's built-in data broke `pipeline/export_seed.js`, which runs on every
update. Both are now guarded, and `tests/test_data.py::test_seed_export_runs_on_the_app` covers it.

## Earnings figures still to copy from filings (stored as null, never estimated)
- Packages a day, operating days, revenue per piece and U.S. domestic: every UPS quarter Q1 2024–Q1 2026, and all eight FedEx quarters FY25 Q1–FY26 Q4.
- Revenue in $ millions (`rev_m`, `rev_prior_m`): every quarter except UPS Q2 2026.
- `revYoY`: UPS Q3 2025 and FedEx FY25 Q3.

## Facts taken from the brief and not re-verified from here
UPS SBR figures; UPS 5.9% average (Ground, Air, International); FedEx Freight completion (June 1, 2026, FDXF, 19.9%);
USPS Sept 22 release; C.H. Robinson "$5.8 billion implied transaction value"; DHL–Venipak July 27, 2026 (this one matches
story nr1dab23); InPost–Yodel April 17, 2025 (95.5%).

## Found by the independent bug review of the merged work, and fixed
- **Reading article pages (B16/B17).** A headline with an apostrophe ("UPS's …") was read as "UPS", and a "Subscribe…" banner could be taken as the article's first paragraph, so real stories would have been held as mismatched. When an article was recovered after a bot wall, it was still judged by the bot-wall page.
- **"Benefit removed" rule (B3).** A plain percentage counted as "adding a charge", so a sentence like "SBR, which includes fuel at no extra cost, will rise 4.5%" was wrongly flagged as removing the fuel benefit.
- **Robot notes (B9).** Two published UPS stories still showed robot notes ("the NEW text; the OLD excerpt…", "Also: …"). Those notes are now cleaned.
- **Earnings stock prices (B28).** A failure to fetch stock prices no longer turns every run red. It shows a warning and keeps the last good figures.
- **"Waiting" stories (B6).** A "still waiting" story is closed only when its headline is about that carrier, so a FedEx story that mentions UPS isn't dropped.
- **Stock watch (B30).** Rotating stock cards changed height by about 110 px, which shifted the whole page below them. The height is now kept steady.
- **Back button (B33).** Returning to Today now settles at the right place even while the phone header collapses. A flaky test was also measuring the wrong starting point; it now measures correctly.

## Still for a person to decide or check
- **USPS last day of the peak (B7, e11).** One source says the peak runs "through Jan 17, 2027 (midnight CT)", while PRC Order 9703 says prices "roll back Jan 17". The app uses Jan 16 as the last day on the rate clock, and the almanac and peak table show Jan 17. Settle it from USPS Notice 123.
- **9.7% figure.** "About 9.7% combined (1.045 × 1.05)" for SBR is the brief's own calculation, labeled as calculated, before agreement terms.
- **Larsen interview (B17).** The story was kept with its Supply Chain 24/7 link. If that page isn't the interview, remove the story (add its id to data/drop.json).
- **Ask Coop.** "Small Business Rates fuel" opens with SBR's advertised inclusions, and the Dec 21 change appears under Related stories.
- **Earnings robot (B32).** It picks the newest release link on the IR page. The UPS IR page may load its links with JavaScript, so if the automatic add doesn't fire after Oct 27, add the quarter by hand.
