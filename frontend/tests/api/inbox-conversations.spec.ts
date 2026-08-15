import { randomUUID } from "node:crypto";

import { expect, test, type APIRequestContext } from "@playwright/test";

import { authenticatedApi, e2eIdentities } from "./helpers/auth";
import {
  archiveIfPossible,
  createConversation,
  seededTenantAData,
  type Conversation,
} from "./helpers/inbox";

type ConversationPage = {
  items: Conversation[];
  next_cursor: string | null;
  has_more: boolean;
  page_size: number;
};

type AuditItem = {
  action: string;
  resource_id: string | null;
  metadata: Record<string, unknown>;
};

type AuditPage = { items: AuditItem[] };

async function expectConversationStatus(
  api: APIRequestContext,
  conversationId: string,
  expectedStatus: string,
) {
  const response = await api.get(`/v1/inbox/conversations/${conversationId}`);
  expect(response.status()).toBe(200);
  const body = (await response.json()) as Conversation;
  expect(body.status).toBe(expectedStatus);
}

test("workflow principal Conversations, archivage et audit", async ({ playwright }) => {
  const identities = e2eIdentities();
  const ownerA = await authenticatedApi(playwright.request, identities.ownerA);
  const ownerB = await authenticatedApi(playwright.request, identities.ownerB);
  let conversationA: Conversation | undefined;
  let conversationB: Conversation | undefined;

  try {
    const seeded = await seededTenantAData(ownerA);
    const subject = `Conversation E2E Playwright ${randomUUID()}`;

    const forbiddenTenant = await ownerA.post("/v1/inbox/conversations", {
      data: {
        company_id: identities.ownerB.companyId,
        channel: "internal",
        subject,
        priority: "normal",
      },
    });
    expect(forbiddenTenant.status()).toBe(422);

    conversationB = await createConversation(ownerB, subject);
    conversationA = await createConversation(ownerA, subject, {
      contactId: seeded.contact.id,
      leadId: seeded.lead.id,
    });
    expect(conversationA.id).toMatch(/^[0-9a-f-]{36}$/i);
    expect(conversationA.status).toBe("open");
    expect(conversationA.priority).toBe("normal");
    expect(conversationA.human_takeover).toBe(false);
    expect(conversationA).not.toHaveProperty("company_id");

    const listResponse = await ownerA.get("/v1/inbox/conversations", {
      params: { search: subject, page_size: 10, sort_by: "created_at" },
    });
    expect(listResponse.status()).toBe(200);
    const page = (await listResponse.json()) as ConversationPage;
    expect(page.page_size).toBe(10);
    expect(typeof page.has_more).toBe("boolean");
    expect(page.next_cursor === null || typeof page.next_cursor === "string").toBe(true);
    expect(page.items.some((item) => item.id === conversationA!.id)).toBe(true);
    expect(page.items.some((item) => item.id === conversationB!.id)).toBe(false);

    const detailResponse = await ownerA.get(
      `/v1/inbox/conversations/${conversationA.id}`,
    );
    expect(detailResponse.status()).toBe(200);
    const detail = (await detailResponse.json()) as Conversation;
    expect(detail.id).toBe(conversationA.id);
    expect(detail.subject).toBe(subject);
    expect(detail.contact?.id).toBe(seeded.contact.id);
    expect(detail.lead?.id).toBe(seeded.lead.id);
    expect(detail).not.toHaveProperty("company_id");

    const pending = await ownerA.post(
      `/v1/inbox/conversations/${conversationA.id}/status`,
      { data: { status: "pending" } },
    );
    expect(pending.status()).toBe(200);
    expect(((await pending.json()) as Conversation).status).toBe("pending");

    const reopened = await ownerA.post(
      `/v1/inbox/conversations/${conversationA.id}/status`,
      { data: { status: "open" } },
    );
    expect(reopened.status()).toBe(200);
    expect(((await reopened.json()) as Conversation).status).toBe("open");

    const invalidTransition = await ownerA.post(
      `/v1/inbox/conversations/${conversationA.id}/status`,
      { data: { status: "closed" } },
    );
    expect(invalidTransition.status()).toBe(422);
    await expectConversationStatus(ownerA, conversationA.id, "open");

    const priority = await ownerA.post(
      `/v1/inbox/conversations/${conversationA.id}/priority`,
      { data: { priority: "high" } },
    );
    expect(priority.status()).toBe(200);
    expect(((await priority.json()) as Conversation).priority).toBe("high");
    expect(
      (
        await ownerA.post(`/v1/inbox/conversations/${conversationA.id}/priority`, {
          data: { priority: "impossible" },
        })
      ).status(),
    ).toBe(422);

    const assignment = await ownerA.post(
      `/v1/inbox/conversations/${conversationA.id}/assign`,
      { data: { assigned_membership_id: seeded.support.membership_id } },
    );
    expect(assignment.status()).toBe(200);
    expect(((await assignment.json()) as Conversation).assigned_membership_id).toBe(
      seeded.support.membership_id,
    );

    const missingAssignment = await ownerA.post(
      `/v1/inbox/conversations/${conversationA.id}/assign`,
      { data: { assigned_membership_id: randomUUID() } },
    );
    expect(missingAssignment.status()).toBe(422);
    const ownerBAssigneesResponse = await ownerB.get("/v1/crm/assignees");
    expect(ownerBAssigneesResponse.status()).toBe(200);
    const ownerBAssignees = (await ownerBAssigneesResponse.json()) as Array<{
      membership_id: string;
      role: string;
    }>;
    const ownerBMembership = ownerBAssignees.find((item) => item.role === "owner");
    expect(ownerBMembership).toBeTruthy();
    const foreignAssignment = await ownerA.post(
      `/v1/inbox/conversations/${conversationA.id}/assign`,
      { data: { assigned_membership_id: ownerBMembership!.membership_id } },
    );
    expect(foreignAssignment.status()).toBe(422);

    const takeover = await ownerA.post(
      `/v1/inbox/conversations/${conversationA.id}/takeover`,
    );
    expect(takeover.status()).toBe(200);
    expect(((await takeover.json()) as Conversation).human_takeover).toBe(true);
    const release = await ownerA.post(
      `/v1/inbox/conversations/${conversationA.id}/release`,
    );
    expect(release.status()).toBe(200);
    expect(((await release.json()) as Conversation).human_takeover).toBe(false);

    const archived = await ownerA.post(
      `/v1/inbox/conversations/${conversationA.id}/archive`,
    );
    expect(archived.status()).toBe(200);
    const archivedBody = (await archived.json()) as Conversation;
    expect(archivedBody.status).toBe("archived");
    expect(archivedBody.archived_at).toBeTruthy();

    const blockedRequests = [
      ownerA.post(`/v1/inbox/conversations/${conversationA.id}/priority`, {
        data: { priority: "urgent" },
      }),
      ownerA.post(`/v1/inbox/conversations/${conversationA.id}/status`, {
        data: { status: "open" },
      }),
      ownerA.post(`/v1/inbox/conversations/${conversationA.id}/takeover`),
    ];
    for (const blocked of await Promise.all(blockedRequests)) {
      expect(blocked.status()).toBe(409);
    }
    const repeatedArchive = await ownerA.post(
      `/v1/inbox/conversations/${conversationA.id}/archive`,
    );
    expect(repeatedArchive.status()).toBe(200);
    expect(((await repeatedArchive.json()) as Conversation).status).toBe("archived");

    const auditResponse = await ownerA.get("/v1/audit-logs", {
      params: { resource_type: "conversation", limit: 100 },
    });
    expect(auditResponse.status()).toBe(200);
    const auditPage = (await auditResponse.json()) as AuditPage;
    const actions = auditPage.items
      .filter((item) => item.resource_id === conversationA!.id)
      .map((item) => item.action);
    for (const suffix of [
      ".created",
      ".status_changed",
      ".priority_changed",
      ".assigned",
      ".takeover",
      ".released",
      ".archived",
    ]) {
      expect(actions.some((action) => action.endsWith(suffix))).toBe(true);
    }
    const serializedMetadata = JSON.stringify(
      auditPage.items
        .filter((item) => item.resource_id === conversationA!.id)
        .map((item) => item.metadata),
    );
    expect(serializedMetadata).not.toMatch(
      /access_token|refresh_token|authorization|password|jwt|api[_-]?key|secret/i,
    );
  } finally {
    if (conversationA && conversationA.status !== "archived") {
      await archiveIfPossible(ownerA, conversationA.id);
    }
    if (conversationB) {
      await archiveIfPossible(ownerB, conversationB.id);
    }
    await ownerA.dispose();
    await ownerB.dispose();
  }
});

