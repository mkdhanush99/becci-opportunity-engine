# BECCI Public Website — Frontend Integration Guide

This guide details how the React frontend at `https://preview.becci.in` / `https://becci.in` connects to the deployed backend at `https://becci-api.azurewebsites.net`.

---

## 1. Environment Configuration

Add the backend URL to your `.env` file in the frontend project:

```env
VITE_API_BASE_URL=https://becci-api.azurewebsites.net
```

---

## 2. API Client Setup (Axios / Fetch)

```typescript
// src/api/client.ts
import axios from 'axios';

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || 'https://becci-api.azurewebsites.net',
  headers: {
    'Content-Type': 'application/json',
  },
});

// Attach JWT token for authenticated requests
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('becci_auth_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export default api;
```

---

## 3. Opportunity Explorer Implementation

```typescript
// Fetch opportunities with search and filtering
export async function fetchOpportunities(params: {
  category?: 'tender' | 'job' | 'funding';
  state?: string;
  q?: string;
  sector?: string;
  page?: number;
  pageSize?: number;
}) {
  const response = await api.get('/api/v1/opportunities', { params });
  return response.data; // { items: [...], total: 48, page: 1, page_size: 20 }
}
```

---

## 4. Government Schemes & Eligibility Check

```typescript
// Strict territorial scheme filter: Telangana or Andhra Pradesh
export async function fetchSchemes(state: 'Telangana' | 'Andhra Pradesh') {
  const response = await api.get('/api/v1/schemes', { params: { state } });
  return response.data;
}

// Advisory eligibility assessment
export async function checkSchemeEligibility(schemeId: string, assessment: {
  domicile_state: string;
  caste_community: string;
  is_non_creamy_layer: boolean;
  annual_family_income: number;
  age: number;
  gender: string;
}) {
  const response = await api.post(`/api/v1/schemes/${schemeId}/check-eligibility`, assessment);
  return response.data;
}
```

---

## 5. Member Recommendations

```typescript
export async function fetchMemberRecommendations() {
  const response = await api.get('/api/v1/recommendations');
  return response.data; // List of matched opportunities with match_score and match_reasons
}
```
