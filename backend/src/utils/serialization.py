import hashlib, json


def checksum(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def dataset_dict(d):
    return {'id': d.id, 'name': d.name, 'source': d.source, 'rows': len(d.records), 'checksum': d.checksum,
            'created_at': d.created_at, 'station_id': d.station_id, 'generation': d.generation,
            'snapshot_id': d.snapshot_id}


def job_dict(j):
    data = {k: getattr(j, k) for k in ['id', 'name', 'dataset_id', 'params', 'status', 'result', 'error', 'approved',
                                       'created_at', 'finished_at']}
    data.update({'station_code': j.station_code, 'dataset_generation': j.dataset_generation,
                 'dataset_checksum': j.dataset_checksum})
    return data


def report_dict(r):
    return {k: getattr(r, k) for k in ['id', 'name', 'job_id', 'destination', 'interval_seconds', 'next_run',
                                       'enabled']}


def delivery_dict(d):
    return {k: getattr(d, k) for k in ['id', 'report_id', 'created_at', 'checksum', 'filename', 'destination']}
