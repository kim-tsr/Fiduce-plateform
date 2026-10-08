#!/usr/bin/env bash
# Test de bout en bout : parcours métier complet à travers la gateway.
set -euo pipefail
API="${API:-http://localhost:8081}/api"

wait_for() {  # attend qu'une URL réponde 200
  for _ in $(seq 1 60); do curl -fsS "$1" >/dev/null 2>&1 && return 0; sleep 2; done
  echo "Timeout : $1" >&2; return 1
}
poll() {  # interroge une ressource jusqu'à obtenir le statut attendu
  for _ in $(seq 1 30); do
    s=$(curl -fsS -H "$AUTH" "$1" | jq -r .status)
    [ "$s" = "$2" ] && return 0; sleep 1
  done
  echo "Statut '$2' jamais atteint pour $1 (dernier : $s)" >&2; return 1
}

wait_for "${API%/api}/readyz"

echo "1. Connexion"
TOKEN=$(curl -fsS -X POST "$API/auth/login" -H 'Content-Type: application/json' \
  -d '{"tenant":"acme","username":"alice","password":"demo-password"}' | jq -er .access_token)
AUTH="Authorization: Bearer $TOKEN"

echo "2. Écriture comptable"
curl -fsS -X POST "$API/ledger/entries" -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"account_code":"1000","amount_cents":12345,"side":"debit","external_ref":"BANK-E2E"}' >/dev/null

echo "3. Solde"
curl -fsS -H "$AUTH" "$API/ledger/accounts/1000/balance" | jq -e '.balance_cents != null' >/dev/null

echo "4. Réconciliation asynchrone (ledger → NATS → worker)"
RUN=$(curl -fsS -X POST -H "$AUTH" "$API/ledger/reconcile" | jq -er .run_id)
poll "$API/ledger/reconcile/$RUN" completed

echo "5. Rapport asynchrone (reporting → NATS → worker)"
REP=$(curl -fsS -X POST "$API/reporting/reports" -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"type":"balance_summary"}' | jq -er .report_id)
poll "$API/reporting/reports/$REP" ready

echo "6. Isolation multi-tenant : globex ne voit pas l'écriture d'acme"
T2=$(curl -fsS -X POST "$API/auth/login" -H 'Content-Type: application/json' \
  -d '{"tenant":"globex","username":"carol","password":"demo-password"}' | jq -er .access_token)
curl -fsS -H "Authorization: Bearer $T2" "$API/ledger/entries" \
  | jq -e 'all(.[]; .external_ref != "BANK-E2E")' >/dev/null
code=$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $T2" "$API/ledger/reconcile/$RUN")
[ "$code" = "404" ] || { echo "globex accède au run d'acme (HTTP $code)" >&2; exit 1; }

echo "E2E OK"
