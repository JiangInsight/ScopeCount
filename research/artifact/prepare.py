




import argparse
import csv
import hashlib
import io
import json
import os
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import urlencode

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

NOAA = 'https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/'
NOAA_VERSIONS = [(2020, '20260323'), (2021, '20260323'), (2022, '20260625'),
                 (2023, '20260323'), (2024, '20260728')]
UCI = 'https://archive.ics.uci.edu/static/public/'
TLC = 'https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_2023-01.parquet'
MCQ = 'https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2017/DataFiles/MCQ_J.xpt'
SURVEY = ('https://media.githubusercontent.com/media/StackExchange/Survey/'
          '9dd5c163b7ec09ce5503f711c37a99dbd80ff3c7/packages/archive/2024/results.csv')
SCHEMAS = {'storm', 'taxi', 'diabetes', 'nhanes', 'scania', 'crash', 'survey', 'maude'}


def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def fetch(url, target):
    if target.is_file():
        return target
    print('Download', target.name, flush=True)
    session = requests.Session()
    retry = Retry(total=4, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    session.mount('https://', HTTPAdapter(max_retries=retry))
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as tmp:
        path = Path(tmp.name)
    try:
        with session.get(url, stream=True, timeout=(15, 120)) as resp:
            resp.raise_for_status()
            with path.open('wb') as out:
                for block in resp.iter_content(1 << 19):
                    out.write(block)
        path.replace(target)
    finally:
        path.unlink(missing_ok=True)
        session.close()
    return target


def csv_frames(f, token, **kwargs):
    return pd.read_csv(f, dtype=str, keep_default_na=False, na_values=[token],
                       chunksize=8192, **kwargs)


def collect_inputs(dataset, cache, taxi_file):
    if dataset == 'storm':
        paths = [(NOAA + (name := f'StormEvents_details-ftp_v1.0_d{year}_c{version}.csv.gz'),
                  cache / name) for year, version in NOAA_VERSIONS]
    elif dataset == 'taxi':
        paths = [(TLC, taxi_file or cache / TLC.rsplit('/', 1)[1])]
    elif dataset == 'diabetes':
        paths = [(UCI + '296/diabetes+130-us+hospitals+for+years+1999-2008.zip', cache / 'diabetes.zip')]
    elif dataset == 'scania':
        paths = [(UCI + '421/aps+failure+at+scania+trucks.zip', cache / 'scania.zip')]
    elif dataset == 'nhanes':
        paths = [(MCQ, cache / 'MCQ_J.xpt')]
    elif dataset == 'survey':
        paths = [(SURVEY, cache / 'survey2024.csv')]
    elif dataset == 'maude':
        paths = [('https://www.accessdata.fda.gov/MAUDE/ftparea/mdrfoi.zip', cache / 'mdrfoi.zip')]
    elif dataset == 'crash':
        base = 'https://data.cityofchicago.org/resource/85ca-t3if.csv?'
        paths = []
        for month in range(1, 13):
            start = f'2024-{month:02d}-01T00:00:00'
            end = f'2024-{month+1:02d}-01T00:00:00' if month < 12 else '2025-01-01T00:00:00'
            query = urlencode({'$where': f"crash_date >= '{start}' AND crash_date < '{end}'",
                               '$order': 'crash_date,crash_record_id', '$limit': '50000'})
            paths.append((base + query, cache / f'crash-2024-{month:02d}.csv'))
    else:
        raise ValueError(dataset)
    for url, path in paths:
        fetch(url, path)
    return paths


def frames(dataset, paths):
    for _, path in paths:
        if dataset == 'maude':


            with zipfile.ZipFile(path) as archive, archive.open('mdrfoi.txt') as stream:
                names = stream.readline().decode('ascii').rstrip('\r\n').split('|')
                delims = len(names) - 1
                chunk, pending = [], b''
                for line in stream:
                    raw = pending + line.rstrip(b'\r\n')
                    n = raw.count(b'|')
                    if n < delims:
                        pending = raw + b' '
                        continue
                    if n != delims:
                        raise ValueError('FDA export has an ambiguous number of fields')
                    pending = b''
                    chunk.append(raw)
                    if len(chunk) == 8192:
                        yield nulls_from_records(chunk, names)
                        chunk.clear()
                if pending:
                    raise ValueError('Incomplete FDA record at EOF')
                if chunk:
                    yield nulls_from_records(chunk, names)
            continue
        if dataset == 'taxi':

            for batch in pq.ParquetFile(path).iter_batches(batch_size=65536):
                yield batch.schema.names, [c.is_null().to_numpy(zero_copy_only=False) for c in batch.columns]
            continue
        if dataset == 'nhanes':
            frames_iterator = [pd.read_sas(path, format='xport')]
        elif dataset == 'storm':
            frames_iterator = csv_frames(path, '', encoding='latin-1', compression='gzip')
        elif dataset == 'crash':
            frames_iterator = csv_frames(path, '')
        elif dataset == 'survey':
            frames_iterator = csv_frames(path, 'NA')
        elif dataset == 'diabetes':
            with zipfile.ZipFile(path) as archive:
                with archive.open('diabetic_data.csv') as stream:
                    for df in csv_frames(stream, '?'):
                        yield df.columns.tolist(), [df[c].isna().to_numpy() for c in df]
            continue
        elif dataset == 'scania':
            with zipfile.ZipFile(path) as archive:
                for member in ['aps_failure_training_set.csv', 'aps_failure_test_set.csv']:
                    with archive.open(member) as stream:
                        for line in stream:
                            if line.startswith(b'class,'):
                                names = line.decode('ascii').strip().split(',')
                                break
                        else:
                            raise ValueError(f'Missing CSV header in {member}')
                        for df in csv_frames(stream, 'na', names=names):
                            yield names, [df[c].isna().to_numpy() for c in names[:63]]
            continue
        nrows = 0
        for df in frames_iterator:
            nrows += len(df)
            yield df.columns.tolist(), [df[c].isna().to_numpy() for c in df.columns[:63]]
        if dataset == 'crash' and nrows >= 50000:
            raise ValueError('The monthly query reached its pagination cap.')


def nulls_from_records(records, names):
    with io.BytesIO(b'\n'.join(records)) as f:
        df = pd.read_csv(f, dtype=str, na_values=[''], keep_default_na=False,
                         header=None, names=names, usecols=range(min(63, len(names))),
                         encoding='latin-1', sep='|', quoting=csv.QUOTE_NONE)
    return names, [df[c].isna().to_numpy() for c in df]


def prepare(dataset, cache, data, taxi_file):
    paths = collect_inputs(dataset, cache, taxi_file)
    words, schema = [], None
    for columns, bits in frames(dataset, paths):
        if schema is None:
            schema = columns
        if columns != schema:
            raise ValueError(f'{dataset}: schema mismatch')
        word = np.zeros(len(bits[0]), dtype=np.uint64)
        for i, flags in enumerate(bits[:63]):
            word |= np.asarray(flags, dtype=np.uint64) << i
        words.append(word)
    masks = np.concatenate(words)
    if not len(masks):
        raise ValueError(f'{dataset}: empty output')
    names = np.array(schema[:63])
    target = data / (dataset + '.npz')
    with tempfile.NamedTemporaryFile(dir=data, suffix='.npz', delete=False) as tmp:
        path = Path(tmp.name)
    try:
        np.savez_compressed(path, names=names, masks=masks)
        path.replace(target)
    finally:
        path.unlink(missing_ok=True)
    counts = np.unique(masks, return_counts=True)[1]
    manifest = {'rows':len(masks), 'columns':len(names), 'source_columns':len(schema),
                'varying_columns':int(int(np.bitwise_or.reduce(masks) ^ np.bitwise_and.reduce(masks)).bit_count()),
                'distinct_signatures':len(counts), 'largest_signature_rows':int(counts.max()),
                'masks_sha256_le':hashlib.sha256(masks.astype('<u8', copy=False).tobytes()).hexdigest(),
                'names':list(names), 'sources':[{'url':url,'bytes':p.stat().st_size,'sha256':digest(p)}
                                                for url,p in paths]}
    (data / (dataset + '.json')).write_text(json.dumps(manifest,indent=2)+'\n', encoding='utf-8')
    print(dataset, {k:v for k,v in manifest.items() if k not in ['names','sources']}, flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cache', type=Path, default=Path(os.getenv('LOCALAPPDATA', Path.home()/'.cache'))/'scopecount-raw')
    p.add_argument('--data', type=Path, default=Path(__file__).resolve().parents[2]/'data')
    p.add_argument('--taxi-file', type=Path)
    p.add_argument('datasets', nargs='*')
    args = p.parse_args()
    args.data.mkdir(parents=True, exist_ok=True)
    args.cache.mkdir(parents=True, exist_ok=True)
    for key in args.datasets or sorted(SCHEMAS):
        if key not in SCHEMAS:
            p.error(f'Unknown dataset {key}')
        prepare(key, args.cache, args.data, args.taxi_file)
