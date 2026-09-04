import { FlaskConical, ServerCog, ShieldAlert } from "lucide-react";
import { Panel, StatusBadge } from "../components/ui";

type Obj = Record<string, any>;

export function ProviderCenter({ providers = [] }: { providers?: Obj[] }) {
  return <div className="content governance-page">
    <div className="section-heading"><div><div className="eyebrow">PROVIDER GOVERNANCE</div><h1>服务商治理</h1><p>处理角色、地区、留存、训练使用和影响评估必须由人员登记，不使用 IP 推断。</p></div><ServerCog /></div>
    {!providers.length ? <div className="legal-block"><ShieldAlert /><div><h3>正式外发被阻断</h3><p>尚无经复核的服务商档案。关键字段未知时不会显示为可用。</p></div></div> :
      <div className="capability-grid">{providers.map(provider => <Panel key={provider.id} title={provider.name}><p>{provider.processing_regions?.join(" / ") || "处理地区未知"}</p><StatusBadge tone={provider.status === "reviewed" ? "green" : "amber"}>{provider.status}</StatusBadge></Panel>)}</div>}
  </div>;
}

export function BenchmarkCenter({ protocols = [] }: { protocols?: Obj[] }) {
  const frozen = protocols.filter(item => item.status === "frozen").length;
  return <div className="content governance-page">
    <div className="section-heading"><div><div className="eyebrow">ISOLATED RESEARCH</div><h1>隔离实验</h1><p>Ianvs 的 DP、掩码、投影与 MIA 只在无案件卷、无 mapping、无网关密钥的环境运行。</p></div><FlaskConical /></div>
    <div className="legal-block"><ShieldAlert /><div><h3>不进入生产 dispatch</h3><p>已冻结攻击协议 {frozen}/4。not_run、error、uncertain 与 not_applicable 均不能充当通过。</p></div></div>
    <Panel title="ianvs-pipl profile"><code>lexaegis bench --profile ianvs-pipl</code><p>必须提供真实向量或真实目标模型输出；缺失输入时返回 not_applicable，不生成伪指标。</p></Panel>
  </div>;
}
