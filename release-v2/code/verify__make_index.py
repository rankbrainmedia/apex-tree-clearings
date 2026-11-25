#!/usr/bin/env python
"""make_index.py: the review pages for the verification set. Writes only into ../out_verify/, and never writes verify_log.csv.

    ../apex-canopy/df-venv/bin/python make_index.py

  out_verify/index.html            front page: the three sets, the log, how to review
  out_verify/review.html           the reviewer: 10 clearings per page, verdict buttons, share slider, notes, export
  out_verify/release/index.html    open the reviewer on the release set   (238)
  out_verify/sample/index.html     open the reviewer on the random sample (100)
  out_verify/large/index.html      open the reviewer on the optional large set (37)
  out_verify/image_dates.csv       the flight or composite dates behind every panel of every image

All three sets are reviewed in the one file, review.html, on purpose: verdicts are saved in the browser's storage for that
file as they are entered, and some browsers keep a separate store for each local file. The three index.html files only pass
the reader on to it. "Export" writes the verdicts out in the format of verify_log.csv (the blank file is read here for its
row order and is not changed); the reader saves the export over the blank log, or anywhere, and runs verify_report.py on it.
"""
import html, json, os
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "out_verify")
PER_PAGE = 10
I = pd.read_csv(os.path.join(OUT, "items.csv"), dtype=str).fillna("")
M = []
for r in I.itertuples():
    fn = os.path.join(OUT, "_meta", r.id + ".json")
    m = json.load(open(fn)) if os.path.exists(fn) else {}
    j = lambda k: "; ".join(m.get(k) or [])
    M.append(dict(id=r.id, set=r.set, image=r.image, image_exists=os.path.exists(os.path.join(OUT, r.image)), frame_m=m.get("frame_m", ""), panels=m.get("panels", ""), naip_before=j("naip_before_dates"),
                  naip_first_after=j("naip_first_after_dates"), naip_during=j("naip_during_dates"), naip_after=j("naip_after_dates") or "none", state_photo=j("state_photo_dates"),
                  state_photo_vs_first_detection=m.get("state_photo_vs_first_detection", ""), s2_before=m.get("s2_before", ""), s2_before_gap_share=m.get("s2_before_gap_share", ""), s2_latest=m.get("s2_latest", "")))
M = pd.DataFrame(M)
M.to_csv(os.path.join(OUT, "image_dates.csv"), index=False)
I = I.merge(M.drop(columns=["set", "image"]), on="id")
I["extra"] = [("status: " + r.release_status) if r.set == "release" else ("stratum: " + r.stratum + (", overlaps release " + r.overlaps_release_id if r.overlaps_release_id else "")) for r in I.itertuples()]
recs = I[["id", "set", "acres", "first_quarter", "governing_case", "case_name", "conflict_flag", "centroid_lat", "centroid_lon", "image", "image_exists", "extra", "naip_before", "naip_first_after", "naip_during", "naip_after",
          "state_photo", "state_photo_vs_first_detection", "frame_m"]].to_dict("records")
# the row order and the acres and quarter strings of the two logs, exactly as the blank logs have them
log_main = pd.read_csv(os.path.join(OUT, "verify_log.csv"), dtype=str).fillna("")[["id", "set", "acres", "first_quarter"]].values.tolist()
log_large = pd.read_csv(os.path.join(OUT, "verify_log_large_optional.csv"), dtype=str).fillna("")[["id", "set", "acres", "first_quarter"]].values.tolist()

