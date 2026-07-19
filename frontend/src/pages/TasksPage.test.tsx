// Tests for the agent task queue page (Epic 11). jsdom has no backend, so `../api`
// is mocked: listTasks drives the queue, completeTask drives the Complete action
// (Phase 3). The page reads the session via `../session`, so that is mocked too —
// useSession returns a fixed identity (agent or admin) and useCapability is driven
// per capability (create_edit_records). The page renders react-router links, so it
// is wrapped in a MemoryRouter. Covers: loading, loaded table, the overdue badge,
// the opportunity link vs contact plain text, empty + error states, and the
// role-conditional Assignee column.

import { fireEvent, render, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import TasksPage from "./TasksPage.tsx";
import type { Capability, Identity, Task } from "../api";

vi.mock("../api", () => ({
  listTasks: vi.fn(),
  completeTask: vi.fn(),
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.name = "ApiError";
      this.status = status;
    }
  },
}));

vi.mock("../session", () => ({
  useSession: vi.fn(),
  useCapability: vi.fn(),
}));

import { completeTask, listTasks } from "../api";
import { useCapability, useSession } from "../session";

const listTasksMock = vi.mocked(listTasks);
const completeTaskMock = vi.mocked(completeTask);
const useCapabilityMock = vi.mocked(useCapability);
const useSessionMock = vi.mocked(useSession);

const agentIdentity: Identity = {
  user: {
    id: "11111111-1111-1111-1111-111111111111",
    username: "agent.one",
    role: "agent",
    tenant_id: "22222222-2222-2222-2222-222222222222",
    tenant_slug: "sunshine-senior-benefits",
    tenant_name: "Sunshine Senior Benefits",
  },
  capabilities: ["create_edit_records", "view_tenant_records"],
};

const adminIdentity: Identity = {
  user: {
    id: "99999999-9999-9999-9999-999999999999",
    username: "admin.one",
    role: "tenant_admin",
    tenant_id: "22222222-2222-2222-2222-222222222222",
    tenant_slug: "sunshine-senior-benefits",
    tenant_name: "Sunshine Senior Benefits",
  },
  capabilities: ["create_edit_records", "view_tenant_records"],
};

// A task with sensible defaults; each test overrides only what it asserts.
function makeTask(overrides: Partial<Task>): Task {
  return {
    id: "task-default",
    task_type: "renewal_review",
    body: "Review the Ramirez Medicare Advantage renewal",
    due_date: "2026-07-20T12:00:00Z",
    is_overdue: false,
    related_entity_type: "opportunity",
    related_entity_id: "opp-1",
    assignee_username: "agent.one",
    status: "open",
    ...overrides,
  };
}

function sessionFor(identity: Identity) {
  return {
    status: "signed-in" as const,
    identity,
    capabilities: identity.capabilities,
    assumePersona: vi.fn(),
    signOut: vi.fn(),
  };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <TasksPage />
    </MemoryRouter>,
  );
}

// Drive useCapability off a held-capability set; a test flips one by overriding.
function capabilitySet(held: Capability[]) {
  return (capability: Capability) => held.includes(capability);
}

