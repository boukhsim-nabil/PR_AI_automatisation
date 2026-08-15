import { randomUUID } from "node:crypto";

import { expect, test, type APIRequestContext } from "@playwright/test";

import { authenticatedApi, e2eIdentities } from "./helpers/auth";
import { archiveIfPossible, createConversation, type Conversation } from "./helpers/inbox";

type Message = {
  id: string;
  conversation_id: string;
  direction: string;
  content_type: string;
  body_text: string | null;
  status: string;
  sent_at: string | null;
  received_at: string | null;
  html_requires_sanitization: boolean;
};

type MessagePage = {
  items: Message[];
  next_cursor: string | null;
  has_more: boolean;
  page_size: number;
};

type AuditPage = {
  items: Array<{
    action: string;
    resource_id: string | null;
    metadata: Record<string, unknown>;
  }>;
};

async function createDraft(
  api: APIRequestContext,
  conversationId: string,
  bodyText: string,
): Promise<Message> {
  const response = await api.post(`/v1/inbox/conversations/${conversationId}/drafts`, {
    data: { content_type: "text", body_text: bodyText },
  });
  expect(response.status()).toBe(201);
  return (await response.json()) as Message;
}

test("cycle brouillon, envoi simulé, réception et idempotence", async ({ playwright }) => {
  const identities = e2eIdentities();
  const owner = await authenticatedApi(playwright.request, identities.ownerA);
  const support = await authenticatedApi(playwright.request, identities.supportA);
  const conversation = await createConversation(
    owner,
    `Messages E2E ${randomUUID()}`,
  );

  try {
    const draft = await createDraft(support, conversation.id, "Premier brouillon E2E");
    expect(draft.direction).toBe("outbound");
    expect(draft.status).toBe("draft");

    const updatedResponse = await support.patch(`/v1/inbox/messages/${draft.id}/draft`, {
      data: { body_text: "Brouillon E2E modifié" },
    });
    expect(updatedResponse.status()).toBe(200);
    expect(((await updatedResponse.json()) as Message).body_text).toBe(
      "Brouillon E2E modifié",
    );

    const queuedResponse = await support.post(`/v1/inbox/messages/${draft.id}/queue`);
    expect(queuedResponse.status()).toBe(200);
    expect(((await queuedResponse.json()) as Message).status).toBe("queued");

    const immutableQueued = await support.patch(`/v1/inbox/messages/${draft.id}/draft`, {
      data: { body_text: "Modification interdite" },
    });
    expect(immutableQueued.status()).toBe(422);

    const sentResponse = await support.post(`/v1/inbox/messages/${draft.id}/send`);
    expect(sentResponse.status()).toBe(200);
    const sent = (await sentResponse.json()) as Message;
    expect(sent.status).toBe("sent");
    expect(sent.sent_at).toBeTruthy();

    const immutableSent = await support.patch(`/v1/inbox/messages/${draft.id}/draft`, {
      data: { body_text: "Toujours interdite" },
    });
    expect(immutableSent.status()).toBe(422);

    const listResponse = await owner.get(
      `/v1/inbox/conversations/${conversation.id}/messages`,
      { params: { page_size: 20 } },
    );
    expect(listResponse.status()).toBe(200);
    const page = (await listResponse.json()) as MessagePage;
    expect(page.page_size).toBe(20);
    expect(page.items.some((item) => item.id === draft.id && item.status === "sent")).toBe(
      true,
    );

    const beforeInboundResponse = await owner.get(
      `/v1/inbox/conversations/${conversation.id}`,
    );
    expect(beforeInboundResponse.status()).toBe(200);
    const beforeInbound = (await beforeInboundResponse.json()) as Conversation;

    const externalMessageId = `playwright-inbound-${randomUUID()}`;
    const inboundPayload = {
      conversation_id: conversation.id,
      sender_identifier: "controlled-e2e-sender",
      content_type: "text",
      body_text: "Message entrant simulé E2E",
      external_message_id: externalMessageId,
    };
    const inboundResponse = await owner.post("/v1/inbox/messages/simulate-inbound", {
      data: inboundPayload,
    });
    expect(inboundResponse.status()).toBe(201);
    const inbound = (await inboundResponse.json()) as Message;
    expect(inbound.direction).toBe("inbound");
    expect(inbound.status).toBe("received");
    expect(inbound.received_at).toBeTruthy();

    const repeatedInbound = await owner.post("/v1/inbox/messages/simulate-inbound", {
      data: inboundPayload,
    });
    expect(repeatedInbound.status()).toBe(200);
    expect(((await repeatedInbound.json()) as Message).id).toBe(inbound.id);

    const detailResponse = await owner.get(`/v1/inbox/conversations/${conversation.id}`);
    expect(detailResponse.status()).toBe(200);
    const detail = (await detailResponse.json()) as Conversation;
    expect(detail.unread_count).toBe((beforeInbound.unread_count ?? 0) + 1);
    expect(detail.last_message_at).toBeTruthy();
    if (beforeInbound.last_message_at) {
      expect(Date.parse(detail.last_message_at!)).toBeGreaterThanOrEqual(
        Date.parse(beforeInbound.last_message_at),
      );
    }

    const auditResponse = await owner.get("/v1/audit-logs", {
      params: { resource_type: "message", limit: 100 },
    });
    expect(auditResponse.status()).toBe(200);
    const audits = (await auditResponse.json()) as AuditPage;
    const draftActions = audits.items
      .filter((item) => item.resource_id === draft.id)
      .map((item) => item.action);
    for (const action of [
      "inbox.message.draft_created",
      "inbox.message.draft_updated",
      "inbox.message.queued",
      "inbox.message.sent",
    ]) {
      expect(draftActions).toContain(action);
    }
    expect(
      audits.items.some(
        (item) =>
          item.resource_id === inbound.id &&
          item.action === "inbox.message.received_simulated",
      ),
    ).toBe(true);
    expect(JSON.stringify(audits.items.map((item) => item.metadata))).not.toMatch(
      /access_token|refresh_token|authorization|password|jwt|api[_-]?key|secret/i,
    );
  } finally {
    await archiveIfPossible(owner, conversation.id);
    await owner.dispose();
    await support.dispose();
  }
});