CSS = """
*{box-sizing:border-box}
body{font:15px/1.45 -apple-system,Segoe UI,Helvetica,Arial,sans-serif;margin:0;background:#f4f4f1;color:#1c1c1c}
header{position:sticky;top:0;background:#fff;border-bottom:1px solid #cfcfc8;padding:8px 16px;z-index:5}
.bar{display:flex;gap:8px 14px;align-items:center;flex-wrap:wrap}
.bar+.bar{margin-top:6px}
header h1{font-size:16px;margin:0 6px 0 0}
button,select,input[type=text],textarea{font:inherit}
button,select{padding:4px 11px;border:1px solid #9a9a92;background:#fff;border-radius:5px;cursor:pointer;color:inherit}
button:disabled{opacity:.4;cursor:default}
.tabs button.on{background:#1c1c1c;color:#fff;border-color:#1c1c1c}
.small{font-size:13px;color:#555}
#saved{font-size:13px;color:#1b7837}#saved.bad{color:#a11616;font-weight:600}
main{padding:14px 16px 80px}
.item{background:#fff;border:1px solid #d6d6cf;border-left:6px solid #d6d6cf;border-radius:6px;margin:0 0 18px;padding:12px 14px;scroll-margin-top:110px}
.item.cur{border-color:#0b4f8a;box-shadow:0 0 0 2px #0b4f8a33}
.item.done{border-left-color:#1b7837}.item.done.v-partly{border-left-color:#c98a00}.item.done.v-not{border-left-color:#a11616}.item.done.v-cant{border-left-color:#777}
.item h2{font-size:18px;margin:0 0 4px}
.facts{display:flex;gap:6px 22px;flex-wrap:wrap;margin:0 0 8px}
.facts b{font-weight:600}
.dates{color:#555;font-size:13px;margin:6px 0 0}
.flag{color:#a11616;font-weight:600}
img{width:100%;height:auto;display:block;border:1px solid #bbb}
a{color:#0b4f8a}
.verdict{display:flex;gap:8px 10px;align-items:center;flex-wrap:wrap;margin:0 0 10px}
.verdict button{padding:6px 12px}
.verdict button kbd,.keys kbd{font:12px ui-monospace,Menlo,monospace;border:1px solid #aaa;border-radius:3px;padding:0 4px;margin-right:5px;background:#f4f4f1;color:#333}
.verdict button.on{color:#fff;border-color:transparent}
.verdict button.on[data-v="cleared"]{background:#1b7837}.verdict button.on[data-v="partly"]{background:#b07800}
.verdict button.on[data-v="not cleared"]{background:#a11616}.verdict button.on[data-v="can't tell"]{background:#666}
.share{display:flex;gap:8px;align-items:center}
.share input{width:220px}
.share .unset{color:#a11616;font-weight:600}
textarea{width:100%;min-height:34px;height:34px;padding:6px 8px;border:1px solid #b9b9b1;border-radius:5px;resize:vertical;margin:0 0 10px}
.keys{display:none;background:#fbfbf8;border:1px solid #d6d6cf;border-radius:6px;padding:8px 12px;margin:0 0 14px;font-size:14px}
.keys.show{display:block}.keys span{margin-right:18px;white-space:nowrap;display:inline-block}
#modal{position:fixed;inset:0;background:#0008;display:none;align-items:center;justify-content:center;z-index:20}
#modal.show{display:flex}
#modal form{background:#fff;padding:22px 24px;border-radius:8px;max-width:420px;width:90%}
#modal input{width:100%;padding:7px 9px;border:1px solid #9a9a92;border-radius:5px;margin:8px 0 14px}
#msg{display:none;background:#fff8dc;border:1px solid #d9c36a;border-radius:6px;padding:8px 12px;margin:0 0 14px}
#msg.show{display:block}
.note{max-width:980px}
table{border-collapse:collapse}td,th{border:1px solid #cfcfc8;padding:5px 10px;text-align:left}
code{background:#eceae4;padding:1px 4px;border-radius:3px}
"""

