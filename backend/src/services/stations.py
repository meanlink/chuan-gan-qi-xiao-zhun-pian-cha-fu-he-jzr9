import math
import time
from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from src.models import Station, StationSnapshot, LedgerRow, Dataset
from src.services.business import metadata
from src.utils.serialization import checksum

COLUMNS = metadata()['columns']
CHUNK_SIZE = 50
DIFF_SAMPLE_LIMIT = 300


def normalize_rows(rows):
    """校验并规范化整份台账；任何一行不合法都不会写入数据库。"""
    if not rows:
        raise HTTPException(422, '快照至少需要一条读数')
    if len(rows) > 5000:
        raise HTTPException(422, '单份台账最多 5000 条读数，请按站点拆分')
    normalized, seen = [], set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise HTTPException(422, f'第 {index + 1} 行必须是对象')
        record = {}
        for column in COLUMNS:
            key, label, kind = column['key'], column['label'], column['type']
            value = row.get(key)
            if value is None or (isinstance(value, str) and not value.strip()):
                raise HTTPException(422, f'第 {index + 1} 行缺少字段 {label}')
            if kind == 'number':
                try:
                    if isinstance(value, bool):
                        raise ValueError()
                    number = float(value)
                    if not math.isfinite(number):
                        raise ValueError()
                except (TypeError, ValueError, OverflowError):
                    raise HTTPException(422, f'第 {index + 1} 行 {label} 必须为有限数值')
                record[key] = number
            else:
                text = str(value).strip()
                if not text:
                    raise HTTPException(422, f'第 {index + 1} 行 {label} 不能为空')
                record[key] = text
        if record['sample'] in seen:
            raise HTTPException(422, f'读数编号 {record["sample"]} 重复，整份快照拒收')
        seen.add(record['sample'])
        normalized.append(record)
    # 台账按读数编号排序，同一份内容即使行序不同也得到相同指纹。
    normalized.sort(key=lambda item: item['sample'])
    return normalized


def _row_dict(row):
    return {'sample': row.sample, 'band': row.band, 'reference': row.reference, 'measured': row.measured}


def snapshot_rows(db, snapshot_id):
    if snapshot_id is None:
        return []
    rows = db.scalars(select(LedgerRow).where(LedgerRow.snapshot_id == snapshot_id).order_by(LedgerRow.position))
    return [_row_dict(row) for row in rows]


def _current_rows(db, station):
    return snapshot_rows(db, station.current_snapshot_id) if station else []


def compute_diff(base_rows, new_rows):
    """对比当前已发布台账与新快照：新增、修改、撤销。"""
    base = {row['sample']: row for row in base_rows}
    fresh = {row['sample']: row for row in new_rows}
    added, modified, revoked = [], [], []
    for row in new_rows:
        previous = base.get(row['sample'])
        if previous is None:
            added.append(row)
        elif any(previous[key] != row[key] for key in ('band', 'reference', 'measured')):
            modified.append({'sample': row['sample'], 'before': previous, 'after': row})
    for row in base_rows:
        if row['sample'] not in fresh:
            revoked.append(row)
    unchanged = len(new_rows) - len(added) - len(modified)
    return {
        'counts': {'added': len(added), 'modified': len(modified), 'revoked': len(revoked), 'unchanged': unchanged},
        'added': {'items': added[:DIFF_SAMPLE_LIMIT], 'truncated': len(added) > DIFF_SAMPLE_LIMIT},
        'modified': {'items': modified[:DIFF_SAMPLE_LIMIT], 'truncated': len(modified) > DIFF_SAMPLE_LIMIT},
        'revoked': {'items': revoked[:DIFF_SAMPLE_LIMIT], 'truncated': len(revoked) > DIFF_SAMPLE_LIMIT},
    }


def _empty_diff():
    return {'counts': {'added': 0, 'modified': 0, 'revoked': 0, 'unchanged': 0},
            'added': {'items': [], 'truncated': False},
            'modified': {'items': [], 'truncated': False},
            'revoked': {'items': [], 'truncated': False}}


