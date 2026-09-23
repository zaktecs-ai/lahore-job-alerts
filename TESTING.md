# Testing Plan & Verification Checklist

## Local test (PC par)

```bash
cd lahore-job-alerts
python -m pytest tests/ -v          # 33 unit tests — parser, matcher
python -m src.main status           # config + registry sanity
```

Expected: `33 passed`, status report without errors.

## Email module test

```bash
python -m src.main test-email
```

Expected: test email `ranazak73@gmail.com` (sender) se
`zakriarajpoot73@gmail.com` (receiver) par aati hai. Pehli dafa **Spam
folder** check karein aur "Not spam" mark karein — is se future alerts inbox
mein aayenge.

## Pipeline dry-run (bina real email ke)

```bash
python -m src.main scrape --dry-run
```

Expected output (plain English):
- `Scraping N companies in M batches...`
- Har batch ka summary
- End mein: `X matches found (Y new)` — dry-run par email NAHI jayegi

## Full pipeline verification checklist

- [ ] `status` — companies count > 0, career pages > 0
- [ ] `test-email` — Gmail dono taraf deliver
- [ ] `scrape --dry-run` — koi crash nahi, matches report hote hain
- [ ] `scrape` (real) — matching job milne par email aati hai
- [ ] Non-matching jobs par email NAHI jata (seen-jobs file mein log ho jate hain)
- [ ] Dobara `scrape` — same jobs dobara notify NAHI hoti (dedup kaam kar raha hai)
- [ ] OCI cron — `logs/cron.log` har 8-hour run ka record rakhta hai
- [ ] Broken career page — registry skip karta hai, crash nahi hota

## Matcher sanity (kya match hoga / kya nahi)

| Posting | Match? |
|---|---|
| "Junior Data Engineer — 1 year experience, Lahore" | ✅ |
| "Web Scraper Intern (0-2 yrs)" | ✅ |
| "Data Automation Engineer — 3+ years" | ❌ (experience zyada) |
| "Senior Backend Developer" | ❌ (target role nahi) |
| "Graphic Designer" | ❌ |

## Regression tests — real bugs jo live run mein pakre gaye

Yeh teen bugs asli alerts mein false positives la rahe the. Har ek ka unit
test + server evidence maujood hai.

| # | Bug (kya galat hua) | Fix | Test |
|---|---|---|---|
| 1 | Blog/services page ko job samajh liya — "Off-Road Studios — AI & Data Science" (blog) aur "Folio3 — Data Engineering Services" (services page) email ho gaye | `matcher._NON_JOB_URL_PATTERNS` + `_TITLE_NON_JOB_WORDS` + title mein job-word lazmi | `tests/test_matcher.py` |
| 2 | "Experience: 4-6" (bina "years" shabd ke) detect nahi hua — Arpatech "Data Engineer" email ho gaya | `_EXP_LABELED_RANGE` / `_EXP_LABELED_SINGLE` + `parser.html_to_text()` + detail-verify poora page dekhta hai | `test_exp_labeled_range_without_years_word`, `test_matcher_rejects_labeled_range_in_snippet` |
| 3 | Listing container ka poora text title ban gaya — "Full-time / Contract Marketing Data Analyst Analyze channel performance…" (Weproms) | `parser._looks_like_sentence_blob()` + `_find_title_near_link()` heading prefer karta hai + matcher blob guard | `test_parse_html_rejects_container_text_blob`, `test_matcher_rejects_text_blob_title` |

### Verified evidence (server, 253 pages, `scrape --dry-run`)

```text
detail-verify REJECT Arpatech (Data Engineer) -> needs 4+ years
detail-verify: 3 -> 2 candidates
== SUMMARY: pages=253 jobs_found=568 matched=2 new=0 ==
MATCH: Techabout | Data Analyst | junior hint: intern
MATCH: Techabout | Junior Data Scientist | junior hint: junior
```

`python -m pytest tests/ -q` -> **33 passed**.

### `html_to_text` kyun zaroori hai

Career pages aksar label aur value ko alag tags mein rakhte hain:

```html
<span class="awsm-job-specification-label"><strong>Experience: </strong></span>
<span class="awsm-job-specification-term">4-6</span>
```

Raw HTML par regex chalane se `Experience: ` aur `4-6` alag rehte hain, is
liye experience detect nahi hota. Detail-verify pehle `html_to_text()` se
plain text banata hai, phir `extract_experience()` chalata hai.
