# Cycle de vie des conversations

Les statuts persistés sont `open`, `pending`, `waiting_customer`,
`waiting_internal`, `resolved`, `closed` et `archived`.

- `archived` est strictement read-only.
- `closed` exige `ConversationService.reopen` avant toute modification.
- Une réception sur une conversation `resolved` la rouvre automatiquement en
  `open`.
- Une réception sur une conversation `closed` ou `archived` est refusée.
- Le premier message renseigne `first_message_at` ; chaque message met à jour
  `last_message_at`.
- Chaque message inbound incrémente `unread_count` et `mark_read` le remet à zéro.
- Le compteur ne peut pas être négatif, à la fois dans le service et via la
  contrainte PostgreSQL.
- Une attribution n’accepte qu’un membership actif du même tenant.
- Activer `human_takeover` désactive `ai_enabled`. Cela prépare les automatismes
  futurs sans implémenter d’agent IA dans ce lot.

Les timestamps sont calculés une seule fois par commande, affectés au message et
à la conversation, puis persistés dans la transaction appelante.
