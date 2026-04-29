// Repro for promise-unhandled-rejection.
//
// `fetchUserName` returns a Promise chain with no `.catch(...)`. When the
// underlying fetch rejects (network error, 4xx, 5xx, JSON parse failure),
// the rejection escapes the chain. Under Node, the process emits:
//
//   UnhandledPromiseRejection: ...
//   (node:1234) UnhandledPromiseRejectionWarning
//
// In a browser console it surfaces as:
//
//   Uncaught (in promise) TypeError: ...
//
// The fix is to terminate the chain with `.catch(...)` (or wrap the
// awaited call in try/catch) so the failure is observed at a known
// boundary instead of silently corrupting downstream state.

export function fetchUserName(id) {
  return fetch(`/api/users/${id}`)
    .then((response) => response.json())
    .then((data) => data.name);
}
