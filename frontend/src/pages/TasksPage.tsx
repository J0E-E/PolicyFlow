import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { CheckCircle } from "iconoir-react";
import Button from "../components/Button.tsx";
import StampTag from "../components/StampTag.tsx";
import { useCapability, useSession } from "../session";
import { completeTask, listTasks } from "../api";
import type { Task } from "../api";
import {
  isOpportunityTask,
  relatedRecordLabel,
  taskDueDateLabel,
  taskTypeLabel,
} from "./tasksPresentation.ts";

// The agent task queue at `/app/tasks` (Epic 11). It renders INSIDE the AppShell
// chrome (masthead + left nav), so it carries its OWN Guide §5 page header (a
// Besley "Tasks" headline + the Oxford double rule), with NO "New" action —
// tasks are created by automation (the sweeps) and conversion, never by hand.
//
// One read backs the page: `listTasks()` returns the caller's non-completed
// queue, already role-scoped and ordered soonest-due/overdue-first on the server.
// The role only shapes the VIEW: an Agent sees their own queue with no Assignee
// column (redundant — every row is theirs); a Tenant Admin / Read-Only sees every
// task with an Assignee column. There is no assignee filter control (the backend
// supports `?assignee=`, but the control is deferred to Goal scope).
//
// Each row flags an overdue task (a red "Overdue" stamp), links to its related
// record where a live surface exists (an opportunity detail page; a contact is
// plain text — no page yet), and — for a `create_edit_records` holder — carries a
// one-click Complete that clears the task from the list on success (Phase 3).

/** What the task fetch is doing. Mirrors LeadsListPage's LoadState idiom so
 *  loading / error / loaded each render once. */
type TasksLoadState =
  | { kind: "loading" }
  | { kind: "loaded"; tasks: Task[] }
  | { kind: "error" };

// The page header — the same Besley headline + Oxford rule on every branch, so
// each body state wraps it. No action affordance (tasks aren't hand-created).
function TasksHeader() {
  return (
    <header id="tasks-page-header" className="tasks-page-header">
      <h1 id="tasks-page-title" className="tasks-page-title">
        Tasks
      </h1>
      <hr id="tasks-page-rule" className="oxford-double-rule" />
    </header>
  );
}

