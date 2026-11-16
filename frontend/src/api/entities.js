import {api} from './client.js';
export const datasets={list:()=>api('/datasets'),get:id=>api('/datasets/'+id),create:data=>api('/datasets',{method:'POST',body:JSON.stringify(data)})};
export const jobs={list:()=>api('/jobs'),get:id=>api('/jobs/'+id),create:data=>api('/jobs',{method:'POST',body:JSON.stringify(data)}),approve:id=>api('/jobs/'+id+'/approve',{method:'POST'})};
export const reports={list:()=>api('/reports'),create:data=>api('/reports',{method:'POST',body:JSON.stringify(data)}),toggle:id=>api('/reports/'+id+'/toggle',{method:'POST'}),deliveries:()=>api('/deliveries')};
export const stations={
 list:()=>api('/stations'),
 get:code=>api('/stations/'+encodeURIComponent(code)),
 current:code=>api('/stations/'+encodeURIComponent(code)+'/current'),
 snapshots:code=>api('/stations/'+encodeURIComponent(code)+'/snapshots'),
 receive:(code,data,dryRun=false)=>api('/stations/'+encodeURIComponent(code)+'/snapshots'+(dryRun?'?dry_run=true':''),{method:'POST',body:JSON.stringify(data)})
};
