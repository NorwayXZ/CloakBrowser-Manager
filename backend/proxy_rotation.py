"""Supplier refresh links are actions; HTTP success alone never proves an IP change."""
from __future__ import annotations

import asyncio
import hashlib
import http.client
import ipaddress
import json
import socket
import ssl
import time
import threading
import uuid
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import certifi

from . import database as db

VERIFY_SECONDS = 45
POLL_SECONDS = 3
TASKS: set[asyncio.Task] = set()


class RotationError(ValueError):
    """A controlled message that is safe to return without supplier credentials."""


def public_address(value: str) -> bool:
    address = ipaddress.ip_address(value)
    if isinstance(address,ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return address.is_global


def validate_settings(config: dict) -> None:
    url = config.get("url", "")
    if not url: return
    u = urlsplit(url)
    if u.scheme not in {"http", "https"} or not u.hostname or u.username is not None or u.fragment:
        raise ValueError("切换链接必须是 HTTP(S) 地址，不支持 URL 账号密码或片段")
    try: port = u.port
    except ValueError: raise ValueError("切换链接端口无效") from None
    if port is not None and not 1 <= port <= 65535: raise ValueError("切换链接端口无效")
    if u.hostname.lower() == "localhost": raise ValueError("切换链接不能指向本机或内网地址")
    try: address = ipaddress.ip_address(u.hostname)
    except ValueError: address = None
    if address is not None and not public_address(u.hostname): raise ValueError("切换链接不能指向本机或内网地址")
    if config.get("method", "GET") not in {"GET", "POST"}: raise ValueError("只支持 GET 和 POST")
    for name, value in config.get("headers", {}).items():
        if name.lower() in {"host", "content-length", "connection", "transfer-encoding"} or any(c in name+value for c in "\r\n"):
            raise ValueError("请求头格式无效或包含不允许的请求头")
    if len(json.dumps(config.get("body"))) > 16384: raise ValueError("请求体过大")
    if not 5 <= int(config.get("cooldown_seconds",60)) <= 3600: raise ValueError("冷却时间需要 5 到 3600 秒")


def rotation_key(config: dict) -> str:
    if config.get("shared_group"):
        value = "group:"+config["shared_group"]
    else:
        u = urlsplit(config["url"])
        host = u.hostname.lower()
        if ':' in host: host = '['+host+']'
        port = u.port
        authority = host + (f':{port}' if port and port != (443 if u.scheme=='https' else 80) else '')
        value = urlunsplit((u.scheme.lower(),authority,u.path or '/',urlencode(sorted(parse_qsl(u.query,keep_blank_values=True))),""))
    return hashlib.sha256(value.encode()).hexdigest()


def send_refresh(config: dict) -> None:
    """Resolve and pin a public address. Never follow a redirect or expose response text."""
    validate_settings(config)
    started = time.monotonic()
    u = urlsplit(config["url"])
    port = u.port or (443 if u.scheme == "https" else 80)
    addresses = socket.getaddrinfo(u.hostname,port,type=socket.SOCK_STREAM)
    if not addresses or any(not public_address(a[4][0]) for a in addresses):
        raise RotationError("刷新地址解析到不可访问的内网地址")
    remaining = 15-(time.monotonic()-started)
    if remaining <= 0: raise TimeoutError()
    # One attempt only: a refresh request must not be automatically replayed.
    raw = socket.create_connection((addresses[0][4][0],port),timeout=remaining)
    conn = http.client.HTTPConnection(u.hostname,port,timeout=remaining)
    timer = None
    try:
        conn.sock = ssl.create_default_context(cafile=certifi.where()).wrap_socket(raw,server_hostname=u.hostname) if u.scheme == "https" else raw
        remaining = 15-(time.monotonic()-started)
        if remaining <= 0: raise TimeoutError()
        stream = conn.sock
        stream.settimeout(remaining)
        def expire():
            try: stream.shutdown(socket.SHUT_RDWR)
            except OSError: pass
            stream.close()
        timer = threading.Timer(remaining,expire)
        timer.daemon = True
        timer.start()
        headers = {**config.get("headers", {}), "Connection": "close"}
        body = json.dumps(config["body"]).encode() if config.get("body") is not None else None
        if body is not None: headers.setdefault("Content-Type","application/json")
        conn.request(config.get("method","GET"),(u.path or '/')+('?' + u.query if u.query else ''),body=body,headers=headers)
        response = conn.getresponse()
        data = response.read(8192)
        if not 200 <= response.status < 300: raise RotationError(f"供应商刷新接口返回 HTTP {response.status}；没有自动重试或跟随跳转")
        try: decoded = json.loads(data)
        except (ValueError,UnicodeError): decoded = None
        if isinstance(decoded,dict) and decoded.get("success") is False: raise RotationError("供应商返回切换失败，请核对切换配置与冷却时间")
    finally:
        if timer: timer.cancel()
        conn.close()
        raw.close()


def capabilities(proxy_id: str, profile_id: str | None = None) -> dict:
    preset = db.get_proxy_preset(proxy_id)
    if not preset: raise ValueError("代理不存在")
    config = db.get_proxy_rotation_settings(proxy_id)
    valid = preset["proxy"].lower().startswith("socks5://")
    affected = []
    group = rotation_key(config) if config else None
    ids = {proxy_id}
    cooldown = config.get("cooldown_seconds",60) if config else 60
    presets = db.list_proxy_presets()
    by_id = {p["id"]: p for p in presets}
    if config:
        for p in presets:
            c = db.get_proxy_rotation_settings(p["id"])
            if c and rotation_key(c) == group:
                ids.add(p["id"])
                cooldown = max(cooldown,c.get("cooldown_seconds",60))
    for p in db.list_profiles():
        if p.get("proxy_id"):
            bound = p["proxy_id"] if by_id.get(p["proxy_id"],{}).get("proxy") == p.get("proxy") else None
        else:
            matches = [x["id"] for x in presets if x["proxy"] == p.get("proxy")]
            bound = matches[0] if len(matches)==1 else None
        if bound in ids: affected.append(p["id"])
    reason = None
    if profile_id:
        p = db.get_profile(profile_id)
        if not p or db.resolve_proxy_binding(p.get("proxy"),p.get("proxy_id")) != proxy_id:
            raise ValueError("环境与代理关联不一致，请重新选择代理")
    if not config: reason = "未配置切换链接"
    elif not valid: reason = "目前仅 SOCKS5 支持供应商 IP 切换"
    return {"proxy_id":proxy_id,"name":preset["name"],"can_rotate_ip":bool(config) and valid,
        "capabilities":{"check_exit_ip":True,"rotate_ip":bool(config) and valid},
        "rotate_tool":"rotate_proxy_ip","check_tool":"check_proxy_exit_ip","cooldown_seconds":cooldown,
        "affected_profile_ids":affected,"shared":len(ids)>1 or len(affected)>1 or bool(config and config.get("shared_group")),"reason":reason}


def profile_capabilities(profile_id: str) -> dict:
    p = db.get_profile(profile_id)
    if not p: raise ValueError("环境不存在")
    proxy_id = db.resolve_proxy_binding(p.get("proxy"),p.get("proxy_id"))
    if not proxy_id: return {"can_rotate_ip":False,"reason":"环境尚未关联唯一的已保存代理，请重新选择代理","proxy_id":None}
    return capabilities(proxy_id,profile_id)


def reserve(proxy_id: str, request_id: str, profile_id: str | None = None) -> tuple[dict,bool]:
    def find_request(conn):
        return conn.execute("SELECT id,profile_id FROM proxy_rotation_jobs WHERE proxy_id=? AND request_id=? UNION ALL SELECT job_id AS id,profile_id FROM proxy_rotation_requests WHERE proxy_id=? AND request_id=? LIMIT 1",(proxy_id,request_id,proxy_id,request_id)).fetchone()
    with db.get_db() as conn:
        existing = find_request(conn)
    if existing:
        if existing["profile_id"] != profile_id: raise ValueError("同一个请求编号已用于其他环境，请检查操作意图")
        return db.get_rotation_job(existing["id"]),False
    caps = capabilities(proxy_id,profile_id)
    if not caps["can_rotate_ip"]: raise ValueError(caps["reason"])
    config = db.get_proxy_rotation_settings(proxy_id)
    key = rotation_key(config)
    cooldown = caps["cooldown_seconds"]
    now = time.time()
    with db.get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute("SELECT rotation_config FROM proxy_presets WHERE id=?",(proxy_id,)).fetchone()
        from .secrets_crypto import decrypt_json
        if not current or decrypt_json(current[0]) != config: raise ValueError("切换配置已改变，请重新查看代理能力")
        existing = find_request(conn)
        if existing and existing["profile_id"] != profile_id: raise ValueError("同一个请求编号已用于其他环境，请检查操作意图")
        active = conn.execute("SELECT id FROM proxy_rotation_jobs WHERE rotation_key=? AND state IN ('queued','running')",(key,)).fetchone()
        if existing or active:
            job_id = (existing or active)[0]
            if not existing:
                conn.execute("INSERT INTO proxy_rotation_requests (proxy_id,request_id,profile_id,job_id) VALUES (?,?,?,?)",(proxy_id,request_id,profile_id,job_id))
            conn.commit()
            return db.get_rotation_job(job_id),False
        past = conn.execute("SELECT attempted_at,result_json FROM proxy_rotation_jobs WHERE rotation_key=? AND attempted_at IS NOT NULL",(key,)).fetchall()
        next_at = max([max(p["attempted_at"]+cooldown,json.loads(p["result_json"]).get("next_allowed_at",0)) for p in past],default=0)
        if now < next_at: raise ValueError(f"冷却中，请在 {max(1,int(next_at-now))} 秒后再试")
        job_id = str(uuid.uuid4())
        conn.execute("INSERT INTO proxy_rotation_jobs (id,proxy_id,profile_id,rotation_key,request_id,state,created_at,result_json) VALUES (?,?,?,?,?,'queued',?,?)",
            (job_id,proxy_id,profile_id,key,request_id,now,json.dumps({"affected_profile_ids":caps["affected_profile_ids"],"shared":caps["shared"],"cooldown_seconds":cooldown})))
        conn.commit()
    return db.get_rotation_job(job_id),True


async def execute(job_id: str, probe) -> None:
    job = db.get_rotation_job(job_id)
    if not job: return
    config = db.get_proxy_rotation_settings(job["proxy_id"])
    preset = db.get_proxy_preset(job["proxy_id"])
    profile = db.get_profile(job["profile_id"]) if job["profile_id"] else None
    if not config or not preset or (job["profile_id"] and not profile):
        db.finish_rotation_job(job_id,"failed",{"message":"关联代理、环境或切换配置已不存在；未发送切换请求","do_not_retry":True})
        return
    route = {"proxy":preset["proxy"],"proxy_connection_mode":profile.get("proxy_connection_mode","direct") if profile else "direct",
        "relay_id":profile.get("relay_id") if profile else None}
    result = {"before_ip":None,"after_ip":None,"request_responded":False,
        "affected_profile_ids":job.get("affected_profile_ids",[]),"shared":job.get("shared",False),"requires_reconnect":True,"do_not_retry":True}
    db.finish_rotation_job(job_id,"running",result)
    def unchanged_route():
        current = db.get_proxy_preset(job["proxy_id"])
        if not current or current["proxy"] != route["proxy"]: raise RotationError("代理配置已改变，请重新检查当前代理")
        if job["profile_id"]:
            p = db.get_profile(job["profile_id"])
            if not p or any(p.get(k,"direct" if k=="proxy_connection_mode" else None)!=v for k,v in route.items()):
                raise RotationError("环境连接路径已改变，本次结果不能确认当前环境的出口")
    async def measure():
        try:
            response = await asyncio.wait_for(probe(route),20)
            return response.ip
        except Exception: return None
    try:
        result["before_ip"] = await measure()
        unchanged_route()
        if job["profile_id"]: capabilities(job["proxy_id"],job["profile_id"])
        with db.get_db() as conn:
            conn.execute("UPDATE proxy_rotation_jobs SET attempted_at=? WHERE id=?",(time.time(),job_id));conn.commit()
        result["next_allowed_at"] = time.time()+job.get("cooldown_seconds",config.get("cooldown_seconds",60))
        db.finish_rotation_job(job_id,"running",result)
        await asyncio.wait_for(asyncio.to_thread(send_refresh,config),20)
        result["request_responded"] = True
        db.finish_rotation_job(job_id,"running",result)
        deadline = time.monotonic()+VERIFY_SECONDS
        while True:
            after = await measure()
            result["after_ip"] = after
            before = result["before_ip"]
            if before and after and ipaddress.ip_address(before).version==ipaddress.ip_address(after).version and before != after:
                unchanged_route()
                if job["profile_id"]: capabilities(job["proxy_id"],job["profile_id"])
                with db.get_db() as conn:
                    for affected in result["affected_profile_ids"]:
                        conn.execute("UPDATE profiles SET proxy_geo_json=NULL WHERE id=?",(affected,))
                    conn.commit()
                db.finish_rotation_job(job_id,"verified",{**result,"message":"已确认出口 IP 改变；已有网页连接可能仍需重新连接"})
                return
            if time.monotonic() >= deadline: break
            await asyncio.sleep(POLL_SECONDS)
        state = "unchanged" if result["before_ip"] and result["after_ip"]==result["before_ip"] else "accepted_unverified"
        db.finish_rotation_job(job_id,state,{**result,"message":"切换链接已响应，但尚未确认 IP 改变。请勿连续重复切换"})
    except asyncio.CancelledError:
        db.finish_rotation_job(job_id,"accepted_unverified",{**result,"message":"检查被中断，切换结果未知；不会自动重试刷新链接"})
        raise
    except Exception as exc:
        # Never include exception strings from HTTP libraries: they can contain secret URLs.
        message = str(exc) if isinstance(exc,RotationError) else "切换请求或验证失败，请核对配置和供应商状态；未自动重试"
        uncertain = result["request_responded"] or isinstance(exc,(TimeoutError,OSError))
        db.finish_rotation_job(job_id,"accepted_unverified" if uncertain else "failed",{**result,"message":message})


def recover() -> None:
    with db.get_db() as conn:
        rows = conn.execute("SELECT id,result_json FROM proxy_rotation_jobs WHERE state IN ('queued','running')").fetchall()
        for row in rows:
            result = {**json.loads(row["result_json"]),"message":"程序重启中断了检查，结果未知；不会自动重新调用切换链接","do_not_retry":True,"requires_reconnect":True}
            conn.execute("UPDATE proxy_rotation_jobs SET state='accepted_unverified',result_json=? WHERE id=?",(json.dumps(result),row["id"]))
        conn.commit()
