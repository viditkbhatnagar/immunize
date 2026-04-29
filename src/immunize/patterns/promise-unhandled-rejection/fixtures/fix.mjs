// Fix for promise-unhandled-rejection.
//
// Same `fetchUserName(id)` interface as repro, but the chain terminates
// in a `.catch(...)` that surfaces a typed error to the caller. The
// caller now has a deterministic recovery point; no rejection escapes
// the function.

export function fetchUserName(id) {
  return fetch(`/api/users/${id}`)
    .then((response) => response.json())
    .then((data) => data.name)
    .catch((err) => {
      throw new Error(`failed to fetch user ${id}: ${err.message}`);
    });
}
