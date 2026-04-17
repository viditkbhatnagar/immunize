---
name: immunize-react-hook-missing-dep
description: Use when writing React components with useEffect or useCallback to ensure every reactive value referenced in the hook body appears in the dependency array.
---

# react-hook-missing-dep

When you write `useEffect` or `useCallback`, list every reactive value the
body reads in the dependency array. A "reactive value" is anything whose
reference can change between renders: props, state from
`useState`/`useReducer`, context values, and other hook results.

Declare the dep even if it feels obvious that the value is stable. React's
exhaustive-deps lint catches this, and relying on it slows you down; write
the array correctly the first time.

## Example

Wrong — `count` changes but is missing from the deps array, so the effect
uses the stale value from the first render:

```jsx
function Counter() {
  const [count, setCount] = useState(0);

  useEffect(() => {
    document.title = `Count: ${count}`;
  }, []);

  return <button onClick={() => setCount(count + 1)}>{count}</button>;
}
```

Right — `count` is declared, so the effect re-runs when it changes:

```jsx
function Counter() {
  const [count, setCount] = useState(0);

  useEffect(() => {
    document.title = `Count: ${count}`;
  }, [count]);

  return <button onClick={() => setCount(count + 1)}>{count}</button>;
}
```

## When an empty deps array is correct

Only when the effect genuinely runs once and the body references NO
reactive values. If you write `[]` to "silence the warning," either move
the stable reference outside the component or wrap the function in
`useCallback` with its own correct deps. Do not paper over missing deps
with `eslint-disable` comments.

## Immunity note

This pattern is a source-level check, not a runtime behavioral test. The
verification asserts the deps array lists every `useState` identifier the
hook body references. It cannot catch every stale-closure bug (some are
semantic), but it prevents the most common shape the AI produces.
