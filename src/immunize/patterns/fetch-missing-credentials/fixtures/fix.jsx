export async function fetchUser() {
  const response = await fetch('https://api.example.com/me', {
    credentials: 'include',
  });
  return response.json();
}
