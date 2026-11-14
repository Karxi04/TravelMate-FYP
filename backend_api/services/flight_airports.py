import json
from pathlib import Path

CITY_TO_IATA = {
    'KUALA LUMPUR': 'KUL',
    'KL': 'KUL',
    'KLIA': 'KUL',
    'PENANG': 'PEN',
    'GEORGETOWN': 'PEN',
    'GEORGE TOWN': 'PEN',
    'SINGAPORE': 'SIN',
    'CHANGI': 'SIN',
    'BANGKOK': 'BKK',
    'SUVARNABHUMI': 'BKK',
    'TOKYO': 'NRT',
    'NARITA': 'NRT',
    'HANEDA': 'HND',
    'SEOUL': 'ICN',
    'INCHEON': 'ICN',
    'HONG KONG': 'HKG',
    'HK': 'HKG',
    'LANGKAWI': 'LGK',
    'KOTA KINABALU': 'BKI',
    'KUCHING': 'KCH',
    'JOHOR BAHRU': 'JHB',
    'JB': 'JHB',
    'IPOH': 'IPH',
    'MELAKA': 'MKZ',
    'MALACCA': 'MKZ',
    'ALOR SATAR': 'AOR',
    'KOTA BAHARU': 'KBR',
    'SULTAN HAJI AHMAD SHAH': 'KUA',
    'PULAU PINANG': 'PEN',
    'LONG DATIH': 'LGL',
    'TANJONG MANIS': 'TGC',
    'LONDON': 'LHR',
    'HEATHROW': 'LHR',
    'SYDNEY': 'SYD',
    'MELBOURNE': 'MEL',
    'BALI': 'DPS',
    'DENPASAR': 'DPS',
    'JAKARTA': 'CGK',
    'TAIPEI': 'TPE',
    'OSAKA': 'KIX',
    'DUBAI': 'DXB',
}

AIRPORT_CATALOG = json.loads((Path(__file__).parent / 'data' / 'flight_airports.json').read_text(encoding='utf-8'))
SUPPORTED_AIRPORTS = frozenset(AIRPORT_CATALOG)
MALAYSIAN_AIRPORT_CATALOG = json.loads((Path(__file__).parent / 'data' / 'malaysian_airports.json').read_text(encoding='utf-8'))
MALAYSIAN_AIRPORTS = frozenset(MALAYSIAN_AIRPORT_CATALOG)
assert set(CITY_TO_IATA.values()) <= SUPPORTED_AIRPORTS | MALAYSIAN_AIRPORTS

def resolve_airport(value):
    code = str(value or '').strip().upper()
    if code in CITY_TO_IATA or code in MALAYSIAN_AIRPORTS:
        return CITY_TO_IATA.get(code, code)
    matches = [iata for iata, airport in MALAYSIAN_AIRPORT_CATALOG.items()
               if code in {airport['name'].upper(), airport['city'].upper()}]
    return matches[0] if len(matches) == 1 else code
