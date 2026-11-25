#!/usr/bin/env python3
"""Generate the two standalone Earth Engine programs and synthetic fixture."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def read(name):
    return (ROOT / 'src' / name).read_text(encoding='utf-8').rstrip() + '\n'

def main():
    (ROOT / 'scripts').mkdir(exist_ok=True)
    (ROOT / 'tests').mkdir(exist_ok=True)
    common = read('scientific_logic.js') + '\n' + read('ee_core.js') + '\n'
    products = [
        ('scripts/01_ghana_viewer_c3.js', 'viewer_intro.js', ['viewer_app.js', 'viewer_lst.js', 'viewer_footer.js']),
        ('scripts/02_monthly_csv_exporter_c3.js', 'exporter_intro.js', ['exporter.js']),
        ('tests/gee_synthetic_c3.js', None, ['gee_synthetic.js']),
    ]
    for target, introduction, parts in products:
        start = read(introduction) if introduction else '/* Synthetic Earth Engine validation fixture. */\n'
        text = start + '\n' + common + '\n'.join(read(part) for part in parts)
        (ROOT / target).write_text(text, encoding='utf-8', newline='\n')
        print(target)

if __name__ == '__main__':
    main()