export default function TasksPage() {
  const { identity } = useSession();
  // Only an Agent hides the Assignee column (every row is their own); a Tenant
  // Admin / Read-Only sees all tasks and needs the column for clarity.
  const showAssigneeColumn = identity?.user.role !== "agent";
  // The Complete control is gated on `create_edit_records` — Read-Only sees no
  // button (mirrors the endpoint's 403).
  const canCompleteTasks = useCapability("create_edit_records");

  const [tasksLoad, setTasksLoad] = useState<TasksLoadState>({
    kind: "loading",
  });
  // The id of the task whose Complete is in flight (its button shows the
  // spinner), or null when none is pending. One at a time keeps the reconcile
  // simple (mirrors LeadsListPage's `claimingLeadId`).
  const [completingTaskId, setCompletingTaskId] = useState<string | null>(null);
  // The cleanup for an in-flight post-complete refetch, held in a ref because it
  // lives outside React's render data (mirrors LeadsListPage's claim-refetch
  // discipline) — so a re-load can cancel a stale resolve.
  const completeRefetchCleanup = useRef<(() => void) | null>(null);
  // A non-destructive complete error: the list stays intact and the row's button
  // re-enables. Cleared on the next complete attempt.
  const [completeErrorMessage, setCompleteErrorMessage] = useState<
    string | null
  >(null);

  // Fetch the caller's queue. `listTasks()` is the same call for every role — the
  // server scopes the rows; the role only decides whether the Assignee column
  // shows. Returns the cleanup that ignores a stale resolve after unmount.
  const loadTasks = useCallback(() => {
    setTasksLoad({ kind: "loading" });
    let isActive = true;
    listTasks()
      .then((tasks) => {
        if (isActive) {
          setTasksLoad({ kind: "loaded", tasks });
        }
      })
      .catch(() => {
        if (isActive) {
          setTasksLoad({ kind: "error" });
        }
      });
    return () => {
      isActive = false;
    };
  }, []);

  // Load on mount. Cancel any in-flight post-complete refetch first — this fetch
  // supersedes it, so its stale resolve must not overwrite the fresh load.
  useEffect(() => {
    completeRefetchCleanup.current?.();
    completeRefetchCleanup.current = null;
    return loadTasks();
  }, [loadTasks]);

  // Complete one task, then reconcile by refetching: the completed task leaves the
  // list (GET filters completed out). A failure surfaces a non-destructive inline
  // error and re-enables the row's button — the list (and its rows) stay put.
  const completeTaskById = (taskId: string) => {
    setCompleteErrorMessage(null);
    setCompletingTaskId(taskId);
    completeTask(taskId)
      .then(() => {
        // Track this refetch's cleanup so a later load can cancel a stale resolve.
        completeRefetchCleanup.current = loadTasks();
      })
      .catch(() => {
        setCompleteErrorMessage(
          "We couldn't complete that task — it may have already been completed. Please try again.",
        );
      })
      .finally(() => {
        setCompletingTaskId(null);
      });
  };

  if (tasksLoad.kind === "loading") {
    return (
      <div id="tasks-page" className="tasks-page">
        <TasksHeader />
        <p
          id="tasks-page-loading"
          className="tasks-page-status"
          role="status"
          aria-live="polite"
        >
          Loading tasks…
        </p>
      </div>
    );
  }

  if (tasksLoad.kind === "error") {
    return (
      <div id="tasks-page" className="tasks-page">
        <TasksHeader />
        <div id="tasks-page-error" className="tasks-page-error">
          <p
            id="tasks-page-error-message"
            className="tasks-page-status"
            role="status"
            aria-live="polite"
          >
            We couldn't load your tasks. Please try again.
          </p>
          <Button
            id="tasks-page-error-retry-button"
            variant="tonal"
            onClick={loadTasks}
          >
            Retry
          </Button>
        </div>
      </div>
    );
  }

  if (tasksLoad.tasks.length === 0) {
    return (
      <div id="tasks-page" className="tasks-page">
        <TasksHeader />
        <TasksEmptyState />
      </div>
    );
  }

  return (
    <div id="tasks-page" className="tasks-page">
      <TasksHeader />
      {completeErrorMessage !== null && (
        <p
          id="tasks-page-complete-error"
          className="tasks-page-complete-error"
          role="alert"
        >
          {completeErrorMessage}
        </p>
      )}
      <TasksTable
        tasks={tasksLoad.tasks}
        showAssigneeColumn={showAssigneeColumn}
        canCompleteTasks={canCompleteTasks}
        completingTaskId={completingTaskId}
        onComplete={completeTaskById}
      />
    </div>
  );
}

// ---- Empty state: a calm Guide §5 framed note (mirrors LeadsEmptyState) ----

function TasksEmptyState() {
  return (
    <div id="tasks-page-empty" className="tasks-page-empty" role="status">
      <span
        id="tasks-page-empty-icon"
        className="tasks-page-empty-icon"
        aria-hidden="true"
      >
        <CheckCircle width={28} height={28} />
      </span>
      <p id="tasks-page-empty-message" className="tasks-page-empty-message">
        Your queue is clear — no open tasks.
      </p>
    </div>
  );
}

// ---- The dense data table (Guide §5): Stamp-type heads, hairline dividers ----

// The Assignee column is present only in the admin/read-only "all" view; the
// action column head is intentionally label-less (Guide §5 per-row action cell).
function taskColumnHeads(showAssigneeColumn: boolean) {
  return [
    { key: "task", label: "Task" },
    { key: "type", label: "Type" },
    { key: "due", label: "Due" },
    { key: "related", label: "Related record" },
    ...(showAssigneeColumn ? [{ key: "assignee", label: "Assignee" }] : []),
    { key: "action", label: "" },
  ];
}