test("refuse la liste sans authentification", async ({ request }) => {
  const response = await request.get("/v1/inbox/conversations");
  expect(response.status()).toBe(401);
});

test("Viewer A lit mais ne peut effectuer aucune mutation", async ({ playwright }) => {
  const identities = e2eIdentities();
  const owner = await authenticatedApi(playwright.request, identities.ownerA);
  const viewer = await authenticatedApi(playwright.request, identities.viewerA);
  const seeded = await seededTenantAData(owner);
  const conversation = await createConversation(
    owner,
    `Viewer security ${randomUUID()}`,
  );
  try {
    expect(
      (await viewer.get(`/v1/inbox/conversations/${conversation.id}`)).status(),
    ).toBe(200);
    const mutations = [
      viewer.post(`/v1/inbox/conversations/${conversation.id}/assign`, {
        data: { assigned_membership_id: seeded.support.membership_id },
      }),
      viewer.post(`/v1/inbox/conversations/${conversation.id}/status`, {
        data: { status: "pending" },
      }),
      viewer.post(`/v1/inbox/conversations/${conversation.id}/priority`, {
        data: { priority: "high" },
      }),
      viewer.post(`/v1/inbox/conversations/${conversation.id}/takeover`),
      viewer.post(`/v1/inbox/conversations/${conversation.id}/archive`),
    ];
    for (const response of await Promise.all(mutations)) {
      expect(response.status()).toBe(403);
    }
  } finally {
    await archiveIfPossible(owner, conversation.id);
    await owner.dispose();
    await viewer.dispose();
  }
});

test("Tenant B reçoit 404 pour la lecture et la mutation du Tenant A", async ({
  playwright,
}) => {
  const identities = e2eIdentities();
  const ownerA = await authenticatedApi(playwright.request, identities.ownerA);
  const ownerB = await authenticatedApi(playwright.request, identities.ownerB);
  const conversation = await createConversation(
    ownerA,
    `Tenant isolation ${randomUUID()}`,
  );
  try {
    expect(
      (await ownerB.get(`/v1/inbox/conversations/${conversation.id}`)).status(),
    ).toBe(404);
    expect(
      (
        await ownerB.post(`/v1/inbox/conversations/${conversation.id}/priority`, {
          data: { priority: "urgent" },
        })
      ).status(),
    ).toBe(404);
  } finally {
    await archiveIfPossible(ownerA, conversation.id);
    await ownerA.dispose();
    await ownerB.dispose();
  }
});