def snapshot_dict(snapshot):
    if snapshot is None:
        return None
    return {'id': snapshot.id, 'station_id': snapshot.station_id, 'generation': snapshot.generation,
            'status': snapshot.status, 'checksum': snapshot.checksum, 'source': snapshot.source,
            'row_count': snapshot.row_count, 'progress': snapshot.progress, 'diff': snapshot.diff or _empty_diff(),
            'dataset_id': snapshot.dataset_id, 'created_by': snapshot.created_by,
            'created_at': snapshot.created_at, 'published_at': snapshot.published_at}


def station_dict(db, station, detail=False):
    current = db.get(StationSnapshot, station.current_snapshot_id) if station.current_snapshot_id else None
    result = {'code': station.code, 'name': station.name,
              'current_generation': station.current_generation or 0,
              'current_snapshot_id': station.current_snapshot_id,
              'rows': current.row_count if current else 0,
              'current_checksum': current.checksum if current else '',
              'published_at': current.published_at if current else None,
              'current_source': current.source if current else '',
              'pending': []}
    pending = db.scalars(select(StationSnapshot).where(StationSnapshot.station_id == station.id,
                                                       StationSnapshot.status == 'staging')
                         .order_by(StationSnapshot.generation))
    result['pending'] = [{'id': snap.id, 'generation': snap.generation, 'progress': snap.progress,
                          'row_count': snap.row_count, 'checksum': snap.checksum} for snap in pending]
    if detail:
        snapshots = db.scalars(select(StationSnapshot).where(StationSnapshot.station_id == station.id)
                               .order_by(StationSnapshot.generation.desc()).limit(20))
        result['snapshots'] = [snapshot_dict(snap) for snap in snapshots]
        result['current_diff'] = current.diff if current else _empty_diff()
        result['current_rows_preview'] = _current_rows(db, station)[:30]
    return result


def _get_station(db, code):
    return db.scalar(select(Station).where(Station.code == code))


def _ensure_station(db, code, name):
    station = _get_station(db, code)
    if station:
        if name and name != station.name:
            station.name = name
        return station
    station = Station(code=code, name=name or code, current_generation=0,
                      current_snapshot_id=None, created_at=time.time())
    db.add(station)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        station = _get_station(db, code)
        if station is None:
            raise HTTPException(409, '站点正在被另一请求创建，请重试')
    return station


def _result(db, station, snapshot, replayed=False, dry_run=False, would_publish=False):
    return {'replayed': replayed, 'dry_run': dry_run,
            'would_publish': would_publish,
            'station': station_dict(db, station),
            'snapshot': snapshot_dict(snapshot),
            'diff': (snapshot.diff if snapshot else _empty_diff())}


def _stage_rows(db, snapshot_id, rows):
    """按块逐条落库并推进 progress；进程中断后可从已提交位置续写。"""
    snapshot = db.get(StationSnapshot, snapshot_id)
    last = db.scalar(select(func.max(LedgerRow.position)).where(LedgerRow.snapshot_id == snapshot_id)) or 0
    snapshot.progress = last
    db.commit()
    while last < len(rows):
        chunk = rows[last:last + CHUNK_SIZE]
        for offset, row in enumerate(chunk):
            db.add(LedgerRow(snapshot_id=snapshot_id, position=last + offset + 1, sample=row['sample'],
                             band=row['band'], reference=row['reference'], measured=row['measured']))
        snapshot = db.get(StationSnapshot, snapshot_id)
        snapshot.progress = last + len(chunk)
        try:
            db.commit()
            last += len(chunk)
        except IntegrityError:
            db.rollback()
            current = db.scalar(select(func.max(LedgerRow.position)).where(LedgerRow.snapshot_id == snapshot_id)) or 0
            if current <= last:
                raise HTTPException(409, '该快照正被另一请求写入，请稍后以相同内容重试')
            last = current
            snapshot = db.get(StationSnapshot, snapshot_id)
            snapshot.progress = last
            db.commit()
    snapshot = db.get(StationSnapshot, snapshot_id)
    if (snapshot.progress or 0) < snapshot.row_count:
        snapshot.progress = last
        db.commit()


