import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { isApiError, request } from "../../shared/api/client";
import { Banner, Button, Dialog, FormField, Input, Select, Textarea } from "../../ui";
import { editorKeys } from "../editor/api";

type Caps = { proxy_id: string | null; can_rotate_ip: boolean; reason?: string; affected_profile_ids?: string[]; shared?: boolean };
type Job = { id: string; state: string; proxy_id?: string; profile_id?: string | null; before_ip?: string | null; after_ip?: string | null; message?: string; affected_profile_ids?: string[]; shared?: boolean; requires_reconnect?: boolean; created_at?: number };
type Settings = { url: string; method: "GET" | "POST"; cooldown_seconds: number; shared_group: string; headers: Record<string,string>; body: object | null };
const labels: Record<string,string> = { queued:"等待处理",running:"正在切换并验证",verified:"已确认换 IP",unchanged:"IP 未变化",accepted_unverified:"结果尚未确认",failed:"切换失败" };
const enc = encodeURIComponent;

export function ProxyIpActions({ proxyId, profileId, configured, editable = false }: {
  proxyId?: string | null; profileId?: string; configured?: boolean; editable?: boolean;
}) {
  const cache = useQueryClient();
  const [caps,setCaps] = useState<Caps | null>(null);
  const [error,setError] = useState("");
  const [job,setJob] = useState<Job | null>(null);
  const [open,setOpen] = useState(false);
  const [busy,setBusy] = useState(false);
  const [settings,setSettings] = useState(false);
  const [history,setHistory] = useState<Job[] | null>(null);
  const id = proxyId || caps?.proxy_id;
  const intentKey = `proxy-rotation:${id ?? ""}:${profileId ?? ""}`;
  const [uncertain,setUncertain] = useState<string | null>(()=>sessionStorage.getItem(intentKey));
  const submitting = useRef(false);
  useEffect(()=>{setUncertain(sessionStorage.getItem(intentKey));},[intentKey]);
  useEffect(() => {
    let active=true;
    if(profileId) request<Caps>(`/api/profiles/${enc(profileId)}/proxy-capabilities`).then(v=>{if(active)setCaps(v);}).catch(e=>{if(active)setError(e.message);});
    return ()=>{active=false;};
  },[profileId]);
  useEffect(() => {
    if(!job || !["queued","running"].includes(job.state)) return;
    let active=true;
    const timer=setTimeout(()=>{
      request<Job>(`/api/proxy-rotations/${enc(job.id)}`).then(v=>{
        if(active){setJob(v);if(!["queued","running"].includes(v.state)){void cache.invalidateQueries({queryKey:["profiles"]});}}
      }).catch(e=>{if(active){setError(`无法读取结果：${e.message}。不要重新触发切换，请稍后查看记录。`);}});
    },2000);
    return ()=>{active=false;clearTimeout(timer);};
  },[job,cache]);
  const rotate = async () => {
    if(!id || submitting.current)return;
    submitting.current=true;
    setOpen(true);setBusy(true);setError("");setHistory(null);
    let requestId=uncertain;
    try {
      if(!requestId){
        const capability=await request<Caps>(`/api/proxy-presets/${enc(id)}/capabilities`);
        setCaps(capability);
        if(!capability.can_rotate_ip)throw new Error(capability.reason || "未配置切换链接");
        requestId=crypto.randomUUID();
        sessionStorage.setItem(intentKey,requestId);setUncertain(requestId);
      }
      const value=await request<Job>(`/api/proxy-presets/${enc(id)}/rotate`,{method:"POST",body:{request_id:requestId,profile_id:profileId ?? null}});
      setJob(value);
      sessionStorage.removeItem(intentKey);setUncertain(null);
    } catch(e){
      if(isApiError(e)&&e.kind==="http"&&e.status!==null&&e.status<500){sessionStorage.removeItem(intentKey);setUncertain(null);requestId=null;}
      setError(requestId?"请求结果未知。请查询本次请求，系统会复用原编号，避免重复切换。":e instanceof Error?e.message:String(e));
    }
    finally{setBusy(false);submitting.current=false;}
  };
  const refresh=async()=>{
    if(!job)return;
    setError("");
    try{setJob(await request<Job>(`/api/proxy-rotations/${enc(job.id)}`));}
    catch(e){setError(e instanceof Error?e.message:String(e));}
  };
  const records=async()=>{
    if(!id)return;
    setOpen(true);setError("");
    try{const rows=await request<Job[]>(`/api/proxy-presets/${enc(id)}/rotations`);setHistory(rows);if(rows[0]&&["queued","running"].includes(rows[0].state))setJob(rows[0]);}
    catch(e){setError(e instanceof Error?e.message:String(e));}
  };
  const available=profileId?Boolean(caps?.can_rotate_ip):Boolean(configured);
  const pending=busy || Boolean(job&&["queued","running"].includes(job.state));
  const otherRoute=job && job.proxy_id!==undefined && (job.proxy_id!==id || (job.profile_id ?? null)!==(profileId ?? null));
  return <div className="mt-2 flex flex-wrap items-center gap-1.5 font-sans text-xs" onClick={e=>e.stopPropagation()}>
    <Button size="sm" disabled={(!available && !uncertain) || pending} loading={pending} onClick={()=>void rotate()}>{uncertain?"查询本次请求":"一键切换 IP"}</Button>
    {editable && id && <Button size="sm" variant="ghost" onClick={()=>setSettings(true)}>切换链接</Button>}
    {id && <Button size="sm" variant="ghost" onClick={()=>void records()}>切换记录</Button>}
    {!available && <span className="text-fg-3">{caps?.reason || (error?"关联需要检查":"未配置 IP 切换")}</span>}
    {caps?.shared && <span className="text-fg-3">共享切换 · {caps.affected_profile_ids?.length ?? 0} 个环境</span>}
    {settings && id && <RotationSettings proxyId={id} onClose={()=>setSettings(false)} onSaved={()=>{setSettings(false);void cache.invalidateQueries({queryKey:editorKeys.proxyPresets});}} />}
    <Dialog open={open} onOpenChange={setOpen} title="IP 切换结果" description="通过当前实际连接路径验证。刷新链接返回成功不等于出口 IP 已改变。" footer={<Button onClick={()=>setOpen(false)}>关闭</Button>}>
      <div className="flex flex-col gap-3">
        {(caps?.shared || job?.shared) && <Banner tone="warning">共享切换，可能影响 {caps?.affected_profile_ids?.length ?? job?.affected_profile_ids?.length ?? 0} 个关联环境。</Banner>}
        {error && <Banner tone="danger">{error}</Banner>}
        {uncertain && <Button disabled={busy} onClick={()=>void rotate()}>查询本次请求</Button>}
        {job && <div role="status" className="rounded-md border border-border p-3">
          <p className="font-medium">{labels[job.state] || job.state}</p>
          {otherRoute && <p className="mt-2 text-xs text-fg-2">这是共享出口已有任务的结果，验证的是发起操作的另一条路径；当前环境请单独检测出口。</p>}
          <p className="mt-2 font-mono text-sm">{job.before_ip || "原 IP 未知"} → {job.after_ip || "等待新 IP"}</p>
          <p className="mt-2 text-xs text-fg-2">{job.message || "正在检测、请求供应商并等待新出口；不会自动重复请求切换链接。"}</p>
          {(caps?.shared || (job.affected_profile_ids?.length ?? 0)>1) && <p className="mt-2 text-xs text-fg-2">共享操作只验证发起操作的那条路径，其他环境请分别检查出口。</p>}
          {job.requires_reconnect && <p className="mt-2 text-xs text-fg-2">已有网页连接可能仍用旧 IP。需要时手动重新连接或重开环境；本次操作不会关闭浏览器。</p>}
          <Button size="sm" variant="ghost" onClick={()=>void refresh()}>刷新结果</Button>
        </div>}
        {history && <div className="flex flex-col gap-2">{history.length===0?<p>还没有切换记录</p>:history.map(row=><div key={row.id} className="rounded-md border border-border p-2 text-xs"><span>{labels[row.state] || row.state}</span><span className="ml-3 font-mono">{row.before_ip || "未知"} → {row.after_ip || "未知"}</span><p className="mt-1 text-fg-2">{row.created_at ? new Date(row.created_at*1000).toLocaleString():""}</p></div>)}</div>}
      </div>
    </Dialog>
  </div>;
}

