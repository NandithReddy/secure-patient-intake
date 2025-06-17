import { Request, Response, NextFunction } from 'express';
import { AuthRequest } from './auth';

export function authorizeRole(role: 'admin' | 'clinician') {
  return (req: AuthRequest, res: Response, next: NextFunction) => {
    if (req.user?.role !== role) {
      return res.status(403).json({ message: 'Forbidden' });
    }
    next();
  };
}