function TasksTable({
  tasks,
  showAssigneeColumn,
  canCompleteTasks,
  completingTaskId,
  onComplete,
}: {
  tasks: Task[];
  showAssigneeColumn: boolean;
  canCompleteTasks: boolean;
  completingTaskId: string | null;
  onComplete: (taskId: string) => void;
}) {
  const columnHeads = taskColumnHeads(showAssigneeColumn);
  return (
    <table id="tasks-page-table" className="tasks-page-table">
      <thead id="tasks-page-table-head">
        <tr id="tasks-page-table-head-row">
          {columnHeads.map((column) => (
            <th
              key={column.key}
              id={`tasks-page-head-${column.key}`}
              className="tasks-page-head"
              scope="col"
            >
              {column.label}
            </th>
          ))}
        </tr>
      </thead>
      <tbody id="tasks-page-table-body">
        {tasks.map((task) => (
          <TaskRow
            key={task.id}
            task={task}
            showAssigneeColumn={showAssigneeColumn}
            canCompleteTasks={canCompleteTasks}
            isCompleting={completingTaskId === task.id}
            onComplete={onComplete}
          />
        ))}
      </tbody>
    </table>
  );
}

function TaskRow({
  task,
  showAssigneeColumn,
  canCompleteTasks,
  isCompleting,
  onComplete,
}: {
  task: Task;
  showAssigneeColumn: boolean;
  canCompleteTasks: boolean;
  isCompleting: boolean;
  onComplete: (taskId: string) => void;
}) {
  return (
    <tr id={`tasks-page-row-${task.id}`} className="tasks-page-row">
      <td id={`tasks-page-row-${task.id}-task`} className="tasks-page-cell">
        <span id={`tasks-page-row-${task.id}-body`} className="tasks-page-body">
          {task.body}
        </span>
        {task.is_overdue && (
          <StampTag id={`tasks-page-row-${task.id}-overdue`} status="error">
            Overdue
          </StampTag>
        )}
      </td>
      <td id={`tasks-page-row-${task.id}-type`} className="tasks-page-cell">
        {taskTypeLabel(task.task_type)}
      </td>
      <td id={`tasks-page-row-${task.id}-due`} className="tasks-page-cell">
        {taskDueDateLabel(task.due_date)}
      </td>
      <td id={`tasks-page-row-${task.id}-related`} className="tasks-page-cell">
        {isOpportunityTask(task) ? (
          // The opportunity detail page exists — link the row to it.
          <Link
            id={`tasks-page-row-${task.id}-related-link`}
            className="tasks-page-related-link"
            to={`/app/opportunities/${task.related_entity_id}`}
          >
            {relatedRecordLabel(task.related_entity_type)}
          </Link>
        ) : (
          // No detail surface for this related type yet (e.g. a contact) — plain
          // text, never a dead link (the honest-inert convention).
          relatedRecordLabel(task.related_entity_type)
        )}
      </td>
      {showAssigneeColumn && (
        <td
          id={`tasks-page-row-${task.id}-assignee`}
          className="tasks-page-cell"
        >
          {task.assignee_username ?? "—"}
        </td>
      )}
      <td id={`tasks-page-row-${task.id}-action`} className="tasks-page-cell">
        {/* One-click Complete for a `create_edit_records` holder — Read-Only sees
            no button (mirrors the endpoint's 403). On success the list refetches
            so the completed task leaves it. */}
        {canCompleteTasks && (
          <Button
            id={`tasks-page-row-${task.id}-complete-button`}
            variant="tonal"
            isPending={isCompleting}
            onClick={() => onComplete(task.id)}
          >
            Complete
          </Button>
        )}
      </td>
    </tr>
  );
}