JS = r"""
const PER=__PER__, KEY='apexVerify.v1';
const SETS=[['release','Release'],['sample','Random sample'],['large','Large (optional)']];
const VERDICTS=['cleared','partly','not cleared',"can't tell"];
const HEADER=['id','set','acres','first_quarter','reviewer','verdict','share_of_outline_cleared','notes'];
const BY={}; for(const s of SETS) BY[s[0]]=ITEMS.filter(d=>d.set===s[0]);
let store={reviewer:'',rows:{}}, storageOK=true, loadFailed=false, cur=0;
try{const t=localStorage.getItem(KEY); if(t) store=Object.assign(store,JSON.parse(t));}catch(e){loadFailed=true}
const $=id=>document.getElementById(id);
function esc(s){return String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function k(d){return d.set+'/'+d.id}
function row(d){return store.rows[k(d)]||{}}
function save(){const s=$('saved');
 if(loadFailed){s.className='bad'; s.textContent='The verdicts saved in this browser could not be read. Nothing is being saved, so nothing is overwritten. Use "load a saved log" to carry on from an export.'; counts(); return}
 try{localStorage.setItem(KEY,JSON.stringify(store));storageOK=true}catch(e){storageOK=false}
 s.className=storageOK?'':'bad';
 s.textContent=storageOK?('saved in this browser '+new Date().toLocaleTimeString()):'NOT SAVED: this browser is blocking storage for local files. Export often.'; counts()}
function put(d,patch){const r=Object.assign({},row(d),patch); r.r=store.reviewer;
 if(!r.v&&!(r.n||'').trim()) delete store.rows[k(d)]; else store.rows[k(d)]=r; save()}
function state(){const h=location.hash, s=(h.match(/set=(\w+)/)||[])[1], p=+((h.match(/p=(\d+)/)||[])[1]||1);
 const set=BY[s]?s:'release', pages=Math.ceil(BY[set].length/PER); return {set,pages,p:Math.min(Math.max(p,1),pages)}}
function go(set,p){const h='set='+set+'&p='+p; if(location.hash.slice(1)===h) draw(); else location.hash=h}
function pageItems(){const st=state(); return BY[st.set].slice((st.p-1)*PER,st.p*PER)}
function done(d){return !!row(d).v}
function counts(){const st=state();
 $('tabs').innerHTML=SETS.map(([s,label])=>`<button class="${s===st.set?'on':''}" onclick="go('${s}',1)">${label} ${BY[s].filter(done).length}/${BY[s].length}</button>`).join(' ');
 const j=$('jump'), v=j.value;
 j.innerHTML=Array.from({length:st.pages},(_,i)=>{const a=BY[st.set].slice(i*PER,(i+1)*PER);return `<option value="${i+1}">page ${i+1}: ${a[0].id} (${a.filter(done).length}/${a.length})</option>`}).join('');
 j.value=st.p; $('who').textContent=store.reviewer||'not set'}
function controls(d){const r=row(d), partly=r.v==='partly';
 return `<div class="verdict">${VERDICTS.map((v,i)=>`<button data-v="${esc(v)}" class="${r.v===v?'on':''}" onclick="verdict('${d.id}',${i})"><kbd>${i+1}</kbd>${esc(v)}</button>`).join('')}
 <button onclick="verdict('${d.id}',-1)" title="clear the verdict"><kbd>0</kbd>clear</button>
 ${partly?`<span class="share"><input type="range" min="0" max="100" step="5" value="${r.s==null?50:r.s}" oninput="share('${d.id}',+this.value)" aria-label="share of the outline cleared">
 <span class="${r.s==null?'unset':''}" id="sl-${d.id}">${r.s==null?'share not set: move the slider or press [ ]':r.s+'% of the outline cleared'}</span></span>`:''}</div>
 <textarea placeholder="notes" oninput="note('${d.id}',this.value)" onfocus="setCur('${d.id}',true)">${esc(r.n||'')}</textarea>`}
function card(d){const r=row(d), cls=r.v?(' done v-'+({'cleared':'ok','partly':'partly','not cleared':'not',"can't tell":'cant'}[r.v])):'';
 return `<section class="item${cls}" id="${d.id}" onclick="setCur('${d.id}',true)"><h2>${d.id}</h2>
 <div class="facts"><span><b>${esc(d.acres)}</b> acres</span><span>first quarter <b>${d.first_quarter}</b></span><span>governing case <b>${esc(d.governing_case)}</b>${d.case_name?' ('+esc(d.case_name)+')':''}</span>
 ${d.extra?'<span>'+esc(d.extra)+'</span>':''}${d.conflict_flag?'<span class="flag">'+esc(d.conflict_flag)+'</span>':''}
 <span><a href="https://www.openstreetmap.org/?mlat=${d.centroid_lat}&mlon=${d.centroid_lon}#map=16/${d.centroid_lat}/${d.centroid_lon}" target="_blank" rel="noopener">${d.centroid_lat}, ${d.centroid_lon}</a></span></div>
 <div class="ctl">${controls(d)}</div>
 ${d.image_exists?`<a href="${d.image}" target="_blank"><img loading="lazy" src="${d.image}" alt="${d.id}"></a>`:'<p class="flag">image not rendered</p>'}
 <p class="dates">NAIP before: ${d.naip_before||'none'}${d.naip_first_after?' · NAIP first after: '+d.naip_first_after:''}${d.naip_during?' · NAIP during the quarter: '+d.naip_during:''} · NAIP after: ${d.naip_after}
 · State aerial photo: ${d.state_photo||'none'} ${d.state_photo_vs_first_detection?'('+d.state_photo_vs_first_detection.toLowerCase()+')':''} · frame ${d.frame_m} m across</p></section>`}
function draw(){const st=state(), a=pageItems();
 $('list').innerHTML=a.map(card).join('');
 $('where').textContent=`page ${st.p} of ${st.pages} · ${a[0].id} to ${a[a.length-1].id}`;
 $('prev').disabled=st.p<=1; $('next').disabled=st.p>=st.pages; counts();
 cur=Math.min(cur,a.length-1); if(cur<0)cur=0; mark(false); window.scrollTo(0,0)}
function mark(scroll){document.querySelectorAll('.item').forEach((e,i)=>e.classList.toggle('cur',i===cur));
 const e=document.querySelectorAll('.item')[cur]; if(e&&scroll) e.scrollIntoView({block:'start',behavior:'smooth'})}
function setCur(id,quiet){const i=pageItems().findIndex(d=>d.id===id); if(i>=0&&i!==cur){cur=i; mark(!quiet)}}
function repaint(d){const e=$(d.id); if(!e)return; const r=row(d);
 e.className='item'+(r.v?(' done v-'+({'cleared':'ok','partly':'partly','not cleared':'not',"can't tell":'cant'}[r.v])):'')+(pageItems()[cur]&&pageItems()[cur].id===d.id?' cur':'');
 const ta=e.querySelector('textarea'), had=document.activeElement===ta, val=ta?ta.value:'';
 e.querySelector('.ctl').innerHTML=controls(d); if(had){const t=e.querySelector('textarea'); t.value=val; t.focus()}}
function find(id){return pageItems().find(d=>d.id===id)}
function verdict(id,i,advance){const d=find(id); if(!d)return; setCur(id,true);
 if(i<0) put(d,{v:'',s:null}); else put(d,{v:VERDICTS[i],s:VERDICTS[i]==='partly'?(row(d).s==null?null:row(d).s):null});
 repaint(d); if(advance&&i>=0&&VERDICTS[i]!=='partly') step(1)}
function share(id,v){const d=find(id); if(!d)return; v=Math.min(100,Math.max(0,v)); put(d,{s:v});
 const l=$('sl-'+id); if(l){l.textContent=v+'% of the outline cleared'; l.className=''} const sl=$(id).querySelector('input[type=range]'); if(sl&&+sl.value!==v) sl.value=v}
function note(id,v){const d=find(id); if(d){put(d,{n:v}); const e=$(id); if(e&&!row(d).v) e.classList.remove('done')}}
function step(n){const a=pageItems(), st=state();
 if(cur+n>=a.length){if(st.p<st.pages){cur=0; go(st.set,st.p+1)} return}
 if(cur+n<0){if(st.p>1){cur=PER-1; go(st.set,st.p-1)} return}
 cur+=n; mark(true)}
function firstOpen(){const st=state(), i=BY[st.set].findIndex(d=>!done(d)); if(i<0){say('Every clearing in this set has a verdict.');return}
 cur=i%PER; go(st.set,Math.floor(i/PER)+1); setTimeout(()=>mark(true),60)}
function say(t){const m=$('msg'); m.innerHTML=t; m.className=t?'show':''}
function askName(){$('modal').className='show'; const i=$('name'); i.value=store.reviewer||''; setTimeout(()=>i.focus(),30)}
function setName(ev){ev.preventDefault(); const v=$('name').value.trim(); if(!v)return false; store.reviewer=v; save(); $('modal').className=''; return false}
// ---- export and load, in the format of verify_log.csv
function q(s){s=String(s==null?'':s); return /[",\n\r]/.test(s)?'"'+s.replace(/"/g,'""')+'"':s}
function csv(order){return [HEADER.join(',')].concat(order.map(([id,set,acres,fq])=>{const r=store.rows[set+'/'+id]||{};
 return [id,set,acres,fq,(r.v||r.n)?(r.r||store.reviewer):'',r.v||'',(r.v==='partly'&&r.s!=null)?r.s+'%':'',r.n||''].map(q).join(',')})).join('\n')+'\n'}
async function exportLog(which){const order=which==='large'?LOG_LARGE:LOG_MAIN, name=which==='large'?'verify_log_large_optional.csv':'verify_log.csv', text=csv(order);
 const n=order.filter(([id,set])=>(store.rows[set+'/'+id]||{}).v).length, open_=order.filter(([id,set])=>{const r=store.rows[set+'/'+id]||{};return r.v==='partly'&&r.s==null}).length;
 const other=which==='large'?LOG_MAIN:LOG_LARGE, nOther=other.filter(([id,set])=>(store.rows[set+'/'+id]||{}).v).length;
 const tail=`${n} of ${order.length} rows have a verdict`+(open_?`; ${open_} "partly" row(s) have no share set`:'')+'.'
  +(nOther?`<br><b>This file does not hold your ${nOther} verdict(s) for the ${which==='large'?'release and sample sets':'large set'}.</b> They go in their own file: press "${which==='large'?'Export to verify_log.csv':'Export large set log'}" as well.`:'');
 if(window.showSaveFilePicker){try{const h=await window.showSaveFilePicker({suggestedName:name,types:[{description:'CSV',accept:{'text/csv':['.csv']}}]});
   const w=await h.createWritable(); await w.write(text); await w.close(); say(`Saved as <b>${esc(h.name)}</b>. ${tail} To replace the blank log, save it as <code>out_verify/${name}</code>.`); return}catch(e){if(e&&e.name==='AbortError')return}}
 const a=document.createElement('a'); a.href=URL.createObjectURL(new Blob([text],{type:'text/csv'})); a.download=name; document.body.appendChild(a); a.click(); a.remove();
 say(`Downloaded <b>${name}</b> to your downloads folder. ${tail} Move it into <code>out_verify/</code> over the blank log, or run <code>verify_report.py --log</code> on it where it is.`)}
function parseCSV(t){const rows=[];let r=[],f='',inq=false;for(let i=0;i<t.length;i++){const c=t[i];
  if(inq){if(c==='"'){if(t[i+1]==='"'){f+='"';i++}else inq=false}else f+=c}
  else if(c==='"')inq=true; else if(c===','){r.push(f);f=''} else if(c==='\n'||c==='\r'){if(c==='\r'&&t[i+1]==='\n')i++; r.push(f);f=''; if(r.length>1||r[0]!=='')rows.push(r); r=[]} else f+=c}
 if(f!==''||r.length){r.push(f);rows.push(r)} return rows}
function loadLog(file){const fr=new FileReader(); fr.onload=()=>{const rows=parseCSV(String(fr.result)), h=rows.shift()||[]; const ix=Object.fromEntries(HEADER.map(c=>[c,h.indexOf(c)]));
  if(HEADER.some(c=>ix[c]<0)){say('That file does not have the columns of verify_log.csv.');return} let n=0,skip=0;
  for(const r of rows){const key=(r[ix.set]||'').trim().toLowerCase()+'/'+(r[ix.id]||'').trim(); if(!ITEMS.some(d=>k(d)===key)){if(r[ix.id])skip++;continue}
   let v=(r[ix.verdict]||'').trim().toLowerCase().replace(/[’`]/g,"'").replace(/\s+/g,' '); if(v==='cant tell')v="can't tell";
   const nt=r[ix.notes]||''; if(!VERDICTS.includes(v)){if(v)skip++; v=''} if(!v&&!nt.trim())continue;
   let s=null; const raw=(r[ix.share_of_outline_cleared]||'').trim(); if(v==='partly'&&raw){let x=parseFloat(raw); if(!isNaN(x)){if(!raw.includes('%')&&x<=1)x*=100; s=Math.round(Math.min(100,Math.max(0,x)))}}
   store.rows[key]={v,s,n:nt,r:(r[ix.reviewer]||'').trim()||store.reviewer}; n++}
  loadFailed=false; save(); draw(); say(`Loaded ${n} row(s) from ${esc(file.name)}`+(skip?`; ${skip} row(s) were not recognised and were left out`:'')+'. Rows the file leaves blank were not changed.')}; fr.readAsText(file)}
// ---- keys
document.addEventListener('keydown',e=>{const t=e.target.tagName; if(e.metaKey||e.ctrlKey||e.altKey)return;
 if(t==='TEXTAREA'||(t==='INPUT'&&e.target.type==='text')){if(e.key==='Escape')e.target.blur(); return}
 if($('modal').className==='show'||t==='SELECT')return;
 const a=pageItems(), d=a[cur], st=state(); if(!d)return;
 if(e.key>='1'&&e.key<='4'){verdict(d.id,+e.key-1,true); e.preventDefault()}
 else if(e.key==='0'){verdict(d.id,-1); e.preventDefault()}
 else if((e.key==='['||e.key===']')&&row(d).v==='partly'){const s=row(d).s==null?50:row(d).s; share(d.id,s+(e.key===']'?5:-5)); e.preventDefault()}
 else if(e.key==='j'||e.key==='Enter'){step(1); e.preventDefault()}
 else if(e.key==='k'){step(-1); e.preventDefault()}
 else if(e.key==='n'){const x=$(d.id).querySelector('textarea'); if(x){x.focus(); e.preventDefault()}}
 else if(e.key==='u'){firstOpen(); e.preventDefault()}
 else if(e.key==='ArrowRight'&&t!=='INPUT'&&st.p<st.pages){cur=0; go(st.set,st.p+1)}
 else if(e.key==='ArrowLeft'&&t!=='INPUT'&&st.p>1){cur=0; go(st.set,st.p-1)}
 else if(e.key==='?'){$('keys').classList.toggle('show')}});
window.addEventListener('hashchange',draw);
draw(); save(); if(!store.reviewer) askName();
"""

page = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Clearing review</title><style>__CSS__</style></head><body>
<header><div class="bar"><h1>Clearing review</h1><span class="tabs" id="tabs"></span>
<button id="prev" onclick="cur=0;go(state().set,state().p-1)">&larr; previous</button><select id="jump" onchange="cur=0;go(state().set,this.value)"></select><button id="next" onclick="cur=0;go(state().set,state().p+1)">next &rarr;</button>
<span id="where" class="small"></span><button onclick="firstOpen()" title="key: u">first unreviewed</button></div>
<div class="bar"><span class="small">Reviewer: <b id="who"></b> <a href="#" onclick="askName();return false">change</a></span>
<button onclick="exportLog('main')">Export to verify_log.csv</button><button onclick="exportLog('large')">Export large set log</button>
<label class="small"><a href="#" onclick="document.getElementById('file').click();return false">load a saved log</a><input id="file" type="file" accept=".csv,text/csv" hidden onchange="if(this.files[0])loadLog(this.files[0]);this.value=''"></label>
<span id="saved"></span><a href="#" class="small" onclick="document.getElementById('keys').classList.toggle('show');return false">keys (?)</a><a href="index.html" class="small">front page</a></div></header>
<main><div id="msg"></div>
<div id="keys" class="keys"><span><kbd>1</kbd>cleared</span><span><kbd>2</kbd>partly</span><span><kbd>3</kbd>not cleared</span><span><kbd>4</kbd>can't tell</span><span><kbd>0</kbd>clear the verdict</span>
<span><kbd>[</kbd><kbd>]</kbd>share down / up 5 points (partly)</span><span><kbd>j</kbd> or <kbd>Enter</kbd>next clearing</span><span><kbd>k</kbd>previous</span><span><kbd>n</kbd>notes (<kbd>Esc</kbd> to leave)</span>
<span><kbd>&larr;</kbd><kbd>&rarr;</kbd>turn the page</span><span><kbd>u</kbd>first unreviewed</span><br>Keys act on the clearing with the blue border. 1, 3 and 4 move on to the next clearing; 2 stays so the share can be set.</div>
<div id="list"></div></main>
<div id="modal"><form onsubmit="return setName(event)"><b>Your name, for the reviewer column</b><br><span class="small">Asked once and kept in this browser. It is written on each row you give a verdict.</span>
<input id="name" type="text" autocomplete="off"><button type="submit">Start reviewing</button></form></div>
<script>const ITEMS=__ITEMS__, LOG_MAIN=__LOGMAIN__, LOG_LARGE=__LOGLARGE__;__JS__</script></body></html>"""
page = (page.replace("__CSS__", CSS).replace("__JS__", JS.replace("__PER__", str(PER_PAGE))).replace("__ITEMS__", json.dumps(recs).replace("</", "<\\/"))
        .replace("__LOGMAIN__", json.dumps(log_main)).replace("__LOGLARGE__", json.dumps(log_large)))
open(os.path.join(OUT, "review.html"), "w").write(page)

for s in ("release", "sample", "large"):
    os.makedirs(os.path.join(OUT, s), exist_ok=True)
    open(os.path.join(OUT, s, "index.html"), "w").write(f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{s} set</title>
<script>var p=(location.hash.match(/p=(\\d+)/)||[])[1]||1;location.replace("../review.html#set={s}&p="+p);</script></head>
<body><p>The {s} set is reviewed in <a href="../review.html#set={s}&p=1">review.html</a>.</p></body></html>""")