function RotationSettings({proxyId,onClose,onSaved}:{proxyId:string;onClose:()=>void;onSaved:()=>void}) {
  const [form,setForm]=useState<Settings>({url:"",method:"GET",cooldown_seconds:60,shared_group:"",headers:{},body:null});
  const [headers,setHeaders]=useState("{}");const [body,setBody]=useState("");
  const [error,setError]=useState("");const [loading,setLoading]=useState(true);const [saving,setSaving]=useState(false);
  useEffect(()=>{let active=true;request<Settings>(`/api/proxy-presets/${enc(proxyId)}/rotation-settings`).then(v=>{if(active){setForm(v);setHeaders(JSON.stringify(v.headers));setBody(v.body?JSON.stringify(v.body):"");}}).catch(e=>{if(active)setError(e.message);}).finally(()=>{if(active)setLoading(false);});return()=>{active=false;};},[proxyId]);
  const save=async()=>{
    setSaving(true);setError("");
    try{
      const h=JSON.parse(headers || "{}");const b=body.trim()?JSON.parse(body):null;
      if(typeof h!=="object"||Array.isArray(h)||h===null||Object.values(h).some(v=>typeof v!=="string"))throw new Error("请求头应是字符串值的 JSON 对象");
      await request(`/api/proxy-presets/${enc(proxyId)}/rotation-settings`,{method:"PUT",body:{...form,url:form.url.trim(),headers:h,body:b}});onSaved();
    }catch(e){setError(e instanceof Error?e.message:String(e));}finally{setSaving(false);}
  };
  return <Dialog open onOpenChange={v=>{if(!v)onClose();}} title="配置一键换 IP" description="粘贴供应商提供的刷新链接。保存不会调用链接；清空链接保存可关闭此能力。" dismissible={!saving} footer={<><Button variant="ghost" disabled={saving} onClick={onClose}>取消</Button><Button disabled={loading} loading={saving} onClick={()=>void save()}>保存切换设置</Button></>}>
    <div className="flex flex-col gap-4">
      <FormField label="换 IP 链接"><Textarea value={form.url} autoComplete="off" spellCheck={false} rows={3} placeholder="粘贴供应商的 http(s):// 刷新链接" onChange={e=>setForm({...form,url:e.target.value})} /></FormField>
      <p className="text-xs text-fg-2">链接与认证信息加密保存。Agent 工具仅返回能力和操作结果，不返回原始链接。链接由 Manager 的管理网络发起，不通过正在切换的 SOCKS5。</p>
      <FormField label="冷却时间（秒）"><Input type="number" min={5} max={3600} value={form.cooldown_seconds} onChange={e=>setForm({...form,cooldown_seconds:Number(e.target.value)})} /></FormField>
      <FormField label="共享切换组（可选）" description="不同链接会切换同一批出口时，填写相同组名。相同链接自动共用锁和冷却时间。"><Input value={form.shared_group} maxLength={64} onChange={e=>setForm({...form,shared_group:e.target.value})} /></FormField>
      <details><summary className="cursor-pointer text-sm text-fg-2">高级请求设置</summary><div className="mt-3 flex flex-col gap-3">
        <FormField label="请求方式"><Select value={form.method} onChange={e=>setForm({...form,method:e.target.value as Settings["method"]})}><option>GET</option><option>POST</option></Select></FormField>
        <FormField label="请求头 JSON"><Textarea value={headers} onChange={e=>setHeaders(e.target.value)} autoComplete="off" spellCheck={false} /></FormField>
        <FormField label="请求体 JSON（可选）"><Textarea value={body} onChange={e=>setBody(e.target.value)} autoComplete="off" spellCheck={false} /></FormField>
      </div></details>
      {loading && <p>正在读取配置…</p>}{error && <Banner tone="danger">{error}</Banner>}
    </div>
  </Dialog>;
}
