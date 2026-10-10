(() => {
  const $ = id => document.getElementById(id);
  async function responseJson(res) {
    try { return await res.json(); }
    catch { return {}; }
  }
  async function init() {
    try {
      const me = await fetch('/api/auth/me',{credentials:'same-origin',cache:'no-store'});
      if (me.ok) {location.replace('/');return;}
      const res = await fetch('/api/auth/config',{cache:'no-store'});
      if (!res.ok) throw new Error('无法读取登录配置');
      const config = await responseJson(res);
      $('email').value = config.email || 'huanjiaceshi@163.com';
      if (config.qr_enabled) {
        $('qr-image').src = '/api/auth/qr';
        $('qr-box').hidden = false;
      }
    } catch (e) { $('error').textContent = '登录服务暂不可用：' + e.message; }
  }
  $('login-form').addEventListener('submit',async event => {
    event.preventDefault();
    const button=$('login-button');
    button.disabled=true; $('error').textContent='';
    try {
      const res=await fetch('/api/auth/login',{
        method:'POST',headers:{'Content-Type':'application/json'},
        credentials:'same-origin',cache:'no-store',
        body:JSON.stringify({email:$('email').value,password:$('password').value})
      });
      const data=await responseJson(res);
      if (!res.ok) throw new Error(data.detail || '登录失败，请稍后重试');
      $('password').value='';
      location.replace('/');
    } catch(e) { $('error').textContent=e.message; }
    finally { button.disabled=false; }
  });
  init();
})();
