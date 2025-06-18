// src/middleware/auth.ts

import { Request, Response, NextFunction } from 'express';
import { users } from '../data/users';

export function authMiddleware(req: any, res: any, next: NextFunction) {
  // 1) Allow CORS preflight requests through
  if (req.method === 'OPTIONS') {
    return next();
  }

  // 2) Then do your usual auth checks
  const authHeader = req.headers.authorization;
  if (!authHeader) {
    return res.status(401).json({ message: 'Missing Authorization Header' });
  }

  const [username, password] = Buffer.from(authHeader, 'base64').toString().split(':');
  const user = users.find(u => u.username === username && u.password === password);
  if (!user) {
    return res.status(401).json({ message: 'Invalid credentials' });
  }

  // 3) Attach user and proceed
  req.user = user;
  next();
}
