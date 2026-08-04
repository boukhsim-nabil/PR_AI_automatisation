# Modèle de domaine Inbox

L’Inbox est un agrégat tenant-scoped centré sur `Conversation`. Les services de
domaine reçoivent toujours une transaction SQLAlchemy dont le contexte RLS a déjà
été positionné. Ils ne font jamais de `commit` et ne prennent jamais de
`company_id` depuis une commande publique.

```text
Company
├── Contact
├── Lead
├── Conversation
│   ├── Participants
│   ├── Messages
│   │   └── Attachments
│   ├── Notes
│   └── Tags
└── Memberships
```

`ConversationService` protège les états read-only, le compteur non lu,
l’attribution et le takeover humain. `MessageService` contrôle la création des
brouillons, la réception, les événements système et le cycle de livraison.
`ParticipantService`, `NoteService` et `TagService` maintiennent les invariants
complémentaires.

Les notes sont des objets internes distincts des messages. Un `system_event` est
un message interne immuable créé uniquement par la méthode dédiée du service. Les
pièces jointes ne contiennent que des métadonnées : aucun binaire ou URL publique
n’appartient au modèle actuel.
