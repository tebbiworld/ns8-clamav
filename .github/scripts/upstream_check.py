#!/usr/bin/env python3
"""Print the newest upstream image tag and compare it with the pinned one.

Reads UPSTREAM_IMAGE (docker.io/<ns>/<repo>), TAG_REGEX (anchored regex the
version tags must match; the numeric groups are compared) and BUILD_SCRIPT
(build-images.sh holding the pinned reference). Writes newest/current/newer to
$GITHUB_OUTPUT.
"""
import json
import os
import re
import sys
import urllib.request

image = os.environ["UPSTREAM_IMAGE"]
regex = re.compile(os.environ["TAG_REGEX"])
script = os.environ.get("BUILD_SCRIPT", "build-images.sh")
repo = image.split("/", 1)[1] if image.startswith("docker.io/") else image

def numeric(tag):
    return [int(x) for x in re.findall(r"\d+", regex.match(tag).group("ver"))]

tags, url = [], f"https://hub.docker.com/v2/repositories/{repo}/tags?page_size=100&ordering=last_updated"
while url and len(tags) < 400:
    with urllib.request.urlopen(url, timeout=30) as r:
        d = json.load(r)
    tags += [t["name"] for t in d["results"]]
    url = d.get("next")
versions = [t for t in tags if regex.match(t)]
if not versions:
    print("no version tags found", file=sys.stderr); sys.exit(1)
newest = max(versions, key=numeric)

current = ""
for line in open(script):
    m = re.search(rf'{re.escape(image)}:([A-Za-z0-9_.-]+)', line)
    if m:
        current = m.group(1); break
if not current:
    print("pinned tag not found in", script, file=sys.stderr); sys.exit(1)

newer = regex.match(current) is not None and numeric(newest) > numeric(current)
print(f"current={current} newest={newest} newer={newer}")
with open(os.environ.get("GITHUB_OUTPUT", "/dev/null"), "a") as fp:
    fp.write(f"current={current}\nnewest={newest}\nnewer={'true' if newer else 'false'}\n")