def _publish(db, snapshot_id):
    snapshot = db.get(StationSnapshot, snapshot_id)
    if snapshot.status == 'published':
        return _result(db, db.get(Station, snapshot.station_id), snapshot, replayed=True)
    db.rollback()
    snapshot = db.execute(select(StationSnapshot).where(StationSnapshot.id == snapshot_id)
                          .with_for_update()).scalar_one()
    station = db.execute(select(Station).where(Station.id == snapshot.station_id)
                         .with_for_update()).scalar_one()
    if snapshot.status == 'published':
        db.commit()
        return _result(db, station, snapshot, replayed=True)
    # 并发接收不同代号时，先发布的新代已经推进 current_generation；旧执行不得覆盖。
    if snapshot.generation <= (station.current_generation or 0):
        snapshot.status = 'rejected'
        snapshot.diff = {**(_empty_diff()), 'rejected_reason': f'代号 {snapshot.generation} 晚于当前代号 {station.current_generation}，整份拒收'}
        db.commit()
        raise HTTPException(409, f'代号 {snapshot.generation} 晚于当前代号 {station.current_generation}，旧代拒收，本站台账保持不变')
    total = db.scalar(select(func.count()).select_from(LedgerRow)
                      .where(LedgerRow.snapshot_id == snapshot.id)) or 0
    if total != snapshot.row_count:
        snapshot.progress = total
        db.commit()
        raise HTTPException(409, f'快照仅写入 {total}/{snapshot.row_count} 条，尚未达到发布条件，请以相同内容重试续传')
    rows = snapshot_rows(db, snapshot.id)
    if checksum(rows) != snapshot.checksum:
        # 保留暂存状态，旧代继续服务；相同内容重试可继续补齐，不产生新批次。
        snapshot.progress = total
        db.commit()
        raise HTTPException(409, '暂存读数与快照指纹不一致，本站仍使用旧代；请以相同内容重试续传')
    diff = compute_diff(_current_rows(db, station), rows)
    name = f'{station.code} · 全量台账 代号 {snapshot.generation}'
    dataset = db.scalar(select(Dataset).where(Dataset.name == name))
    if dataset is None:
        dataset = Dataset(name=name, source=snapshot.source, records=rows, checksum=snapshot.checksum,
                          created_at=time.time(), station_id=station.id,
                          generation=snapshot.generation, snapshot_id=snapshot.id)
        db.add(dataset)
        try:
            db.flush()
        except IntegrityError:
            # 另一执行刚发布了同代；不得覆盖，按已发布内容重新判定。
            db.rollback()
            return _recheck_after_race(db, snapshot_id)
    else:
        # 同代批次已存在：只接受内容一致的复用，绝不改写已被历史分析绑定的台账。
        if dataset.checksum != snapshot.checksum or dataset.records != rows:
            raise HTTPException(409, f'代号 {snapshot.generation} 的台账批次与快照内容不一致，拒绝覆盖；'
                                     '本站台账保持不变')
    snapshot.status = 'published'
    snapshot.dataset_id = dataset.id
    snapshot.diff = diff
    snapshot.progress = snapshot.row_count
    snapshot.published_at = time.time()
    station.current_generation = snapshot.generation
    station.current_snapshot_id = snapshot.id
    # 更早的暂存代已不可能发布，标记为被取代，避免误以为仍在接入。
    stale = db.scalars(select(StationSnapshot).where(StationSnapshot.station_id == station.id,
                                                     StationSnapshot.status == 'staging',
                                                     StationSnapshot.generation < snapshot.generation))
    for other in stale:
        other.status = 'superseded'
    db.commit()
    return _result(db, station, snapshot, replayed=False)


