export async function fetchUser() {
  const response = await fetch('https://api.example.com/me');
  return response.json();
}
