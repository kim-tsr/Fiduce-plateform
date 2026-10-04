# Fiduce — Plateforme de réconciliation des paiements

---

## 1. Architecture

```
                     ┌──────────┐
   navigateur  ───▶  │   web    │  (SPA statique, nginx non-root, :8080)
                     └────┬─────┘
                          │ /api/*
                     ┌────▼─────┐
                     │ gateway  │  BFF : valide le JWT (JWKS), injecte l'identité
                     └────┬─────┘  tenant en en-têtes de confiance, reverse-proxy
          ┌───────────────┼───────────────┐
     ┌────▼────┐     ┌────▼─────┐     ┌────▼──────┐
     │  auth   │     │  ledger  │     │ reporting │
     │ JWT/JWKS│     │ écritures│     │ rapports  │
     └────┬────┘     └──┬───┬───┘     └─────┬─────┘
          │             │   │               │
          │        (publie jobs)       (publie jobs)
          │             │   │               │
          ▼             ▼   ▼               ▼
     ┌─────────┐   ┌────────┐  ┌─────────┐  ┌──────────────┐
     │ Postgres│   │ Redis  │  │  NATS   │◀─┤    worker    │ (consomme les jobs :
     └─────────┘   └────────┘  │JetStream│  └──────────────┘  réconciliation, rapports)
                               └─────────┘
```

Chaque service expose `/healthz` (liveness), `/readyz` (readiness avec checks de
dépendances) et `/metrics` (Prometheus). Le tracing OpenTelemetry est propagé de
bout en bout (gateway → services → NATS → worker), corrélé aux logs JSON.

### Services

| Service     | Rôle | Port | Dépendances |
|-------------|------|------|-------------|
| `web`       | Frontend SPA (vanilla JS) servi par nginx non-root | 8080 | gateway |
| `gateway`   | API gateway / BFF : validation JWT, injection tenant, proxy | 8080 | auth (JWKS), ledger, reporting |
| `auth`      | Authentification, émission JWT RS256, JWKS | 8000 | Postgres |
| `ledger`    | Cœur métier : écritures comptables, soldes, réconciliation | 8000 | Postgres, Redis, NATS |
| `reporting` | API de demande de rapports (asynchrones) | 8000 | Postgres, NATS |
| `worker`    | Traitement asynchrone des jobs (réconciliation, rapports) | 8000 | Postgres, Redis, NATS |

### Bibliothèque partagée `libs/fiduce_platform`

Briques transverses réutilisées par tous les services : configuration
(`config`), logs JSON corrélés (`logging`), tracing OTel (`telemetry`), métriques
Prometheus (`metrics`), middleware (`middleware`), sondes de santé (`health`),
fabrique d'app (`app_factory`), accès Postgres/Redis/NATS (`db`/`cache`/`broker`)
et sécurité JWT/argon2 (`security`). Les dépendances lourdes sont importées au
sein des fonctions afin qu'un service ne tire que ce qu'il utilise.

---

## 2. Modèle multi-tenant

- Toutes les tables métier portent une colonne `tenant_id`.
- L'identité du tenant est transportée par un *claim* du JWT.
- La **gateway** valide le JWT puis injecte `X-Tenant-ID`, `X-User-ID`, `X-Roles`
  vers les services amont, qui filtrent **systématiquement** leurs requêtes par
  tenant. Les services amont ne reçoivent jamais le JWT brut (sauf `auth/userinfo`).
- **Frontière de confiance** : en l'état, les services font confiance à l'en-tête
  `X-Tenant-ID` posé par la gateway. Le durcir (mTLS de maillage, revue de token
  par service, NetworkPolicies isolant les espaces de noms) fait partie du mandat.

---

## 3. Flux de données illustrant le scénario cible

1. `POST /api/auth/login` → la gateway proxifie vers `auth`, qui vérifie le mot de
   passe (argon2) et renvoie un JWT RS256 signé.
