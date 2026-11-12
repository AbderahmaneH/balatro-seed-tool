#!/usr/bin/env python3
"""Builds the standalone page: ui/index.html + ui/engine.js + game data (from game.lua) -> one HTML file.
   python build_ui.py              -> "Balatro Seed Tool.html" (double-click it: works offline, no Python needed)"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))          # tools/
ROOT = os.path.dirname(HERE)                              # repository root
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, 'src'))

def page(artifact=False):
    from gen_js_data import build
    tpl = open(os.path.join(ROOT, 'ui', 'index.html'), encoding='utf-8').read()
    eng = open(os.path.join(ROOT, 'ui', 'engine.js'), encoding='utf-8').read()
    data = json.dumps(build(), separators=(',', ':')).replace('</', '<\\/')
    html = tpl.replace('/*__DATA__*/', 'const DATA = ' + data + ';', 1).replace('/*__ENGINE__*/', eng.replace('</script', '<\\/script'), 1)
    if artifact:   # hosted page: the host supplies doctype/html/head/body; downloads become copy boxes
        head = html[html.index('<head>') + 6:html.index('</head>')]
        head = '\n'.join(l for l in head.split('\n') if 'charset' not in l and 'name="viewport"' not in l)
        body = html[html.index('<body>') + 6:html.rindex('</body>')]
        html = head.strip() + '\n' + body.replace('/*__ARTIFACT__*/false', 'true', 1)
    return html

if __name__ == '__main__':
    art = '--artifact' in sys.argv
    args = [a for a in sys.argv[1:] if a != '--artifact']
    out = args[0] if args else os.path.join(ROOT, 'Balatro Seed Tool.html')
    open(out, 'w', encoding='utf-8').write(page(art))
    print('wrote', out, os.path.getsize(out), 'bytes')
