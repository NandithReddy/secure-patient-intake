export interface User {
  id: number;
  username: string;
  password: string;
  role: 'admin' | 'clinician';
}

export const users: User[] = [
  { id: 1, username: 'admin', password: 'admin123', role: 'admin' },
  { id: 2, username: 'clinician', password: 'clinician123', role: 'clinician' }
];

