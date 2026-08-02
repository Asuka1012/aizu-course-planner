#!/usr/bin/env python3
"""Parse Aizu University syllabus HTML (JA + EN) into data/courses.json."""
import re
import json
import os
import html

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JA_DIR = os.path.join(ROOT, "raw", "syllabus_ja")
EN_DIR = os.path.join(ROOT, "raw", "syllabus_en")
OUT = os.path.join(ROOT, "data", "courses.json")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def strip_tags(s):
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n", s)
    return s.strip()


def parse_index(path):
    """Returns dict: code -> {daikbn, chukbn, cat_page}"""
    text = read(path)
    info = {}
    # split into daikbn ("box") sections
    boxes = re.split(r'<div class="box">', text)[1:]
    for box in boxes:
        m = re.search(r'class="daikbn"><img[^>]*/?>\s*([^<]+)', box)
        daikbn = m.group(1).strip() if m else ""
        chukbn = ""
        # walk through box line by line preserving order of chukbn / kamoku entries
        # split by chukbn markers and kamoku links, keeping order via finditer over combined pattern
        pattern = re.compile(
            r'class="chukbn">\s*([^<]+?)\s*</td>|'
            r'<a href="(2026_1_J_0\d\d\.html)#([A-Za-z0-9]+)">\s*([A-Za-z0-9-]+)\s+([^<]+?)\s*</a>'
        )
        for mm in pattern.finditer(box):
            if mm.group(1) is not None:
                chukbn = mm.group(1).strip()
            else:
                cat_page, anchor, code, name_ja = mm.group(2), mm.group(3), mm.group(4), mm.group(5)
                info[anchor] = {
                    "code": code,
                    "name_ja_index": html.unescape(name_ja.strip()),
                    "daikbn": daikbn,
                    "chukbn": chukbn,
                    "cat_page": cat_page,
                }
    return info


NO_PREREQ_PHRASES = {
    "なし", "特になし", "特に指定しない", "n/a", "na", "none",
    "no prerequisite", "no prerequisites", "－", "-",
}

# The syllabus's own 先修科目/Essential courses field is an advisory "courses
# you should have studied beforehand" list, not the same thing as an actual
# registration prerequisite - the official course-registration simulation
# system (crpsap.u-aizu.ac.jp) enforces a separate, distinct set of hard
# prerequisites that block registration when unmet. For courses like FU06 the
# two even contradict each other (the syllabus text listed a course offered in
# a LATER quarter than FU06 itself, which can't be a real prerequisite).
#
# This map was hand-verified against the crps course-registration planner
# (screenshots checked against its "先修科目: X and Y and ..." popovers) and is
# now the sole source of truth for essential_courses - it supersedes the
# syllabus scrape entirely. Any course not listed here has no crps-enforced
# prerequisite, even if its syllabus text suggests otherwise.
CRPS_PREREQUISITES = {
    "SE05": ["FU14"],
    "MA09": ["FU03", "FU08"],
    "LI14": ["MA05", "FU01"],
    "MA04": ["MA03"],
    "MA06": ["MA03"],
    "MA08": ["MA01", "FU03"],
    "MA11": ["PL01", "FU03", "MA01", "MA10"],
    "PL05": ["PL02", "PL03", "FU01"],
    "MA10": ["MA01"],
    "FU09": ["MA01", "FU03", "PL02", "FU01"],
    "FU10": ["FU08"],
    "FU05": ["FU04"],
    "MA02": ["MA01"],
    "SY06": ["LI13", "NS04", "FU04"],
    "SY02": ["LI13", "NS04"],
    "FU02": ["MA07", "LI04", "FU01", "FU03"],
    "FU14": ["PL03"],
    "MA05": ["MA01", "MA03"],
    "FU08": ["FU01", "FU03"],
    "SY07": ["FU04"],
    "SY04": ["FU05", "FU06", "FU14", "PL02"],
    "IT06": ["LI10", "IT02"],
    "MA07": ["MA03"],
    "LI06": ["LI01"],
    "IT10": ["MA01", "FU01", "FU03"],
    "CN03": ["LI11", "PL02"],
    "CN05": ["LI11", "PL04", "CN04"],
    "IT02": ["PL02"],
    "PL03": ["PL02"],
    "IT01": ["LI14", "FU01", "MA09", "FU03"],
    "SE06": ["PL03"],
    "IE04": ["IE03", "FU14"],
}


