# Patch Tuesday Plus

A weekly cybersecurity news rollup, published every Tuesday, for IT admins and security-minded pros. Voice: direct, plain-spoken, no hype.

**Hard rule:** never use em dashes anywhere on this site. Use commas, colons, or hyphens instead.

## Structure

- `index.html` - Home page: brand, tagline, latest edition card, archive list, email signup section.
- `editions/edition-NNN.html` - One file per weekly edition. Edition #1 covers the week of September 15-22, 2026.
- `styles.css` - The single stylesheet for the whole site.

No build step, no dependencies. Hand-written HTML and CSS, deployable as-is to GitHub Pages.

## How to add a new Tuesday edition

1. Copy `editions/edition-001.html` to `editions/edition-002.html` (increment the number).
2. Update the `<title>`, the `<h1>`, and the `meta` published line with the new edition number and week range.
3. Replace the story cards. Keep the section structure: Patch now (top 3) / Zero-days and KEV additions / Breaches / Ransomware / Outages / On deck for next week.
4. Curate from `~/workspace/security-alerts/seen.json` and the daily logs in `~/memory/YYYY-MM-DD.md`. Lead with what matters most to a working IT admin. Every "Patch now" and major item should carry an `action` box that says what to do, not just what happened.
5. In `index.html`:
   - Update the "Latest edition" card to point at the new edition (change the link, week range, and summary paragraph; move the `New` badge).
   - Add the new edition to the top of the archive list with its week range and a one-line summary. Keep older editions listed below.
6. Proofread for em dashes before publishing. A quick check: `grep -P "\x{2014}" index.html editions/edition-*.html` should return nothing.

## Email capture

The signup form on `index.html` posts to a placeholder endpoint and is marked with an HTML comment. New subscribers land on the `Patch Notes` Beehiiv list (https://patchnotesdaily.beehiiv.com; tagline: "The 5-minute daily cybersecurity brief for people with a network to defend"). The Daily Security Brief writer owns the daily email and the Beehiiv publication; they will supply the real subscribe embed or form action, at which point update the form and remove the comment.

Agreed weekly/daily split (Sept 23, 2026, via the CMO): the daily brief reports what broke overnight using the saved `Daily Brief Template` in Beehiiv (5 item slots, each tagged PATCH NOW / WATCH / IGNORE, with headline, 2-3 sentence summary, one-line action, and source link). The weekly rollup on this site curates and ranks the week's biggest items with context and actions. Funnel: the weekly site drives capture to the Beehiiv list, then the welcome sequence takes over (4 emails: immediate welcome, Day 1 origin story, Day 4 engagement plus expectations for the Tuesday weekly edition, Day 7 pitch for the $39 pack with LAUNCH20 through Oct 6; loaded as a DRAFT automation, OFF until Nicholas says go).

## Deploy

GitHub Pages, same playbook as the other house sites. Repo: `NJShell2/patch-tuesday-plus`, Pages from `main` branch root.