def _recheck_after_race(db, snapshot_id):
    snapshot = db.get(StationSnapshot, snapshot_id)
    station = db.get(Station, snapshot.station_id)
    if snapshot.status == 'published':
        return _result(db, station, snapshot, replayed=True)
    raise HTTPException(409, '该快照正被另一请求发布，请稍后以相同内容重试')


def intake(db, station_code, generation, rows, source='station-snapshot.json',
           station_name='', actor='', dry_run=False):
    code = (station_code or '').strip()
    if not code:
        raise HTTPException(422, '站点代号不能为空')
    if len(code) > 80:
        raise HTTPException(422, '站点代号最多 80 个字符')
    if generation < 1:
        raise HTTPException(422, '快照代号必须是大于 0 的整数')
    normalized = normalize_rows(rows)
    fingerprint = checksum(normalized)
    station = _get_station(db, code)

    if station is None:
        if dry_run:
            return {'replayed': False, 'dry_run': True, 'would_publish': True,
                    'station': {'code': code, 'name': station_name or code, 'current_generation': 0,
                                'current_snapshot_id': None, 'rows': 0, 'current_checksum': '',
                                'published_at': None, 'current_source': '', 'pending': []},
                    'snapshot': None,
                    'diff': compute_diff([], normalized)}
        station = _ensure_station(db, code, station_name)

    current_generation = station.current_generation or 0
    existing = db.scalar(select(StationSnapshot).where(StationSnapshot.station_id == station.id,
                                                       StationSnapshot.generation == generation))

    if generation < current_generation:
        if existing is not None and existing.status == 'staging':
            existing.status = 'superseded'
            db.commit()
        raise HTTPException(409, f'代号 {generation} 早于当前代号 {current_generation}，旧代拒收，本站台账保持不变')
    if generation == current_generation and existing is not None:
        if existing.checksum == fingerprint:
            return _result(db, station, existing, replayed=True, dry_run=dry_run)
        raise HTTPException(409, f'代号 {generation} 已发布且内容不同，拒绝以异内容覆盖；本站台账保持不变')
    if generation == current_generation and existing is None:
        raise HTTPException(409, f'代号 {generation} 已是当前代号，但没有可重放的快照记录，请检查站点')

    if existing is not None:
        if existing.checksum != fingerprint:
            raise HTTPException(409, f'代号 {generation} 已接收过不同内容的快照，同代异内容冲突；本站台账保持不变')
        if existing.status in ('rejected', 'superseded'):
            raise HTTPException(409, f'代号 {generation} 已被判定过期或冲突，不能再次发布；请回传更高代号')
        if existing.status == 'published':
            return _result(db, station, existing, replayed=True, dry_run=dry_run)

    base_rows = _current_rows(db, station)
    diff = compute_diff(base_rows, normalized)
    if dry_run:
        return {'replayed': False, 'dry_run': True, 'would_publish': True,
                'station': station_dict(db, station), 'snapshot': snapshot_dict(existing),
                'diff': diff}

    if existing is None:
        snapshot = StationSnapshot(station_id=station.id, generation=generation, status='staging',
                                   checksum=fingerprint, source=(source or 'station-snapshot.json')[:200],
                                   row_count=len(normalized), progress=0, diff=_empty_diff(),
                                   dataset_id=None, created_by=actor[:150], created_at=time.time())
        db.add(snapshot)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            snapshot = db.scalar(select(StationSnapshot).where(StationSnapshot.station_id == station.id,
                                                               StationSnapshot.generation == generation))
            if snapshot is None:
                raise HTTPException(409, '该站点快照正在被另一请求接收，请重试')
            if snapshot.checksum != fingerprint:
                raise HTTPException(409, f'代号 {generation} 已接收过不同内容的快照，同代异内容冲突')
    else:
        snapshot = existing

    _stage_rows(db, snapshot.id, normalized)
    return _publish(db, snapshot.id)