def parse_essential_courses(essential_raw):
    """Parse the 先修科目/Essential courses field into a clean list of course
    references, filtering out "no prerequisite" phrases and the boilerplate
    lead-in sentence (which can wrap a <BR> mid-word, so a naive per-line
    keyword check misses the first half of it - strip the whole sentence
    against the un-split text instead)."""
    text = essential_raw.strip()
    if not text:
        return []
    text = re.sub(r"事前に学んでおいてほしい科目一覧.*?進めます[）)]", "", text, flags=re.S)
    text = re.sub(
        r"Courses? preferred to be learned prior to this course.*?following course[s]?\)?[:：]?",
        "", text, flags=re.S,
    )
    text = text.strip()

    normalized = text.strip(" 　.。").lower()
    if not normalized or normalized in NO_PREREQ_PHRASES:
        return []

    items = []
    for raw_item in re.split(r"[,、\n]", text):
        item = raw_item.strip(" 　・-*")
        if not item:
            continue
        if item.lower() in ("and", "or"):
            continue
        if "既知として" in item or "assumes understanding" in item:
            continue
        items.append(item)
    return items


def normalize_quarter(label):
    """Map raw 開講学期 text to a list of quarter numbers [1-4] (best effort)."""
    if "前期" in label and "後期" in label:
        return [1, 2, 3, 4]
    if "前期" in label:
        return [1, 2]
    if "後期" in label:
        return [3, 4]
    nums = [int(n) for n in re.findall(r"([1-4])学期", label)]
    if nums:
        return sorted(set(nums))
    return []


FIELD_LABELS = {
    "quarter": "開講学期",
    "target_year": "対象学年",
    "credits": "単位数",
    "coordinator": "責任者",
    "instructors": "担当教員名",
    "track": "推奨トラック",
    "essential": "先修科目",
    "outline": "授業の概要",
}


def parse_category_ja(path):
    """Returns dict: anchor_id -> record"""
    text = read(path)
    records = {}
    blocks = re.split(r'<div id="(S[A-Za-z0-9]+)"\s+style="padding', text)[1:]
    # blocks alternates: anchor_id, block_text, anchor_id, block_text, ...
    for i in range(0, len(blocks) - 1, 2):
        anchor = blocks[i]
        block = blocks[i + 1]
        # cut off at next div id start already excluded by split
        title_m = re.search(r'<a href="#tabs-1">\s*([A-Za-z0-9-]+)\s+([^<]+?)\s*</a>', block)
        code = title_m.group(1) if title_m else ""
        name_ja = html.unescape(title_m.group(2).strip()) if title_m else ""

        def field(label):
            m = re.search(
                r'<th[^>]*>\s*' + re.escape(label) + r'.*?</th>\s*<td[^>]*>(.*?)</td>',
                block,
                re.S,
            )
            return strip_tags(m.group(1)) if m else ""

        quarter_label = field(FIELD_LABELS["quarter"])
        quarter = normalize_quarter(quarter_label)
        target_year_raw = field(FIELD_LABELS["target_year"])
        target_year = [t.strip() for t in re.split(r"[,\n]", target_year_raw) if t.strip()]
        credits_raw = field(FIELD_LABELS["credits"])
        try:
            credits = float(re.search(r"[\d.]+", credits_raw).group())
        except Exception:
            credits = None
        coordinator = field(FIELD_LABELS["coordinator"])
        instructors_raw = field(FIELD_LABELS["instructors"])
        instructors = [t.strip() for t in re.split(r"[,\n、]", instructors_raw) if t.strip()]
        essential_raw = field(FIELD_LABELS["essential"])
        essential = parse_essential_courses(essential_raw)
        outline = field(FIELD_LABELS["outline"])

        records[anchor] = {
            "code": code,
            "name_ja": name_ja,
            "quarter": quarter,
            "quarter_label": quarter_label,
            "target_year": target_year,
            "credits": credits,
            "coordinator": coordinator,
            "instructors": instructors,
            "essential_courses": essential,
            "outline": outline,
        }
    return records


