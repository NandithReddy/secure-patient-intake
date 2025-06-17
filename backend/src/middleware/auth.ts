import { Request, Response, NextFunction } from 'express';
import { users } from '../data/users';

export function authMiddleware(req: Request, res: Response, next: NextFunction): void {
  const authHeader = req.headers.authorization;

  if (!authHeader) {
    res.status(401).json({ message: 'Missing Authorization Header' });
    return;
  }

  const [username, password] = Buffer.from(authHeader, 'base64').toString().split(':');
  const user = users.find(u => u.username === username && u.password === password);

  if (!user) {
    res.status(401).json({ message: 'Invalid credentials' });
    return;
  }

  // Attach user to request object as any (simplifies types)
  (req as any).user = user;

  next();
}

