# Flux de session et refresh token

## Durées et secrets

- L’access token reste un JWT signé, de courte durée (`15` minutes par défaut).
- Le refresh token possède une durée distincte (`30` jours par défaut) et une
  partie secrète aléatoire de 384 bits.
- Le refresh token complet n’est jamais enregistré ni renvoyé dans un JSON.
  PostgreSQL conserve uniquement son hash SHA-256.
- Le préfixe UUID du token identifie uniquement le tenant afin de positionner
  RLS avant la recherche du hash ; il n’accorde aucun accès.

## Login

1. Le backend vérifie l’utilisateur, l’entreprise et le membership actif.
2. Il crée une ligne `auth_sessions` avec l’utilisateur, le membership, le
   tenant, l’expiration, le user-agent et l’adresse IP observée.
3. Il crée la première génération dans `refresh_tokens`.
4. L’access token est renvoyé au BFF Next.js. Le refresh token est envoyé
   exclusivement dans un cookie HttpOnly.
5. Next.js stocke l’access token dans son cookie HttpOnly existant et relaie les
   cookies de session au navigateur.

## Rotation et détection de réutilisation

`POST /v1/auth/refresh` verrouille la génération présentée avec
`SELECT … FOR UPDATE`, vérifie la session et le membership actif, marque la
génération comme utilisée, puis crée un nouveau refresh token et un nouveau
jeton CSRF. Deux requêtes concurrentes ne peuvent donc pas utiliser la même
génération avec succès.

Les anciennes générations restent sous forme de hash. Toute nouvelle
présentation d’une génération utilisée ou révoquée entraîne la révocation de
toute la famille `auth_sessions`, ainsi que de toutes ses générations.

## Cookies et CSRF

- Refresh : HttpOnly, `Secure` en staging/production, `SameSite=Lax`.
- CSRF : lisible côté client/BFF, mêmes options et durée, mais non HttpOnly.
- Chemin backend : `/v1/auth`.
- Chemin exposé par le BFF Next.js : `/api/auth`.
- Access token Next.js : HttpOnly, chemin `/`.

Les endpoints refresh/logout/logout-all exigent le cookie CSRF, le header
`X-CSRF-Token` identique et le hash CSRF lié à la session. Le BFF refuse aussi
les requêtes dont `Origin` ou `Sec-Fetch-Site` indiquent un appel cross-site.

## Révocation

- `POST /v1/auth/logout` révoque la famille courante.
- `POST /v1/auth/logout-all` révoque toutes les sessions du même utilisateur
  dans l’entreprise courante.
- Les routes RBAC vérifient la session persistée quand le JWT contient
  `session_id`, ce qui rend la révocation effective avant l’expiration du JWT.
- Les JWT émis avant cette migration, sans `session_id`, restent acceptés
  jusqu’à leur expiration naturelle afin de permettre une migration progressive.

## Limites opérationnelles

- L’adresse IP correspond à `request.client`. Derrière un proxy, celui-ci doit
  être configuré comme proxy de confiance avant d’utiliser `X-Forwarded-For`.
- Le rôle PostgreSQL de migration peut contourner RLS et ne doit jamais être
  utilisé par FastAPI.
- Une suppression manuelle des lignes de token empêche la détection ultérieure
  de leur réutilisation ; la rétention doit au minimum couvrir l’expiration de
  la famille.
- Le renouvellement automatique d’une page Server Component nécessite un appel
  POST au proxy `/api/auth/refresh`; aucun refresh n’est effectué par un GET.