def parse_category_en(path):
    """Returns dict: anchor_id -> name_en"""
    text = read(path)
    names = {}
    blocks = re.split(r'<div id="(S[A-Za-z0-9]+)"\s+style="padding', text)[1:]
    for i in range(0, len(blocks) - 1, 2):
        anchor = blocks[i]
        block = blocks[i + 1]
        title_m = re.search(r'<a href="#tabs-1">\s*([A-Za-z0-9-]+)\s+([^<]+?)\s*</a>', block)
        if title_m:
            names[anchor] = html.unescape(title_m.group(2).strip())
    return names


def main():
    index_info = parse_index(os.path.join(JA_DIR, "000.html"))

    all_records = {}
    for i in range(1, 22):
        num = f"{i:03d}"
        ja_path = os.path.join(JA_DIR, f"{num}.html")
        en_path = os.path.join(EN_DIR, f"{num}.html")
        if not os.path.exists(ja_path):
            continue
        ja_records = parse_category_ja(ja_path)
        en_names = parse_category_en(en_path) if os.path.exists(en_path) else {}
        for anchor, rec in ja_records.items():
            rec["name_en"] = en_names.get(anchor, "")
            all_records[anchor] = rec

    courses = []
    for anchor, idx in index_info.items():
        rec = all_records.get(anchor)
        if rec is None:
            continue
        courses.append({
            "id": anchor,
            "code": rec["code"] or idx["code"],
            "name_ja": rec["name_ja"] or idx["name_ja_index"],
            "name_en": rec["name_en"],
            "credits": rec["credits"],
            "target_year": rec["target_year"],
            "quarter": rec["quarter"],
            "quarter_label": rec["quarter_label"],
            "category": {"major": idx["daikbn"], "minor": idx["chukbn"]},
            "coordinator": rec["coordinator"],
            "instructors": rec["instructors"],
            "essential_courses": rec["essential_courses"],
            "outline": rec["outline"],
        })

    # anchors present in category pages but missing from index (rare) -> append too
    for anchor, rec in all_records.items():
        if anchor not in index_info:
            courses.append({
                "id": anchor,
                "code": rec["code"],
                "name_ja": rec["name_ja"],
                "name_en": rec["name_en"],
                "credits": rec["credits"],
                "target_year": rec["target_year"],
                "quarter": rec["quarter"],
                "quarter_label": rec["quarter_label"],
                "category": {"major": "", "minor": ""},
                "coordinator": rec["coordinator"],
                "instructors": rec["instructors"],
                "essential_courses": rec["essential_courses"],
                "outline": rec["outline"],
            })

    # crps-verified prerequisites supersede the syllabus scrape entirely (see
    # CRPS_PREREQUISITES above) - any course not in that map has no
    # crps-enforced prerequisite, regardless of what its syllabus text says.
    code_to_name = {c["code"]: c["name_ja"] for c in courses}
    for c in courses:
        prereq_codes = CRPS_PREREQUISITES.get(c["code"], [])
        c["essential_courses"] = [f"{p} {code_to_name.get(p, '')}".strip() for p in prereq_codes]

    courses.sort(key=lambda c: c["code"])
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(courses, f, ensure_ascii=False, indent=1)
    print(f"Wrote {len(courses)} courses to {OUT}")


if __name__ == "__main__":
    main()