2. `POST /api/ledger/entries` → création d'une écriture (scopée au tenant),
   invalidation du solde en cache.
3. `POST /api/ledger/reconcile` → `ledger` crée un *run* et publie un job sur NATS.
   Le `worker` le consomme, rapproche les écritures, met à jour les compteurs.
4. `POST /api/reporting/reports` → `reporting` enregistre la demande et publie un
   job ; le `worker` génère le résultat (JSON) et le persiste ; le frontend
   *poll* le statut jusqu'à `ready`.

---

## 4. Référence API (via la gateway, préfixe `/api`)

**Authentification**
- `POST /api/auth/login` — `{tenant, username, password}` → `{access_token, token_type, expires_in}`
- `GET /api/auth/userinfo` — (Bearer) → claims
- `GET /api/auth/.well-known/jwks.json` *(exposé directement par `auth`)*

**Ledger** *(Bearer requis)*
- `GET /api/ledger/accounts`
- `GET /api/ledger/entries?status=&limit=`
- `POST /api/ledger/entries` — `{account_code, amount_cents, side, currency?, reference?, external_ref?}`
- `GET /api/ledger/accounts/{code}/balance`
- `POST /api/ledger/reconcile` → `{run_id, status}`
- `GET /api/ledger/reconcile/{run_id}`

**Reporting** *(Bearer requis)*
- `POST /api/reporting/reports` — `{type, period?}` (`balance_summary` | `reconciliation_audit` | `entries_export`)
- `GET /api/reporting/reports`
- `GET /api/reporting/reports/{report_id}`

**Transverses (chaque service)** : `GET /healthz`, `GET /readyz`, `GET /metrics`,
`GET /docs` (OpenAPI).

---

## 5. Exécution locale (pour valider l'app avant industrialisation)

> Prérequis : Docker + Docker Compose. Le `docker-compose.yml` est un outil de
> **développement** (il embarque Postgres, Redis, NATS, Jaeger, Prometheus) ;
> ce n'est pas une cible de production.

```bash
make up        # build + démarrage de toute la plateforme
# Frontend          → http://localhost:8080   (acme/alice, mot de passe demo-password)
# API (gateway)     → http://localhost:8081
# Traces  (Jaeger)  → http://localhost:16686
# Métriques (Prom.) → http://localhost:9090

make logs SVC=worker   # suivre un service
make clean             # tout arrêter + RAZ des volumes
```

Scaler le worker (partage de charge via *queue group* NATS) :
```bash
docker compose up -d --scale worker=3
```

Vérification statique du code (imports + montage des apps, sans dépendances) :
```bash
make smoke
```

### Comptes de démonstration

| Tenant  | Identifiant | Rôles        |
|---------|-------------|--------------|
| acme    | alice       | admin, user  |
| acme    | bob         | user         |
| globex  | carol       | user         |

Mot de passe commun : `demo-password` (amorçage de test, désactivable via
`DEMO_SEED=false`).

---

## 6. Configuration

Toutes les variables sont documentées dans [`.env.example`](.env.example).
Points clés :

- **Zéro secret en clair** : la clé privée JWT et les URL avec identifiants sont
  fournies par l'environnement. En production, elles proviennent du gestionnaire
  de secrets de la plateforme. En dev, si `JWT_PRIVATE_KEY_PEM` est absente, une
  clé éphémère est générée au démarrage.
- `OTEL_EXPORTER_OTLP_ENDPOINT` vide ⇒ le service tourne sans export de traces.

---

## 7. Observabilité

- **Logs** : JSON structuré sur stdout, avec `trace_id`, `request_id`, `tenant`.
- **Métriques** : `/metrics` par service (latence et volume HTTP, jobs traités,
  profondeur de file estimée…).
- **Traces** : OpenTelemetry, export OTLP/HTTP, propagation W3C `traceparent` y
  compris dans les en-têtes des messages NATS → une requête est traçable du
  navigateur jusqu'au worker.

---
