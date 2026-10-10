"use strict";
const $ = id => document.getElementById(id);
const navNames = {home:'首页',live:'实时评估',video:'视频评估',history:'评估报告与记录'};
const state = {poses:{},socket:null,camera:null,timer:null,previewUrl:null,lastReport:null,lastVoice:'',pending:false};
const labels = {joint_conformity:'S1 · 姿势符合性',topology_stability:'S2 · 拓扑稳定性',force_proxy:'S3 · 支撑链视觉代理'};
const steps = {guide:0,framing:1,stabilizing:2,scoring:3,advice:4,reassess:1};

function go(name){
  if(!navNames[name])name='home';
  document.querySelectorAll('[data-page]').forEach(p=>p.classList.toggle('active',p.dataset.page===name));
  document.querySelectorAll('[data-nav]').forEach(b=>b.classList.toggle('active',b.dataset.nav===name));
  $('crumb-current').textContent=navNames[name];
  history.replaceState(null,'','#'+name);
  if(name==='history')loadReports();
  window.scrollTo({top:0,behavior:'smooth'});
}
document.querySelectorAll('[data-go],[data-nav]').forEach(el=>el.addEventListener('click',()=>go(el.dataset.go||el.dataset.nav)));
window.addEventListener('hashchange',()=>go(location.hash.slice(1)));
const safe = x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num = v=>Number.isFinite(Number(v))?Number(v).toFixed(1):'—';
async function api(path, options){
  const r=await fetch(path,options);
  if(!r.ok){let message=`HTTP ${r.status}`;try{const j=await r.json();message=typeof j.detail==='string'?j.detail:message;}catch{}throw Error(message);}
  return r.json();
}
async function startup(){
  try{
    const [status,p]=await Promise.all([api('/health'),api('/poses')]);
    if(!status.ok)throw Error('后端健康检查失败');
    p.poses.forEach(item=>state.poses[item.id]=item.name);
    const items=p.poses.map(x=>`<option value="${safe(x.id)}">${safe(x.name)}</option>`).join('');
    $('live-pose').innerHTML=items;$('video-pose').innerHTML=items;
    $('live-pose').value='warrior2';$('video-pose').value='warrior2';
    $('api-status').textContent='算法服务已连接';$('api-indicator').classList.add('ok');
  }catch(e){$('api-status').textContent='后端连接失败：'+e.message;}
  go(location.hash.slice(1)||'home');
}
function speak(msg, interrupt=true){
  if(!msg||!('speechSynthesis' in window))return;
  if(interrupt)window.speechSynthesis.cancel();
  const u=new SpeechSynthesisUtterance(String(msg));u.lang='zh-CN';u.rate=.95;u.pitch=1;
  window.speechSynthesis.speak(u);
}
function scoreHtml(obj,compact=false){
  if(!obj||!obj.dimensions)return `<div class="empty-result">暂无可靠评分</div>`;
  const bars=Object.entries(labels).map(([k,label])=>`<div class="measure"><div class="measure-label"><span>${safe(label)}</span><strong>${num(obj.dimensions[k])}</strong></div><div class="measure-track"><div style="width:${Math.min(100,Math.max(0,Number(obj.dimensions[k])||0))}%"></div></div></div>`).join('');
  return `<div class="score-top"><div class="score-bubble">${num(obj.score)}</div><div><strong>综合评分 · ${safe(obj.grade)}</strong><small>真实算法评估结果 / 100</small></div></div>${bars}<div class="risk-row"><span>动作代偿代理风险</span><strong>${num(obj.risk)}%</strong></div><div class="advice-card"><strong>动作纠正建议</strong><br>${safe(obj.advice)}</div><details class="advanced"><summary>展开技术分析详情</summary><pre>${safe(JSON.stringify({confidence:obj.confidence,compensation:obj.compensation,topology_ik:obj.topology_ik,hold:obj.hold,metric_scores:obj.metric_scores},null,2))}</pre></details>`;
}
function setPhase(phase,message,progress=0){
  $('live-message').textContent=message||'正在检测';
  $('camera-label').textContent=({guide:'动作引导',framing:'位置检测',stabilizing:'稳定检测',scoring:'正在评分',advice:'纠正指导',reassess:'再次评估'})[phase]||'检测中';
  const idx=steps[phase]??0;
  document.querySelectorAll('#live-steps li').forEach((el,i)=>el.classList.toggle('active',i===idx));
  $('stable-bar').style.width=Math.round(Math.min(1,progress)*100)+'%';
}
function drawSkeleton(points){
  const c=$('live-overlay'),v=$('camera-video'),box=$('live-stage');
  const cw=box.clientWidth,ch=box.clientHeight;
  const dpr=Math.min(devicePixelRatio||1,2);
  c.width=cw*dpr;c.height=ch*dpr;const ctx=c.getContext('2d');ctx.scale(dpr,dpr);ctx.clearRect(0,0,cw,ch);
  if(!Array.isArray(points)||points.length!==33||!v.videoWidth)return;
  const scale=Math.min(cw/v.videoWidth,ch/v.videoHeight),rw=v.videoWidth*scale,rh=v.videoHeight*scale;
  const ox=(cw-rw)/2,oy=(ch-rh)/2;
  const xy=i=>[ox+points[i][0]*rw,oy+points[i][1]*rh];
  const edges=[[11,13],[13,15],[12,14],[14,16],[11,12],[11,23],[12,24],[23,24],[23,25],[25,27],[24,26],[26,28],[27,31],[28,32]];
  ctx.lineWidth=3;ctx.strokeStyle='#b9d8a9';
  edges.forEach(([a,b])=>{if(points[a][3]<.5||points[b][3]<.5)return;ctx.beginPath();ctx.moveTo(...xy(a));ctx.lineTo(...xy(b));ctx.stroke();});
  ctx.fillStyle='#eec16e';points.forEach((p,i)=>{if(p[3]<.5)return;const [x,y]=xy(i);ctx.beginPath();ctx.arc(x,y,3,0,2*Math.PI);ctx.fill();});
}
async function startCamera(){
  if(state.socket)return;
  const pose=$('live-pose').value,view=$('live-view').value,level=$('live-level').value;
  $('start-live').disabled=true;
  try{
    if(!navigator.mediaDevices?.getUserMedia)throw Error('当前浏览器未开放摄像头 API，请使用 localhost 或 HTTPS');
    state.camera=await navigator.mediaDevices.getUserMedia({video:{width:{ideal:960},height:{ideal:720},facingMode:'user'},audio:false});
    const video=$('camera-video');video.srcObject=state.camera;await video.play();
    $('camera-placeholder').style.display='none';
    const protocol=location.protocol==='https:'?'wss:':'ws:';
    const ws=new WebSocket(`${protocol}//${location.host}/ws/assess`);state.socket=ws;
    ws.onopen=()=>{ws.send(JSON.stringify({pose,view,level}));setPhase('guide',`请准备${state.poses[pose]||pose}`);speak(`请准备${state.poses[pose]||pose}。将身体完整放入画面，保持姿势稳定约两秒。`);
      const capture=document.createElement('canvas');capture.width=640;capture.height=480;
      state.timer=setInterval(()=>{
        if(ws.readyState!==WebSocket.OPEN||state.pending||!video.videoWidth)return;
        const ratio=Math.min(640/video.videoWidth,480/video.videoHeight,1);
        capture.width=Math.max(1,Math.round(video.videoWidth*ratio));capture.height=Math.max(1,Math.round(video.videoHeight*ratio));
        capture.getContext('2d').drawImage(video,0,0,capture.width,capture.height);
        state.pending=true;
        capture.toBlob(blob=>{if(blob&&ws.readyState===WebSocket.OPEN){blob.arrayBuffer().then(buf=>ws.send(buf)).finally(()=>state.pending=false);}else state.pending=false;},'image/jpeg',.68);
      },230);
    };
    ws.onmessage=ev=>{
      let msg;try{msg=JSON.parse(ev.data);}catch{return;}
      if(msg.error){$('live-message').textContent=msg.error;return;}
      setPhase(msg.phase,msg.message,msg.progress||0);drawSkeleton(msg.landmarks);
      if(msg.result){state.lastReport=msg.result;$('live-result').innerHTML=scoreHtml(msg.result);speak(msg.result.advice);}
    };
    ws.onerror=()=>{$('live-message').textContent='连接失败，请检查后端服务';};
    ws.onclose=()=>{if(state.socket===ws){stopCamera(false);}};
    $('stop-live').disabled=false;
  }catch(e){$('live-message').textContent='无法启动摄像头：'+e.message;stopCamera(false);}
}
function stopCamera(close=true){
  if(state.timer){clearInterval(state.timer);state.timer=null;}
  const ws=state.socket;state.socket=null;
  if(close&&ws&&ws.readyState<=1)ws.close(1000,'stop');
  if(state.camera){state.camera.getTracks().forEach(t=>t.stop());state.camera=null;}
  $('camera-video').srcObject=null;$('camera-placeholder').style.display='grid';
  $('stop-live').disabled=true;$('start-live').disabled=false;state.pending=false;
  drawSkeleton([]);$('camera-label').textContent='尚未连接';
  if(close){setPhase('guide','训练已结束；有效结果将在历史记录中保存');speak('训练已结束。');}
}
$('start-live').onclick=startCamera;$('stop-live').onclick=()=>stopCamera();
window.addEventListener('beforeunload',()=>stopCamera(false));
const upload=$('video-file'),drop=$('drop-zone');
function showFile(file){
  if(state.previewUrl)URL.revokeObjectURL(state.previewUrl);
  $('video-filename').textContent=file?`${file.name} · ${(file.size/1024/1024).toFixed(1)}MB`:'尚未选择视频';
  $('upload-preview').classList.toggle('show',!!file);
  if(file){state.previewUrl=URL.createObjectURL(file);$('upload-preview').src=state.previewUrl;}
}
upload.onchange=()=>showFile(upload.files[0]);
['dragover','dragenter'].forEach(type=>drop.addEventListener(type,e=>{e.preventDefault();drop.classList.add('dragging');}));
['dragleave','drop'].forEach(type=>drop.addEventListener(type,e=>{e.preventDefault();drop.classList.remove('dragging');}));
drop.addEventListener('drop',e=>{const f=e.dataTransfer.files[0];if(f){const dt=new DataTransfer();dt.items.add(f);upload.files=dt.files;showFile(f);}});
$('submit-video').onclick=async()=>{
  const file=upload.files[0];if(!file){$('video-message').textContent='请先选择视频';return;}
  if(file.size>120*1024*1024){$('video-message').textContent='视频超过120MB限制';return;}
  const btn=$('submit-video');btn.disabled=true;btn.textContent='正在逐帧分析，请稍候…';
  $('video-message').textContent='系统正在逐帧提取关键点、评估稳定性并选取最佳有效帧。';
  const form=new FormData();form.append('file',file);
  const p=new URLSearchParams({pose:$('video-pose').value,view:$('video-view').value,level:$('video-level').value});
  try{const result=await api(`/analyze-video?${p}`,{method:'POST',body:form});
    $('video-result').innerHTML=`<img src="${result.best_frame_url}" alt="最佳帧（已标注关键点）" style="width:100%;border-radius:10px;margin-bottom:16px"/>`+scoreHtml(result.result);
    $('video-message').textContent=`分析完成 · 共处理 ${result.video.processed_frames} 帧 · 最佳有效帧 ${result.result.frame_index} · ${result.result.time_sec}秒`;
    state.lastReport=result;
  }catch(e){$('video-message').textContent='分析失败：'+e.message;
    $('video-result').innerHTML=`<div class="empty-result">${safe(e.message)}</div>`;
  }finally{btn.disabled=false;btn.textContent='开始逐帧分析 →';}
};
async function loadReports(){
  try{const data=await api('/api/reports');
    const list=$('history-list');
    list.innerHTML=data.items.length?data.items.map(x=>`<button class="history-item" data-report="${x.id}"><div><strong>${safe(x.pose.name)} · ${x.pose.view==='front'?'正位':'侧位'}</strong><small>${new Date(x.created_at).toLocaleString('zh-CN')} · ${x.source==='camera'?'实时检测':'上传视频'} · ${x.pose.level==='beginner'?'新手':'普通'}</small></div><span class="history-score">${num(x.result.score)}</span></button>`).join(''):'<div class="empty-result">暂无已归档的有效评估</div>';
    list.querySelectorAll('[data-report]').forEach(b=>b.onclick=()=>showReport(b.dataset.report));
  }catch(e){$('history-list').innerHTML=`<div class="empty-result">无法读取历史记录：${safe(e.message)}</div>`;}
}
async function showReport(id){
  try{const r=await api(`/api/reports/${encodeURIComponent(id)}`);state.lastReport=r;
    $('report-detail').innerHTML=`<div class="report-layout"><img src="${r.best_frame_url}" alt="算法选择的最佳有效帧"/><div><h3>${safe(r.pose.name)} · ${r.pose.view==='front'?'正位':'侧位'}</h3>${scoreHtml(r.result)}<div style="margin-top:14px"><button class="btn btn-neutral" id="export-report">导出报告 JSON ↓</button></div></div></div>`;
    $('export-report').onclick=()=>{const blob=new Blob([JSON.stringify(r,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=`VectorBody_${r.id}.json`;a.click();URL.revokeObjectURL(url);};
  }catch(e){$('report-detail').textContent=e.message;}
}
$('refresh-history').onclick=loadReports;
startup();