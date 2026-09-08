import { useCallback, useEffect, useState } from "react";
import {
  ShieldCheck,
  FolderOpen,
  Layers3,
  Settings2,
  ArrowUpRight,
  ArrowRight,
  Plus,
  Check,
  LockKeyhole,
  ChevronRight,
  X,
  Search,
  Clock3,
  Loader2,
  LogOut,
  PanelLeftClose,
  CircleHelp,
  Users,
  Moon,
  Sun,
} from "lucide-react";
import { Dialog, Empty, StageStepper, Tag } from "./components/ui";
import { BenchmarkCenter, LegalPackCenter, ProviderCenter, UserCenter } from "./pages/GovernanceCenters";
import { RiskWorkspace } from "./workspaces/RiskWorkspace";
import { RestorationWorkspace } from "./workspaces/RestorationWorkspace";
import { SourceViewer } from "./workspaces/SourceViewer";
import { FactWorkspace } from "./workspaces/FactWorkspace";
import { DisclosureWorkspace } from "./workspaces/DisclosureWorkspace";
import { ContextRail } from "./workspaces/ContextRail";

const PALETTES = [
  ["forest", "林绿"],
  ["ink", "墨青"],
  ["dusk", "缃褐"],
] as const;
type Palette = (typeof PALETTES)[number][0];

function storedPalette(): Palette {
  const value = localStorage.getItem("lex_palette");
  return value === "ink" || value === "dusk" || value === "forest" ? value : "forest";
}

function AppearanceSwitch({
  theme,
  palette,
  setTheme,
  setPalette,
}: {
  theme: string;
  palette: Palette;
  setTheme: (theme: string) => void;
  setPalette: (palette: Palette) => void;
}) {
  return (
    <>
      <select
        className="palette-select"
        aria-label="配色"
        value={palette}
        onChange={(event) => setPalette(event.target.value as Palette)}
      >
        {PALETTES.map(([value, label]) => (
          <option key={value} value={value}>
            {label}
          </option>
        ))}
      </select>
      <button className="icon-button" aria-label={theme==="light"?"切换深色主题":"切换浅色主题"}
        onClick={()=>setTheme(theme==="light"?"dark":"light")}>{theme==="light"?<Moon size={15}/>:<Sun size={15}/>}</button>
    </>
  );
}

