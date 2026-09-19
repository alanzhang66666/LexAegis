export type RecordingProvider = { id: string; name: string; model: string; endpoint: string; purpose: string; regions: string; retention: string; notes: string; status: string };
export function loadRecordingProviders(): RecordingProvider[] {
  try {
    const rows = JSON.parse(sessionStorage.getItem("lex_recording_providers") || "null");
    if (Array.isArray(rows) && rows.every(row => row && typeof row.id === "string")) return rows;
  } catch { /* Use the presentation defaults when storage is unavailable. */ }
  return [{id:"recording-deepseek",name:"DeepSeek 主模型服务",model:"DeepSeek V4.1 Flash",endpoint:"https://api.deepseek.com/v1",
    purpose:"工资争议事实摘要",regions:"按实际服务协议登记",retention:"按实际服务协议登记",notes:"仅处理经人工批准的请求范围。",status:"页面已配置"}];
}
