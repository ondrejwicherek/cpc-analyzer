"""
convert_pricelists.py
Converts XLSX price list files from CZ and SK Heureka folders to JSON.
Mirrors the parse logic from app.py's parse_pricelist route and the
parseLabelFromName regex from index.html.
"""

import os
import re
import json
import io
import sys
import pandas as pd

# Force UTF-8 output on Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding and sys.stderr.encoding.lower() != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

# ── CONFIG ──────────────────────────────────────────────────────────────
MARKETS = {
    'cz': r'C:/Users/Ondrej/Desktop/CZ_heureka_price_list',
    'sk': r'C:/Users/Ondrej/Desktop/SK_heureka_price_list',
}
OUT_DIR = r'C:/Users/Ondrej/CPC_analyzer/static/data'

# ── HELPERS ──────────────────────────────────────────────────────────────
def parse_label_from_name(filename):
    """
    Mirrors JS parseLabelFromName:
    match (d{1,2})[.\\s]+(d{1,2})[.\\s]+(d{4}) -> YYYY-MM-DD
    """
    m = re.search(r'(\d{1,2})[.\s]+(\d{1,2})[.\s]+(\d{4})', filename)
    if m:
        day, month, year = m.group(1), m.group(2), m.group(3)
        return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
    # Fallback: strip extension
    return re.sub(r'\.xlsx?$', '', filename, flags=re.IGNORECASE)


def clean_value(val_str):
    """
    Mirrors app.py value cleaning:
    strip €, Kc, &nbsp; (\xa0 / \u00a0), spaces, replace comma with dot.
    Handles both CZ (Kc) and SK (EUR) price list formats.
    """
    return (val_str
            .replace('€', '')
            .replace('K\u010d', '')  # Kč (Czech koruna)
            .replace('\xa0', '')
            .replace('\u00a0', '')
            .replace('\u202f', '')   # narrow no-break space
            .replace(' ', '')
            .replace(',', '.')
            .strip())


def parse_xlsx(filepath):
    """
    Mirrors app.py parse_pricelist logic:
    - header row 0
    - col 0 = category ID (convert to int string)
    - col 1 = category name
    - cols 2+ = CPC brackets
    - skip rows with empty/invalid ID
    """
    with open(filepath, 'rb') as f:
        content = f.read()

    df = pd.read_excel(io.BytesIO(content), header=0, dtype=str)

    brackets = [str(c) for c in df.columns[2:]]
    categories = []

    for _, row in df.iterrows():
        raw_id = row.iloc[0]
        if pd.isna(raw_id) or not str(raw_id).strip():
            continue
        try:
            sec_id = str(int(float(str(raw_id).strip())))
        except Exception:
            continue

        name = str(row.iloc[1]) if pd.notna(row.iloc[1]) else ''
        cpcs = {}
        for bracket in brackets:
            val = row.get(bracket)
            if pd.notna(val) and str(val).strip():
                v = clean_value(str(val))
                try:
                    cpcs[bracket] = float(v)
                except Exception:
                    cpcs[bracket] = 0.0
            else:
                cpcs[bracket] = 0.0

        categories.append({'id': sec_id, 'name': name, 'cpcs': cpcs})

    return brackets, categories


# ── MAIN ─────────────────────────────────────────────────────────────────
def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"Output directory: {OUT_DIR}")

    for market, src_dir in MARKETS.items():
        print(f"\n{'='*50}")
        print(f"Processing market: {market.upper()}")
        print(f"Source dir: {src_dir}")

        if not os.path.isdir(src_dir):
            print(f"  ERROR: Directory not found: {src_dir}")
            continue

        xlsx_files = sorted(
            f for f in os.listdir(src_dir)
            if f.lower().endswith('.xlsx') or f.lower().endswith('.xls')
        )
        print(f"  Found {len(xlsx_files)} XLSX files")

        pricelists = []
        errors = []
        seen_labels = {}

        for fname in xlsx_files:
            fpath = os.path.join(src_dir, fname)
            label = parse_label_from_name(fname)

            # Deduplicate labels (same logic as JS: append (2), (3), ...)
            base_label = label
            if label in seen_labels:
                seen_labels[label] += 1
                label = f"{base_label} ({seen_labels[base_label]})"
            else:
                seen_labels[label] = 1

            try:
                brackets, categories = parse_xlsx(fpath)
                pricelists.append({
                    'label': label,
                    'brackets': brackets,
                    'categories': categories,
                })
                print(f"  OK  {fname} -> {label} ({len(categories)} categories, {len(brackets)} brackets)")
            except Exception as e:
                errors.append(f"{fname}: {e}")
                print(f"  ERR {fname}: {e}")

        # Sort by label ascending
        pricelists.sort(key=lambda x: x['label'])

        out_path = os.path.join(OUT_DIR, f'{market}_pricelists.json')
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(pricelists, f, ensure_ascii=False, indent=2)

        print(f"\n  Summary: {len(pricelists)} files processed, {len(errors)} errors")
        if errors:
            print("  Errors:")
            for e in errors:
                print(f"    - {e}")
        print(f"  Written: {out_path}")

    print("\nDone.")


if __name__ == '__main__':
    main()
