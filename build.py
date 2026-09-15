"""Embed data.json into template.html and write the site's index.html."""
import json, pathlib

here = pathlib.Path(__file__).parent
data = json.loads((here / "data.json").read_text())
payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
body = (here / "template.html").read_text().replace("/*DATA*/null", payload)

html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>⚽</text></svg>">
</head>
<body>
{body}
</body>
</html>
"""
(here / "index.html").write_text(html)
print("built index.html,", len(html), "bytes")
