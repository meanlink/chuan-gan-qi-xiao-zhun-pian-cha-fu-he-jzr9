from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from src.config.database import get_db
from src.middlewares.auth import current_user
from src.models import Dataset, Job, Report, Audit, Station, StationSnapshot, LedgerRow
from src.services.business import metadata
from src.services import stations

router = APIRouter()


@router.get('/meta')
def meta(): return metadata()


@router.get('/overview')
def overview(db=Depends(get_db), user=Depends(current_user)):
    station_list = list(db.scalars(select(Station).order_by(Station.code)))
    return {'datasets': db.scalar(select(func.count()).select_from(Dataset)),
            'records': db.scalar(select(func.count()).select_from(LedgerRow).where(
                LedgerRow.snapshot_id.in_([s.current_snapshot_id for s in station_list if s.current_snapshot_id]))),
            'jobs': db.scalar(select(func.count()).select_from(Job)),
            'approved': db.scalar(select(func.count()).select_from(Job).where(Job.approved == True)),
            'reports': db.scalar(select(func.count()).select_from(Report)),
            'stations': len(station_list),
            'snapshots': db.scalar(select(func.count()).select_from(StationSnapshot)),
            'pending': [{'station': s.code, **p} for s in station_list
                        for p in stations.station_dict(db, s)['pending']]}


@router.get('/audits')
def audits(db=Depends(get_db), user=Depends(current_user)):
    return [{'id': a.id, 'actor': a.actor, 'action': a.action, 'detail': a.detail, 'at': a.at}
            for a in db.scalars(select(Audit).order_by(Audit.id.desc()).limit(50))]
