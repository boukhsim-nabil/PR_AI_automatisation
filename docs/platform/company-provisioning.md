# Provisioning d'une entreprise

La procédure normale est `/admin/companies/new` ou `POST /v1/platform/companies`.
SQL ne doit jamais servir d'interface d'administration courante.

Le backend crée dans une transaction la `Company`, son état initial, le plan d'essai,
l'invitation Owner et l'audit. Les rôles tenant système sont globaux et idempotents ;
le rôle `owner` est imposé lors de l'acceptation. Aucun `User` incomplet ni mot de passe
temporaire n'est créé.

Le token d'invitation est aléatoire. Seul son SHA-256 est stocké. L'abstraction
`EmailSender` écrit localement dans `.local/emails`, ignoré par Git ; elle devra être
remplacée par un fournisseur transactionnel en production.

L'acceptation est transactionnelle :

- nouvel email : création du User puis Membership Owner actif ;
- User existant : vérification du mot de passe et ajout du Membership sans doublon ;
- dans les deux cas : invitation consommée, Company en `onboarding`, audit.

Les invitations expirées et révoquées restent historisées. Le token et son hash ne sont
jamais renvoyés dans les réponses du portail.
