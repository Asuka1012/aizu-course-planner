#!/usr/bin/env python3
"""Parse Aizu University timetable HTML pages into data/timetable.json."""
import re
import json
import os
import html

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TT_DIR = os.path.join(ROOT, "raw", "timetable")
OUT = os.path.join(ROOT, "data", "timetable.json")

# filename pattern: 1-6{year}j = Q1, 1-7{year}j = Q2, 1-8{year}j = Q3, 1-9{year}j = Q4
QUARTER_DIGIT = {"6": 1, "7": 2, "8": 3, "9": 4}

FIELD_LABELS = {"CS", "SY", "CN", "IT-SPR", "IT-CMV", "SE-DE"}
CLASS_LABEL_RE = re.compile(r"^C[1-6]$")
E_LABEL_RE = re.compile(r"^\d+E\d+(-\d+E\d+)?$")
FLAG_LABELS = {"演", "再", "SR"}


def strip_tags(s):
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    return s.strip()


def classify_bracket(label):
    if label in FIELD_LABELS:
        return "field"
    if CLASS_LABEL_RE.match(label):
        return "class"
    if E_LABEL_RE.match(label):
        return "eclass"
    return "flag"


CODE_RE = re.compile(r"^([A-Za-z]{1,4}\d{2,4}(?:-[A-Za-z0-9]+)?)\s+(.*)$", re.S)
TOKEN_RE = re.compile(r"\[([^\]]*)\]|\(([^)]*)\)")


def parse_line(raw_line):
    """Parse one <BR>-separated course line (already tag-stripped except FONT/B)."""
    recommendation = "general"
    line = raw_line
    m = re.search(r'<FONT color="(tomato|blue|red)"', line, re.I)
    if m:
        color = m.group(1).lower()
        recommendation = "basic" if color in ("tomato", "red") else "field"
    line = re.sub(r"</?FONT[^>]*>", "", line, flags=re.I)
    line = re.sub(r"</?B>", "", line, flags=re.I)
    line = html.unescape(line).strip()
    if not line:
        return None
    if "[再]" in line:
        return None  # retake slot - ignore per spec

    cm = CODE_RE.match(line)
    if cm:
        code, rest = cm.group(1), cm.group(2)
    else:
        code, rest = "", line

    # name = text before first '[' or '('
    name_m = re.match(r"([^\[\(]*)", rest)
    name = name_m.group(1).strip() if name_m else ""
    remainder = rest[len(name):]

    tags = []
    field_tag = None
    pending_labels = []
    assignments = []
    default_room_instructors = None

    for tok in TOKEN_RE.finditer(remainder):
        bracket, paren = tok.group(1), tok.group(2)
        if bracket is not None:
            label = bracket.strip()
            kind = classify_bracket(label)
            if kind == "field":
                field_tag = label
            elif kind in ("class", "eclass"):
                pending_labels.append(label)
            else:
                tags.append(label)
        else:
            parts = [p.strip() for p in paren.split(",") if p.strip()]
            room = parts[0] if parts else ""
            instructors = parts[1:] if len(parts) > 1 else []
            if pending_labels:
                for lbl in pending_labels:
                    assignments.append({"label": lbl, "room": room, "instructors": instructors})
                pending_labels = []
            else:
                default_room_instructors = {"room": room, "instructors": instructors}

    if "SR" in tags:
        # [SR] is the authoritative marker for 基本推奨科目 (confirmed by domain owner),
        # more reliable than font-color detection alone.
        recommendation = "basic"

    entry = {
        "code": code,
        "name": name,
        "recommendation": recommendation,
        "field_tag": field_tag,
        "tags": tags,
    }
    if assignments:
        entry["class_assignments"] = assignments
    if default_room_instructors:
        entry["room"] = default_room_instructors["room"]
        entry["instructors"] = default_room_instructors["instructors"]
    return entry


def parse_file(path, year, quarter):
    text = read(path)
    entries = []

    header_m = re.search(r"<THEAD>(.*?)</THEAD>", text, re.S)
    columns = []
    if header_m:
        for th in re.findall(r"<TH[^>]*>(.*?)</TH>", header_m.group(1), re.S):
            label = strip_tags(th)
            if label and label != " ":
                columns.append(label)

    body_m = re.search(r"<TBODY>(.*?)</TBODY>", text, re.S)
    if not body_m:
        return entries
    body = body_m.group(1)

    rows = re.findall(r"<TR>(.*?)</TR>", body, re.S)
    for row in rows:
        row_header_m = re.search(r'<TD scope="row">([^<]*)</TD>', row)
        if not row_header_m:
            continue  # separator <HR> row
        header_text = row_header_m.group(1).strip()
        dm = re.match(r"([月火水木金土日])(\d+)", header_text)
        if not dm:
            continue
        day, period = dm.group(1), int(dm.group(2))

        cells = re.findall(r"<TD>(.*?)</TD>", row, re.S)
        for col_idx, cell in enumerate(cells):
            if col_idx >= len(columns):
                continue
            column = columns[col_idx]
            cell = cell.strip()
            if cell in ("<BR>", ""):
                continue
            for raw_line in re.split(r"<BR>", cell, flags=re.I):
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                parsed = parse_line(raw_line)
                if parsed is None:
                    continue
                entries.append({
                    "year": year,
                    "quarter": quarter,
                    "column": column,
                    "day": day,
                    "period": period,
                    **parsed,
                })
    return entries


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def resolve_course_ids(entries):
    """Attach course_id by matching timetable code (+name fallback) to courses.json."""
    courses_path = os.path.join(ROOT, "data", "courses.json")
    with open(courses_path, encoding="utf-8") as f:
        courses = json.load(f)
    by_code = {}
    by_code_name = {}
    for c in courses:
        by_code.setdefault(c["code"], c["id"])
        by_code_name[(c["code"], c["name_ja"])] = c["id"]
        for pref in (c["code"].split("-")[0],):
            by_code_name.setdefault((pref, c["name_ja"]), c["id"])

    unresolved = []
    for e in entries:
        code = e["code"]
        if not code:
            e["course_id"] = None
            continue
        cid = by_code.get(code)
        if cid is None:
            stripped_name = re.sub(r"\s*\([^)]*\)\s*$", "", e["name"]).strip()
            cid = by_code_name.get((code, stripped_name))
        if cid is None:
            unresolved.append(code)
        e["course_id"] = cid
    if unresolved:
        print("Unresolved timetable codes (no course_id match):", sorted(set(unresolved)))
    return entries


def main():
    all_entries = []
    for year in "1234":
        for qdigit, qnum in QUARTER_DIGIT.items():
            fname = f"tt_1-{qdigit}{year}j.html"
            path = os.path.join(TT_DIR, fname)
            if not os.path.exists(path):
                print("MISSING", fname)
                continue
            entries = parse_file(path, int(year), qnum)
            all_entries.extend(entries)

    all_entries = resolve_course_ids(all_entries)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(all_entries, f, ensure_ascii=False, indent=1)
    print(f"Wrote {len(all_entries)} timetable entries to {OUT}")


if __name__ == "__main__":
    main()