test("supprime logiquement un brouillon", async ({ playwright }) => {
  const identities = e2eIdentities();
  const owner = await authenticatedApi(playwright.request, identities.ownerA);
  const conversation = await createConversation(owner, `Discard draft ${randomUUID()}`);
  try {
    const draft = await createDraft(owner, conversation.id, "Brouillon à supprimer");
    const deleted = await owner.delete(`/v1/inbox/messages/${draft.id}/draft`);
    expect(deleted.status()).toBe(204);
    expect((await owner.get(`/v1/inbox/messages/${draft.id}`)).status()).toBe(404);
  } finally {
    await archiveIfPossible(owner, conversation.id);
    await owner.dispose();
  }
});

test("refuse les messages sans authentification", async ({ request }) => {
  expect(
    (await request.get(`/v1/inbox/conversations/${randomUUID()}/messages`)).status(),
  ).toBe(401);
});

test("applique RBAC Viewer et l'isolation Tenant B", async ({ playwright }) => {
  const identities = e2eIdentities();
  const ownerA = await authenticatedApi(playwright.request, identities.ownerA);
  const viewerA = await authenticatedApi(playwright.request, identities.viewerA);
  const ownerB = await authenticatedApi(playwright.request, identities.ownerB);
  const conversation = await createConversation(ownerA, `Message security ${randomUUID()}`);
  try {
    const viewerDraft = await viewerA.post(
      `/v1/inbox/conversations/${conversation.id}/drafts`,
      { data: { body_text: "Interdit au viewer" } },
    );
    expect(viewerDraft.status()).toBe(403);
    expect(
      (await ownerB.get(`/v1/inbox/conversations/${conversation.id}/messages`)).status(),
    ).toBe(404);
    expect(
      (
        await ownerB.post(`/v1/inbox/conversations/${conversation.id}/drafts`, {
          data: { body_text: "Interdit au Tenant B" },
        })
      ).status(),
    ).toBe(404);
  } finally {
    await archiveIfPossible(ownerA, conversation.id);
    await ownerA.dispose();
    await viewerA.dispose();
    await ownerB.dispose();
  }
});

test("refuse une conversation archivée et un reply d'une autre conversation", async ({
  playwright,
}) => {
  const identities = e2eIdentities();
  const owner = await authenticatedApi(playwright.request, identities.ownerA);
  const first = await createConversation(owner, `Reply first ${randomUUID()}`);
  const second = await createConversation(owner, `Reply second ${randomUUID()}`);
  try {
    const otherDraft = await createDraft(owner, second.id, "Message de référence");
    const invalidReply = await owner.post(`/v1/inbox/conversations/${first.id}/drafts`, {
      data: { body_text: "Mauvaise conversation", reply_to_message_id: otherDraft.id },
    });
    expect(invalidReply.status()).toBe(422);

    expect((await owner.post(`/v1/inbox/conversations/${first.id}/archive`)).status()).toBe(
      200,
    );
    expect(
      (
        await owner.post(`/v1/inbox/conversations/${first.id}/drafts`, {
          data: { body_text: "Conversation archivée" },
        })
      ).status(),
    ).toBe(409);
    expect(
      (
        await owner.post("/v1/inbox/messages/simulate-inbound", {
          data: {
            conversation_id: first.id,
            sender_identifier: "controlled-e2e-sender",
            body_text: "Réception interdite",
          },
        })
      ).status(),
    ).toBe(409);
  } finally {
    await archiveIfPossible(owner, first.id);
    await archiveIfPossible(owner, second.id);
    await owner.dispose();
  }
});
