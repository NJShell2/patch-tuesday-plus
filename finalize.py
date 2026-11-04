#!/usr/bin/env python3
"""Patch Tuesday Plus finalize: everything after the writing, no agent involved.

Given a finished edition HTML file (already written by the editor, with its
4 images generated into assets/edition-NNN/), this script:
1. Drafts the Marcus spoken briefing script from the edition text with one
   Gemini call (page section order preserved, Patch now weighted most),
   validates it (every line labeled "Marcus: ", 1000 to 1800 words, no URLs,
   no em dashes), and writes it to /tmp.
2. Generates the briefing audio with podcast-helper, saves it as
   audio/edition-NNN.mp3 (this repo only, never the podcast library), and
   reads its real duration with ffprobe.
3. Embeds the listen section right after the meta line and the share script
   before </body>, using the exact templates from the standing job rules,
   unless they are already present.
4. Updates index.html: latest edition card and a new archive entry.
5. Pushes images, audio, edition, and index with gh-api, verifies each push,
   and checks the Pages build. A 401 or 403 from GitHub stops everything
   with a clear message (standing rule).
6. Appends the one line edition note to the daily log and prints the report.

Usage: finalize.py --edition 8 --blurb "short archive blurb" [--styles]
                   [--dry-run] [--workdir PATH] [--skip-podcast]
--dry-run does all local work but skips the GitHub pushes and build check.
--skip-podcast exists for testing the text, embed, and index steps only.
"""
import json, re, shutil, subprocess, sys, time
from datetime import datetime
from html import unescape
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/New_York")
GH = Path.home() / "workspace/skills/github/bin/gh-api"
GEMINI = Path.home() / "workspace/custom-connectors/custom.gemini/bin/gemini_generate.py"
REPO = "NJShell2/patch-tuesday-plus"
PACK_URL = "https://payhip.com/b/pXhFW"
PACK_SECTION = (
    '<div class="signup pack-promo" id="pack">\n'
    '  <h2>Automate the routine work</h2>\n'
    '  <p>Stop doing AD user management by hand. The Windows IT Admin Automation Pack gives you '
    'five PowerShell scripts for bulk onboarding, safe offboarding, stale account cleanup, group '
    'audits, and a Microsoft 365 license audit, plus a quick-start guide and sample CSVs. Built by '
    'a working IT desktop support engineer.</p>\n'
    f'  <a class="button" href="{PACK_URL}">Get the pack, $39 one time</a>\n'
    '  <p>Also new: the <a href="https://payhip.com/b/YFrg1">Windows Patch &amp; Endpoint '
    'Health Toolkit</a>, five read-only scripts for patch health, Windows 11 readiness, stale '
    'computer accounts, local admin audits, and failed-update reports. $49 one time.</p>\n'
    '  <p class="fine">One-time purchase, free v1.x updates, single-seat commercial license. '
    'Delivered instantly by Payhip.</p>\n'
    '</div>')
FREEKIT_URL = "https://payhip.com/buy?s=1&cart_links%5B%5D=1vIyB&qty%5B1vIyB%5D=1"
FREEKIT_SECTION = (
    '<div class="signup pack-promo" id="freekit">\n'
    '  <h2>Start with the free Triage Kit</h2>\n'
    '  <p>The Patch Tuesday Triage Kit is free: the one-page triage order with checkboxes, plus '
    'Get-WindowsUpdateHealth.ps1, a read-only script that flags pending reboots, stale hotfixes, '
    'and low disk space before they break your patch cycle.</p>\n'
    f'  <a class="button" href="{FREEKIT_URL}">Get the free Triage Kit</a>\n'
    '  <p class="fine">Free download from Payhip, no card needed. Includes the checklist PDF, '
    'the script, and a quick-start README.</p>\n'
    '</div>')


def ensure_pack_promo(html, back_link):
    """Insert the Payhip pack promo once, just before the back-to-home line,
    and the free Triage Kit promo once, just before the pack promo."""
    if PACK_URL not in html:
        marker = f'<p><a href="{back_link}">&larr; Back to home</a></p>'
        if marker in html:
            html = html.replace(marker, PACK_SECTION + "\n\n    " + marker, 1)
        else:
            html = html.replace("</main>", PACK_SECTION + "\n</main>", 1)
    if FREEKIT_URL not in html:
        html = html.replace('<div class="signup pack-promo" id="pack">',
                            FREEKIT_SECTION + '\n\n    <div class="signup pack-promo" id="pack">', 1)
    return html


def run(cmd, timeout=300, ok_codes=(0,)):
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if p.returncode not in ok_codes:
        raise RuntimeError(f"command failed ({' '.join(str(c) for c in cmd[:3])}...): "
                           f"{(p.stderr or p.stdout).strip()[:400]}")
    return p.stdout