D = json.load(open(os.path.join(OUT, "sample_draw.json")))
alloc = pd.DataFrame(D["allocation"])
rows = "".join(f"<tr><td>{y}</td>" + "".join(f"<td>{int(g[g.size_class == c].drawn.sum())} of {int(g[g.size_class == c].clearings.sum())}</td>" for c in D["size_classes"]) + f"<td>{int(g.drawn.sum())} of {int(g.clearings.sum())}</td></tr>"
               for y, g in alloc.groupby("year"))
n_missing = int((~M.image_exists).sum())
n_set = I.groupby("set").size()
has_after = I[I.naip_after != "none"].groupby("set").size()
front = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Clearing verification set</title><style>{CSS}</style></head><body>
<header><h1>Clearing verification set</h1></header><main class="note">
<p><a href="review.html#set=release&p=1"><b>Release clearings</b></a>: all {n_set['release']}, C001 to C238, largest first.<br>
<a href="review.html#set=sample&p=1"><b>Random sample</b></a>: {n_set['sample']} clearings drawn from the {D['frame']['clearings']} in the 2017-2026 detection ({D['frame']['acres']:,} acres), by year and size. Seed {D['seed']}.<br>
<a href="review.html#set=large&p=1"><b>Optional: the other large clearings</b></a>: the {n_set['large']} clearings over 10 acres that the draw did not pick. They go in their own log,
verify_log_large_optional.csv. Clearings over 10 acres hold 44% of the detection's acres, so reviewing all of them makes the acres-weighted result much firmer. Skip it and the report still runs.</p>
{f'<p class="flag">{n_missing} image(s) have not been rendered yet. Run render.py again, then make_index.py.</p>' if n_missing else ''}
<h3>Reviewing</h3>
<p>All three sets open in one page, <a href="review.html">review.html</a>, ten clearings at a time. Each clearing has four verdict buttons (<b>cleared</b>, <b>partly</b>, <b>not cleared</b>, <b>can't tell</b>), a share slider that
appears for "partly", and a notes box. Number keys 1 to 4 give the verdict to the clearing with the blue border and move on; press <b>?</b> on the page for all the keys. It asks for your reviewer name once.</p>
<p><b>Saving.</b> Every click is saved at once in this browser's own storage for that page. That store belongs to this browser on this computer: it does not travel, and clearing the browser's site data wipes it.
So press <b>Export to verify_log.csv</b> now and then, and when you finish. The export has every row of the log in its original order and format. Save it over the blank
<a href="verify_log.csv">verify_log.csv</a> in this folder (in Chrome the button lets you pick the file; in other browsers it lands in your downloads folder). "Load a saved log" reads an export back in,
on this or another computer. Then run <code>verify/verify_report.py</code>. A "partly" row with no share is carried as a range, from none of it to all of it.</p>
<h3>What each image shows</h3>
<ol><li><b>NAIP before</b>: the latest NAIP flight flown before the first-detection quarter began. For clearings first detected from October 2025 on, that is the July 25, 2025 flight.</li>
<li><b>NAIP first after</b> (older clearings only): the first NAIP flight after the first-detection quarter, where that is not also the latest one.</li>
<li><b>NAIP during</b> (a few clearings): a flight flown inside the first-detection quarter. It may show the ground before or after the clearing.</li>
<li><b>NAIP after</b>: the latest NAIP flight flown after the first-detection quarter ended. The latest flight over Apex is <b>July 25, 2025</b> (30 cm), so every clearing first detected before July 2025 has a NAIP "after"
({int(has_after.get('release', 0))} of {n_set['release']} release clearings, {int(has_after.get('sample', 0))} of {n_set['sample']} sampled, {int(has_after.get('large', 0))} of {n_set['large']} large). Clearings first detected from July 2025 on have none, and the panel says so.</li>
<li><b>State aerial photo</b>: North Carolina's own 6-inch photography (NC OneMap), flown over Wake County on February 14, 2025 with the leaves off. It is not NAIP. The green or red title says whether it was flown after or before the first detection.</li>
<li><b>Sentinel-2 before</b>: true colour, the last July-September before the first-detection quarter, at 10 m.</li>
<li><b>Sentinel-2 latest</b>: true colour, October 1-24, 2026, at 10 m. For clearings first detected from July 2025 on, this is the only "after" view.</li></ol>
<p>The yellow line is the detected outline. Click an image to open it at full size.</p>
<h3>The sample draw</h3>
<table><tr><th>Year</th>{''.join(f'<th>{c}</th>' for c in D['size_classes'])}<th>All sizes</th></tr>{rows}</table>
<p>Drawn of available, by year of first detection and size. Files: <a href="sample_frame.csv">sample_frame.csv</a> (every clearing in the frame, its stratum and whether it was drawn), <a href="sample_draw.json">sample_draw.json</a> (seed and allocation),
<a href="items.csv">items.csv</a>, <a href="image_dates.csv">image_dates.csv</a>, <a href="outlines.geojson">outlines.geojson</a>.</p>
<p>Imagery: USDA NAIP; NC OneMap orthoimagery (NC Center for Geographic Information and Analysis, NC 911 Board); Copernicus Sentinel-2 (ESA).</p></main></body></html>"""
open(os.path.join(OUT, "index.html"), "w").write(front)
print(f"pages written; {int(M.image_exists.sum())} of {len(M)} images present")
Mi = M.merge(I[["id", "set", "first_quarter"]], on=["id", "set"])
print(Mi.groupby("set").agg(items=("id", "size"), naip_after=("naip_after", lambda s: int((s != "none").sum())), naip_after_2025=("naip_after", lambda s: int(s.str.contains("2025-07-25").sum())),
                            naip_first_after=("naip_first_after", lambda s: int((s != "").sum())), naip_during=("naip_during", lambda s: int((s != "").sum())),
                            naip_before_2025=("naip_before", lambda s: int(s.str.contains("2025-07-25").sum())), state_photo_missing=("state_photo", lambda s: int((s == "").sum()) + int(s.str.contains("error").sum()))).to_string())
