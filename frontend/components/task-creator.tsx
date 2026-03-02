"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  createTask,
  CreateTaskInput,
  ExecutorCapability,
  Task,
  getExecutorOptions,
  getHealthStatus
} from "@/lib/api";
import { bi } from "@/lib/i18n";
import { resetTaskListClickCount, setTaskNavigationContext } from "@/lib/telemetry";

const DEFAULT_PRIORITY = 5;
const DEFAULT_TIMEOUT_SECONDS = 180;
const DEFAULT_REASONING_EFFORT = "medium";
const WORKDIR_HISTORY_KEY = "pocket_codex_workdir_history";
const TEMPLATE_STORAGE_KEY = "pocket_codex_task_templates";
const MAX_WORKDIR_HISTORY = 30;
const MAX_TEMPLATES = 20;

interface TaskCreatorProps {
  onCreated?: (task: Task) => void;
  workdirSuggestions?: string[];
  compact?: boolean;
}

interface TaskTemplate {
  id: string;
  name: string;
  prompt: string;
  priority: number;
  timeout_seconds: number;
  model?: string;
  reasoning_effort?: string;
  enable_parallel_agents?: boolean;
  workdir?: string;
  created_at: string;
}

function normalizeWorkdirList(items: string[]): string[] {
  return Array.from(new Set(items.map((item) => item.trim()).filter((item) => item.length > 0)));
}

function normalizeTemplate(raw: unknown): TaskTemplate | null {
  if (!raw || typeof raw !== "object") {
    return null;
  }
  const value = raw as Record<string, unknown>;
  if (
    typeof value.id !== "string" ||
    typeof value.name !== "string" ||
    typeof value.prompt !== "string" ||
    typeof value.priority !== "number" ||
    typeof value.timeout_seconds !== "number" ||
    typeof value.created_at !== "string"
  ) {
    return null;
  }
  const workdir = typeof value.workdir === "string" ? value.workdir : undefined;
  const model = typeof value.model === "string" ? value.model : undefined;
  const reasoning_effort =
    typeof value.reasoning_effort === "string" ? value.reasoning_effort : undefined;
  const enable_parallel_agents = Boolean(value.enable_parallel_agents);
  return {
    id: value.id,
    name: value.name,
    prompt: value.prompt,
    priority: value.priority,
    timeout_seconds: value.timeout_seconds,
    model,
    reasoning_effort,
    enable_parallel_agents,
    workdir,
    created_at: value.created_at
  };
}

