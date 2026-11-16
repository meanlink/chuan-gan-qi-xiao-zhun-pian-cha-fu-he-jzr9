/** @typedef {{id:number,name:string,source:string,rows:number,checksum:string,station_id:number|null,generation:number|null,snapshot_id:number|null,station_code:string,is_current:boolean}} Dataset */
/** @typedef {{id:number,name:string,dataset_id:number,station_code:string,dataset_generation:number|null,dataset_checksum:string,status:string,result:Object,approved:boolean}} AnalysisJob */
/** @typedef {{id:number,name:string,job_id:number,destination:string,next_run:number,enabled:boolean}} ReportSchedule */
/** @typedef {{code:string,name:string,current_generation:number,current_snapshot_id:number|null,rows:number,current_checksum:string,published_at:number|null,pending:Array<{id:number,generation:number,progress:number,row_count:number,checksum:string}>}} Station */
/** @typedef {{id:number,station_id:number,generation:number,status:string,checksum:string,source:string,row_count:number,progress:number,diff:Object,dataset_id:number|null,created_at:number,published_at:number|null}} StationSnapshot */
export {};
