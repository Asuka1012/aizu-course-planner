#!/usr/bin/env python3
"""Inject data/*.json into the app template to produce the standalone index.html."""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = os.path.join(ROOT, "scripts", "app_template.html")
OUT = os.path.join(ROOT, "index.html")


def load(name):
    with open(os.path.join(ROOT, "data", name), encoding="utf-8") as f:
        return json.load(f)


def safe_json(obj):
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    # prevent premature </script> termination if any string contains it
    text = re.sub(r"</(script)", r"<\\/\1", text, flags=re.I)
    return text


def main():
    courses = load("courses.json")
    timetable = load("timetable.json")
    gradreq = load("graduation_requirements.json")
    teaching = load("teaching_license.json")

    with open(TEMPLATE, encoding="utf-8") as f:
        html = f.read()

    html = html.replace("__COURSES_JSON__", safe_json(courses))
    html = html.replace("__TIMETABLE_JSON__", safe_json(timetable))
    html = html.replace("__GRADREQ_JSON__", safe_json(gradreq))
    html = html.replace("__TEACHING_JSON__", safe_json(teaching))

    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Wrote {OUT} ({os.path.getsize(OUT)/1024:.0f} KB)")


if __name__ == "__main__":
    main()
