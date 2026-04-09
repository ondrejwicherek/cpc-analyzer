from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import requests
import pandas as pd
import io
import xml.etree.ElementTree as ET
from datetime import date, timedelta

app = Flask(__name__)
CORS(app)

# Simple in-memory cache for category XML (key: 'cz'/'sk')
_cat_cache = {}


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/heureka-categories')
def heureka_categories():
    market = request.args.get('market', 'cz').lower()
    if market not in ('cz', 'sk'):
        market = 'cz'

    if market in _cat_cache:
        return jsonify(_cat_cache[market])

    url = f'https://www.heureka.{"sk" if market == "sk" else "cz"}/direct/xml-export/shops/heureka-sekce.xml'
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        return jsonify({'error': f'Nelze stáhnout kategorie: {e}'}), 500

    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as e:
        return jsonify({'error': f'Chyba parsování XML: {e}'}), 500

    categories = {}   # id → display name
    parents    = {}   # child_id → parent_id

    def parse_node(element, parent_id=None):
        for cat in element.findall('CATEGORY'):
            id_el = cat.find('CATEGORY_ID')
            if id_el is None or not (id_el.text or '').strip():
                continue
            cat_id = id_el.text.strip()

            fullname_el = cat.find('CATEGORY_FULLNAME')
            name_el     = cat.find('CATEGORY_NAME')

            if fullname_el is not None and (fullname_el.text or '').strip():
                parts = [p.strip() for p in fullname_el.text.split('|')]
                if parts and parts[0].lower().startswith('heureka'):
                    parts = parts[1:]
                categories[cat_id] = ' | '.join(parts)
            elif name_el is not None and (name_el.text or '').strip():
                categories[cat_id] = name_el.text.strip()
            else:
                categories[cat_id] = cat_id

            if parent_id is not None:
                parents[cat_id] = parent_id

            parse_node(cat, cat_id)   # recurse

    parse_node(root)

    result = {'categories': categories, 'parents': parents}
    _cat_cache[market] = result
    return jsonify(result)


@app.route('/api/fetch-heureka', methods=['POST'])
def fetch_heureka():
    data = request.json
    api_key    = data.get('api_key', '').strip()
    start_date = data.get('start_date')
    end_date   = data.get('end_date')

    if not api_key:
        return jsonify({'error': 'Chybí API klíč'}), 400

    try:
        start = date.fromisoformat(start_date)
        end   = date.fromisoformat(end_date)
    except Exception:
        return jsonify({'error': 'Neplatné datum'}), 400

    if (end - start).days > 365:
        return jsonify({'error': 'Rozsah nesmí přesáhnout 365 dní'}), 400

    aggregated = {}
    errors = []
    days_fetched = 0
    current = start

    while current <= end:
        try:
            resp = requests.get(
                'https://api.heureka.group/v1/reports/conversions',
                params={'date': current.isoformat()},
                headers={'x-heureka-api-key': api_key},
                timeout=15
            )
            if resp.status_code == 200:
                for conv in resp.json().get('conversions', []):
                    cat_id = str(conv['portal_category']['id'])
                    if cat_id not in aggregated:
                        aggregated[cat_id] = {
                            'cost': 0.0, 'revenue': 0.0,
                            'visits': 0, 'bidded_visits': 0, 'orders': 0,
                        }
                    a = aggregated[cat_id]
                    a['cost']          += conv['costs_with_vat']['total']
                    a['revenue']       += conv['revenue']['total']
                    a['visits']        += conv['visits']['total']
                    a['bidded_visits'] += conv['visits'].get('bidded', 0)
                    a['orders']        += conv['orders']['total']
                days_fetched += 1
            elif resp.status_code in (401, 403):
                return jsonify({'error': f'Autentizace selhala (HTTP {resp.status_code})'}), resp.status_code
            else:
                errors.append(f"{current}: HTTP {resp.status_code}")
        except requests.Timeout:
            errors.append(f"{current}: Timeout")
        except Exception as e:
            errors.append(f"{current}: {str(e)}")
        current += timedelta(days=1)

    result = []
    for cat_id, a in aggregated.items():
        result.append({
            'category_id': cat_id,
            'cost':          round(a['cost'], 4),
            'revenue':       round(a['revenue'], 4),
            'visits':        a['visits'],
            'bidded_visits': a['bidded_visits'],
            'orders':        a['orders'],
            'roas': round(a['revenue'] / a['cost'], 2) if a['cost'] > 0 else None,
        })
    result.sort(key=lambda x: x['cost'], reverse=True)

    return jsonify({'data': result, 'days_fetched': days_fetched, 'errors': errors[:10]})


@app.route('/api/parse-pricelist', methods=['POST'])
def parse_pricelist():
    if 'file' not in request.files:
        return jsonify({'error': 'Chybí soubor'}), 400

    file  = request.files['file']
    label = request.form.get('label', '').strip() or file.filename

    try:
        content = file.read()
        df = pd.read_excel(io.BytesIO(content), header=0, dtype=str)

        brackets   = [str(c) for c in df.columns[2:]]
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
                    v = (str(val).replace('€', '').replace('\xa0', '')
                                 .replace('\u00a0', '').replace(' ', '')
                                 .replace(',', '.').strip())
                    try:
                        cpcs[bracket] = float(v)
                    except Exception:
                        cpcs[bracket] = 0.0
                else:
                    cpcs[bracket] = 0.0

            categories.append({'id': sec_id, 'name': name, 'cpcs': cpcs})

        return jsonify({'label': label, 'categories': categories, 'brackets': brackets})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True, port=5000)
