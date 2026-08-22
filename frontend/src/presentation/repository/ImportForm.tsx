/**
 * ImportForm component.
 *
 * Purpose:       Collect a project name and a repository source (ZIP upload or Git
 *                URL) and hand them to the pipeline.
 * Responsibility: Presentation and local form state only — it does not call the API
 *                 itself; the parent passes `onImport` from the pipeline hook.
 * Why it exists: The first two steps of the slice (create project, import
 *                repository) are one user intent, so they are one form.
 * Depends on:    application/pipeline/useRepositoryPipeline.ts (for `ImportSource`).
 * Depended on by: presentation/pipeline/PipelinePanel.tsx.
 */

import { useState } from "react";

import type { ImportSource } from "@/application/pipeline/useRepositoryPipeline";

const INPUT_CLASS =
  "w-full rounded-md border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm " +
  "text-neutral-100 placeholder-neutral-500 focus:border-neutral-500 focus:outline-none " +
  "disabled:opacity-50";

const LABEL_CLASS = "mb-1 block text-xs uppercase tracking-wide text-neutral-500";

interface ImportFormProps {
  isPending: boolean;
  error: string | null;
  disabled: boolean;
  onImport: (projectName: string, source: ImportSource) => void;
}

export function ImportForm({ isPending, error, disabled, onImport }: ImportFormProps) {
  const [kind, setKind] = useState<"zip" | "git">("zip");
  const [projectName, setProjectName] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [gitUrl, setGitUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);

  const trimmedName = projectName.trim();
  const canSubmit =
    !disabled &&
    !isPending &&
    trimmedName.length > 0 &&
    (kind === "zip" ? file !== null : gitUrl.trim().length > 0);

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!canSubmit) return;

    if (kind === "zip" && file) {
      const trimmedDisplay = displayName.trim();
      onImport(trimmedName, {
        kind: "zip",
        file,
        ...(trimmedDisplay ? { displayName: trimmedDisplay } : {}),
      });
    } else if (kind === "git") {
      onImport(trimmedName, { kind: "git", url: gitUrl.trim() });
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label className={LABEL_CLASS} htmlFor="project-name">
          Project name
        </label>
        <input
          id="project-name"
          className={INPUT_CLASS}
          value={projectName}
          maxLength={200}
          disabled={disabled || isPending}
          placeholder="my-analysis"
          onChange={(e) => setProjectName(e.target.value)}
        />
      </div>

      <div className="flex gap-2" role="group" aria-label="Import source">
        {(["zip", "git"] as const).map((option) => (
          <button
            key={option}
            type="button"
            aria-pressed={kind === option}
            disabled={disabled || isPending}
            onClick={() => setKind(option)}
            className={
              "rounded-md px-3 py-1.5 text-sm disabled:opacity-50 " +
              (kind === option
                ? "bg-neutral-100 font-medium text-neutral-900"
                : "bg-neutral-800 text-neutral-300 hover:bg-neutral-700")
            }
          >
            {option === "zip" ? "ZIP upload" : "Git URL"}
          </button>
        ))}
      </div>

      {kind === "zip" ? (
        <div className="space-y-4">
          <div>
            <label className={LABEL_CLASS} htmlFor="zip-file">
              ZIP archive
            </label>
            <input
              id="zip-file"
              type="file"
              accept=".zip,application/zip"
              disabled={disabled || isPending}
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className={
                "w-full text-sm text-neutral-400 disabled:opacity-50 " +
                "file:mr-3 file:rounded-md file:border-0 file:bg-neutral-800 " +
                "file:px-3 file:py-1.5 file:text-sm file:text-neutral-200"
              }
            />
          </div>
          <div>
            <label className={LABEL_CLASS} htmlFor="display-name">
              Display name (optional)
            </label>
            <input
              id="display-name"
              className={INPUT_CLASS}
              value={displayName}
              disabled={disabled || isPending}
              placeholder="Defaults to the archive name"
              onChange={(e) => setDisplayName(e.target.value)}
            />
          </div>
        </div>
      ) : (
        <div>
          <label className={LABEL_CLASS} htmlFor="git-url">
            Git URL (HTTPS only)
          </label>
          <input
            id="git-url"
            className={INPUT_CLASS}
            value={gitUrl}
            maxLength={2000}
            disabled={disabled || isPending}
            placeholder="https://github.com/org/repo.git"
            onChange={(e) => setGitUrl(e.target.value)}
          />
        </div>
      )}

      <button
        type="submit"
        disabled={!canSubmit}
        className={
          "w-full rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white " +
          "hover:bg-emerald-500 disabled:cursor-not-allowed disabled:bg-neutral-800 " +
          "disabled:text-neutral-500"
        }
      >
        {isPending ? "Importing…" : "Create project & import"}
      </button>

      {error && (
        <p role="alert" className="rounded-md bg-red-950 px-3 py-2 text-sm text-red-300">
          {error}
        </p>
      )}
    </form>
  );
}