export function TaskCreator({ onCreated, workdirSuggestions = [], compact = false }: TaskCreatorProps) {
  const router = useRouter();
  const [prompt, setPrompt] = useState("");
  const [priority, setPriority] = useState(DEFAULT_PRIORITY);
  const [timeoutSeconds, setTimeoutSeconds] = useState(DEFAULT_TIMEOUT_SECONDS);
  const [model, setModel] = useState("");
  const [reasoningEffort, setReasoningEffort] = useState(DEFAULT_REASONING_EFFORT);
  const [enableParallelAgents, setEnableParallelAgents] = useState(false);
  const [executorCapabilities, setExecutorCapabilities] = useState<ExecutorCapability | null>(null);
  const [minTimeoutSeconds, setMinTimeoutSeconds] = useState(5);
  const [workdir, setWorkdir] = useState("");
  const [workdirHistory, setWorkdirHistory] = useState<string[]>([]);
  const [templates, setTemplates] = useState<TaskTemplate[]>([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState("");
  const [templateName, setTemplateName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const raw = window.localStorage.getItem(WORKDIR_HISTORY_KEY);
    if (!raw) {
      return;
    }
    try {
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) {
        return;
      }
      const loaded = normalizeWorkdirList(
        parsed.filter((item): item is string => typeof item === "string")
      ).slice(0, MAX_WORKDIR_HISTORY);
      setWorkdirHistory(loaded);
    } catch {
      // Ignore malformed history payload.
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    getExecutorOptions()
      .then((result) => {
        if (cancelled) {
          return;
        }
        setExecutorCapabilities(result);
        if (result.model_options.length > 0) {
          setModel((previous) => previous.trim() || result.model_options[0]);
        }
        if (result.reasoning_effort_options.length > 0) {
          setReasoningEffort((previous) =>
            result.reasoning_effort_options.includes(previous)
              ? previous
              : result.reasoning_effort_options[0]
          );
        }
      })
      .catch(() => {
        if (!cancelled) {
          setExecutorCapabilities(null);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    getHealthStatus()
      .then((status) => {
        if (cancelled) {
          return;
        }
        const minTimeout =
          typeof status.codex_min_timeout_seconds === "number"
            ? Math.max(5, Math.floor(status.codex_min_timeout_seconds))
            : 5;
        setMinTimeoutSeconds(minTimeout);
        setTimeoutSeconds((previous) => (previous < minTimeout ? minTimeout : previous));
      })
      .catch(() => {
        if (!cancelled) {
          setMinTimeoutSeconds(5);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const raw = window.localStorage.getItem(TEMPLATE_STORAGE_KEY);
    if (!raw) {
      return;
    }
    try {
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) {
        return;
      }
      const loaded = parsed
        .map(normalizeTemplate)
        .filter((item): item is TaskTemplate => Boolean(item))
        .slice(0, MAX_TEMPLATES);
      setTemplates(loaded);
    } catch {
      // Ignore malformed template payload.
    }
  }, []);

  const disabled = useMemo(() => {
    return submitting || prompt.trim().length === 0;
  }, [submitting, prompt]);

  const mergedWorkdirOptions = useMemo(() => {
    return normalizeWorkdirList([...workdirHistory, ...workdirSuggestions]).slice(0, MAX_WORKDIR_HISTORY);
  }, [workdirHistory, workdirSuggestions]);

  const selectedTemplate = useMemo(
    () => templates.find((item) => item.id === selectedTemplateId) ?? null,
    [selectedTemplateId, templates]
  );
  const modelOptions = useMemo(() => {
    const fromExecutor = executorCapabilities?.model_options ?? [];
    if (model.trim() && !fromExecutor.includes(model.trim())) {
      return [model.trim(), ...fromExecutor];
    }
    return fromExecutor;
  }, [executorCapabilities?.model_options, model]);
  const reasoningOptions = useMemo(() => {
    const fromExecutor = executorCapabilities?.reasoning_effort_options ?? ["low", "medium", "high"];
    if (!fromExecutor.includes(reasoningEffort)) {
      return [reasoningEffort, ...fromExecutor];
    }
    return fromExecutor;
  }, [executorCapabilities?.reasoning_effort_options, reasoningEffort]);

  function saveWorkdirHistory(nextWorkdir: string): void {
    const trimmed = nextWorkdir.trim();
    if (!trimmed || typeof window === "undefined") {
      return;
    }
    const next = normalizeWorkdirList([trimmed, ...workdirHistory]).slice(0, MAX_WORKDIR_HISTORY);
    setWorkdirHistory(next);
    window.localStorage.setItem(WORKDIR_HISTORY_KEY, JSON.stringify(next));
  }

  function persistTemplates(nextTemplates: TaskTemplate[]): void {
    setTemplates(nextTemplates);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(TEMPLATE_STORAGE_KEY, JSON.stringify(nextTemplates));
    }
  }

  function applyTemplate(template: TaskTemplate): void {
    setPrompt(template.prompt);
    setPriority(template.priority);
    setTimeoutSeconds(template.timeout_seconds);
    setModel(template.model ?? "");
    setReasoningEffort(template.reasoning_effort || DEFAULT_REASONING_EFFORT);
    setEnableParallelAgents(Boolean(template.enable_parallel_agents));
    setWorkdir(template.workdir ?? "");
    setNote(bi("模板已填充到表单。", "Template applied to form."));
    setError(null);
  }

  function handleSaveTemplate(): void {
    const name = templateName.trim();
    const promptValue = prompt.trim();
    if (!name || !promptValue) {
      setError(bi("保存模板前请填写模板名称和任务指令。", "Fill template name and prompt before saving."));
      return;
    }
    const template: TaskTemplate = {
      id: `tpl_${Date.now().toString(36)}`,
      name,
      prompt: promptValue,
      priority,
      timeout_seconds: timeoutSeconds,
      model: model.trim() || undefined,
      reasoning_effort: reasoningEffort,
      enable_parallel_agents: enableParallelAgents,
      workdir: workdir.trim() || undefined,
      created_at: new Date().toISOString()
    };
    const nextTemplates = [template, ...templates].slice(0, MAX_TEMPLATES);
    persistTemplates(nextTemplates);
    setSelectedTemplateId(template.id);
    setTemplateName("");
    setNote(bi("模板已保存。", "Template saved."));
    setError(null);
  }

  function handleDeleteTemplate(): void {
    if (!selectedTemplateId) {
      return;
    }
    const nextTemplates = templates.filter((item) => item.id !== selectedTemplateId);
    persistTemplates(nextTemplates);
    setSelectedTemplateId("");
    setNote(bi("模板已删除。", "Template removed."));
    setError(null);
  }

  async function submitTask(input: CreateTaskInput): Promise<void> {
    setSubmitting(true);
    setError(null);
    setNote(null);

    try {
      const created = await createTask(input);
      const savedWorkdir = created.workdir || input.workdir?.trim();
      if (savedWorkdir) {
        saveWorkdirHistory(savedWorkdir);
      }
      setTaskNavigationContext(created.id, "create", 0);
      resetTaskListClickCount();
      setPrompt("");
      setModel("");
      setReasoningEffort(DEFAULT_REASONING_EFFORT);
      setEnableParallelAgents(false);
      setWorkdir("");
      onCreated?.(created);
      router.push(`/tasks/${created.id}`);
    } catch (submitError) {
      setError(
        submitError instanceof Error
          ? submitError.message
          : bi("创建任务失败。", "Failed to create task.")
      );
    } finally {
      setSubmitting(false);
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (disabled) {
      return;
    }
    await submitTask({
      prompt: prompt.trim(),
      priority,
      timeout_seconds: timeoutSeconds,
      model: model.trim() || undefined,
      reasoning_effort: reasoningEffort,
      enable_parallel_agents: enableParallelAgents,
      workdir: workdir.trim() || undefined
    });
  }

  async function handleCreateFromTemplate(): Promise<void> {
    if (!selectedTemplate || submitting) {
      return;
    }
    await submitTask({
      prompt: selectedTemplate.prompt,
      priority: selectedTemplate.priority,
      timeout_seconds: selectedTemplate.timeout_seconds,
      model: selectedTemplate.model,
      reasoning_effort: selectedTemplate.reasoning_effort || DEFAULT_REASONING_EFFORT,
      enable_parallel_agents: Boolean(selectedTemplate.enable_parallel_agents),
      workdir: selectedTemplate.workdir
    });
  }

  return (
    <section className="panel animate-rise" id="create-task-panel">
      <div className="panel-title-row">
        <h2 className="panel-title">{bi("创建任务", "Create Task")}</h2>
        <span className="chip">{bi("移动优先", "Mobile First")}</span>
      </div>
      <form className="stack" onSubmit={handleSubmit}>
        {!compact ? (
          <div className="detail-block">
            <h3>{bi("模板库", "Template Library")}</h3>
            <div className="stack">
              <div className="template-grid">
                <label className="field">
                  <span>{bi("已保存模板", "Saved templates")}</span>
                  <select
                    value={selectedTemplateId}
                    onChange={(event) => {
                      setSelectedTemplateId(event.target.value);
                    }}
                  >
                    <option value="">
                      {templates.length > 0
                        ? bi("选择模板", "Select template")
                        : bi("暂无模板", "No templates yet")}
                    </option>
                    {templates.map((template) => (
                      <option key={template.id} value={template.id}>
                        {template.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  <span>{bi("新模板名称", "New template name")}</span>
                  <input
                    type="text"
                    value={templateName}
                    onChange={(event) => setTemplateName(event.target.value)}
                    placeholder={bi("例如：回归检查模板", "Example: Regression template")}
                  />
                </label>
              </div>
              <div className="pagination-actions compact-actions">
                <button
                  className="button button-secondary"
                  type="button"
                  onClick={handleSaveTemplate}
                  disabled={submitting}
                >
                  {bi("保存当前为模板", "Save current as template")}
                </button>
                {selectedTemplate ? (
                  <>
                    <button
                      className="button button-secondary"
                      type="button"
                      disabled={submitting}
                      onClick={() => {
                        applyTemplate(selectedTemplate);
                      }}
                    >
                      {bi("应用模板", "Apply template")}
                    </button>
                    <button
                      className="button"
                      type="button"
                      disabled={submitting}
                      onClick={() => {
                        void handleCreateFromTemplate();
                      }}
                    >
                      {bi("一键创建任务", "Create from template")}
                    </button>
                    <details className="template-more-actions">
                      <summary className="link">{bi("更多操作", "More actions")}</summary>
                      <div className="pagination-actions compact-actions">
                        <button
                          className="button button-secondary"
                          type="button"
                          disabled={submitting}
                          onClick={handleDeleteTemplate}
                        >
                          {bi("删除模板", "Delete template")}
                        </button>
                      </div>
                    </details>
                  </>
                ) : null}
              </div>
            </div>
          </div>
        ) : null}

        <label className="field">
          <span>{bi("任务指令", "Prompt")}</span>
          <textarea
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            rows={4}
            placeholder={bi("请输入可执行的任务指令...", "Ask Codex to do something actionable...")}
            required
          />
        </label>

        {compact ? (
          <details className="detail-block">
            <summary className="link">{bi("高级设置", "Advanced settings")}</summary>
            <div className="stack" style={{ marginTop: "10px" }}>
              <div className="row">
                <label className="field">
                  <span>{bi("优先级", "Priority")}</span>
                  <input
                    type="number"
                    min={1}
                    max={10}
                    value={priority}
                    onChange={(event) => setPriority(Number(event.target.value) || DEFAULT_PRIORITY)}
                  />
                </label>
                <label className="field">
                  <span>{bi("超时(秒)", "Timeout (sec)")}</span>
                  <input
                    type="number"
                    min={minTimeoutSeconds}
                    max={3600}
                    value={timeoutSeconds}
                    onChange={(event) =>
                      setTimeoutSeconds(
                        Math.max(minTimeoutSeconds, Number(event.target.value) || DEFAULT_TIMEOUT_SECONDS)
                      )
                    }
                  />
                  <small className="muted">
                    {bi("最小可用超时", "Minimum timeout")}: {minTimeoutSeconds}s
                  </small>
                </label>
              </div>
              <div className="row">
                <label className="field">
                  <span>{bi("模型(可选)", "Model (optional)")}</span>
                  <select
                    value={model}
                    onChange={(event) => setModel(event.target.value)}
                    disabled={modelOptions.length === 0}
                  >
                    {modelOptions.length === 0 ? (
                      <option value="">{bi("未获取到模型列表", "Model list unavailable")}</option>
                    ) : null}
                    {modelOptions.map((item) => (
                      <option key={item} value={item}>
                        {item}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  <span>{bi("推理强度", "Reasoning Effort")}</span>
                  <select
                    value={reasoningEffort}
                    onChange={(event) => setReasoningEffort(event.target.value)}
                    disabled={reasoningOptions.length === 0}
                  >
                    {reasoningOptions.map((item) => (
                      <option key={item} value={item}>
                        {item === "low" ? bi("低", "Low") : item === "high" ? bi("高", "High") : bi("中", "Medium")}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <label className="field field-inline">
                <span>{bi("多代理并行执行", "Parallel multi-agent execution")}</span>
                <input
                  type="checkbox"
                  checked={enableParallelAgents}
                  disabled={executorCapabilities?.supports_parallel_agents === false}
                  onChange={(event) => setEnableParallelAgents(event.target.checked)}
                />
              </label>
              <div className="row">
                <label className="field">
                  <span>{bi("历史目录快速选择", "Quick pick from history")}</span>
                  <select
                    defaultValue=""
                    disabled={mergedWorkdirOptions.length === 0}
                    onChange={(event) => {
                      const selected = event.target.value;
                      if (selected) {
                        setWorkdir(selected);
                      }
                    }}
                  >
                    <option value="">
                      {mergedWorkdirOptions.length > 0
                        ? bi("请选择历史工作目录", "Select a previous workdir")
                        : bi("暂无历史目录", "No workdir history yet")}
                    </option>
                    {mergedWorkdirOptions.map((path) => (
                      <option key={path} value={path}>
                        {path}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  <span>{bi("工作目录(可选)", "Workdir (optional)")}</span>
                  <input
                    type="text"
                    value={workdir}
                    onChange={(event) => setWorkdir(event.target.value)}
                    list="workdir-history-options"
                    placeholder="/Users/slg/workspace/Pocket-Codex"
                  />
                  <datalist id="workdir-history-options">
                    {mergedWorkdirOptions.map((path) => (
                      <option key={`hint-${path}`} value={path} />
                    ))}
                  </datalist>
                </label>
              </div>
              {executorCapabilities ? (
                <p className="muted">
                  {bi("能力来源", "Options source")}: {executorCapabilities.source}
                </p>
              ) : (
                <p className="muted">
                  {bi("模型与推理强度暂未从 CLI 读取到，先使用默认值。", "Model and reasoning options are temporarily unavailable from CLI.")}
                </p>
              )}
            </div>
          </details>
        ) : (
          <>
            <div className="row">
              <label className="field">
                <span>{bi("优先级", "Priority")}</span>
                <input
                  type="number"
                  min={1}
                  max={10}
                  value={priority}
                  onChange={(event) => setPriority(Number(event.target.value) || DEFAULT_PRIORITY)}
                />
              </label>
              <label className="field">
                <span>{bi("超时(秒)", "Timeout (sec)")}</span>
                <input
                  type="number"
                  min={minTimeoutSeconds}
                  max={3600}
                  value={timeoutSeconds}
                  onChange={(event) =>
                    setTimeoutSeconds(
                      Math.max(minTimeoutSeconds, Number(event.target.value) || DEFAULT_TIMEOUT_SECONDS)
                    )
                  }
                />
                <small className="muted">
                  {bi("最小可用超时", "Minimum timeout")}: {minTimeoutSeconds}s
                </small>
              </label>
            </div>

            <div className="row">
              <label className="field">
                <span>{bi("模型(可选)", "Model (optional)")}</span>
                <select
                  value={model}
                  onChange={(event) => setModel(event.target.value)}
                  disabled={modelOptions.length === 0}
                >
                  {modelOptions.length === 0 ? (
                    <option value="">{bi("未获取到模型列表", "Model list unavailable")}</option>
                  ) : null}
                  {modelOptions.map((item) => (
                    <option key={item} value={item}>
                      {item}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span>{bi("推理强度", "Reasoning Effort")}</span>
                <select
                  value={reasoningEffort}
                  onChange={(event) => setReasoningEffort(event.target.value)}
                  disabled={reasoningOptions.length === 0}
                >
                  {reasoningOptions.map((item) => (
                    <option key={item} value={item}>
                      {item === "low" ? bi("低", "Low") : item === "high" ? bi("高", "High") : bi("中", "Medium")}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            <label className="field field-inline">
              <span>{bi("多代理并行执行", "Parallel multi-agent execution")}</span>
              <input
                type="checkbox"
                checked={enableParallelAgents}
                disabled={executorCapabilities?.supports_parallel_agents === false}
                onChange={(event) => setEnableParallelAgents(event.target.checked)}
              />
            </label>
            {executorCapabilities ? (
              <p className="muted">
                {bi("能力来源", "Options source")}: {executorCapabilities.source}
              </p>
            ) : (
              <p className="muted">
                {bi("模型与推理强度暂未从 CLI 读取到，先使用默认值。", "Model and reasoning options are temporarily unavailable from CLI.")}
              </p>
            )}
            <p className="muted">
              {bi(
                "策略提示：低推理更快更省，高推理更稳；并行多代理通常更快但成本更高。",
                "Strategy hint: low reasoning is faster/cheaper, high reasoning is steadier; parallel agents are usually faster but cost more."
              )}
            </p>

            <div className="row">
              <label className="field">
                <span>{bi("历史目录快速选择", "Quick pick from history")}</span>
                <select
                  defaultValue=""
                  disabled={mergedWorkdirOptions.length === 0}
                  onChange={(event) => {
                    const selected = event.target.value;
                    if (selected) {
                      setWorkdir(selected);
                    }
                  }}
                >
                  <option value="">
                    {mergedWorkdirOptions.length > 0
                      ? bi("请选择历史工作目录", "Select a previous workdir")
                      : bi("暂无历史目录", "No workdir history yet")}
                  </option>
                  {mergedWorkdirOptions.map((path) => (
                    <option key={path} value={path}>
                      {path}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span>{bi("工作目录(可选)", "Workdir (optional)")}</span>
                <input
                  type="text"
                  value={workdir}
                  onChange={(event) => setWorkdir(event.target.value)}
                  list="workdir-history-options"
                  placeholder="/Users/slg/workspace/Pocket-Codex"
                />
                <datalist id="workdir-history-options">
                  {mergedWorkdirOptions.map((path) => (
                    <option key={`hint-${path}`} value={path} />
                  ))}
                </datalist>
              </label>
            </div>
          </>
        )}
        {mergedWorkdirOptions.length === 0 ? (
          <p className="muted">
            {bi(
              "先创建一次任务后即可在这里快速复用工作目录。",
              "Create one task first, then you can quickly reuse workdirs here."
            )}
          </p>
        ) : null}

        {error ? <p className="error">{error}</p> : null}
        {note ? <p className="note">{note}</p> : null}

        <div className="mobile-sticky-actions">
          <button className="button" type="submit" disabled={disabled}>
            {submitting ? bi("创建中...", "Creating...") : bi("创建任务", "Create Task")}
          </button>
        </div>
      </form>
    </section>
  );
}