type Obj = Record<string, any>;
const labels: Record<string, string> = {
  entity: "主体",
  relation: "关系",
  event: "事件",
  date: "日期",
  amount: "金额",
  evidence: "证据",
  fact_summary: "事实摘要",
  timeline: "时间线",
  evidence_inventory: "证据整理",
  issue_extraction: "争点提取",
  unused_fact: "未使用事实",
  gap: "云端缺口",
  feedback_issue: "回写问题",
  keep: "保留",
  pseudonymize: "假名化",
  generalize: "泛化",
  delete: "删除",
  required: "必要",
  conditional: "条件必要",
  unnecessary: "不必要",
  uncertain: "不确定",
  available: "可用",
  unconfigured: "未配置",
  unimplemented: "未实现",
  failed: "执行失败",
  draft: "待编辑",
  review: "待审批",
  approved: "已批准",
  blocked: "已阻断",
  stale: "依据已变化",
  queued: "待发送",
  sending: "发送中",
  complete: "已完成",
  unknown: "结果不明",
  stopped: "已停止",
  pending: "排队中",
  running: "运行中",
  cancelled: "已取消",
  identity: "身份恢复",
  candidate_set: "候选集合缩小",
  sensitive_inference: "敏感事实推断",
  cross_round: "跨轮关联",
};
const attackLabels: Record<string, string> = { resisted: "攻击未成功", succeeded: "攻击成功 · 阻断", uncertain: "结果不确定 · 阻断", error: "执行错误 · 阻断", not_run: "未运行 · 阻断", not_applicable: "不适用 · 不计通过" };
const txt = (key: string) => labels[key] || key;
async function api(path: string, method = "GET", body?: any) {
  const response = await fetch("/api/v1" + path, {
    method,
    credentials: "same-origin",
    headers:
      body instanceof FormData ? {} : { "Content-Type": "application/json" },
    body:
      body === undefined
        ? undefined
        : body instanceof FormData
          ? body
          : JSON.stringify(body),
  });
  if (!response.ok) {
    const data = await response
      .json()
      .catch(() => ({ detail: "服务暂时不可用" }));
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : JSON.stringify(data.detail),
    );
  }
  return response.json();
}
export default function App() {
  const [boot, setBoot] = useState<Obj | null>(null),
    [principal, setPrincipal] = useState<Obj | null>(null),
    [logged, setLogged] = useState(false),
    [loginReady, setLoginReady] = useState(false),
    [username, setUsername] = useState("admin"),
    [password, setPassword] = useState("");
  const [theme,setTheme]=useState(()=>localStorage.getItem("lex_theme")||"light");
  const [palette,setPalette]=useState<Palette>(storedPalette);
  const [caseId, setCaseId] = useState(""),
    [data, setData] = useState<Obj | null>(null),
    [page, setPage] = useState("cases"),
    [tab, setTab] = useState("facts"),
    [taskId, setTaskId] = useState("");
  const [source, setSource] = useState<Obj | null>(null),
    [cap, setCap] = useState<Obj | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [notice, setNotice] = useState("");
  const [pane,setPane]=useState<"source"|"work">("work"),[contextOpen,setContextOpen]=useState(false);
  const [modal, setModal] = useState(""),
    [form, setForm] = useState<Obj>({}),
    [filter, setFilter] = useState("");
  const reload = useCallback(async () => {
    const [b,me] = await Promise.all([api("/bootstrap"),api("/me")]);
    setBoot(b);
    setPrincipal(me);
    setLogged(true);
    if (caseId) setData(await api("/cases/" + caseId));
  }, [caseId]);
  useEffect(()=>{
    document.documentElement.dataset.theme=theme;
    document.documentElement.dataset.palette=palette;
    localStorage.setItem("lex_theme",theme);
    localStorage.setItem("lex_palette",palette);
  },[theme,palette]);
  useEffect(() => {
    reload()
      .catch(() => setLogged(false))
      .finally(() => setLoginReady(true));
  }, [reload]);
  useEffect(() => {
    if (!logged) return;
    api("/capabilities")
      .then(setCap)
      .catch(() => {});
  }, [logged]);
  useEffect(() => {
    if (!caseId || !logged) return;
    const events = new EventSource("/api/v1/cases/" + caseId + "/events");
    events.addEventListener("changed", () => {
      api("/cases/" + caseId)
        .then(setData)
        .catch(() => {});
    });
    return () => events.close();
  }, [caseId, logged]);
  const run = async (fn: () => Promise<any>, message = "") => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await fn();
      await reload();
      if (message) setNotice(message);
      return result;
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const task =
    data?.tasks.find((t: Obj) => t.id === taskId) || data?.tasks.at(-1);
  const approveSlots = approvalSlots(task);
  const blocks: Obj[] =
    data?.documents.flatMap((d: Obj) => d.ir?.blocks || []) || [];
  const activeSource = source || blocks[0] || null;
  const currentCase = data?.case;
  const factFieldOptions = Array.from(
    new Map<string, Obj>(
      (boot?.packs || [])
        .filter((pack: Obj) => pack.domain_id === currentCase?.domain)
        .flatMap((pack: Obj) => pack.fact_fields || [])
        .map((field: Obj | string) => {
          const id = typeof field === "string" ? field : field.id;
          return [id, { id, label: typeof field === "string" ? txt(id) : field.label || txt(id) }];
        }),
    ).values(),
  );
  const pickCase = (id: string) => {
    setCaseId(id);
    setData(null);
    setTaskId("");
    setSource(null);
    setPage("workspace");
    setTab("facts");
  };
  const createDemo = (scenario: string) =>
    run(async () => {
      const c = await api("/demos", "POST", { scenario });
      pickCase(c.id);
    }, "已载入固定合成材料，不包含真实案件数据。");
  const locate = async (ids: string[]) => {
    if (!ids.length) return;
    try {
      const anchors: Obj[] = await api("/cases/" + caseId + "/anchors");
      const normalized = ids.map((item: any) => typeof item === "string" ? item : item.id);
      const b = anchors.find((a) => normalized.includes(a.id));
      if (b) { setSource(b); setPane("source"); }
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const taskAction = (action: string, body?: Obj) =>
    run(() => api(`/tasks/${task.id}/${action}`, "POST", body));
  const openFact = (fact?: Obj) => {
    setForm(
      fact
        ? { ...fact }
        : {
            field: "event",
            value: "",
            source_ids: activeSource ? [activeSource.id] : [],
            confirmed: false,
          },
    );
    setModal("fact");
  };
  const saveFact = () =>
    run(async () => {
      await api(
        `/cases/${caseId}/facts${form.id ? "/" + form.id : ""}`,
        form.id ? "PUT" : "POST",
        {
          field: form.field,
          value: form.value,
          source_ids: form.source_ids,
          confirmed: form.confirmed,
        },
      );
      setModal("");
    }, "事实已保存；相关旧任务需要重新生成。");
  const startTask = (transport: string, taskType = "fact_summary") =>
    run(async () => {
      const t = await api(`/cases/${caseId}/tasks`, "POST", { transport, task_type: taskType });
      setTaskId(t.id);
      setTab(taskType === "timeline" || taskType === "evidence_inventory" || taskType === "issue_extraction" ? "result" : "disclosure");
    }, taskType === "timeline" ? "本地时间线已生成，未发生外发。"
      : taskType === "evidence_inventory" ? "本地证据清单已生成，未发生外发。"
      : taskType === "issue_extraction" ? "本地争点候选已生成，未发生外发。"
      : "披露方案已生成，请逐项核对。");
  const startFollowupTask = () =>
    run(async () => {
      const t = await api(`/cases/${caseId}/followups/task`, "POST", {
        transport: currentCase?.mode === "demo" ? "mock" : "local",
        task_type: "fact_summary",
      });
      setTaskId(t.id);
      setTab("disclosure");
    }, "已根据未使用事实创建后续披露，请逐项核对。");
  const editDecision = (d: Obj, updates: Obj) =>
    run(() =>
      api(`/tasks/${task.id}/decisions/${d.fact_id}`, "PATCH", {
        transform: d.transform,
        necessity: d.necessity,
        ...updates,
      }),
    );

  if (!loginReady)
    return (
      <div className="loading">
        <Loader2 className="spin" /> 正在检查本地登录
      </div>
    );
  if (!logged)
    return (
      <div className="login-page">
        <div className="login-appearance">
          <AppearanceSwitch theme={theme} palette={palette} setTheme={setTheme} setPalette={setPalette}/>
        </div>
        <div className="login-brand">
          <ShieldCheck size={38} />
          <b>
            LexAegis<span>案隐盾</span>
          </b>
        </div>
        <div className="login-card">
          <div className="eyebrow">本地工作空间</div>
          <h1 className="display">
            让案件信息，
            <br />
            留在合适的边界。
          </h1>
          <p>输入启动终端显示的本地访问口令，进入云边协同工作台。</p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              run(async () => {
                const me=await api("/login", "POST", { username,password });
                setPrincipal(me);
                setLogged(true);
              });
            }}
          >
            <label>
              用户名
              <input value={username} onChange={(e)=>setUsername(e.target.value)} required autoComplete="username"/>
            </label>
            <label>
              本地访问口令
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoFocus
                required
                autoComplete="current-password"
              />
            </label>
            {error && <div className="error">{error}</div>}
            <button className="primary" disabled={busy}>
              进入工作台 <ArrowRight size={16} />
            </button>
          </form>
          <small>
            <LockKeyhole size={13} /> 原始材料在边侧处理，云端请求经人工审批。
          </small>
        </div>
        <div className="login-footer">
          LEXAEGIS / 0.2 <span>按目的保护</span>
        </div>
      </div>
    );

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">跳到正文</a>
      <aside className="sidebar">
        <div className="brand">
          <ShieldCheck size={30} />
          <div>
            LexAegis<small>案隐盾 · 法律隐私工作台</small>
          </div>
        </div>
        <div className="workspace-label">
          个人工作空间 <span>V0.2</span>
        </div>
        <nav>
          {[
            { id: "cases", name: "案件工作台", icon: FolderOpen },
            { id: "registry", name: "法学规则中心", icon: Layers3 },
            { id: "providers", name: "服务商治理", icon: LockKeyhole },
            { id: "benchmark", name: "隔离实验", icon: CircleHelp },
            { id: "settings", name: "运行配置", icon: Settings2 },
            { id: "users", name: "本地用户", icon: Users },
          ].filter(item=>!["benchmark","settings","users"].includes(item.id)||principal?.role==="admin")
            .filter(item=>item.id!=="providers"||["admin","legal_reviewer"].includes(principal?.role))
            .map((item) => (
            <button
              key={item.id}
              className={
                page === item.id ||
                (item.id === "cases" && page === "workspace")
                  ? "active"
                  : ""
              }
              onClick={() => setPage(item.id)}
            >
              <item.icon size={18} />
              {item.name}
              {item.id === "cases" && (
                <span className="nav-count">{boot?.cases.length || 0}</span>
              )}
            </button>
          ))}
        </nav>
        <div className="recent-label">最近案件</div>
        <div className="recent-list">
          {boot?.cases
            .slice(-5)
            .reverse()
            .map((c: Obj) => (
              <button
                key={c.id}
                className={
                  c.id === caseId && page === "workspace" ? "chosen" : ""
                }
                onClick={() => pickCase(c.id)}
              >
                <span className="case-dot" />
                <span>{c.name}</span>
              </button>
            ))}
        </div>
        <div className="side-bottom">
          <div className="edge-indicator">
            {cap?.edge?.status === "available" && <span className="pulse-dot" />}
            {edgeWorkbenchLabel(cap)}
          </div>
          <p>
            原文留在边侧
            <br />
            披露由你决定
          </p>
          <button
            className="profile"
            onClick={() =>
              run(async () => {
                await api("/logout", "POST");
                setLogged(false);
                setPrincipal(null);
                setCap(null);
              })
            }
          >
            <div className="avatar">{(principal?.actor||"律").slice(0,1)}</div>
            <span>
              {principal?.actor||"本地用户"}<small>{principal?.role||"unknown"}</small>
            </span>
            <LogOut size={16} />
          </button>
        </div>
      </aside>
      <main id="main-content">
        <header className="topbar">
          <div className="crumb">
            <PanelLeftClose size={17} />
            <span>工作空间</span>
            <ChevronRight size={13} />
            <strong>{pageCrumb(page, currentCase?.name)}</strong>
          </div>
          <div className="top-right">
            <span>
              <LockKeyhole size={13} /> 本地优先
            </span>
            <Tag tone="green">云边协同</Tag>
            <AppearanceSwitch theme={theme} palette={palette} setTheme={setTheme} setPalette={setPalette}/>
          </div>
        </header>
        {(error || notice) && (
          <div
            role="alert"
            className={"toast " + (error ? "error" : "success")}
          >
            <span>{error || notice}</span>
            <button
              aria-label="关闭提示"
              onClick={() => {
                setError("");
                setNotice("");
              }}
            >
              <X size={15} />
            </button>
          </div>
        )}
        {busy && <div className="busy-bar" />}
        {page === "cases" && (
          <div className="content dashboard">
            <div className="section-heading">
              <div>
                <div className="eyebrow">案件工作空间</div>
                <h1>案件工作台</h1>
                <p>从材料到摘要，为每一次信息披露保留依据。</p>
              </div>
              <button
                className="primary"
                onClick={() => {
                  setForm({ name: "", domain: "labor" });
                  setModal("case");
                }}
              >
                <Plus size={17} />
                新建案件
              </button>
            </div>
            <div className="overview-grid">
              <div className="overview-intro">
                <div className="eyebrow light">按目的披露</div>
                <h2 className="display">
                  先厘清事实，
                  <br />
                  再决定披露。
                </h2>
                <p>
                  边侧小模型处理敏感材料，云端大模型执行经批准的任务。你始终掌握外发边界。
                </p>
                <div className="intro-flow">
                  <span>边侧处理</span>
                  <ArrowRight size={14} />
                  <span>律师审批</span>
                  <ArrowRight size={14} />
                  <span>云端生成</span>
                </div>
                <ShieldCheck className="watermark" />
              </div>
              <div className="metric">
                <span>当前案件</span>
                <strong className="tabular">
                  {String(boot?.cases.length || 0).padStart(2, "0")}
                </strong>
                <small>
                  <FolderOpen size={14} />
                  独立材料与身份映射
                </small>
              </div>
              <div className="metric">
                <span>首期任务</span>
                <strong className="word">事实摘要</strong>
                <small>
                  <Layers3 size={14} />
                  劳动争议 · 演示规则
                </small>
              </div>
            </div>
            <div className="list-heading">
              <h2>
                全部案件 <span>{boot?.cases.length || 0}</span>
              </h2>
              <div className="search">
                <Search size={15} />
                <input
                  aria-label="搜索案件"
                  placeholder="搜索案件名称"
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                />
              </div>
            </div>
            <div className="case-table">
              <div className="table-head">
                <span>案件名称</span>
                <span>案由</span>
                <span>运行模式</span>
                <span>创建日期</span>
                <span />
              </div>
              {boot?.cases
                .filter((c: Obj) => c.name.includes(filter))
                .reverse()
                .map((c: Obj) => (
                  <button
                    className="case-row"
                    key={c.id}
                    onClick={() => pickCase(c.id)}
                  >
                    <span className="case-name">
                      <span className="file-icon">
                        <FolderOpen size={19} />
                      </span>
                      <span>
                        <b>{c.name}</b>
                        <small>{c.id}</small>
                      </span>
                    </span>
                    <span>{c.domain === "labor" ? "劳动争议" : c.domain}</span>
                    <span>
                      <Tag tone={c.mode === "demo" ? "amber" : "green"}>
                        {c.mode === "demo" ? "合成演示" : "正式案件"}
                      </Tag>
                    </span>
                    <span className="tabular">
                      {new Date(c.created_at).toLocaleDateString("zh-CN")}
                    </span>
                    <ArrowUpRight size={17} />
                  </button>
                ))}
              {!boot?.cases.length && (
                <Empty
                  title="从第一份案件材料开始"
                  detail="创建正式案件，或使用下方合成案例体验完整流程。"
                />
              )}
            </div>
            <div className="list-heading demo-heading">
              <div>
                <h2>先体验，再开始</h2>
                <p>固定合成材料 · 不包含真实身份 · 模拟结果明确标注</p>
              </div>
              <Tag>三个边界场景</Tag>
            </div>
            <div className="demo-grid">
              {[
                {
                  id: "success",
                  no: "01",
                  name: "完整披露流程",
                  desc: "从事实整理到知情审批，体验带原文依据的摘要。",
                  icon: ArrowUpRight,
                },
                {
                  id: "linkage",
                  no: "02",
                  name: "看见组合线索风险",
                  desc: "姓名已替换，唯一岗位与事件仍可能暴露身份。",
                  icon: Search,
                },
                {
                  id: "stop",
                  no: "03",
                  name: "在必要时主动停止",
                  desc: "材料无法核实，明确阻断外发并保留原因。",
                  icon: ShieldCheck,
                },
              ].map((d) => (
                <button
                  key={d.id}
                  className={d.id === "success" ? "demo-card featured" : "demo-card"}
                  disabled={busy}
                  onClick={() => createDemo(d.id)}
                >
                  <div>
                    <span>{d.no}</span>
                    <d.icon size={19} />
                  </div>
                  <h3>{d.name}</h3>
                  <p>{d.desc}</p>
                  <small>
                    载入合成案例 <ArrowRight size={14} />
                  </small>
                </button>
              ))}
            </div>
            <footer className="page-footer">
              <ShieldCheck size={14} />
              正式案件在适用规则与必需风险检验就绪前，始终阻断外发。
              <span>LEXAEGIS - 2026</span>
            </footer>
          </div>
        )}

        {page === "workspace" && data && (
          <div className="workspace-content">
            <div className="workspace-title">
              <div>
                <div className="eyebrow">{currentCase.id}</div>
                <h1>
                  {currentCase.name}{" "}
                  <Tag tone={currentCase.mode === "demo" ? "amber" : "green"}>
                    {currentCase.mode === "demo" ? "固定合成演示" : "正式案件"}
                  </Tag>
                </h1>
                <p>
                  材料版本 {currentCase.revision} · 累计披露记录{" "}
                  {data.ledger.length} ·{" "}
                  {currentCase.mode === "demo"
                    ? "仅供演示，不构成正式风险结论"
                    : "未完成的规则与风险检验将阻断外发"}
                </p>
              </div>
              <button className="secondary" onClick={() => setPage("cases")}>
                返回案件列表
              </button>
            </div>
            <StageStepper active={tab} onSelect={id=>{setTab(id);setPane("work")}} stages={[
              {id:"facts",label:"材料与事实"},{id:"disclosure",label:"披露方案"},
              {id:"risk",label:"风险与审批"},{id:"result",label:"摘要与回链"},
            ]}/>
            <div className="pane-tabs" aria-label="工作区面板">
              <button className={pane==="source"?"selected":""} onClick={()=>setPane("source")}>原始材料</button>
              <button className={pane==="work"?"selected":""} onClick={()=>setPane("work")}>案件工作区</button>
              <button className={contextOpen?"selected":""} onClick={()=>setContextOpen(!contextOpen)}>依据与留痕</button>
            </div>
            {data.jobs.some((j: Obj) =>
              ["pending", "running", "failed"].includes(j.status),
            ) && (
              <div className="jobs">
                {data.jobs.slice(-3).map((j: Obj) => (
                  <span key={j.id}>
                    <Clock3 size={13} />
                    {j.kind} · {txt(j.status)} {j.error && <b>{j.error}</b>}
                    {j.status === "pending" &&
                      !["send", "reconcile"].includes(j.kind) && (
                        <button
                          onClick={() =>
                            run(() => api("/jobs/" + j.id + "/cancel", "POST"))
                          }
                        >
                          取消
                        </button>
                      )}
                  </span>
                ))}
              </div>
            )}
            <div className={`three-panel pane-${pane} ${contextOpen?"context-open":""}`}>
              <SourceViewer data={data} currentCase={currentCase} caseId={caseId} busy={busy}
                activeSource={activeSource} blocks={blocks} onSelect={setSource}
                onUpload={(file) => {
                  const body = new FormData();
                  body.append("file", file);
                  run(() => api("/cases/" + caseId + "/documents", "POST", body),
                    "已进入本地解析队列。");
                }}
                onCorrect={(selected) => {
                  setForm({ text: selected.text, block_id: selected.id, document_id: selected.document_id });
                  setModal("correction");
                }}
                onConfirm={(selected) => {
                  run(async () => {
                    const d = await api(
                      `/cases/${caseId}/documents/${selected.document_id}/confirmation`,
                      "PUT",
                      { block_id: selected.id },
                    );
                    setSource(d.ir.blocks.find((b: Obj) => b.id === selected.id) || d.ir.blocks[0]);
                  });
                }}/>

              <section className="work-panel">
                <div className="panel-heading">
                  <h3>
                    {tab === "facts"
                      ? "事实与证据"
                      : tab === "disclosure"
                        ? "逐项披露方案"
                        : tab === "risk"
                          ? "风险检验与审批"
                          : task ? txt(task.type) : "结果"}
                  </h3>
                  {task && tab !== "facts" && (
                    <Tag
                      tone={
                        task.status === "blocked"
                          ? "red"
                          : task.status === "complete"
                            ? "green"
                            : "neutral"
                      }
                    >
                      {txt(task.status)}
                    </Tag>
                  )}
                </div>
                {tab === "facts" && <FactWorkspace facts={data.facts} currentCase={currentCase}
                  busy={busy} label={txt}
                  onExtract={() => run(() => api("/cases/" + caseId + "/extract", "POST"),
                    "已进入边侧模型提取队列。")}
                  onOpen={openFact} onLocate={locate}
                  onDelete={(fact) => { setForm(fact); setModal("deleteFact"); }}
                  onTimeline={() => startTask("local", "timeline")}
                  onEvidence={() => startTask("local", "evidence_inventory")}
                  onIssues={() => startTask("local", "issue_extraction")}
                  onSummary={() => startTask(currentCase.mode === "demo" ? "mock" : "local")}
                  onStartCloud={() => startTask("cloud")}/>}

                {tab !== "facts" && !task && (
                  <Empty
                    title="尚未创建任务"
                    detail="请先核实事实，再生成披露方案。"
                  />
                )}
                {tab !== "facts" && task && (
                  <>
                    <div className="task-switch">
                      <select
                        aria-label="任务历史"
                        value={task.id}
                        onChange={(e) => setTaskId(e.target.value)}
                      >
                        {data.tasks.map((t: Obj, i: number) => (
                          <option key={t.id} value={t.id}>
                            任务 {i + 1} ·{" "}
                            {t.transport === "local" ? "本地" : t.transport === "mock" ? "模拟" : "云端 API"} ·{" "}
                            {txt(t.status)}
                          </option>
                        ))}
                      </select>
                      <button
                        className="text-button"
                        onClick={() =>
                          startTask(
                            currentCase.mode === "demo" ? "mock" : "local",
                          )
                        }
                      >
                        新建任务
                      </button>
                    </div>
                    {task.stale && (
                      <div className="inline-warning">
                        材料或配置已变化，请新建任务。历史记录仍保留。
                      </div>
                    )}
                    {tab === "disclosure" && <DisclosureWorkspace task={task}
                      currentCase={currentCase} busy={busy} label={txt}
                      onEdit={editDecision} onLocate={locate}
                      onEditOutput={(decision) => { setForm({ ...decision }); setModal("output"); }}
                      onEvaluate={() => run(async () => {
                        await api("/tasks/" + task.id + "/evaluate", "POST");
                        setTab("risk");
                      })}/>}

                    {tab === "risk" && (
                      <RiskWorkspace task={task} busy={busy} label={txt} attackLabels={attackLabels}
                        onAction={taskAction} onApprove={()=>setModal("approve")} onResult={()=>setTab("result")}
                        onRunAttacks={(auxiliary)=>run(()=>api(`/tasks/${task.id}/attacks/run`,"POST",{auxiliary}),
                          "红队作业已排队；完成后请重新检验。")}/>
                    )}

                    {tab === "result" && (
                      <RestorationWorkspace task={task} currentCase={currentCase} busy={busy} locate={locate}
                        onAction={taskAction}
                        onDismissFollowup={(id) => run(() => api(`/cases/${caseId}/followups/${id}/dismiss`, "POST"))}
                        onFollowupTask={startFollowupTask}/>
                    )}
                  </>
                )}
              </section>
              <ContextRail currentCase={currentCase} task={task} caseId={caseId}
                audit={data.audit} busy={busy} onClose={() => setContextOpen(false)}
                onStartCloud={() => startTask("cloud")}/>
            </div>
          </div>
        )}

        {page === "settings" && (
          <div className="content settings-page">
            <div className="section-heading">
              <div>
                <div className="eyebrow">边侧与云端</div>
                <h1>运行配置</h1>
                <p>边侧负责敏感处理，云端只接收批准后的最小必要内容。</p>
              </div>
              <button
                className="secondary"
                onClick={() =>
                  run(async () => setCap(await api("/capabilities")))
                }
              >
                检查连接
              </button>
            </div>
            <div className="capability-grid">
              {[
                ["edge", "边侧小模型"],
                ["cloud", "云端网关"],
                ["ocr", "本地 OCR"],
                ["redteam", "风险攻击"],
                ["isolation", "网络隔离"],
                ["technical", "技术实现"],
                ["runtime", "运行配置"],
                ["legal", "法学发布"],
                ["validation", "实际验证"],
              ].map(([key, name]) => (
                <div className="capability" key={key}>
                  <div>
                    <b>{name}</b>
                    <Tag
                      tone={
                        cap?.[key]?.status === "available" ? "green" : "amber"
                      }
                    >
                      {txt(cap?.[key]?.status || "unconfigured")}
                    </Tag>
                  </div>
                  <p>{capabilityDetail(key, cap?.[key])}</p>
                </div>
              ))}
            </div>
            {boot && (
              <SettingsForm
                value={boot.settings}
                providers={boot.providers || []}
                busy={busy}
                save={(v: Obj) =>
                  run(
                    () => api("/settings", "PUT", v),
                    "配置已更新；旧任务依据已失效。",
                  )
                }
              />
            )}
            <div className="settings-note">
              <LockKeyhole size={20} />
              <div>
                <h3>密钥只配置在外发网关</h3>
                <p>
                  在本机 .env 中设置 LEX_CLOUD_API_KEY
                  和允许的服务商主机名。界面与业务 API
                  不读取或存储云端密钥。运行配置变化后需要重新创建任务。
                </p>
              </div>
            </div>
          </div>
        )}
        {page === "providers" && <ProviderCenter providers={boot?.providers} request={api} refresh={reload} busy={busy}/>}
        {page === "benchmark" && <BenchmarkCenter protocols={boot?.risk_protocols} request={api} refresh={reload}/>}
        {page === "registry" && <LegalPackCenter packs={boot?.packs} tasks={boot?.task_definitions||boot?.tasks} request={api}/>}
        {page === "users" && <UserCenter request={api}/>}
      </main>

      {modal && (
        <Dialog open title={modal} busy={busy} onClose={() => setModal("")}>
            {modal === "case" && (
              <>
                <div className="eyebrow">新建案件</div>
                <h2>建立案件工作空间</h2>
                <p>材料、身份映射和披露记录独立归属于该案件。</p>
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    run(async () => {
                      const c = await api("/cases", "POST", form);
                      setModal("");
                      pickCase(c.id);
                    });
                  }}
                >
                  <label>
                    案件名称
                    <input
                      autoFocus
                      required
                      value={form.name}
                      onChange={(e) =>
                        setForm({ ...form, name: e.target.value })
                      }
                      placeholder="例如：劳动争议材料整理"
                    />
                  </label>
                  <label>
                    案由
                    <select
                      value={form.domain}
                      onChange={(e) =>
                        setForm({ ...form, domain: e.target.value })
                      }
                    >
                      {boot?.packs.map((p: Obj) => (
                        <option key={p.id} value={p.domain_id}>
                          {p.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <div className="inline-warning">
                    当前规则与红队能力尚未就绪，正式案件支持本地处理，外发保持阻断。
                  </div>
                  <button className="primary" disabled={busy}>
                    创建正式案件 <ArrowRight size={15} />
                  </button>
                </form>
              </>
            )}
            {modal === "fact" && (
              <>
                <h2>{form.id ? "编辑事实" : "添加可核实事实"}</h2>
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    saveFact();
                  }}
                >
                  <label>
                    事实类型
                    <select
                      value={form.field}
                      onChange={(e) =>
                        setForm({ ...form, field: e.target.value })
                      }
                    >
                      {factFieldOptions.map((field) => (
                        <option key={field.id} value={field.id}>
                          {field.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    事实内容
                    <textarea
                      required
                      rows={4}
                      value={form.value}
                      onChange={(e) =>
                        setForm({ ...form, value: e.target.value })
                      }
                    />
                  </label>
                  <label>
                    原文依据（可多选）
                    <select
                      multiple
                      required
                      value={form.source_ids}
                      onChange={(e) =>
                        setForm({
                          ...form,
                          source_ids: Array.from(
                            e.target.selectedOptions,
                            (o) => o.value,
                          ),
                        })
                      }
                    >
                      {blocks.map((b: Obj) => (
                        <option key={b.id} value={b.id}>
                          {b.locator} · {b.text.slice(0, 35)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="checkbox">
                    <input
                      type="checkbox"
                      checked={form.confirmed}
                      onChange={(e) =>
                        setForm({ ...form, confirmed: e.target.checked })
                      }
                    />
                    我已核对事实及其来源
                  </label>
                  <button className="primary" disabled={busy}>
                    保存事实
                  </button>
                </form>
              </>
            )}
            {modal === "correction" && (
              <>
                <h2>校正材料文本</h2>
                <p>保存后生成新材料版本，引用旧版本的事实需要重新核实。</p>
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    run(async () => {
                      const d = await api(
                        `/cases/${caseId}/documents/${form.document_id}/correction`,
                        "PUT",
                        { block_id: form.block_id, text: form.text },
                      );
                      setSource(d.ir.blocks[0]);
                      setModal("");
                    });
                  }}
                >
                  <textarea
                    required
                    rows={9}
                    value={form.text}
                    onChange={(e) => setForm({ ...form, text: e.target.value })}
                  />
                  <button className="primary" disabled={busy}>
                    保存新版本
                  </button>
                </form>
              </>
            )}
            {modal === "output" && (
              <>
                <h2>编辑本项披露文本</h2>
                <p>修改后旧审批失效，必须重新检验。</p>
                <textarea
                  rows={6}
                  value={form.output}
                  onChange={(e) => setForm({ ...form, output: e.target.value })}
                />
                <button
                  className="primary"
                  disabled={busy}
                  onClick={() =>
                    run(async () => {
                      await api(
                        `/tasks/${task.id}/decisions/${form.fact_id}`,
                        "PATCH",
                        {
                          transform: form.transform,
                          necessity: form.necessity,
                          output: form.output,
                        },
                      );
                      setModal("");
                    })
                  }
                >
                  保存修改
                </button>
              </>
            )}
            {modal === "approve" && (
              <>
                <ShieldCheck size={32} className="green-icon" />
                <h2>批准这一份完整请求</h2>
                <p>
                  请确认已阅读请求正文、目标服务、信息保留依据和残余风险。固定合成演示不替代正式冻结攻击与法学审核。
                </p>
                <div className="approval-summary">
                  <b>主模型 · {approveSlots.primary.model || "未提供"}</b>
                  <span>{approveSlots.primary.target || "目标未提供"}</span>
                  <b>备用模型 · {approveSlots.standby.model || "未提供"}</b>
                  <span>{approveSlots.standby.target || "目标未提供"}</span>
                  <span>
                    备用仅在主模型尚未开始生成时使用；生成开始后失败不会自动换模型。
                  </span>
                  {approveSlots.prompt_hash && (
                    <code>{approveSlots.prompt_hash}</code>
                  )}
                  <code>{task?.request_hash}</code>
                </div>
                <button
                  className="primary"
                  disabled={busy}
                  onClick={() =>
                    run(async () => {
                      await api(`/tasks/${task.id}/approve`, "POST", {
                        request_hash: task.request_hash,
                      });
                      setModal("");
                    }, "当前请求已批准，有效期 30 分钟；尚未发送。")
                  }
                >
                  已知悉并批准当前版本
                </button>
              </>
            )}
            {modal === "deleteFact" && (
              <>
                <h2>删除这项事实？</h2>
                <p>相关任务将标记为依据已变化。原始材料与历史任务仍保留。</p>
                <button
                  className="primary"
                  disabled={busy}
                  onClick={() =>
                    run(async () => {
                      await api(`/cases/${caseId}/facts/${form.id}`, "DELETE");
                      setModal("");
                    })
                  }
                >
                  确认删除
                </button>
              </>
            )}
            {error && <p className="error">{error}</p>}
        </Dialog>
      )}
    </div>
  );
}

function pageCrumb(page: string, caseName?: string) {
  if (page === "workspace") return caseName || "载入中";
  return (
    {
      cases: "案件工作台",
      registry: "法学规则中心",
      providers: "服务商治理",
      benchmark: "隔离实验与风险协议",
      settings: "运行配置",
      users: "本地用户与角色",
    }[page] || "案件工作台"
  );
}

function edgeWorkbenchLabel(cap: Obj | null) {
  if (!cap) return "边侧工作台检查中";
  return `边侧工作台${txt(cap.edge?.status || "unconfigured")}`;
}

function asSlot(raw: any, fallback: Obj = {}) {
  const slot = raw && typeof raw === "object" ? raw : {};
  return {
    url: String(slot.url || fallback.url || ""),
    model: String(slot.model || fallback.model || ""),
    provider_id: slot.provider_id || fallback.provider_id || "",
  };
}

function settingsPayload(v: Obj) {
  const primary = {
    url: v.cloud_url,
    model: v.cloud_model,
    provider_id: v.provider_id || null,
  };
  return {
    cloud_url: primary.url,
    cloud_model: primary.model,
    provider_id: primary.provider_id,
    cloud_primary: primary,
    cloud_standby: {
      url: v.standby_url,
      model: v.standby_model,
      provider_id: v.standby_provider_id || null,
    },
    edge_url: v.edge_url,
    edge_model: v.edge_model,
    disclosure_budget_chars: Number(v.disclosure_budget_chars || 50000),
    disclosure_budget_entries: Number(v.disclosure_budget_entries || 20),
    deployment_mode: v.deployment_mode,
    isolation_verified: Boolean(v.isolation_verified),
  };
}

function capabilityDetail(key: string, item: Obj | undefined) {
  const detail = item?.detail || "正在检查配置";
  if (key !== "cloud") return detail;
  return detail.includes("双槽")
    ? detail
    : `${detail} 界面可配置云端双槽，不代表已完成真实外发验证。`;
}

function approvalSlots(task: Obj | undefined) {
  const request = task?.request || {};
  const body = request.body || {};
  const deps = task?.dependencies || request.dependencies || {};
  const dual = request.dual_slot || task?.dual_slot || deps.dual_slot;
  return {
    primary: {
      model: dual?.primary?.model || deps.primary_model || body.model || "",
      target: dual?.primary?.target || request.target || "",
    },
    standby: {
      model: dual?.standby?.model || deps.standby_model || "",
      target: dual?.standby?.target || "",
    },
    prompt_hash: deps.prompt_hash || request.prompt_hash || "",
  };
}

function CloudSlotFields({
  title,
  url,
  model,
  providerId,
  providers,
  onUrl,
  onModel,
  onProvider,
}: {
  title: string;
  url: string;
  model: string;
  providerId: string;
  providers: Obj[];
  onUrl: (value: string) => void;
  onModel: (value: string) => void;
  onProvider: (value: string | null) => void;
}) {
  return (
    <div className="settings-slot">
      <h3>{title}</h3>
      <label>
        API 根地址
        <input value={url} onChange={(e) => onUrl(e.target.value)} />
      </label>
      <label>
        模型名称
        <input
          value={model}
          placeholder="填写服务商提供的模型标识"
          onChange={(e) => onModel(e.target.value)}
        />
      </label>
      <label>
        经复核服务商档案
        <select
          value={providerId}
          onChange={(e) => onProvider(e.target.value || null)}
        >
          <option value="">未选择（正式外发阻断）</option>
          {providers.map((provider) => (
            <option key={provider.id} value={provider.id}>
              {provider.name} · {provider.status}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}

function SettingsForm({
  value,
  providers,
  busy,
  save,
}: {
  value: Obj;
  providers: Obj[];
  busy: boolean;
  save: (v: Obj) => void;
}) {
  const primary = asSlot(value.cloud_primary, {
    url: value.cloud_url,
    model: value.cloud_model,
    provider_id: value.provider_id,
  });
  const standby = asSlot(value.cloud_standby);
  const [v, setV] = useState({
    cloud_url: primary.url,
    cloud_model: primary.model,
    provider_id: primary.provider_id || "",
    standby_url: standby.url,
    standby_model: standby.model,
    standby_provider_id: standby.provider_id || "",
    edge_url: value.edge_url || "",
    edge_model: value.edge_model || "",
    disclosure_budget_chars: value.disclosure_budget_chars || 50000,
    disclosure_budget_entries: value.disclosure_budget_entries || 20,
    deployment_mode: value.deployment_mode || "native",
    isolation_verified: Boolean(value.isolation_verified),
  });
  return (
    <form
      className="settings-form"
      onSubmit={(e) => {
        e.preventDefault();
        save(settingsPayload(v));
      }}
    >
      <div>
        <h3>边侧推理服务</h3>
        <p>仅允许已登记的本机或可信内网地址。</p>
        <label>
          API 根地址
          <input
            value={v.edge_url}
            onChange={(e) => setV({ ...v, edge_url: e.target.value })}
          />
        </label>
        <label>
          边侧模型名称
          <input
            value={v.edge_model}
            placeholder="填写已下载的小模型标识"
            onChange={(e) => setV({ ...v, edge_model: e.target.value })}
          />
        </label>
      </div>
      <div>
        <h3>云端大模型</h3>
        <p>
          使用兼容 Chat Completions 的 API。密钥只在外发网关，思考关闭，流式不进入本界面。主模型同步写入兼容字段。
        </p>
        <CloudSlotFields
          title="主模型"
          url={v.cloud_url}
          model={v.cloud_model}
          providerId={v.provider_id || ""}
          providers={providers}
          onUrl={(cloud_url) => setV({ ...v, cloud_url })}
          onModel={(cloud_model) => setV({ ...v, cloud_model })}
          onProvider={(provider_id) => setV({ ...v, provider_id: provider_id || "" })}
        />
        <CloudSlotFields
          title="备用模型"
          url={v.standby_url}
          model={v.standby_model}
          providerId={v.standby_provider_id || ""}
          providers={providers}
          onUrl={(standby_url) => setV({ ...v, standby_url })}
          onModel={(standby_model) => setV({ ...v, standby_model })}
          onProvider={(standby_provider_id) =>
            setV({ ...v, standby_provider_id: standby_provider_id || "" })
          }
        />
        <p>部署模式：{v.deployment_mode} · 隔离验收：{v.isolation_verified ? "已记录" : "未通过"}</p>
        <h3>跨轮外发工程预算</h3>
        <p>累计账本字符与条数上限，防止演示或误操作无限轮外发。不是法学必要性判断。</p>
        <label>
          累计外发字符
          <input
            type="number"
            min={1}
            max={2000000}
            value={v.disclosure_budget_chars}
            onChange={(e) => setV({ ...v, disclosure_budget_chars: Number(e.target.value) })}
          />
        </label>
        <label>
          累计外发条数
          <input
            type="number"
            min={1}
            max={1000}
            value={v.disclosure_budget_entries}
            onChange={(e) => setV({ ...v, disclosure_budget_entries: Number(e.target.value) })}
          />
        </label>
      </div>
      <button className="primary" disabled={busy}>
        保存运行配置
      </button>
    </form>
  );
}
