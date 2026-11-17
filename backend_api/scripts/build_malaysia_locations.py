"""Build the reviewed Malaysia gazetteer from explicit local GeoNames inputs. No network/DB."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.malaysia_boundary import coordinate_state


def build(archive, admin_file):
    reviews = json.loads((Path(__file__).resolve().parents[1] / 'services/data/malaysia_location_reviews.json').read_text(encoding='utf-8'))
    states = {line.split('\t')[0].split('.')[1]: line.split('\t')[1]
              for line in admin_file.read_text(encoding='utf-8').splitlines() if line.startswith('MY.')}
    with zipfile.ZipFile(archive) as zipped:
        source = [line.split('\t') for line in zipped.read('MY.txt').decode('utf-8').splitlines()]
    districts = {(row[10], row[11]): row[1] for row in source if row[7] == 'ADM2'}
    places, rejected = [], Counter()
    for row in source:
        if not (row[6] == 'P' and row[7] not in {'PPLH', 'PPLQ', 'PPLW', 'PPLCH'}
                or row[7] in {'ADM2', 'ADM3', 'ISL', 'ISLS'}):
            continue
        state = states.get(row[10])
        review = reviews.get(row[0])
        if review:
            if row[1] != review['expectedName'] or row[10] != review['expectedAdmin1']:
                raise ValueError('Reviewed source record changed; recheck ' + row[0])
            state = review['state']
        if row[8] != 'MY' or not state:
            rejected['unknown_country_or_state'] += 1
            continue
        latitude, longitude = float(row[4]), float(row[5])
        if coordinate_state(latitude, longitude) != state:
            rejected['coordinate_state_conflict_or_outside_geometry'] += 1
            continue
        aliases = sorted({name for name in [row[1], row[2], *row[3].split(',')]
                          if 2 <= len(name) <= 100 and re.fullmatch(r"[A-Za-zÀ-ž0-9 .()/'’–-]+", name)})
        if review:
            aliases = review['aliases']
        population = int(row[14] or 0)
        fast = population >= 1000 or row[7].startswith('PPLA') or row[7] in {'PPLC', 'ADM2'} or (
            row[6] == 'P' and not re.match(r'^(kamp[uoa]ng|kampong|taman|rumah|ladang|felda|kg[ .])', row[1], re.I))
        places.append({'id': row[0], 'name': row[1], 'state': state,
                       'district': None if review else districts.get((row[10], row[11])),
                       'kind': 'district' if row[7] == 'ADM2' else 'subdistrict' if row[7] == 'ADM3'
                               else 'island' if row[7] in {'ISL', 'ISLS'} else 'locality',
                       'latitude': latitude, 'longitude': longitude, 'aliases': aliases,
                       'feature': row[7], 'population': population, 'fast': fast,
                       'modified': row[18]})
        if review:
            places[-1]['reviewSources'] = review['sources']
    places.sort(key=lambda row: int(row['id']))
    return {'source': 'https://download.geonames.org/export/dump/MY.zip',
            'adminSource': 'https://download.geonames.org/export/dump/admin1CodesASCII.txt',
            'license': 'https://creativecommons.org/licenses/by/4.0/',
            'attribution': 'GeoNames, CC BY 4.0. Filtered against pinned DOSM state geometry; explicit reviewed corrections are separately documented.',
            'archiveSha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
            'adminSha256': hashlib.sha256(admin_file.read_bytes()).hexdigest(),
            'counts': {'featuresInArchive': len(source), 'included': len(places),
                       'fast': sum(row['fast'] for row in places), 'rejected': dict(rejected),
                       'byState': dict(sorted(Counter(row['state'] for row in places).items()))},
            'places': places}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--geonames', type=Path, required=True)
    parser.add_argument('--admin1', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = build(args.geonames, args.admin1)
    # One record per line keeps a generated dataset reviewable without whitespace bloat.
    text = json.dumps({k: v for k, v in result.items() if k != 'places'}, ensure_ascii=False, indent=2)
    text = text[:-2] + ',\n  "places": [\n' + ',\n'.join(
        '    ' + json.dumps(row, ensure_ascii=False, separators=(',', ':')) for row in result['places']) + '\n  ]\n}\n'
    args.output.write_text(text, encoding='utf-8')
    print(json.dumps(result['counts'], sort_keys=True))
