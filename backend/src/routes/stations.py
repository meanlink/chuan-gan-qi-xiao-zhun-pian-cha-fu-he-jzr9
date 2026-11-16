from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from src.config.database import get_db
from src.models import Station, StationSnapshot
from src.schemas.station import SnapshotInput
from src.middlewares.auth import current_user, can_write
from src.services import stations
from src.services.audit import record

router = APIRouter(prefix='/stations')


@router.get('')
def listing(db=Depends(get_db), u=Depends(current_user)):
    return [stations.station_dict(db, s) for s in db.scalars(select(Station).order_by(Station.code))]


@router.get('/{code}')
def detail(code: str, db=Depends(get_db), u=Depends(current_user)):
    station = db.scalar(select(Station).where(Station.code == code))
    if not station:
        raise HTTPException(404, '站点不存在')
    return stations.station_dict(db, station, detail=True)


@router.get('/{code}/snapshots')
def snapshots(code: str, db=Depends(get_db), u=Depends(current_user)):
    station = db.scalar(select(Station).where(Station.code == code))
    if not station:
        raise HTTPException(404, '站点不存在')
    rows = db.scalars(select(StationSnapshot).where(StationSnapshot.station_id == station.id)
                      .order_by(StationSnapshot.generation.desc()).limit(50))
    return [stations.snapshot_dict(s) for s in rows]


@router.get('/{code}/current')
def current(code: str, db=Depends(get_db), u=Depends(current_user)):
    station = db.scalar(select(Station).where(Station.code == code))
    if not station:
        raise HTTPException(404, '站点不存在')
    return {'station': stations.station_dict(db, station),
            'rows': stations.snapshot_rows(db, station.current_snapshot_id)}


@router.post('/{code}/snapshots')
def receive(code: str, data: SnapshotInput, response: Response = None, dry_run: bool = False,
            db=Depends(get_db), u=Depends(can_write)):
    result = stations.intake(db, code, data.generation, data.records, source=data.source,
                             station_name=data.station_name, actor=u.email, dry_run=dry_run)
    if not dry_run and not result.get('replayed'):
        record(db, u.email, 'station.snapshot.publish',
               {'station': code, 'generation': data.generation,
                'counts': result['diff']['counts'],
                'checksum': result['snapshot']['checksum']})
        db.commit()
    # 201 表示确实发布了新代；同代重试、预校验与拒收的 409 由异常处理。
    if response is not None:
        response.status_code = 200 if (dry_run or result.get('replayed')) else 201
    return result
