"""Email OTP and one-time QR pairing for VectorBody Web. Configure SMTP for delivery."""
import hashlib,hmac,os,secrets,sqlite3,time
from pathlib import Path
from urllib.parse import urlencode
from fastapi import APIRouter,Request,HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel,EmailStr
from email.message import EmailMessage
import smtplib

DB=Path(os.getenv("VECTORBODY_DATA_DIR",str(Path(__file__).parent/"web_data")))/"accounts.sqlite3"
DB.parent.mkdir(parents=True,exist_ok=True)
router=APIRouter(prefix="/api/account")
def conn():
    c=sqlite3.connect(DB,timeout=10)
    c.row_factory=sqlite3.Row
    return c
with conn() as c:
    c.executescript("""CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,email TEXT UNIQUE NOT NULL,created INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS otps(email TEXT PRIMARY KEY,hash TEXT NOT NULL,expires INTEGER NOT NULL,attempts INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS sessions(hash TEXT PRIMARY KEY,user_id TEXT NOT NULL,expires INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS pairings(hash TEXT PRIMARY KEY,user_id TEXT NOT NULL,expires INTEGER NOT NULL,used INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS report_owners(report_id TEXT PRIMARY KEY,user_id TEXT NOT NULL);""")
SECRET=os.getenv("VECTORBODY_AUTH_SECRET","")
if len(SECRET)<32: raise RuntimeError("Set VECTORBODY_AUTH_SECRET to a random 32+ character secret")
def digest(s):return hmac.new(SECRET.encode(),s.encode(),hashlib.sha256).hexdigest()
def user(req:Request):
    token=req.cookies.get("vb_session","")
    with conn() as c:
        row=c.execute("SELECT user_id FROM sessions WHERE hash=? AND expires>?",(digest(token),int(time.time()))).fetchone() if token else None
    if not row:raise HTTPException(401,"请先完成邮箱登录")
    return row["user_id"]
class Email(BaseModel):email:EmailStr
class Verify(Email):code:str
class Pair(BaseModel):token:str
@router.post("/otp")
def otp(data:Email,request:Request):
    email=data.email.lower()
    now=int(time.time())
    with conn() as c:
        old=c.execute("SELECT expires FROM otps WHERE email=?",(email,)).fetchone()
        if old and old["expires"]>now+240:raise HTTPException(429,"请稍后重新发送验证码")
    code=f"{secrets.randbelow(1000000):06d}"
    host=os.getenv("VECTORBODY_SMTP_HOST")
    if not host:raise HTTPException(503,"尚未配置邮件服务器")
    msg=EmailMessage();msg["Subject"]="VectorBody 邮箱验证码";msg["From"]=os.environ["VECTORBODY_SMTP_FROM"];msg["To"]=email
    msg.set_content(f"验证码：{code}。5分钟内有效，请勿转发。")
    try:
        with smtplib.SMTP(host,int(os.getenv("VECTORBODY_SMTP_PORT","587")),timeout=12) as smtp:
            smtp.starttls();smtp.login(os.environ["VECTORBODY_SMTP_USER"],os.environ["VECTORBODY_SMTP_PASSWORD"])
            smtp.send_message(msg)
    except Exception:raise HTTPException(503,"验证码发送失败")
    with conn() as c:c.execute("INSERT OR REPLACE INTO otps VALUES(?,?,?,0)",(email,digest(email+":"+code),now+300))
    return {"ok":True}
@router.post("/verify")
def verify(data:Verify):
    email=data.email.lower();now=int(time.time())
    with conn() as c:
        row=c.execute("SELECT * FROM otps WHERE email=?",(email,)).fetchone()
        if not row or row["expires"]<now or row["attempts"]>=5:raise HTTPException(400,"验证码无效或已过期")
        c.execute("UPDATE otps SET attempts=attempts+1 WHERE email=?",(email,))
        if not hmac.compare_digest(row["hash"],digest(email+":"+data.code)):raise HTTPException(400,"验证码错误")
        c.execute("DELETE FROM otps WHERE email=?",(email,))
        uid=c.execute("SELECT id FROM users WHERE email=?",(email,)).fetchone()
        if not uid:
            uid=secrets.token_hex(16);c.execute("INSERT INTO users VALUES(?,?,?)",(uid,email,now))
        else:uid=uid["id"]
        token=secrets.token_urlsafe(32)
        c.execute("INSERT INTO sessions VALUES(?,?,?)",(digest(token),uid,now+604800))
    res=JSONResponse({"ok":True,"email":email})
    res.set_cookie("vb_session",token,max_age=604800,httponly=True,secure=os.getenv("VECTORBODY_COOKIE_SECURE","true").lower()=="true",samesite="lax")
    return res
@router.get("/me")
def me(request:Request):
    uid=user(request)
    with conn() as c:email=c.execute("SELECT email FROM users WHERE id=?",(uid,)).fetchone()["email"]
    return {"id":uid,"email":email}
@router.post("/pair/new")
def new_pair(request:Request):
    uid=user(request);token=secrets.token_urlsafe(32)
    with conn() as c:c.execute("INSERT INTO pairings(hash,user_id,expires) VALUES(?,?,?)",(digest(token),uid,int(time.time())+120))
    return {"token":token,"expires_in":120}
@router.post("/pair/confirm")
def confirm(data:Pair,request:Request):
    uid=user(request);now=int(time.time())
    with conn() as c:
        row=c.execute("SELECT user_id FROM pairings WHERE hash=? AND expires>? AND used=0",(digest(data.token),now)).fetchone()
        if not row:raise HTTPException(400,"二维码无效或已过期")
        if row["user_id"]!=uid:raise HTTPException(403,"二维码所属邮箱账号不一致")
        c.execute("UPDATE pairings SET used=1 WHERE hash=? AND used=0",(digest(data.token),))
    return {"ok":True,"bound":True}
@router.post("/logout")
def logout(request:Request):
    token=request.cookies.get("vb_session","")
    with conn() as c:c.execute("DELETE FROM sessions WHERE hash=?",(digest(token),))
    res=JSONResponse({"ok":True});res.delete_cookie("vb_session");return res
