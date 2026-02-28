"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useMemo, useState } from "react";
import { createTask, Task } from "@/lib/api";

const DEFAULT_PRIORITY = 5;

interface TaskCreatorProps {
  onCreated?: (task: Task) => void;
}

export function TaskCreator({ onCreated }: TaskCreatorProps) {
  const router = useRouter();
  const [prompt, setPrompt] = useState("");
  const [priority, setPriority] = useState(DEFAULT_PRIORITY);
  const [timeoutSeconds, setTimeoutSeconds] = useState(20);
  const [workdir, setWorkdir] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const disabled = useMemo(() => {
    return submitting || prompt.trim().length === 0;
  }, [submitting, prompt]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (disabled) {
      return;
    }

    setSubmitting(true);
    setError(null);

    try {
      const created = await createTask({
        prompt: prompt.trim(),
        priority,
        timeout_seconds: timeoutSeconds,
        workdir: workdir.trim() || undefined
      });

      setPrompt("");
      setWorkdir("");
      onCreated?.(created);
      router.push(`/tasks/${created.id}`);
    } catch (submitError) {
      setError(
        submitError instanceof Error ? submitError.message : "Failed to create task."
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="panel animate-rise">
      <div className="panel-title-row">
        <h2 className="panel-title">Create Task</h2>
        <span className="chip">Mobile First</span>
      </div>
      <form className="stack" onSubmit={handleSubmit}>
        <label className="field">
          <span>Prompt</span>
          <textarea
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            rows={4}
            placeholder="Ask Codex to do something actionable..."
            required
          />
        </label>

        <div className="row">
          <label className="field">
            <span>Priority</span>
            <input
              type="number"
              min={1}
              max={10}
              value={priority}
              onChange={(event) => setPriority(Number(event.target.value) || DEFAULT_PRIORITY)}
            />
          </label>
          <label className="field">
            <span>Timeout (sec)</span>
            <input
              type="number"
              min={5}
              max={3600}
              value={timeoutSeconds}
              onChange={(event) => setTimeoutSeconds(Number(event.target.value) || 20)}
            />
          </label>
        </div>

        <div className="row">
          <label className="field">
            <span>Workdir (optional)</span>
            <input
              type="text"
              value={workdir}
              onChange={(event) => setWorkdir(event.target.value)}
              placeholder="/Users/slg/workspace/Pocket-Codex"
            />
          </label>
        </div>

        {error ? <p className="error">{error}</p> : null}

        <button className="button" type="submit" disabled={disabled}>
          {submitting ? "Creating..." : "Create Task"}
        </button>
      </form>
    </section>
  );
}
