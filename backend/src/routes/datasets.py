from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from src.config.database import get_db
from src.models import Dataset, Station
from src.schemas.dataset import DatasetInput
from src.middlewares.auth import current_user, can_write
from src.services import datasets
from src.services.audit import record
from src.utils.serialization import dataset_dict

router = APIRouter(prefix='/datasets')


def _annotate(db, d):
    data = dataset_dict(d)
    station = db.get(Station, d.station_id) if d.station_id else None
    data['station_code'] = station.code if station else ''
    data['is_current'] = station is None or d.snapshot_id == station.current_snapshot_id
    return data


@router.get('')
def listing(db=Depends(get_db), u=Depends(current_user)):
    return [_annotate(db, d) for d in db.scalars(select(Dataset).order_by(Dataset.id.desc()))]


@router.post('', status_code=201)
def create(data: DatasetInput, db=Depends(get_db), u=Depends(can_write)):
    d = datasets.create(db, data); record(db, u.email, 'dataset.create', {'id': d.id, 'rows': len(d.records)})
    db.commit(); return _annotate(db, d)


@router.get('/{id}')
def detail(id: int, db=Depends(get_db), u=Depends(current_user)):
    d = db.get(Dataset, id)
    if not d: raise HTTPException(404, '数据批次不存在')
    return {**_annotate(db, d), 'records': d.records}