def strip_tags(s):
    s = re.sub(r"<script.*?</script>|<style.*?</style>", " ", s, flags=re.S)
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def edition_text(html):
    body = re.search(r"<body>(.*)</body>", html, re.S).group(1)
    body = re.sub(r'<section class="edition-podcast".*?</section>', " ", body, flags=re.S)
    body = re.sub(r'<div class="signup pack-promo".*?</div>\s*</div>', " ", body, flags=re.S)
    body = re.sub(r'<div class="signup pack-promo".*?</p>\s*</div>', " ", body, flags=re.S)
    return strip_tags(body)


PLUG_LINE = "Marcus: Get the free Patch Tuesday Triage Kit, linked right on this page."
MID_LINE = ("Marcus: Quick break. The free Triage Kit pairs the one page patching order with a "
            "read only script that flags failing machines early. Grab it free, linked on this page.")


def draft_script(text, num):
    prompt = (
        f"Write the spoken briefing script for Patch Tuesday Plus Edition #{num} from the edition "
        "text below. One host, Marcus, talking to IT admins. Follow the edition's section order "
        "exactly, top to bottom, so a listener can scroll along: lede first, then the three Patch "
        "now items with the most time (what happened, who is affected, what to do), then Watch "
        "items with moderate time, then one brisk dismissive line per Ignore item, then the On "
        "deck look-ahead.\n\n"
        "Sponsor lines, both mandatory and verbatim:\n"
        f"- The script MUST begin with this exact line, word for word, as its first line: {PLUG_LINE}\n"
        "- After you finish covering the FIRST Patch now item, and before you begin the second "
        f"Patch now item, insert this exact line, word for word, on its own line: {MID_LINE}\n"
        "- Do not alter, repeat, or add any other sponsor or product mention.\n\n"
        "Format rules, all mandatory:\n"
        "- Every non-blank line starts with 'Marcus: '\n"
        "- 1200 to 1600 words total, counting the two sponsor lines\n"
        "- Spell out all numbers as words\n"
        "- No stage directions, no markup, no emoji, no URLs read aloud\n"
        "- No em dashes\n"
        "- Direct, plain spoken, no hype\n\n"
        "EDITION TEXT:\n" + text[:14000])
    pf = Path("/tmp/ptp-script-prompt.txt")
    words = 0
    for attempt in (1, 2):
        pf.write_text(prompt)
        p = subprocess.run(["python3", str(GEMINI), str(pf)], capture_output=True, text=True, timeout=300)
        if p.returncode != 0:
            raise RuntimeError(f"Gemini script draft failed: {p.stderr.strip()[:200]}")
        script = p.stdout.strip()
        lines = [ln for ln in script.splitlines() if ln.strip()]
        script = "\n".join(ln if ln.startswith("Marcus: ") else "Marcus: " + ln.lstrip("- ").strip()
                           for ln in lines)
        # Sponsor opening plug: guaranteed first line, exactly once (deterministic, not left to the draft).
        slines = [ln for ln in script.split("\n") if ln != PLUG_LINE]
        slines.insert(0, PLUG_LINE)
        script = "\n".join(slines)
        # Sponsor mid-briefing pitch: must appear verbatim between the first and second Patch now items.
        if MID_LINE not in script:
            if attempt == 1:
                prompt += ("\n\nYour previous draft was missing the mandatory mid-briefing sponsor "
                           "line. Write a fresh draft and include the exact sponsor line given "
                           "above, on its own line, between the first and second Patch now items.")
                continue
            raise RuntimeError("draft script missing the mandatory Triage Kit mid-briefing line "
                               "after 2 attempts; editor review needed")
        words = len(script.split())
        if "http" in script or "—" in script:
            raise RuntimeError("draft script failed validation (URL or em dash present)")
        if 1000 <= words <= 1800:
            return script, words
        direction = "too long, cut it down" if words > 1800 else "too short, expand it"
        prompt += (f"\n\nYour previous draft was {words} words, {direction}. Write a fresh draft of "
                   f"1200 to 1600 words, keeping the Patch now items the fullest part.")
    raise RuntimeError(f"draft script word count {words} outside 1000 to 1800 after 2 attempts; "
                       f"editor review needed")


def gh_push(repo_path, local_path, message):
    out = run([str(GH), "put-file", REPO, repo_path, str(local_path),
               "--message", message, "--branch", "main"], timeout=600)
    if "401" in out or "403" in out:
        raise RuntimeError("GitHub credential rejected (401/403). The GitHub token needs attention.")
    run([str(GH), "get-file", REPO, repo_path], timeout=120)


