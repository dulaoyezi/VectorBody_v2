/* VectorBody browser UI. Scores are populated exclusively from /api/*, never generated client-side. */
(() => {
  const $ = id => document.getElementById(id);
  const POSE_NAMES = {warrior1:'战士一式',warrior2:'战士二式',tadasana:'山式',sukhasana:'简易坐',uttanasana:'站立前屈式',cobra:'眼镜蛇式',balance:'平衡式',downward:'下犬式'};
  const LINKS = [[11,12],[11,13],[13,15],[12,14],[14,16],[11,23],[12,24],[23,24],[23,25],[25,27],[24,26],[26,28],[27,29],[28,30],[29,31],[30,32]];
  const state = {page:'home',stream:null,session:null,running:false,busy:false,timer:null,lastPhase:'',lastSpeak:0,lastScore:null,lastLive:null,firstResultSpoken:false,lastVideo:null,lastReport:null,voice:true,videoFile:null};
  const icon = id => `<svg><use href="#i-${id}"></use></svg>`;
  const esc = text => String(text ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  function notify(text){const t=$('toast');t.textContent=String(text);t.classList.add('show');clearTimeout(notify.timer);notify.timer=setTimeout(()=>t.classList.remove('show'),4200)}
  async function api(path, opts={}){const response=await fetch(path,opts);let body;try{body=await response.json()}catch{body={}}if(response.status===401){window.location.replace('/login');throw new Error('登录已过期，请重新登录。')}if(!response.ok)throw new Error(typeof body.detail==='string'?body.detail:`请求失败 HTTP ${response.status}`);return body}
  function navigate(page){if(!['home','live','video','reports'].includes(page))page='home';const saving=(page!=='live'&&state.running)?stopLive():null;state.page=page;document.querySelectorAll('.page').forEach(x=>x.classList.toggle('active',x.id===`page-${page}`));document.querySelectorAll('.nav-link').forEach(x=>x.classList.toggle('current',x.dataset.go===page));window.history.replaceState({},'',`#${page}`);window.scrollTo({top:0,behavior:'smooth'});if(page==='reports'){loadReports();if(saving)saving.finally(()=>{if(state.page==='reports')loadReports()})}}
  document.querySelectorAll('[data-go]').forEach(btn=>btn.addEventListener('click',e=>{e.preventDefault();navigate(btn.dataset.go)}));
  for(const id of ['live-pose','video-pose'])$(id).innerHTML=Object.entries(POSE_NAMES).map(([k,v])=>`<option value="${k}" ${k==='warrior2'?'selected':''}>${v}</option>`).join('');
  async function health(){try{await api('/api/health');$('server-dot').className='online-state online';$('server-dot').lastElementChild.textContent='引擎已就绪'}catch{$('server-dot').className='online-state offline';$('server-dot').lastElementChild.textContent='服务不可用'}}
  function pct(n){return Math.max(0,Math.min(100,Number(n)||0))}
  function renderMetric(prefix,result){const parent=$(`${prefix}-metrics`);if(!result){return}const values=[result.dimensions?.s1,result.dimensions?.s2,result.dimensions?.s3];parent.querySelectorAll('div').forEach((node,i)=>{node.querySelector('strong').textContent=Math.round(values[i]??0);node.querySelector('em').style.width=`${pct(values[i])}%`})}
  function tech(result){if(!result)return '尚无技术分析数据';const t=result.topology_ik||{},c=result.confidence||{},co=result.compensation||{};const items=[['拓扑节点',t.nodes],['拓扑骨骼边',t.edges],['DLS迭代次数',t.iterations],['DLS最终残差',t.final_residual],['最大骨长误差',`${t.max_length_error_pct??'—'}%`],['虚拟骨长可信',c.ready?(c.valid?'可信':'异常'):'建立中'],['虚拟骨长质量',`${c.quality_pct??0}%`],['灵活关节锁定风险',`${co.mobile_lock_pct??0}%`],['非灵活关节代偿风险',`${co.stiff_comp_pct??0}%`]];return items.map(([k,v])=>`<div class="tech-item"><span>${esc(k)}</span><strong>${esc(v??'—')}</strong></div>`).join('')}
  function resultUI(prefix,result){if(!result)return;const score=Math.round(result.score);$(prefix+'-score').textContent=score;$(prefix+'-grade').textContent=`${esc(result.grade)}级`;$(prefix+'-grade').className='status-tag';$(prefix+'-ring').style.borderColor=score>=85?'#829b74':score>=70?'#ddbb6d':'#bc8b69';$(prefix+'-headline').textContent=score>=85?'动作表现良好':score>=70?'存在改善空间':score>=55?'建议重点纠正':'请降低动作难度';$(prefix+'-advice').textContent=result.advice||'暂无纠正建议';renderMetric(prefix,result);$(prefix+'-tech').innerHTML=tech(result);mountAnatomy(prefix,$(prefix+'-view')?.value||'front');$(prefix+'-risk').textContent=`${Math.round(result.risk_pct)}% · ${result.risk_pct<15?'低':result.risk_pct<30?'中':'较高'}`}
  function drawSkeleton(canvas,video,points){const stage=canvas.parentElement;const w=stage.clientWidth,h=stage.clientHeight,dpr=Math.min(window.devicePixelRatio||1,2);canvas.width=Math.round(w*dpr);canvas.height=Math.round(h*dpr);const ctx=canvas.getContext('2d');ctx.scale(dpr,dpr);ctx.clearRect(0,0,w,h);if(!points||!video?.videoWidth)return;
    const srcW=video.videoWidth,srcH=video.videoHeight;const ratio=Math.min(w/srcW,h/srcH);const dw=srcW*ratio,dh=srcH*ratio;const left=(w-dw)/2,top=(h-dh)/2;
    const pt=id=>{const p=points[id];return [left+p[0]*dw,top+p[1]*dh,p[2]]};ctx.strokeStyle='#e4d096';ctx.lineWidth=2.4;ctx.lineCap='round';ctx.shadowColor='#172b1c';ctx.shadowBlur=2;
    LINKS.forEach(([a,b])=>{const pa=pt(a),pb=pt(b);if(pa[2]<.3||pb[2]<.3)return;ctx.beginPath();ctx.moveTo(pa[0],pa[1]);ctx.lineTo(pb[0],pb[1]);ctx.stroke()});ctx.shadowBlur=0;
    LINKS.flat().filter((id,i,a)=>a.indexOf(id)===i).forEach(id=>{const [x,y,v]=pt(id);if(v<.3)return;ctx.beginPath();ctx.arc(x,y,3.5,0,Math.PI*2);ctx.fillStyle='#f8e6b8';ctx.fill();ctx.strokeStyle='#5c7d51';ctx.lineWidth=1;ctx.stroke()});
  }
  // Original desktop images: front/back skeleton & muscle. Side view is a diagram only.
  const ISSUE_POSITIONS = {
    front:{neck:[[50,18]],shoulders:[[36,25],[64,25]],spine:[[50,45]],pelvis:[[50,64]],knees:[[41,78],[59,78]],ankles:[[41,93],[59,93]]},
    back:{neck:[[50,18]],shoulders:[[35,25],[65,25]],spine:[[50,45]],pelvis:[[50,64]],knees:[[40,80],[60,80]],ankles:[[40,93],[60,93]]}
  };
  const evidenceSource=source=>source==='report'?state.lastReport?.body:source==='live'?state.lastLive:state.lastVideo?.result;
  function anatomyWidget(source,initial='front',full=false){
    return `<div class="anatomy-widget ${full?'anatomy-full':'anatomy-compact'}" data-source="${esc(source)}" data-orientation="${initial==='back'?'back':'front'}" data-layer="skeleton">
      <div class="anatomy-switches"><div class="seg-switch" role="group" aria-label="人体观察视角">
        <button type="button" data-anatomy-view="front">正位</button><button type="button" data-anatomy-view="back">背面</button></div>
        <div class="seg-switch" role="group" aria-label="人体模型类型"><button type="button" data-anatomy-layer="skeleton">骨骼</button><button type="button" data-anatomy-layer="muscle">肌肉</button></div></div>
      <div class="anatomy-columns"><figure class="anatomy-figure"><div class="anatomy-image-shell"><img data-anatomy-image alt="人体解剖视图" loading="lazy"><div class="anatomy-pins"></div></div><figcaption data-anatomy-caption></figcaption></figure>
      <section class="anatomy-findings"><h4>重点关注部位</h4><div class="finding-cards"></div></section></div>
      <p class="anatomy-note">红/金色圆环对应低分项指标的身体区域，仅供教学辅助定位。单目视觉不能识别确切损伤；切换解剖视图不代表额外拍摄了该视角。</p></div>`;
  }
  function syncAnatomy(widget){
    if(!widget)return;
    const view=widget.dataset.orientation==='back'?'back':'front',layer=widget.dataset.layer||'skeleton';
    const url=`/api/anatomy/${view}/${layer}`;
    const img=widget.querySelector('[data-anatomy-image]');
    if(img.getAttribute('src')!==url)img.setAttribute('src',url);
    widget.querySelectorAll('[data-anatomy-view]').forEach(b=>b.classList.toggle('selected',b.dataset.anatomyView===view));
    widget.querySelectorAll('[data-anatomy-layer]').forEach(b=>{b.classList.toggle('selected',b.dataset.anatomyLayer===layer);b.disabled=false});
    widget.querySelector('[data-anatomy-caption]').textContent=(view==='back'?'背面':'正面')+(layer==='muscle'?'肌肉':'骨骼')+'示意图 · 标记位置为近似定位';
    const findings=(evidenceSource(widget.dataset.source)?.issue_regions||[]).filter(x=>x.region);
    const unique=[];
    findings.forEach(x=>{if(!unique.some(z=>z.region===x.region))unique.push(x)});
    const positions=ISSUE_POSITIONS[view]||ISSUE_POSITIONS.front;
    widget.querySelector('.anatomy-pins').innerHTML=unique.slice(0,4).flatMap(x=>(positions[x.region]||[]).map(([left,top])=>`<span class="anatomy-pin ${esc(x.severity)}" style="left:${left}%;top:${top}%" title="${esc(x.region_label)}：${esc(x.label)}"></span>`)).join('');
    widget.querySelector('.finding-cards').innerHTML=findings.length?findings.map((x,i)=>`<article class="finding-card"><span class="finding-rank ${esc(x.severity)}">${String(i+1).padStart(2,'0')}</span><div><strong>${esc(x.region_label)} · ${esc(x.label)}</strong><p>${esc(x.advice||'建议结合教师反馈调整动作。')}</p><small>分项评分 ${esc(x.score)}/100 · 视觉辅助提示</small></div></article>`).join(''):'<p class="no-findings">当前未发现明显低于85分的分项指标；不代表不存在身体问题，仍需教师复核。</p>';
  }
  function mountAnatomy(source,view){
    const host=$(`${source}-anatomy-host`);
    if(!host)return;
    if(!host.querySelector('.anatomy-widget'))host.innerHTML=anatomyWidget(source,view,false);
    syncAnatomy(host.querySelector('.anatomy-widget'));
  }
  document.addEventListener('click',e=>{
    const v=e.target.closest('[data-anatomy-view]'),layer=e.target.closest('[data-anatomy-layer]');
    if(v||layer){const widget=(v||layer).closest('.anatomy-widget');if(v)widget.dataset.orientation=v.dataset.anatomyView;if(layer)widget.dataset.layer=layer.dataset.anatomyLayer;syncAnatomy(widget)}
    const photo=e.target.closest('[data-photo-type]');if(photo)setReportPhoto(photo.dataset.photoType);
  });
  function setReportPhoto(kind){
    const media=state.lastReport?.body?.media||{},url=media[kind];
    const img=$('archive-photo'),empty=$('archive-photo-empty');if(!img||!empty)return;
    const ok=typeof url==='string'&&url.startsWith('/api/reports/');
    img.hidden=!ok;empty.hidden=ok;
    if(ok){img.src=url;img.alt=kind==='skeleton'?'骨架标注照片':'最佳帧原始照片'}
    else empty.textContent='历史报告未保存对应照片；使用新版评估后可自动归档。';
    document.querySelectorAll('[data-photo-type]').forEach(b=>b.classList.toggle('selected',b.dataset.photoType===kind));
  }
  function speech(text,force=false){if(!state.voice||!text||!('speechSynthesis'in window))return;const now=Date.now();if(!force&&now-state.lastSpeak<7000)return;state.lastSpeak=now;const say=new SpeechSynthesisUtterance(String(text));say.lang='zh-CN';say.rate=1.06;say.volume=.9;window.speechSynthesis.cancel();window.speechSynthesis.speak(say)}
  $('voice-toggle').addEventListener('click',()=>{state.voice=!state.voice;$('voice-toggle').querySelector('span').textContent=state.voice?'语音已开启':'语音已关闭';if(!state.voice&&window.speechSynthesis)window.speechSynthesis.cancel()});
  function phaseUI(phase){const idx=phase==='prepare'||phase==='framing'||phase==='centering'?0:phase==='stabilizing'?1:phase==='hold'?2:0;document.querySelectorAll('#phase-flow span').forEach((x,i)=>x.classList.toggle('on',i===idx));$('live-status').textContent=({prepare:'动作准备',framing:'调整入镜',centering:'调整位置',stabilizing:'稳定确认',hold:'正式评分'})[phase]||'进行中';$('live-status').className='status-tag'}
  async function startLive(){try{
    const studentName=$('live-student-name').value.trim();
    if(!studentName){$('live-student-name').focus();throw new Error('请先填写受评者姓名或匿名代号。')}
    if(!navigator.mediaDevices?.getUserMedia){throw new Error('请通过HTTPS或localhost访问，并允许浏览器使用摄像头。')}
    const stream=await navigator.mediaDevices.getUserMedia({video:{facingMode:'user',width:{ideal:960},height:{ideal:720}},audio:false});state.stream=stream;$('live-player').srcObject=stream;await $('live-player').play();
    const started=await api('/api/live/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pose:$('live-pose').value,view:$('live-view').value,level:$('live-level').value,student_name:studentName})});state.session=started.session_id;state.running=true;state.lastPhase='prepare';state.lastScore=null;state.lastLive=null;state.firstResultSpoken=false;state.lastSpeak=0;$('live-empty').hidden=true;$('live-empty').style.display='none';$('live-toggle').innerHTML=`${icon('check')}完成评估并存档`;$('live-hint').textContent=started.message;phaseUI('prepare');speech(started.voice,true);state.timer=setInterval(captureFrame,320);notify('摄像头已开启，动作稳定约2秒后自动开始评分。');
  }catch(e){notify(e.message);if(state.stream){state.stream.getTracks().forEach(t=>t.stop());state.stream=null}}}
  const grab=document.createElement('canvas');
  async function captureFrame(){if(!state.running||state.busy||!state.session)return;const video=$('live-player');if(!video.videoWidth)return;state.busy=true;try{grab.width=video.videoWidth;grab.height=video.videoHeight;grab.getContext('2d').drawImage(video,0,0,grab.width,grab.height);const blob=await new Promise(resolve=>grab.toBlob(resolve,'image/jpeg',.76));if(!blob)return;const form=new FormData();form.append('session_id',state.session);form.append('frame',blob,'camera.jpg');const data=await api('/api/live/frame',{method:'POST',body:form});$('live-hint').textContent=data.message;phaseUI(data.phase);drawSkeleton($('live-overlay'),video,data.landmarks);
    if(data.phase!==state.lastPhase){if(data.phase==='framing')speech('请确保全身入镜。');else if(data.phase==='centering')speech('请移动到检测区域中央。');else if(data.phase==='stabilizing')speech('请保持身体稳定。');else if(data.phase==='hold')speech(data.voice||'动作稳定，开始评估。',true);state.lastPhase=data.phase}
    if(data.result){const result=data.result;state.lastLive=result;resultUI('live',result);const now=Date.now();if(!state.firstResultSpoken){state.firstResultSpoken=true;setTimeout(()=>{if(state.running)speech(result.advice,true)},1600)}if(result.grade==='D'&&now-state.lastSpeak>12000)speech('当前代偿风险较高，建议降低动作幅度。');else if(state.lastScore!==null&&Math.abs(result.score-state.lastScore)>=4&&now-state.lastSpeak>15000)speech(result.advice);state.lastScore=result.score}
  }catch(e){notify(`实时评估暂时中断：${e.message}`);if(/会话失效/.test(e.message))stopLive(false)}finally{state.busy=false}}
  async function stopLive(archive=true){if(!state.running&&!state.stream)return;state.running=false;clearInterval(state.timer);if(state.stream){state.stream.getTracks().forEach(t=>t.stop());state.stream=null}$('live-player').srcObject=null;$('live-empty').hidden=false;$('live-empty').style.display='flex';$('live-toggle').innerHTML=`${icon('play')}开启摄像头评估`;$('live-status').textContent='已结束';$('live-status').className='status-tag neutral';$('live-hint').textContent='本次实时评估已结束';if(window.speechSynthesis)window.speechSynthesis.cancel();if(state.session){const session=state.session;state.session=null;try{const form=new FormData();form.append('session_id',session);form.append('archive',String(archive));const data=await api('/api/live/stop',{method:'POST',body:form});if(data.report_id)notify('实时评估结束，最佳评分已归档，可进入“评估报告”查看。');else notify('评估已结束。本次没有有效保持评分。')}catch(e){notify('结束成功，但归档请求失败：'+e.message)}}}
  $('live-toggle').addEventListener('click',()=>state.running?stopLive():startLive());
  function acceptFile(file){if(!file)return;state.videoFile=file;$('upload-info').textContent=`${file.name} · ${(file.size/1024/1024).toFixed(1)} MB`;$('upload-badge').textContent='视频已选择';$('uploaded-stage').hidden=false;$('file-drop').style.display='none';const player=$('uploaded-player');if(player.src?.startsWith('blob:'))URL.revokeObjectURL(player.src);player.src=URL.createObjectURL(file);$('show-video-report').disabled=true}
  $('video-file').addEventListener('change',e=>acceptFile(e.target.files?.[0]));const zone=$('file-drop');zone.addEventListener('dragover',e=>{e.preventDefault();zone.classList.add('drag')});zone.addEventListener('dragleave',()=>zone.classList.remove('drag'));zone.addEventListener('drop',e=>{e.preventDefault();zone.classList.remove('drag');acceptFile(e.dataTransfer?.files?.[0])});
  $('analyze-video').addEventListener('click',async()=>{if(!state.videoFile){notify('请先选择待分析视频。');return}const studentName=$('video-student-name').value.trim();if(!studentName){notify('请填写受评者姓名或匿名代号。');$('video-student-name').focus();return}const btn=$('analyze-video');btn.disabled=true;btn.textContent='正在执行逐帧视觉分析…';try{const fd=new FormData();fd.append('file',state.videoFile);fd.append('pose',$('video-pose').value);fd.append('view',$('video-view').value);fd.append('level',$('video-level').value);fd.append('student_name',studentName);const data=await api('/api/analyze-video',{method:'POST',body:fd});state.lastVideo=data;resultUI('video',data.result);$('best-time').textContent=`${data.video.best_time_sec}s`;$('valid-frames').textContent=data.video.evaluated_frames;$('show-video-report').disabled=false;$('video-risk').textContent=`${Math.round(data.result.risk_pct)}%`;const player=$('uploaded-player');player.addEventListener('seeked',()=>drawSkeleton($('uploaded-overlay'),player,data.result.landmarks),{once:true});player.currentTime=data.video.best_time_sec;notify('已使用VectorBody核心算法完成视频评估并归档。')}catch(e){notify(`分析失败：${e.message}`)}finally{btn.disabled=false;btn.innerHTML=`${icon('activity')}开始视频分析`}});
  $('show-video-report').addEventListener('click',async()=>{navigate('reports');if(state.lastVideo?.report_id)await openReport(state.lastVideo.report_id)});
  async function loadReports(){
    const box=$('reports-list');box.innerHTML='<div class="empty-message">正在加载记录…</div>';
    try{
      const filter=$('report-name-filter').value.trim();
      const data=await api('/api/reports'+(filter?'?student_name='+encodeURIComponent(filter):''));
      if(!data.reports?.length){box.innerHTML='<div class="empty-message">还没有记录。完成一次动作评估后，将自动保存在这里。</div>';return}
      box.innerHTML=data.reports.map(r=>`<div class="report-row">
        <div class="report-thumb">${r.has_photo?`<img alt="档案最佳帧" loading="lazy" src="/api/reports/${encodeURIComponent(r.id)}/photos/original">`:icon('image')}</div>
        <div class="report-name">${esc(r.student_name||'未填写姓名')} · ${esc(POSE_NAMES[r.pose]||r.pose)} · ${r.source==='live'?'实时评估':'视频评估'}<small>${esc(new Date(r.created_at).toLocaleString())} · ${r.view==='front'?'正位':'侧位'} · ${r.level==='beginner'?'新手':'普通'}</small></div>
        <strong class="report-score">${Math.round(r.score)}分</strong><button class="report-action" data-report="${esc(r.id)}">查看报告 →</button></div>`).join('');
      box.querySelectorAll('[data-report]').forEach(b=>b.addEventListener('click',()=>openReport(b.dataset.report)));
    }catch(e){box.innerHTML=`<div class="empty-message">加载失败：${esc(e.message)}</div>`}
  }
  $('refresh-reports').addEventListener('click',loadReports);
  $('report-search-button').addEventListener('click',loadReports);
  $('report-name-filter').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();loadReports()}});
  $('account-logout').addEventListener('click',async()=>{
    if(state.running){notify('请先结束实时评估，再退出。');return;}
    try{await fetch('/api/auth/logout',{method:'POST',credentials:'same-origin'});}
    finally{window.location.replace('/login');}
  });
  $('judge-qr-open').addEventListener('click',async()=>{
    const modal=$('judge-qr-modal'),hint=$('judge-qr-hint'),img=$('judge-qr-image'),link=$('judge-public-link');
    modal.hidden=false;img.hidden=true;link.hidden=true;hint.textContent='正在获取公网二维码…';
    try{
      const cfg=await api('/api/auth/config');
      if(!cfg.qr_enabled||!cfg.public_url){hint.textContent='尚未设置公网 HTTPS 地址。请先配置 VECTORBODY_PUBLIC_URL 并重启服务。';return;}
      img.onload=()=>{hint.textContent='使用手机扫码，进入同一个测试账号登录页面。';};
      img.onerror=()=>{hint.textContent='二维码加载失败，请检查网络与服务配置。';};
      img.src='/api/auth/qr';
      img.hidden=false;
      link.href=cfg.public_url+'/';link.textContent=cfg.public_url;link.hidden=false;
    }catch(e){hint.textContent='二维码加载失败：'+e.message;}
  });
  $('judge-qr-close').addEventListener('click',()=>{$('judge-qr-modal').hidden=true;});
  $('judge-qr-modal').addEventListener('click',e=>{if(e.target===$('judge-qr-modal'))$('judge-qr-modal').hidden=true;});
  window.addEventListener('keydown',e=>{if(e.key==='Escape')$('judge-qr-modal').hidden=true;});
  async function openReport(id){
    try{
      const data=await api('/api/reports/'+encodeURIComponent(id));state.lastReport=data;const r=data.body;
      const rows=Object.entries(r.metrics||{}).map(([key,item])=>`<tr><td>${esc(key)}</td><td>${esc(item.value)}</td><td>${esc(item.score)}</td><td>${esc(item.stability)}</td><td>${esc(item.weight)}</td></tr>`).join('');
      const meta=`受评者 ${esc(data.student_name||r.student_name||'未填写姓名')} · ${esc(new Date(data.created_at).toLocaleString())} · ${data.view==='front'?'正位采集':'侧位采集'} · ${data.level==='beginner'?'新手':'普通'} · ${esc(data.id)}`;
      $('report-content').innerHTML=`<div class="detail-body">
        <div class="detail-head"><div><span class="report-kicker">MOVEMENT EVIDENCE REPORT</span>
          <h3>${esc(data.student_name||r.student_name||'未填写姓名')} · ${esc(POSE_NAMES[data.pose]||data.pose)} · ${data.source==='live'?'实时评估':'视频评估'}</h3><p>${meta}</p></div><strong>${Math.round(r.score)} <small>/ 100</small></strong></div>
        <div class="report-evidence">
          <article class="evidence-card photo-evidence"><div class="evidence-head"><div>${icon('image')}<strong>最佳评分帧 · 档案照片</strong></div><div class="seg-switch"><button type="button" data-photo-type="original" class="selected">原始照片</button><button type="button" data-photo-type="skeleton">骨架标注</button></div></div>
             <figure class="archive-photo"><img id="archive-photo" alt="最佳评分帧" loading="eager"><div class="archive-photo-empty" id="archive-photo-empty" hidden>没有归档照片</div></figure>
             <div class="photo-caption">${r.time_sec!=null?'最佳时刻 '+esc(r.time_sec)+'s · ':''}来自本次评分最高的有效帧；保存原始照片与骨架标注照片，不保留完整视频。</div></article>
          <article class="evidence-card anatomy-evidence"><div class="evidence-head"><div>${icon('target')}<strong>人体骨骼 / 肌肉 · 部位定位</strong></div></div>${anatomyWidget('report',data.view,true)}</article>
        </div>
        <div class="report-dims"><div><strong>${esc(r.dimensions?.s1??'—')}</strong><span>S1 关节—姿态符合度</span></div><div><strong>${esc(r.dimensions?.s2??'—')}</strong><span>S2 拓扑稳定与代偿控制</span></div><div><strong>${esc(r.dimensions?.s3??'—')}</strong><span>S3 支撑—代偿视觉代理</span></div></div>
        <p class="detail-advice"><b>可解释纠正与反馈：</b>${esc(r.advice||'暂无')}<br>总体代偿风险：${esc(r.risk_pct)}%　· 等级：${esc(r.grade)}</p>
        <details class="tech-details" open><summary>结构优化与骨长依据 ${icon('chevron')}</summary><div>${tech(r)}</div></details>
        <h4 class="report-subheading">分项指标与评分依据</h4><div class="report-table-wrap"><table class="metric-table"><thead><tr><th>指标</th><th>观测值</th><th>评分</th><th>稳定性</th><th>权重</th></tr></thead><tbody>${rows}</tbody></table></div>
        <p class="subtle-caption report-privacy">照片是个人运动影像，保存在当前服务器，应经授权访问和管理。系统仅用于动作学习与教学辅助，不用于医疗诊断；切换正面或背面解剖图不代表额外采集了对应视角。</p>
      </div>`;
      $('report-detail').hidden=false;syncAnatomy($('report-content').querySelector('.anatomy-widget'));setReportPhoto('original');
      $('report-detail').scrollIntoView({behavior:'smooth',block:'start'});
    }catch(e){notify('无法打开报告：'+e.message)}
  }
  $('print-report').addEventListener('click',()=>{if(!state.lastReport){notify('请先打开一份评估报告。');return;}document.querySelectorAll('#report-detail details').forEach(x=>x.open=true);const name=(state.lastReport.student_name||'未填写姓名').replace(/[\\/:*?"<>|]/g,'_');document.title='VectorBody_评估报告_'+name;window.print();});
  window.addEventListener('afterprint',()=>{document.title='VectorBody — 科学地理解每一次动作';});
  window.addEventListener('beforeunload',()=>{if(state.stream)state.stream.getTracks().forEach(t=>t.stop())});
  window.addEventListener('resize',()=>{if(state.running&&state.lastLive)drawSkeleton($('live-overlay'),$('live-player'),state.lastLive.landmarks)});
  health();navigate((location.hash||'#home').slice(1));
})();