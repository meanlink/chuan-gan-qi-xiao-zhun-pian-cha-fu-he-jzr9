import time
from fastapi import HTTPException
from redis import Redis
from sqlalchemy import select
from src.config.settings import REDIS_URL
from src.models import Dataset, Job, Station
from src.services.business import metadata


def create(db, data, user):
    # 先取批次再按站点行加锁，与发布时的加锁顺序一致，避免创建与换代交错。
    dataset = db.get(Dataset, data.dataset_id)
    if not dataset: raise HTTPException(404, '数据批次不存在')
    station = db.get(Station, dataset.station_id) if dataset.station_id else None
    if station is not None:
        station = db.execute(select(Station).where(Station.id == station.id).with_for_update()).scalar_one()
        db.refresh(dataset)
    allowed = {p['key']: p for p in metadata().get('parameters', [])}
    if set(data.params) - set(allowed): raise HTTPException(422, '包含未知分析参数')
    params = {k: p['default'] for k, p in allowed.items()}
    params.update(data.params)
    for key, p in allowed.items():
        v = params[key]
        if p['type'] == 'number':
            try:
                v = float(v)
                if not (p.get('min', -1e9) <= v <= p.get('max', 1e9)): raise ValueError()
                params[key] = v
            except (ValueError, TypeError): raise HTTPException(422, f'{p["label"]} 超出范围或非数值')
        elif str(v) not in [str(o['value']) for o in p.get('options', [])]:
            raise HTTPException(422, f'{p["label"]} 不是有效选项')
    # 已被新代替换的台账不再进入新分析；历史任务与其简报仍保留当时的完整读数。
    if station is not None and dataset.snapshot_id != station.current_snapshot_id:
        raise HTTPException(409, f'{station.code} 当前代号为 {station.current_generation}，'
                                 '请使用站点当前台账发起分析；历史分析保留当时读数')
    j = Job(name=data.name, dataset_id=dataset.id, params=params, created_by=user.id, created_at=time.time(),
            status='queued', station_code=station.code if station else '',
            dataset_generation=dataset.generation, dataset_checksum=dataset.checksum or '')
    db.add(j); db.flush()
    return j


def enqueue(job_id):
    try:
        r = Redis.from_url(REDIS_URL); r.rpush('analysis:queue', job_id); r.close()
    except Exception:
        pass  # SQL queued status is the durable fallback