def main():
    args = sys.argv[1:]
    num = int(args[args.index("--edition") + 1])
    nnn = f"{num:03d}"
    dry = "--dry-run" in args
    skip_pod = "--skip-podcast" in args
    ws = Path(args[args.index("--workdir") + 1]) if "--workdir" in args \
        else Path.home() / "workspace/patch-tuesday-plus"
    blurb = args[args.index("--blurb") + 1] if "--blurb" in args else ""
    ed_path = ws / "editions" / f"edition-{nnn}.html"
    html = ed_path.read_text()

    assets = sorted((ws / "assets" / f"edition-{nnn}").glob("*.png"))
    if len(assets) < 4:
        print(f"ERROR: expected 4 images in assets/edition-{nnn}/ (hero + 3 Patch now), "
              f"found {len(assets)}. Generate the images first.", file=sys.stderr)
        sys.exit(1)

    h1 = re.search(r"<h1>Edition #\d+: (Week of [^<]+)</h1>", html)
    range_str = h1.group(1) if h1 else ""
    lede_m = re.search(r'<p class="lede">(.*?)</p>', html, re.S)
    lede = strip_tags(lede_m.group(1)) if lede_m else ""

    duration = "0:00"
    if not skip_pod:
        script, words = draft_script(edition_text(html), num)
        spath = Path(f"/tmp/ptp-edition-{nnn}-script.txt")
        spath.write_text(script + "\n")
        topics = Path("/tmp/ptp-topics.md")
        topics.write_text(f"Patch Tuesday Plus Edition #{num}: {blurb or lede[:120]}\n")
        # Full-length briefings (1000-1800 words) can take well over the
        # 900s that timed out in the Nov 3, 2026 test; allow 2400s per
        # attempt and retry once if the generator stalls.
        out = None
        for attempt in (1, 2):
            try:
                out = run(["podcast-helper", "generate", "--script", str(spath),
                           "--title", f"Patch Tuesday Plus: Edition #{num} Briefing",
                           "--description", f"Marcus briefs Edition #{num} of Patch Tuesday Plus.",
                           "--speaker", "Marcus=avocado_v2:MAI_03",
                           "--topics-file", str(topics)], timeout=2400)
                break
            except subprocess.TimeoutExpired:
                if attempt == 2:
                    raise RuntimeError("podcast-helper timed out twice (2400s each) "
                                       "generating the briefing audio")
                print("Podcast generation timed out at 2400s; retrying once.")
        m = re.search(r"(/[^\s\"']+\.mp3)", out)
        if not m:
            raise RuntimeError(f"podcast-helper finished but no MP3 path found in its output: {out[:300]}")
        src = Path(m.group(1))
        audio_dir = ws / "audio"
        audio_dir.mkdir(exist_ok=True)
        dest = audio_dir / f"edition-{nnn}.mp3"
        shutil.copyfile(src, dest)
        if dest.stat().st_size == 0:
            raise RuntimeError("generated MP3 is 0 bytes")
        dur = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                   "-of", "csv=p=0", str(dest)], timeout=60).strip()
        secs = int(float(dur))
        duration = f"{secs // 60}:{secs % 60:02d}"
        print(f"Podcast: {dest} ({dest.stat().st_size} bytes, {duration}, script {words} words)")

    if 'class="edition-podcast"' not in html:
        embed = (
            '<section class="edition-podcast" id="listen">\n'
            '  <h2 class="podcast-heading">Listen to this edition</h2>\n'
            f'  <p class="podcast-meta">Marcus reads Edition #{num} &middot; {duration}</p>\n'
            f'  <audio controls preload="metadata" src="../audio/edition-{nnn}.mp3"></audio>\n'
            '  <div><button class="share-btn" type="button" data-share>Copy link to this episode</button></div>\n'
            '</section>')
        html, nsub = re.subn(r'(<p class="meta">.*?</p>)', r"\1\n" + embed, html, count=1, flags=re.S)
        if nsub == 0:
            raise RuntimeError("could not find the meta line to embed the podcast after")
        share = (
            "<script>\n(function () {\n"
            '  var btn = document.querySelector("[data-share]");\n'
            "  if (btn) {\n"
            '    btn.addEventListener("click", function () {\n'
            f'      var link = "https://njshell2.github.io/patch-tuesday-plus/editions/edition-{nnn}.html#listen";\n'
            "      function done(ok) {\n"
            '        btn.textContent = ok ? "Copied!" : "Copy failed";\n'
            '        setTimeout(function () { btn.textContent = "Copy link to this episode"; }, 2000);\n'
            "      }\n"
            "      if (navigator.clipboard && navigator.clipboard.writeText) {\n"
            "        navigator.clipboard.writeText(link).then(function () { done(true); }, function () { done(false); });\n"
            "      } else {\n"
            '        var ta = document.createElement("textarea");\n'
            "        ta.value = link;\n"
            "        document.body.appendChild(ta);\n"
            "        ta.select();\n"
            '        try { done(document.execCommand("copy")); } catch (e) { done(false); }\n'
            "        document.body.removeChild(ta);\n"
            "      }\n"
            "    });\n"
            "  }\n"
            "  function revealFromHash() {\n"
            '    if (location.hash !== "#listen") return;\n'
            '    var target = document.getElementById("listen");\n'
            "    if (!target) return;\n"
            '    target.scrollIntoView({ block: "center" });\n'
            '    target.classList.remove("flash");\n'
            "    void target.offsetWidth;\n"
            '    target.classList.add("flash");\n'
            '    setTimeout(function () { target.classList.remove("flash"); }, 2500);\n'
            "  }\n"
            '  window.addEventListener("hashchange", revealFromHash);\n'
            "  revealFromHash();\n"
            "})();\n</script>\n")
        html = html.replace("</body>", share + "</body>")
        ed_path.write_text(html)
        print(f"Embed: podcast section and share script inserted ({duration})")

    new_html = ensure_pack_promo(html, "../index.html")
    if new_html != html:
        html = new_html
        ed_path.write_text(html)
        print("Pack promo: Payhip pack section inserted into the edition")

    idx_path = ws / "index.html"
    idx = idx_path.read_text()
    if PACK_URL not in idx:
        idx = idx.replace('<div class="signup" id="signup">',
                          PACK_SECTION + '\n\n    <div class="signup" id="signup">', 1)
        print("Pack promo: Payhip pack section inserted into index.html")
    if FREEKIT_URL not in idx:
        idx = idx.replace('<div class="signup pack-promo" id="pack">',
                          FREEKIT_SECTION + '\n\n    <div class="signup pack-promo" id="pack">', 1)
        print("Free kit promo: Triage Kit section inserted into index.html")
    card = (f'<h3><a href="editions/edition-{nnn}.html">Edition #{num}: {range_str}</a></h3>\n'
            f'      <p>{lede}</p>\n'
            f'      <p><a href="editions/edition-{nnn}.html">Read Edition #{num} &rarr;</a></p>')
    idx2, nsub = re.subn(r"<h3><a href=\"editions/edition-\d+\.html\">Edition #\d+: [^<]+</a></h3>\s*"
                         r"<p>.*?</p>\s*<p><a href=\"editions/edition-\d+\.html\">Read Edition #\d+ &rarr;</a></p>",
                         card, idx, count=1, flags=re.S)
    if nsub == 0:
        raise RuntimeError("could not find the latest edition card in index.html")
    idx = idx2
    if f"editions/edition-{nnn}.html" not in idx.split('id="archive"')[1].split("</ul>")[0]:
        li = (f'      <li>\n'
              f'        <span class="ed-num"><a href="editions/edition-{nnn}.html">Edition #{num}</a></span>\n'
              f'        <span class="ed-date"> &middot; {range_str}</span>\n'
              f'        <br>{blurb or lede[:150]}\n'
              f'      </li>\n')
        idx = idx.replace('<ul class="archive">\n', '<ul class="archive">\n' + li, 1)
    idx_path.write_text(idx)
    print("Index: latest card and archive entry updated")

    if dry:
        print("DRY RUN: skipping GitHub pushes and Pages build check")
    else:
        for a in assets:
            gh_push(f"assets/edition-{nnn}/{a.name}", a, f"Add images for Edition #{num}")
        if not skip_pod:
            gh_push(f"audio/edition-{nnn}.mp3", ws / "audio" / f"edition-{nnn}.mp3",
                    f"Add briefing audio for Edition #{num}")
        gh_push(f"editions/edition-{nnn}.html", ed_path, f"Add Edition #{num}: {range_str}")
        gh_push("index.html", idx_path, f"Update homepage for Edition #{num}")
        if "--styles" in args:
            gh_push("styles.css", ws / "styles.css", f"Update styles for Edition #{num}")
        status = ""
        for _ in range(3):
            out = run([str(GH), "pages-build", REPO], timeout=120)
            status = out.strip()[:200]
            if "built" in status.lower():
                break
            time.sleep(45)
        print(f"Pages build: {status}")
        log = Path.home() / f"memory/{datetime.now(TZ).date().isoformat()}.md"
        with log.open("a") as f:
            f.write(f"\n- Patch Tuesday Plus Edition #{num} published (finalize script): "
                    f"{range_str}, Marcus briefing {duration}.\n")
    print(f"Edition #{num} ({range_str}) ready at "
          f"https://njshell2.github.io/patch-tuesday-plus/editions/edition-{nnn}.html "
          f"with the Marcus briefing ({duration}) embedded at the top.")


if __name__ == "__main__":
    main()