beforeEach(() => {
  listTasksMock.mockReset();
  completeTaskMock.mockReset();
  useCapabilityMock.mockReset();
  useSessionMock.mockReset();
  useSessionMock.mockReturnValue(sessionFor(agentIdentity));
  useCapabilityMock.mockImplementation(capabilitySet(["create_edit_records"]));
  listTasksMock.mockResolvedValue([]);
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("TasksPage header + loading", () => {
  it("shows a loading state while the tasks are in flight", () => {
    listTasksMock.mockReturnValue(new Promise<Task[]>(() => {}));

    renderPage();

    expect(document.getElementById("tasks-page-loading")).toBeInTheDocument();
    expect(document.getElementById("tasks-page-title")).toHaveTextContent(
      "Tasks",
    );
  });

  it("has no New action in the header (tasks aren't hand-created)", async () => {
    renderPage();

    await waitFor(() => {
      expect(document.getElementById("tasks-page-empty")).toBeInTheDocument();
    });
    expect(document.getElementById("tasks-page-new-task-link")).toBeNull();
  });
});

describe("TasksPage loaded table", () => {
  it("renders a row per task with body, type, due date, and related record", async () => {
    listTasksMock.mockResolvedValue([
      makeTask({
        id: "task-a",
        body: "Review the Ramirez renewal",
        task_type: "renewal_review",
        due_date: "2026-07-20T12:00:00Z",
        related_entity_type: "opportunity",
        related_entity_id: "opp-42",
      }),
    ]);

    renderPage();

    await waitFor(() => {
      expect(document.getElementById("tasks-page-row-task-a")).toBeInTheDocument();
    });
    expect(
      document.getElementById("tasks-page-row-task-a-body"),
    ).toHaveTextContent("Review the Ramirez renewal");
    // The raw task_type key is humanized for the Type cell.
    expect(
      document.getElementById("tasks-page-row-task-a-type"),
    ).toHaveTextContent("Renewal review");
    // The due date is the fixed YYYY-MM-DD slice.
    expect(
      document.getElementById("tasks-page-row-task-a-due"),
    ).toHaveTextContent("2026-07-20");
  });

  it("renders the overdue badge only on an overdue row", async () => {
    listTasksMock.mockResolvedValue([
      makeTask({ id: "late", is_overdue: true }),
      makeTask({ id: "ontime", is_overdue: false }),
    ]);

    renderPage();

    await waitFor(() => {
      expect(document.getElementById("tasks-page-row-late")).toBeInTheDocument();
    });
    expect(
      document.getElementById("tasks-page-row-late-overdue-label"),
    ).toHaveTextContent("Overdue");
    // An on-time row carries no overdue stamp.
    expect(document.getElementById("tasks-page-row-ontime-overdue")).toBeNull();
  });

  it("links an opportunity task to its detail page and renders a contact task as plain text", async () => {
    listTasksMock.mockResolvedValue([
      makeTask({
        id: "opp-task",
        related_entity_type: "opportunity",
        related_entity_id: "opp-7",
      }),
      makeTask({
        id: "note-task",
        task_type: "note",
        related_entity_type: "contact",
        related_entity_id: "contact-3",
        due_date: null,
      }),
    ]);

    renderPage();

    await waitFor(() => {
      expect(
        document.getElementById("tasks-page-row-opp-task"),
      ).toBeInTheDocument();
    });
    // The opportunity task links to the existing detail page.
    const oppLink = document.getElementById("tasks-page-row-opp-task-related-link");
    expect(oppLink).toHaveTextContent("Opportunity");
    expect(oppLink).toHaveAttribute("href", "/app/opportunities/opp-7");
    // The contact task is plain text — no dead link (no contact page yet).
    expect(
      document.getElementById("tasks-page-row-note-task-related-link"),
    ).toBeNull();
    expect(
      document.getElementById("tasks-page-row-note-task-related"),
    ).toHaveTextContent("Contact");
    // A null-due note task shows an em dash in the Due cell.
    expect(
      document.getElementById("tasks-page-row-note-task-due"),
    ).toHaveTextContent("—");
  });
});

describe("TasksPage role-conditional Assignee column", () => {
  it("hides the Assignee column for an Agent's own queue", async () => {
    useSessionMock.mockReturnValue(sessionFor(agentIdentity));
    listTasksMock.mockResolvedValue([makeTask({ id: "task-a" })]);

    renderPage();

    await waitFor(() => {
      expect(document.getElementById("tasks-page-row-task-a")).toBeInTheDocument();
    });
    expect(document.getElementById("tasks-page-head-assignee")).toBeNull();
    expect(
      document.getElementById("tasks-page-row-task-a-assignee"),
    ).toBeNull();
  });

  it("shows the Assignee column for a Tenant Admin's all-tasks view", async () => {
    useSessionMock.mockReturnValue(sessionFor(adminIdentity));
    listTasksMock.mockResolvedValue([
      makeTask({ id: "task-a", assignee_username: "agent.two" }),
    ]);

    renderPage();

    await waitFor(() => {
      expect(document.getElementById("tasks-page-row-task-a")).toBeInTheDocument();
    });
    expect(document.getElementById("tasks-page-head-assignee")).toBeInTheDocument();
    expect(
      document.getElementById("tasks-page-row-task-a-assignee"),
    ).toHaveTextContent("agent.two");
  });
});

describe("TasksPage empty + error states", () => {
  it("shows the calm queue-clear empty note when there are no tasks", async () => {
    listTasksMock.mockResolvedValue([]);

    renderPage();

    await waitFor(() => {
      expect(document.getElementById("tasks-page-empty")).toBeInTheDocument();
    });
    expect(
      document.getElementById("tasks-page-empty-message"),
    ).toHaveTextContent("Your queue is clear — no open tasks.");
    const emptyIcon = document.getElementById("tasks-page-empty-icon");
    expect(emptyIcon).toBeInTheDocument();
    expect(emptyIcon).toHaveAttribute("aria-hidden", "true");
  });

  it("shows a fetch error and retries", async () => {
    listTasksMock
      .mockRejectedValueOnce(new Error("server error"))
      .mockResolvedValueOnce([makeTask({ id: "task-a" })]);

    renderPage();

    await waitFor(() => {
      expect(document.getElementById("tasks-page-error")).toBeInTheDocument();
    });

    fireEvent.click(document.getElementById("tasks-page-error-retry-button")!);

    await waitFor(() => {
      expect(document.getElementById("tasks-page-row-task-a")).toBeInTheDocument();
    });
  });
});

describe("TasksPage complete action", () => {
  it("shows a Complete button for a create_edit_records holder", async () => {
    useCapabilityMock.mockImplementation(capabilitySet(["create_edit_records"]));
    listTasksMock.mockResolvedValue([makeTask({ id: "task-a" })]);

    renderPage();

    await waitFor(() => {
      expect(
        document.getElementById("tasks-page-row-task-a-complete-button"),
      ).toBeInTheDocument();
    });
  });

  it("hides the Complete button from a Read-Only user", async () => {
    useCapabilityMock.mockImplementation(capabilitySet(["view_tenant_records"]));
    listTasksMock.mockResolvedValue([makeTask({ id: "task-a" })]);

    renderPage();

    await waitFor(() => {
      expect(document.getElementById("tasks-page-row-task-a")).toBeInTheDocument();
    });
    expect(
      document.getElementById("tasks-page-row-task-a-complete-button"),
    ).toBeNull();
  });

  it("completes a task then refetches it out of the list", async () => {
    // First load: one open task. After completing it, the refetch returns an empty
    // queue (the GET filters completed tasks out).
    listTasksMock
      .mockResolvedValueOnce([makeTask({ id: "task-a" })])
      .mockResolvedValueOnce([]);
    completeTaskMock.mockResolvedValue(
      makeTask({ id: "task-a", status: "completed" }),
    );

    renderPage();

    await waitFor(() => {
      expect(
        document.getElementById("tasks-page-row-task-a-complete-button"),
      ).toBeInTheDocument();
    });

    fireEvent.click(
      document.getElementById("tasks-page-row-task-a-complete-button")!,
    );

    expect(completeTaskMock).toHaveBeenCalledWith("task-a");

    // After the refetch the task is gone and the empty state shows.
    await waitFor(() => {
      expect(document.getElementById("tasks-page-empty")).toBeInTheDocument();
    });
    expect(document.getElementById("tasks-page-row-task-a")).toBeNull();
  });

  it("surfaces a non-destructive inline error and re-enables the row when a complete fails", async () => {
    listTasksMock.mockResolvedValue([makeTask({ id: "task-a" })]);
    completeTaskMock.mockRejectedValue(new Error("409 already completed"));

    renderPage();

    await waitFor(() => {
      expect(
        document.getElementById("tasks-page-row-task-a-complete-button"),
      ).toBeInTheDocument();
    });

    fireEvent.click(
      document.getElementById("tasks-page-row-task-a-complete-button")!,
    );

    await waitFor(() => {
      expect(
        document.getElementById("tasks-page-complete-error"),
      ).toBeInTheDocument();
    });
    // The list stays intact and the row's Complete button re-enables.
    expect(document.getElementById("tasks-page-row-task-a")).toBeInTheDocument();
    const completeButton = document.getElementById(
      "tasks-page-row-task-a-complete-button",
    ) as HTMLButtonElement | null;
    expect(completeButton).not.toBeNull();
    expect(completeButton!.disabled).toBe(false);
  });
});
