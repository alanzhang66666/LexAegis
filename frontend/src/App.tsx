import { useCallback, useEffect, useState } from "react";
import {
  ShieldCheck,
  FolderOpen,
  Layers3,
  Settings2,
  ArrowUpRight,
  ArrowRight,
  Plus,
  FileText,
  Upload,
  Check,
  LockKeyhole,
  AlertTriangle,
  ChevronRight,
  Download,
  Play,
  X,
  Search,
  Clock3,
  ExternalLink,
  Link2,
  Loader2,
  LogOut,
  PanelLeftClose,
  CircleHelp,
} from "lucide-react";

type Obj = Record<string, any>;
const labels: Record<string, string> = {
  entity: "主体",
  relation: "关系",
  event: "事件",
  date: "日期",
  amount: "金额",
  evidence: "证据",
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
const Tag = ({
  children,
  tone = "neutral",
}: {
  children: React.ReactNode;
  tone?: string;
}) => <span className={"tag " + tone}>{children}</span>;
const Empty = ({ title, detail }: { title: string; detail: string }) => (
  <div className="empty">
    <FileText size={32} />
    <h3>{title}</h3>
    <p>{detail}</p>
  </div>
);

export default function App() {
  const [boot, setBoot] = useState<Obj | null>(null),
    [logged, setLogged] = useState(false),
    [loginReady, setLoginReady] = useState(false),
    [password, setPassword] = useState("");
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
  const [modal, setModal] = useState(""),
    [form, setForm] = useState<Obj>({}),
    [filter, setFilter] = useState("");
  const reload = useCallback(async () => {
    const b = await api("/bootstrap");
    setBoot(b);
    setLogged(true);
    if (caseId) setData(await api("/cases/" + caseId));
  }, [caseId]);
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
  const blocks: Obj[] =
    data?.documents.flatMap((d: Obj) => d.ir?.blocks || []) || [];
  const activeSource = source || blocks[0] || null;
  const currentCase = data?.case;
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
      const b = anchors.find((a) => ids.includes(a.id));
      if (b) setSource(b);
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
  const startTask = (transport: string) =>
    run(async () => {
      const t = await api(`/cases/${caseId}/tasks`, "POST", { transport });
      setTaskId(t.id);
      setTab("disclosure");
    }, "披露方案已生成，请逐项核对。");
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
        <Loader2 className="spin" /> 正在连接边侧工作台
      </div>
    );
  if (!logged)
    return (
      <div className="login-page">
        <div className="login-brand">
          <ShieldCheck size={38} />
          <b>
            LexAegis<span>案隐盾</span>
          </b>
        </div>
        <div className="login-card">
          <div className="eyebrow">LOCAL WORKSPACE · 本地可信环境</div>
          <h1>
            让案件信息，
            <br />
            留在合适的边界。
          </h1>
          <p>输入启动终端显示的本地访问口令，进入云边协同工作台。</p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              run(async () => {
                await api("/login", "POST", { password });
                setLogged(true);
              });
            }}
          >
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
          LEXAEGIS / 0.1 <span>PRIVACY BY PURPOSE</span>
        </div>
      </div>
    );

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <ShieldCheck size={30} />
          <div>
            LexAegis<small>案隐盾 · 法律隐私工作台</small>
          </div>
        </div>
        <div className="workspace-label">
          个人工作空间 <span>V0.1</span>
        </div>
        <nav>
          {[
            { id: "cases", name: "案件工作台", icon: FolderOpen },
            { id: "registry", name: "能力与知识包", icon: Layers3 },
            { id: "settings", name: "运行配置", icon: Settings2 },
          ].map((item) => (
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
            <span className="pulse-dot" />
            边侧工作台在线
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
              })
            }
          >
            <div className="avatar">律</div>
            <span>
              本地律师<small>单用户工作空间</small>
            </span>
            <LogOut size={16} />
          </button>
        </div>
      </aside>
      <main>
        <header className="topbar">
          <div className="crumb">
            <PanelLeftClose size={17} />
            <span>工作空间</span>
            <ChevronRight size={13} />
            <strong>
              {page === "workspace"
                ? currentCase?.name || "载入中"
                : page === "settings"
                  ? "运行配置"
                  : page === "registry"
                    ? "能力与知识包"
                    : "案件工作台"}
            </strong>
          </div>
          <div className="top-right">
            <span>
              <LockKeyhole size={13} /> 本地优先
            </span>
            <Tag tone="green">云边协同</Tag>
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
                <div className="eyebrow">CASE WORKSPACE</div>
                <h1>
                  案件工作台<span className="heading-dot">.</span>
                </h1>
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
                <div className="eyebrow light">PURPOSE-BOUND DISCLOSURE</div>
                <h2>
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
                <strong>
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
                    <span>
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
                  className="demo-card"
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
              <span>LEXAEGIS — 2026</span>
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
            <div className="stage-bar">
              {["材料与事实", "披露方案", "风险与审批", "摘要与回链"].map(
                (name, i) => (
                  <button
                    key={name}
                    className={
                      tab === ["facts", "disclosure", "risk", "result"][i]
                        ? "selected"
                        : ""
                    }
                    onClick={() =>
                      setTab(["facts", "disclosure", "risk", "result"][i])
                    }
                  >
                    <span>{String(i + 1).padStart(2, "0")}</span>
                    {name}
                    <ChevronRight size={15} />
                  </button>
                ),
              )}
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
            <div className="three-panel">
              <section className="source-panel">
                <div className="panel-heading">
                  <h3>
                    <FileText size={16} />
                    原始材料
                  </h3>
                  <Tag>仅边侧</Tag>
                </div>
                <div className="document-list">
                  {data.documents.map((d: Obj) => (
                    <button
                      key={d.id}
                      onClick={() => setSource(d.ir?.blocks[0] || null)}
                    >
                      <FileText size={15} />
                      <span>
                        {d.name}
                        <small>
                          v{d.version} ·{" "}
                          {d.status === "ready" ? "已解析" : txt(d.status)}
                        </small>
                        {d.error && (
                          <small className="danger-text">{d.error}</small>
                        )}
                      </span>
                      {d.path !== null && d.extension !== "demo" && (
                        <a
                          href={`/api/v1/cases/${caseId}/documents/${d.id}/file`}
                          onClick={(e) => e.stopPropagation()}
                          title="下载原件"
                        >
                          <Download size={14} />
                        </a>
                      )}
                    </button>
                  ))}
                </div>
                {currentCase.mode === "formal" && (
                  <label className="upload">
                    <Upload size={17} />
                    <span>
                      上传 DOCX / PDF<small>支持扫描页检测 · 最大 20 MB</small>
                    </span>
                    <input
                      type="file"
                      accept=".docx,.pdf"
                      disabled={busy}
                      onChange={(e) => {
                        const f = e.target.files?.[0];
                        if (f) {
                          const body = new FormData();
                          body.append("file", f);
                          run(
                            () =>
                              api(
                                "/cases/" + caseId + "/documents",
                                "POST",
                                body,
                              ),
                            "已进入本地解析队列。",
                          );
                          e.target.value = "";
                        }
                      }}
                    />
                  </label>
                )}
                {activeSource ? (
                  <>
                    <div className="source-label">
                      <span>
                        {activeSource.locator} · v
                        {activeSource.document_version}
                      </span>
                      {activeSource.confidence !== null &&
                        activeSource.confidence !== undefined && (
                          <Tag tone="amber">
                            OCR {Math.round(activeSource.confidence * 100)}%
                          </Tag>
                        )}
                    </div>
                    {activeSource.page && (
                      <div className="page-preview">
                        <img
                          alt={`原文第 ${activeSource.page} 页`}
                          src={`/api/v1/cases/${caseId}/documents/${activeSource.document_id}/page/${activeSource.page}`}
                        />
                        {activeSource.bbox && (
                          <div
                            className="bbox"
                            style={{
                              left: activeSource.bbox[0] * 100 + "%",
                              top: activeSource.bbox[1] * 100 + "%",
                              width:
                                (activeSource.bbox[2] - activeSource.bbox[0]) *
                                  100 +
                                "%",
                              height:
                                (activeSource.bbox[3] - activeSource.bbox[1]) *
                                  100 +
                                "%",
                            }}
                          />
                        )}
                      </div>
                    )}
                    <div className="source-text">
                      {activeSource.text ||
                        "未识别文本。请配置 OCR 或查看原图后人工转录。"}
                    </div>
                    <div className="source-actions">
                      {currentCase.mode === "formal" && (
                        <button
                          className="text-button"
                          onClick={() => {
                            setForm({
                              text: activeSource.text,
                              block_id: activeSource.id,
                              document_id: activeSource.document_id,
                            });
                            setModal("correction");
                          }}
                        >
                          校正并生成新版本
                        </button>
                      )}
                    </div>
                    <div className="anchor-list">
                      {blocks.map((b: Obj, i: number) => (
                        <button
                          className={activeSource.id === b.id ? "selected" : ""}
                          key={b.id}
                          onClick={() => setSource(b)}
                        >
                          <span>{String(i + 1).padStart(2, "0")}</span>
                          <span>{b.text.slice(0, 35) || b.locator}</span>
                        </button>
                      ))}
                    </div>
                  </>
                ) : (
                  <Empty
                    title="尚无材料"
                    detail="上传材料后在此查看原文与来源位置。"
                  />
                )}
              </section>

              <section className="work-panel">
                <div className="panel-heading">
                  <h3>
                    {tab === "facts"
                      ? "事实与证据"
                      : tab === "disclosure"
                        ? "逐项披露方案"
                        : tab === "risk"
                          ? "风险检验与审批"
                          : "事实摘要"}
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
                {tab === "facts" && (
                  <>
                    <div className="toolbar">
                      <p>{data.facts.length} 项事实 · 来源可追溯</p>
                      {currentCase.mode === "formal" && (
                        <div>
                          <button
                            className="secondary compact"
                            disabled={busy}
                            onClick={() =>
                              run(
                                () =>
                                  api("/cases/" + caseId + "/extract", "POST"),
                                "已进入边侧模型提取队列。",
                              )
                            }
                          >
                            边侧提取
                          </button>
                          <button
                            className="primary compact"
                            onClick={() => openFact()}
                          >
                            <Plus size={14} />
                            添加事实
                          </button>
                        </div>
                      )}
                    </div>
                    {data.facts.length ? (
                      data.facts.map((f: Obj, i: number) => (
                        <article className="fact-card" key={f.id}>
                          <div className="fact-meta">
                            <span className="fact-no">
                              F{String(i + 1).padStart(2, "0")}
                            </span>
                            <Tag>{txt(f.field)}</Tag>
                            <span
                              className={
                                "fact-state " + (f.stale ? "danger-text" : "")
                              }
                            >
                              {f.stale
                                ? "来源已更新"
                                : f.confirmed
                                  ? "已确认"
                                  : "待人工确认"}
                            </span>
                          </div>
                          <p>{f.value}</p>
                          <div className="fact-footer">
                            <button onClick={() => locate(f.source_ids)}>
                              <Link2 size={13} />
                              查看原文依据
                            </button>
                            <span>
                              {f.origin === "edge_model"
                                ? "边侧模型提取"
                                : f.origin === "synthetic"
                                  ? "合成标注"
                                  : "人工录入"}
                            </span>
                            {currentCase.mode === "formal" && (
                              <>
                                <button onClick={() => openFact(f)}>
                                  编辑
                                </button>
                                <button
                                  className="danger-text"
                                  onClick={() => {
                                    setForm(f);
                                    setModal("deleteFact");
                                  }}
                                >
                                  删除
                                </button>
                              </>
                            )}
                          </div>
                        </article>
                      ))
                    ) : (
                      <Empty
                        title="将材料整理为可核实事实"
                        detail="使用边侧模型提取，或选择原文片段后人工添加。"
                      />
                    )}
                    <div className="bottom-action">
                      <button
                        className="primary"
                        disabled={busy || !data.facts.length}
                        onClick={() =>
                          startTask(
                            currentCase.mode === "demo" ? "mock" : "cloud",
                          )
                        }
                      >
                        生成披露方案 <ArrowRight size={15} />
                      </button>
                    </div>
                  </>
                )}

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
                            {t.transport === "mock" ? "模拟" : "云端 API"} ·{" "}
                            {txt(t.status)}
                          </option>
                        ))}
                      </select>
                      <button
                        className="text-button"
                        onClick={() =>
                          startTask(
                            currentCase.mode === "demo" ? "mock" : "cloud",
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
                    {tab === "disclosure" && (
                      <>
                        <div className="context-note">
                          <LockKeyhole size={14} />
                          仅下方披露内容会进入请求；原文和身份映射保留在边侧。
                        </div>
                        {task.decisions.map((d: Obj, i: number) => (
                          <article className="decision-card" key={d.fact_id}>
                            <div className="fact-meta">
                              <span className="fact-no">
                                F{String(i + 1).padStart(2, "0")}
                              </span>
                              <Tag>{txt(d.field)}</Tag>
                              <select
                                aria-label={`字段 ${i + 1} 必要性`}
                                disabled={
                                  busy ||
                                  task.stale ||
                                  [
                                    "complete",
                                    "unknown",
                                    "stopped",
                                    "queued",
                                    "sending",
                                    "failed",
                                  ].includes(task.status)
                                }
                                value={d.necessity}
                                onChange={(e) =>
                                  editDecision(d, { necessity: e.target.value })
                                }
                              >
                                {[
                                  "required",
                                  "conditional",
                                  "unnecessary",
                                  "uncertain",
                                ].map((v) => (
                                  <option key={v} value={v}>
                                    {txt(v)}
                                  </option>
                                ))}
                              </select>
                            </div>
                            <div className="transform-options">
                              {[
                                "keep",
                                "pseudonymize",
                                "generalize",
                                "delete",
                              ].map((v) => (
                                <button
                                  disabled={
                                    busy ||
                                    task.stale ||
                                    [
                                      "complete",
                                      "unknown",
                                      "stopped",
                                      "queued",
                                      "sending",
                                      "failed",
                                    ].includes(task.status)
                                  }
                                  className={d.transform === v ? "active" : ""}
                                  key={v}
                                  onClick={() =>
                                    editDecision(d, { transform: v })
                                  }
                                >
                                  {txt(v)}
                                </button>
                              ))}
                            </div>
                            <div
                              className={
                                "disclosed-text " + (!d.output ? "deleted" : "")
                              }
                            >
                              {d.output || "此项已删除，不进入外发内容。"}
                            </div>
                            <small className="reason">{d.reason}</small>
                            <div className="fact-footer">
                              <button
                                onClick={() =>
                                  locate(
                                    task.fact_snapshot.find(
                                      (f: Obj) => f.id === d.fact_id,
                                    )?.source_ids || [],
                                  )
                                }
                              >
                                <Link2 size={13} />
                                查看依据
                              </button>
                              {currentCase.mode === "formal" && (
                                <button
                                  onClick={() => {
                                    setForm({ ...d });
                                    setModal("output");
                                  }}
                                >
                                  编辑披露文本
                                </button>
                              )}
                            </div>
                          </article>
                        ))}
                        <div className="bottom-action">
                          <button
                            className="primary"
                            disabled={busy || task.stale}
                            onClick={() =>
                              run(async () => {
                                await api(
                                  "/tasks/" + task.id + "/evaluate",
                                  "POST",
                                );
                                setTab("risk");
                              })
                            }
                          >
                            检验风险并冻结请求 <ArrowRight size={15} />
                          </button>
                        </div>
                      </>
                    )}

                    {tab === "risk" && (
                      <>
                        {task.risk ? (
                          <>
                            <div
                              className={
                                "risk-banner " +
                                (task.risk.blockers.length
                                  ? "blocked"
                                  : "ready")
                              }
                            >
                              <ShieldCheck size={28} />
                              <div>
                                <h2>
                                  {task.risk.blockers.length
                                    ? "当前请求已阻断"
                                    : "合成演示请求可审批"}
                                </h2>
                                <p>
                                  完整风险检验：
                                  {task.risk.completion === "complete"
                                    ? "已完成"
                                    : "未完成"}{" "}
                                  · 不代表已证明安全
                                </p>
                              </div>
                            </div>
                            {task.risk.blockers.map((b: string) => (
                              <div key={b} className="blocker">
                                <AlertTriangle size={15} />
                                {b}
                              </div>
                            ))}
                            <h4 className="subheading">风险检查记录</h4>
                            <div className="attack-list">
                              {task.risk.attacks.map((a: Obj) => (
                                <div key={a.kind}>
                                  <span>{txt(a.kind)}</span>
                                  <Tag tone="amber">未实现 · 未运行</Tag>
                                </div>
                              ))}
                            </div>
                            {task.risk.findings.map((f: string, i: number) => (
                              <p className="finding" key={i}>
                                {f}
                              </p>
                            ))}
                            <details className="request-detail" open>
                              <summary>
                                完整请求快照 <Tag>v{task.version}</Tag>
                              </summary>
                              <div className="request-target">
                                <b>目标</b>
                                {task.request.target}
                                <b>模型</b>
                                {task.request.body.model}
                              </div>
                              <pre>
                                {JSON.stringify(task.request.body, null, 2)}
                              </pre>
                              <small>SHA-256 · {task.request_hash}</small>
                            </details>
                            <div className="approval-actions">
                              {task.status === "review" && (
                                <button
                                  className="primary"
                                  disabled={busy}
                                  onClick={() => setModal("approve")}
                                >
                                  <Check size={16} />
                                  审批当前完整请求
                                </button>
                              )}
                              {task.status === "approved" && (
                                <button
                                  className="primary"
                                  disabled={busy}
                                  onClick={() => taskAction("send")}
                                >
                                  <Play size={15} />
                                  {task.transport === "mock"
                                    ? "执行模拟调用"
                                    : "发送至已批准云端"}
                                </button>
                              )}
                              {task.status === "unknown" && (
                                <button
                                  className="secondary"
                                  onClick={() => taskAction("reconcile")}
                                >
                                  查询网关记录（不重发）
                                </button>
                              )}
                              <button
                                className="secondary"
                                disabled={
                                  busy ||
                                  [
                                    "queued",
                                    "sending",
                                    "complete",
                                    "unknown",
                                  ].includes(task.status)
                                }
                                onClick={() => taskAction("evaluate")}
                              >
                                重新检验
                              </button>
                              <button
                                className="text-button danger-text"
                                disabled={
                                  busy ||
                                  [
                                    "queued",
                                    "sending",
                                    "complete",
                                    "unknown",
                                  ].includes(task.status)
                                }
                                onClick={() => taskAction("stop")}
                              >
                                停止任务
                              </button>
                            </div>
                            {task.status === "complete" && (
                              <button
                                className="primary"
                                onClick={() => setTab("result")}
                              >
                                查看摘要与回链 <ArrowRight size={16} />
                              </button>
                            )}
                            {task.error && (
                              <div className="inline-warning">{task.error}</div>
                            )}
                          </>
                        ) : (
                          <div className="empty">
                            <ShieldCheck size={30} />
                            <h3>检验当前披露方案</h3>
                            <p>冻结请求后，查看完整发送内容与阻断原因。</p>
                            <button
                              className="primary"
                              onClick={() => taskAction("evaluate")}
                            >
                              开始检验
                            </button>
                          </div>
                        )}
                      </>
                    )}

                    {tab === "result" && (
                      <>
                        {task.artifact ? (
                          <>
                            <div className="result-heading">
                              <Tag
                                tone={
                                  task.artifact.provenance === "simulation"
                                    ? "amber"
                                    : "green"
                                }
                              >
                                {task.artifact.provenance === "simulation"
                                  ? "模拟结果 · 非模型生成"
                                  : "云端 API 返回"}
                              </Tag>
                              <a
                                className="text-button"
                                href={`/api/v1/tasks/${task.id}/export`}
                              >
                                <Download size={14} />
                                导出 JSON
                              </a>
                            </div>
                            <p className="context-note">
                              身份仅在边侧回填；请逐项对照原文后确认。
                            </p>
                            {task.artifact.claims.map((c: Obj, i: number) => (
                              <article className="claim-card" key={c.id}>
                                <div className="fact-meta">
                                  <span className="fact-no">
                                    {String(i + 1).padStart(2, "0")}
                                  </span>
                                  <Tag tone={c.reviewed ? "green" : "amber"}>
                                    {c.reviewed
                                      ? "律师已复核"
                                      : c.status === "source_matched"
                                        ? "引用文本匹配"
                                        : "需人工复核"}
                                  </Tag>
                                </div>
                                <p>{c.local_text || c.text}</p>
                                {c.issues.map((issue: string) => (
                                  <small className="claim-issue" key={issue}>
                                    <AlertTriangle size={12} />
                                    {issue}
                                  </small>
                                ))}
                                <div className="fact-footer">
                                  <button onClick={() => locate(c.anchors)}>
                                    <Link2 size={13} />
                                    回到原文
                                  </button>
                                  <button
                                    disabled={busy || c.reviewed || task.stale}
                                    onClick={() =>
                                      taskAction("claims/" + c.id + "/review")
                                    }
                                  >
                                    {c.reviewed ? "已确认" : "已核对本项"}
                                  </button>
                                </div>
                              </article>
                            ))}
                            <div className="bottom-action">
                              <button
                                className="primary"
                                disabled={
                                  busy ||
                                  task.artifact.confirmed ||
                                  task.stale ||
                                  !task.artifact.claims.every(
                                    (c: Obj) => c.reviewed,
                                  )
                                }
                                onClick={() => taskAction("confirm")}
                              >
                                <Check size={15} />
                                {task.artifact.confirmed
                                  ? "结果已确认"
                                  : "确认最终结果"}
                              </button>
                            </div>
                          </>
                        ) : (
                          <Empty
                            title="尚无摘要结果"
                            detail="完成审批和调用后，结果会在此进入来源校核。"
                          />
                        )}
                      </>
                    )}
                  </>
                )}
              </section>
              <aside className="context-panel">
                <div className="panel-heading">
                  <h3>依据与运行边界</h3>
                  <CircleHelp size={16} />
                </div>
                <div className="boundary-card">
                  <LockKeyhole size={20} />
                  <h4>原文始终留在边侧</h4>
                  <p>身份映射、内部理由和评分真值不会自动进入云端请求。</p>
                </div>
                <dl className="metadata">
                  <dt>运行模式</dt>
                  <dd>
                    {currentCase.mode === "demo" ? "固定合成演示" : "正式案件"}
                  </dd>
                  <dt>当前任务</dt>
                  <dd>事实摘要</dd>
                  <dt>规则版本</dt>
                  <dd>{task?.pack_id || "尚未绑定"}</dd>
                  <dt>调用方式</dt>
                  <dd>
                    {task
                      ? task.transport === "mock"
                        ? "模拟调用（不访问云端）"
                        : "云端大模型 API"
                      : "待创建任务"}
                  </dd>
                </dl>
                {currentCase.mode === "demo" && (
                  <button
                    className="secondary full"
                    disabled={busy}
                    onClick={() => startTask("cloud")}
                  >
                    <ExternalLink size={14} />
                    新建真实 API 演示任务
                  </button>
                )}
                <div className="context-divider" />
                <h4 className="aside-title">
                  操作留痕
                  <a
                    href={`/api/v1/cases/${caseId}/audit-export`}
                    title="导出审计"
                  >
                    <Download size={14} />
                  </a>
                </h4>
                <div className="audit-list">
                  {data.audit
                    .slice(-8)
                    .reverse()
                    .map((e: Obj) => (
                      <div key={e.id}>
                        <span className="audit-dot" />
                        <div>
                          <b>{e.event}</b>
                          <small>
                            {new Date(e.at).toLocaleTimeString("zh-CN")}
                          </small>
                        </div>
                      </div>
                    ))}
                </div>
                <p className="small-note">
                  风险攻击未实现时不会显示“通过”。正式案件当前保持外发阻断。
                </p>
              </aside>
            </div>
          </div>
        )}

        {page === "settings" && (
          <div className="content settings-page">
            <div className="section-heading">
              <div>
                <div className="eyebrow">EDGE & CLOUD</div>
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
                  <p>{cap?.[key]?.detail || "正在检查配置"}</p>
                </div>
              ))}
            </div>
            {boot && (
              <SettingsForm
                value={boot.settings}
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
        {page === "registry" && (
          <div className="content">
            <div className="section-heading">
              <div>
                <div className="eyebrow">EXTENSIBLE BY DESIGN</div>
                <h1>能力与知识包</h1>
                <p>案由与任务独立扩展，共用审批、外发和来源回链。</p>
              </div>
              <Tag>版本化注册</Tag>
            </div>
            <h2 className="subheading">任务能力</h2>
            <div className="capability-grid">
              {boot?.tasks.map((t: Obj) => (
                <div className="capability" key={t.id}>
                  <div>
                    <b>{t.name}</b>
                    <Tag tone={t.available ? "green" : "neutral"}>
                      {t.available ? "已实现" : "尚未开放"}
                    </Tag>
                  </div>
                  <p>
                    {t.id} · {t.version}
                  </p>
                </div>
              ))}
            </div>
            <h2 className="subheading">案由知识包</h2>
            {boot?.packs.map((p: Obj) => (
              <div className="pack-card" key={p.id}>
                <div>
                  <h3>{p.name}</h3>
                  <Tag tone="amber">
                    {p.status === "demo"
                      ? "演示规则"
                      : p.status === "draft"
                        ? "草稿 / 测试"
                        : "已发布"}
                  </Tag>
                </div>
                <p>
                  {p.version} · {p.fact_fields.map(txt).join(" / ")}
                </p>
                <small>{p.references.join(" ")}</small>
                <details>
                  <summary>查看字段规则与依据</summary>
                  <pre>{JSON.stringify(p.rules, null, 2)}</pre>
                </details>
              </div>
            ))}
            <div className="context-note">
              正式规则通过命令行校验并导入，已有版本不可覆盖；知识包不能执行任意代码。
            </div>
          </div>
        )}
      </main>

      {modal && (
        <div className="modal-backdrop" onClick={() => !busy && setModal("")}>
          <div
            className="modal"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
          >
            <button
              className="modal-close"
              aria-label="关闭对话框"
              onClick={() => setModal("")}
            >
              <X size={20} />
            </button>
            {modal === "case" && (
              <>
                <div className="eyebrow">NEW CASE</div>
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
                      {Array.from(
                        new Set<string>(
                          (boot?.packs || [])
                            .filter(
                              (p: Obj) => p.domain_id === currentCase?.domain,
                            )
                            .flatMap((p: Obj) => p.fact_fields),
                        ),
                      ).map((k) => (
                        <option key={k} value={k}>
                          {txt(k)}
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
                  请确认已阅读请求正文、目标服务、信息保留依据和残余风险。完整再识别检验尚未实现，本次只允许固定合成数据演示。
                </p>
                <div className="approval-summary">
                  <b>{task.request.body.model}</b>
                  <span>{task.request.target}</span>
                  <code>{task.request_hash}</code>
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
          </div>
        </div>
      )}
    </div>
  );
}

function SettingsForm({
  value,
  busy,
  save,
}: {
  value: Obj;
  busy: boolean;
  save: (v: Obj) => void;
}) {
  const [v, setV] = useState({
    cloud_url: value.cloud_url,
    cloud_model: value.cloud_model,
    edge_url: value.edge_url,
    edge_model: value.edge_model,
  });
  return (
    <form
      className="settings-form"
      onSubmit={(e) => {
        e.preventDefault();
        save(v);
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
        <p>使用兼容 Chat Completions 的 API。</p>
        <label>
          API 根地址
          <input
            value={v.cloud_url}
            onChange={(e) => setV({ ...v, cloud_url: e.target.value })}
          />
        </label>
        <label>
          云端模型名称
          <input
            value={v.cloud_model}
            placeholder="填写服务商提供的模型标识"
            onChange={(e) => setV({ ...v, cloud_model: e.target.value })}
          />
        </label>
      </div>
      <button className="primary" disabled={busy}>
        保存运行配置
      </button>
    </form>
  );
}
