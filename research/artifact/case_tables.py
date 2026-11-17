
import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DATASETS = {
    'crash': 'Chicago crashes', 'diabetes': 'Hospital encounters',
    'maude': 'FDA MAUDE', 'nhanes': 'NHANES', 'scania': 'Scania APS',
    'storm': 'NOAA storms', 'survey': 'Developer survey', 'taxi': 'NYC yellow taxi',
}

DIRECTIONS = [
    ('maude', 'DATE_FACILITY_AWARE', 'DATE_REPORT_TO_MANUFACTURER', 'MAUDE', 'facility date', 'report to mfr.'),
    ('storm', 'DAMAGE_PROPERTY', 'DAMAGE_CROPS', 'Storms', 'property loss', 'crop loss'),
    ('nhanes', 'MCQ010', 'MCQ025', 'NHANES', 'asthma item', 'age first told'),
    ('survey', 'Currency', 'CompTotal', 'Survey', 'currency', 'pay amount'),
]


def load_source(data, dataset):
    manifest = json.loads((data / (dataset + '.json')).read_text())
    with np.load(data / (dataset + '.npz'), allow_pickle=False) as f:
        rows = f['masks']
        names = f['names'].tolist()
    sha = hashlib.sha256(rows.astype('<u8', copy=False).tobytes()).hexdigest()
    if sha != manifest['masks_sha256_le'] or names != manifest['names']:
        raise ValueError(f'Invalid source fingerprint for {dataset}')
    shapes, counts = np.unique(rows, return_counts=True)
    varying = int(np.bitwise_or.reduce(shapes) ^ np.bitwise_and.reduce(shapes)).bit_count()
    dimensions = len(rows), len(names), len(shapes), varying
    expected = tuple(manifest[k] for k in ('rows', 'columns', 'distinct_signatures', 'varying_columns'))
    if dimensions != expected:
        raise ValueError(f'Dataset dimensions do not agree for {dataset}')
    return manifest, shapes, counts, {n: 1 << i for i, n in enumerate(names)}


def qualifying(present, missing, shape_data):
    shapes, frequencies, fields = shape_data
    p = sum(fields[f] for f in present.split())
    m = sum(fields[f] for f in missing.split())
    return int(frequencies[((shapes & p) == 0) & ((shapes & m) == m)].sum())


def generate(data, runs, dest):
    grouped = {}
    rows = []
    for dataset, label in DATASETS.items():
        meta, shapes, counts, fields = load_source(data, dataset)
        grouped[dataset] = shapes, counts, fields
        rows.append(f'{label} & {meta["rows"]:,} & {meta["columns"]}'
                    f' & {meta["varying_columns"]} & {meta["distinct_signatures"]:,} \\\\')
    (dest / 'setup_input_rows.tex').write_text('\n'.join(rows + [r'\bottomrule']) + '\n', encoding='utf8')

    with (runs / 'case_manifest.tsv').open(encoding='utf8', newline='') as f:
        manifest = list(csv.DictReader(f, delimiter='\t'))
    cases = {}
    for row in manifest:
        k = row['dataset'], row['present'], row['missing']
        if k in cases or k[0] not in grouped:
            raise ValueError(f'Unexpected duplicate or dataset {k}')
        count = qualifying(k[1], k[2], grouped[k[0]])
        if count != int(row['whole_table_count']):
            raise ValueError(f'Named count mismatch for {k}')
        cases[k] = count
    for dataset, *_ in DIRECTIONS:
        ids = sorted(int(r['rule']) for r in manifest if r['dataset'] == dataset)
        if ids != list(range(8)):
            raise ValueError(f'Incomplete named bundle for {dataset}')
    if len(cases) != 32:
        raise ValueError('Incomplete named trace')

    table = []
    for dataset, left, right, label, a, b in DIRECTIONS:
        absent = cases[dataset, left, right]
        present = cases[dataset, left + ' ' + right, '']
        table.append(f'{label} & {a} & {b} & {absent:,} & {present:,} \\\\')
    (dest / 'case_count_rows.tex').write_text('\n'.join(table + [r'\bottomrule']) + '\n', encoding='utf8')
    select = {
        'StormMagnitude': ('storm', 'MAGNITUDE', 'MAGNITUDE_TYPE'),
        'StormBoth': ('storm', 'DAMAGE_PROPERTY DAMAGE_CROPS', ''),
        'MdrThree': ('maude', 'DATE_RECEIVED DATE_REPORT DATE_OF_EVENT', ''),
        'MdrFlagOnly': ('maude', 'REPORT_TO_FDA', 'DATE_REPORT_TO_FDA'),
        'MdrDateOnly': ('maude', 'DATE_REPORT_TO_FDA', 'REPORT_TO_FDA'),
        'SurveyBoth': ('survey', 'Currency CompTotal', ''),
        'SurveyLanguage': ('survey', 'LanguageHaveWorkedWith', 'LanguageWantToWorkWith'),
        'SurveyDatabase': ('survey', 'DatabaseHaveWorkedWith', 'DatabaseWantToWorkWith'),
        'NhaChf': ('nhanes', 'MCQ160B', 'MCD180B'),
    }
    macros = [fr'\newcommand{{\count{key}}}{{{cases[t]:,}}}' for key, t in select.items()]
    (dest / 'case_numbers.tex').write_text('\n'.join(macros) + '\n', encoding='utf8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=ROOT.parent / 'data')
    parser.add_argument('--runs', type=Path, default=ROOT.parent / 'runs')
    parser.add_argument('--dest', type=Path, default=ROOT)
    args = parser.parse_args()
    generate(args.data, args.runs, args.dest)
