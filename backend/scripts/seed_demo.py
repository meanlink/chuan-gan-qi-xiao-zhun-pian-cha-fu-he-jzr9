import time, json
from sqlalchemy import select, func
from src.config.database import Session
from migrations.initial import migrate
from src.models import User, Dataset, Job, Report, Delivery, Audit, Station, StationSnapshot, LedgerRow
from src.services.business import metadata, seed_records, analyze
from src.services.reports import deliver
from src.services.stations import compute_diff, snapshot_rows
from src.utils.security import hash_password
from src.utils.serialization import checksum

STATION_CODE = 'WH-A1'
STATION_NAME = '望衡仪器 · 1 号校准站'


def _ensure_station(db, rows, source):
    """建立代号 1 的全量台账；旧库已有的同名批次就地升级为代号 1。"""
    station = db.scalar(select(Station).where(Station.code == STATION_CODE))
    if station is not None:
        return station
    fingerprint = checksum(rows)
    station = Station(code=STATION_CODE, name=STATION_NAME, current_generation=1,
                      current_snapshot_id=None, created_at=time.time())
    db.add(station); db.flush()
    snapshot = StationSnapshot(station_id=station.id, generation=1, status='published',
                               checksum=fingerprint, source=source, row_count=len(rows),
                               progress=len(rows), diff=compute_diff([], rows), dataset_id=None,
                               created_by='seed', created_at=time.time(), published_at=time.time())
    db.add(snapshot); db.flush()
    for position, row in enumerate(rows, start=1):
        db.add(LedgerRow(snapshot_id=snapshot.id, position=position, sample=row['sample'], band=row['band'],
                         reference=row['reference'], measured=row['measured']))
    baseline = db.scalar(select(Dataset).where(Dataset.name == metadata()['dataset_name']))
    if baseline is None:
        baseline = Dataset(name=metadata()['dataset_name'], source=source, records=rows,
                           checksum=fingerprint, created_at=time.time(), station_id=station.id,
                           generation=1, snapshot_id=snapshot.id)
        db.add(baseline); db.flush()
    else:
        # 内容不变，仅规范为按读数编号排序，使批次指纹与快照指纹一致。
        baseline.records = rows
        baseline.checksum = fingerprint
        baseline.station_id = station.id
        baseline.generation = 1
        baseline.snapshot_id = snapshot.id
    snapshot.dataset_id = baseline.id
    station.current_snapshot_id = snapshot.id
    db.flush()
    return station


def seed():
    migrate()
    with Session() as db:
        for role, name in [('admin', '林知 · 业务负责人'), ('analyst', '陈舟 · 分析员'), ('viewer', '周禾 · 观察员')]:
            email = role + '@demo.local'
            if not db.scalar(select(User).where(User.email == email)):
                db.add(User(email=email, name=name, role=role, password=hash_password('Demo123!')))
        db.flush()
        m = metadata()
        source = m['short'] + '-202611.csv'
        station = db.scalar(select(Station).where(Station.code == STATION_CODE))
        if station is None:
            existing = db.scalar(select(Dataset).where(Dataset.name == m['dataset_name']))
            rows = sorted(existing.records, key=lambda r: r['sample']) if existing else \
                sorted(seed_records(), key=lambda r: r['sample'])
            station = _ensure_station(db, rows, existing.source if existing else source)
        else:
            rows = snapshot_rows(db, station.current_snapshot_id)
        d = db.scalar(select(Dataset).where(Dataset.name == m['dataset_name']))
        if d is None:
            # 站点已存在但基线批次缺失：按当前代号重建绑定。
            d = Dataset(name=m['dataset_name'], source=source, records=rows,
                        checksum=checksum(rows), created_at=time.time(), station_id=station.id,
                        generation=station.current_generation, snapshot_id=station.current_snapshot_id)
            db.add(d); db.flush()
        if not db.scalar(select(Job).where(Job.name == '基线复核 · ' + m['name'])):
            params = {p['key']: p['default'] for p in m.get('parameters', [])}
            result = analyze(d.records, params)
            result['binding'] = {'station': station.code, 'generation': d.generation,
                                 'checksum': d.checksum, 'rows': len(d.records)}
            json.dumps(result, ensure_ascii=False, allow_nan=False)
            admin = db.scalar(select(User).where(User.role == 'admin'))
            j = Job(name='基线复核 · ' + m['name'], dataset_id=d.id, params=params, status='completed', result=result,
                    created_by=admin.id, created_at=time.time() - 3600, finished_at=time.time() - 3595,
                    approved=True, station_code=station.code, dataset_generation=d.generation,
                    dataset_checksum=d.checksum)
            db.add(j); db.flush()
            r = Report(name='每日业务复核简报', job_id=j.id, destination='业务复核组 · 本地收件箱',
                       interval_seconds=86400, next_run=time.time() + 86400, enabled=True)
            db.add(r); db.flush(); deliver(db, r)
            db.add(Audit(actor='seed', action='demo.baseline', detail={'dataset': d.id, 'generation': d.generation},
                         at=time.time()))
        db.commit()
        counts = {model.__tablename__: db.scalar(select(func.count()).select_from(model))
                  for model in [User, Dataset, Job, Report, Delivery, Audit, Station, StationSnapshot, LedgerRow]}
        print(json.dumps(counts, ensure_ascii=False))
        return counts


if __name__ == '__main__':
    seed()
